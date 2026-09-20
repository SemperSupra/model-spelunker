#!/usr/bin/env python3
from qualification.export_hosted_realization import project

actor={
    "model":{"provider":"openrouter","id":"openrouter/free","realization":"router"},
    "execution_environment":{"inference_route":"openrouter:free-router"},
}
receipt={
    "run_id":"20260920T140757Z-test",
    "observation":{"workload":{"resolved_models":[],"serving_providers":[]}},
}
value=project(actor,receipt)
assert value["provenance_strength"]=="ROUTED_UNKNOWN"
assert value["route"]["mode"]=="intermediary"
assert value["route"]["intermediary"]=="openrouter"

actor2={
    "model":{"provider":"google","id":"gemini-3.7-flash","realization":"hosted-service"},
    "execution_environment":{"inference_route":"direct:google-ai-studio"},
}
receipt2={
    "run_id":"20260920T141129Z-test",
    "observation":{"workload":{"resolved_models":["gemini-3.7-flash"],"system_fingerprints":["fp-1"],"service_tiers":["free"]}},
}
value2=project(actor2,receipt2)
assert value2["provenance_strength"]=="FINGERPRINTED_HOSTED"
assert value2["resolved_model"]=="gemini-3.7-flash"
assert value2["system_fingerprint"]=="fp-1"
assert value2["route"]["mode"]=="direct"

print("PASS hosted realization projection")
