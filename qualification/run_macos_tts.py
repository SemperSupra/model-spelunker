#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def command_text(*args: str) -> str:
    proc=subprocess.run(args,text=True,capture_output=True,check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--evidence",type=Path,required=True)
    parser.add_argument("--voice",default="Samantha")
    args=parser.parse_args()

    source=args.source.read_text(encoding="utf-8").strip()
    source_sha=sha256_bytes(source.encode("utf-8"))
    voices=subprocess.run(
        ["/usr/bin/say","-v","?"],text=True,capture_output=True,check=False
    )
    voice_lines=[
        line for line in voices.stdout.splitlines()
        if line.split(maxsplit=1)[0] == args.voice
    ]
    admitted=voices.returncode == 0 and len(voice_lines) == 1

    evidence={
        "schema_version":1,
        "record_type":"tts-generation",
        "actor":{
            "runtime":"/usr/bin/say",
            "requested_voice":args.voice,
            "voice_admitted":admitted,
            "voice_listing":voice_lines[0] if admitted else None,
        },
        "environment":{
            "platform_system":platform.system(),
            "platform_machine":platform.machine(),
            "macos_product_version":command_text("/usr/bin/sw_vers","-productVersion"),
            "macos_build_version":command_text("/usr/bin/sw_vers","-buildVersion"),
        },
        "source":{
            "sha256":source_sha,
            "chars":len(source),
            "text_retained":False,
        },
        "output":None,
        "generation_wall_seconds":None,
        "status":"voice-admission-failure" if not admitted else "pending",
    }

    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)

    if not admitted:
        args.evidence.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
        return 78

    started=time.monotonic()
    proc=subprocess.run(
        ["/usr/bin/say","-v",args.voice,"-o",str(args.output),source],
        text=True,capture_output=True,check=False,
    )
    wall=time.monotonic()-started
    evidence["generation_wall_seconds"]=round(wall,6)
    if proc.returncode != 0 or not args.output.is_file():
        evidence["status"]="generator-execution-failure"
        evidence["generator_exit_code"]=proc.returncode
        args.evidence.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
        return 1

    data=args.output.read_bytes()
    evidence["output"]={
        "path":args.output.name,
        "sha256":sha256_bytes(data),
        "size_bytes":len(data),
    }
    evidence["generator_exit_code"]=proc.returncode
    evidence["status"]="generated"
    args.evidence.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
    print(json.dumps(evidence,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
