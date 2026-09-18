#!/usr/bin/env python3
"""Gate 8: qualify visual concept-pack normalization and fail-closed guards."""
from __future__ import annotations

import json

from visual_concept_worker_core import canonical_digest, load_concept_pack


def expect_error(value, fragment: str) -> None:
    try:
        load_concept_pack(value)
    except ValueError as exc:
        if fragment not in str(exc):
            raise
    else:
        raise SystemExit(f"expected ValueError containing {fragment!r}")


def main() -> int:
    current = {
        "schema_version": "visual_concept_pack.v0.1",
        "concepts": [
            {"label": "cat", "concept_id": "object.animal.cat"},
            {"label": "dog", "concept_id": "object.animal.dog"},
        ],
    }
    legacy = {
        "schema_version": "legacy.v0.1",
        "labels": [
            {"label": "cat", "concept_id": "object.animal.cat"},
            {"label": "dog", "concept_id": "object.animal.dog"},
        ],
    }
    flat = [
        {"label": "cat", "concept_id": "object.animal.cat"},
        {"label": "dog", "concept_id": "object.animal.dog"},
    ]
    strings = ["cat", "dog"]

    a = load_concept_pack(current)
    b = load_concept_pack(legacy)
    c = load_concept_pack(flat)
    d = load_concept_pack(strings)

    if not (a == b == c):
        raise SystemExit("current/legacy/flat structured packs did not normalize identically")
    if d != [
        {"label": "cat", "concept_id": None},
        {"label": "dog", "concept_id": None},
    ]:
        raise SystemExit(f"string-only pack normalization drift: {d}")

    if canonical_digest(a) != canonical_digest(b):
        raise SystemExit("equivalent current/legacy packs must have identical digest")

    expect_error(
        {
            "concepts": [{"label": "cat"}],
            "labels": [{"label": "dog"}],
        },
        "both concepts and labels",
    )
    expect_error({"metadata": "no entries"}, "must contain concepts or labels")
    expect_error({"concepts": []}, "empty")
    expect_error(
        {
            "concepts": [
                {"label": "cat", "concept_id": "animal"},
                {"label": "feline", "concept_id": "animal"},
            ]
        },
        "duplicate concept_id",
    )
    expect_error(
        {"concepts": [{"label": "cat"}, {"label": "cat"}]},
        "duplicate concept label",
    )
    expect_error({"concepts": [{"label": ""}]}, "empty label")
    expect_error({"concepts": [42]}, "invalid concept pack entry")

    result = {
        "schema_version": "visual_concept_pack_gate8.v0.1",
        "status": "pass",
        "normalized_digest": canonical_digest(a),
        "entries": len(a),
        "invariants": {
            "legacy_labels_supported": True,
            "current_concepts_supported": True,
            "equivalent_shapes_same_digest": True,
            "ambiguous_pack_rejected": True,
            "empty_pack_rejected": True,
            "duplicate_label_rejected": True,
            "duplicate_concept_id_rejected": True,
            "invalid_entry_rejected": True,
            "private_semantic_authority_present": False,
            "private_content_present": False,
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
