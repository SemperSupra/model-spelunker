#!/usr/bin/env python3
"""Bounded MLX-LM OpenAI tool-call preflight for the Mac actor crossover."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

MLX_LM_VERSION="0.31.3"
MODEL_REPO="mlx-community/Qwen3-0.6B-4bit"
MODEL_REVISION="73e3e38"
PORT=8080
SCHEMA="mlx-tool-call-preflight/v1"


def run(argv:list[str], timeout:int=300, cwd:str|None=None):
    try:
        cp=subprocess.run(argv,check=False,capture_output=True,text=True,timeout=timeout,cwd=cwd)
        return cp.returncode,cp.stdout.strip(),cp.stderr.strip()
    except (OSError,subprocess.SubprocessError) as exc:
        return None,"",f"{type(exc).__name__}: {exc}"


def get_json(url:str, timeout:float=5.0):
    with urllib.request.urlopen(url,timeout=timeout) as r:
        return json.load(r)


def post_json(url:str, payload:dict, timeout:float=120.0):
    body=json.dumps(payload).encode()
    req=urllib.request.Request(url,data=body,method="POST",headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.load(r)


def sha256_file(path:pathlib.Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--label",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    receipt={
        "schema":SCHEMA,
        "provenance":{
            "requested_label":args.label,
            "run_id":os.environ.get("GITHUB_RUN_ID",""),
            "run_attempt":os.environ.get("GITHUB_RUN_ATTEMPT",""),
            "workflow_sha":os.environ.get("GITHUB_SHA",""),
            "image_os":os.environ.get("ImageOS"),
            "image_version":os.environ.get("ImageVersion"),
        },
        "treatment":{
            "mlx_lm_version":MLX_LM_VERSION,
            "model_repo":MODEL_REPO,
            "requested_revision":MODEL_REVISION,
        },
        "classification":"INCONCLUSIVE",
        "reason":"",
        "warnings":[
            "structured tool-call preflight only; task competence is not inferred",
            "local loopback HTTP server is an execution adapter, not a network service dependency",
        ],
    }

    if sys.platform!="darwin" or os.uname().machine!="arm64":
        receipt["classification"]="SKIPPED_GUARDRAIL"
        receipt["reason"]="tool-call preflight requires ARM64 macOS"
    else:
        with tempfile.TemporaryDirectory(prefix="mlx-tool-preflight-") as td:
            root=pathlib.Path(td)
            venv=root/"venv"
            rc,out,err=run([sys.executable,"-m","venv",str(venv)],timeout=90)
            if rc!=0:
                receipt["classification"]="HARNESS_FAILURE"
                receipt["reason"]="venv creation failed"
            else:
                py=venv/"bin"/"python"
                rc,out,err=run([str(py),"-m","pip","install","--disable-pip-version-check","--no-cache-dir",
                                f"mlx-lm=={MLX_LM_VERSION}"],timeout=600)
                receipt["dependency_preparation"]={"exit_code":rc,"stdout":out[-2000:] or None,"stderr":err[-2500:] or None}
                if rc!=0:
                    receipt["classification"]="ENVIRONMENT_FAILURE"
                    receipt["reason"]="pinned mlx-lm installation failed"
                else:
                    child=root/"resolve.py"
                    child.write_text(
                        "from huggingface_hub import snapshot_download\n"
                        f"print(snapshot_download(repo_id={MODEL_REPO!r}, revision={MODEL_REVISION!r}))\n",
                        encoding="utf-8",
                    )
                    rc,out,err=run([str(py),str(child)],timeout=600)
                    if rc!=0 or not out:
                        receipt["classification"]="ENVIRONMENT_FAILURE"
                        receipt["reason"]="pinned model snapshot acquisition failed"
                        receipt["snapshot_error"]=err[-3000:] or None
                    else:
                        snapshot=pathlib.Path(out.splitlines()[-1].strip())
                        receipt["resolved_revision"]=snapshot.name
                        model_file=snapshot/"model.safetensors"
                        if not model_file.exists():
                            receipt["classification"]="HARNESS_FAILURE"
                            receipt["reason"]="expected model.safetensors missing from snapshot"
                        else:
                            receipt["model"]={
                                "model_safetensors_bytes":model_file.stat().st_size,
                                "model_safetensors_sha256":sha256_file(model_file.resolve()),
                            }
                            gpu_rc,gpu_out,gpu_err=run([
                                str(py),"-c",
                                "import mlx.core as mx; "
                                "mx.set_default_device(mx.gpu); "
                                "print(mx.default_device())"
                            ],timeout=30)
                            receipt["gpu_preflight"]={"exit_code":gpu_rc,"default_device":gpu_out,"stderr":gpu_err or None}
                            if gpu_rc!=0 or "gpu" not in gpu_out.lower():
                                receipt["classification"]="ORACLE_FAILURE"
                                receipt["reason"]="MLX GPU default device could not be established"
                            else:
                                log_path=root/"server.log"
                                with log_path.open("w") as log:
                                    server=subprocess.Popen(
                                        [str(py),"-m","mlx_lm.server","--model",str(snapshot),"--port",str(PORT)],
                                        stdout=log,stderr=subprocess.STDOUT,text=True,start_new_session=True,
                                    )
                                try:
                                    ready=False
                                    last_error=None
                                    for _ in range(120):
                                        if server.poll() is not None:
                                            break
                                        try:
                                            models=get_json(f"http://127.0.0.1:{PORT}/v1/models",timeout=2)
                                            if isinstance(models,dict):
                                                ready=True
                                                receipt["models_response"]=models
                                                break
                                        except Exception as exc:
                                            last_error=type(exc).__name__
                                        time.sleep(1)
                                    if not ready:
                                        receipt["classification"]="ENVIRONMENT_FAILURE"
                                        receipt["reason"]="mlx_lm.server failed readiness"
                                        receipt["readiness_error"]=last_error
                                    else:
                                        payload={
                                            "model":str(snapshot),
                                            "messages":[{
                                                "role":"user",
                                                "content":"Call the write_value tool exactly once with content exactly READY. Do not respond with prose."
                                            }],
                                            "tools":[{
                                                "type":"function",
                                                "function":{
                                                    "name":"write_value",
                                                    "description":"Write a value to the target file.",
                                                    "parameters":{
                                                        "type":"object",
                                                        "properties":{"content":{"type":"string"}},
                                                        "required":["content"],
                                                        "additionalProperties":False,
                                                    },
                                                },
                                            }],
                                            "tool_choice":"required",
                                            "temperature":0,
                                            "max_tokens":128,
                                        }
                                        try:
                                            response=post_json(f"http://127.0.0.1:{PORT}/v1/chat/completions",payload,timeout=180)
                                            receipt["response"]=response
                                            msg=((response.get("choices") or [{}])[0].get("message") or {})
                                            calls=msg.get("tool_calls") or []
                                            valid=False
                                            parsed_args=None
                                            if calls:
                                                fn=(calls[0].get("function") or {})
                                                try:
                                                    parsed_args=json.loads(fn.get("arguments") or "{}")
                                                except json.JSONDecodeError:
                                                    parsed_args=None
                                                valid=(
                                                    fn.get("name")=="write_value"
                                                    and isinstance(parsed_args,dict)
                                                    and isinstance(parsed_args.get("content"),str)
                                                )
                                            receipt["tool_call_oracle"]={
                                                "call_count":len(calls),
                                                "valid":valid,
                                                "parsed_arguments":parsed_args,
                                            }
                                            if valid:
                                                receipt["classification"]="SUPPORTED"
                                                receipt["reason"]="local MLX-LM server emitted a valid OpenAI structured tool call"
                                            else:
                                                receipt["classification"]="ORACLE_FAILURE"
                                                receipt["reason"]="model/server completed but did not emit the required structured tool call"
                                        except urllib.error.HTTPError as exc:
                                            body=exc.read().decode(errors="replace")
                                            receipt["classification"]="ORACLE_FAILURE"
                                            receipt["reason"]="tool-call request returned HTTP error"
                                            receipt["http_error"]={"code":exc.code,"body":body[-4000:]}
                                        except Exception as exc:
                                            receipt["classification"]="HARNESS_FAILURE"
                                            receipt["reason"]="tool-call request failed unexpectedly"
                                            receipt["request_error"]=f"{type(exc).__name__}: {exc}"
                                finally:
                                    if server.poll() is None:
                                        server.terminate()
                                        try:
                                            server.wait(timeout=10)
                                        except subprocess.TimeoutExpired:
                                            server.kill()
                                            server.wait(timeout=5)
                                    if log_path.exists():
                                        receipt["server_log_tail"]=log_path.read_text(errors="replace")[-6000:]

    outpath=pathlib.Path(args.out)
    outpath.parent.mkdir(parents=True,exist_ok=True)
    outpath.write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"MLX_TOOL_CALL_PREFLIGHT_RECEIPT={outpath}")
    print(json.dumps(receipt,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
