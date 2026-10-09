"""Secret-free free-model interview guardrails; no hosted inference in this test."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
catalog=json.loads((root/"qualification/models/hosted-api.json").read_text())
expected={
    "openrouter-cohere-north-mini-code-free":"cohere/north-mini-code:free",
    "openrouter-poolside-laguna-s21-free":"poolside/laguna-s-2.1:free",
}
for key,model in expected.items():
    entry=catalog["candidates"][key]
    assert entry["provider"]=="openrouter"
    assert entry["model"]==model and entry["model"].endswith(":free")
    assert entry["cost_class"]=="zero-token-price"
    assert entry["api_base"]=="https://openrouter.ai/api/v1"
    assert entry["treatment_kind"]=="model"
    assert entry["reasoning_effort"]=="omit"
    assert not entry.get("extra_body")

# A third, much larger free model is a separate selected treatment; it does
# not change the original two-model cohort's model list or reporting defaults.
nemotron=catalog["candidates"]["openrouter-nvidia-nemotron3-ultra-free"]
assert nemotron["provider"]=="openrouter"
assert nemotron["model"]=="nvidia/nemotron-3-ultra-550b-a55b:free"
assert nemotron["cost_class"]=="zero-token-price"
assert nemotron["reasoning_effort"]=="omit"
assert nemotron["treatment_kind"]=="model"
single=(root/".github/workflows/openworker-nemotron-ultra-free-interview.yml").read_text()
assert "branches: [main]" in single
assert "pull_request:" not in single
assert "secrets: inherit" in single
assert "issues: write" in single
assert "max_iterations: '8'" in single
assert "--expected-max-iterations 8" in single
assert "--expected-model \"nvidia/nemotron-3-ultra-550b-a55b:free\"" in single

hosted=(root/".github/workflows/openworker-hosted-api-qualification.yml").read_text()
caller=(root/".github/workflows/openworker-free-coding-model-interview.yml").read_text()
assert "workflow_call:" in hosted
assert "zero_token_price" in hosted
assert "QUALIFICATION_BOUNDARY=tool-calling-not-supported" in hosted
assert "QUALIFICATION_BOUNDARY=nonzero-provider-price" in hosted
assert "OPENWORKER_ARTIFACT_REF" in hosted
assert "openworker-prebuilt-venv" not in hosted
assert "openworker-free-coding-model-interview.yml" in caller
assert "branches: [main]" in caller
assert "pull_request:" not in caller
assert "secrets: inherit" in caller
assert "fail-fast: false" in caller
for key in expected:
    assert caller.count(key)==1
assert "boundary-bugfix-v0" in caller
print("PASS free-model cohort and trust-boundary contract")

diagnostic=(root/".github/workflows/openworker-north-tool-action-diagnostic.yml").read_text()
assert "branches: [main]" in diagnostic
assert "pull_request:" not in diagnostic
assert "secrets: inherit" in diagnostic
assert "issues: write" in diagnostic
assert "--expected-model" in diagnostic
assert "cohere/north-mini-code:free" in diagnostic
assert "openrouter-poolside-laguna-s21-free" not in diagnostic
