#!/usr/bin/env python3
"""Differential CPU-vs-MPS diagnostic for the real Visual Concept Worker workload."""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

import requests
import torch
import torch.nn.functional as F
import transformers
from PIL import Image
from transformers import AutoModelForZeroShotImageClassification, AutoProcessor


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tensor_metrics(cpu: torch.Tensor, other: torch.Tensor) -> dict[str, Any]:
    a=cpu.detach().float().cpu()
    b=other.detach().float().cpu()
    if a.shape != b.shape:
        return {"shape_match":False,"cpu_shape":list(a.shape),"mps_shape":list(b.shape)}
    af=a.reshape(-1)
    bf=b.reshape(-1)
    denom=float(torch.linalg.vector_norm(af).item())
    cosine=float(F.cosine_similarity(af.unsqueeze(0),bf.unsqueeze(0)).item()) if af.numel() else None
    return {
        "shape_match":True,
        "shape":list(a.shape),
        "cosine":cosine,
        "max_abs":float((a-b).abs().max().item()) if a.numel() else 0.0,
        "mean_abs":float((a-b).abs().mean().item()) if a.numel() else 0.0,
        "relative_l2":float(torch.linalg.vector_norm(af-bf).item()/denom) if denom else None,
    }


def row_cosines(cpu: torch.Tensor, other: torch.Tensor) -> list[float]:
    a=cpu.detach().float().cpu()
    b=other.detach().float().cpu()
    if a.ndim != 2 or a.shape != b.shape:
        return []
    return [float(x) for x in F.cosine_similarity(a,b,dim=-1).tolist()]


def model_scalars(model) -> dict[str, float | None]:
    out: dict[str,float|None]={}
    raw_scale=getattr(model,"logit_scale",None)
    raw_bias=getattr(model,"logit_bias",None)
    if raw_scale is not None:
        value=raw_scale.detach().float().cpu()
        out["logit_scale_raw"]=float(value.item())
        out["logit_scale_exp"]=float(value.exp().item())
    else:
        out["logit_scale_raw"]=None
        out["logit_scale_exp"]=None
    if raw_bias is not None:
        value=raw_bias.detach().float().cpu()
        out["logit_bias"]=float(value.item())
    else:
        out["logit_bias"]=None
    return out


def run_model(model_id: str, revision: str | None, inputs_cpu: dict[str,Any], device: str):
    model=AutoModelForZeroShotImageClassification.from_pretrained(model_id,revision=revision)
    model.to(device)
    model.eval()
    inputs={
        key:value.to(device) if isinstance(value,torch.Tensor) else value
        for key,value in inputs_cpu.items()
    }
    with torch.inference_mode():
        outputs=model(**inputs)
    logits=outputs.logits_per_image.detach().float().cpu()
    image=getattr(outputs,"image_embeds",None)
    text=getattr(outputs,"text_embeds",None)
    if image is None or text is None:
        raise RuntimeError("model output did not expose image_embeds/text_embeds for differential diagnosis")
    image=image.detach().float().cpu()
    text=text.detach().float().cpu()
    scalars=model_scalars(model)
    placement={
        "requested_device":device,
        "model_device":str(next(model.parameters()).device),
        "logits_device":str(outputs.logits_per_image.device),
    }
    del outputs, inputs, model
    gc.collect()
    if device=="mps":
        torch.mps.synchronize()
        torch.mps.empty_cache()
    return {
        "logits":logits,
        "image_embeds":image,
        "text_embeds":text,
        "scalars":scalars,
        "placement":placement,
    }


def recompose(run: dict[str,Any]) -> torch.Tensor | None:
    scale=run["scalars"].get("logit_scale_exp")
    if scale is None:
        return None
    image=run["image_embeds"]
    text=run["text_embeds"]
    # HF CLIP/SigLIP outputs expose normalized embeddings. Both compute a text-image
    # dot product scaled by exp(logit_scale); SigLIP may also add logit_bias.
    logits_text=text @ image.T
    logits_text=logits_text*float(scale)
    bias=run["scalars"].get("logit_bias")
    if bias is not None:
        logits_text=logits_text+float(bias)
    return logits_text.T


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")!="0":
        raise SystemExit("diagnostic requires PYTORCH_ENABLE_MPS_FALLBACK=0")

    cfg=json.loads(Path(args.config).read_text(encoding="utf-8"))
    response=requests.get(cfg["image_source"],timeout=45)
    response.raise_for_status()
    raw=response.content
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    concepts=cfg["concepts"]
    labels=[str(x["label"]) for x in concepts]
    template=cfg.get("parameters",{}).get("prompt_template","a photo of a {}")
    prompts=[template.format(label) for label in labels]
    padding=cfg.get("parameters",{}).get("text_padding",True)

    processor=AutoProcessor.from_pretrained(cfg["model_id"],revision=cfg.get("model_revision"))
    inputs=processor(text=prompts,images=image,return_tensors="pt",padding=padding)

    cpu=run_model(cfg["model_id"],cfg.get("model_revision"),inputs,"cpu")
    mps=run_model(cfg["model_id"],cfg.get("model_revision"),inputs,"mps")

    cpu_logits=cpu["logits"][0]
    mps_logits=mps["logits"][0]
    cpu_rank=torch.argsort(cpu_logits,descending=True).tolist()
    mps_rank=torch.argsort(mps_logits,descending=True).tolist()

    cpu_recomposed=recompose(cpu)
    mps_recomposed=recompose(mps)

    receipt={
        "schema":"visual-concept-mps-differential/v1",
        "model":{
            "family":cfg["backend_family"],
            "id":cfg["model_id"],
            "revision":cfg.get("model_revision"),
        },
        "fixture":{
            "image_sha256":sha256_bytes(raw),
            "labels":labels,
            "prompts":prompts,
        },
        "runtime":{
            "torch":torch.__version__,
            "transformers":transformers.__version__,
            "mps_built":torch.backends.mps.is_built(),
            "mps_available":torch.backends.mps.is_available(),
            "mps_fallback_env":os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        },
        "placement":{"cpu":cpu["placement"],"mps":mps["placement"]},
        "rankings":{
            "cpu":[labels[i] for i in cpu_rank],
            "mps":[labels[i] for i in mps_rank],
        },
        "logits":{
            "cpu":[float(x) for x in cpu_logits.tolist()],
            "mps":[float(x) for x in mps_logits.tolist()],
            "metrics":tensor_metrics(cpu["logits"],mps["logits"]),
        },
        "image_embeddings":tensor_metrics(cpu["image_embeds"],mps["image_embeds"]),
        "text_embeddings":{
            "aggregate":tensor_metrics(cpu["text_embeds"],mps["text_embeds"]),
            "row_cosines":row_cosines(cpu["text_embeds"],mps["text_embeds"]),
        },
        "scalars":{"cpu":cpu["scalars"],"mps":mps["scalars"]},
        "recomposition":{},
    }
    if cpu_recomposed is not None:
        receipt["recomposition"]["cpu_vs_cpu_actual"]=tensor_metrics(cpu["logits"],cpu_recomposed)
    if mps_recomposed is not None:
        receipt["recomposition"]["mps_embeds_cpu_math_vs_mps_actual"]=tensor_metrics(mps["logits"],mps_recomposed)
        receipt["recomposition"]["cpu_vs_mps_embeds_cpu_math"]=tensor_metrics(cpu["logits"],mps_recomposed)

    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("VISUAL_MPS_DIAGNOSTIC="+str(out))
    print(json.dumps(receipt,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
