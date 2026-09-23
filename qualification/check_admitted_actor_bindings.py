#!/usr/bin/env python3
"""Check cross-file bindings for configured actors that consume admitted harness artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actors", type=Path, default=Path("qualification/actors"))
    parser.add_argument(
        "--admissions",
        type=Path,
        default=Path("qualification/harness-artifacts"),
    )
    args = parser.parse_args()

    admissions = []
    for path in sorted(args.admissions.glob("*.admission*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("record_type") == "harness-artifact-admission":
            admissions.append((path, row))

    by_artifact: dict[str, list[tuple[Path, dict]]] = {}
    for path, row in admissions:
        by_artifact.setdefault(row["artifact"]["ref"], []).append((path, row))

    checked = 0
    for actor_path in sorted(args.actors.glob("*.json")):
        actor = json.loads(actor_path.read_text(encoding="utf-8"))
        if (actor.get("configuration") or {}).get("harness_delivery") != "prebuilt-admitted-artifact":
            continue

        harness = actor["harness"]
        artifact_ref = harness.get("artifact_ref")
        admission_ref = harness.get("admission_ref")
        if not artifact_ref or not admission_ref:
            raise ValueError(f"{actor_path}: prebuilt actor missing artifact/admission ref")

        matches = by_artifact.get(artifact_ref, [])
        if len(matches) != 1:
            raise ValueError(
                f"{actor_path}: artifact {artifact_ref!r} has {len(matches)} local admission matches"
            )

        admission_path, admission = matches[0]
        if admission["admission"]["state"] != "BUILD_ADMITTED":
            raise ValueError(f"{actor_path}: matched admission is not BUILD_ADMITTED")
        if admission["harness"]["name"] != harness["name"]:
            raise ValueError(f"{actor_path}: harness name disagrees with admission")
        declared = admission["harness"].get("declared_version")
        if declared not in (None, "", "0.0.0") and declared != harness["version"]:
            raise ValueError(
                f"{actor_path}: harness version {harness['version']!r} disagrees with "
                f"{admission_path} declared version {declared!r}"
            )

        digest = admission["artifact"]["digest"]
        if not artifact_ref.endswith("@" + digest):
            raise ValueError(f"{actor_path}: artifact ref is not bound to admitted digest")

        checked += 1
        print(f"PASS {actor_path} -> {admission_path}")

    if checked == 0:
        raise SystemExit("no prebuilt admitted actors found")
    print(f"PASS {checked} prebuilt actor/admission bindings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
