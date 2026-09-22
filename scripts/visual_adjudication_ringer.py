#!/usr/bin/env python3
"""Public-safe Gate-13 ringer for post-blind adjudication semantics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from visual_adjudication import AdjudicationStore, verify_blind_snapshot
from visual_concept_worker_core import canonical_digest


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_blind_fixture(root: Path, *, complete: bool = True) -> tuple[Path, Path, Path]:
    assets = [
        {"asset_id": "asset-a", "sha256": hashlib.sha256(b"a").hexdigest()},
        {"asset_id": "asset-b", "sha256": hashlib.sha256(b"b").hexdigest()},
    ]
    session = {
        "schema_version": "visual_blind_review_session.v0.1",
        "reviewer": "synthetic-reviewer",
        "benchmark_sha256": hashlib.sha256(b"benchmark").hexdigest(),
        "reconciliation_queue_sha256": hashlib.sha256(b"queue-placeholder").hexdigest(),
        "assets": assets,
        "implementation_revision": "synthetic-blind-revision",
        "ordering": "sha256_ascending_not_disagreement_priority",
    }
    session_path = root / "session.json"
    write_json(session_path, session)
    session_digest = canonical_digest(session)

    previous = None
    events = []
    selected = assets if complete else assets[:1]
    for index, asset in enumerate(selected):
        event = {
            "schema_version": "visual_human_review_event.v0.1",
            "event_id": f"human-{index}",
            "recorded_at": f"2026-01-01T00:00:0{index}+00:00",
            "reviewer": "synthetic-reviewer",
            "layer": "human",
            "ground_truth": False,
            "session_digest": session_digest,
            "previous_event_digest": previous,
            "asset_id": asset["asset_id"],
            "input_sha256": asset["sha256"],
            "operation": "first_pass",
            "judgment": "observed" if index == 0 else "unknown",
            "labels": ["a synthetic object"] if index == 0 else [],
            "note": "synthetic independent observation",
            "target_event_ids": [],
            "independence_attested": True,
            "evidence_exposure": "blind",
        }
        event["event_digest"] = canonical_digest(event)
        previous = event["event_digest"]
        events.append(event)

    ledger_path = root / "human-events.jsonl"
    ledger_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    queue = {
        "schema_version": "visual_concept_review_queue.v0.1",
        "benchmark_id": "synthetic",
        "benchmark_version": "v1",
        "summary": {
            "assets": 2,
            "candidates": ["direct-v0:aaaaaaaaaaaa", "active-v0:bbbbbbbbbbbb"],
        },
        "items": [
            {
                "asset_id": "asset-a",
                "sha256": assets[0]["sha256"],
                "seed_reference": {
                    "authority": "seed_not_ground_truth",
                    "concepts": [{"concept_id": "cat", "assertion_state": "supported", "status": "seed"}],
                },
                "automated": {
                    "candidates": {
                        "direct-v0:aaaaaaaaaaaa": {"concepts": [{"concept_key": "cat"}]},
                        "active-v0:bbbbbbbbbbbb": {"concepts": [{"concept_key": "dog"}]},
                    },
                    "missing_candidates": [],
                    "failures": [],
                },
                "comparison": {
                    "cross_candidate_disagreements": [{"concept_key": "cat"}],
                    "auto_novel_vs_seed_reference": ["dog"],
                    "seed_reference_not_observed_by_auto": [],
                },
            },
            {
                "asset_id": "asset-b",
                "sha256": assets[1]["sha256"],
                "seed_reference": {"authority": "seed_not_ground_truth", "concepts": []},
                "automated": {
                    "candidates": {
                        "direct-v0:aaaaaaaaaaaa": {"concepts": [{"concept_key": "tree"}]},
                        "active-v0:bbbbbbbbbbbb": {"concepts": [{"concept_key": "tree"}]},
                    },
                    "missing_candidates": [],
                    "failures": [],
                },
                "comparison": {
                    "cross_candidate_disagreements": [],
                    "auto_novel_vs_seed_reference": ["tree"],
                    "seed_reference_not_observed_by_auto": [],
                },
            },
        ],
        "safeguards": {
            "seed_is_ground_truth": False,
            "automated_observations_are_ground_truth": False,
            "accuracy_metrics_present": False,
            "not_observed_means_absent": False,
        },
    }
    queue["queue_digest"] = canonical_digest(queue)
    queue_path = root / "review-queue.json"
    write_json(queue_path, queue)
    return session_path, ledger_path, queue_path


def expect_value_error(fn, contains: str) -> None:
    try:
        fn()
    except ValueError as exc:
        if contains not in str(exc):
            raise AssertionError(f"expected {contains!r} in {str(exc)!r}") from exc
    else:
        raise AssertionError("expected ValueError")


def main() -> int:
    with TemporaryDirectory(prefix="visual-gate13-") as tmp:
        root = Path(tmp)
        good = root / "good"
        good.mkdir()
        session, ledger, queue = make_blind_fixture(good)

        snapshot = verify_blind_snapshot(session, ledger)
        assert len(snapshot["first_pass"]) == 2
        assert snapshot["ledger_tail_digest"]

        incomplete = root / "incomplete"
        incomplete.mkdir()
        inc_session, inc_ledger, _ = make_blind_fixture(incomplete, complete=False)
        expect_value_error(
            lambda: verify_blind_snapshot(inc_session, inc_ledger),
            "incomplete",
        )

        tampered = root / "tampered"
        tampered.mkdir()
        t_session, t_ledger, _ = make_blind_fixture(tampered)
        t_ledger.write_text(
            t_ledger.read_text(encoding="utf-8").replace("synthetic object", "changed object"),
            encoding="utf-8",
        )
        expect_value_error(
            lambda: verify_blind_snapshot(t_session, t_ledger),
            "integrity",
        )

        store = AdjudicationStore(
            blind_session=session,
            blind_ledger=ledger,
            reconciliation_queue=queue,
            directory=root / "adjudication",
            reviewer="synthetic-adjudicator",
            implementation_revision="synthetic-adjudication-revision",
        )

        view = store.view("asset-a")
        serialized = json.dumps(view, sort_keys=True)
        assert "direct-v0" not in serialized
        assert "active-v0" not in serialized
        assert "source-A" in serialized and "source-B" in serialized
        assert view["safeguards"]["ground_truth"] is False
        assert view["safeguards"]["gold"] is False

        mapping = store.reveal_source_identities("asset-a", "reveal-a")
        assert set(mapping) == {"source-A", "source-B"}
        revealed = store.view("asset-a")
        assert revealed["source_identity_revealed"] is True
        assert "source_identity_map" in revealed
        assert store.reveal_source_identities("asset-a", "reveal-a") == mapping

        blind_view = store.view("asset-a")
        cat_alias = next(
            alias
            for alias, value in blind_view["automated"]["sources"].items()
            if any(concept.get("concept_key") == "cat" for concept in value.get("concepts", []))
        )
        payload = {
            "asset_id": "asset-a",
            "subject_type": "concept_id",
            "subject": "cat",
            "decision": "supported",
            "evidence_refs": ["human-0", f"{cat_alias}:cat"],
            "note": "synthetic explicit adjudication",
            "idempotency_key": "adj-a-cat-1",
        }
        event = store.record(payload)
        retry = store.record(payload)
        assert retry["event_id"] == event["event_id"]
        assert event["layer"] == "adjudication"
        assert event["ground_truth"] is False
        assert event["gold"] is False
        assert event["source_identity_revealed"] is True

        conflicting = dict(payload)
        conflicting["decision"] = "contradicted"
        expect_value_error(lambda: store.record(conflicting), "idempotency_key")

        unresolved = dict(payload)
        unresolved["idempotency_key"] = "bad-ref"
        unresolved["evidence_refs"] = ["nonexistent-evidence"]
        expect_value_error(lambda: store.record(unresolved), "unresolved evidence_refs")

        unsupported_without_evidence = dict(payload)
        unsupported_without_evidence["idempotency_key"] = "no-evidence"
        unsupported_without_evidence["evidence_refs"] = []
        expect_value_error(lambda: store.record(unsupported_without_evidence), "requires evidence_refs")

        extra_authority = dict(payload)
        extra_authority["idempotency_key"] = "bad-extra"
        extra_authority["ground_truth"] = True
        expect_value_error(lambda: store.record(extra_authority), "unexpected")

        unknown_operation_subject = dict(payload)
        unknown_operation_subject["idempotency_key"] = "bad-subject"
        unknown_operation_subject["subject_type"] = "auto_mapped_concept"
        expect_value_error(lambda: store.record(unknown_operation_subject), "subject_type")

        events = store.events()
        assert [e["operation"] for e in events] == ["source_identity_revealed", "adjudicate"]
        assert all(e["ground_truth"] is False and e["gold"] is False for e in events)

        changed_queue = root / "changed-queue.json"
        changed = json.loads(queue.read_text(encoding="utf-8"))
        changed["items"][0]["sha256"] = "0" * 64
        changed["queue_digest"] = canonical_digest({k: v for k, v in changed.items() if k != "queue_digest"})
        write_json(changed_queue, changed)
        expect_value_error(
            lambda: AdjudicationStore(
                blind_session=session,
                blind_ledger=ledger,
                reconciliation_queue=changed_queue,
                directory=root / "bad-queue-session",
                reviewer="synthetic-adjudicator",
                implementation_revision="synthetic-adjudication-revision",
            ),
            "asset identity",
        )

        print(
            json.dumps(
                {
                    "schema_version": "visual_gate13_adjudication_contract.v0.1",
                    "status": "pass",
                    "blind_snapshot_digest": snapshot["ledger_tail_digest"],
                    "adjudication_events": len(events),
                    "source_identity_default": "pseudonymous",
                    "gold_promotion_available": False,
                    "private_content_present": False,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
