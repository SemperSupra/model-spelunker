#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
from pathlib import Path


def load(root: Path):
    path = root / "src" / "retry.py"
    spec = importlib.util.spec_from_file_location("retry_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load retry module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.backoff_seconds


def check(root: Path) -> bool:
    try:
        fn = load(root)
        sig = str(inspect.signature(fn))
        if sig != "(attempt: int, base: int = 2, cap: int = 30) -> int":
            return False

        cases = [
            ((1,), 1),
            ((2,), 2),
            ((3,), 4),
            ((5,), 16),
            ((6,), 30),
            ((4, 3, 20), 20),
            ((2, 5, 99), 5),
            ((1, 7, 3), 1),
        ]
        for args, expected in cases:
            value = fn(*args)
            if type(value) is not int or value != expected:
                return False

        for invalid in (0, -1, -7):
            try:
                fn(invalid)
            except ValueError:
                pass
            else:
                return False
        return True
    except Exception:
        return False


def self_test() -> int:
    good = """def backoff_seconds(attempt: int, base: int = 2, cap: int = 30) -> int:
    if attempt <= 0:
        raise ValueError("attempt must be positive")
    return min(cap, base ** (attempt - 1))
"""
    bad = """def backoff_seconds(attempt: int, base: int = 2, cap: int = 30) -> int:
    return min(cap, base ** attempt)
"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        path = root / "src" / "retry.py"
        path.write_text(good, encoding="utf-8")
        assert check(root)
        path.write_text(bad, encoding="utf-8")
        assert not check(root)
    print("PASS boundary-bugfix verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
