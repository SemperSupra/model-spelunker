#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


EXPECTED = {
    "classification": "SIMPLE_REQUEST",
    "code": "T3-CASCADE",
}


def check(root: Path) -> bool:
    try:
        path = root / "result.json"
        if not path.is_file():
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
        return (
            isinstance(value, dict)
            and set(value) == set(EXPECTED)
            and value == EXPECTED
            and all(isinstance(v, str) for v in value.values())
        )
    except Exception:
        return False


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "result.json").write_text(json.dumps(EXPECTED) + "\n", encoding="utf-8")
        assert check(root)
        (root / "result.json").write_text(
            json.dumps({"classification": "RECIPROCAL_DUTY", "code": "Q7-MERIDIAN"}) + "\n",
            encoding="utf-8",
        )
        assert not check(root)
    print("PASS speech-slu-counterfactual-v0 verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
