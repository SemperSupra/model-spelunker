#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema


def finite_tree(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            finite_tree(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            finite_tree(child, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise AssertionError(f"non-finite float at {path}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--schema", type=Path, default=Path("schemas/observation-bundle.schema.json"))
    args = parser.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    jsonschema.validate(bundle, schema)
    finite_tree(bundle)

    provenance = bundle["artifact_provenance"]
    assert provenance["tracked"] is True
    assert provenance["verified"] is True
    assert provenance["identity_digest"].startswith("sha256:")

    probes = bundle["observations"]["probes"]
    assert len(probes) >= 6
    for probe in probes:
        expected = probe["expected_candidate"]
        assert len(probe["conditions"]) == 2
        assert len(probe["activation_contrast"]) > 1
        for condition in probe["conditions"]:
            scores = condition["candidate_scores"]
            candidates = {item["candidate"] for item in scores}
            assert len(scores) == 2
            assert expected in candidates
            assert condition["candidate_winner"] in candidates
            token_counts = {len(item["tokens"]) for item in scores}
            assert len(token_counts) == 1, (
                probe["probe_id"], condition["condition_id"],
                {item["candidate"]: len(item["tokens"]) for item in scores},
            )
            assert next(iter(token_counts)) > 0
            assert condition["input_tokens"] > 0
            assert len(condition["hidden_summary"]) == len(probe["activation_contrast"])

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "probe_count": len(probes),
        "matched_candidate_token_counts": True,
        "artifact_identity": provenance["identity_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
