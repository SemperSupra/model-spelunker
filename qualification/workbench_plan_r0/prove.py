"""Independent fixtures: known-good and planted defects, not a model judge."""
import copy,hashlib,json,pathlib,subprocess,sys,time
HERE=pathlib.Path(__file__).resolve().parent
OUT=pathlib.Path(sys.argv[1]).resolve();OUT.mkdir(parents=True,exist_ok=True)
def hashj(v):return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def invoke(i,s,folder):
    folder.mkdir(); ip=folder/"intent.json";sp=folder/"spec.json"
    ip.write_text(json.dumps(i));sp.write_text(json.dumps(s))
    t=time.perf_counter()
    p=subprocess.run([sys.executable,str(HERE/"plan.py"),"review","--intent",str(ip),"--spec",str(sp)],cwd=folder,capture_output=True,text=True,timeout=10)
    result=json.loads(p.stdout);result["observed_exit"]=p.returncode;result["review_wall_s"]=time.perf_counter()-t
    (folder/"review.json").write_text(json.dumps(result,indent=2));return result
rows=[]
for rep in range(3):
    intent={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","revision":rep,"objective":"Prove framework, not operational qualification","allowed_engines":["cpu"],"max_trials":12+rep}
    spec={"schema_version":1,"scope":"FRAMEWORK_PROVING_ONLY","intent_digest":hashj(intent),"treatments":[{"engine":"cpu","memory":"off","retrieval":None},{"engine":"cpu","memory":"on","retrieval":2}],"repetitions":3}
    cases=[("good",intent,spec,set())]
    def add(name,change,expected):
        s=copy.deepcopy(spec);change(s);cases.append((name,intent,s,expected))
    add("budget",lambda s:s.update(repetitions=100),{"BUDGET_EXCEEDED"})
    add("incompatible",lambda s:s["treatments"][0].update(retrieval=4),{"INCOMPATIBLE_TREATMENT"})
    add("duplicate",lambda s:s["treatments"].append(copy.deepcopy(s["treatments"][0])),{"DUPLICATE_TREATMENT"})
    add("engine",lambda s:s["treatments"][0].update(engine="gpu"),{"ENGINE_NOT_ALLOWED"})
    add("scope",lambda s:s.update(scope="OPERATIONAL"),{"SCOPE_DENIED"})
    add("extra",lambda s:s.update(execute=True),{"UNKNOWN_SPEC_FIELDS"})
    corrected={**intent,"revision":rep+1,"max_trials":4}
    cases.append(("superseded",corrected,spec,{"STALE_INTENT","BUDGET_EXCEEDED"}))
    replanned={**spec,"intent_digest":hashj(corrected),"repetitions":2}
    cases.append(("replanned",corrected,replanned,set()))
    for name,i,s,want in cases:
        result=invoke(i,s,OUT/(str(rep)+"-"+name))
        got={f["code"] for f in result["findings"]}
        assert got==want,(rep,name,got,want)
        assert result["observed_exit"]==(2 if want else 0)
        assert result["execution_authorized"] is False and result["promotion_authorized"] is False
        rows.append({"rep":rep,"case":name,"expected":sorted(want),"observed":sorted(got),"wall_s":result["review_wall_s"]})
summary={"scope":"FRAMEWORK_PROVING_ONLY","cases":len(rows),"correct":len(rows),"positive":sum(not r["expected"] for r in rows),"negative":sum(bool(r["expected"]) for r in rows),"rows":rows,"limitations":"synthetic trusted intent fixtures; not authentication, not actual human feedback service, no execution or real actor qualification"}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2))
print("PLAN_CRITIC="+json.dumps(summary),flush=True)
