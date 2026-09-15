import json
import sys
from pathlib import Path

p = Path(sys.argv[1])
m = json.loads(p.read_text())
expected = {
    "torch": "2.5.1+cpu",
    "transformers": "4.46.3",
    "huggingface_hub": "0.26.2",
    "safetensors": "0.4.5",
    "jsonschema": "4.25.1",
}
assert m["schema_version"] == 1
assert isinstance(m["cache_hit"], bool)
assert float(m["setup_restore_install_seconds"]) > 0
assert m["cache_key"]
for name, version in expected.items():
    assert m["runtime"][name] == version, (name, m["runtime"][name], version)
assert m["pip_freeze_sha256"].startswith("sha256:")
assert m["torch_smoke_sha256"].startswith("sha256:")
print(json.dumps({"validated": True, "cache_hit": m["cache_hit"], "seconds": m["setup_restore_install_seconds"]}, sort_keys=True))
