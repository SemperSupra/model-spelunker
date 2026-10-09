# Substrate-targeted harness realizations

Authority: Model Spelunker #147 (build/foundry), #139 (actor × task experiments), and Agent Dispatch #104 (task-conditioned actor qualification).

## Purpose

Build the harness/framework realization that is appropriate for each supported execution target. Portable task contracts and evidence schemas remain common; *harness binaries and runtime configuration need not be identical*.

A realization profile is a **pre-build specification**, not proof of performance or admission. The immutable build receipt, OCI digest, and admission receipt bind what was actually produced. An actor candidate binds the exact realization profile `sha256` alongside its existing artifact/admission references.

Public profiles describe **target capability classes** (OS/ABI/ISA/permissions) rather than private hardware inventories, user names, hostnames, paths, or operational secrets.

## Identity and isolation

```text
harness source@revision
  + recipe/toolchain/features/flags
  + target OS/ABI/ISA/capability contract
        -> realized payload + build receipt
        -> immutable OCI digest + mechanical admission
        -> configured actor (realization profile digest + artifact ref)
        -> model + tools + runtime config + inference route + execution venue
        -> harness-neutral task + verifier + immutable receipt
```

Existing `qualification/actor-profile.schema.json` profiles remain valid without a realization binding. When present, the optional `harness.realization` object supplies:

```json
{
  "profile_ref": "qualification/harness-realizations/NAME.json",
  "profile_digest": "sha256:<canonical-json-sha256>"
}
```

The launch validator rejects profile drift, name mismatch, invalid paths, and missing referenced profiles. Existing candidate configuration hashing includes `harness`, so the realization binding changes actor identity without reinterpreting historical receipts. It is not permissible to replace only the digest while silently leaving an old artifact/admission ref: any claimed build treatment needs its own immutable artifact and admission evidence.

## Controlled comparisons

Run sparse task-conditioned crossovers rather than a full build × model × venue grid:

1. **Generic control**: admitted baseline build, fixed task/model/venue/tool authority.
2. **Build effect**: same task/model/venue/runtime/policy, compare a target-specific build that changed a declared material axis. Reject comparisons if capabilities disappeared unintentionally.
3. **Runtime effect**: same admitted build, model, task, venue and authority, change one runtime setting.
4. **Placement effect**: same build/model/task/authority, change execution venue when the build is compatible. Distinguish harness placement from inference placement.
5. **Combined actor**: after isolated improvements, assess the selected full actor binding. Record interactions and retest; gains do not automatically compose.

Each optimization proposal needs a falsifiable hypothesis, a primary response, and stop rule. Prioritize verifier success, correct tool/approval behavior, reproducibility and safety. Then compare latency, time to first useful event, resource use, startup size, cost and endurance where measured. An optimized build cannot inherit PASS from the generic baseline.

Material dimensions may include feature/dependency closure, compiler/link profile, ABI/ISA target, memory allocator, sandbox/syscall needs, plugin/tool-protocol projection, and permitted execution mode. Avoid speculative `-march=native` binaries as universal artifacts: they narrow ISA compatibility and may not improve model-bound wall time.

## Build/admission and disclosure boundaries

- No Docker socket, privileged host group, sudo, or global installs for routine rootless builds.
- Prefer minimal native payloads, user-local pinned toolchains, and daemonless OCI packaging (PR #148).
- Private substrate observations stay private; public artifact metadata contains only generic platform requirements and toolchain identities.
- Never publish credentials, network addresses, internal paths, machine serials, or user/organization-internal estate details.
- Fail closed when target ISA/ABI/kernel/permission prerequisites are not verified at execution placement.
- Build success and mechanical admission do **not** qualify an actor against any task.
- Keep the #139 interviews progressing independently; producer tuning is an opportunistic source of new candidates, not a blocking preflight.

## Initial control

`goose-linux-amd64-gnu-control.json` preserves a generic pinned Linux/x64 Goose recipe as the control realization. It does **not** claim that this is optimal. A target-specific challenger should be introduced only once a concrete bottleneck/capability hypothesis is backed by a bounded experiment; the build then earns a new exact artifact and actor receipt.
