#!/usr/bin/env python3
"""R44 device-capability-driven presentation projection, not agent authority.

Presentation changes the *view* of one immutable task/session, not prompts,
tools, memory, answer semantics, task history or approval policy.
No OS enumeration; accepts only bounded non-identifying observations.
"""
from __future__ import annotations
import json

TIERS = ("compact", "balanced", "workspace")
MODES = ("conversation", "review", "detail")
OUTPUTS = ("text", "speech", "visual", "braille", "captions", "haptics")
INPUTS = ("keyboard", "pointer", "touch", "pen", "voice", "switch", "braille", "gamepad", "gaze")
MAX_DISPLAYS = 8

def check(v):
    if not isinstance(v,dict) or set(v) != {
        "schema","displays","viewport","inputs","outputs","preferences","observation"}:
        raise ValueError("invalid presentation capability schema")
    if v["schema"]!="actor-presentation-capabilities/v1" or v["observation"] not in ("synthetic","os-observed","browser-observed"):
        raise ValueError("unknown observation origin")
    screens=v["displays"]
    if not isinstance(screens,list) or not 0 < len(screens) <= MAX_DISPLAYS:
        raise ValueError("display topology invalid")
    for s in screens:
        if not isinstance(s,dict) or set(s)!={"width","height","scale","primary"}:
            raise ValueError("display fields invalid")
        if type(s["width"]) is not int or not 160 <= s["width"] <= 16384:
            raise ValueError("width out of bounds")
        if type(s["height"]) is not int or not 160 <= s["height"] <= 16384:
            raise ValueError("height out of bounds")
        if type(s["scale"]) not in (int,float) or not 0.5 <= s["scale"] <= 5:
            raise ValueError("scale out of bounds")
        if type(s["primary"]) is not bool:
            raise ValueError("primary flag invalid")
    if sum(s["primary"] for s in screens)!=1:
        raise ValueError("exactly one primary display")
    vp=v["viewport"]
    if not isinstance(vp,dict) or set(vp)!={"width","height","font_scale","reduced_motion"}:
        raise ValueError("viewport invalid")
    for k in ("width","height"):
        if type(vp[k]) is not int or not 160 <= vp[k] <= 16384:
            raise ValueError("viewport size invalid")
    if type(vp["font_scale"]) not in (int,float) or not 0.5 <= vp["font_scale"] <= 4:
        raise ValueError("font scale invalid")
    if type(vp["reduced_motion"]) is not bool:
        raise ValueError("reduced motion flag invalid")
    if not isinstance(v["inputs"],list) or any(x not in INPUTS for x in v["inputs"]) or len(set(v["inputs"]))!=len(v["inputs"]):
        raise ValueError("invalid input channels")
    if not isinstance(v["outputs"],list) or "text" not in v["outputs"] or any(x not in OUTPUTS for x in v["outputs"]) or len(set(v["outputs"]))!=len(v["outputs"]):
        raise ValueError("invalid output channels")
    p=v["preferences"]
    if not isinstance(p,dict) or set(p)!={"mode","density","speech_enabled","details_on_demand"}:
        raise ValueError("preferences invalid")
    if p["mode"] not in ("auto",)+MODES or p["density"] not in ("auto",)+TIERS:
        raise ValueError("unknown user override")
    if type(p["speech_enabled"]) is not bool or type(p["details_on_demand"]) is not bool:
        raise ValueError("preferences malformed")
    return v

def project(v, session):
    check(v)
    if not isinstance(session,dict) or set(session)!={"id","revision","task_sha256"}:
        raise ValueError("immutable session identity missing")
    if not isinstance(session["id"],str) or not 1 <= len(session["id"]) <= 80:
        raise ValueError("invalid session ID")
    if type(session["revision"]) is not int or session["revision"] < 0:
        raise ValueError("invalid session revision")
    digest=session["task_sha256"]
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid immutable task reference")
    p=v["preferences"];vp=v["viewport"]
    effective_width=vp["width"]/vp["font_scale"]
    tier="compact" if effective_width<640 else ("balanced" if effective_width<1120 else "workspace")
    if p["density"]!="auto":
        tier=p["density"]
    mode=("conversation" if tier=="compact" else ("review" if tier=="balanced" else "detail"))
    if p["mode"]!="auto":
        mode=p["mode"]
    # Information density is not the same as a claim that any task or evidence was dropped.
    return {
        "schema":"actor-presentation-projection/v1",
        "session":dict(session),
        "tier":tier,"default_mode":mode,"display_count":len(v["displays"]),
        "layout":{
            "navigation":"bottom-or-drawer" if tier=="compact" else "side-rail",
            "panes":1 if tier=="compact" else (2 if tier=="balanced" else min(4,len(v["displays"])+1)),
            "detail_access":"expandable" if tier=="compact" else "parallel-or-expandable",
            "controls":"large-targets" if tier=="compact" or "touch" in v["inputs"] else "pointer-keyboard",
            "motion":"reduced" if vp["reduced_motion"] else "system-default",
        },
        "speech_suggested":bool(p["speech_enabled"] and "voice" in v["inputs"] and "speech" in v["outputs"]),
        "details_available":True,
        "hidden_task_content":False,
        "authorization_changed":False,
        "tools_changed":False,
        "data_transmitted":False,
        "production_admitted":False,
    }
