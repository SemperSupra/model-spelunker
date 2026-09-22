#!/usr/bin/env python3
"""Public-safe Gate-14 ringer for the trusted-local adjudication UI/API."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from visual_adjudication import AdjudicationStore
from visual_concept_worker_core import canonical_digest


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_fixture(root: Path):
    images = root / "images"
    images.mkdir()
    (images / "a.jpg").write_bytes(b"synthetic-image-a")
    (images / "b.jpg").write_bytes(b"synthetic-image-b")
    assets = [
        {"asset_id": "asset-a", "filename": "a.jpg", "sha256": hashlib.sha256((images / "a.jpg").read_bytes()).hexdigest()},
        {"asset_id": "asset-b", "filename": "b.jpg", "sha256": hashlib.sha256((images / "b.jpg").read_bytes()).hexdigest()},
    ]

    benchmark = {
        "benchmark_id": "synthetic-ui",
        "benchmark_version": "v1",
        "assets": [
            {"asset": {"benchmark_asset_id": row["asset_id"], "source_filename": row["filename"], "sha256": row["sha256"]}}
            for row in assets
        ],
    }
    benchmark_path = root / "benchmark.json"
    write_json(benchmark_path, benchmark)

    session = {
        "schema_version": "visual_blind_review_session.v0.1",
        "reviewer": "synthetic-reviewer",
        "benchmark_sha256": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
        "reconciliation_queue_sha256": hashlib.sha256(b"placeholder").hexdigest(),
        "assets": [{"asset_id": row["asset_id"], "sha256": row["sha256"]} for row in assets],
        "implementation_revision": "synthetic-blind-revision",
        "ordering": "sha256_ascending_not_disagreement_priority",
    }
    session_path = root / "session.json"
    write_json(session_path, session)
    session_digest = canonical_digest(session)

    previous = None
    ledger_rows = []
    for index, row in enumerate(assets):
        event = {
            "schema_version": "visual_human_review_event.v0.1",
            "event_id": f"human-{index}",
            "recorded_at": f"2026-01-01T00:00:0{index}+00:00",
            "reviewer": "synthetic-reviewer",
            "layer": "human",
            "ground_truth": False,
            "session_digest": session_digest,
            "previous_event_digest": previous,
            "asset_id": row["asset_id"],
            "input_sha256": row["sha256"],
            "operation": "first_pass",
            "judgment": "observed",
            "labels": [f"synthetic statement {index}"],
            "note": "synthetic blind note",
            "target_event_ids": [],
            "independence_attested": True,
            "evidence_exposure": "blind",
        }
        event["event_digest"] = canonical_digest(event)
        previous = event["event_digest"]
        ledger_rows.append(event)
    ledger = root / "human-events.jsonl"
    ledger.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in ledger_rows), encoding="utf-8")

    queue = {
        "schema_version": "visual_concept_review_queue.v0.1",
        "benchmark_id": "synthetic-ui",
        "benchmark_version": "v1",
        "summary": {"assets": 2, "candidates": ["direct-v0:aaaaaaaaaaaa", "active-v0:bbbbbbbbbbbb"]},
        "items": [
            {
                "asset_id": row["asset_id"],
                "sha256": row["sha256"],
                "seed_reference": {"authority": "seed_not_ground_truth", "concepts": [{"concept_id": "cat"}]},
                "automated": {
                    "candidates": {
                        "direct-v0:aaaaaaaaaaaa": {"concepts": [{"concept_key": "cat"}]},
                        "active-v0:bbbbbbbbbbbb": {"concepts": [{"concept_key": "dog"}]},
                    },
                    "missing_candidates": [],
                    "failures": [],
                },
                "comparison": {"cross_candidate_disagreements": [{"concept_key": "cat"}]},
            }
            for row in assets
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
    return benchmark_path, images, session_path, ledger, queue_path


def main() -> int:
    with TemporaryDirectory(prefix="visual-gate14-") as tmp:
        root = Path(tmp)
        benchmark, images, session, ledger, queue = build_fixture(root)
        store = AdjudicationStore(
            blind_session=session,
            blind_ledger=ledger,
            reconciliation_queue=queue,
            directory=root / "adjudication",
            reviewer="synthetic-adjudicator",
            implementation_revision="synthetic-ui-revision",
        )

        server_path = Path(__file__).resolve().parent / "serve_visual_adjudication.py"
        spec = importlib.util.spec_from_file_location("adj_server", server_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        image_map = module._benchmark_images(benchmark, images, store)
        server, token = module.make_server(store, image_map, 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def call(path, payload=None, auth=True, **headers):
            if auth:
                headers["X-Adjudication-Token"] = token
            data = None if payload is None else json.dumps(payload).encode()
            request = Request(base + path, data=data, headers=headers)
            return urlopen(request)

        try:
            page = call("/").read().decode()
            assert "/api/gold" not in page
            assert "accept model answer" not in page.lower()

            state = json.loads(call("/api/state").read())
            assert state["ground_truth"] is False
            assert state["gold_promotion_available"] is False
            assert len(state["assets"]) == 2

            view = call("/api/view/asset-a").read().decode()
            assert "source-A" in view and "source-B" in view
            assert "direct-v0" not in view and "active-v0" not in view

            image = call("/image/asset-a").read()
            assert hashlib.sha256(image).hexdigest() == state["assets"][0]["sha256"] or hashlib.sha256(image).hexdigest() in {x["sha256"] for x in state["assets"]}

            with_unauth = None
            try:
                call("/api/state", auth=False)
            except HTTPError as exc:
                with_unauth = exc.code
            assert with_unauth == 403

            bad_origin = None
            try:
                call("/api/state", Origin="https://example.com")
            except HTTPError as exc:
                bad_origin = exc.code
            assert bad_origin == 403

            reveal = json.loads(call("/api/reveal", {"asset_id": "asset-a", "idempotency_key": "reveal-a"}).read())
            assert set(reveal) == {"source-A", "source-B"}
            revealed_view = call("/api/view/asset-a").read().decode()
            assert "source_identity_map" in revealed_view
            assert "direct-v0" in revealed_view and "active-v0" in revealed_view

            adjudication = {
                "asset_id": "asset-a",
                "subject_type": "concept_id",
                "subject": "cat",
                "decision": "supported",
                "evidence_refs": ["human-0", "source-A:cat"],
                "note": "synthetic UI adjudication",
                "idempotency_key": "adj-ui-a",
            }
            event = json.loads(call("/api/adjudicate", adjudication).read())
            assert event["layer"] == "adjudication"
            assert event["ground_truth"] is False
            assert event["gold"] is False

            final_state = json.loads(call("/api/state").read())
            assert len(final_state["events"]) == 2
            assert [e["operation"] for e in final_state["events"]] == ["source_identity_revealed", "adjudicate"]

            print(json.dumps({
                "schema_version": "visual_gate14_adjudication_ui.v0.1",
                "status": "pass",
                "assets": len(final_state["assets"]),
                "events": len(final_state["events"]),
                "source_identity_default": "pseudonymous",
                "gold_promotion_available": False,
                "private_content_present": False,
            }, sort_keys=True))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
