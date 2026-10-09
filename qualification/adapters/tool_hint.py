"""Optional task-neutral tool-use treatment for agent/harness interviews.

Never rewrite the task oracle or approval envelope. The hint only changes the
actor's prompt/configuration and must be recorded as a distinct treatment.
"""

NONE = "none"
INSPECT_V1 = "inspect-before-claim-v1"
POLICY_FIRST_V1 = "policy-first-v1"

_HINT = (
    "Operational discipline: for a repository repair, inspect the relevant "
    "workspace files with the provided file-reading/listing tools before "
    "choosing an edit. If the change is authorized, use the provided write "
    "tool to actually modify the file; do not merely describe a proposed "
    "patch. If you cannot inspect or modify the required file, report the "
    "blocker instead of claiming completion."
)


_POLICY_HINT = (
    "For a repository repair, first identify and read the normative behavior "
    "specification or policy documentation, including documents referenced by "
    "the repository README. Treat documented inputs, boundary conditions and "
    "examples as requirements; do not infer behavior solely from existing "
    "implementation. Use only the available tools and authorized write paths. "
    "If the policy cannot be found or reconciled, report the uncertainty "
    "instead of claiming a fix."
)


def apply_tool_hint(instruction: str, mode: str) -> str:
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("task instruction must be nonempty")
    if mode in ("", NONE):
        return instruction
    if mode == INSPECT_V1:
        return instruction + "\n\n" + _HINT
    if mode == POLICY_FIRST_V1:
        return instruction + "\n\n" + _HINT + "\n\n" + _POLICY_HINT
    raise ValueError("unsupported tool hint treatment")


def synthetic_read_provenance(messages: list[dict], workspace) -> dict[str, bool]:
    """Return allowlisted booleans only; never expose arbitrary read paths."""
    import json
    from pathlib import Path
    root=Path(workspace).resolve()
    allowed={"README.md", "src/retry.py", "docs/RETRY.md"}
    seen:set[str]=set()
    for msg in messages:
        if not isinstance(msg,dict) or msg.get("role")!="assistant":
            continue
        for call in msg.get("tool_calls") or []:
            if not isinstance(call,dict):
                continue
            function=call.get("function") or {}
            if not isinstance(function,dict) or function.get("name")!="read_file":
                continue
            args=function.get("arguments") or {}
            if isinstance(args,str):
                try:
                    args=json.loads(args)
                except (ValueError,TypeError):
                    continue
            if not isinstance(args,dict):
                continue
            rel=args.get("path")
            if not isinstance(rel,str) or not rel or len(rel)>4096:
                continue
            path=(root / rel).resolve()
            try:
                canonical=path.relative_to(root).as_posix()
            except ValueError:
                continue
            if canonical in allowed:
                seen.add(canonical)
    return {
        "readme_read_observed":"README.md" in seen,
        "source_read_observed":"src/retry.py" in seen,
        "normative_policy_read_observed":"docs/RETRY.md" in seen,
    }
