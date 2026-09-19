#!/usr/bin/env python3
"""Test-only failing candidate used to prove negative-evidence preservation."""

from pathlib import Path

Path("value.txt").write_text("NOT_READY\n", encoding="utf-8")
