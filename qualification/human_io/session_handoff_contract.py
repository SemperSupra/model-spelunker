#!/usr/bin/env python3
"""R45 source-only, server-owned cross-device session context and replay contract.

Consumers can reattach READ-ONLY to the same externally authenticated session.
No local registry, new login/auth server, cross-device credential transfer,
approval, mutation or real agent process is implemented here.
"""
from __future__ import annotations
import hashlib
import json
import re

SCHEMA = "actor-cross-device-session-snapshot/v1"
CONTEXT_SLOTS = ("conversation", "workspace", "artifacts", "memory",
                 "tool_state", "pending_work", "approvals", "model", "dle")
EVENT_TYPES = {"message", "tool-call", "tool-result", "status", "artifact",
               "approval-request", "approval-decision", "context-change"}
RUN_STATES = {"idle", "running", "paused", "awaiting-approval", "unknown"}
OPAQUE = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_PAGE = 256

def _opaque(value):
    return isinstance(value, str) and bool(OPAQUE.fullmatch(value))

def _hex(value):
    return isinstance(value, str) and bool(HEX.fullmatch(value))

def _nonnegative(value):
    return type(value) is int and value >= 0

def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True,
                                    separators=(",", ":"), ensure_ascii=True)
                          .encode("utf-8")).hexdigest()

def check_snapshot(s: dict) -> dict:
    if not isinstance(s, dict) or set(s) != {
            "schema", "session", "context", "presentation", "admission"}:
        raise ValueError("unknown or missing snapshot fields")
    if s["schema"] != SCHEMA:
        raise ValueError("snapshot schema mismatch")
    session = s["session"]
    if not isinstance(session, dict) or set(session) != {
            "id", "owner_scope", "revision", "last_event_seq", "context_digest",
            "run_state"}:
        raise ValueError("session identity fields invalid")
    if not _opaque(session["id"]) or not _opaque(session["owner_scope"]):
        raise ValueError("session or scope identity invalid")
    if not _nonnegative(session["revision"]) or not _nonnegative(session["last_event_seq"]):
        raise ValueError("invalid monotonic revision/cursor")
    if session["run_state"] not in RUN_STATES:
        raise ValueError("run status invalid")
    manifest = s["context"]
    if not isinstance(manifest, dict) or set(manifest) != set(CONTEXT_SLOTS):
        raise ValueError("incomplete context manifest")
    for slot, ref in manifest.items():
        if ref is None:
            if slot == "conversation":
                raise ValueError("conversation context required")
            continue
        if not isinstance(ref, dict) or set(ref) != {"ref", "digest", "revision"}:
            raise ValueError("invalid context pointer")
        if not _opaque(ref["ref"]) or not _hex(ref["digest"]) or not _nonnegative(ref["revision"]):
            raise ValueError("unverified context pointer")
        # A pointer to approval history is NOT an approval token.
    if not _hex(session["context_digest"]) or session["context_digest"] != manifest_digest(manifest):
        raise ValueError("context digest mismatch")
    presentation = s["presentation"]
    if (not isinstance(presentation, dict) or set(presentation) != {
            "portable", "device_local_preferences", "content_truncated"} or
            presentation["portable"] is not True or
            presentation["device_local_preferences"] is not True or
            presentation["content_truncated"] is not False):
        raise ValueError("device-bound or truncated session content")
    admission = s["admission"]
    if (not isinstance(admission, dict) or set(admission) != {
            "authenticated_by_external_service", "grants_tool_authority",
            "carries_approval_token", "production_admitted"} or
            any(value is not False for value in admission.values())):
        raise ValueError("snapshot cannot grant trust")
    return {"schema": "actor-session-snapshot-critic/v1",
            "state": "CONTEXT_MANIFEST_CONSISTENT",
            "context_slots": len(CONTEXT_SLOTS),
            "session_id": session["id"], "revision": session["revision"],
            "tool_authority": "NOT_GRANTED"}

def make_reattach(snapshot: dict, after_seq: int) -> dict:
    check_snapshot(snapshot)
    current = snapshot["session"]
    if not _nonnegative(after_seq) or after_seq > current["last_event_seq"]:
        raise ValueError("cursor outside authoritative snapshot")
    return {"schema": "actor-session-reattach-request/v1",
            "operation": "read-only-reattach",
            "session_id": current["id"],
            "known_revision": current["revision"],
            "known_context_digest": current["context_digest"],
            "after_seq": after_seq,
            "approval_transfer": False,
            "tool_authority_transfer": False}

def observe_replay(snapshot: dict, request: dict, response: dict) -> dict:
    """Check an externally authorized replay; no actual auth is performed here."""
    check_snapshot(snapshot)
    if not isinstance(request,dict) or request != make_reattach(snapshot,request.get("after_seq")):
        raise ValueError("untrusted reattach request")
    if not isinstance(response,dict) or set(response)!={
            "schema","session_id","revision","context_digest","events","next_seq","has_more"}:
        raise ValueError("malformed replay page")
    s=snapshot["session"]
    if response["schema"]!="actor-session-replay-page/v1" or response["session_id"]!=s["id"]:
        raise ValueError("wrong session replay")
    if response["revision"]!=s["revision"] or response["context_digest"]!=s["context_digest"]:
        raise ValueError("STALE_SNAPSHOT_REQUIRES_AUTHORITATIVE_REFRESH")
    events=response["events"]
    if not isinstance(events,list) or len(events)>MAX_PAGE:
        raise ValueError("unbounded event replay")
    next_seq=request["after_seq"]
    for event in events:
        if not isinstance(event,dict) or set(event)!={"seq","kind","digest"}:
            raise ValueError("malformed event ref")
        if not _nonnegative(event["seq"]) or event["seq"]!=next_seq+1:
            raise ValueError("replay gap, duplicate or reorder")
        if event["kind"] not in EVENT_TYPES or not _hex(event["digest"]):
            raise ValueError("unverified event ref")
        next_seq=event["seq"]
    if type(response["next_seq"]) is not int or response["next_seq"]!=next_seq:
        raise ValueError("incorrect replay cursor")
    if type(response["has_more"]) is not bool or next_seq > s["last_event_seq"]:
        raise ValueError("incorrect replay boundary")
    if response["has_more"] != (next_seq < s["last_event_seq"]):
        raise ValueError("incomplete event replay cannot claim caught up")
    return {"schema":"actor-session-reattach-observation/v1",
            "session_id":s["id"],"revision":s["revision"],
            "context_digest":s["context_digest"],
            "next_seq":next_seq,"caught_up":not response["has_more"],
            "context_available":True, "device_preferences_portable":False,
            "approval_transferred":False,"tool_authority_granted":False,
            "remote_authentication_verified":False,
            "actor_task_qualified":False}
