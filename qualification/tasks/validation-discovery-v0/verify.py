#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

EXPECTED = {"entrypoint": "python scripts/validate.py"}

def check(root: Path) -> bool:
    path = root / "result.json"
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return value == EXPECTED

def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "result.json").write_text(json.dumps(EXPECTED), encoding="utf-8")
        assert check(root)
        (root / "result.json").write_text(json.dumps({"entrypoint":"./scripts/quick_check.sh"}), encoding="utf-8")
        assert not check(root)
    print("PASS verifier self-test")
    return 0

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
