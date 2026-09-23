# Pre-local qualification readiness

This document records the qualification-methodology properties that have been
rehearsed in GitHub Actions before a GARM/sovereign worker exists. It is a
readiness ledger, not a claim that GitHub-hosted infrastructure simulates the
future local substrate.

## Ready in the portable procedure

| Gate | Evidence / behavior | Status |
| --- | --- | --- |
| Harness build is outside Actor × Task qualification | OpenWorker, Goose, and codex-exec are consumed as immutable BUILD_ADMITTED artifacts | PASS |
| Harness identity is content-addressed | Qualification actors bind immutable GHCR digests; admission provenance is separate from actor identity | PASS |
| Fetch is separate from hydration/execution | Artifact portability workflow fetches to OCI layout first, then hydrates from the local layout | PASS |
| Hydration does not require Docker | `hydrate_oci_layout.py` consumes OCI layout directly and verifies blob digests | PASS |
| Hydration fails closed on unsafe layers | Path traversal, links/devices, blob mismatch, receipt mismatch, and payload tampering are rejected | PASS |
| No source build in qualification | Prebuilt lanes hydrate admitted payloads only | PASS |
| No dependency resolution in OpenWorker qualification | Offline wheelhouse uses `--no-index --no-deps` | PASS |
| Actor-admission binding is checked | Each prebuilt actor must bind exactly one local BUILD_ADMITTED receipt with the same immutable artifact digest | PASS |
| Portable launch binding exists | Launch packet binds task, actor, substrate digest, authority/tools, limits, logical credential refs, and output paths | PASS |
| Launch packet rejects venue coupling | GHA temp/workspace/run identifiers and Docker commands are prohibited | PASS |
| Task/tool/substrate drift fails closed | Fault tests mutate task digest, tool projection, substrate digest, and venue-specific output paths | PASS |
| Candidate environment can be minimized | Portable rehearsal uses `--candidate-env-mode minimal`; only explicit credential refs are passed when needed | PASS |
| File-backed secret contents stay out of evidence | Sentinel credential is consumed without appearing in receipt, diagnostics, stdout/stderr, or actor metadata | PASS |
| Each rep receives a fresh workspace | Repeated same-host reps cannot see stale task output; temp workspaces are removed | PASS |
| Candidate descendants are reaped | Candidate process groups are terminated after normal exit and timeout; tests cover both paths | PASS |
| Validator failure is not actor failure | Verifier exit outside 0/1 is `validator-error` and reduces to incomplete evidence | PASS |
| Duplicate receipt cannot strengthen evidence | Same run ID is counted once; divergent behavioral evidence for the same run ID fails closed | PASS |
| Deterministic portability semantics are explicit | Deterministic canary requires task/candidate/evidence/behavior equality except run/substrate/time | PASS |
| Stochastic crossover semantics are explicit | Real actor crossovers preserve outcome differences as evidence; tokens/rounds/tools/time are not equality gates | PASS |
| Procedure survives two execution shapes | Same deterministic canary passes natively on GHA and in a constrained local-shaped container | PASS |
| All three admitted harnesses hydrate daemonlessly | OpenWorker, Goose, and codex-exec fetch by immutable digest, hydrate/verify from OCI layout, and complete native/offline smoke | PASS |

## Findings discovered by the rehearsal

The hardening work found defects that would have been expensive and ambiguous on a
persistent sovereign worker:

1. A partial process-runner refactor introduced a syntax error and was caught by the
   contract/portability gates before merge.
2. Treating any IPv4/IPv6 socket syscall as network dependence produced a false
   positive when Python/OpenWorker created a loopback socket. The policy now rejects
   outbound IP connect/send operations while allowing local IPC/loopback setup.
3. Background candidate children inherited stdout/stderr pipes and could keep the
   parent-side capture open after the candidate process exited. Candidate output now
   uses regular temporary files and the entire candidate process group is reaped after
   both success and timeout.
4. OpenWorker's original offline install path attempted to re-resolve a direct
   dependency. Admission/qualification now installs the captured wheelhouse with
   `--no-index --no-deps`.

These are methodology results, not actor-performance results.

## Intentionally unproven until local/GARM exists

The following must remain UNKNOWN rather than being inferred from GHA:

- local kernel, cgroup, UID/GID, namespace, and service-manager behavior;
- persistent model-cache behavior and actual local model-storage paths;
- local DNS/proxy/firewall policy;
- GPU/NUMA/accelerator exposure and scheduling;
- actual GARM runner lifecycle, labels, registration, teardown, and reboot recovery;
- long-lived file-backed credential ownership/rotation on the real host;
- local OCI registry/cache availability and its authentication mechanism;
- local filesystem performance and mount semantics;
- exact local CPU/memory performance envelope.

The IaC substrate profile should record these only after discovery/observation.

## First sovereign execution sequence

When a real local/GARM substrate becomes available, do not create a new qualification
process. Use the already-rehearsed procedure:

1. discover the local substrate and emit an actor-neutral IaC substrate profile;
2. bind that exact profile/digest into a portable launch packet;
3. fetch an already-admitted harness artifact by immutable digest;
4. hydrate and verify it from local OCI/cache storage;
5. run the deterministic portability canary with the minimal candidate environment;
6. compare the canary with the GHA reference using deterministic comparison;
7. run one admitted OpenWorker + exact local Qwen actor canary;
8. compare GHA and local actor receipts using stochastic-structural comparison;
9. import the new exact Actor × Task × Substrate evidence into Agent Dispatch.

Only failures in the affected plane should block that lane. Do not re-run the broader
historical qualification matrix unless the local crossover exposes a reason to do so.
