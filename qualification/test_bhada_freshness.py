#!/usr/bin/env python3
"""Deterministic contract tests for BHADA freshness-driven maintenance projection."""

from qualification.bhada_freshness import assess_observation

NOW = "2026-09-26T12:00:00Z"


def base(**overrides):
    row = {
        "component": "provider-alpha",
        "observed_at": "2026-09-26T11:30:00Z",
        "max_age_seconds": 3600,
        "observed_context_digest": "ctx-a",
        "current_context_digest": "ctx-a",
        "decision_required": False,
        "stages": {
            "search": "PASS",
            "metadata": "PASS",
            "episodes": "PASS",
            "resolve": "PASS",
        },
    }
    row.update(overrides)
    return row


fresh = assess_observation(base(), now=NOW)
assert fresh["freshness_state"] == "FRESH"
assert fresh["operational_state"] == "WORKING"
assert fresh["next_action"] == "USE_EVIDENCE"
assert fresh["urgency"] == "NONE"

stale = assess_observation(
    base(observed_at="2026-09-26T09:00:00Z"),
    now=NOW,
)
assert stale["freshness_state"] == "STALE"
assert stale["next_action"] == "REVALIDATE"
assert stale["urgency"] == "OPPORTUNISTIC"
assert stale["eligible_for_maintenance"] is True

decision_stale = assess_observation(
    base(observed_at="2026-09-26T09:00:00Z", decision_required=True),
    now=NOW,
)
assert decision_stale["urgency"] == "DECISION_REQUIRED"

invalidated = assess_observation(
    base(current_context_digest="ctx-b"),
    now=NOW,
)
assert invalidated["freshness_state"] == "INVALIDATED"
assert invalidated["next_action"] == "REVALIDATE"

incomplete_context = assess_observation(
    base(current_context_digest=None),
    now=NOW,
)
assert incomplete_context["freshness_state"] == "INVALIDATED"
assert incomplete_context["next_action"] == "REVALIDATE"

future_timestamp = assess_observation(
    base(observed_at="2026-09-26T12:05:00Z"),
    now=NOW,
)
assert future_timestamp["freshness_state"] == "INVALIDATED"
assert "future" in future_timestamp["freshness_reason"]

upstream = assess_observation(
    base(stages={"search": "PASS", "metadata": "PASS", "episodes": "PASS", "resolve": "UPSTREAM_CHANGED"}),
    now=NOW,
)
assert upstream["freshness_state"] == "FRESH"
assert upstream["operational_state"] == "UPSTREAM_CHANGED"
assert upstream["next_action"] == "DIAGNOSE"
assert upstream["task_class"] == "maintenance.diagnosis"

readiness = assess_observation(
    base(stages={"search": "ENVIRONMENT_BLOCKED", "metadata": "NOT_RUN", "episodes": "NOT_RUN", "resolve": "NOT_RUN"}),
    now=NOW,
)
assert readiness["operational_state"] == "ENVIRONMENT_BLOCKED"
assert readiness["next_action"] == "RESTORE_READINESS"
assert readiness["task_class"] == "maintenance.readiness"

unknown = assess_observation(
    base(stages={"search": "UNKNOWN", "metadata": "NOT_RUN", "episodes": "NOT_RUN", "resolve": "NOT_RUN"}),
    now=NOW,
)
assert unknown["operational_state"] == "UNKNOWN"
assert unknown["next_action"] == "OBSERVE"

# Old failed evidence must be revalidated before it is treated as a current diagnosis target.
old_failure = assess_observation(
    base(
        observed_at="2026-09-26T08:00:00Z",
        stages={"search": "PASS", "metadata": "PASS", "episodes": "PASS", "resolve": "FAILED"},
    ),
    now=NOW,
)
assert old_failure["freshness_state"] == "STALE"
assert old_failure["next_action"] == "REVALIDATE"

print("PASS BHADA freshness eligibility preserves freshness, urgency, clock/context, readiness, and diagnosis boundaries")
