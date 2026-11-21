#!/usr/bin/env python3
"""No-content Qwen settings drift audit after actual agent launch."""
import hashlib
import json
from pathlib import Path
from qwen_embody import canonical, load_profile, settings

def audit(path: Path) -> dict:
    expected=settings(load_profile())
    observed_bytes=path.read_bytes()
    expected_bytes=canonical(expected)
    try:
        observed=json.loads(observed_bytes)
    except (ValueError,UnicodeError):
        return {"schema":"agent-embodiment-settings-drift/v1",
                "class":"INVALID_JSON","semantic_equivalent":False,"byte_identical":False,
                "changed_paths":["INVALID_JSON"]}
    paths=[]
    def walk(left,right,key="$"):
        if type(left) is not type(right):
            paths.append(key)
        elif isinstance(left,dict):
            for name in sorted(set(left)|set(right)):
                if name not in left or name not in right:
                    paths.append(key+"."+name)
                else:
                    walk(left[name],right[name],key+"."+name)
        elif isinstance(left,list):
            if len(left)!=len(right):
                paths.append(key+".length")
            else:
                for i,(a,b) in enumerate(zip(left,right)):
                    walk(a,b,key+"["+str(i)+"]")
        elif left!=right:
            paths.append(key)
    walk(expected,observed)
    same=not paths
    return {
        "schema":"agent-embodiment-settings-drift/v1",
        "class":"UNCHANGED" if observed_bytes==expected_bytes else
                "SERIALIZATION_ONLY" if same else "SEMANTIC_DRIFT",
        "semantic_equivalent":same,
        "byte_identical":observed_bytes==expected_bytes,
        "changed_paths":paths,
        "observed_settings_sha256":hashlib.sha256(observed_bytes).hexdigest(),
        "expected_settings_sha256":hashlib.sha256(expected_bytes).hexdigest()
    }

def selftest():
    import tempfile
    target=settings(load_profile())
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"settings.json"
        p.write_bytes(canonical(target))
        assert audit(p)["class"]=="UNCHANGED"
        p.write_text(json.dumps(target,indent=2),encoding="utf-8")
        assert audit(p)["class"]=="SERIALIZATION_ONLY"
        mutated=json.loads(json.dumps(target))
        mutated["tools"]["core"]=["run_shell_command"]
        p.write_text(json.dumps(mutated))
        d=audit(p)
        assert d["class"]=="SEMANTIC_DRIFT" and "$.tools.core[0]" in d["changed_paths"]
        assert "run_shell_command" not in json.dumps(d)
        p.write_text("bad JSON")
        assert audit(p)["class"]=="INVALID_JSON"
    print(json.dumps({"schema":"agent-embodiment-drift-negative/v1",
        "state":"PASS","cases":4},sort_keys=True))
if __name__=="__main__":selftest()
