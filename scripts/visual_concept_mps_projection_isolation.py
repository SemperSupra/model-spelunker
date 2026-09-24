#!/usr/bin/env python3
"""Isolate first-block attention projection CPU-vs-MPS divergence."""
from __future__ import annotations

import argparse
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


def sha_tensor(t: torch.Tensor | None) -> str | None:
    if t is None:
        return None
    x=t.detach().cpu().contiguous()
    return hashlib.sha256(x.numpy().tobytes()).hexdigest()


def first_tensor(value: Any) -> torch.Tensor | None:
    if isinstance(value,torch.Tensor):
        return value
    if isinstance(value,(tuple,list)):
        for item in value:
            found=first_tensor(item)
            if found is not None:
                return found
    return None


def compare(a:torch.Tensor,b:torch.Tensor)->dict[str,Any]:
    x=a.detach().float().cpu()
    y=b.detach().float().cpu()
    if x.shape!=y.shape:
        return {"shape_match":False,"a_shape":list(x.shape),"b_shape":list(y.shape)}
    xf=x.reshape(-1);yf=y.reshape(-1)
    denom=float(torch.linalg.vector_norm(xf).item())
    return {
        "shape_match":True,
        "shape":list(x.shape),
        "cosine":float(F.cosine_similarity(xf.unsqueeze(0),yf.unsqueeze(0)).item()),
        "max_abs":float((x-y).abs().max().item()),
        "mean_abs":float((x-y).abs().mean().item()),
        "relative_l2":float(torch.linalg.vector_norm(xf-yf).item()/denom) if denom else None,
    }


def resolve(model:torch.nn.Module,tower:str)->dict[str,str]:
    names=dict(model.named_modules())
    base=next(
        (n for n in names if n.endswith(f"{tower}_model.encoder.layers.0")),
        None,
    )
    if base is None:
        raise RuntimeError(f"no {tower} block 0")
    ln=next((n for n in names if n==base+".layer_norm1"),None)
    if ln is None:
        raise RuntimeError(f"no {tower} layer_norm1")
    projections={}
    for kind in ("q_proj","k_proj","v_proj"):
        name=next((n for n in names if n==base+".self_attn."+kind),None)
        if name is None:
            raise RuntimeError(f"no {tower} {kind}")
        projections[kind]=name
    return {"layer_norm1":ln,**projections}


def capture_forward(model,inputs,names:dict[str,dict[str,str]],device:str)->dict[str,Any]:
    modules=dict(model.named_modules())
    captured={}
    handles=[]
    for tower,probes in names.items():
        for kind,name in probes.items():
            def hook(_module,_inputs,output,*,key=f"{tower}.{kind}"):
                tensor=first_tensor(output)
                if tensor is None:
                    raise RuntimeError(f"{key} emitted no tensor")
                captured[key]=tensor.detach().float().cpu()
            handles.append(modules[name].register_forward_hook(hook))
    moved={k:(v.to(device) if isinstance(v,torch.Tensor) else v) for k,v in inputs.items()}
    with torch.inference_mode():
        outputs=model(**moved)
    if device=="mps":
        torch.mps.synchronize()
    for h in handles:
        h.remove()
    expected={f"{tower}.{kind}" for tower,p in names.items() for kind in p}
    if set(captured)!=expected:
        raise RuntimeError(f"missing captures: {sorted(expected-set(captured))}")
    return {
        "captured":captured,
        "logits":outputs.logits_per_image.detach().float().cpu(),
        "logits_device":str(outputs.logits_per_image.device),
    }


