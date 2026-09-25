#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

CLAIM_ID = "CLAIM_1_AGENT_REFINING_PERFORMANCE"
EXPERIMENT_ID = "EXP_II_AGENT_REFINING_EFFECTIVENESS"
SOURCE_HASHES = {
    "paper.md": ("e69c502c0c16f860160da8368e5b4fc5ee3da36275fe0571350bdd03b3477e03", 106169),
    "addendum.md": ("d62c727e9aaac69165d0bbeb2b1c4df7f1c8a183c5906d9b0e44cf9401153b43", 5102),
    "config.yaml": ("d1c4d2e713877c647f97a6bb323814175ffc8bd604b9b136afc2a328282732e1", 109),
}
FIELDS = {
    "baseline_refining_methods",
    "treatment_factors",
    "environments_eval_set",
    "mixed_initial_state_distribution_parameter_p",
    "exploration_bonus_parameter_lambda",
    "pre_trained_agent_weights_and_checkpoint_states",
    "refining_training_steps_and_optimizer",
    "evaluation_trials_and_random_seeds",
    "evaluation_metric",
}
EXPECTED_STATUS = {
    "baseline_refining_methods": "EXPLICIT_PAPER",
    "treatment_factors": "EXPLICIT_PAPER",
    "environments_eval_set": "INFERABLE_WITH_EVIDENCE",
    "mixed_initial_state_distribution_parameter_p": "AMBIGUOUS",
    "exploration_bonus_parameter_lambda": "AMBIGUOUS",
    "pre_trained_agent_weights_and_checkpoint_states": "MISSING",
    "refining_training_steps_and_optimizer": "MISSING",
    "evaluation_trials_and_random_seeds": "EXPLICIT_PAPER",
    "evaluation_metric": "EXPLICIT_PAPER",
}
STATUSES = {
    "EXPLICIT_PAPER",
    "EXPLICIT_ADDENDUM",
    "INFERABLE_WITH_EVIDENCE",
    "AMBIGUOUS",
    "MISSING",
    "NOT_APPLICABLE",
}
READINESS = {"RUNNABLE", "PARTIAL", "BLOCKED"}
REF_RE = re.compile(r"^source:(paper\.md|addendum\.md|config\.yaml):L([1-9][0-9]*)(?:-L([1-9][0-9]*))?$")

ANCHORS = {
    "baseline_refining_methods": [("paper.md", {196})],
    "treatment_factors": [("paper.md", {214})],
    "environments_eval_set": [("paper.md", {176}), ("addendum.md", {103, 104})],
    "mixed_initial_state_distribution_parameter_p": [("paper.md", {637, 639}), ("addendum.md", {77})],
    "exploration_bonus_parameter_lambda": [("paper.md", {245, 639}), ("addendum.md", {76})],
    "evaluation_trials_and_random_seeds": [("paper.md", {195})],
    "evaluation_metric": [("paper.md", {214})],
}
VALUE_TERMS = {
    "baseline_refining_methods": ("ppo", "jsrl", "statemask"),
    "treatment_factors": ("rice", "ppo", "jsrl"),
    "environments_eval_set": ("hopper", "walker2d", "reacher", "halfcheetah", "malware"),
    "mixed_initial_state_distribution_parameter_p": ("0.25", "0.5"),
    "exploration_bonus_parameter_lambda": ("0.01",),
    "evaluation_trials_and_random_seeds": ("3", "mean", "standard deviation"),
    "evaluation_metric": ("final reward", "mean", "standard deviation"),
}
BLOCKING_FIELDS = sorted([
    "exploration_bonus_parameter_lambda",
    "mixed_initial_state_distribution_parameter_p",
    "pre_trained_agent_weights_and_checkpoint_states",
    "refining_training_steps_and_optimizer",
])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_lines(root: Path, *, enforce_hashes: bool) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, (expected_sha, expected_size) in SOURCE_HASHES.items():
        path = root / "sources" / name
        data = path.read_bytes()
        if enforce_hashes:
            if len(data) != expected_size or digest(data) != expected_sha:
                raise ValueError(f"frozen source identity mismatch: {name}")
        out[name] = data.decode("utf-8").splitlines()
    return out


