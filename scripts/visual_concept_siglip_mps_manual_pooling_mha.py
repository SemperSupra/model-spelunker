#!/usr/bin/env python3
"""Close the SigLIP MPS residual with an explicit vision pooling MHA treatment."""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import math
import os
import types
from pathlib import Path

import requests
import torch
import torch.nn.functional as F
import transformers
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def metrics(a: torch.Tensor, b: torch.Tensor) -> dict:
    x=a.detach().float().cpu()
    y=b.detach().float().cpu()
    if x.shape != y.shape:
        return {"shape_match":False,"a_shape":list(x.shape),"b_shape":list(y.shape)}
    xf=x.reshape(-1); yf=y.reshape(-1)
    denom=float(torch.linalg.vector_norm(xf).item())
    return {
        "shape_match":True,
        "shape":list(x.shape),
        "cosine":float(F.cosine_similarity(xf.unsqueeze(0),yf.unsqueeze(0)).item()),
        "max_abs":float((x-y).abs().max().item()),
        "mean_abs":float((x-y).abs().mean().item()),
        "relative_l2":float(torch.linalg.vector_norm(xf-yf).item()/denom) if denom else None,
        "a_finite":bool(torch.isfinite(xf).all().item()),
        "b_finite":bool(torch.isfinite(yf).all().item()),
    }


def patch_all_linears(model: torch.nn.Module) -> list[str]:
    patched=[]
    for name,module in model.named_modules():
        if not isinstance(module,torch.nn.Linear):
            continue
        def matmul_forward(self,input):
            out=torch.matmul(input,self.weight.transpose(-1,-2))
            if self.bias is not None:
                out=out+self.bias
            return out
        module.forward=types.MethodType(matmul_forward,module)
        patched.append(name)
    return patched


def patch_vision_pooling_mha(model: torch.nn.Module) -> str:
    mha=model.vision_model.head.attention
    if not isinstance(mha,torch.nn.MultiheadAttention):
        raise RuntimeError(f"unexpected pooling attention type: {type(mha)}")
    if not mha.batch_first:
        raise RuntimeError("expected batch_first pooling MHA")
    if not getattr(mha,"_qkv_same_embed_dim",False):
        raise RuntimeError("expected shared q/k/v embed dim")

    def manual_forward(
        self,
        query,
        key,
        value,
        key_padding_mask=None,
        need_weights=True,
        attn_mask=None,
        average_attn_weights=True,
        is_causal=False,
    ):
        if key_padding_mask is not None or attn_mask is not None or is_causal:
            raise RuntimeError("manual SigLIP pooling MHA admits no masks/causal mode")
        if self.training and self.dropout:
            raise RuntimeError("manual SigLIP pooling MHA requires eval mode")

        embed_dim=self.embed_dim
        heads=self.num_heads
        head_dim=embed_dim//heads
        if head_dim*heads != embed_dim:
            raise RuntimeError("invalid head geometry")

        wq,wk,wv=self.in_proj_weight.chunk(3,dim=0)
        if self.in_proj_bias is None:
            bq=bk=bv=None
        else:
            bq,bk,bv=self.in_proj_bias.chunk(3,dim=0)

        def proj(x,w,b):
            out=torch.matmul(x,w.transpose(-1,-2))
            if b is not None:
                out=out+b
            return out

        q=proj(query,wq,bq)
        k=proj(key,wk,bk)
        v=proj(value,wv,bv)

        bsz,lq,_=q.shape
        lk=k.shape[1]
        q=q.view(bsz,lq,heads,head_dim).transpose(1,2)
        k=k.view(bsz,lk,heads,head_dim).transpose(1,2)
        v=v.view(bsz,lk,heads,head_dim).transpose(1,2)

        scores=torch.matmul(q,k.transpose(-1,-2))*(head_dim**-0.5)
        weights=torch.softmax(scores,dim=-1,dtype=torch.float32).to(q.dtype)
        attn=torch.matmul(weights,v)
        attn=attn.transpose(1,2).contiguous().view(bsz,lq,embed_dim)

        out=torch.matmul(attn,self.out_proj.weight.transpose(-1,-2))
        if self.out_proj.bias is not None:
            out=out+self.out_proj.bias

        if not need_weights:
            return out,None
        returned=weights.mean(dim=1) if average_attn_weights else weights
        return out,returned

    mha.forward=types.MethodType(manual_forward,mha)
    return "vision_model.head.attention"


