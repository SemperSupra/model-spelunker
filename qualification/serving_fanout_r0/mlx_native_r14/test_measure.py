import json
import math
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from measure import InvalidModelObservation, manifest, project_response, make_prompt

def response(**kw):
    obj={"text":"PRIVATE_OUTPUT_DO_NOT_SAVE","prompt_tokens":128,
         "generation_tokens":12,"prompt_tps":400.0,"generation_tps":30.0,
         "peak_memory":1.25,"finish_reason":"length"}
    obj.update(kw)
    return SimpleNamespace(**obj)

class MLXPhaseSourceTests(unittest.TestCase):
    def test_native_fields_not_text_or_sse_frames(self):
        result=project_response(response(),300,680,1.0,.1)
        self.assertEqual(result["prompt_tokens_native"],128)
        self.assertEqual(result["output_tokens_native"],12)
        self.assertEqual(result["prefill_ms_derived_from_native_tps"],320)
        self.assertEqual(result["decode_ms_derived_from_native_tps"],400)
        self.assertNotIn("PRIVATE_OUTPUT_DO_NOT_SAVE",json.dumps(result))
        self.assertEqual(result["active_mlx_allocator_gb"],1.0)

    def test_invalid_fields_rejected(self):
        for obj in (response(prompt_tps=0),response(generation_tps=float("nan")),
                    response(prompt_tokens=True),response(generation_tokens=-1),
                    response(peak_memory=-1),response(finish_reason=None)):
            with self.subTest(obj=obj),self.assertRaises(InvalidModelObservation):
                project_response(obj,200,400)
        with self.assertRaises(InvalidModelObservation):
            project_response(response(),500,400)

    def test_manifest_is_component_bound_not_alias(self):
        with tempfile.TemporaryDirectory() as d:
            model=Path(d)
            (model/"weights.safetensors").write_bytes(b"synthetic-weight")
            (model/"config.json").write_text('{"synthetic": true}')
            (model/"README.md").write_text("unrelated metadata")
            first=manifest(model)
            self.assertEqual(first["weight_file_count"],1)
            (model/"README.md").write_text("changed docs")
            self.assertEqual(first,manifest(model))
            (model/"weights.safetensors").write_bytes(b"new-weight")
            self.assertNotEqual(first["component_manifest_sha256"],
                                manifest(model)["component_manifest_sha256"])

    def test_requires_weights_and_does_not_claim_task_quality(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(InvalidModelObservation):
                manifest(d)
        self.assertIn("Synthetic evaluation",make_prompt(3))

if __name__=="__main__":
    unittest.main()
