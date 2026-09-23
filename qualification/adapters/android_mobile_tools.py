#!/usr/bin/env python3
"""Bounded Android UI tools for Model Spelunker actor qualification."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any

try:
    import aisuite as ai
except Exception:
    ai = None

_ACTIONS: list[dict[str, Any]] = []
_BOUNDS = re.compile(r"^\[(\d+),(\d+)\]\[(\d+),(\d+)\]$")


def _adb_prefix() -> list[str]:
    adb = os.environ.get("MODEL_SPELUNKER_ADB_BIN")
    serial = os.environ.get("MODEL_SPELUNKER_ANDROID_SERIAL")
    if not adb or not serial:
        raise RuntimeError("Android qualification device is not configured")
    prefix: list[str] = []
    if os.environ.get("MODEL_SPELUNKER_ANDROID_USE_SUDO") == "1":
        prefix += ["sudo", "-n"]
    prefix += [adb, "-s", serial]
    return prefix


def _run(args: list[str], *, timeout: int = 20) -> str:
    cp = subprocess.run(
        _adb_prefix() + args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if cp.returncode != 0:
        raise RuntimeError(
            f"bounded adb operation failed rc={cp.returncode}: {cp.stderr[-600:]}"
        )
    return cp.stdout.strip()


def _record(name: str, **fields: Any) -> None:
    _ACTIONS.append({"index": len(_ACTIONS) + 1, "tool": name, **fields})


def parse_ui_xml(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    nodes: list[dict[str, Any]] = []
    for node in root.iter("node"):
        attrs = node.attrib
        text = attrs.get("text", "")
        desc = attrs.get("content-desc", "")
        rid = attrs.get("resource-id", "")
        clickable = attrs.get("clickable") == "true"
        scrollable = attrs.get("scrollable") == "true"
        if not (text or desc or rid or clickable or scrollable):
            continue
        bounds = attrs.get("bounds", "")
        m = _BOUNDS.match(bounds)
        item: dict[str, Any] = {
            "text": text[:160],
            "content_desc": desc[:160],
            "resource_id": rid[:200],
            "class": attrs.get("class", "")[:160],
            "clickable": clickable,
            "scrollable": scrollable,
            "enabled": attrs.get("enabled") == "true",
            "checked": attrs.get("checked") == "true",
        }
        if m:
            item["bounds"] = [int(v) for v in m.groups()]
        nodes.append(item)
        if len(nodes) >= 120:
            break
    return {"schema_version": 1, "nodes": nodes, "truncated": len(nodes) >= 120}


def mobile_observe_ui() -> str:
    """Return a bounded JSON view of visible Android UI nodes."""
    _run(["shell", "uiautomator", "dump", "/sdcard/model-spelunker-window.xml"])
    xml_text = _run(["exec-out", "cat", "/sdcard/model-spelunker-window.xml"])
    observed = parse_ui_xml(xml_text)
    _record("mobile_observe_ui", visible_nodes=len(observed["nodes"]))
    return json.dumps(observed, sort_keys=True)


def mobile_tap(x: int, y: int) -> str:
    """Tap one screen coordinate on the disposable Android emulator."""
    if not (0 <= x <= 5000 and 0 <= y <= 5000):
        raise ValueError("tap coordinate outside bounded screen envelope")
    _run(["shell", "input", "tap", str(x), str(y)])
    time.sleep(0.45)
    _record("mobile_tap", x=x, y=y)
    return "ok"


def mobile_swipe(start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> str:
    """Swipe between two bounded screen coordinates."""
    values = (start_x, start_y, end_x, end_y)
    if any(v < 0 or v > 5000 for v in values):
        raise ValueError("swipe coordinate outside bounded screen envelope")
    duration_ms = max(100, min(int(duration_ms), 1500))
    _run([
        "shell", "input", "swipe", str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)
    ])
    time.sleep(0.55)
    _record(
        "mobile_swipe", start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y,
        duration_ms=duration_ms,
    )
    return "ok"


def mobile_back() -> str:
    """Press Android Back once."""
    _run(["shell", "input", "keyevent", "4"])
    time.sleep(0.4)
    _record("mobile_back")
    return "ok"


def mobile_launch_settings() -> str:
    """Launch the Android Settings home screen."""
    _run(["shell", "am", "start", "-a", "android.settings.SETTINGS"])
    time.sleep(0.7)
    _record("mobile_launch_settings")
    return "ok"


def mobile_open_section(section: str) -> str:
    """Open one explicitly allowed Settings section; only `date_time` is allowed."""
    allowed = {"date_time": "android.settings.DATE_SETTINGS"}
    action = allowed.get(section)
    if action is None:
        raise ValueError(f"unsupported bounded Settings section: {section}")
    _run(["shell", "am", "start", "-a", action])
    time.sleep(0.7)
    _record("mobile_open_section", section=section)
    return "ok"


def mobile_action_log() -> list[dict[str, Any]]:
    return [dict(item) for item in _ACTIONS]


def mobile_tool_functions() -> list:
    funcs = [
        mobile_observe_ui,
        mobile_tap,
        mobile_swipe,
        mobile_back,
        mobile_launch_settings,
        mobile_open_section,
    ]
    if ai is None:
        return funcs
    for fn in funcs:
        fn.__aisuite_tool_metadata__ = ai.ToolMetadata(
            name=fn.__name__,
            category="mobile",
            risk_level="medium",
            requires_approval=False,
            capabilities=["mobile-ui"],
        )
    return funcs
