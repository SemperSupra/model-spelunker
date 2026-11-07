"""Deterministic negative controls for #191 VLM paired oracle; no real model inference."""
import copy
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_oracle import Denied, assess, main, read_pinned

A = "a" * 40
B = "b" * 40
HASH1 = "sha256:" + "1" * 64
HASH2 = "sha256:" + "2" * 64

def sample():
    cases = [
        {"id": "img-count-01", "task_class": "count", "language": "en",
         "modality": "image", "frame_count": 1, "media_sha256": HASH1,
         "prompt_sha256": HASH2, "reference": "public-synthetic:test-image", "expected": 2},
        {"id": "vid-order-01", "task_class": "temporal_order", "language": "de",
         "modality": "video", "frame_count": 3, "media_sha256": HASH2,
         "prompt_sha256": HASH1, "reference": "public-synthetic:test-video", "expected": "A_THEN_B"},
        {"id": "img-unknown-01", "task_class": "unknown_visibility", "language": "th",
         "modality": "image", "frame_count": 1, "media_sha256": HASH1,
         "prompt_sha256": HASH1, "reference": "public-synthetic:test-ambiguous", "expected": "NOT_VISIBLE"},
    ]
    oracle = {"schema": "vlm-oracle/v1", "campaign": "model-spelunker-191", "cases": cases}
    def receipt(treatment, model):
        outputs = []
        for case in cases:
            outputs.append({
                "id": case["id"], "media_sha256": case["media_sha256"],
                "prompt_sha256": case["prompt_sha256"], "frame_count": case["frame_count"],
                "modality": case["modality"], "language": case["language"],
                "status": "ANSWER", "answer": case["expected"],
                "evidence_frames": [0, 2] if case["modality"] == "video" else [0],
            })
        return {
            "schema": "vlm-observation/v1", "campaign": "model-spelunker-191",
            "treatment": treatment, "model_id": model, "model_revision": A if treatment == "base" else B,
            "runtime_id": "fixed-runtime", "sampler_sha256": HASH1,
            "preprocessing_sha256": HASH2, "vision_route_declared": True, "outputs": outputs,
        }
    base = receipt("base", "Qwen/Qwen3-VL-2B-Instruct")
    heretic = receipt("heretic", "heretic-org/Qwen-3-VL-2B-Instruct-heretic")
    return oracle, base, heretic

def score(oracle, base, modified):
    return assess("qwen3-vl-2b", oracle, base, modified, A, B, "3"*64, "4"*64, "5"*64)