def run(model_id,revision,inputs,device,*,global_linear=False,manual_pooler=False):
    model=AutoModelForZeroShotImageClassification.from_pretrained(model_id,revision=revision)
    linear_names=patch_all_linears(model) if global_linear else []
    pooler_name=patch_vision_pooling_mha(model) if manual_pooler else None
    model.to(device); model.eval()
    moved={k:(v.to(device) if isinstance(v,torch.Tensor) else v) for k,v in inputs.items()}
    with torch.inference_mode():
        out=model(**moved)
    if device=="mps":
        torch.mps.synchronize()
    result={
        "logits":out.logits_per_image.detach().float().cpu(),
        "image_embeds":out.image_embeds.detach().float().cpu(),
        "text_embeds":out.text_embeds.detach().float().cpu(),
        "placement":{
            "model_device":str(next(model.parameters()).device),
            "logits_device":str(out.logits_per_image.device),
        },
        "patched_linear_count":len(linear_names),
        "manual_pooler":pooler_name,
    }
    del out,moved,model
    gc.collect()
    if device=="mps":
        torch.mps.empty_cache()
    return result


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()

    if not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")!="0":
        raise SystemExit("fallback must remain disabled")

    cfg=json.loads(Path(a.config).read_text())
    if cfg.get("backend_family")!="siglip":
        raise SystemExit("this treatment is SigLIP-only")

    resp=requests.get(cfg["image_source"],timeout=45); resp.raise_for_status()
    raw=resp.content
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    labels=[str(x["label"]) for x in cfg["concepts"]]
    expected=list(cfg["expected_top_labels"])
    template=cfg.get("parameters",{}).get("prompt_template","a photo of a {}")
    prompts=[template.format(x) for x in labels]
    processor=AutoProcessor.from_pretrained(cfg["model_id"],revision=cfg.get("model_revision"))
    inputs=processor(
        text=prompts,images=image,return_tensors="pt",
        padding=cfg.get("parameters",{}).get("text_padding",True),
    )

    baseline=run(cfg["model_id"],cfg.get("model_revision"),inputs,"cpu")
    cpu_manual=run(
        cfg["model_id"],cfg.get("model_revision"),inputs,"cpu",
        global_linear=True,manual_pooler=True,
    )
    mps_manual=run(
        cfg["model_id"],cfg.get("model_revision"),inputs,"mps",
        global_linear=True,manual_pooler=True,
    )

    def ranking(x):
        return [labels[i] for i in torch.argsort(x[0],descending=True).tolist()]

    base_rank=ranking(baseline["logits"])
    cpu_manual_rank=ranking(cpu_manual["logits"])
    mps_manual_rank=ranking(mps_manual["logits"])

    cpu_control={
        "logits":metrics(baseline["logits"],cpu_manual["logits"]),
        "image_embeds":metrics(baseline["image_embeds"],cpu_manual["image_embeds"]),
        "text_embeds":metrics(baseline["text_embeds"],cpu_manual["text_embeds"]),
        "ranking_match":cpu_manual_rank==base_rank,
    }
    mps_result={
        "logits":metrics(baseline["logits"],mps_manual["logits"]),
        "image_embeds":metrics(baseline["image_embeds"],mps_manual["image_embeds"]),
        "text_embeds":metrics(baseline["text_embeds"],mps_manual["text_embeds"]),
        "ranking_match":mps_manual_rank==base_rank,
    }

    receipt={
        "schema":"visual-concept-siglip-mps-manual-pooling-mha/v1",
        "model":{
            "family":cfg["backend_family"],
            "id":cfg["model_id"],
            "revision":cfg.get("model_revision"),
        },
        "fixture":{
            "image_sha256":sha256_bytes(raw),
            "labels":labels,
            "expected_top_labels":expected,
        },
        "runtime":{
            "torch":torch.__version__,
            "transformers":transformers.__version__,
            "mps_fallback_env":os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        },
        "treatment":{
            "global_linear_matmul_bias":True,
            "manual_vision_pooling_mha":True,
            "manual_mha_projection":"packed in_proj q/k/v split + explicit matmul/bias",
            "manual_mha_attention":"scaled qk -> fp32 softmax -> av -> explicit out matmul/bias",
            "patched_linear_count":mps_manual["patched_linear_count"],
        },
        "placements":{
            "baseline_cpu":baseline["placement"],
            "manual_cpu":cpu_manual["placement"],
            "manual_mps":mps_manual["placement"],
        },
        "rankings":{
            "baseline_cpu":base_rank,
            "manual_cpu":cpu_manual_rank,
            "manual_mps":mps_manual_rank,
        },
        "cpu_manual_equivalence":cpu_control,
        "cpu_vs_manual_mps":mps_result,
        "oracle":{
            "baseline_cpu_pass":base_rank[0] in expected,
            "cpu_manual_top1_pass":cpu_manual_rank[0] in expected,
            "cpu_manual_full_ranking_match":cpu_manual_rank==base_rank,
            "manual_mps_top1_pass":mps_manual_rank[0] in expected,
            "manual_mps_full_ranking_match":mps_manual_rank==base_rank,
        },
    }

    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "rankings":receipt["rankings"],
        "cpu_manual_equivalence":receipt["cpu_manual_equivalence"],
        "cpu_vs_manual_mps":receipt["cpu_vs_manual_mps"],
        "oracle":receipt["oracle"],
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
