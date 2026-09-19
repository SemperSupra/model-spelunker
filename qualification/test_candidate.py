#!/usr/bin/env python3
"""Test-only candidate used to prove the qualification runner contract."""

from pathlib import Path

Path("value.txt").write_text("READY\n", encoding="utf-8")
