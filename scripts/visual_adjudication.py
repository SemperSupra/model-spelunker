#!/usr/bin/env python3
"""Post-blind reconciliation/adjudication contract.

The blind human ledger, seed reference, automated evidence, adjudication, and any
future gold layer remain distinct. This module never creates gold labels.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from visual_concept_worker_core import canonical_digest


DECISIONS = {"supported", "contradicted", "unknown", "abstain", "needs_followup"}
SUBJECT_TYPES = {"concept_id", "human_statement"}
ADJUDICATION_KEYS = {
    "asset_id",
    "subject_type",
    "subject",
    "decision",
    "evidence_refs",
    "note",
    "idempotency_key",
}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"non-object JSONL row at line {line_number}")
        rows.append(value)
    return rows


def verify_blind_snapshot(session_path: str | Path, ledger_path: str | Path) -> dict[str, Any]:
    session_path = Path(session_path)
    ledger_path = Path(ledger_path)
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assets = session.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("blind session has no assets")
    by_asset: dict[str, str] = {}
    for row in assets:
        if not isinstance(row, dict):
            raise ValueError("invalid blind session asset")
        asset_id = str(row.get("asset_id") or "")
        sha = str(row.get("sha256") or "")
        if not asset_id or len(sha) != 64:
            raise ValueError("blind session asset missing identity")
        if asset_id in by_asset:
            raise ValueError("duplicate blind session asset")
        by_asset[asset_id] = sha

    expected_session_digest = canonical_digest(session)
    events = _read_jsonl(ledger_path)
    previous = None
    first_pass: dict[str, dict[str, Any]] = {}
    for event in events:
        supplied_digest = event.get("event_digest")
        computed = canonical_digest({k: v for k, v in event.items() if k != "event_digest"})
        if event.get("previous_event_digest") != previous or supplied_digest != computed:
            raise ValueError("blind human ledger integrity failure")
        previous = supplied_digest
        if event.get("session_digest") != expected_session_digest:
            raise ValueError("blind human ledger session mismatch")
        if event.get("layer") != "human" or event.get("ground_truth") is not False:
            raise ValueError("blind event authority boundary violated")
        asset_id = str(event.get("asset_id") or "")
        if asset_id not in by_asset or event.get("input_sha256") != by_asset[asset_id]:
            raise ValueError("blind event asset identity mismatch")
        if event.get("operation") == "reconciliation_exposed":
            raise ValueError("blind snapshot already contains reconciliation exposure")
        if event.get("operation") == "first_pass":
            if asset_id in first_pass:
                raise ValueError("duplicate blind first-pass event")
            if event.get("evidence_exposure") != "blind":
                raise ValueError("first-pass event is not blind")
            first_pass[asset_id] = event

    if set(first_pass) != set(by_asset):
        raise ValueError("blind first pass is incomplete")

    return {
        "session": session,
        "session_sha256": sha256_file(session_path),
        "session_digest": expected_session_digest,
        "ledger_sha256": sha256_file(ledger_path),
        "ledger_tail_digest": previous,
        "assets": [{"asset_id": asset_id, "sha256": by_asset[asset_id]} for asset_id in sorted(by_asset)],
        "first_pass": first_pass,
    }


def verify_reconciliation_queue(path: str | Path, assets: list[dict[str, str]]) -> dict[str, Any]:
    path = Path(path)
    queue = json.loads(path.read_text(encoding="utf-8"))
    supplied = queue.get("queue_digest")
    if not supplied:
        raise ValueError("reconciliation queue lacks queue_digest")
    computed = canonical_digest({k: v for k, v in queue.items() if k != "queue_digest"})
    if supplied != computed:
        raise ValueError("reconciliation queue digest mismatch")

    expected = {row["asset_id"]: row["sha256"] for row in assets}
    items = queue.get("items")
    if not isinstance(items, list):
        raise ValueError("reconciliation queue lacks items")
    by_asset = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid reconciliation queue item")
        asset_id = str(item.get("asset_id") or "")
        if asset_id in by_asset:
            raise ValueError("duplicate reconciliation asset")
        by_asset[asset_id] = item
    if set(by_asset) != set(expected):
        raise ValueError("reconciliation queue asset set mismatch")
    for asset_id, sha in expected.items():
        if by_asset[asset_id].get("sha256") != sha:
            raise ValueError("reconciliation queue asset identity mismatch")

    return {
        "queue": queue,
        "queue_sha256": sha256_file(path),
        "queue_digest": supplied,
        "items": by_asset,
    }


class AdjudicationStore:
    def __init__(
        self,
        *,
        blind_session: str | Path,
        blind_ledger: str | Path,
        reconciliation_queue: str | Path,
        directory: str | Path,
        reviewer: str,
        implementation_revision: str,
    ):
        reviewer = reviewer.strip()
        implementation_revision = implementation_revision.strip()
        if not reviewer or not implementation_revision:
            raise ValueError("reviewer and implementation revision are required")

        blind = verify_blind_snapshot(blind_session, blind_ledger)
        queue = verify_reconciliation_queue(reconciliation_queue, blind["assets"])

        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ledger = self.directory / "adjudication-events.jsonl"
        self.session_path = self.directory / "adjudication-session.json"
        self.reviewer = reviewer
        self.blind = blind
        self.queue = queue

        candidate_names = set()
        for item in queue["items"].values():
            automated = item.get("automated", {})
            candidates = automated.get("candidates", {}) if isinstance(automated, dict) else {}
            if isinstance(candidates, dict):
                candidate_names.update(str(name) for name in candidates)
        self.source_aliases = {
            name: f"source-{chr(ord('A') + index)}"
            for index, name in enumerate(sorted(candidate_names))
        }

        self.binding = {
            "schema_version": "visual_adjudication_session.v0.1",
            "reviewer": reviewer,
            "implementation_revision": implementation_revision,
            "blind_session_sha256": blind["session_sha256"],
            "blind_session_digest": blind["session_digest"],
            "blind_ledger_sha256": blind["ledger_sha256"],
            "blind_ledger_tail_digest": blind["ledger_tail_digest"],
            "reconciliation_queue_sha256": queue["queue_sha256"],
            "reconciliation_queue_digest": queue["queue_digest"],
            "assets": blind["assets"],
            "source_identity_default": "pseudonymous",
            "gold_promotion_available": False,
        }

        with self.lock():
            if self.session_path.exists():
                if json.loads(self.session_path.read_text(encoding="utf-8")) != self.binding:
                    raise ValueError("adjudication session binding changed")
            else:
                if self.ledger.exists():
                    raise ValueError("adjudication ledger exists without session binding")
                self.session_path.write_text(
                    json.dumps(self.binding, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            self.events()

    @contextmanager
    def lock(self):
        with (self.directory / ".lock").open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def events(self) -> list[dict[str, Any]]:
        rows = _read_jsonl(self.ledger)
        previous = None
        session_digest = canonical_digest(self.binding)
        for event in rows:
            supplied = event.get("event_digest")
            computed = canonical_digest({k: v for k, v in event.items() if k != "event_digest"})
            if event.get("previous_event_digest") != previous or supplied != computed:
                raise ValueError("adjudication ledger integrity failure")
            if event.get("session_digest") != session_digest:
                raise ValueError("adjudication ledger session mismatch")
            if event.get("layer") != "adjudication" or event.get("ground_truth") is not False:
                raise ValueError("adjudication authority boundary violated")
            previous = supplied
        return rows

    def _append(self, payload: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        import os

        event = {
            **payload,
            "schema_version": "visual_adjudication_event.v0.1",
            "event_id": uuid.uuid4().hex,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "reviewer": self.reviewer,
            "layer": "adjudication",
            "ground_truth": False,
            "gold": False,
            "session_digest": canonical_digest(self.binding),
            "previous_event_digest": events[-1]["event_digest"] if events else None,
        }
        event["event_digest"] = canonical_digest(event)
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def _asset_known(self, asset_id: str) -> bool:
        return asset_id in self.queue["items"]

    def _source_revealed(self, asset_id: str, events: list[dict[str, Any]]) -> bool:
        return any(
            e.get("operation") == "source_identity_revealed" and e.get("asset_id") == asset_id
            for e in events
        )

    def view(self, asset_id: str) -> dict[str, Any]:
        if not isinstance(asset_id, str) or not self._asset_known(asset_id):
            raise ValueError("unknown asset")
        events = self.events()
        item = self.queue["items"][asset_id]
        human = self.blind["first_pass"][asset_id]
        automated = item.get("automated", {})
        candidates = automated.get("candidates", {}) if isinstance(automated, dict) else {}
        aliased = {
            self.source_aliases.get(str(name), "source-UNKNOWN"): value
            for name, value in sorted(candidates.items())
        }
        payload = {
            "asset_id": asset_id,
            "sha256": next(x["sha256"] for x in self.blind["assets"] if x["asset_id"] == asset_id),
            "blind_human": {
                "event_id": human.get("event_id"),
                "judgment": human.get("judgment"),
                "labels": human.get("labels", []),
                "note": human.get("note", ""),
            },
            "seed_reference": item.get("seed_reference"),
            "automated": {
                "sources": aliased,
                "missing_candidates": automated.get("missing_candidates", []) if isinstance(automated, dict) else [],
                "failures": automated.get("failures", []) if isinstance(automated, dict) else [],
            },
            "comparison": item.get("comparison"),
            "source_identity_revealed": self._source_revealed(asset_id, events),
            "safeguards": {
                "blind_first_pass_immutable": True,
                "ground_truth": False,
                "gold": False,
                "candidate_ranking_present": False,
            },
        }
        if payload["source_identity_revealed"]:
            payload["source_identity_map"] = {
                alias: name for name, alias in sorted(self.source_aliases.items())
            }
        return payload

    def reveal_source_identities(self, asset_id: str, idempotency_key: str) -> dict[str, str]:
        if not isinstance(asset_id, str) or not self._asset_known(asset_id):
            raise ValueError("unknown asset")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        with self.lock():
            events = self.events()
            existing = [
                e for e in events
                if e.get("operation") == "source_identity_revealed"
                and e.get("asset_id") == asset_id
                and e.get("idempotency_key") == idempotency_key
            ]
            if existing:
                return {alias: name for name, alias in sorted(self.source_aliases.items())}
            self._append(
                {
                    "asset_id": asset_id,
                    "operation": "source_identity_revealed",
                    "idempotency_key": idempotency_key,
                },
                events,
            )
        return {alias: name for name, alias in sorted(self.source_aliases.items())}

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != ADJUDICATION_KEYS:
            raise ValueError("adjudication payload has unexpected or missing fields")
        asset_id = payload["asset_id"]
        if not isinstance(asset_id, str) or not self._asset_known(asset_id):
            raise ValueError("unknown asset")
        subject_type = payload["subject_type"]
        subject = payload["subject"]
        decision = payload["decision"]
        refs = payload["evidence_refs"]
        note = payload["note"]
        key = payload["idempotency_key"]
        if subject_type not in SUBJECT_TYPES:
            raise ValueError("invalid subject_type")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 2000:
            raise ValueError("invalid subject")
        if decision not in DECISIONS:
            raise ValueError("invalid adjudication decision")
        if not isinstance(refs, list) or len(refs) > 200 or any(not isinstance(x, str) or not x.strip() for x in refs):
            raise ValueError("invalid evidence_refs")
        if not isinstance(note, str) or len(note) > 20000:
            raise ValueError("invalid note")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("idempotency_key is required")

        normalized = {
            "asset_id": asset_id,
            "operation": "adjudicate",
            "subject_type": subject_type,
            "subject": subject.strip(),
            "decision": decision,
            "evidence_refs": list(refs),
            "note": note,
            "idempotency_key": key,
            "source_identity_revealed": False,
        }

        with self.lock():
            events = self.events()
            normalized["source_identity_revealed"] = self._source_revealed(asset_id, events)
            for event in events:
                if event.get("operation") == "adjudicate" and event.get("idempotency_key") == key:
                    same = all(event.get(k) == v for k, v in normalized.items())
                    if not same:
                        raise ValueError("idempotency_key reused for different adjudication")
                    return event
            return self._append(normalized, events)
