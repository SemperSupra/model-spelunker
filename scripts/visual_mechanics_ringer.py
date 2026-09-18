#!/usr/bin/env python3
"""Fast public-safe qualification for benchmark and active-controller mechanics."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openimages_qualification import group_qualification_items, iter_human_image_labels, load_class_descriptions
from visual_active_controller import ActionRequest, run_active_skeleton
from visual_concept_worker_core import CandidateSpec, Evidence, Observation


class RepeatPolicy:
    def choose(self, *, observations, trace, remaining_actions):
        return ActionRequest(tool="probe", parameters={"step": len(trace) + 1})


class OneProbePolicy:
    def choose(self, *, observations, trace, remaining_actions):
        if trace:
            return None
        return ActionRequest(tool="probe", parameters={"concept": "cat"})


class BadParentPolicy:
    def choose(self, *, observations, trace, remaining_actions):
        return ActionRequest(tool="probe", parameters={}, parent_observation_id="does-not-exist")


class FakeTool:
    def execute(self, *, image_path, request, action_id):
        return [
            Observation(
                observation_id="tool-local-random-looking-id",
                concept_id="object.animal.cat",
                label="cat",
                assertion="candidate",
                evidence=(
                    Evidence(
                        kind="mock_probe",
                        source="fake-tool",
                        score=0.7,
                        metadata={"action_id": action_id},
                    ),
                ),
            )
        ]


def active_candidate(*, max_actions=2, toolset=("probe",)):
    return CandidateSpec(
        worker_framework="visual-concept-worker",
        framework_version="0.1.0",
        backend_family="stub",
        model_id="public/fake-scorer",
        model_revision="v1",
        concept_pack_digest="0" * 64,
        action_policy="active-v0",
        toolset=toolset,
        parameters={"max_actions": max_actions},
    )


def expect_error(fn, fragment: str) -> None:
    try:
        fn()
    except ValueError as exc:
        if fragment not in str(exc):
            raise
    else:
        raise SystemExit(f"expected ValueError containing {fragment!r}")


def qualify_openimages(tmp: Path) -> dict:
    classes = tmp / "classes.csv"
    classes.write_text("/m/cat,Cat\n/m/dog,Dog\n/m/bird,Bird\n", encoding="utf-8")
    labels = tmp / "labels.csv"
    labels.write_text(
        "ImageID,Source,LabelName,Confidence\n"
        "img1,verification,/m/cat,1\n"
        "img1,crowdsource-verification,/m/dog,0\n"
        "img2,verification,/m/bird,1\n",
        encoding="utf-8",
    )
    mapping = load_class_descriptions(classes)
    rows = list(iter_human_image_labels(labels, mapping))
    grouped = group_qualification_items(rows)
    img1 = grouped[0]
    assert [x["external_label"] for x in img1["verified_present"]] == ["Cat"]
    assert [x["external_label"] for x in img1["verified_absent"]] == ["Dog"]
    assert "Bird" not in str(img1)

    machine = tmp / "machine.csv"
    machine.write_text(
        "ImageID,Source,LabelName,Confidence\nimg1,machine,/m/cat,1\n",
        encoding="utf-8",
    )
    expect_error(lambda: list(iter_human_image_labels(machine, mapping)), "non-human")

    missing = tmp / "missing.csv"
    missing.write_text(
        "ImageID,Source,LabelName,Confidence\nimg1,verification,/m/missing,1\n",
        encoding="utf-8",
    )
    expect_error(lambda: list(iter_human_image_labels(missing, mapping)), "missing class description")

    return {
        "rows": len(rows),
        "images": len(grouped),
        "verified_present_img1": ["Cat"],
        "verified_absent_img1": ["Dog"],
        "unannotated_bird_img1": "unknown",
        "machine_source_rejected": True,
        "missing_class_description_rejected": True,
    }


def qualify_active(tmp: Path) -> dict:
    image = tmp / "fixture.bin"
    image.write_bytes(b"public-safe-active-controller-fixture")
    kwargs = dict(
        candidate=active_candidate(max_actions=2),
        image_path=image,
        initial_observations=(),
        policy=RepeatPolicy(),
        tools={"probe": FakeTool()},
        max_actions=2,
        execution_lane="public-ringer",
    )
    first = run_active_skeleton(**kwargs)
    second = run_active_skeleton(**kwargs)
    assert first["actions_executed"] == 2
    assert first["stop_reason"] == "budget_exhausted"
    assert first["execution_digest"] == second["execution_digest"]
    ids1 = [x["observation_id"] for x in first["worker_run"]["observations"]]
    ids2 = [x["observation_id"] for x in second["worker_run"]["observations"]]
    assert ids1 == ids2
    assert "tool-local-random-looking-id" not in ids1

    stopped = run_active_skeleton(
        candidate=active_candidate(max_actions=3),
        image_path=image,
        initial_observations=(),
        policy=OneProbePolicy(),
        tools={"probe": FakeTool()},
        max_actions=3,
        execution_lane="public-ringer",
    )
    assert stopped["actions_executed"] == 1
    assert stopped["stop_reason"] == "policy_stop"

    expect_error(
        lambda: run_active_skeleton(
            candidate=active_candidate(max_actions=3),
            image_path=image, initial_observations=(), policy=RepeatPolicy(),
            tools={"probe": FakeTool()}, max_actions=2,
        ),
        "does not match candidate",
    )
    expect_error(
        lambda: run_active_skeleton(
            candidate=active_candidate(max_actions=1, toolset=()),
            image_path=image, initial_observations=(), policy=RepeatPolicy(),
            tools={"probe": FakeTool()}, max_actions=1,
        ),
        "not declared by candidate",
    )
    expect_error(
        lambda: run_active_skeleton(
            candidate=active_candidate(max_actions=1),
            image_path=image, initial_observations=(), policy=BadParentPolicy(),
            tools={"probe": FakeTool()}, max_actions=1,
        ),
        "unknown parent observation",
    )

    return {
        "budget_exhausted": True,
        "policy_stop": True,
        "execution_digest_reproducible": True,
        "controller_owned_observation_ids": True,
        "budget_drift_rejected": True,
        "undeclared_tool_rejected": True,
        "unknown_parent_rejected": True,
    }


def main() -> int:
    with TemporaryDirectory(prefix="vcw-mechanics-") as tmpdir:
        tmp = Path(tmpdir)
        result = {
            "schema_version": "visual_concept_worker_mechanics_ringer.v0.1",
            "status": "pass",
            "openimages": qualify_openimages(tmp),
            "active_controller": qualify_active(tmp),
            "safeguards": {
                "public_safe": True,
                "private_content_present": False,
                "private_semantic_authority_present": False,
                "performance_claim": False,
            },
        }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
