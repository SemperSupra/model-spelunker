"""Bounded active-perception controller mechanics for public qualification."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from visual_concept_worker_core import CandidateSpec, Observation, build_run_manifest, canonical_digest


@dataclass(frozen=True)
class ActionRequest:
    tool: str
    parameters: dict[str, Any] = field(default_factory=dict)
    parent_observation_id: str | None = None


@dataclass(frozen=True)
class ActionTrace:
    step: int
    action_id: str
    tool: str
    parameters: dict[str, Any]
    parent_observation_id: str | None
    observation_ids: tuple[str, ...]


class ActivePolicy(Protocol):
    def choose(
        self,
        *,
        observations: Sequence[Observation],
        trace: Sequence[ActionTrace],
        remaining_actions: int,
    ) -> ActionRequest | None: ...


class PerceptionTool(Protocol):
    def execute(
        self,
        *,
        image_path: str | Path,
        request: ActionRequest,
        action_id: str,
    ) -> Sequence[Observation]: ...


def run_active_skeleton(
    *,
    candidate: CandidateSpec,
    image_path: str | Path,
    initial_observations: Sequence[Observation],
    policy: ActivePolicy,
    tools: Mapping[str, PerceptionTool],
    max_actions: int,
    execution_lane: str = "public-ringer",
) -> dict[str, Any]:
    if candidate.action_policy != "active-v0":
        raise ValueError("candidate action_policy must be active-v0")
    if max_actions < 0:
        raise ValueError("max_actions must be >= 0")
    declared_budget = candidate.parameters.get("max_actions")
    if declared_budget is not None and int(declared_budget) != max_actions:
        raise ValueError(
            f"runtime max_actions={max_actions} does not match candidate max_actions={declared_budget}"
        )

    observations = list(initial_observations)
    known_observation_ids = {item.observation_id for item in observations}
    trace: list[ActionTrace] = []
    stop_reason = "budget_exhausted" if max_actions == 0 else "policy_stop"

    for step in range(1, max_actions + 1):
        request = policy.choose(
            observations=tuple(observations),
            trace=tuple(trace),
            remaining_actions=max_actions - step + 1,
        )
        if request is None:
            stop_reason = "policy_stop"
            break
        if request.tool not in candidate.toolset:
            raise ValueError(f"policy selected tool not declared by candidate: {request.tool}")
        if request.tool not in tools:
            raise ValueError(f"policy selected unavailable tool: {request.tool}")
        if request.parent_observation_id is not None and request.parent_observation_id not in known_observation_ids:
            raise ValueError(
                f"policy selected unknown parent observation: {request.parent_observation_id}"
            )

        action_identity = {
            "step": step,
            "tool": request.tool,
            "parameters": request.parameters,
            "parent_observation_id": request.parent_observation_id,
        }
        action_id = f"act-{step:04d}-{canonical_digest(action_identity)[:8]}"
        raw_produced = tuple(
            tools[request.tool].execute(
                image_path=image_path,
                request=request,
                action_id=action_id,
            )
        )
        produced: list[Observation] = []
        for output_index, item in enumerate(raw_produced, start=1):
            identity = asdict(item)
            identity.pop("observation_id", None)
            identity["parent_observation_id"] = request.parent_observation_id
            stable_id = f"obs-{action_id}-{output_index:02d}-{canonical_digest(identity)[:8]}"
            produced.append(
                replace(
                    item,
                    observation_id=stable_id,
                    parent_observation_id=request.parent_observation_id,
                )
            )
        observations.extend(produced)
        known_observation_ids.update(item.observation_id for item in produced)
        trace.append(
            ActionTrace(
                step=step,
                action_id=action_id,
                tool=request.tool,
                parameters=dict(request.parameters),
                parent_observation_id=request.parent_observation_id,
                observation_ids=tuple(item.observation_id for item in produced),
            )
        )
    else:
        stop_reason = "budget_exhausted"

    worker_run = build_run_manifest(
        candidate=candidate,
        input_path=image_path,
        observations=observations,
        execution_lane=execution_lane,
    )
    trace_records = [asdict(item) for item in trace]
    result = {
        "schema_version": "visual_concept_active_execution.v0.1",
        "worker_run": worker_run,
        "action_budget": max_actions,
        "actions_executed": len(trace),
        "stop_reason": stop_reason,
        "action_trace": trace_records,
    }
    result["execution_digest"] = canonical_digest(
        {
            "worker_run_digest": worker_run["run_digest"],
            "action_budget": max_actions,
            "stop_reason": stop_reason,
            "action_trace": trace_records,
        }
    )
    return result
