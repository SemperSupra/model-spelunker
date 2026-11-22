#!/usr/bin/env python3
"""Pi RPC JSONL envelope and lifecycle observer; no actor/process/network effects.

Only an independently admitted transport may use this to drive a real agent.
Prompt acceptance and agent_settled are NOT task success or tool approval.
Upstream evidence: earendil-works/pi packages/coding-agent/docs/rpc.md
and rpc-commands.md, pinned source census in R35.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

MAX_MESSAGE = 8192
MAX_IMAGE_BYTES = 1_048_576
MAX_RECORD_BYTES = 2_097_152
ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}

def prompt_record(request_id: str, message: str, images: list[dict] | None = None) -> bytes:
    if not isinstance(request_id, str) or not ID.fullmatch(request_id):
        raise ValueError("invalid command correlation id")
    if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > MAX_MESSAGE:
        raise ValueError("invalid or over-budget message")
    # Extension/skill/template commands can expand to additional authority.
    if message.lstrip().startswith("/"):
        raise ValueError("unqualified extension/skill command")
    payload = {"id": request_id, "type": "prompt", "message": message}
    if images is not None:
        if not isinstance(images, list) or len(images) > 2:
            raise ValueError("image count over budget")
        sanitized = []
        for img in images:
            if not isinstance(img, dict) or set(img) != {"data", "mimeType", "type"}:
                raise ValueError("invalid image record")
            if img["type"] != "image" or img["mimeType"] not in IMAGE_TYPES:
                raise ValueError("unsupported image type")
            if not isinstance(img["data"], str) or len(img["data"]) > (MAX_IMAGE_BYTES * 4 // 3 + 16):
                raise ValueError("invalid image payload")
            try:
                decoded = base64.b64decode(img["data"], validate=True)
            except Exception as exc:
                raise ValueError("invalid base64 image") from exc
            if not decoded or len(decoded) > MAX_IMAGE_BYTES:
                raise ValueError("image exceeds byte ceiling")
            sanitized.append(dict(img))
        payload["images"] = sanitized
    encoded = (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError("oversize RPC command")
    return encoded

def parse_jsonl(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n"):
        raise ValueError("framing requires bounded LF-terminated bytes")
    raw = raw[:-1].removesuffix(b"\r")
    if b"\n" in raw or b"\r" in raw:
        raise ValueError("multiple records or embedded bare newline")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid JSONL record") from exc
    if not isinstance(record, dict) or not isinstance(record.get("type"), str):
        raise ValueError("invalid RPC object")
    return record

@dataclass
class PromptObservation:
    request_id: str
    accepted: bool = False
    disposition: str | None = None
    settled: bool = False
    response_seen: bool = False
    rejection: bool = False
    event_types: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not ID.fullmatch(self.request_id):
            raise ValueError("invalid request id")

    def consume(self, record: dict) -> None:
        typ = record.get("type")
        if typ == "response":
            if record.get("id") != self.request_id or record.get("command") != "prompt":
                raise ValueError("uncorrelated prompt response")
            if self.response_seen or type(record.get("success")) is not bool:
                raise ValueError("duplicate or malformed prompt response")
            self.response_seen = True
            self.accepted = record["success"]
            self.rejection = not self.accepted
            if self.accepted:
                disposition = record.get("data", {}).get("disposition")
                if disposition not in ("started", "queued", "handled"):
                    raise ValueError("unknown successful prompt disposition")
                self.disposition = disposition
            return
        if not isinstance(typ, str) or len(typ) > 80:
            raise ValueError("invalid event type")
        if len(self.event_types) >= 2048:
            raise ValueError("event observation ceiling")
        self.event_types.append(typ)
        if typ == "agent_settled":
            self.settled = True

    def receipt(self) -> dict:
        return {
            "schema": "pi-rpc-prompt-observation/v1",
            "command_id": self.request_id,
            "prompt_accepted": self.accepted,
            "disposition": self.disposition,
            "agent_settled_observed": self.settled,
            "event_count": len(self.event_types),
            "task_oracle_passed": False,
            "model_tool_qualified": False,
            "production_admitted": False,
        }
