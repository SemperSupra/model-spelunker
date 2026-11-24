#!/usr/bin/env python3
"""Public synthetic wording-only pilot; uses existing native task and oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import re
import tempfile
from unittest.mock import patch as mock_patch
from io import BytesIO

BASE=Path("qualification/agent_embodiment/run_native_installed.sh")
BLOB="295182078db21c19ccae1c20f835f76a03a14b96"
ORIGINAL="Use read_file on index.txt. Its TARGET names a second file; read that file using read_file and output only its VALUE. Do not guess."
PROMPTS={
    "original":ORIGINAL,
    "numbered":"1. Use read_file to read index.txt.\n2. Use read_file to read the file named by its TARGET.\n3. Output only that file's VALUE. Do not guess.",
}
def git_blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def patch(data):
    if git_blob(data)!=BLOB:
        raise ValueError("source pin drift")
    text=data.decode()
    replacements=[
        ("'"+ORIGINAL+"'",'"$PILOT_PROMPT"'),
        ('target="a.txt" if secrets.randbelow(2)==0 else "b.txt"','target=os.environ["PILOT_TARGET"]'),
        ('print("PASS pinned native model census")','import os\nopen(os.environ["RUNNER_TEMP"]+"/pilot-model-digest.txt","w").write(match["digest"])\nprint("PASS pinned native model census")'),
        ('set +e\n(\n cd "$root/task"','set +e\nagent_start=$SECONDS\n(\n cd "$root/task"'),
        ('rc=$?\nset -e','rc=$?\nexport PILOT_AGENT_SECONDS=$((SECONDS-agent_start))\nset -e'),
        ('"cli_exit":int(os.environ["R18_EXIT"])','"pilot_agent_seconds_coarse":int(os.environ["PILOT_AGENT_SECONDS"]), "cli_exit":int(os.environ["R18_EXIT"])'),
    ]
    for before,after in replacements:
        if text.count(before)!=1:
            raise ValueError("missing or ambiguous exact source anchor")
        text=text.replace(before,after)
    return text
def self_test():
    data=BASE.read_bytes()
    p=patch(data)
    assert p.count('"$PILOT_PROMPT"')==1
    assert p.count("export QWEN_SYSTEM_MD")==1
    assert p.count("verify_selected(stdout,expected,decoy)") == data.decode().count("verify_selected(stdout,expected,decoy)")
    subprocess.run(["bash","-n"],input=p,text=True,check=True)
    # Bash syntax checking alone missed an embedded Python runtime error.
    # Execute the actual patched census heredoc with a simulated /api/tags reply.
    blocks=re.findall(r"python3 - <<'PY'\n(.*?)\nPY",p,re.S)
    assert len(blocks)==3
    for i,block in enumerate(blocks):
        compile(block,f"<native-heredoc-{i}>","exec")
    digest="sha256:8f68893c685c"+"0"*52
    with tempfile.TemporaryDirectory() as tmp:
        response=json.dumps({"models":[{"name":"qwen3:1.7b","digest":digest}]}).encode()
        with mock_patch.dict(os.environ,{"RUNNER_TEMP":tmp}), mock_patch("urllib.request.urlopen",return_value=BytesIO(response)):
            exec(compile(blocks[0],"<census-sensor-test>","exec"),{})
        assert (Path(tmp)/"pilot-model-digest.txt").read_text()==digest
        wrong=json.dumps({"models":[{"name":"qwen3:1.7b","digest":"sha256:"+"0"*64}]}).encode()
        with mock_patch.dict(os.environ,{"RUNNER_TEMP":tmp}), mock_patch("urllib.request.urlopen",return_value=BytesIO(wrong)):
            try:exec(compile(blocks[0],"<wrong-digest-test>","exec"),{})
            except AssertionError:pass
            else:raise AssertionError("wrong model digest accepted")
    try:patch(data+b"x")
    except ValueError:pass
    else:raise AssertionError("drift not rejected")
    print("PASS pinned source, narrow patch, unchanged independent oracle, drift refusal")
def run(arm,target,out):
    if os.getenv("GITHUB_ACTIONS")!="true" or not os.getenv("RUNNER_TEMP"):
        raise ValueError("ephemeral public runner required")
    root=Path(os.environ["RUNNER_TEMP"])
    staged=root/"pilot-native.sh"
    staged.write_text(patch(BASE.read_bytes()))
    prompt=PROMPTS[arm]
    start=time.monotonic()
    p=subprocess.run(["bash",str(staged)],env=dict(os.environ,PILOT_PROMPT=prompt,PILOT_TARGET=target))
    elapsed=time.monotonic()-start
    path=root/"qwen-r18-live/receipt.json"
    row={"arm":arm,"target":target,"source_blob":BLOB,"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"elapsed_including_setup_s":elapsed,"runner_exit":p.returncode,"prompt_tokens":None,"completion_tokens":None,"agent_elapsed_s":None,"model_digest":None,"verdict":"NO_RECEIPT","scope":"PUBLIC_SYNTHETIC_ONLY"}
    if path.is_file():
        r=json.loads(path.read_text())
        if r.get("source_class")!="PUBLIC_SYNTHETIC" or r.get("model_inference")!="ACTUAL":
            raise ValueError("wrong evidence class")
        assert (root/"qwen-r18-live/task/index.txt").read_text().strip()=="TARGET="+target
        assert r["verdict"] in ("PASS","FAIL")
        row.update({k:r[k] for k in ("framework","runtime","independent_hidden_oracle","tool_lineage_class","post_run_profile_integrity","verdict")})
        row["agent_elapsed_s"]=r["pilot_agent_seconds_coarse"]
        row["model_digest"]=(root/"pilot-model-digest.txt").read_text().strip()
        assert row["model_digest"].removeprefix("sha256:").startswith("8f68893c685c")
        if r["verdict"]=="PASS":
            assert p.returncode==0 and all(r[k]=="PASS" for k in ("independent_hidden_oracle","tool_lineage_class","post_run_profile_integrity"))
    out.write_text(json.dumps(row,indent=2,sort_keys=True)+"\n")
    print("PUBLIC_PROMPT_PILOT="+json.dumps(row,sort_keys=True))
    if row["verdict"]=="NO_RECEIPT":raise SystemExit(2)
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--arm",choices=PROMPTS)
    p.add_argument("--target",choices=["a.txt","b.txt"])
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.self_test:self_test()
    elif a.arm and a.target and a.out:run(a.arm,a.target,a.out)
    else:p.error("arm, target and out required")
