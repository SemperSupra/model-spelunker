#!/usr/bin/env python3
"""Public synthetic wording-only pilot; uses existing native task and oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import resource
import secrets
import re
import tempfile
from unittest.mock import patch as mock_patch
from io import BytesIO

BASE=Path("qualification/agent_embodiment/run_native_installed.sh")
BLOB="295182078db21c19ccae1c20f835f76a03a14b96"
MODEL_DIGEST="8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
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
        ('export OLLAMA_MODELS="$RUNNER_TEMP/qwen-r18-models"','export OLLAMA_MODELS="${PILOT_SHARED_MODELS:-$RUNNER_TEMP/qwen-r18-models}"'),
        ("'"+ORIGINAL+"'",'"$PILOT_PROMPT"'),
        ('.startswith("8f68893c685c")',' == "'+MODEL_DIGEST+'"'),
        ('import os,secrets,json','import os,secrets,json,hashlib'),
        ('"VALUE="+secrets.token_hex(16)+"\\n")\n(root/"task/b.txt").write_text("VALUE="+secrets.token_hex(16)+"\\n")','"VALUE="+hashlib.sha256((os.environ["PILOT_PAIR_NONCE"]+":a").encode()).hexdigest()[:32]+"\\n")\n(root/"task/b.txt").write_text("VALUE="+hashlib.sha256((os.environ["PILOT_PAIR_NONCE"]+":b").encode()).hexdigest()[:32]+"\\n")'),
        ('export HOME="$cell/home"','unset PILOT_PAIR_NONCE\nexport HOME="$cell/home"'),
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
    digest="sha256:"+MODEL_DIGEST
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
    test_sensor()
    print("PASS pinned source, exact model digest, unchanged oracle, and reported-metric controls")
def positive_int(v):
    return v if type(v) is int and v>0 else None
def sensor(stdout):
    empty={"prompt_tokens":None,"completion_tokens":None,"reported_usage_status":"UNKNOWN","reported_duration_ms":None,"reported_api_duration_ms":None,"reported_turns":None,"observed_tool_calls":None,"observed_tool_errors":None}
    try: rows=json.loads(stdout)
    except (ValueError,TypeError):return empty
    if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):return empty
    results=[x for x in rows if x.get("type")=="result"]
    if len(results)!=1:return empty
    result=results[0]
    usage=result.get("usage")
    usage=usage if isinstance(usage,dict) else {}
    blocks=[]
    for item in rows:
        msg=item.get("message")
        if isinstance(msg,dict) and isinstance(msg.get("content"),list):
            blocks.extend(x for x in msg["content"] if isinstance(x,dict))
    inp=positive_int(usage.get("input_tokens"))
    output=positive_int(usage.get("output_tokens"))
    return {"prompt_tokens":inp,"completion_tokens":output,
        "reported_usage_status":"HARNESS_REPORTED_BOTH" if inp is not None and output is not None else "PARTIAL_OR_UNKNOWN",
        "reported_duration_ms":positive_int(result.get("duration_ms")),
        "reported_api_duration_ms":positive_int(result.get("duration_api_ms")),
        "reported_turns":positive_int(result.get("num_turns")),
        "observed_tool_calls":sum(x.get("type")=="tool_use" for x in blocks),
        "observed_tool_errors":sum(x.get("type")=="tool_result" and x.get("is_error") is True for x in blocks)}
def test_sensor():
    r={"type":"result","usage":{"input_tokens":22,"output_tokens":11},"duration_ms":99,"duration_api_ms":70,"num_turns":2}
    x=sensor(json.dumps([{"message":{"content":[{"type":"tool_use"},{"type":"tool_result","is_error":True}]}},r]))
    assert (x["prompt_tokens"],x["completion_tokens"],x["observed_tool_calls"],x["observed_tool_errors"])==(22,11,1,1)
    for raw in ("not json","[]",json.dumps([r,r]),json.dumps([{"type":"result","usage":{"input_tokens":0,"output_tokens":-1}}])):
        x=sensor(raw)
        assert x["prompt_tokens"] is None and x["completion_tokens"] is None
def run(arm,target,out,nonce=None,shared_models=None,pair_meta=None):
    if os.getenv("GITHUB_ACTIONS")!="true" or not os.getenv("RUNNER_TEMP"):
        raise ValueError("ephemeral public runner required")
    root=Path(os.environ["RUNNER_TEMP"])
    staged=root/"pilot-native.sh"
    staged.write_text(patch(BASE.read_bytes()))
    prompt=PROMPTS[arm]
    start=time.monotonic()
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    env=dict(os.environ,PILOT_PROMPT=prompt,PILOT_TARGET=target,PILOT_PAIR_NONCE=nonce or secrets.token_hex(16))
    if shared_models is not None:env["PILOT_SHARED_MODELS"]=str(shared_models)
    p=subprocess.run(["bash",str(staged)],env=env)
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    elapsed=time.monotonic()-start
    path=root/"qwen-r18-live/receipt.json"
    row={"arm":arm,"target":target,"source_blob":BLOB,"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"elapsed_including_setup_s":elapsed,"runner_exit":p.returncode,"prompt_tokens":None,"completion_tokens":None,"agent_elapsed_s":None,"model_digest":None,"verdict":"NO_RECEIPT","scope":"PUBLIC_SYNTHETIC_ONLY"}
    row.update(pair_meta or {})
    row["child_user_cpu_s"]=after.ru_utime-before.ru_utime
    row["child_system_cpu_s"]=after.ru_stime-before.ru_stime
    if path.is_file():
        r=json.loads(path.read_text())
        if r.get("source_class")!="PUBLIC_SYNTHETIC" or r.get("model_inference")!="ACTUAL":
            raise ValueError("wrong evidence class")
        assert (root/"qwen-r18-live/task/index.txt").read_text().strip()=="TARGET="+target
        assert r["verdict"] in ("PASS","FAIL")
        row.update({k:r[k] for k in ("framework","runtime","independent_hidden_oracle","tool_lineage_class","post_run_profile_integrity","verdict")})
        row["agent_elapsed_s"]=r["pilot_agent_seconds_coarse"]
        row["model_digest"]=(root/"pilot-model-digest.txt").read_text().strip()
        assert row["model_digest"].removeprefix("sha256:")==MODEL_DIGEST
        row.update(sensor((root/"qwen-r18-live/cli.stdout").read_text(errors="replace")))
        task=root/"qwen-r18-live/task"
        row["synthetic_fixture_sha256"]=hashlib.sha256(b"".join((task/x).read_bytes() for x in ("index.txt","a.txt","b.txt"))).hexdigest()
        if r["verdict"]=="PASS":
            assert p.returncode==0 and all(r[k]=="PASS" for k in ("independent_hidden_oracle","tool_lineage_class","post_run_profile_integrity"))
    out.write_text(json.dumps(row,indent=2,sort_keys=True)+"\n")
    print("PUBLIC_PROMPT_PILOT="+json.dumps(row,sort_keys=True))
    if row["verdict"]=="NO_RECEIPT":raise SystemExit(2)
    return row
def paired(order,target,out):
    parent=Path(os.environ["RUNNER_TEMP"])
    nonce=secrets.token_hex(16)
    arms=["original","numbered"] if order=="original-first" else ["numbered","original"]
    rows=[]
    for pos,arm in enumerate(arms,1):
        with tempfile.TemporaryDirectory(prefix="public-prompt-cell-",dir=parent) as tmp:
            with mock_patch.dict(os.environ,{"RUNNER_TEMP":tmp}):
                rows.append(run(arm,target,out.with_name(out.stem+"-"+arm+".json"),nonce,parent/"prompt-pair-model-cache",{"pair":target+"-"+order,"position":pos,"process_state":"fresh","download_cache":"shared"}))
    assert rows[0]["synthetic_fixture_sha256"]==rows[1]["synthetic_fixture_sha256"]
    out.write_text(json.dumps({"pair":target+"-"+order,"same_fixture":True,"arms":arms},sort_keys=True)+"\n")
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--arm",choices=PROMPTS)
    p.add_argument("--pair",choices=["original-first","numbered-first"])
    p.add_argument("--target",choices=["a.txt","b.txt"])
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.self_test:self_test()
    elif a.pair and a.target and a.out and not a.arm:paired(a.pair,a.target,a.out)
    elif a.arm and a.target and a.out and not a.pair:run(a.arm,a.target,a.out)
    else:p.error("arm, target and out required")
