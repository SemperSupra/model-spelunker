import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_shared_probe", ROOT / "scripts" / "run_shared_probe.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def test_probe_set_is_valid_and_has_required_contrasts():
    data = mod.load_probe_set(ROOT / "experiments" / "mvp" / "probes.json")
    ids = [c["probe_case_id"] for c in data["cases"]]
    assert len(ids) == len(set(ids))
    contrasts = {c["contrast_id"] for c in data["cases"]}
    assert {
        "protocol-native-vs-generic",
        "direct-vs-decomposed",
        "semantic-paraphrase",
        "negative-null",
    } <= contrasts


def test_foundry_identity_fails_closed():
    good = {
        "logical_id": "llm/test",
        "upstream_repository": "example/model",
        "upstream_exact_revision": "a" * 40,
        "identity_kind": "content-manifest",
        "identity_digest": "sha256:" + "b" * 64,
        "foundry_ref": "SemperSupra/model-artifact-foundry@deadbeef",
        "hydration_verified": True,
    }
    mod.validate_foundry_identity(good)
    bad = dict(good)
    bad["hydration_verified"] = False
    try:
        mod.validate_foundry_identity(bad)
    except RuntimeError as exc:
        assert "verified" in str(exc)
    else:
        raise AssertionError("unverified hydration must fail closed")


def test_batch_economics():
    timing = {
        "dependency_setup_seconds": 10.0,
        "artifact_hydration_seconds": 20.0,
        "artifact_verification_seconds": 5.0,
        "model_load_seconds": 15.0,
        "instrumentation_init_seconds": 0.0,
    }
    summary = mod.summarize_batch_timing(timing, [5.0, 5.0, 5.0, 5.0])
    assert summary["probe_count"] == 4
    assert summary["fixed_setup_seconds"] == 50.0
    assert summary["mean_marginal_probe_seconds"] == 5.0
    assert 0.71 < summary["setup_fraction"] < 0.72
    assert summary["throughput_probes_per_minute"] == 12.0
    assert summary["break_even_batch_size_at_20pct_setup"] == 40


def test_plan_mode_needs_no_model_dependencies(tmp_path):
    class Args:
        probes = ROOT / "experiments" / "mvp" / "probes.json"

    plan = mod.plan(Args())
    assert plan["case_count"] == 8
    assert plan["execution_shape"].startswith("one hydrated model")
