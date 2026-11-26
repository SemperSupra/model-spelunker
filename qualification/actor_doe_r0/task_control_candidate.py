"""Deterministic scripted controls, NOT reasoning agents."""
import os,pathlib,sys
mode=sys.argv[1];instruction=sys.stdin.read()
root=pathlib.Path.cwd();task=os.environ.get("MODEL_SPELUNKER_TASK_ID","")
if mode not in ("repair","lookup","composite"):raise ValueError("invalid control")
if "Replace the entire contents" in instruction and mode in ("repair","composite"):
    (root/"value.txt").write_bytes(b"READY\n")
elif "Read index.txt" in instruction and mode in ("lookup","composite"):
    target=(root/"index.txt").read_text().strip().split("=",1)[1]
    if target not in ("alpha.txt","beta.txt"):raise ValueError("invalid fixture target")
    (root/"value.txt").write_bytes((root/target).read_bytes())
else:
    # Deliberately unsupported task class, candidate exits successfully; oracle rejects.
    (root/"value.txt").write_bytes(b"WRONG\n")
