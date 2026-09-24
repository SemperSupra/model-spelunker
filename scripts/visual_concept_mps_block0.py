#!/usr/bin/env python3
"""First-transformer-block CPU-vs-MPS sub-operation localization."""
from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import os
from collections import defaultdict
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


def metrics(a: torch.Tensor, b: torch.Tensor) -> dict[str, Any]:
    x=a.detach().float().cpu()
    y=b.detach().float().cpu()
    if x.shape != y.shape:
        return {"shape_match":False,"cpu_shape":list(x.shape),"mps_shape":list(y.shape)}
    xf=x.reshape(-1)
    yf=y.reshape(-1)
    if not xf.numel():
        return {"shape_match":True,"shape":list(x.shape),"cosine":None,"max_abs":0.0,"mean_abs":0.0,"relative_l2":None}
    denom=float(torch.linalg.vector_norm(xf).item())
    return {
        "shape_match":True,
        "shape":list(x.shape),
        "cosine":float(F.cosine_similarity(xf.unsqueeze(0),yf.unsqueeze(0)).item()),
        "max_abs":float((x-y).abs().max().item()),
        "mean_abs":float((x-y).abs().mean().item()),
        "relative_l2":float(torch.linalg.vector_norm(xf-yf).item()/denom) if denom else None,
        "cpu_finite":bool(torch.isfinite(xf).all().item()),
        "mps_finite":bool(torch.isfinite(yf).all().item()),
    }


def first_layer_prefix(model: torch.nn.Module, tower: str) -> str:
    needle=f"{tower}_model.encoder.layers.0"
    names=[name for name,_ in model.named_modules()]
    matches=[name for name in names if name.endswith(needle)]
    if len(matches)!=1:
        raise RuntimeError(f"expected one {tower} layer-0 module, got {matches}")
    return matches[0]


def interesting(name: str, module: torch.nn.Module, prefix: str) -> bool:
    if not name.startswith(prefix+"."):
        return False
    local=name[len(prefix)+1:]
    # Record leaf operations and semantically meaningful composite outputs.
    leaf=not any(True for _ in module.children())
    keywords=(
        "layer_norm","layernorm","self_attn","attention","q_proj","k_proj","v_proj",
        "out_proj","mlp","fc1","fc2","projection","activation","act",
    )
    return leaf or any(k in local.casefold() for k in keywords)


def run(model_id:str, revision:str|None, inputs_cpu:dict[str,Any], device:str, expected_names:dict[str,list[str]]|None=None)->dict[str,Any]:
    model=AutoModelForZeroShotImageClassification.from_pretrained(model_id,revision=revision)
    prefixes={tower:first_layer_prefix(model,tower) for tower in ("vision","text")}

    modules=dict(model.named_modules())
    selected={}
    for tower,prefix in prefixes.items():
        names=[name for name,module in modules.items() if interesting(name,module,prefix)]
        selected[tower]=names

    if expected_names is not None and selected != expected_names:
        raise RuntimeError("block-0 probe topology differs between device realizations")

    events=[]
    captures=defaultdict(list)
    handles=[]
    for tower in ("vision","text"):
        for name in selected[tower]:
            module=modules[name]
            def hook(_module,_inputs,output,*,probe=name,which=tower):
                tensor=first_tensor(output)
                if tensor is None:
                    return
                occurrence=len(captures[probe])
                cpu=tensor.detach().float().cpu()
                captures[probe].append(cpu)
                events.append({"tower":which,"name":probe,"occurrence":occurrence,"shape":list(cpu.shape)})
            handles.append(module.register_forward_hook(hook))

    model.to(device)
    model.eval()
    inputs={k:(v.to(device) if isinstance(v,torch.Tensor) else v) for k,v in inputs_cpu.items()}
    with torch.inference_mode():
        outputs=model(**inputs)
    logits=outputs.logits_per_image.detach().float().cpu()

    for h in handles:
        h.remove()
    placement={
        "model_device":str(next(model.parameters()).device),
        "logits_device":str(outputs.logits_per_image.device),
    }
    del outputs,inputs,model
    gc.collect()
    if device=="mps":
        torch.mps.synchronize()
        torch.mps.empty_cache()

    return {
        "selected":selected,
        "events":events,
        "captures":dict(captures),
        "logits":logits,
        "placement":placement,
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")!="0":
        raise SystemExit("fallback must remain disabled")

    cfg=json.loads(Path(args.config).read_text())
    response=requests.get(cfg["image_source"],timeout=45)
    response.raise_for_status()
    raw=response.content
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    labels=[str(x["label"]) for x in cfg["concepts"]]
    template=cfg.get("parameters",{}).get("prompt_template","a photo of a {}")
    prompts=[template.format(label) for label in labels]
    processor=AutoProcessor.from_pretrained(cfg["model_id"],revision=cfg.get("model_revision"))
    inputs=processor(
        text=prompts,
        images=image,
        return_tensors="pt",
        padding=cfg.get("parameters",{}).get("text_padding",True),
    )

    cpu=run(cfg["model_id"],cfg.get("model_revision"),inputs,"cpu")
    mps=run(cfg["model_id"],cfg.get("model_revision"),inputs,"mps",expected_names=cpu["selected"])

    if [(e["tower"],e["name"],e["occurrence"]) for e in cpu["events"]] != [(e["tower"],e["name"],e["occurrence"]) for e in mps["events"]]:
        raise RuntimeError("CPU/MPS block-0 execution event topology differs")

    event_results=[]
    first_by_tower={"vision":None,"text":None}
    for event in cpu["events"]:
        name=event["name"]; occurrence=event["occurrence"]; tower=event["tower"]
        result=metrics(cpu["captures"][name][occurrence],mps["captures"][name][occurrence])
        row={**event,"metrics":result}
        event_results.append(row)
        if first_by_tower[tower] is None:
            cosine=result.get("cosine")
            rel=result.get("relative_l2")
            materially=(
                result.get("shape_match") is not True
                or result.get("cpu_finite") is False
                or result.get("mps_finite") is False
                or (cosine is not None and cosine<0.999)
                or (rel is not None and rel>0.01)
            )
            if materially:
                first_by_tower[tower]={
                    "name":name,
                    "occurrence":occurrence,
                    "cosine":cosine,
                    "relative_l2":rel,
                    "max_abs":result.get("max_abs"),
                }

    cpu_logits=cpu["logits"][0];mps_logits=mps["logits"][0]
    receipt={
        "schema":"visual-concept-mps-block0/v1",
        "model":{"family":cfg["backend_family"],"id":cfg["model_id"],"revision":cfg.get("model_revision")},
        "fixture":{"image_sha256":sha256_bytes(raw),"labels":labels},
        "runtime":{
            "torch":torch.__version__,
            "transformers":transformers.__version__,
            "mps_fallback_env":os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"),
        },
        "placement":{"cpu":cpu["placement"],"mps":mps["placement"]},
        "rankings":{
            "cpu":[labels[i] for i in torch.argsort(cpu_logits,descending=True).tolist()],
            "mps":[labels[i] for i in torch.argsort(mps_logits,descending=True).tolist()],
        },
        "first_material_divergence":first_by_tower,
        "events":event_results,
        "threshold":{"cosine_lt":0.999,"relative_l2_gt":0.01,"role":"diagnostic only"},
    }
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print("VISUAL_MPS_BLOCK0="+str(out))
    print(json.dumps({
        "rankings":receipt["rankings"],
        "first_material_divergence":first_by_tower,
        "event_count":len(event_results),
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
