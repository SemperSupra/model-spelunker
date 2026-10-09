#!/usr/bin/env python3
"""Post-run synthetic boundary repair diagnostic; never changes task verdict.

Consumes only task-allowlisted output snapshot and sanitized adapter summary.
Reports *case pass/fail booleans*, tool names, and approval counts, never code,
prompts, tool arguments, user paths, tokens, or untrusted model prose.
Run only in an ephemeral, credential-free qualification workcell.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

OUTPUT = Path("src/retry.py")
ALLOWED_TOOLS = {"read_file", "write_file", "list_files"}

CASES = [
    ("step-1", [1], 1), ("step-2", [2], 2),
    ("step-3", [3], 4), ("step-5", [5], 16),
    ("cap-default", [6], 30), ("cap-explicit", [4, 3, 20], 20),
    ("base-explicit", [2, 5, 99], 5),
    ("cap-underflow", [1, 7, 3], 1),
    ("invalid-zero", [0], "ValueError"),
    ("invalid-negative", [-1], "ValueError"),
]
CHILD = r"""
import json, runpy, sys
filename=sys.argv[1]
cases=json.loads(sys.argv[2])
try:
    fn=runpy.run_path(filename)["backoff_seconds"]
    result={}
    for name,args,expected in cases:
        try:
            actual=fn(*args)
            passed=type(actual) is int and actual == expected
        except ValueError:
            passed=(expected == "ValueError")
        except BaseException:
            passed=False
        result[name]=bool(passed)
except BaseException:
    result={name:False for name,_,_ in cases}
print("DIAG_CASES="+json.dumps(result,sort_keys=True))
"""


def bounded_summary(snapshot_dir: Path, diagnostics: Path, task_receipt: Path) -> dict:
    snap_root = snapshot_dir.resolve()
    manifest_path = snap_root / "snapshot_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing allowed-output snapshot manifest")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    rows=manifest.get("files", {})
    if set(rows) != {OUTPUT.as_posix()}:
        raise ValueError("diagnostic must use exactly the synthetic permitted target")
    source=snap_root / OUTPUT
    row=rows[OUTPUT.as_posix()]
    if not row.get("present") or source.is_symlink() or not source.is_file():
        raise ValueError("missing permitted output in snapshot")
    data=source.read_bytes()
    expected="sha256:"+hashlib.sha256(data).hexdigest()
    if row.get("sha256") != expected or row.get("size_bytes") != len(data):
        raise ValueError("snapshot content/hash disagreement")
    if len(data) > 65536:
        raise ValueError("diagnostic source exceeds bounded size")
    receipt=json.loads(task_receipt.read_text(encoding="utf-8"))
    if receipt.get("task", {}).get("id") != "boundary-bugfix-v0":
        raise ValueError("diagnostic limited to synthetic boundary-bugfix-v0")
    details=json.loads(diagnostics.read_text(encoding="utf-8"))
    stdout=str(details.get("candidate_stdout_tail", ""))
    summary_lines=[x.removeprefix("OPENWORKER_SUMMARY=") for x in stdout.splitlines() if x.startswith("OPENWORKER_SUMMARY=")]
    if not summary_lines:
        raise ValueError("adapter summary missing from bounded diagnostics")
    summary=json.loads(summary_lines[-1])
    tool_names=list(summary.get("tool_calls", []))
    if any(name not in ALLOWED_TOOLS for name in tool_names):
        raise ValueError("observed tool name not on synthetic workcell allowlist")
    approvals=summary.get("approvals", [])
    if not isinstance(approvals, list):
        raise ValueError("malformed approval summary")
    counts={"allowed":0,"denied":0}
    for row in approvals:
        if not isinstance(row, dict) or type(row.get("allowed")) is not bool:
            raise ValueError("malformed approval entry")
        counts["allowed" if row["allowed"] else "denied"]+=1
    try:
        parsed=ast.parse(data.decode("utf-8"))
        syntax_valid=True
        signature_function_present=any(isinstance(n,ast.FunctionDef) and n.name=="backoff_seconds" for n in ast.walk(parsed))
    except (SyntaxError, UnicodeError):
        syntax_valid=False
        signature_function_present=False
    # The candidate output is untrusted code. The offline subprocess is
    # timeout-bounded, isolated from user credentials and reports booleans only.
    # Never print the subprocess output unless it contains the exact marker.
    outcome=None
    if syntax_valid:
        command=[sys.executable,"-I","-B","-c",CHILD,str(source),json.dumps(CASES)]
        try:
            run=subprocess.run(command,capture_output=True,text=True,timeout=5,check=False,
                               env={"PATH":"/usr/bin:/bin","PYTHONDONTWRITEBYTECODE":"1"})
            lines=[line.removeprefix("DIAG_CASES=") for line in run.stdout.splitlines() if line.startswith("DIAG_CASES=")]
            if lines:
                parsed_cases=json.loads(lines[-1])
                if set(parsed_cases)=={row[0] for row in CASES} and all(type(value) is bool for value in parsed_cases.values()):
                    outcome=parsed_cases
        except (OSError,subprocess.TimeoutExpired,ValueError):
            pass
    return {
        "schema_version":1,
        "record_type":"synthetic-boundary-postwrite-diagnostic",
        "task_id":"boundary-bugfix-v0",
        "task_receipt_evidence_digest":receipt.get("evidence_digest"),
        "output_sha256":expected,
        "output_size_bytes":len(data),
        "python_syntax_valid":syntax_valid,
        "backoff_function_declared":signature_function_present,
        "tool_name_counts":{k:tool_names.count(k) for k in sorted(ALLOWED_TOOLS)},
        "approval_counts":counts,
        "case_pass":outcome,
        "postwrite_accepted":bool(receipt.get("observation",{}).get("success")),
        "note":"Diagnostic only; original external verifier remains authoritative",
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--snapshot-dir",type=Path,required=True)
    ap.add_argument("--diagnostics",type=Path,required=True)
    ap.add_argument("--receipt",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    try:
        doc=bounded_summary(args.snapshot_dir,args.diagnostics,args.receipt)
        args.output.write_text(json.dumps(doc,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        print("MODEL_SPELUNKER_BOUNDARY_DIAGNOSTIC="+json.dumps(doc,sort_keys=True),flush=True)
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print("BOUNDARY_DIAGNOSTIC_BLOCKED="+type(exc).__name__,file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
