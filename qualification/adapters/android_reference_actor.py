#!/usr/bin/env python3
"""Deterministic reference policy for Android embodied-task calibration."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from android_mobile_tools import mobile_launch_settings, mobile_observe_ui, mobile_swipe, mobile_tap


def nodes() -> list[dict]:
    return json.loads(mobile_observe_ui())["nodes"]


def center(node: dict) -> tuple[int, int]:
    x1, y1, x2, y2 = node["bounds"]
    return (x1 + x2) // 2, (y1 + y2) // 2


def _matches(node: dict, wanted: tuple[str, ...]) -> bool:
    for field in ("text", "content_desc"):
        value = str(node.get(field) or "").strip().casefold()
        if value and any(value == target or target in value for target in wanted):
            return True
    return False


def _reset_to_top() -> None:
    # Settings may restore list position. Bound the reset rather than assuming launch
    # always starts at the top of the preference hierarchy.
    for _ in range(5):
        mobile_swipe(540, 500, 540, 1900, 300)
    time.sleep(0.8)


def find_text(candidates: tuple[str, ...], *, max_scrolls: int = 10) -> dict:
    wanted = tuple(x.casefold() for x in candidates)
    seen: list[str] = []
    for attempt in range(max_scrolls + 1):
        current = nodes()
        for node in current:
            for field in ("text", "content_desc"):
                value = str(node.get(field) or "").strip()
                if value and value not in seen:
                    seen.append(value)
            if _matches(node, wanted) and "bounds" in node:
                return node
        if attempt != max_scrolls:
            mobile_swipe(540, 1850, 540, 450, 350)
    print(
        "REFERENCE_VISIBLE_LABELS=" + json.dumps(seen[-80:], ensure_ascii=False),
        file=sys.stderr,
        flush=True,
    )
    raise RuntimeError(f"reference policy could not find any of: {candidates}")


def tap_label(*labels: str) -> dict:
    node = find_text(tuple(labels))
    x, y = center(node)
    mobile_tap(x, y)
    time.sleep(0.5)
    return node


def main() -> int:
    _ = sys.stdin.read()
    mobile_launch_settings()
    time.sleep(1.0)
    _reset_to_top()
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