def parse_ref(ref: str, sources: dict[str, list[str]]) -> tuple[str, int, int] | None:
    match = REF_RE.match(ref)
    if not match:
        return None
    name, first, last = match.groups()
    start = int(first)
    end = int(last or first)
    if start > end or end > len(sources[name]):
        return None
    return name, start, end


def refs_ok(refs, sources: dict[str, list[str]], *, allow_empty: bool = False) -> bool:
    if not isinstance(refs, list):
        return False
    if not refs:
        return allow_empty
    if refs != sorted(set(refs)):
        return False
    return all(isinstance(ref, str) and parse_ref(ref, sources) is not None for ref in refs)


def refs_cover(refs: list[str], sources: dict[str, list[str]], artifact: str, lines: set[int]) -> bool:
    for ref in refs:
        parsed = parse_ref(ref, sources)
        if parsed is None:
            continue
        name, start, end = parsed
        if name == artifact and any(start <= line <= end for line in lines):
            return True
    return False


def check(root: Path, *, enforce_hashes: bool = True) -> bool:
    try:
        sources = source_lines(root, enforce_hashes=enforce_hashes)
        output = json.loads((root / "method_ir.json").read_text(encoding="utf-8"))
        if set(output) != {"schema_version", "claim", "method_fields", "execution_readiness"}:
            return False
        if output["schema_version"] != 1:
            return False

        claim = output["claim"]
        if set(claim) != {"claim_id", "experiment_id", "statement", "evidence_refs"}:
            return False
        if claim["claim_id"] != CLAIM_ID or claim["experiment_id"] != EXPERIMENT_ID:
            return False
        if not isinstance(claim["statement"], str) or not claim["statement"].strip():
            return False
        statement = claim["statement"].lower()
        if not all(term in statement for term in ("rice", "ppo", "jsrl", "statemask")):
            return False
        if not refs_ok(claim["evidence_refs"], sources):
            return False
        if not refs_cover(claim["evidence_refs"], sources, "paper.md", {196}):
            return False
        if not refs_cover(claim["evidence_refs"], sources, "paper.md", {208, 214}):
            return False

        fields = output["method_fields"]
        if set(fields) != FIELDS:
            return False
        for name in sorted(FIELDS):
            row = fields[name]
            if not isinstance(row, dict) or set(row) != {"status", "value", "evidence_refs", "absence_search"}:
                return False
            status = row["status"]
            if status not in STATUSES or status != EXPECTED_STATUS[name]:
                return False
            value = row["value"]
            refs = row["evidence_refs"]
            absence = row["absence_search"]

            if status == "MISSING":
                if value is not None or refs != []:
                    return False
                if not isinstance(absence, str) or not absence.strip():
                    return False
                lowered = absence.lower()
                if not all(source in lowered for source in ("paper.md", "addendum.md", "config.yaml")):
                    return False
                continue

            if status == "NOT_APPLICABLE":
                if not isinstance(value, str) or not value.strip() or refs != [] or absence is not None:
                    return False
                continue

            if not isinstance(value, str) or not value.strip() or absence is not None:
                return False
            if not refs_ok(refs, sources):
                return False
            for artifact, lines in ANCHORS.get(name, []):
                if not refs_cover(refs, sources, artifact, lines):
                    return False
            if status == "AMBIGUOUS":
                artifacts = {parse_ref(ref, sources)[0] for ref in refs}
                if len(artifacts) < 2:
                    return False
            lower_value = value.lower()
            if not all(term in lower_value for term in VALUE_TERMS.get(name, ())):
                return False

        readiness = output["execution_readiness"]
        if set(readiness) != {"status", "blocking_fields", "notes"}:
            return False
        if readiness["status"] not in READINESS or readiness["status"] != "BLOCKED":
            return False
        blockers = readiness["blocking_fields"]
        if not isinstance(blockers, list) or blockers != sorted(set(blockers)):
            return False
        if blockers != BLOCKING_FIELDS:
            return False
        if not isinstance(readiness["notes"], str) or not readiness["notes"].strip():
            return False
        return True
    except Exception:
        return False


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "sources"
        src.mkdir(parents=True)
        paper = [f"paper line {i}" for i in range(1, 221)]
        addendum = [f"addendum line {i}" for i in range(1, 111)]
        config = ["id: rice", "title: RICE"]
        for line, value in {
            176: "Hopper Walker2d Reacher HalfCheetah and malware environments",
            195: "We repeat each experiment 3 times and report mean and standard deviation",
            196: "PPO fine-tuning StateMask JSRL comparison",
            208: "RICE improves performance against PPO JSRL StateMask",
            214: "RICE PPO JSRL final reward mean standard deviation",
            245: "lambda value of 0.01",
            637: "p 0.25 or 0.5",
            639: "p 0.25 0.5 lambda 0.01",
        }.items():
            paper[line - 1] = value
        addendum[75] = "Figure 7 lambda 0.01"
        addendum[76] = "Figure 8 p 0.25 0.5"
        addendum[102] = "Malware Mutation environment is out of scope"
        (src / "paper.md").write_text("\n".join(paper) + "\n", encoding="utf-8")
        (src / "addendum.md").write_text("\n".join(addendum) + "\n", encoding="utf-8")
        (src / "config.yaml").write_text("\n".join(config) + "\n", encoding="utf-8")

        good_fields = {
            "baseline_refining_methods": {"status":"EXPLICIT_PAPER","value":"PPO, JSRL, and StateMask baselines","evidence_refs":["source:paper.md:L196"],"absence_search":None},
            "treatment_factors": {"status":"EXPLICIT_PAPER","value":"RICE compared with PPO, JSRL and StateMask-R","evidence_refs":["source:paper.md:L214"],"absence_search":None},
            "environments_eval_set": {"status":"INFERABLE_WITH_EVIDENCE","value":"Hopper Walker2d Reacher HalfCheetah plus real-world applications; malware is out of scope","evidence_refs":["source:addendum.md:L103","source:paper.md:L176"],"absence_search":None},
            "mixed_initial_state_distribution_parameter_p": {"status":"AMBIGUOUS","value":"p 0.25 or 0.5; exact per-task setting remains ambiguous","evidence_refs":["source:addendum.md:L77","source:paper.md:L637"],"absence_search":None},
            "exploration_bonus_parameter_lambda": {"status":"AMBIGUOUS","value":"lambda 0.01 is suggested but exact per-task setting remains ambiguous","evidence_refs":["source:addendum.md:L76","source:paper.md:L245"],"absence_search":None},
            "pre_trained_agent_weights_and_checkpoint_states": {"status":"MISSING","value":None,"evidence_refs":[],"absence_search":"Checked paper.md, addendum.md, and config.yaml."},
            "refining_training_steps_and_optimizer": {"status":"MISSING","value":None,"evidence_refs":[],"absence_search":"Checked paper.md, addendum.md, and config.yaml."},
            "evaluation_trials_and_random_seeds": {"status":"EXPLICIT_PAPER","value":"3 trials; mean and standard deviation reported with random seeds","evidence_refs":["source:paper.md:L195"],"absence_search":None},
            "evaluation_metric": {"status":"EXPLICIT_PAPER","value":"final reward; mean and standard deviation, higher is better","evidence_refs":["source:paper.md:L214"],"absence_search":None},
        }
        good = {
            "schema_version": 1,
            "claim": {
                "claim_id": CLAIM_ID,
                "experiment_id": EXPERIMENT_ID,
                "statement": "RICE outperforms PPO, JSRL, and StateMask refining baselines.",
                "evidence_refs": ["source:paper.md:L196", "source:paper.md:L208-L214"],
            },
            "method_fields": good_fields,
            "execution_readiness": {
                "status": "BLOCKED",
                "blocking_fields": BLOCKING_FIELDS,
                "notes": "Publication inputs leave required parameters/checkpoints unresolved.",
            },
        }
        (root / "method_ir.json").write_text(json.dumps(good), encoding="utf-8")
        assert check(root, enforce_hashes=False)

        bad = json.loads(json.dumps(good))
        bad["method_fields"]["mixed_initial_state_distribution_parameter_p"]["evidence_refs"] = ["source:paper.md:L637"]
        (root / "method_ir.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root, enforce_hashes=False)

        bad = json.loads(json.dumps(good))
        bad["method_fields"]["baseline_refining_methods"]["evidence_refs"] = ["source:paper.md:L195"]
        (root / "method_ir.json").write_text(json.dumps(bad), encoding="utf-8")
        assert not check(root, enforce_hashes=False)

    print("PASS RICE Method-IR held-out structural/source-binding verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
