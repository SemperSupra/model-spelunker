"""Encoded audiovisual fixture controls. No natural media or model claims."""
import hashlib
import json
import math
import os
import pathlib
import random
import struct
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction

ROOT=pathlib.Path(__file__).resolve().parents[2]
SIZE=32
RATE=8000
WINDOW=2000
ARMS=("good","valid_alt","late_audio","timestamp_shift","wrong_rate","no_audio","truncated","silent","wrong_tone")
VALID={"good","valid_alt"}
INSTRUCTION=("Produce a one-second Matroska clip: four lossless FFV1 RGB frames at 4 fps, "
             "a red square in the upper left always and a blue square in the lower right in exactly frame 1 or 2 "
             "(zero-based); mono 8 kHz PCM, one 400 Hz tone lasting 0.25 s aligned to the blue event, silence otherwise. "
             "Both streams start at time zero. Save clip.mkv. Do not change intent.json.")

def write(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n",encoding="utf-8")

def sha(raw):return "sha256:"+hashlib.sha256(raw).hexdigest()
def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def run(args,timeout=15):
    return subprocess.check_output(args,stderr=subprocess.PIPE,timeout=timeout)
def paint(buf,x,y,rgb):
    for dy in range(4):
        for dx in range(4):
            i=3*((y+dy)*SIZE+x+dx)
            buf[i:i+3]=bytes(rgb)
def generate(arm):
    visual=2 if arm=="valid_alt" else 1
    acoustic=2 if arm in ("valid_alt","late_audio") else 1
    with tempfile.TemporaryDirectory() as tmp:
        p=pathlib.Path(tmp);frames=[]
        for i in range(3 if arm=="truncated" else 4):
            buf=bytearray(SIZE*SIZE*3);paint(buf,2,2,(255,0,0))
            if i==visual:paint(buf,24,24,(0,0,255))
            frames.append(bytes(buf))
        raw=p/"frames.rgb";raw.write_bytes(b"".join(frames))
        pcm=[]
        for i in range(4):
            f=(300 if arm=="wrong_tone" else 400) if i==acoustic and arm!="silent" else 0
            pcm.extend(round(10000*math.sin(2*math.pi*f*j/RATE)) for j in range(WINDOW))
        audio=p/"sound.wav"
        with wave.open(str(audio),"wb") as w:
            w.setparams((1,2,RATE,len(pcm),"NONE","not compressed"))
            w.writeframes(struct.pack("<"+"h"*len(pcm),*pcm))
        cmd=["ffmpeg","-nostdin","-v","error","-y","-f","rawvideo","-pixel_format","rgb24","-video_size","32x32",
             "-framerate","5" if arm=="wrong_rate" else "4","-i",str(raw)]
        if arm!="no_audio":
            if arm=="timestamp_shift":cmd+=["-itsoffset","0.25"]
            cmd+=["-i",str(audio)]
        cmd+=["-map","0:v:0","-c:v","ffv1","-pix_fmt","bgr0","-threads","1"]
        if arm!="no_audio":cmd+=["-map","1:a:0","-c:a","pcm_s16le"]
        run(cmd+["clip.mkv"])

def observe(root):
    # No reliance on candidate-provided metadata or event time. Decode the
    # actual container and independently check stream timestamps and samples.
    result={"valid":False}
    def reject(reason):
        result["reason"]=reason
        return result
    try:
        if {p.name for p in root.iterdir()}!={"clip.mkv","intent.json"}:
            return reject("workspace")
        for p in root.iterdir():
            if p.is_symlink() or not p.is_file() or p.stat().st_size>1024*1024:
                return reject("workspace")
        if json.loads((root/"intent.json").read_text(encoding="utf-8"))!={"scenario":INSTRUCTION}:
            return reject("intent")
        clip=str(root/"clip.mkv")
        info=json.loads(run(["ffprobe","-v","error","-show_streams","-show_frames","-of","json",clip]))
        streams=info["streams"];vs=[s for s in streams if s["codec_type"]=="video"];au=[s for s in streams if s["codec_type"]=="audio"]
        if len(streams)!=2 or len(vs)!=1 or len(au)!=1:return reject("streams")
        v,a=vs[0],au[0]
        if (v["codec_name"],v["width"],v["height"],Fraction(v["r_frame_rate"]))!=("ffv1",SIZE,SIZE,Fraction(4)):
            return reject("video_format")
        if (a["codec_name"],int(a["sample_rate"]),a["channels"])!=("pcm_s16le",RATE,1):
            return reject("audio_format")
        vf=[f for f in info["frames"] if f["media_type"]=="video"]
        af=[f for f in info["frames"] if f["media_type"]=="audio"]
        vtimes=[float(f["best_effort_timestamp_time"]) for f in vf]
        result["video_pts_seconds"]=vtimes
        if len(vtimes)!=4 or any(abs(t-i/4)>0.001 for i,t in enumerate(vtimes)):
            return reject("video_timestamps")
        # Matroska millisecond timestamp precision; allow a 1.1 ms
        # quantization tolerance while checking continuous decoded audio.
        samples=0;atimes=[]
        for f in af:
            t=float(f["best_effort_timestamp_time"]);atimes.append(t)
            if abs(t-samples/RATE)>0.0011:return reject("audio_timestamps")
            samples+=int(f["nb_samples"])
        result["audio_pts_seconds"]=atimes
        if samples!=RATE:return reject("audio_duration")
        data=run(["ffmpeg","-nostdin","-v","error","-i",clip,"-map","0:v:0",
                  "-an","-c:v","rawvideo","-pix_fmt","rgb24","-vsync","0","-threads","1","-f","rawvideo","-"])
        raw_audio=run(["ffmpeg","-nostdin","-v","error","-i",clip,"-map","0:a:0","-vn","-c:a","pcm_s16le","-f","s16le","-"])
        framebytes=3*SIZE*SIZE
        if len(data)!=4*framebytes or len(raw_audio)!=2*RATE:return reject("decoded_duration")
        expected_red={(x,y) for y in range(2,6) for x in range(2,6)}
        expected_blue={(x,y) for y in range(24,28) for x in range(24,28)}
        visual=[]
        for k in range(4):
            frame=data[k*framebytes:(k+1)*framebytes]
            red=set();blue=set()
            for i in range(SIZE*SIZE):
                rgb=tuple(frame[3*i:3*i+3]);point=(i%SIZE,i//SIZE)
                if rgb==(255,0,0):red.add(point)
                elif rgb==(0,0,255):blue.add(point)
                elif rgb!=(0,0,0):return reject("unexpected_pixels")
            if red!=expected_red:return reject("red_shape")
            if blue:
                if blue!=expected_blue:return reject("blue_shape")
                visual.append(k)
        values=struct.unpack("<8000h",raw_audio);acoustic=[]
        for k in range(4):
            w=values[k*WINDOW:(k+1)*WINDOW]
            if all(s==0 for s in w):continue
            rms=math.sqrt(sum(s*s for s in w)/len(w));signs=[s>0 for s in w if s]
            freq=sum(x!=y for x,y in zip(signs,signs[1:]))*RATE/(2*len(w))
            if not (6000<=rms<=8000 and abs(freq-400)<=4):return reject("tone")
            acoustic.append(k)
        result.update(visual_windows=visual,acoustic_windows=acoustic,
                      individually_valid_streams=visual in ([1],[2]) and acoustic in ([1],[2]))
        if not result["individually_valid_streams"]:return reject("event_presence")
        if visual!=acoustic:return reject("cross_stream_alignment")
        result["valid"]=True;result["reason"]="accepted";return result
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,struct.error):
        return reject("decode_or_metadata_error")

def main(out):
    out.mkdir(parents=True,exist_ok=False)
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    versions={t:run([t,"-version"]).decode("utf-8",errors="replace").splitlines()[0] for t in ("ffmpeg","ffprobe")}
    write(out/"runtime.json",versions)
    task=out/"package";(task/"fixture").mkdir(parents=True)
    write(task/"fixture/intent.json",{"scenario":INSTRUCTION})
    (task/"verify.py").write_text("import subprocess,sys\nraise SystemExit(subprocess.call([sys.executable,"+repr(str(pathlib.Path(__file__).resolve()))+",'--verify',sys.argv[1]]))\n",encoding="utf-8")
    task_id="encoded-av-timestamps-v0"
    write(task/"task.json",{"schema_version":1,"id":task_id,"task_class":"framework.encoded-av",
          "instruction":INSTRUCTION,"fixture":"fixture","verifier":"verify.py","limits":{"wall_seconds":25},
          "success":{"kind":"deterministic-final-state"},"allowed_write_paths":["clip.mkv"],"projected_tools":["write_file"]})
    arms=list(ARMS);random.Random(20261126).shuffle(arms);rows=[]
    for index,arm in enumerate(arms):
        d=out/"trials"/str(index);d.mkdir(parents=True)
        meta=d/"candidate.json";exp=d/"experiment.json";receipt=d/"receipt.json";snap=d/"snapshot"
        write(meta,{"harness":{"name":"scripted-encoded-av"},"model":{"id":"none"},"toolset":["write_file"],"arm":arm,"runtime":versions})
        write(exp,{"schema_version":2,"id":"encoded-av-controls-r0","task":{"id":task_id},
                   "claim_type":"framework-proving","experimental_role":"control","design_block":index,
                   "primary_responses":["acceptance","stream_timestamp_fidelity"]})
        cmd=[sys.executable,str(ROOT/"qualification/run_task.py"),"--task-commit",commit,
             "--substrate-profile-id","framework-linux-ffmpeg","--substrate-profile-commit",commit,
             "--experiment",str(exp),"--snapshot-dir",str(snap),str(task),str(meta),str(receipt),"--",
             sys.executable,str(pathlib.Path(__file__).resolve()),"--candidate",arm]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=60)
        check(receipt.is_file(),"receipt absent: "+p.stderr[-500:])
        raw=receipt.read_bytes();r=json.loads(raw);obs=r["observation"];expected=arm in VALID
        check(r["task"]["id"]==task_id and r["task"]["source_commit"]==commit and r["experiment"]["claim_type"]=="framework-proving","receipt identity")
        check(obs["candidate_exit_code"]==0 and not obs["timed_out"],"unexpected encoder failure "+arm)
        check(obs["success"] is expected and p.returncode==(0 if expected else 1),"wrong verdict "+arm)
        clip=snap/"clip.mkv";manifest=json.loads((snap/"snapshot_manifest.json").read_text(encoding="utf-8"))["files"]["clip.mkv"]
        check(manifest["present"] and manifest["sha256"]==sha(clip.read_bytes()),"snapshot digest")
        # Re-run independent decode on the captured artifact, not on the candidate state.
        (snap/"intent.json").write_bytes((task/"fixture/intent.json").read_bytes())
        # snapshot includes bookkeeping file not part of candidate workspace.
        with tempfile.TemporaryDirectory() as tmp:
            isolated=pathlib.Path(tmp)
            for name in ("clip.mkv","intent.json"):(isolated/name).write_bytes((snap/name).read_bytes())
            detail=observe(isolated)
        check(detail["valid"] is expected,"independent snapshot verdict "+arm)
        if arm=="late_audio":
            check(detail.get("individually_valid_streams") is True and detail["reason"]=="cross_stream_alignment","late-audio causal control")
        if arm=="timestamp_shift":check(detail["reason"]=="audio_timestamps","PTS fault not isolated")
        rows.append({"arm":arm,"run_id":r["run_id"],"receipt_sha256":sha(raw),"artifact_sha256":manifest["sha256"],"accepted":obs["success"],"detail":detail})
    check(len({r["run_id"] for r in rows})==len(arms),"duplicate run")
    s={"scope":"FRAMEWORK_PROVING_ONLY","source_commit":commit,"actual_receipts":len(rows),
       "accepted":sum(r["accepted"] for r in rows),"rejected":sum(not r["accepted"] for r in rows),
       "runtime":versions,"promotion_authorized":False,
       "limitations":"Synthetic lossless Matroska FFV1/PCM only; observed hosted FFmpeg build, not pinned. No natural-media, generative model, speech, lip sync, lossy codec, variable-framerate or production qualification claim.","rows":rows}
    write(out/"summary.json",s);print("ENCODED_AV="+json.dumps(s),flush=True)

if __name__=="__main__":
    if sys.argv[1]=="--candidate":generate(sys.argv[2])
    elif sys.argv[1]=="--verify":sys.exit(0 if observe(pathlib.Path(sys.argv[2]))["valid"] else 1)
    else:main(pathlib.Path(sys.argv[1]).resolve())
