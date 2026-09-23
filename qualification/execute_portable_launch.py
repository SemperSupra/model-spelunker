#!/usr/bin/env python3
"""Execute one portable qualification launch packet.

This is the venue-neutral execution seam. A scheduler/workflow may select a packet,
but the packet itself binds the task, actor, substrate, authority, credentials, limits,
and output names. The candidate command remains an explicit actuator supplied by the
caller so this layer does not become an agent registry or scheduler.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from qualification.validate_portable_launch_packet import (
    canonical_digest,
    read,
    validate_packet,
)


ROOT = Path(__file__).resolve().parents[1]


def safe_output(root: Path, relative: str) -> Path:
    rel=Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe launch output path: {relative}")
    base=root.resolve()
    target=(base/rel).resolve()
    if target!=base and base not in target.parents:
        raise ValueError(f"launch output escapes root: {relative}")
    target.parent.mkdir(parents=True,exist_ok=True)
    return target


def candidate_metadata(actor: dict) -> dict:
    harness={
        key:value
        for key,value in actor["harness"].items()
        if value is not None
    }
    source_model=actor["model"]
    model={
        "provider":source_model["provider"],
        "id":source_model["id"],
    }
    artifact_ref=source_model.get("artifact_ref")
    if artifact_ref:
        model["artifact_ref"]=artifact_ref
    if source_model.get("realization")=="router":
        model["treatment_kind"]="router"

    out={
        "harness":harness,
        "model":model,
        "toolset":list(actor.get("toolset") or []),
        "configuration":actor.get("configuration") or {},
    }
    return out


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("packet",type=Path)
    parser.add_argument("--task-commit",required=True)
    parser.add_argument("--substrate-profile-commit",required=True)
    parser.add_argument("--output-root",type=Path,required=True)
    parser.add_argument("command",nargs=argparse.REMAINDER)
    args=parser.parse_args()

    command=list(args.command)
    if command and command[0]=="--":
        command=command[1:]
    if not command:
        parser.error("candidate command is required after --")

    packet=read(args.packet)
    schema=read(ROOT/"qualification/portable-launch-packet.schema.json")
    task_ref=Path(packet["task"]["profile_ref"])
    if task_ref.name!="task.json":
        raise ValueError("task profile_ref must name task.json")
    task_dir=task_ref.parent
    actor_profile=Path(packet["actor"]["profile_ref"])
    substrate_profile=Path(packet["substrate"]["profile_ref"])

    _,actor,substrate=validate_packet(
        packet,
        schema,
        task_dir,
        actor_profile,
        substrate_profile,
    )

    for ref in packet["credentials"]["refs"]:
        if ref not in os.environ or not os.environ[ref]:
            raise ValueError(f"required credential reference is unavailable: {ref}")

    output_root=args.output_root
    output_root.mkdir(parents=True,exist_ok=True)
    receipt=safe_output(output_root,packet["outputs"]["receipt"])
    diagnostics=safe_output(output_root,packet["outputs"]["diagnostics"])
    packet_digest=canonical_digest(packet)

    candidate=candidate_metadata(actor)
    with tempfile.TemporaryDirectory(prefix="model-spelunker-launch-") as tmp:
        metadata=Path(tmp)/"candidate.json"
        metadata.write_text(
            json.dumps(candidate,indent=2,sort_keys=True)+"\n",
            encoding="utf-8",
        )

        run=[
            sys.executable,
            str(ROOT/"qualification/run_task.py"),
            "--task-commit",args.task_commit,
            "--substrate-profile-id",substrate["id"],
            "--substrate-profile-commit",args.substrate_profile_commit,
            "--substrate-profile-digest",packet["substrate"]["profile_digest"],
            "--launch-id",packet["launch_id"],
            "--launch-packet-digest",packet_digest,
            "--diagnostics",str(diagnostics),
            "--candidate-env-mode","minimal",
        ]
        for ref in packet["credentials"]["refs"]:
            run.extend(["--pass-env",ref])
        run.extend([
            str(task_dir),
            str(metadata),
            str(receipt),
            "--",
            *command,
        ])
        completed=subprocess.run(run,check=False)

    if not receipt.is_file():
        raise RuntimeError("portable launch did not emit a receipt")

    emitted=json.loads(receipt.read_text(encoding="utf-8"))
    if emitted.get("launch") != {
        "launch_id":packet["launch_id"],
        "packet_digest":packet_digest,
    }:
        raise RuntimeError("receipt launch provenance does not match packet")
    if emitted["substrate"].get("profile_digest") != packet["substrate"]["profile_digest"]:
        raise RuntimeError("receipt substrate digest does not match packet")

    return completed.returncode


if __name__=="__main__":
    raise SystemExit(main())
