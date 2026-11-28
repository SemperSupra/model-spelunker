# Native CPU build reuse R0

Authority: [#139 continuation claim](https://github.com/SemperSupra/model-spelunker/issues/139#issuecomment-7240693617), cell B; performance methodology [#316](https://github.com/SemperSupra/model-spelunker/issues/316).

This experiment tests whether one exact llama.cpp CPU build can be reused by
two fresh public Ubuntu 24.04 jobs. It addresses repeated build/setup work seen
in [#435](https://github.com/SemperSupra/model-spelunker/pull/435). It does not
rerun that model experiment or estimate causal savings by subtracting timings
from different historical hosts.

## Reuse existing mechanisms

The fixture imports the existing
`qualification.package_artifact_oci.build_layer` deterministic tar carrier;
it does not create or publish an OCI registry entry. GitHub's supported
[workflow artifact transfer](https://docs.github.com/en/actions/tutorials/store-and-share-data)
passes one immutable artifact ID from producer to consumers. Tar preserves
the native files' executable permissions inside the artifact transport.

Existing checkout and upload action SHAs are retained. No download action pin
existed in the repository at the starting base. Official
[download-artifact v8.0.0](https://github.com/actions/download-artifact/blob/70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3/action.yml)
is pinned to `70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3`; its digest mismatch
behavior is explicitly `error`. Content and manifest hashes are independently
checked again by the consumer.

## Fixed scope and qualification gates

One producer (25-minute cap) builds source
`a6ac41c757c066941766164439f6876f2deaab04` with the same five CMake settings as
#435: Release, `GGML_NATIVE=OFF`, tests off, examples off, server on, and build
parallelism two. Actual CMake cache, effective settings, compiler/linker/CMake
versions and executable hashes are retained. The toolchain is observed and
digest-bound for this build; it is not asserted reproducible across future
hosted-image updates.

The payload contains `llama-server`, every project-built `build/bin/*.so*`
name with symlinks safely dereferenced, and the upstream license. It does not
bundle glibc or the system loader. Their actual resolved file identities,
along with every other external dependency reached from all native payload
objects, form an exact same-substrate dependency contract.

Two separate fresh consumer jobs (8-minute cap each) must:

1. Download the exact producer artifact ID within the same workflow run.
2. Verify tar and manifest digests supplied as producer outputs, safely unpack
   only regular files/directories, and reject unexpected or missing members.
3. Match project source, upstream revision, build settings, run ID and attempt,
   Ubuntu release/architecture/libc and hosted-image identities.
4. Independently resolve every native object with `ldd`, require packaged
   project libraries, and match every external dependency's size/hash and the
   dependency graph. Missing or changed identities fail the gate and remain in
   logs/receipts.
5. Execute the actual binary's `--version` and `--help`, check its source
   revision and server CLI surface, and retain output digests/bytes and logs.
6. Reject nine actual-payload controls: different run/attempt replay, incorrect
   manifest anchor/substrate/upstream/flags, missing toolchain provenance,
   corrupt binary and missing project shared library. Some manifest mutants
   are self-rehashed to prove checks beyond hash agreement.

Each job also runs independent synthetic archive corruption, traversal, link,
duplicate-member, unexpected-file and permission tests. These are finite
boundary controls, not a universal artifact-security claim. The two consumers
independently apply the same verifier; human/source review remains separate
from producer self-report.

No weights are downloaded, no model inference is performed, and no endpoint,
service, registry, cache policy, scheduler, production configuration or physical
host is changed. Passing qualifies only native CLI/dependency reuse within the
observed Ubuntu substrate. It does not establish inference equivalence,
cross-platform portability, or local Metal/CUDA performance.

## Cost and evidence

Receipts preserve monotonic intervals and UTC clock origins for setup,
source fetch, configure, compile, packaging, producer CLI probes, artifact
upload/download intervals, verification, dynamic resolution, consumer probes
and negative controls. Download intervals include action startup and adjacent
step transition overhead. Runner provisioning, queue wait and final evidence
uploads are outside measured intervals. Per-job intervals are not concurrent
campaign makespan, and two CLI consumers are not two accepted agent tasks.

The payload artifact is retained for three days; compact producer/consumer
receipts, CMake cache, CLI output and build/dependency logs for fourteen days.
Provider completion alone is not acceptance: both consumer receipts and their
full provenance/fault-control gates must be independently reconciled.

```sh
python -m unittest discover -s qualification/serving_fanout_r0/native_build_reuse_r0 -p 'test_*.py' -v
```

The prospective workflow is `.github/workflows/native-build-reuse-r0.yml`.
There are exactly three standard public Linux jobs. No remote launch occurs
when running the local synthetic tests.
