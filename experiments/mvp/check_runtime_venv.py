import json
import sys
from pathlib import Path

m = json.loads(Path(sys.argv[1]).read_text())
expected = {
    "torch": "2.5.1+cpu",
    "transformers": "4.46.3",
    "huggingface_hub": "0.26.2",
    "safetensors": "0.4.5",
    "jsonschema": "4.25.1",
}
assert m["schema_version"] == 1
assert isinstance(m["cache_hit"], bool)
assert float(m["restore_or_build_to_ready_seconds"]) > 0
assert int(m["venv_size_bytes"]) > 0
assert ".runtime-venv" in m["runtime"]["python_executable"]
for name, version in expected.items():
    assert m["runtime"][name] == version, (name, m["runtime"][name], version)
assert m["pip_freeze_sha256"].startswith("sha256:")
assert m["integer_torch_smoke_sha256"].startswith("sha256:")
print(json.dumps({
    "validated": True,
    "cache_hit": m["cache_hit"],
    "seconds": m["restore_or_build_to_ready_seconds"],
    "venv_size_bytes": m["venv_size_bytes"],
    "environment_hash": m["pip_freeze_sha256"],
    "integer_smoke": m["integer_torch_smoke_sha256"],
}, sort_keys=True))
