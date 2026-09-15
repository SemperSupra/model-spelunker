#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import jsonschema

EXPECTED_DIGEST = "sha256:c93e953d44105c8cd59be4b893acee43858e9fcb8b4deb20f83535a2165c1c3d"
EXPECTED_REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
EXPECTED_MODEL = "google/siglip2-base-patch16-224"


def finite_tree(value, path="root"):
    if isinstance(value, dict):
        for k, v in value.items():
            finite_tree(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            finite_tree(v, f"{path}[{i}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise AssertionError(f"non-finite float at {path}: {value}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    p.add_argument("--schema", type=Path, default=Path("schemas/observation-bundle.schema.json"))
    args = p.parse_args()

    b = json.loads(args.bundle.read_text())
    schema = json.loads(args.schema.read_text())
    jsonschema.validate(b, schema)
    finite_tree(b)

    assert b["probe_id"] == "multimodal-portability-siglip2-v1"
    assert b["access_tier"] == "A2"
    assert b["evidence_level"] == "REPRODUCED"
    assert b["model_identity"]["repository"] == EXPECTED_MODEL
    assert b["model_identity"]["revision"] == EXPECTED_REVISION
    assert b["model_identity"]["model_class"] == "vision-text-embedding-encoder"

    prov = b["artifact_provenance"]
    assert prov["tracked"] is True and prov["verified"] is True
    assert prov["identity_kind"] == "oci"
    assert prov["identity_digest"] == EXPECTED_DIGEST
    assert prov["upstream_revision"] == EXPECTED_REVISION

    o = b["observations"]
    assert o["embedding_shapes"] == {"image": [4, 768], "text": [6, 768]}
    assert len(o["primary_cross_modal_cosine"]) == 3
    assert all(len(row) == 3 for row in o["primary_cross_modal_cosine"])
    assert len(o["paraphrase_cross_modal_cosine"]) == 3
    assert len(o["matches"]) == 3
    assert len(o["vision_layer_contrasts"]) > 4
    assert len(o["text_layer_contrasts"]) > 4

    d = b["derived_metrics"]
    assert 0.0 <= float(d["primary_top1_rate"]) <= 1.0
    assert 0.0 <= float(d["paraphrase_top1_rate"]) <= 1.0
    assert float(d["red_image_dim_perturbation_cosine_distance"]) >= 0.0
    assert float(d["red_text_paraphrase_cosine_distance"]) >= 0.0
    assert all(d["portable_instrument_checks"].values())

    c = b["cost"]
    assert 0.0 < float(c["peak_rss_mib"]) < 15000.0
    assert float(c["model_load_seconds"]) > 0.0
    assert float(c["experiment_seconds"]) > 0.0

    print(json.dumps({
        "validated": True,
        "run_id": b["provenance"]["run_id"],
        "digest": prov["identity_digest"],
        "primary_top1_rate": d["primary_top1_rate"],
        "paraphrase_top1_rate": d["paraphrase_top1_rate"],
        "rsa": d["cross_modal_rsa_pairwise_pearson"],
        "peak_rss_mib": c["peak_rss_mib"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
