#!/usr/bin/env python3
"""Batch runner for the retrospective trajectory RDT&E bench."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from .reduce_trace import reduce_manifest
except ImportError:
    from reduce_trace import reduce_manifest


def run_batch(manifest_dir: Path) -> tuple[dict, str]:
    files = sorted(manifest_dir.glob("*.json"))
    if not files:
        raise SystemExit("no manifests found")

    results = []
    for path in files:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        result = reduce_manifest(manifest)
        result["manifest"] = path.name
        results.append(result)

    signal_counts = Counter(
        signal for result in results for signal in result.get("signals", [])
    )
    actor_counts = Counter(result["actor_family"] for result in results)
    trace_counts = Counter(result["trace_disposition"] for result in results)

    batch = {
        "record_type": "retrospective-trajectory-batch",
        "schema_version": 1,
        "rep_count": len(results),
        "actor_family_counts": dict(sorted(actor_counts.items())),
        "trace_disposition_counts": dict(sorted(trace_counts.items())),
        "signal_counts": dict(sorted(signal_counts.items())),
        "results": results,
        "qualification_state_changed": False,
    }

    lines = [
        "# Retrospective trajectory RDT&E batch",
        "",
        f"Reps: **{len(results)}**",
        "",
        "## Actor families",
        "",
    ]
    for key, value in sorted(actor_counts.items()):
        lines.append(f"- {key}: {value}")
    lines += ["", "## Trace dispositions", ""]
    for key, value in sorted(trace_counts.items()):
        lines.append(f"- {key}: {value}")
    lines += ["", "## Observed decision signals", ""]
    for key, value in sorted(signal_counts.items()):
        lines.append(f"- {key}: {value}")
    lines += ["", "## Per-rep", ""]
    for result in results:
        signals = ", ".join(result["signals"]) or "none"
        lines.append(
            f"- **{result['rep_id']}** ({result['actor_family']}, "
            f"{result['trace_disposition']}): {signals}"
        )
    lines += [
        "",
        "> RDT&E only. These outputs do not update actor qualification or routing state.",
        "",
    ]
    return batch, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifests", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    batch, markdown = run_batch(args.manifests)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "results.json").write_text(
        json.dumps(batch, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "summary.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
