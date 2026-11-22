#!/usr/bin/env python3
"""R42 human I/O capability and event observation contract, stdlib only.

Not a driver, HID enumerator, remote-control service or authorization system.
A device-origin event is untrusted input, NEVER approval for tool execution.
"""
from __future__ import annotations
import hashlib
import json
import re
from collections import Counter

SCHEMA = "actor-human-io-observation/v1"
PLATFORMS = {"windows", "macos", "linux", "android", "ios", "ipados", "chromeos",
             "browser", "server-headless", "xr"}
ENVIRONMENTS = {"physical-device", "vm-guest", "container", "remote-session", "hosted-ci"}
TRANSPORTS = {"usb-hid", "bluetooth-hid", "i2c-hid", "spi-hid", "os-accessibility",
              "os-sensor", "os-media", "network-remote", "virtual", "none"}
STATES = {"unknown", "advertised", "observed", "exercised", "unsupported"}
CHANNELS = {
 "keyboard", "mouse", "trackpad", "trackball", "touch", "pen", "stylus", "graphics-tablet",
 "gamepad", "joystick", "wheel-pedals", "switch-access", "adaptive-controller",
 "braille-display", "screen-reader", "screen-magnifier", "eye-gaze", "head-tracking",
 "hand-gesture", "motion-controller", "spatial-xr", "voice", "speech-recognition",
 "microphone", "camera", "photo-picker", "document-scanner", "barcode-scanner",
 "midi-controller", "haptic-feedback", "audio-output", "visual-display",
 "captioning", "led-status", "tactile-output", "sip-puff"
}
SENSITIVE = {"microphone", "camera", "photo-picker", "document-scanner", "eye-gaze",
             "head-tracking", "speech-recognition", "voice", "hand-gesture", "spatial-xr"}
# An interaction may lead to a REQUEST for review, but NEVER to approval without
# independently authenticated identity and exact action-scoped authorization.
INTENTS = {"text", "point", "select", "navigate", "inspect", "dictate", "attach",
           "request-approval", "cancel", "status"}
SAFE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")

def invalid(reason: str):
    raise ValueError(reason)

def _name(v):
    return isinstance(v, str) and bool(SAFE.fullmatch(v))

def validate_profile(p: dict) -> dict:
    if not isinstance(p, dict) or set(p) != {"schema","profile_id","platform","environment",
                                              "entries","authority"} or p["schema"] != SCHEMA:
        invalid("wrong profile schema")
    if not _name(p["profile_id"]) or p["platform"] not in PLATFORMS or p["environment"] not in ENVIRONMENTS:
        invalid("invalid platform or source profile")
    authority = p["authority"]
    if not isinstance(authority, dict) or set(authority) != {
        "allows_injected_human_approval","grants_tool_authority","production_admitted"} or any(
        authority[k] is not False for k in authority):
        invalid("HID cannot authenticate or grant external authority")
    if not isinstance(p["entries"], list) or not p["entries"]:
        invalid("empty channel observations")
    seen = set()
    for e in p["entries"]:
        if not isinstance(e, dict) or set(e) != {
            "channel","transport","state","scope","evidence_sha256","permission"}:
            invalid("malformed channel observation")
        ch, transport, state = e["channel"], e["transport"], e["state"]
        if ch not in CHANNELS or transport not in TRANSPORTS or state not in STATES or ch in seen:
            invalid("unsupported or duplicate device channel")
        seen.add(ch)
        if e["scope"] not in ("local", "remote", "synthetic", "unavailable"):
            invalid("invalid source scope")
        if e["permission"] not in ("not-requested","denied","granted","not-applicable"):
            invalid("invalid permission state")
        digest = e["evidence_sha256"]
        if state in ("observed","exercised") and (not isinstance(digest,str) or not SHA.fullmatch(digest)):
            invalid("positive observation without immutable evidence")
        if state in ("unknown","advertised","unsupported") and digest is not None:
            invalid("unsupported or advertised feature cannot claim tested evidence")
        if e["scope"] == "synthetic" and state == "exercised":
            # Exercised synthetic fixtures belong to simulation evidence, NOT device HIL.
            invalid("synthetic cannot claim physical HID exercise")
        if ch in SENSITIVE and e["permission"] == "granted" and state not in ("observed","exercised"):
            invalid("consent not demonstrated by discovery flags")
    return {"schema":"actor-human-io-profile-critic/v1","state":"SOURCE_ONLY_VALID",
            "channel_count":len(seen),
            "physical_exercise_claims":sum(e["state"]=="exercised" for e in p["entries"]),
            "human_approval_authorized":False,"production_admitted":False}

def normalize_event(profile: dict, event: dict) -> dict:
    """Normalize textless device intent metadata; no raw images/audio/coordinates."""
    validate_profile(profile)
    if not isinstance(event,dict) or set(event) != {"channel","intent","source","sequence"}:
        invalid("raw payload or unexpected event fields")
    if event["intent"] not in INTENTS or event["channel"] not in CHANNELS:
        invalid("invalid human intent")
    if event["source"] not in ("human-device", "assistive-device", "remote", "synthetic"):
        invalid("unknown attribution")
    if type(event["sequence"]) is not int or not 0 <= event["sequence"] < 2**53:
        invalid("invalid sequence")
    matches = [e for e in profile["entries"] if e["channel"] == event["channel"]]
    if len(matches) != 1 or matches[0]["state"] not in ("observed","exercised"):
        invalid("channel not observed, no interaction available")
    e = matches[0]
    if event["source"] == "synthetic" and e["scope"] != "synthetic":
        invalid("synthetic/hardware source mismatch")
    if event["source"] != "synthetic" and e["scope"] == "synthetic":
        invalid("synthetic input falsely treated as physical user")
    if event["channel"] in SENSITIVE and e["permission"] != "granted":
        invalid("media/sensor access not consented")
    # Never elevate to approved tool action even for an accessibility switch or remote pointer.
    return {"schema":"actor-human-io-intent/v1","profile_id":profile["profile_id"],
            "channel":event["channel"],"intent":event["intent"],
            "source":event["source"],"sequence":event["sequence"],
            "authorization":"UNTRUSTED_INPUT_ONLY","tool_execution_approved":False}

def digest_bytes(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def inventory_summary(profiles:list[dict])->dict:
    counts=Counter()
    for p in profiles:
        validate_profile(p)
        for e in p["entries"]:
            counts[e["state"]]+=1
    return {"profiles":len(profiles),"observations_by_state":dict(sorted(counts.items())),
            "production_admission":"NOT_GRANTED"}
