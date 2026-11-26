"""Public synthetic media fixture proof, not a generative model benchmark.
Use actual PPM images, PCM WAV and ordered frame files; no video codec/ASR claim.
"""
import hashlib
import json
import pathlib
import random
import subprocess
import sys

ROOT=pathlib.Path(__file__).resolve().parents[2]

GENERATOR=r'''
import math, pathlib, struct, sys, wave

kind, arm = sys.argv[1:3]

def image(path, objects):
    pixels=bytearray([255]*12*12*3)
    for x,y,color in objects:
        for dy in range(2):
            for dx in range(2):
                i=3*((y+dy)*12+x+dx)
                pixels[i:i+3]=bytes(color)
    path.write_bytes(b"P6\n12 12\n255\n"+pixels)

red=(255,0,0);blue=(0,0,255);green=(0,255,0)
if kind=="image":
    objects=[(1,2,red),(8,7,blue)]
    if arm=="omission":objects.pop()
    if arm=="substitution":objects[1]=(8,7,green)
    if arm=="spatial":objects=[(8,7,red),(1,2,blue)]
    image(pathlib.Path("image.ppm"),objects)
elif kind=="audio":
    events=[200,400]
    if arm=="omission":events[1]=0
    if arm=="substitution":events[1]=300
    if arm=="order":events.reverse()
    pcm=[]
    for f in events:
        pcm.extend(round(10000*math.sin(2*math.pi*f*i/8000)) for i in range(2000))
    with wave.open("audio.wav","wb") as w:
        w.setparams((1,2,8000,len(pcm),"NONE","not compressed"))
        w.writeframes(struct.pack("<"+"h"*len(pcm),*pcm))
elif kind=="sequence":
    positions=[1,4,7]
    if arm=="order":positions.reverse()
    for n,x in enumerate(positions):
        if arm=="omission" and n==1:continue
        color=blue if arm=="substitution" and n==1 else red
        image(pathlib.Path(f"frame-{n}.ppm"),[(x,4,color)])
'''

VERIFIER=r'''
import json, math, pathlib, struct, sys, wave

kind=__KIND__
fixture=__FIXTURE__
red=(255,0,0);blue=(0,0,255);white=(255,255,255)

def objects(path):
    raw=path.read_bytes();header=b"P6\n12 12\n255\n"
    if not raw.startswith(header) or len(raw)!=len(header)+432:
        raise ValueError("bad fixture image encoding")
    data=raw[len(header):];found={}
    for i in range(144):
        rgb=tuple(data[i*3:i*3+3])
        if rgb==white:continue
        if rgb not in (red,blue):raise ValueError("unexpected color")
        found.setdefault(rgb,set()).add((i%12,i//12))
    boxes={}
    for c,points in found.items():
        x=min(a for a,b in points);y=min(b for a,b in points)
        if points!={(x,y),(x+1,y),(x,y+1),(x+1,y+1)}:
            raise ValueError("wrong size or shape")
        boxes[c]=(x,y)
    return boxes

def tone(window):
    rms=math.sqrt(sum(v*v for v in window)/len(window))
    if not 6000<=rms<=8000:return None
    # Independent zero-crossing estimator, exact durations fixed for fixture.
    previous=0;crossings=0
    for x in window:
        if not x:continue
        s=1 if x>0 else -1
        if previous and s!=previous:crossings+=1
        previous=s
    return crossings*8000/(2*len(window))

def verify(root):
    try:
        names={"image":{"image.ppm"},"audio":{"audio.wav"},"sequence":{f"frame-{n}.ppm" for n in range(3)}}[kind]
        if {p.name for p in root.iterdir()}!=names|{"intent.json"}:return False
        for p in root.iterdir():
            if p.is_symlink() or not p.is_file() or p.stat().st_size>65536:return False
        if (root/"intent.json").read_bytes()!=fixture:return False
        if kind=="image":
            return objects(root/"image.ppm")=={red:(1,2),blue:(8,7)}
        if kind=="sequence":
            return all(objects(root/f"frame-{i}.ppm")=={red:(x,4)} for i,x in enumerate((1,4,7)))
        with wave.open(str(root/"audio.wav"),"rb") as w:
            if (w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getnframes(),w.getcomptype())!=(1,2,8000,4000,"NONE"):
                return False
            pcm=struct.unpack("<4000h",w.readframes(4000))
        measured=[tone(pcm[i:i+2000]) for i in (0,2000)]
        return all(m is not None and abs(m-f)<=4 for m,f in zip(measured,(200,400)))
    except (OSError,ValueError,EOFError,struct.error,wave.Error):
        return False

if __name__=="__main__":
    sys.exit(0 if verify(pathlib.Path(sys.argv[1])) else 1)
'''

