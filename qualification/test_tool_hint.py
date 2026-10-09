from qualification.adapters.tool_hint import NONE, INSPECT_V1, apply_tool_hint

simple = "Repair the authorized repository file."
assert apply_tool_hint(simple, NONE) == simple
assert apply_tool_hint(simple, "") == simple
hinted = apply_tool_hint(simple, INSPECT_V1)
assert hinted.startswith(simple + "\n\n")
assert "inspect the relevant workspace files" in hinted
assert "do not merely describe" in hinted
assert "report the blocker" in hinted
assert "src/retry.py" not in hinted
assert "hidden" not in hinted.lower()
assert apply_tool_hint(simple, INSPECT_V1) == hinted

for wrong in ("auto", "bypass", "run-shell", "inspect-v2"):
    try:
        apply_tool_hint(simple, wrong)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown hint treatment accepted: " + wrong)

try:
    apply_tool_hint("", INSPECT_V1)
except ValueError:
    pass
else:
    raise AssertionError("empty task instruction accepted")

print("PASS task-neutral tool hint treatment contract")
