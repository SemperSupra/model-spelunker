"""Optional task-neutral tool-use treatment for agent/harness interviews.

Never rewrite the task oracle or approval envelope. The hint only changes the
actor's prompt/configuration and must be recorded as a distinct treatment.
"""

NONE = "none"
INSPECT_V1 = "inspect-before-claim-v1"

_HINT = (
    "Operational discipline: for a repository repair, inspect the relevant "
    "workspace files with the provided file-reading/listing tools before "
    "choosing an edit. If the change is authorized, use the provided write "
    "tool to actually modify the file; do not merely describe a proposed "
    "patch. If you cannot inspect or modify the required file, report the "
    "blocker instead of claiming completion."
)


def apply_tool_hint(instruction: str, mode: str) -> str:
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("task instruction must be nonempty")
    if mode in ("", NONE):
        return instruction
    if mode != INSPECT_V1:
        raise ValueError("unsupported tool hint treatment")
    return instruction + "\n\n" + _HINT
