#!/usr/bin/env python3
"""Locate SigLIP residual CPU-vs-MPS divergence after patching every nn.Linear on MPS."""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import os
import re
import types
from pathlib import Path
from typing import Any

import requests
import torch
import torch.nn.functional as F
import transformers
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor

LAYER_RE = re.compile(r"^(?P<prefix>.*(?:vision_model|text_model)\.encoder\.layers\.)(?P<index>[0-9]+)$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def first_tensor(value: Any) -> torch.Tensor | None:
    if isinstance(value, torch.Tensor):
        return value
    if isinstance(value, (tuple, list)):
        for item in value:
            found = first_tensor(item)
            if found is not None:
                return found
    if hasattr(value, "to_tuple"):
        try:
            return first_tensor(value.to_tuple())
        except Exception:
            return None
    return None


def metrics(cpu: torch.Tensor, other: torch.Tensor) -> dict[str, Any]:
    a=cpu.detach().float().cpu()
    b=other.detach().float().cpu()
    if a.shape != b.shape:
        return {"shape_match":False,"cpu_shape":list(a.shape),"mps_shape":list(b.shape)}
    af=a.reshape(-1); bf=b.reshape(-1)
    if not af.numel():
        return {"shape_match":True,"shape":list(a.shape),"cosine":None,"max_abs":0.0,"mean_abs":0.0,"relative_l2":None,"cpu_finite":True,"mps_finite":True}
    denom=float(torch.linalg.vector_norm(af).item())
    return {
        "shape_match":True,
        "shape":list(a.shape),
        "cosine":float(F.cosine_similarity(af.unsqueeze(0),bf.unsqueeze(0)).item()),
        "max_abs":float((a-b).abs().max().item()),
        "mean_abs":float((a-b).abs().mean().item()),
        "relative_l2":float(torch.linalg.vector_norm(af-bf).item()/denom) if denom else None,
        "cpu_finite":bool(torch.isfinite(af).all().item()),
        "mps_finite":bool(torch.isfinite(bf).all().item()),
    }


def tower_layers(names: list[str], tower: str) -> list[tuple[int,str]]:
    needle=f"{tower}_model.encoder.layers."
    out=[]
    for name in names:
        if needle not in name:
            continue
        m=LAYER_RE.fullmatch(name)
        if m:
            out.append((int(m.group("index")),name))
    return sorted(set(out))


def select_probes(model: torch.nn.Module) -> dict[str,list[str]]:
    names=[name for name,_ in model.named_modules()]
    selected={"vision":[],"text":[]}
    for tower in ("vision","text"):
        emb=next((n for n in names if n.endswith(f"{tower}_model.embeddings")),None)
        if emb:
            selected[tower].append(emb)
        selected[tower].extend([name for _,name in tower_layers(names,tower)])
        for suffix in (
            f"{tower}_model.pre_layrnorm",
            f"{tower}_model.post_layernorm",
            f"{tower}_model.final_layer_norm",
        ):
            n=next((x for x in names if x.endswith(suffix)),None)
            if n and n not in selected[tower]:
                selected[tower].append(n)
    projections={
        "vision":("visual_projection","vision_projection"),
        "text":("text_projection",),
    }
    for tower,suffixes in projections.items():
        for suffix in suffixes:
            n=next((x for x in names if x.endswith(suffix)),None)
            if n and n not in selected[tower]:
                selected[tower].append(n)
    if not selected["vision"] or not selected["text"]:
        raise RuntimeError(f"missing tower probes: {selected}")
    return selected


def patch_all_linears(model: torch.nn.Module) -> list[str]:
    patched=[]
    for name,module in model.named_modules():
        if not isinstance(module,torch.nn.Linear):
            continue
        def matmul_forward(self,input):
            output=torch.matmul(input,self.weight.transpose(-1,-2))
            if self.bias is not None:
                output=output+self.bias
            return output
        module.forward=types.MethodType(matmul_forward,module)
        patched.append(name)
    return patched


def run_model(model_id:str,revision:str|None,inputs_cpu:dict[str,Any],device:str,*,expected_probes=None,patch_linears=False)->dict[str,Any]:
    model=AutoModelForZeroShotImageClassification.from_pretrained(model_id,revision=revision)
    patched=patch_all_linears(model) if patch_linears else []
    probes=select_probes(model)
    if expected_probes is not None and probes!=expected_probes:
        raise RuntimeError("probe topology differs between CPU and patched MPS")
    modules=dict(model.named_modules())
    captures={}
    handles=[]
    for name in probes["vision"]+probes["text"]:
        module=modules[name]
        def hook(_module,_inputs,output,*,probe=name):
            t=first_tensor(output)
            if t is None:
                raise RuntimeError(f"probe {probe} produced no tensor")
            captures[probe]=t.detach().float().cpu()
        handles.append(module.register_forward_hook(hook))
    model.to(device); model.eval()
    inputs={k:(v.to(device) if isinstance(v,torch.Tensor) else v) for k,v in inputs_cpu.items()}
    with torch.inference_mode():
        outputs=model(**inputs)
    if device=="mps":
        torch.mps.synchronize()
    logits=outputs.logits_per_image.detach().float().cpu()
    for h in handles:
        h.remove()
    missing=[n for n in probes["vision"]+probes["text"] if n not in captures]
    if missing:
        raise RuntimeError(f"missing probes: {missing}")
    placement={"model_device":str(next(model.parameters()).device),"logits_device":str(outputs.logits_per_image.device)}
    del outputs,inputs,model
    gc.collect()
    if device=="mps":
        torch.mps.empty_cache()
    return {"probes":probes,"captures":captures,"logits":logits,"placement":placement,"patched":patched}


def material(m:dict[str,Any])->bool:
    return (
        m.get("shape_match") is not True
        or m.get("cpu_finite") is False
        or m.get("mps_finite") is False
        or (m.get("cosine") is not None and m["cosine"]<0.999)
        or (m.get("relative_l2") is not None and m["relative_l2"]>0.01)
    )


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
        raise SystemExit("this diagnostic is SigLIP-only")
    response=requests.get(cfg["image_source"],timeout=45); response.raise_for_status()
    raw=response.content
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    labels=[str(x["label"]) for x in cfg["concepts"]]
    expected=list(cfg["expected_top_labels"])
    template=cfg.get("parameters",{}).get("prompt_template","a photo of a {}")
    prompts=[template.format(x) for x in labels]
    processor=AutoProcessor.from_pretrained(cfg["model_id"],revision=cfg.get("model_revision"))
    inputs=processor(text=prompts,images=image,return_tensors="pt",padding=cfg.get("parameters",{}).get("text_padding",True))

    cpu=run_model(cfg["model_id"],cfg.get("model_revision"),inputs,"cpu")
    patched=run_model(cfg["model_id"],cfg.get("model_revision"),inputs,"mps",expected_probes=cpu["probes"],patch_linears=True)

    towers={}
    for tower in ("vision","text"):
        stages=[]
        first=None
        for name in cpu["probes"][tower]:
            m=metrics(cpu["captures"][name],patched["captures"][name])
            stages.append({"name":name,"metrics":m})
            if first is None and material(m):
                first={"name":name,"cosine":m.get("cosine"),"relative_l2":m.get("relative_l2"),"max_abs":m.get("max_abs")}
        towers[tower]={"stages":stages,"first_material_divergence":first}

    def ranking(logits):
        return [labels[i] for i in torch.argsort(logits[0],descending=True).tolist()]
    cpu_rank=ranking(cpu["logits"])
    patched_rank=ranking(patched["logits"])
    receipt={
        "schema":"visual-concept-siglip-mps-global-linear-layerwise/v1",
        "model":{"family":cfg["backend_family"],"id":cfg["model_id"],"revision":cfg.get("model_revision")},
        "fixture":{"image_sha256":sha256_bytes(raw),"labels":labels,"expected_top_labels":expected},
        "runtime":{"torch":torch.__version__,"transformers":transformers.__version__,"mps_fallback_env":os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")},
        "placement":{"cpu":cpu["placement"],"patched_mps":patched["placement"]},
        "treatment":{"name":"mps-all-nn-linear-matmul-bias-v0","patched_linear_count":len(patched["patched"]),"provider_fallback":False},
        "rankings":{"cpu":cpu_rank,"patched_mps":patched_rank},
        "logits":metrics(cpu["logits"],patched["logits"]),
        "towers":towers,
        "oracle":{
            "cpu_control_pass":cpu_rank[0] in expected,
            "patched_mps_pass":patched_rank[0] in expected,
            "restored_cpu_top1":patched_rank[0]==cpu_rank[0],
            "restored_full_ranking":patched_rank==cpu_rank,
        },
        "threshold":{"cosine_lt":0.999,"relative_l2_gt":0.01,"role":"diagnostic only"},
    }
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "patched_linear_count":len(patched["patched"]),
        "rankings":receipt["rankings"],
        "first_material_divergence":{t:towers[t]["first_material_divergence"] for t in towers},
        "oracle":receipt["oracle"],
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
