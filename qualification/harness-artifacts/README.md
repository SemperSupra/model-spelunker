# Harness artifact admission

Harness build/admission is intentionally separate from Actor × Task qualification.

A harness artifact may be **BUILD_ADMITTED** when its immutable payload can be traced to a pinned source revision and mechanically satisfies the minimum runtime/interface checks needed by the qualification runner. Admission does not imply that any configured actor using the artifact is qualified for any task.

## Invariants

- Build once; qualification consumes an immutable artifact reference.
- Source revision, build recipe/toolchain, target, payload hashes, and immutable OCI digest are preserved.
- Mutable tags are convenience pointers only; qualification binds the immutable digest.
- Secrets are never included in build payloads.
- Behaviorally material runtime configuration, tool projection, model route, and authority remain part of configured-actor identity.
- Historical source-built actor evidence remains historical evidence. A prebuilt artifact mints a distinct configured actor realization and earns bridge evidence.
- Source-building inside an Actor × Task job is reserved for explicit build-characterization experiments.

## Packaging

The initial carrier is an OCI image used as a content-addressed distribution envelope. Qualification may extract and execute native contents; OCI packaging does not require containerized actor execution.

Initial payloads:

- OpenWorker: offline Python wheelhouse plus build receipt.
- Goose: projected native Linux x64 binary plus build receipt.
- codex-exec: admitted only after the current build seam is repaired.

## Admission checks

Admission stays mechanical:

1. immutable payload digest is known;
2. embedded build receipt validates;
3. payload hashes match the build receipt;
4. expected executable/package identity can be loaded or started;
5. the minimum qualification-facing CLI/import surface exists.

No model inference, task score, routing decision, ranking, or Agent Dispatch qualification state is produced here.
