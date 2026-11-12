#!/usr/bin/env python3
"""Real authenticated Go → ComfyUI nn.Embedding → nn.Conv2d paired job smoke."""
import hashlib
import json
import os
import time
from integration_smoke import fetch

def main():
    token=os.environ["CONDITIONING_TEST_TOKEN"]
    status,raw,_=fetch("/api/v1/capabilities",token)
    caps=json.loads(raw)
    assert status==200 and "toy-conditioned-v1" in caps["allowed_workflows"]
    status,raw,_=fetch("/api/v1/openapi.json",token)
    doc=json.loads(raw)
    assert status==200
    assert "toy-conditioned-v1" in doc["components"]["schemas"]["JobInput"]["properties"]["workflow"]["enum"]
    jobs=[
       {"workflow":"toy-conditioned-v1","prompt":"red-square",
        "seed":71,"variant":x,"size":64} for x in ("base","modified")
    ]
    packet={"request_id":"actual-two-torch-models-0001","jobs":jobs}
    code,raw,_=fetch("/api/v1/batches",token,packet)
    accepted=json.loads(raw)
    assert code==202 and accepted["idempotent_replay"] is False
    ids=accepted["job_ids"]
    code,raw,_=fetch("/api/v1/batches",token,packet)
    assert code==202 and json.loads(raw)["job_ids"]==ids
    assert json.loads(raw)["idempotent_replay"] is True
    results=[]
    deadline=time.monotonic()+120
    for ident,variant in zip(ids,("base","modified")):
        while time.monotonic()<deadline:
            _,raw,_=fetch("/api/v1/jobs/"+ident,token)
            job=json.loads(raw)
            if job["state"]=="COMPLETED":break
            if job["state"].startswith("UNKNOWN"):
                raise AssertionError("NATIVE_CONDITIONED_JOB_AMBIGUOUS")
            time.sleep(0.5)
        else:raise AssertionError("NATIVE_CONDITIONED_JOB_TIMEOUT")
        assert job["request"]["workflow"]=="toy-conditioned-v1"
        assert job["request"]["prompt"]=="red-square"
        assert job["request"]["variant"]==variant
        code,png,kind=fetch("/api/v1/jobs/"+ident+"/image",token)
        assert code==200 and kind.startswith("image/png")
        assert png[:8]==bytes.fromhex("89504e470d0a1a0a")
        digest=hashlib.sha256(png).hexdigest()
        assert digest==job["image_sha256"]
        results.append({"variant":variant,"image_sha256":digest,"bytes":len(png)})
    assert len(results)==2 and results[0]["image_sha256"]!=results[1]["image_sha256"]
    print(json.dumps({
      "schema":"conditioning-controller-two-model-native/v1",
      "status":"REAL_CONTROLLER_TWO_TORCH_MODULE_QUEUE_PASS",
      "prompt":"red-square","seed":71,
      "verified_outputs":results,
      "idempotent_replay":True,"model_acquisition":False,
      "real_llm":False,"real_diffusion":False,
      "cuda_inference":False,"actual_heretic":False
    },sort_keys=True))

if __name__=="__main__":
    main()
