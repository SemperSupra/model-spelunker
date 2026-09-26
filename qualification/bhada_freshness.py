#!/usr/bin/env python3
"""Small, policy-neutral freshness/maintenance eligibility projection.

This module deliberately does not schedule, dispatch, rank actors, or mutate products.
It turns one dated operational observation into a bounded maintenance-work candidate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PASS_STATES = {"PASS", "WORKING"}
READINESS_STATES = {"ENVIRONMENT_BLOCKED", "CAPABILITY_REQUIRED", "ACCESS_REQUIRED"}
FAILURE_STATES = {"UPSTREAM_CHANGED", "FAILED", "DEGRADED"}
UNKNOWN_STATES = {"UNKNOWN", "NOT_RUN"}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _operational_state(stages: dict[str, str]) -> str:
    values = [str(value).upper() for value in stages.values()]
    for state in ("ENVIRONMENT_BLOCKED", "CAPABILITY_REQUIRED", "ACCESS_REQUIRED"):
        if state in values:
            return state
    for state in ("UPSTREAM_CHANGED", "FAILED", "DEGRADED"):
        if state in values:
            return state
    if any(value in UNKNOWN_STATES for value in values):
        return "UNKNOWN"
    if values and all(value in PASS_STATES for value in values):
        return "WORKING"
    return "UNKNOWN"


def assess_observation(observation: dict[str, Any], *, now: str | datetime) -> dict[str, Any]:
    """Project freshness, operational state, and the next eligible maintenance task.

    Expiry makes work eligible; it does not itself authorize or dispatch work.
    """

    component = str(observation["component"])
    observed_at = _parse_time(str(observation["observed_at"]))
    current_time = _parse_time(now) if isinstance(now, str) else now.astimezone(timezone.utc)
    max_age_seconds = int(observation["max_age_seconds"])
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    raw_age_seconds = int((current_time - observed_at).total_seconds())
    age_seconds = max(0, raw_age_seconds)

    observed_context = observation.get("observed_context_digest")
    current_context = observation.get("current_context_digest")
    context_incomplete = bool(observed_context) != bool(current_context)
    context_changed = bool(
        observed_context
        and current_context
        and str(observed_context) != str(current_context)
    )

    if raw_age_seconds < 0:
        freshness_state = "INVALIDATED"
        freshness_reason = "observation timestamp is in the future"
    elif context_incomplete:
        freshness_state = "INVALIDATED"
        freshness_reason = "context applicability evidence is incomplete"
    elif context_changed:
        freshness_state = "INVALIDATED"
        freshness_reason = "relevant context changed"
    elif age_seconds > max_age_seconds:
        freshness_state = "STALE"
        freshness_reason = "freshness horizon exceeded"
    else:
        freshness_state = "FRESH"
        freshness_reason = "evidence remains within applicability horizon"

    stages = observation.get("stages") or {}
    if not isinstance(stages, dict):
        raise ValueError("stages must be an object")
    operational_state = _operational_state(stages)

    decision_required = bool(observation.get("decision_required", False))

    # Applicability/freshness is checked before diagnosing historical failures.
    if freshness_state != "FRESH":
        next_action = "REVALIDATE"
        task_class = "maintenance.revalidation"
    elif operational_state in READINESS_STATES:
        next_action = "RESTORE_READINESS"
        task_class = "maintenance.readiness"
    elif operational_state in FAILURE_STATES:
        next_action = "DIAGNOSE"
        task_class = "maintenance.diagnosis"
    elif operational_state == "UNKNOWN":
        next_action = "OBSERVE"
        task_class = "maintenance.observation"
    else:
        next_action = "USE_EVIDENCE"
        task_class = None

    if next_action == "USE_EVIDENCE":
        urgency = "NONE"
    elif decision_required:
        urgency = "DECISION_REQUIRED"
    else:
        urgency = "OPPORTUNISTIC"

    return {
        "component": component,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "freshness_state": freshness_state,
        "freshness_reason": freshness_reason,
        "operational_state": operational_state,
        "eligible_for_maintenance": next_action != "USE_EVIDENCE",
        "urgency": urgency,
        "next_action": next_action,
        "task_class": task_class,
        "decision_required": decision_required,
    }
