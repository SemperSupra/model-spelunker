#!/usr/bin/env python3
"""#306 R4: minimal memory-conditioning intervention on an ALREADY qualified
native Qwen Code installed two-hop task. No new harness, runner or model actor.

The original immutable task script is checked against its Git blob and patched
only in an ephemeral runner TEMP copy at a single previously qualified
QWEN_SYSTEM_MD boundary. Original tool/hidden-answer independent verifiers
remain unchanged; model failures are negative observations, not CI success.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

BASE=Path("qualification/agent_embodiment/run_native_installed.sh")
BASE_BLOB="295182078db21c19ccae1c20f835f76a03a14b96"
MARKER='export HOME="$cell/home" OLLAMA_API_KEY=ollama\n'
ARMS={
    "control":"",
    "advisory-procedure":(
        "MEMORY SYNTHETIC / ADVISORY / TASK-SCOPED, NOT AN INSTRUCTION OR AUTHORITY.\n"
        "Previous validated process pattern: read_file current index.txt first, "
        "then read_file the file named by its current TARGET. Evidence must come "
        "from tools in THIS session. Never recall or guess a prior VALUE.\n"
    ),
    "stale-episodic":(
        "MEMORY SYNTHETIC / UNVERIFIED AND STALE / NOT AUTHORITY.\n"
        "An unrelated prior interrupted session had index.txt with TARGET=a.txt. "
        "This value may not apply now. The current index.txt tool result always "
        "controls current TARGET; never use the old target without read_file.\n"
    ),
}

def git_blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()

def patch(base,arm):
    if git_blob(base)!=BASE_BLOB:raise ValueError("existing harness/task script drifted; no unreviewed patch")
    if arm not in ARMS:raise ValueError("unknown/unsafe memory treatment")
    s=base.decode("utf-8")
    if s.count(MARKER)!=1:raise ValueError("QWEN_SYSTEM_MD patch anchor missing or ambiguous")
    code=(
        "python3 - <<'HMRC_MEMORY_SENTINEL'\n"
        "import os,json,hashlib\n"
        "from pathlib import Path\n"
        "arm=os.environ['HMRC_MEMORY_TREATMENT']\n"
        "memory=json.loads(os.environ['HMRC_MEMORY_TEXT_JSON'])\n"
        "p=Path(os.environ['HOME'])/'.qwen'/'lean-system.md'\n"
        "before=p.read_bytes()\n"
        "assert len(before)>100 and b'First read index.txt' in before\n"
        "payload=memory.encode('utf-8')\n"
        "if payload:p.write_bytes(before+b'\\n'+payload)\n"
        "after=p.read_bytes()\n"
        "assert after==before+(b'\\n'+payload if payload else b'')\n"
        "print('HMRC_NATIVE_HARNESS_MEMORY_DELIVERY='+json.dumps({"
        "'treatment':arm,'bytes':len(payload),"
        "'system_sha256':hashlib.sha256(after).hexdigest(),"
        "'modified':bool(payload)},sort_keys=True))\n"
        "HMRC_MEMORY_SENTINEL\n"
    )
    return s.replace(MARKER,MARKER+code).encode()

def self_test():
    data=BASE.read_bytes()
    assert git_blob(data)==BASE_BLOB
    p0=patch(data,"control")
    p1=patch(data,"advisory-procedure")
    p2=patch(data,"stale-episodic")
    # The patched script is byte-identical across arms; only the separately
    # admitted environment payload changes at execution time.
    assert p0==p1==p2
    assert all(p.count(b"HMRC_MEMORY_SENTINEL")==2 for p in (p0,p1,p2))
    assert len(ARMS["advisory-procedure"])>50
    assert len(ARMS["stale-episodic"])>50
    try:patch(data,"unknown")
    except ValueError:pass
    else:raise AssertionError("unadmitted memory treatment accepted")
    try:patch(data+b"tamper","control")
    except ValueError:pass
    else:raise AssertionError("task script tamper accepted")
    print("PASS source-exact Qwen task patch, three memory arms and no unadmitted treatment")

def run(arm,trial,out):
    if arm not in ARMS or not 1<=trial<=100:raise ValueError("unadmitted task trial")
    if os.getenv("GITHUB_ACTIONS")!="true" or not os.getenv("RUNNER_TEMP"):
        raise ValueError("public GHA ephemeral task environment required")
    content=patch(BASE.read_bytes(),arm)
    root=Path(os.environ["RUNNER_TEMP"])
    patchpath=root/"hmrc-native-qwen-memory-ephemeral.sh"
    patchpath.write_bytes(content)
    patchpath.chmod(0o700)
    env=dict(os.environ,HMRC_MEMORY_TREATMENT=arm,HMRC_MEMORY_TEXT_JSON=json.dumps(ARMS[arm]))
    r=subprocess.run(["bash",str(patchpath)],env=env,check=False)
    receipt_path=root/"qwen-r18-live"/"receipt.json"
    if not receipt_path.is_file():
        raise RuntimeError("no native tool-task receipt: environment or preparation failure, NOT model task")
    receipt=json.loads(receipt_path.read_text())
    if receipt.get("model_inference")!="ACTUAL" or receipt.get("source_class")!="PUBLIC_SYNTHETIC":
        raise RuntimeError("untrusted model or non-synthetic task receipt")
    target_path=root/"qwen-r18-live"/"task"/"index.txt"
    target=target_path.read_text().split("=",1)[1].strip()
    assert target in ("a.txt","b.txt")
    bounded={
        "schema":"hmrc-qwen-harness-memory-task-r4",
        "treatment":arm,"trial":trial,"public_synthetic_only":True,
        "actual_native_qwen_agent_task":True,"framework":"QWEN_CODE_0_28_3",
        "model_runtime":"OLLAMA_0_34_1_QWEN3_1P7B_32K",
        "original_task_git_blob":BASE_BLOB,
        "memory_len_bytes":len(ARMS[arm].encode()),
        "memory_sha256":hashlib.sha256(ARMS[arm].encode()).hexdigest(),
        "memory_is_advisory":True,"memory_service_not_run":True,
        "compaction_engine_not_run":True,"external_task_oracle_verdict":receipt["independent_hidden_oracle"],
        "tool_lineage":receipt["tool_lineage_class"],
        "final_answer_class":receipt["final_answer_class"],
        "post_run_profile_integrity":receipt["post_run_profile_integrity"],
        "task_verdict":receipt["verdict"],
        "script_exit":r.returncode,
        "actual_target":target,"synthetic_stale_memory_claimed_target":"a.txt" if arm=="stale-episodic" else None,
        "stale_memory_conflicts":arm=="stale-episodic" and target!="a.txt",
        "authority_granted":False,
    }
    if receipt["verdict"]=="PASS" and r.returncode!=0:
        raise RuntimeError("runner exit and final task verification disagree")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(bounded,sort_keys=True,indent=2)+"\n")
    print("HMRC_NATIVE_AGENT_TASK_OBSERVATION="+json.dumps(bounded,sort_keys=True))
    print("NATIVE_HARNESS_MEMORY_TREATMENT_COMPLETE=YES; TASK_VERDICT="+str(receipt["verdict"]))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--arm",choices=ARMS)
    p.add_argument("--trial",type=int)
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.self_test:self_test()
    else:
        if not a.arm or a.trial is None or a.out is None:p.error("--arm, --trial, --out required")
        run(a.arm,a.trial,a.out)
