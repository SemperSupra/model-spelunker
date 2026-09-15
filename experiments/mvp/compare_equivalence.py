#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def probe_by_id(bundle, probe_id):
    matches = [p for p in bundle["observations"]["probes"] if p["probe_id"] == probe_id]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {probe_id!r}, got {len(matches)}")
    return matches[0]


def score_map(condition):
    return {item["candidate"]: float(item["logprob"]) for item in condition["candidate_scores"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("isolated", type=Path)
    parser.add_argument("--probe-id", required=True)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args()

    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    isolated = json.loads(args.isolated.read_text(encoding="utf-8"))
    assert batch["model_identity"] == isolated["model_identity"]
    assert batch["artifact_provenance"]["identity_digest"] == isolated["artifact_provenance"]["identity_digest"]

    left = probe_by_id(batch, args.probe_id)
    right = probe_by_id(isolated, args.probe_id)
    assert left["contrast_id"] == right["contrast_id"]
    assert len(left["conditions"]) == len(right["conditions"])

    max_score_delta = 0.0
    max_hidden_delta = 0.0
    max_contrast_delta = 0.0

    for a, b in zip(left["conditions"], right["conditions"]):
        for key in ("condition_id", "render", "prompt_sha256", "input_token_ids_sha256", "input_tokens", "candidate_winner", "generation"):
            assert a[key] == b[key], (key, a[key], b[key])
        sa, sb = score_map(a), score_map(b)
        assert sa.keys() == sb.keys()
        for key in sa:
            max_score_delta = max(max_score_delta, abs(sa[key] - sb[key]))
        assert len(a["hidden_summary"]) == len(b["hidden_summary"])
        for ha, hb in zip(a["hidden_summary"], b["hidden_summary"]):
            assert ha["layer"] == hb["layer"]
            for key in ("l2", "mean", "std"):
                max_hidden_delta = max(max_hidden_delta, abs(float(ha[key]) - float(hb[key])))

    assert len(left["activation_contrast"]) == len(right["activation_contrast"])
    for a, b in zip(left["activation_contrast"], right["activation_contrast"]):
        assert a["layer"] == b["layer"]
        for key in ("cosine_similarity", "cosine_distance", "delta_l2", "mean_abs_delta"):
            max_contrast_delta = max(max_contrast_delta, abs(float(a[key]) - float(b[key])))

    assert max_score_delta <= args.tolerance, max_score_delta
    assert max_hidden_delta <= args.tolerance, max_hidden_delta
    assert max_contrast_delta <= args.tolerance, max_contrast_delta

    print(json.dumps({
        "equivalent": True,
        "probe_id": args.probe_id,
        "tolerance": args.tolerance,
        "max_candidate_logprob_delta": max_score_delta,
        "max_hidden_summary_delta": max_hidden_delta,
        "max_activation_contrast_delta": max_contrast_delta,
        "batch_hydrate_seconds": batch["cost"]["hydrate_seconds"],
        "isolated_hydrate_seconds": isolated["cost"]["hydrate_seconds"],
        "batch_model_load_seconds": batch["cost"]["model_load_seconds"],
        "isolated_model_load_seconds": isolated["cost"]["model_load_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
