#!/usr/bin/env python3
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

def check(root: Path) -> bool:
    path=root/"speech.aiff"
    return path.is_file() and path.stat().st_size > 1000

def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        assert not check(root)
        (root/"speech.aiff").write_bytes(b"FORM"+b"x"*1200)
        assert check(root)
    print("PASS TTS mechanical artifact verifier self-test")
    return 0

if __name__=="__main__":
    if len(sys.argv)==2 and sys.argv[1]=="--self-test":
        raise SystemExit(self_test())
    if len(sys.argv)!=2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
