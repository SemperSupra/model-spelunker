# Agent framework installation, qualification and embodiment — R18

## Purpose

Build a repeatable, reproducible and evidence-backed system that can **install, configure, operate, qualify and remove** agent frameworks on multiple workcell embodiments. Agent runtimes and models are independently interchangeable *subject to their supported interface, capability, security and resource contracts*. Begin with Qwen Code, not by treating Qwen Code as a universal solution.

Required audiences: human operators (clear setup and outcomes); automation (deterministic commands, schemas, machine-readable receipts); reasoning actors (least-authority, capability-calibrated tools and recoverable instructions).

## Operations and invariants

1. **Discover** supported software release, embodiment and model/runtime options; enumerate actual host and runtime capabilities before admission.
2. **Plan** from immutable framework artifact, model binding, tools, context, memory and workcell authority. Derive a deterministic plan/digest. Plan is data, **not approval**.
3. **Admit** plan/effects at an independent authenticated workcell/Agent Dispatch trust boundary. An actor cannot approve its own scope or interpret a JSON flag as permission.
4. **Stage/install** into its owned copy-on-write/ephemeral workcell; verify exact archive hashes, archive safety, official binary version, paths and settings. Never alter the persistent control host for public synthetic tests.
5. **Configure/bind** versioned framework settings, model provider/runtime, actual supported context/output budgets, prompt/system instructions, tool allowlist, memory and environment-based credentials. Do not materialize credentials in Git, receipts, prompts or archived artifacts.
6. **Qualify** the exact *model × harness × runtime × embodiment × task × authority* treatment. Test actual execution, hidden verifier, egress and negative controls. Distinguish tool operation PASS from assistant final answer PASS; measure repeated reliability.
7. **Operate** by governed assignment→workcell→actual tool effects→external verification→DLE reconciliation; support controlled delegation and human intervention.
8. **Observe/recover/remove** persistent state and scope; preserve source provenance and redacted receipts, revoke leases and credentials, destroy only the owned workcell; prevent stale config drift.

System invariants: fail closed; source-first Git authority; deterministic, replayable plan; byte-verified software; least authority; no silent model/provider fallback; no secrets in artifacts; synthetic/public/private classification boundaries; exact task-conditioned evidence; honest censoring of provider failures; idempotent observation and bounded rollback; no invented release promotion. Every component should be substitutable only behind the same evidenced contract.

## Current reference embodiment: disposable public Linux CPU Qwen Code

`qwen-public-linux.json` pins **Qwen Code 0.28.3**, the exact official Linux x64 archive in `qualification/qwencode_public/release-manifest.json`, local Ollama OpenAI-compatible `qwen3:1.7b` at loopback, 32,768 context, 256 requested max output tokens, no MCP servers, read_file-only, zero memory/agents, no external network authority, no production admission. It references the `OLLAMA_API_KEY` **environment variable name**; it never stores a real secret. Actual Ollama service is provided separately by the task workcell, not provisioned by this installer.

The `qwen_embody.py` prototype exposes `self-test`, `plan`, `stage`, `verify`, `remove`. It uses the existing pinned `kit.py` verifier and native `--version` smoke. It **only stages/removes within GitHub Actions RUNNER_TEMP**, and refuses root reuse or unowned rollback. It does not provision Ollama, deploy Windows/macOS/TrueNAS/BigMac, enable private networking, invoke production credentials, or attest workcells. A production embodiment applicator **must** use independently admitted effects and site-specific resource capability observation; extending synthetic mode via a user-editable environment flag would be unsafe.

### Public synthetic execution

```bash
python3 qualification/agent_embodiment/qwen_embody.py self-test
python3 qualification/agent_embodiment/qwen_embody.py plan
python3 qualification/qwencode_public/kit.py fetch --platform linux-x64 --archive "$RUNNER_TEMP/qwen-code-linux-x64.tar.gz"
python3 qualification/agent_embodiment/qwen_embody.py stage --root "$RUNNER_TEMP/qwen-embodied" --archive "$RUNNER_TEMP/qwen-code-linux-x64.tar.gz"
python3 qualification/agent_embodiment/qwen_embody.py verify --root "$RUNNER_TEMP/qwen-embodied"
python3 qualification/agent_embodiment/qwen_embody.py remove --root "$RUNNER_TEMP/qwen-embodied"
```

Public GHA is the sole accepted execution environment for these instructions. Installing on a personal Windows development computer or persistent sovereign host is **not** authorized by these public synthetic commands.

## Required embodiment matrix and next implementations

| Embodiment | Framework artifact/install | Runtime/model binding | Tools/context/memory | External authority | Current state |
| --- | --- | --- | --- | --- | --- |
| Disposable public Ubuntu x64 GHA | Official pinned Qwen standalone | Loopback Ollama Qwen3:1.7b | Strict read_file, 32K, no memory | Synthetic workcell only | R18 install/config/rollback qualification |
| Windows x64 Hyper-V disposable guest | Existing pinned `Invoke-QwenCapsule.ps1` guest plan/apply/verify/rollback | Configured local/remote authorized endpoints | PS5.1, constrained tools, 32K budget by observed model | External signed workcell admission, not PR flag | Existing capsule baseline; integration/admission outstanding |
| BigMac macOS arm64 | Native upstream distribution or platform-compatible mechanism to qualify | llama-server/llama-swap, installed model census | Model-specific context/memory/tool behavior | Owner local actor/workcell | NOT ADMITTED / needs adapter & HIL |
| TrueNAS/Linux sovereign runner | Qualified Linux binary/container generation | Ollama sovereign model census | Capabilities, GPU/memory constraints, tool whitelist | Agent Dispatch workset lease + host authority | NOT ADMITTED / needs adapter & HIL |
| Public Codespaces/ephemeral cloud | Verified release and bounded user-space install | Zero-cost cloud API or public synthetic runtime | Scoped workspace, tool/network admission | Public-only workcell, no secrets on PR code | Candidate work surface/backend; needs qualification |
| Other harnesses (Aider, Pi, OpenCode, Goose, etc.) | Framework-specific installers and source pins | Same independent model/provider census | Normalized capability contracts | Same DLE/workcell contract | Future substitution/crossover |

No workcell is admitted just because its profile is listed. Model providers and workcell embodiments are orthogonal: a valid model URL does not establish reachable network permission or fit for a task.

## Release criteria

The first Qwen Code *framework embodiment MVP* requires evidence of:
- an unprivileged cold install, exact version/hash and verified settings, repeatable reinstall/rollback on a disposable workcell;
- actual model/tool calls from the configured workcell, with independent verifier and fail-closed negative controls;
- multiple source-pinned model/runtime bindings (including at least one sovereign endpoint, when independently authorized) and at least two embodiments;
- a sealed per-workcell instruction/tools/memory profile, no credential exfiltration, safe network boundary and workflow recovery;
- an end-to-end Agent Dispatch DLE workthread: assigned, admitted, executed, checked, reconciled, and terminated.

The R18 first increment covers only public-Linux pinned install/plan/verify/remove; existing R10–R17 experiments cover selected live model/tool tests. **Neither alone constitutes the MVP or production operational acceptance.**

## Future substitution interface

Represent an embodiment as `(framework_release, installer_adapter, environment_attestation, model_binding, tool_profile, memory_profile, authority_lease, task_receipt)`. Candidate implementations may substitute for each component once their actual effects, authority and qualification evidence satisfy the same invariants. Do not encode nominally 'supported' capabilities as observed acceptance.