TASKS={
    "image":("A 12 by 12 PPM: red 2x2 square at (1,2), blue 2x2 square at (8,7), white background.",["image.ppm"],["good","omission","substitution","spatial"]),
    "audio":("8 kHz mono PCM WAV: 200 Hz tone for 0.25 seconds, then 400 Hz for 0.25 seconds.",["audio.wav"],["good","omission","substitution","order"]),
    "sequence":("Three ordered 12 by 12 PPM frames: a red 2x2 square moves along x=1,4,7 at y=4.",["frame-0.ppm","frame-1.ppm","frame-2.ppm"],["good","omission","substitution","order"]),
}
def write(p,x):p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def require(ok,msg):
    if not ok:raise RuntimeError(msg)
def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    generator=out/"generator.py";generator.write_text(GENERATOR,encoding="utf-8")
    jobs=[]
    for kind,(instruction,paths,arms) in TASKS.items():
        task=out/"packages"/kind;(task/"fixture").mkdir(parents=True)
        write(task/"fixture/intent.json",{"scenario":instruction})
        (task/"verify.py").write_text(VERIFIER.replace("__KIND__",repr(kind)).replace("__FIXTURE__",repr((task/"fixture/intent.json").read_bytes())),encoding="utf-8")
        write(task/"task.json",{"schema_version":1,"id":"media-"+kind+"-controls-v0","task_class":"framework.media-fidelity",
              "instruction":instruction,"fixture":"fixture","verifier":"verify.py","limits":{"wall_seconds":10},
              "success":{"kind":"deterministic-final-state"},"allowed_write_paths":paths,"projected_tools":["write_file"]})
        jobs.extend((kind,task,arm) for arm in arms)
    random.Random(20261126).shuffle(jobs)
    rows=[]
    for i,(kind,task,arm) in enumerate(jobs):
        d=out/"trials"/str(i);d.mkdir(parents=True)
        meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json";snap=d/"artifact"
        task_id="media-"+kind+"-controls-v0"
        write(meta,{"harness":{"name":"scripted-media-control"},"model":{"id":"none"},"toolset":["write_file"],"treatment":arm})
        write(exp,{"schema_version":2,"id":"media-fidelity-controls-r0","task":{"id":task_id},
              "claim_type":"framework-proving","experimental_role":"control","design_block":i,"primary_responses":["acceptance"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,
             "--substrate-profile-id","framework-"+sys.platform,"--substrate-profile-commit",commit,
             "--experiment",str(exp),"--snapshot-dir",str(snap),str(task),str(meta),str(receipt),
             "--",sys.executable,str(generator),kind,arm]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=30)
        require(receipt.exists(),"receipt missing "+p.stderr)
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"]
        require(r["task"]["source_commit"]==commit and r["task"]["id"]==task_id,"task identity mismatch")
        require(r["experiment"]["claim_type"]=="framework-proving","wrong purpose")
        require(obs["success"] is (arm=="good") and p.returncode==(0 if arm=="good" else 1),"wrong media verdict "+kind+"/"+arm)
        # Candidate completed for every case: these are output-fidelity faults, not transport failures.
        require(obs["candidate_exit_code"]==0 and not obs["timed_out"],"unexpected execution failure")
        require(obs["verifier_exit_code"]==(0 if arm=="good" else 1),"wrong verifier status")
        manifest=json.loads((snap/"snapshot_manifest.json").read_text(encoding="utf-8"))
        for relative,info in manifest["files"].items():
            if info["present"]:
                require(info["sha256"]=="sha256:"+hashlib.sha256((snap/relative).read_bytes()).hexdigest(),"artifact digest mismatch")
        rows.append({"kind":kind,"arm":arm,"run_id":r["run_id"],"accepted":obs["success"],
                     "receipt_sha256":"sha256:"+hashlib.sha256(raw).hexdigest()})
    require(len({r["run_id"] for r in rows})==len(rows),"duplicate receipts")
    s={"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,"actual_receipts":len(rows),
       "known_good_accepted":sum(r["accepted"] for r in rows),"planted_faults_rejected":sum(not r["accepted"] for r in rows),
       "promotion_authorized":False,"limitations":"Synthetic geometry, tone events and frame sequences only. No natural image/audio/video, TTS/ASR, audiovisual sync, codec, open-ended semantic evaluation or target capability claim.","rows":rows}
    write(out/"summary.json",s);print("MEDIA_CONTROLS="+json.dumps(s),flush=True)
if __name__=="__main__":
    main(pathlib.Path(sys.argv[1]).resolve())
