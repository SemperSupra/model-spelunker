#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def output_ok(root: Path) -> bool:
    try:
        value = json.loads((root / "result.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    return set(value) == {"schema_version", "completed"} and value == {
        "schema_version": 1,
        "completed": True,
    }


def adb_prefix() -> list[str]:
    adb = os.environ.get("MODEL_SPELUNKER_ADB_BIN")
    serial = os.environ.get("MODEL_SPELUNKER_ANDROID_SERIAL")
    if not adb or not serial:
        raise RuntimeError("missing verifier Android device environment")
    prefix: list[str] = []
    if os.environ.get("MODEL_SPELUNKER_ANDROID_USE_SUDO") == "1":
        prefix += ["sudo", "-n"]
    return prefix + [adb, "-s", serial]


def device_24h_value() -> str:
    cp = subprocess.run(
        adb_prefix() + ["shell", "settings", "get", "system", "time_12_24"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"verifier adb failed: {cp.stderr[-400:]}")
    return cp.stdout.strip()


def check(root: Path) -> bool:
    return output_ok(root) and device_24h_value() == "24"


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "result.json").write_text(
            '{"schema_version":1,"completed":true}\n', encoding="utf-8"
        )
        assert output_ok(root)
        (root / "result.json").write_text(
            '{"schema_version":1,"completed":false}\n', encoding="utf-8"
        )
        assert not output_ok(root)
        (root / "result.json").write_text(
            '{"schema_version":1,"completed":true,"extra":1}\n', encoding="utf-8"
        )
        assert not output_ok(root)
    print("PASS android-settings-24h verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    try:
        ok = check(Path(sys.argv[1]))
    except Exception as exc:
        print(f"VERIFIER_ERROR={type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(0 if ok else 1)
