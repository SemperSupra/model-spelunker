"""Reusable deterministic, bounded evidence checks for source-known RE interviews.

This code is verifier-side only; no inference/model calls, no external downloads,
no R8 mapping ingestion, no private corpus.
"""
from __future__ import annotations
import json
import math
from pathlib import Path

MAX_JSON_BYTES = 64 * 1024

def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    """Fail closed on conflicting claims, including nested duplicate JSON members."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result

def _reject_nonfinite_constant(_value: str):
    raise ValueError("non-finite JSON literal")

def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed

def pristine_task_workspace(root: Path, task_dir: Path, allowed_output: str) -> bool:
    """Task-local integrity oracle: all fixture files unchanged; exactly one new output.

    The candidate only receives a copy of task_dir/fixture. This helper runs on
    the verifier side, where the original fixture is available as a reference.
    It does not replace the OpenWorker tool and filesystem admission boundary.
    """
    fixture = task_dir / "fixture"
    if (root.is_symlink() or fixture.is_symlink()
            or not root.is_dir() or not fixture.is_dir()):
        return False
    originals = list(fixture.iterdir())
    observed = list(root.iterdir())
    # These source-known task fixtures are deliberately flat. A changed layout
    # requires a separately reviewed fixture/workspace contract.
    if any(path.is_symlink() or not path.is_file() for path in originals + observed):
        return False
    by_name = {path.name: path for path in originals}
    if allowed_output in by_name:
        return False
    if {path.name for path in observed} != set(by_name) | {allowed_output}:
        return False
    return all((root / name).read_bytes() == source.read_bytes()
               for name, source in by_name.items())

def bounded_json(root: Path, name: str) -> dict:
    """Only an existing, regular, non-symlink file inside the task workspace."""
    if name not in ("evidence.json", "classification.json", "triage.json"):
        raise ValueError("unexpected evidence file")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or symlinked task file")
    size = path.stat().st_size
    if not (0 < size <= MAX_JSON_BYTES):
        raise ValueError("out of bounds JSON input")
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_json_pairs,
        parse_constant=_reject_nonfinite_constant,
        parse_float=_finite_json_float,
    )
    if not isinstance(value, dict):
        raise ValueError("JSON root must be object")
    return value

def ref_resolve(evidence: dict, reference: str):
    """Resolve RFC6901 paths, allowing only exact fixture/evidence file."""
    prefix = "evidence.json#"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValueError("evidence citations must remain local")
    pointer = reference[len(prefix):]
    if not pointer.startswith("/") or len(pointer) > 180:
        raise ValueError("invalid evidence path")
    current = evidence
    for item in pointer[1:].split("/"):
        # Reject malformed escape sequences; unlike lenient string replacement.
        t = 0
        while t < len(item):
            if item[t] == "~":
                if t + 1 >= len(item) or item[t + 1] not in "01":
                    raise ValueError("malformed RFC6901 escape")
                t += 2
            else:
                t += 1
        key = item.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            raise ValueError("citation points outside fixture")
        current = current[key]
    return current

def check_refs(evidence: dict, refs, required: tuple[str, ...]) -> bool:
    if not isinstance(refs, list) or not 2 <= len(refs) <= 12:
        return False
    if any(not isinstance(ref, str) for ref in refs):
        return False
    if sorted(set(refs)) != refs:
        return False
    if not set(required).issubset(set(refs)):
        return False
    try:
        for ref in refs:
            if ref_resolve(evidence, ref) is None:
                return False
    except ValueError:
        return False
    return True

def pointer(*components: str) -> str:
    return "evidence.json#/" + "/".join(
        x.replace("~", "~0").replace("/", "~1") for x in components
    )
