#!/usr/bin/env python3
from __future__ import annotations
import sys, tempfile
from pathlib import Path

EXPECTED_ALPHA = "header\nMODE=strict\nfooter\n"
EXPECTED_BETA = "prefix\nSCALE=2\nsuffix\n"

def check(root: Path) -> bool:
    try:
        return (
            (root / "alpha.txt").read_text(encoding="utf-8") == EXPECTED_ALPHA
            and (root / "beta.txt").read_text(encoding="utf-8") == EXPECTED_BETA
            and sorted(p.name for p in root.iterdir() if p.is_file()) == ["alpha.txt","beta.txt"]
        )
    except Exception:
        return False

def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/"alpha.txt").write_text(EXPECTED_ALPHA,encoding="utf-8")
        (root/"beta.txt").write_text(EXPECTED_BETA,encoding="utf-8")
        assert check(root)
        (root/"beta.txt").write_text("prefix\nSCALE=1\nsuffix\n",encoding="utf-8")
        assert not check(root)
    print("PASS bounded multi-file replace verifier self-test")
    return 0

if __name__=="__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":
        raise SystemExit(self_test())
    if len(sys.argv)!=2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
