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
    assert provenance["identity_kind"] in {"oci", "content-manifest"}
    assert provenance["identity_digest"].startswith("sha256:")
    assert len(provenance["upstream_revision"]) == 40

    probes = bundle["observations"]["probes"]
    assert len(probes) >= 4
    for probe in probes:
        assert len(probe["conditions"]) == 2, probe["probe_id"]
        assert len(probe["activation_contrast"]) > 1, probe["probe_id"]
        layer_ids = [x["layer"] for x in probe["activation_contrast"]]
        assert layer_ids == list(range(len(layer_ids))), probe["probe_id"]
        for condition in probe["conditions"]:
            assert condition["candidate_winner"] in {"A", "B"}
            assert len(condition["candidate_scores"]) == 2
            assert condition["input_tokens"] > 0
            assert len(condition["hidden_summary"]) == len(probe["activation_contrast"])

    print(json.dumps({
        "validated": True,
        "run_id": bundle["provenance"]["run_id"],
        "probe_count": len(probes),
        "artifact_identity": provenance["identity_digest"],
        "identity_kind": provenance["identity_kind"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
