#!/usr/bin/env python3
"""Validate a portable qualification launch packet against local contract inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import jsonschema

from qualification.run_task import tree_digest


def canonical_digest(value: object) -> str:
    payload=json.dumps(value,sort_keys=True,separators=(",",":")).encode("utf-8")
    return "sha256:"+hashlib.sha256(payload).hexdigest()


def read(path: Path) -> dict:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def validate_packet(
    packet: dict,
    schema: dict,
    task_dir: Path,
    actor_profile: Path,
    substrate_profile: Path,
) -> tuple[dict, dict, dict]:
    task=read(task_dir/"task.json")
    actor=read(actor_profile)
    substrate=read(substrate_profile)

    jsonschema.Draft7Validator(schema).validate(packet)

    if packet["task"]["profile_ref"] != str(task_dir/"task.json"):
        raise ValueError("task profile_ref does not match supplied task package")
    actual_task_digest=tree_digest(task_dir)
    if packet["task"]["package_digest"] != actual_task_digest:
        raise ValueError(
            f"task package digest mismatch: {packet['task']['package_digest']} != {actual_task_digest}"
        )

    if packet["actor"]["profile_ref"] != str(actor_profile):
        raise ValueError("actor profile_ref does not match supplied actor profile")

    if packet["substrate"]["profile_ref"] != str(substrate_profile):
        raise ValueError("substrate profile_ref does not match supplied substrate profile")
    actual_substrate_digest=canonical_digest(substrate)
    if packet["substrate"]["profile_digest"] != actual_substrate_digest:
        raise ValueError(
            f"substrate profile digest mismatch: {packet['substrate']['profile_digest']} "
            f"!= {actual_substrate_digest}"
        )

    if packet["authority"]["profile_ref"] != actor["authority_profile"]:
        raise ValueError("authority profile disagrees with configured actor")

    required_tools=sorted(f"tool:{name}" for name in task.get("projected_tools") or [])
    if sorted(packet["authority"]["tool_refs"]) != required_tools:
        raise ValueError("launch tool refs disagree with task projection")

    actor_tools=sorted(f"tool:{name}" for name in actor.get("toolset") or [])
    if actor_tools != required_tools:
        raise ValueError("configured actor toolset disagrees with task projection")

    if packet["limits"]["wall_seconds"] != task["limits"]["wall_seconds"]:
        raise ValueError("launch wall limit disagrees with task package")

    forbidden_fragments=("GITHUB_WORKSPACE","RUNNER_TEMP","github.run_id","docker pull","docker create")
    serialized=json.dumps(packet,sort_keys=True)
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"venue-specific launch content is prohibited: {fragment}")

    return task, actor, substrate


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("packet",type=Path)
    parser.add_argument("--schema",type=Path,default=Path("qualification/portable-launch-packet.schema.json"))
    parser.add_argument("--task-dir",type=Path,required=True)
    parser.add_argument("--actor-profile",type=Path,required=True)
    parser.add_argument("--substrate-profile",type=Path,required=True)
    args=parser.parse_args()

    packet=read(args.packet)
    schema=read(args.schema)
    task,actor,substrate=validate_packet(
        packet,
        schema,
        args.task_dir,
        args.actor_profile,
        args.substrate_profile,
    )

    print(
        "PASS portable launch packet "
        f"{packet['launch_id']} task={task['id']} actor={actor['id']} substrate={substrate['id']}"
    )
    return 0


if __name__=="__main__":
    raise SystemExit(main())
