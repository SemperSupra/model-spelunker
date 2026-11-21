#!/usr/bin/env python3
"""Offline source/authority contract for the advisory Edge0 candidate census.

This is not a model, runtime, tool-use, consent or production acceptance oracle.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("edge0_source_catalog_v1.json")
FAMILY = {"text", "asr", "tts"}
PUBLIC_MODES = {
    "public-m1-smoke-candidate",
    "public-m1-capacity-only",
    "public-source-only",
    "source-and-license-screen-only",
}
KNOWN_ENGINES = {"legacy-mlx-preview", "edge0-infer-native",
                 "edge0-strata", "independently-unverified"}


def _unique_keys(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError("duplicate catalog JSON key")
        seen[k] = v
    return seen


def parse_strict(text: str) -> dict:
    obj = json.loads(text, object_pairs_hook=_unique_keys)
    if not isinstance(obj, dict):
        raise ValueError("catalog must be JSON object")
    return obj


def validate(obj: dict) -> None:
    if obj.get("schema") != "edge0-source-candidate-census-v1":
        raise ValueError("unknown census schema")
    if obj.get("scope") != "PUBLIC_SOURCE_ADVISORY_NOT_ARTIFACT_AUTHORITY":
        raise ValueError("source catalog cannot mint authority")
    if obj.get("framework_edge0_agent_acceptances") != 0:
        raise ValueError("no Edge0 agent task acceptance has been established")
    src = obj.get("source_authority", {})
    for name in ("readme_blob", "new_models_guide_blob", "small_model_guide_blob"):
        value = src.get(name)
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("missing exact upstream documentation blob")
    models = obj.get("candidates")
    if not isinstance(models, list) or len(models) != 21:
        raise ValueError("catalog coverage count is not the publisher's observed 21")
    ids = [m.get("id") for m in models if isinstance(m, dict)]
    if len(ids) != len(models) or len(set(ids)) != 21:
        raise ValueError("invalid or duplicated source model ids")
    families = [m["family"] for m in models]
    if families.count("text") != 6 or families.count("asr") + families.count("tts") != 15:
        raise ValueError("text/audio coverage drift")
    for m in models:
        model = m["id"]
        if not isinstance(model, str) or not model.startswith("Edge0/") or len(model) > 128:
            raise ValueError("invalid model identity")
        if m.get("source_url") != "https://huggingface.co/" + model:
            raise ValueError("model source URL mismatch")
        if m.get("family") not in FAMILY or m.get("native_engine") not in KNOWN_ENGINES:
            raise ValueError("invalid model role or engine")
        if m.get("public_venue") not in PUBLIC_MODES:
            raise ValueError("unknown venue gate")
        if m.get("production_authorized") is not False:
            raise ValueError("candidate census cannot authorize production")
        if m.get("agent_task_acceptance") != "NOT_QUALIFIED":
            raise ValueError("unverified Edge0 task outcome promoted")
        if m.get("inference_observation") not in {"no-execution", "macos-mlxlm-http-integration-unknown"}:
            raise ValueError("unsupported inference acceptance claim")
        if m["family"] != "text":
            if m.get("checkpoint") is not None:
                raise ValueError("unsupported invented audio checkpoint footprint")
            if m.get("public_venue") != "source-and-license-screen-only":
                raise ValueError("audio execution requires independent gate")
    by_id = {m["id"]: m for m in models}
    def text(name, engine, quant, amount, unit, venue):
        m = by_id["Edge0/" + name]
        if (m["family"], m["native_engine"], m["quantization"], m["checkpoint"],
            m["public_venue"]) != ("text", engine, quant, {"amount": amount, "unit": unit}, venue):
            raise ValueError("text-model source/runtime/weight gate drift")
    text("Edge0-8B-A1B-preview", "legacy-mlx-preview", "int4-affine-g64",
         4.55, "GB", "public-m1-smoke-candidate")
    text("Edge0-35B-A3B-preview", "edge0-infer-native", "int4",
         19.6, "GB", "public-m1-capacity-only")
    for scale, active, q3, nv in ((120, 8.64, 27.98, 32.96),
                                  (145, 10.12, 40.81, 47.79)):
        for suffix, quant, size in (("q3k", "Q3_K-mixed-IQ4_NL", q3),
                                    ("NVFP4", "NVFP4", nv)):
            m = by_id[f"Edge0/Edge0-{scale}B-{suffix}"]
            text(f"Edge0-{scale}B-{suffix}", "edge0-strata", quant,
                 size, "GiB", "public-source-only")
            if m.get("total_parameters_b") != scale or m.get("active_parameters_b") != active:
                raise ValueError("sparse active and total parameters conflated")
    if by_id["Edge0/Edge0-8B-A1B-preview"]["inference_observation"] != "macos-mlxlm-http-integration-unknown":
        raise ValueError("invalid 8B inference claim")
    observed = obj.get("host_class_observations", {})
    if observed.get("public_macos15_m1", {}).get("CUDA") is not False or observed.get("public_linux_ubuntu2404", {}).get("CUDA") is not False:
        raise ValueError("unsupported public CUDA venue")
    if not isinstance(obj.get("preconditions"), list) or len(obj["preconditions"]) < 5:
        raise ValueError("missing admission preconditions")


class CatalogContract(unittest.TestCase):
    def test_positive_source_read(self):
        validate(parse_strict(SOURCE.read_text(encoding="utf-8")))

    def test_reject_ambiguous_input(self):
        raw = SOURCE.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            parse_strict('{"schema":"valid","schema":"override"}')
        with self.assertRaises(ValueError):
            parse_strict(raw[:-2] + ',"scope":"PUBLIC_SOURCE_ADVISORY_NOT_ARTIFACT_AUTHORITY"}')

    def test_reject_duplicates_and_promotion(self):
        good = parse_strict(SOURCE.read_text(encoding="utf-8"))
        for mutate in ("duplicate", "task_success", "release", "venue", "engine", "source", "drop"):
            bad = copy.deepcopy(good)
            if mutate == "duplicate":
                bad["candidates"][1]["id"] = bad["candidates"][0]["id"]
            elif mutate == "task_success":
                bad["candidates"][0]["agent_task_acceptance"] = "PASS"
            elif mutate == "release":
                bad["candidates"][0]["production_authorized"] = True
            elif mutate == "venue":
                bad["candidates"][2]["public_venue"] = "public-m1-smoke-candidate"
            elif mutate == "engine":
                bad["candidates"][0]["native_engine"] = "edge0-infer-native"
            elif mutate == "source":
                bad["candidates"][0]["source_url"] = "https://example.invalid/poison"
            else:
                bad["candidates"].pop()
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                validate(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
