from pathlib import Path
from tempfile import TemporaryDirectory
from qualification.adapters.tool_hint import NONE, INSPECT_V1, POLICY_FIRST_V1, apply_tool_hint, synthetic_read_provenance

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
policy=apply_tool_hint(simple,POLICY_FIRST_V1)
assert policy.startswith(hinted)
assert "normative behavior" in policy
assert "README" in policy
assert "docs/RETRY.md" not in policy
assert "attempt - 1" not in policy


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

with TemporaryDirectory() as td:
    root=Path(td)
    messages=[
        {"role":"user","content":"ignore"},
        {"role":"assistant","tool_calls":[
            {"function":{"name":"read_file","arguments":'{"path":"src/retry.py"}'}},
            {"function":{"name":"read_file","arguments":'{"path":"docs/RETRY.md"}'}},
            {"function":{"name":"read_file","arguments":'{"path":"../../private-secret"}'}},
            {"function":{"name":"write_file","arguments":'{"path":"secret.txt"}'}},
        ]},
    ]
    flags=synthetic_read_provenance(messages,root)
    assert flags=={
        "readme_read_observed":False,
        "source_read_observed":True,
        "normative_policy_read_observed":True,
    }
    assert td not in str(flags)
    assert "private" not in str(flags)
    assert "secret" not in str(flags)
    assert synthetic_read_provenance([],root)=={
        "readme_read_observed":False,
        "source_read_observed":False,
        "normative_policy_read_observed":False,
    }
print("PASS synthetic policy-read provenance booleans")
