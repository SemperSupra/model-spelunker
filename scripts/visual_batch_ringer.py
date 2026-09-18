#!/usr/bin/env python3
"""Public-safe Gate-4 qualification for the content-addressed batch harness."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from tempfile import TemporaryDirectory
from visual_batch import run_batch

def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()

def main()->int:
 with TemporaryDirectory(prefix="vcw-gate4-") as tmpdir:
  root=Path(tmpdir); (root/"good-a.bin").write_bytes(b"alpha"); (root/"good-b.bin").write_bytes(b"beta")
  benchmark={
   "benchmark_id":"public-batch-fixture","benchmark_version":"v1",
   "assets":[
    {"asset":{"benchmark_asset_id":"asset-a","source_filename":"good-a.bin","sha256":sha(b"alpha")}},
    {"asset":{"benchmark_asset_id":"asset-b","source_filename":"good-b.bin","sha256":sha(b"beta")}},
    {"asset":{"benchmark_asset_id":"asset-missing","source_filename":"missing.bin","sha256":sha(b"missing")}},
   ]
  }
  calls={"n":0}
  def run_one(path,asset):
   calls["n"]+=1
   return {"run_id":f"volatile-{calls['n']}","run_digest":sha((asset.asset_id+"-stable").encode()),"observations":[]}
  kwargs=dict(
   benchmark=benchmark,image_root=root,candidate_digest="c"*64,treatment="direct-v0",
   run_one=run_one,execution_lane="public-ringer",private_inputs=False,
  )
  first=run_batch(output_dir=root/"out1",**kwargs)
  second=run_batch(output_dir=root/"out2",**kwargs)
  assert first["asset_count_requested"]==3
  assert first["asset_count_succeeded"]==2
  assert first["asset_count_failed"]==1
  assert first["failures"][0]["asset_id"]=="asset-missing"
  assert first["failures"][0]["error_kind"]=="image_missing"
  assert first["batch_digest"]==second["batch_digest"]
  assert first["run_id"]!=second["run_id"]
  assert first["private_inputs"] is False
  assert first["safeguards"]["public_runner_used_for_private_bytes"] is False
  outputs=sorted(x["output_file"] for x in first["results"])
  assert outputs==[
   "asset-a.cccccccccccc.direct-v0.json",
   "asset-b.cccccccccccc.direct-v0.json",
  ]
  result={
   "schema_version":"visual_concept_batch_gate4.v0.1","status":"pass",
   "batch_digest":first["batch_digest"],"requested":3,"succeeded":2,"failed":1,
   "failure_retained":"image_missing","content_addressed_outputs":outputs,
   "invariants":{
    "nested_asset_identity_resolved":True,"volatile_run_id_excluded_from_batch_identity":True,
    "failures_retained_without_aborting_batch":True,"public_safe_lane_explicit":True,
    "private_content_present":False,"performance_claim":False,
   }
  }
  print(json.dumps(result,sort_keys=True))
 return 0

if __name__=="__main__": raise SystemExit(main())
