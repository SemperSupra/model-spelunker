#!/usr/bin/env python3
"""Read-only checkout observation and synthetic Git calibration; not authorization."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

def git(root,*args):
    env={k:v for k,v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0",GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git","-C",str(root),*args],env=env,capture_output=True,check=True,timeout=15).stdout

def read_checkout(root,commit,tree):
    start=time.monotonic()
    findings=[]
    actual=None
    actual_tree=None
    if not all(isinstance(s,str) and re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})",s) for s in (commit,tree)):
        findings.append("INVALID_EXPECTED_IDENTITY")
    else:
        try:
            root=Path(root).resolve(strict=True)
            if Path(os.fsdecode(git(root,"rev-parse","--show-toplevel")).strip()).resolve()!=root:
                findings.append("WRONG_ROOT")
            actual=git(root,"rev-parse","--verify","HEAD^{commit}").decode().strip()
            actual_tree=git(root,"rev-parse","--verify","HEAD^{tree}").decode().strip()
            if actual!=commit:findings.append("COMMIT_MISMATCH")
            if actual_tree!=tree:findings.append("TREE_MISMATCH")
            if git(root,"status","--porcelain=v1","-z","--untracked-files=all","--ignore-submodules=none"):
                findings.append("DIRTY_CHECKOUT")
            if git(root,"rev-parse","--verify","HEAD^{commit}").decode().strip()!=actual:
                findings.append("HEAD_CHANGED_DURING_CHECK")
        except (OSError,ValueError,subprocess.SubprocessError):
            findings.append("OBSERVATION_UNAVAILABLE")
    return {"verdict":"MATCH" if not findings else "HOLD","findings":findings,
            "observed_commit":actual,"observed_tree":actual_tree,"wall_seconds":time.monotonic()-start,
            "authorization_granted":False,"operation_completed":False}

def self_test():
    rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/"fixture";p.mkdir()
        git(p,"init","--initial-branch=main")
        git(p,"config","user.name","Synthetic Control")
        git(p,"config","user.email","synthetic@example.invalid")
        git(p,"config","commit.gpgsign","false")
        (p/"contract.txt").write_text("initial\n",encoding="utf-8")
        (p/"nested").mkdir()
        (p/"nested"/"tracked.txt").write_text("fixture\n",encoding="utf-8")
        git(p,"add",".");git(p,"commit","-m","initial synthetic fixture")
        old=git(p,"rev-parse","HEAD").decode().strip()
        oldtree=git(p,"rev-parse","HEAD^{tree}").decode().strip()
        (p/"contract.txt").write_text("updated\n",encoding="utf-8")
        git(p,"add",".");git(p,"commit","-m","updated synthetic fixture")
        new=git(p,"rev-parse","HEAD").decode().strip()
        tree=git(p,"rev-parse","HEAD^{tree}").decode().strip()
        def case(name,root,commit,expected_tree,expected):
            r=read_checkout(root,commit,expected_tree)
            assert r["findings"]==expected,(name,r)
            assert r["verdict"]==("HOLD" if expected else "MATCH")
            assert not r["authorization_granted"] and not r["operation_completed"]
            rows.append({"case":name,**r})
        case("clean",p,new,tree,[])
        case("wrong-base",p,old,oldtree,["COMMIT_MISMATCH","TREE_MISMATCH"])
        case("wrong-tree",p,new,oldtree,["TREE_MISMATCH"])
        case("nested-directory",p/"nested",new,tree,["WRONG_ROOT"])
        case("missing",p/"missing",new,tree,["OBSERVATION_UNAVAILABLE"])
        case("invalid-expected",p,"HEAD",tree,["INVALID_EXPECTED_IDENTITY"])
        (p/"contract.txt").write_text("dirty\n",encoding="utf-8")
        case("tracked-dirty",p,new,tree,["DIRTY_CHECKOUT"])
        git(p,"add","contract.txt")
        case("staged-dirty",p,new,tree,["DIRTY_CHECKOUT"])
        git(p,"reset","--hard","HEAD")
        (p/"unexpected.txt").write_text("untracked\n",encoding="utf-8")
        case("untracked",p,new,tree,["DIRTY_CHECKOUT"])
        (p/"unexpected.txt").unlink()
        git(p,"checkout","--detach",new)
        case("detached-exact",p,new,tree,[])
        assert git(p,"status","--porcelain=v1")==b""
    return {"scope":"SYNTHETIC_GIT_CHECKOUT_CALIBRATION","platform":os.name,"controls":len(rows),"matched":len(rows),"rows":rows}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--root")
    parser.add_argument("--commit")
    parser.add_argument("--tree")
    parser.add_argument("--out")
    a=parser.parse_args()
    if a.self_test:
        r=self_test()
    elif all((a.root,a.commit,a.tree)):
        r=read_checkout(a.root,a.commit,a.tree)
    else:
        parser.error("provide --self-test or --root, --commit and --tree")
    payload=json.dumps(r,sort_keys=True)
    if a.out:
        with open(a.out,"x",encoding="utf-8") as f:f.write(payload+"\n")
    print("GIT_CHECKOUT_PREFLIGHT="+payload)
    raise SystemExit(2 if r.get("verdict")=="HOLD" else 0)