class PairedVisionOracleTests(unittest.TestCase):
    def setUp(self):
        self.oracle, self.base, self.modified = sample()

    def test_matched_pair_is_structural_only(self):
        scored = score(self.oracle, self.base, self.modified)
        self.assertEqual(scored["case_count"], 3)
        self.assertEqual(scored["verdict"], "STRUCTURAL_ORACLE_SCORE_ONLY")
        self.assertFalse(scored["model_inference_attested"])
        self.assertFalse(scored["physical_anatomy_certified"])
        self.assertIn("UNKNOWN", scored["actor_qualification"])
        self.assertEqual(scored["task_class_language_modality_scores"]["temporal_order/de/video"]["heretic_exact"], 1)

    def test_distinct_quality_score_and_abstention_not_auto_pass(self):
        self.modified["outputs"][0]["answer"] = 3
        self.modified["outputs"][2].update(status="ABSTAIN", answer=None, evidence_frames=[])
        scored = score(self.oracle, self.base, self.modified)
        self.assertEqual(scored["task_class_language_modality_scores"]["count/en/image"]["heretic_exact"], 0)
        self.assertEqual(scored["task_class_language_modality_scores"]["unknown_visibility/th/image"]["heretic_abstentions"], 1)
        self.assertEqual(scored["task_class_language_modality_scores"]["unknown_visibility/th/image"]["heretic_exact"], 0)

    def test_unpinned_or_wrong_variant(self):
        self.modified["model_id"] = "heretic-org/Qwen-3-VL-8B-Instruct-heretic"
        with self.assertRaisesRegex(Denied, "MODEL_IDENTITY"):
            score(self.oracle, self.base, self.modified)
        self.modified["model_id"] = "heretic-org/Qwen-3-VL-2B-Instruct-heretic"
        with self.assertRaisesRegex(Denied, "MODEL_PAIR_OR_REVISION"):
            assess("qwen3-vl-2b", self.oracle, self.base, self.modified, "main", B, "3"*64, "4"*64, "5"*64)

    def test_output_receipt_cannot_carry_sealed_oracle_or_extra_metadata(self):
        self.modified["oracle_expected"] = {"img-count-01": 2}
        with self.assertRaisesRegex(Denied, "ORACLE_LEAK"):
            score(self.oracle, self.base, self.modified)
        del self.modified["oracle_expected"]
        self.base["extra_public_claim"] = "self-evaluated-pass"
        with self.assertRaisesRegex(Denied, "ORACLE_LEAK"):
            score(self.oracle, self.base, self.modified)

    def test_text_only_or_missing_vision_route(self):
        self.modified["vision_route_declared"] = False
        with self.assertRaisesRegex(Denied, "VISION_ROUTE"):
            score(self.oracle, self.base, self.modified)

    def test_frame_order_evidence_required(self):
        self.modified["outputs"][1]["evidence_frames"] = [0]
        with self.assertRaisesRegex(Denied, "TEMPORAL_EVIDENCE"):
            score(self.oracle, self.base, self.modified)

    def test_out_of_range_and_duplicate_frames(self):
        for bad in ([0, 3], [0, 0], [-1, 2], [True, 2]):
            with self.subTest(bad=bad):
                self.modified["outputs"][1]["evidence_frames"] = bad
                with self.assertRaisesRegex(Denied, "FRAME_REFERENCE_INVALID"):
                    score(self.oracle, self.base, self.modified)

    def test_missing_or_duplicate_case(self):
        self.modified["outputs"].pop()
        with self.assertRaisesRegex(Denied, "OUTPUT_COUNT"):
            score(self.oracle, self.base, self.modified)
        self.modified["outputs"].append(copy.deepcopy(self.modified["outputs"][0]))
        with self.assertRaisesRegex(Denied, "OUTPUT_ID"):
            score(self.oracle, self.base, self.modified)

    def test_pixel_or_prompt_drift_denied(self):
        self.modified["outputs"][0]["media_sha256"] = HASH2
        with self.assertRaisesRegex(Denied, "INPUT_TREATMENT_DRIFT"):
            score(self.oracle, self.base, self.modified)
        self.modified["outputs"][0]["media_sha256"] = HASH1
        self.modified["outputs"][0]["prompt_sha256"] = HASH1
        with self.assertRaisesRegex(Denied, "INPUT_TREATMENT_DRIFT"):
            score(self.oracle, self.base, self.modified)

    def test_sampling_or_preprocessing_confounded(self):
        self.modified["preprocessing_sha256"] = HASH1
        with self.assertRaisesRegex(Denied, "CONFOUNDED"):
            score(self.oracle, self.base, self.modified)
        self.modified["preprocessing_sha256"] = HASH2
        self.modified["sampler_sha256"] = HASH2
        with self.assertRaisesRegex(Denied, "CONFOUNDED"):
            score(self.oracle, self.base, self.modified)

    def test_oracle_validation_unknown_or_wrong_frame_class(self):
        self.oracle["cases"][0]["frame_count"] = 2
        with self.assertRaisesRegex(Denied, "ORACLE_CASE_INVALID"):
            score(self.oracle, self.base, self.modified)
        self.oracle["cases"][0]["frame_count"] = 1
        self.oracle["cases"][0]["task_class"] = "temporal_order"
        with self.assertRaisesRegex(Denied, "ORACLE_CASE_INVALID"):
            score(self.oracle, self.base, self.modified)

    def test_model_output_is_not_independent_ground_truth(self):
        self.modified["outputs"][1]["answer"] = "WRONG"
        self.assertEqual(score(self.oracle, self.base, self.modified)["task_class_language_modality_scores"]["temporal_order/de/video"]["heretic_exact"], 0)
        self.assertEqual(self.oracle["cases"][1]["expected"], "A_THEN_B")

    def test_bad_answer_type_and_ungrounded(self):
        self.modified["outputs"][0]["answer"] = {"freeform": "not a structured answer"}
        with self.assertRaisesRegex(Denied, "ANSWER_UNGROUNDED"):
            score(self.oracle, self.base, self.modified)
        self.modified["outputs"][0]["answer"] = 2
        self.modified["outputs"][0]["evidence_frames"] = []
        with self.assertRaisesRegex(Denied, "ANSWER_UNGROUNDED"):
            score(self.oracle, self.base, self.modified)

    def test_bad_abstention(self):
        self.modified["outputs"][0].update(status="ABSTAIN", answer="NOT_VISIBLE", evidence_frames=[])
        with self.assertRaisesRegex(Denied, "ABSTENTION"):
            score(self.oracle, self.base, self.modified)

    def test_duplicate_json_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "oracle.json"
            for raw in (b'{"id":"a","id":"b"}', b'{"value":NaN}'):
                target.write_bytes(raw)
                d = hashlib.sha256(raw).hexdigest()
                with self.assertRaises(Denied):
                    read_pinned(target, d)

    def test_digest_tampering_denied(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "oracle.json"
            target.write_text(json.dumps(self.oracle), encoding="utf-8")
            with self.assertRaisesRegex(Denied, "INPUT_DIGEST_MISMATCH"):
                read_pinned(target, "f"*64)
            good = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(read_pinned(target, good)["campaign"], "model-spelunker-191")

    def test_symlink_input_denied(self):
        with tempfile.TemporaryDirectory() as root:
            origin, link = Path(root)/"original.json", Path(root)/"symlink.json"
            origin.write_text(json.dumps(self.oracle), encoding="utf-8")
            link.symlink_to(origin)
            with self.assertRaisesRegex(Denied, "INPUT_FILE_UNTRUSTED"):
                read_pinned(link, hashlib.sha256(origin.read_bytes()).hexdigest())

    def test_cli_hermetic_receipt_no_model_qualification(self):
        with tempfile.TemporaryDirectory() as root:
            paths = []
            for name, value in (("oracle", self.oracle), ("base", self.base), ("heretic", self.modified)):
                p = Path(root)/f"{name}.json"
                p.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
                paths.extend(["--"+name, str(p), "--"+name+"-sha256", hashlib.sha256(p.read_bytes()).hexdigest()])
            out = StringIO()
            with redirect_stdout(out):
                rc = main(["--pair", "qwen3-vl-2b", "--base-revision", A,
                           "--heretic-revision", B, *paths])
            self.assertEqual(rc, 0)
            result = json.loads(out.getvalue())
            self.assertFalse(result["model_inference_attested"])
            self.assertEqual(result["case_count"], 3)

if __name__ == "__main__":
    unittest.main()