def tensor_layout(t:torch.Tensor)->dict[str,Any]:
    x=t.detach()
    return {
        "shape":list(x.shape),
        "stride":list(x.stride()),
        "dtype":str(x.dtype),
        "contiguous":bool(x.is_contiguous()),
        "sha256":sha_tensor(x),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    if not torch.backends.mps.is_available():
        raise SystemExit("MPS unavailable")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")!="0":
        raise SystemExit("fallback must remain disabled")

    cfg=json.loads(Path(args.config).read_text())
    raw=requests.get(cfg["image_source"],timeout=45).content
    image=Image.open(io.BytesIO(raw)).convert("RGB")
    labels=[str(x["label"]) for x in cfg["concepts"]]
    template=cfg.get("parameters",{}).get("prompt_template","a photo of a {}")
    prompts=[template.format(x) for x in labels]
    processor=AutoProcessor.from_pretrained(cfg["model_id"],revision=cfg.get("model_revision"))
    inputs=processor(
        text=prompts,
        images=image,
        return_tensors="pt",
        padding=cfg.get("parameters",{}).get("text_padding",True),
    )

    model=AutoModelForZeroShotImageClassification.from_pretrained(
        cfg["model_id"],revision=cfg.get("model_revision")
    )
    model.eval()
    names={tower:resolve(model,tower) for tower in ("vision","text")}
    modules=dict(model.named_modules())

    cpu_parameters={}
    for tower in ("vision","text"):
        cpu_parameters[tower]={}
        for kind in ("q_proj","k_proj","v_proj"):
            module=modules[names[tower][kind]]
            cpu_parameters[tower][kind]={
                "weight":module.weight.detach().cpu().clone(),
                "bias":module.bias.detach().cpu().clone() if module.bias is not None else None,
            }

    cpu=capture_forward(model,inputs,names,"cpu")

    # Move the exact same loaded model to MPS: model identity/parameters are held constant.
    model.to("mps")
    mps=capture_forward(model,inputs,names,"mps")
    modules=dict(model.named_modules())

    result_towers={}
    for tower in ("vision","text"):
        ln_cpu=cpu["captured"][f"{tower}.layer_norm1"]
        ln_mps_native=mps["captured"][f"{tower}.layer_norm1"]
        projection_results={}
        for kind in ("q_proj","k_proj","v_proj"):
            module=modules[names[tower][kind]]
            w_after=module.weight.detach().cpu()
            b_after=module.bias.detach().cpu() if module.bias is not None else None
            w_cpu=cpu_parameters[tower][kind]["weight"]
            b_cpu=cpu_parameters[tower][kind]["bias"]
            native_cpu=cpu["captured"][f"{tower}.{kind}"]
            native_mps=mps["captured"][f"{tower}.{kind}"]

            cpu_from_roundtrip=F.linear(ln_cpu,w_after,b_after)
            with torch.inference_mode():
                explicit_linear=F.linear(
                    ln_cpu.to("mps"),
                    w_cpu.to("mps"),
                    b_cpu.to("mps") if b_cpu is not None else None,
                )
                explicit_matmul=torch.matmul(
                    ln_cpu.to("mps"),
                    w_cpu.to("mps").transpose(-1,-2),
                )
                if b_cpu is not None:
                    explicit_matmul=explicit_matmul+b_cpu.to("mps")
                torch.mps.synchronize()
            explicit_linear=explicit_linear.detach().float().cpu()
            explicit_matmul=explicit_matmul.detach().float().cpu()

            projection_results[kind]={
                "weight_cpu":tensor_layout(w_cpu),
                "weight_after_mps_roundtrip":tensor_layout(w_after),
                "weight_roundtrip_delta":compare(w_cpu,w_after),
                "bias_cpu":tensor_layout(b_cpu) if b_cpu is not None else None,
                "bias_after_mps_roundtrip":tensor_layout(b_after) if b_after is not None else None,
                "bias_roundtrip_delta":compare(b_cpu,b_after) if b_cpu is not None else None,
                "native_cpu_vs_native_mps":compare(native_cpu,native_mps),
                "native_cpu_vs_cpu_using_roundtripped_mps_weights":compare(native_cpu,cpu_from_roundtrip),
                "native_cpu_vs_explicit_mps_linear_same_input_weights":compare(native_cpu,explicit_linear),
                "native_cpu_vs_explicit_mps_matmul_same_input_weights":compare(native_cpu,explicit_matmul),
                "explicit_mps_linear_vs_explicit_mps_matmul":compare(explicit_linear,explicit_matmul),
            }
        result_towers[tower]={
            "layer_norm_input_layout":tensor_layout(ln_cpu),
            "layer_norm_cpu_vs_native_mps":compare(ln_cpu,ln_mps_native),
            "projections":projection_results,
        }

    receipt={
        "schema":"visual-concept-mps-projection-isolation/v1",
        "model":{"family":cfg["backend_family"],"id":cfg["model_id"],"revision":cfg.get("model_revision")},
        "runtime":{"torch":torch.__version__,"transformers":transformers.__version__,"mps_fallback_env":os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")},
        "rankings":{
            "cpu":[labels[i] for i in torch.argsort(cpu["logits"][0],descending=True).tolist()],
            "mps":[labels[i] for i in torch.argsort(mps["logits"][0],descending=True).tolist()],
        },
        "towers":result_towers,
    }
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    summary={}
    for tower in ("vision","text"):
        summary[tower]={}
        for kind,row in result_towers[tower]["projections"].items():
            summary[tower][kind]={
                "weight_max_abs":row["weight_roundtrip_delta"]["max_abs"],
                "native_mps_rel_l2":row["native_cpu_vs_native_mps"]["relative_l2"],
                "explicit_mps_linear_rel_l2":row["native_cpu_vs_explicit_mps_linear_same_input_weights"]["relative_l2"],
                "explicit_mps_matmul_rel_l2":row["native_cpu_vs_explicit_mps_matmul_same_input_weights"]["relative_l2"],
            }
    print(json.dumps(summary,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
