#!/usr/bin/env python3
"""Deterministic reference policy for Android embodied-task calibration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from android_mobile_tools import mobile_launch_settings, mobile_observe_ui, mobile_swipe, mobile_tap


def nodes() -> list[dict]:
    return json.loads(mobile_observe_ui())["nodes"]


def center(node: dict) -> tuple[int, int]:
    x1, y1, x2, y2 = node["bounds"]
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_text(candidates: tuple[str, ...], *, max_scrolls: int = 5) -> dict:
    wanted = tuple(x.casefold() for x in candidates)
    for attempt in range(max_scrolls + 1):
        current = nodes()
        for node in current:
            text = str(node.get("text") or "").strip()
            folded = text.casefold()
            if folded and any(folded == target or target in folded for target in wanted):
                if "bounds" in node:
                    return node
        if attempt != max_scrolls:
            mobile_swipe(540, 1850, 540, 450, 350)
    raise RuntimeError(f"reference policy could not find any of: {candidates}")


def tap_label(*labels: str) -> dict:
    node = find_text(tuple(labels))
    x, y = center(node)
    mobile_tap(x, y)
    return node


def main() -> int:
    _ = sys.stdin.read()
    mobile_launch_settings()
    tap_label("System", "System & updates")
    tap_label("Date & time")
    target = find_text(("Use 24-hour format",))
    if not bool(target.get("checked")):
        x, y = center(target)
        mobile_tap(x, y)
    Path("result.json").write_text(
        json.dumps({"schema_version": 1, "completed": True}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
