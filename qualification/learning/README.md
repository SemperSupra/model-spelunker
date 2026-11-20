# Memory, skill and self-improvement qualification (Issue #206)

**Status:** source-only treatment definition and first $0 public screening. No automatic
memory promotion, skill installation, model fine-tuning, OpenCode V2 admission, or
local sovereign execution is claimed by this repository change.

## Authority and execution

GitHub [issue #206](https://github.com/SemperSupra/model-spelunker/issues/206)
owns this experiment and its exact-head receipts; #139 owns configured-actor
science and Agent Dispatch private #104 owns actor admission. The adopted WoW
and the project-native DLE remain authority. Model Spelunker verifies outcomes,
not whose prose sounds most convincing.

The first public execution reuses:

- The immutable OpenWorker build and admission receipt in
  `.github/workflows/openworker-prebuilt-ollama-qualification.yml`.
- One pinned `ollama:qwen3:1.7b` CPU model (checked against its expected digest).
- Existing deterministic tasks and hidden/frozen validators, with newly
  created disposable workspaces for every rep.
- A public, unprivileged GitHub-hosted Ubuntu 24.04 runner, with no inherited
  provider credentials, private task material, paid endpoints, or home-host
  connections. Public runner cost is subject to provider fair-use policy.
- `qualification/run_task.py` run receipt, same tool/authority envelope.
  Neither a model completion marker nor a learned-skill proposal is PASS.

**Do not** call this a sandbox containment test. The hosted runner is ephemeral,
but the OpenWorker process is not demonstrated to be isolated from its entire
job. Public-safe synthetic tasks only.

## Treatments and two screening tasks

| Arm | Frozen input | Experimental claim |
| --- | --- | --- |
| `control` | existing task, no extra hint | existing baseline |
| `episodic-memory` | `learning/memory-recall-v1.txt`, explicitly provisional | *fixed episodic retrieval* proxy, not native persistent auto-memory |
| `procedural-skill` | `learning/skill-procedure-v1.txt`, explicitly provisional | *fixed procedural skill* proxy, not native OpenCode SKILL tool |

Files are source-pinned, allowlisted, read-bounded, UTF-8 validated, and
accessed by known treatment ID rather than arbitrary model-supplied paths.
The memory and skill texts are similar in length and intentionally **contain
no task solution**, target/private material or release authority. Both are
advisory. The existing `tool_hint_mode` is used to avoid another injection
mechanism; the value is included in the configured actor candidate's digest.
The exact source commit also pins the retrieved bundle bytes.

First matrix: `boundary-bugfix-v0` and `validation-discovery-v0`, each with
three treatments (six cells, one independent rep each). This is a **screening
experiment only**; N=1 per cell cannot establish general improvement. The
existing preregistered task oracle must self-test and score each result.

## Exact execution

Source-only tests on any approved local or public-safe executor:

```sh
PYTHONPATH=. python -m unittest qualification.test_learning_treatment -v
PYTHONPATH=. python qualification/test_tool_hint.py
python qualification/tasks/boundary-bugfix-v0/verify.py --self-test
python qualification/tasks/validation-discovery-v0/verify.py --self-test
```

The workflow `.github/workflows/learning-bootcamp-screen.yml` runs six
model-backed cells from an issue-linked public pull request in this public
repository. It uses the existing reusable Qwen/Ollama workflow and its
admitted immutable harness, pinned GitHub Actions and sanitized receipts.
No public workflow should receive credentials or source/data from the
private sovereign worksets.

Collect each job's independent receipt and exact head SHA. Reuse
`qualification/reduce_evidence.py` and the configured-actor interview
science; do not invent an alternate success scorer. Compare matched
task/treatment results, unauthorized writes, false completion, observed
tool-use, elapsed time, memory/context bytes and compute use. An
infrastructure timeout/model-hydration failure is not a model-quality loss.

## Hard stops and progressive design

- **Immediate stop:** unexpected secret/external network exposure, false-positive
  verification, invalid task custody, executable untrusted skill, agent gain of
  additional authority or unexpected paid consumption. Treat UNKNOWN as UNKNOWN.
- **No useful signal:** avoid repeated expensive inference; keep negative
  results and compare task/harness interaction instead of adding complexity.
- **Positive screen:** require at least one independently verified correction
  on a task where the control failed, no security/authority regression, and a
  repeatability plan. Replicate with randomized run order and at least three
  fresh reps before suggesting task-conditional skill adoption.
- **Held-out transfer:** use distinct synthetic task families (including
  `authority-boundary-restraint-v0`) kept out of the bundle authorship path.
  A test cannot be used both to derive and validate a learned lesson.
- **Real learning:** the agent must propose a lesson from a prior episode,
  a separate critic must falsify it, and a fresh verifier must establish
  benefit on unseen tasks. Only then may a versioned SKILL.md be promoted
  with rollback. Do not let a model edit its own authority, A–D information
  boundary, T-tier protection, evaluator, or owner WoW.
- **Sovereign crossover:** only after issue #558's credential exposure is
  contained and current BigMac/TrueNAS host/actor authorization is verified.
  Qualify installed V1 and pinned OpenCode V2 separately; then test local
  pinned memory plugin and Qwen Code's first-party auto-memory as separate
  treatments. No public runner connects to sovereign private models.

## Reproduction/handoff fields

Every rep records: issue/DLE ref, actor/session, task ID and package digest,
source commit, bundle mode and source digest, model/config/tool/runtime route,
data class, isolation and external effect authority, verifier disposition,
success/failure/UNKNOWN, raw token/byte and wall resource evidence if available,
candidate custody, tested rollback/cleanup result, next executable action.
Never store raw prompts containing private material or credentials in a
public artifact. This document is a plan, not a claim that learning occurred.
