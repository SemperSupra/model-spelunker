"""Hermetic controls for #193 conditioning DOE; all identities/hashes are mock fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_protocol import Denied, controls_digest, inspect_observations, main, strict_load, validate_plan

H = lambda ch: ch * 64
R = lambda ch: ch * 40
PLAN_SHA = H("9")

def mock_plan():
    return {
        "schema": "conditioning-doe-plan/v1", "campaign": "model-spelunker-193",
        "generator": "z-image-turbo", "generator_repo": "Tongyi-MAI/Z-Image-Turbo",
        "generator_revision": R("a"), "generator_weights_sha256": H("a"),
        "vae_sha256": H("b"), "workflow_sha256": H("c"),
        "runtime_image_sha256": H("d"), "comfyui_commit": R("b"),
        "preprocess_sha256": H("e"), "dataset_sha256": H("f"),
        "sampler": "euler", "steps": 9, "guidance": 1.0,
        "width": 768, "height": 768, "quantization": "bf16",
        "prompt_cases": [
            {"id": "spatial-two-cubes", "prompt_sha256": H("1")},
            {"id": "ocr-label-north", "prompt_sha256": H("2")}
        ],
        "seeds": [17, 101],
        "encoders": [
            {"variant": "base", "repository": "Qwen/Qwen3-4B",
             "revision": R("c"), "weights_sha256": H("3"), "quantization": "bf16"},
            {"variant": "heretic", "repository": "CCSSNE/DreamFast-qwen3-4b-heretic",
             "revision": R("d"), "weights_sha256": H("4"), "quantization": "bf16"}
        ],
    }

def mock_observations(plan):
    encoders = {e["variant"]: e for e in plan["encoders"]}
    rows = []
    for variant, prompt_id, seed in validate_plan(plan):
        encoder = encoders[variant]
        rows.append({
            "variant": variant, "model_repository": encoder["repository"],
            "model_revision": encoder["revision"],
            "encoder_weights_sha256": encoder["weights_sha256"],
            "prompt_id": prompt_id, "seed": seed,
            "controls_sha256": controls_digest(plan), "image_sha256": H("8"),
            "native_run_ref": f"rep-{len(rows):03d}"
        })
    return {"schema": "conditioning-doe-observations/v1",
            "campaign": "model-spelunker-193", "plan_sha256": PLAN_SHA, "runs": rows}

def judge(plan, obs):
    return inspect_observations(obs, plan, PLAN_SHA)

class ConditioningProtocolTests(unittest.TestCase):
    def setUp(self):
        self.plan = mock_plan()
        self.obs = mock_observations(self.plan)

    def test_correct_pair_plan_is_source_only(self):
        self.assertEqual(len(validate_plan(self.plan)), 8)
        r = judge(self.plan, self.obs)
        self.assertEqual(r["status"], "STRUCTURE_ONLY")
        self.assertEqual(r["expected_outputs"], 8)
        self.assertFalse(r["native_inference_attested"])
        self.assertFalse(r["image_bytes_verified"])
        self.assertFalse(r["quality_verified"])

    def test_second_generator_with_same_encoder_pair(self):
        p = copy.deepcopy(self.plan)
        p.update(generator="flux2-klein-4b", generator_repo="black-forest-labs/FLUX.2-klein-4B",
                 generator_revision=R("e"), generator_weights_sha256=H("7"))
        obs = mock_observations(p)
        self.assertEqual(judge(p, obs)["generator"], "flux2-klein-4b")

    def test_krea_vl_not_silently_interchangeable(self):
        self.plan["generator"] = "krea2"
        self.plan["generator_repo"] = "Comfy-Org/Krea-2"
        with self.assertRaisesRegex(Denied, "GENERATOR_NOT_ALLOWLISTED"):
            validate_plan(self.plan)

    def test_unapproved_generator_repo(self):
        self.plan["generator_repo"] = "unknown/replacement"
        with self.assertRaisesRegex(Denied, "GENERATOR_NOT_ALLOWLISTED"):
            validate_plan(self.plan)

    def test_revisions_and_artifact_digests_pinned(self):
        self.plan["comfyui_commit"] = "main"
        with self.assertRaisesRegex(Denied, "REVISION_UNPINNED"):
            validate_plan(self.plan)
        self.plan["comfyui_commit"] = R("b")
        self.plan["vae_sha256"] = ""
        with self.assertRaisesRegex(Denied, "ARTIFACT_DIGEST_UNPINNED"):
            validate_plan(self.plan)

    def test_wrong_model_pair_identity(self):
        self.plan["encoders"][1]["repository"] = "heretic-org/Qwen3-4B-Instruct-2507-heretic"
        with self.assertRaisesRegex(Denied, "ENCODER_IDENTITY"):
            validate_plan(self.plan)

    def test_encoder_quantization_cannot_drift(self):
        self.plan["encoders"][1]["quantization"] = "fp8-e4m3"
        with self.assertRaisesRegex(Denied, "ENCODER_IDENTITY"):
            validate_plan(self.plan)

    def test_sampling_and_resource_bounds(self):
        for field, value in (("width", 1537), ("height", 767), ("steps", 61),
                             ("guidance", 30), ("sampler", "arbitrary_code"),
                             ("width", True)):
            with self.subTest(field=field, value=value):
                p = copy.deepcopy(self.plan)
                p[field] = value
                with self.assertRaisesRegex(Denied, "SAMPLING_GEOMETRY"):
                    validate_plan(p)

    def test_seeds_and_prompt_cases_bounded(self):
        self.plan["seeds"] = [17, 17]
        with self.assertRaisesRegex(Denied, "SEED_SET"):
            validate_plan(self.plan)
        self.plan["seeds"] = [17, 101]
        self.plan["prompt_cases"].append(copy.deepcopy(self.plan["prompt_cases"][0]))
        with self.assertRaisesRegex(Denied, "PROMPT_CASE_INVALID"):
            validate_plan(self.plan)

    def test_unequal_or_missing_treatments(self):
        self.plan["encoders"] = [self.plan["encoders"][0]]
        with self.assertRaisesRegex(Denied, "ENCODER_PAIR_REQUIRED"):
            validate_plan(self.plan)
        self.plan["encoders"] = [mock_plan()["encoders"][0]] * 2
        with self.assertRaisesRegex(Denied, "ENCODER_IDENTITY"):
            validate_plan(self.plan)

    def test_missing_output_cannot_pass(self):
        self.obs["runs"].pop()
        with self.assertRaisesRegex(Denied, "OBSERVATION_SCHEMA_OR_COMPLETENESS"):
            judge(self.plan, self.obs)

    def test_repeat_or_foreign_run_cannot_pass(self):
        self.obs["runs"][-1] = copy.deepcopy(self.obs["runs"][0])
        with self.assertRaisesRegex(Denied, "RUN_PAIRING_DRIFT"):
            judge(self.plan, self.obs)

    def test_wrong_generator_or_vae_cannot_pass(self):
        self.obs["runs"][0]["controls_sha256"] = H("0")
        with self.assertRaisesRegex(Denied, "RUN_MODEL_OR_CONTROLS_DRIFT"):
            judge(self.plan, self.obs)

    def test_wrong_model_or_encoder_artifact_cannot_pass(self):
        self.obs["runs"][2]["model_revision"] = R("f")
        with self.assertRaisesRegex(Denied, "RUN_MODEL_OR_CONTROLS_DRIFT"):
            judge(self.plan, self.obs)
        self.obs = mock_observations(self.plan)
        self.obs["runs"][2]["encoder_weights_sha256"] = H("0")
        with self.assertRaisesRegex(Denied, "RUN_MODEL_OR_CONTROLS_DRIFT"):
            judge(self.plan, self.obs)

    def test_self_scoring_and_extra_fields_denied(self):
        self.obs["runs"][0]["model_claimed_quality"] = 1.0
        with self.assertRaisesRegex(Denied, "SELF_SCORING"):
            judge(self.plan, self.obs)
        self.obs = mock_observations(self.plan)
        self.obs["oracle_expected"] = "yes"
        with self.assertRaisesRegex(Denied, "OBSERVATION_SCHEMA"):
            judge(self.plan, self.obs)

    def test_native_run_ref_still_not_runtime_attestation(self):
        self.obs["runs"][0]["native_run_ref"] = "my-claimed-run-id"
        r = judge(self.plan, self.obs)
        self.assertFalse(r["native_inference_attested"])

    def test_strict_digest_inputs_duplicate_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"input.json"
            for value in (b'{"a":1,"a":2}', b'{"score":NaN}'):
                path.write_bytes(value)
                with self.assertRaises(Denied):
                    strict_load(path, hashlib.sha256(value).hexdigest())

    def test_forged_sha_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"input.json"
            path.write_text(json.dumps(self.plan))
            with self.assertRaisesRegex(Denied, "INPUT_SHA_MISMATCH"):
                strict_load(path, H("0"))
            link = Path(td)/"link.json"
            link.symlink_to(path)
            with self.assertRaisesRegex(Denied, "INPUT_NOT_REGULAR_FILE"):
                strict_load(link, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_cli_plan_never_attests_quality(self):
        with tempfile.TemporaryDirectory() as td:
            from contextlib import redirect_stdout
            from io import StringIO
            path = Path(td)/"plan.json"
            path.write_text(json.dumps(self.plan), encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            buf = StringIO()
            with redirect_stdout(buf):
                rc = main(["--plan", str(path), "--plan-sha256", digest])
            self.assertEqual(rc, 0)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["status"], "PLANNED_ONLY")
            self.assertFalse(result["gpu_admitted"])
            self.assertFalse(result["quality_verified"])

if __name__ == "__main__":
    unittest.main()
