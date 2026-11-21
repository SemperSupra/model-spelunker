#!/usr/bin/env python3
"""Pure public-safe batch-packet validator and weak-actor handoff compiler.

This is NOT an executor, queue, scheduler, authority source or model router.
Every printed candidate is advisory; Agent Dispatch performs external admission.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

THIS = Path(__file__).resolve().parent
PUBLIC_REF = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(issues|pull|actions/runs)/[0-9]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
ID = re.compile(r"^[A-Z][A-Z0-9-]{3,35}$")
VALID_STATES = {"READY", "BLOCKED_ADMISSION", "BLOCKED_INPUT", "IN_PROGRESS", "DONE_VERIFIED", "FAILED"}
VALID_CLASSES = {"PUBLIC_SOURCE", "SYNTHETIC", "PRIVATE"}
VALID_RUNTIMES = {"public-gha", "private-admitted-guest"}
VALID_ROLES = {"developer", "critic", "planner", "operator", "integrator"}


def assert_valid(condition, label):
    if not condition:
        raise ValueError(label)


def validate(plan):
    assert_valid(isinstance(plan, dict) and plan.get("schema") == "qwen-independent-batches/v1", "schema")
    assert_valid(plan.get("dispatcher") == "AGENT_DISPATCH_ONLY", "do not create second scheduler")
    assert_valid(isinstance(plan.get("max_parallel"), int) and 1 <= plan["max_parallel"] <= 3, "parallel cap")
    assert_valid(plan.get("public_host_effects") is False, "public effects must be denied")
    assert_valid(isinstance(plan.get("tasks"), list) and 1 <= len(plan["tasks"]) <= 16, "task count")
    ids = set()
    source_paths = []
    role_budget = {}
    for t in plan["tasks"]:
        assert_valid(isinstance(t, dict), "task type")
        task_id = t.get("id")
        assert_valid(isinstance(task_id, str) and ID.fullmatch(task_id) and task_id not in ids, "duplicate/invalid task id")
        ids.add(task_id)
        assert_valid(t.get("state") in VALID_STATES, f"{task_id}: state")
        assert_valid(t.get("classification") in VALID_CLASSES, f"{task_id}: classification")
        assert_valid(t.get("runtime") in VALID_RUNTIMES, f"{task_id}: runtime")
        assert_valid(t.get("role") in VALID_ROLES, f"{task_id}: role")
        assert_valid(t["classification"] == "PRIVATE" or t["runtime"] == "public-gha",
                     f"{task_id}: source public/private boundary")
        assert_valid(t["runtime"] != "public-gha" or t["classification"] != "PRIVATE",
                     f"{task_id}: private source on public runner")
        assert_valid(t["runtime"] == "public-gha" or t["state"] != "READY",
                     f"{task_id}: private workcell cannot self-admit READY")
        assert_valid(isinstance(t.get("repo"), str) and
                     re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", t["repo"]), f"{task_id}: repo")
        assert_valid(isinstance(t.get("source_sha"), str) and SHA.fullmatch(t["source_sha"]),
                     f"{task_id}: source must be exact commit")
        assert_valid(isinstance(t.get("dle"), str) and PUBLIC_REF.fullmatch(t["dle"]),
                     f"{task_id}: source-of-truth issue/PR")
        assert_valid(isinstance(t.get("mission"), str) and 12 <= len(t["mission"]) <= 210,
                     f"{task_id}: bounded mission")
        assert_valid(isinstance(t.get("oracle"), str) and 12 <= len(t["oracle"]) <= 210,
                     f"{task_id}: explicit independent oracle")
        assert_valid(isinstance(t.get("failure"), str) and 12 <= len(t["failure"]) <= 210,
                     f"{task_id}: bounded failure semantics")
        assert_valid(isinstance(t.get("scope"), list) and 1 <= len(t["scope"]) <= 5,
                     f"{task_id}: source scope")
        assert_valid(isinstance(t.get("depends_on"), list), f"{task_id}: dependencies")
        assert_valid(isinstance(t.get("budget"), dict), f"{task_id}: budget")
        b = t["budget"]
        for k, low, high in (("wall_minutes", 1, 20), ("tool_calls", 1, 8),
                             ("context_tokens", 256, 1600), ("output_tokens", 128, 800)):
            assert_valid(type(b.get(k)) is int and low <= b[k] <= high, f"{task_id}: {k} budget")
        assert_valid(b.get("cost_usd") == 0 and b.get("private_actions_minutes") == 0,
                     f"{task_id}: budget must be public/free")
        assert_valid(t.get("resource_class") in ("light", "heavy"), f"{task_id}: resource class")
        assert_valid(t["state"] != "DONE_VERIFIED" or (
            isinstance(t.get("evidence"), dict) and
            SHA.fullmatch(t["evidence"].get("source_sha", "")) and
            t["evidence"]["source_sha"] == t["source_sha"] and
            t["evidence"].get("independent_oracle") == "PASS" and
            PUBLIC_REF.fullmatch(t["evidence"].get("run_url", ""))),
            f"{task_id}: unverifiable DONE marker")
        assert_valid(t["state"] != "FAILED" or (
            isinstance(t.get("evidence"), dict) and
            SHA.fullmatch(t["evidence"].get("source_sha", "")) and
            t["evidence"]["source_sha"] == t["source_sha"] and
            t["evidence"].get("independent_oracle") == "FAIL" and
            PUBLIC_REF.fullmatch(t["evidence"].get("run_url", ""))),
            f"{task_id}: unverifiable FAILED marker")
        for s in t["scope"]:
            assert_valid(isinstance(s, str) and s.startswith("qualification/") and
                         not s.startswith("/") and "//" not in s and
                         all(x not in ("", ".", "..") for x in s.rstrip("/").split("/")),
                         f"{task_id}: unsafe scope")
            source_paths.append((t["repo"], task_id, s.rstrip("/")))
        role_budget[t["role"]] = role_budget.get(t["role"], 0) + 1
    mapping = {t["id"]: t for t in plan["tasks"]}
    for t in plan["tasks"]:
        deps = t["depends_on"]
        assert_valid(all(isinstance(x, str) and x in mapping and x != t["id"] for x in deps),
                     f"{t['id']}: missing/self dependency")
        assert_valid(len(deps) == len(set(deps)), f"{t['id']}: duplicate dependency")
        if t["state"] in ("READY", "IN_PROGRESS", "DONE_VERIFIED"):
            assert_valid(all(mapping[x]["state"] == "DONE_VERIFIED" for x in deps),
                         f"{t['id']}: dependency not verified")
    visited = set()
    visiting = set()
    def walk(id_):
        assert_valid(id_ not in visiting, "dependency cycle")
        if id_ in visited:
            return
        visiting.add(id_)
        for dep in mapping[id_]["depends_on"]:
            walk(dep)
        visiting.remove(id_)
        visited.add(id_)
    for id_ in ids:
        walk(id_)
    # Every declared source scope has a single writer across all parallel branches.
    for i, (repo_a, a, path_a) in enumerate(source_paths):
        for repo_b, b, path_b in source_paths[i+1:]:
            if repo_a != repo_b or a == b:
                continue
            assert_valid(not (path_a == path_b or path_a.startswith(path_b+"/") or
                              path_b.startswith(path_a+"/")),
                         f"source scope collision {a}/{b}")
    return plan


def plan_candidates(plan):
    validate(plan)
    ready = [x for x in plan["tasks"] if x["state"] == "READY"]
    ready.sort(key=lambda t: (t["resource_class"] == "heavy", t["id"]))
    selected = []
    heavy = 0
    for task in ready:
        if len(selected) >= plan["max_parallel"]:
            break
        if task["resource_class"] == "heavy" and heavy >= 1:
            continue
        selected.append(task)
        heavy += task["resource_class"] == "heavy"
    return {"schema": "qwen-batch-candidates/v1",
            "dispatch_authorized": False,
            "dispatcher": "AGENT_DISPATCH_ONLY",
            "candidate_ids": [t["id"] for t in selected],
            "eligible": len(ready),
            "in_progress": [t["id"] for t in plan["tasks"] if t["state"] == "IN_PROGRESS"],
            "failed": [t["id"] for t in plan["tasks"] if t["state"] == "FAILED"],
            "blocked": [{"id": t["id"], "state": t["state"]} for t in plan["tasks"]
                        if t["state"].startswith("BLOCKED")],
            "verified_count": sum(t["state"] == "DONE_VERIFIED" for t in plan["tasks"]),
            "collisions": 0, "private_actions_minutes": 0}


def actor_card(t):
    """Small bounded instruction for weaker model; cannot confer authority."""
    data = {
        "packet": t["id"],
        "role": t["role"],
        "source": f'{t["repo"]}@{t["source_sha"]}',
        "authoritative_dle": t["dle"],
        "only_edit_paths": t["scope"],
        "mission": t["mission"],
        "independent_acceptance": t["oracle"],
        "on_failure": t["failure"],
        "max_tool_calls": t["budget"]["tool_calls"],
        "max_context_tokens": t["budget"]["context_tokens"],
        "max_wall_minutes": t["budget"]["wall_minutes"],
        "mandatory_sequence": "observe DLE -> plan -> admitted apply in owned branch -> test -> independent oracle -> source/receipt/PR DLE -> stop",
        "rule": "Never self-promote results, widen paths, read secrets, dispatch without admission, merge main, or send private data to public CI."
    }
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("validate", "candidates", "cards", "hash"))
    p.add_argument("--file", default=str(THIS/"workset.public.json"))
    args = p.parse_args()
    raw = Path(args.file).read_bytes()
    doc = validate(json.loads(raw))
    if args.command == "validate":
        print("PASS qwen batch packet contract")
    elif args.command == "hash":
        print(hashlib.sha256(raw).hexdigest())
    elif args.command == "candidates":
        print(json.dumps(plan_candidates(doc), indent=2, sort_keys=True))
    elif args.command == "cards":
        for t in sorted(doc["tasks"], key=lambda a: a["id"]):
            print(json.dumps(actor_card(t), sort_keys=True))
if __name__ == "__main__":
    main()
