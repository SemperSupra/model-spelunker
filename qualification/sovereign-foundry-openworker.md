# Rootless sovereign OpenWorker foundry — bounded producer v1

Authority: Model Spelunker #147. Implementation:
`qualification/sovereign_foundry_openworker.py`.

This is a **native Linux x86_64 Python/ABI realization** of pinned OpenWorker
`5bc10d928e0b64aae74313349a3b17bd19643ae2`. It is not a claim that a
local build outperforms the existing GHA artifact. The exact installed Python
interpreter ABI and dependency wheelhouse are part of the realized build receipt.
No model inference is performed during build, packaging, or admission.
The build and publication receipts bind the exact canonical SHA-256 digest of
`qualification/harness-realizations/openworker-linux-amd64-sovereign-python-abi-v1.json`.
This gives later configured-actor interviews a stable target-realization reference;
the actual ABI/toolchain and immutable OCI digest remain separate evidence.

## Execution boundaries

- Uses the existing TrueNAS ordinary user and user-local `uv`, `git`, `gh`.
- Clones only the pinned upstream source revision into disposable staging.
- Builds a dependency-closed wheelhouse using a disposable Python environment.
- Verifies offline import and CLI surface before publishing.
- Packages under `/artifact` in an OCI layout with existing
  `package_artifact_oci.py`; deterministic tar metadata, no Docker.
- Verifies local OCI hydration and each embedded payload hash.
- Separate explicit **publish** command: downloads pinned regctl to a 0700
  temporary directory, verifies its SHA-256, obtains TrueNAS `gh` token
  via a pipe directly into regctl, and copies the OCI layout to GHCR.
- Refuses to retarget an existing content-derived tag to a different digest.
- Resolves the exact immutable `@sha256` published reference; independently
  refetches, rehydrates and verifies embedded hashes; repeats offline
  import/CLI smoke and writes a BUILD_ADMITTED receipt.
- No daemon/socket, `sudo`, privileged group, global install, or persisted
  registry credentials. Registry authorization requires `write:packages`
  **only in the publish stage**. Never publish `gh auth token` output.

## TrueNAS kickoff (no Docker, no host administrator privileges)

Run from a normal TrueNAS shell, or through `ssh -t truenas`. The repository
is the source of truth; use a detached exact checkout to prevent TOCTOU drift.

```bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$HOME/.local/src" "$HOME/.local/share/model-spelunker-foundry"
cd "$HOME/.local/src"
if [ ! -d model-spelunker/.git ]; then
  gh repo clone SemperSupra/model-spelunker model-spelunker
fi
cd model-spelunker
git fetch --quiet origin main
sha="$(gh api repos/SemperSupra/model-spelunker/branches/main --jq .commit.sha)"
git checkout --detach "$sha"
test "$(git rev-parse HEAD)" = "$sha"

python3 -m qualification.sovereign_foundry_openworker observe
python3 -m qualification.sovereign_foundry_openworker plan

short="$(printf '%s' "$sha" | cut -c1-12)"
out="$HOME/.local/share/model-spelunker-foundry/openworker-$short"
python3 -m qualification.sovereign_foundry_openworker build --output "$out"
python3 -m qualification.sovereign_foundry_openworker verify --output "$out"
```

**Publishing is a separate, explicit authority crossing**. Only when ready:
```bash
# If needed, interactively grant the native TrueNAS GitHub session package WRITE.
gh auth refresh -h github.com -s write:packages

cd "$HOME/.local/src/model-spelunker"
short="$(git rev-parse --short=12 HEAD)"
python3 -m qualification.sovereign_foundry_openworker publish \
  --output "$HOME/.local/share/model-spelunker-foundry/openworker-$short"
```

The returned `artifact_ref` must use the immutable `@sha256:` form. Store
`payload/build-receipt.json`, `layout-receipt.json`, `admission.json`,
and `publication.json` as the DLE evidence set; the private raw executor log
is not a public artifact. Do not post machine paths, resource inventory or
credential/config files to a public repo or issue.

## Idempotence, failure attribution, and reversal

- `observe` and `plan` are read-only; never contact the model.
- `build` refuses to silently overwrite a different existing output.
  An exact previously built output is reverified and reported `ALREADY_BUILT`.
- Until build verification succeeds, work remains in a disposable sibling
  directory. On failure, that directory is deleted and the prior output
  is unchanged. On success, only OCI layout/payload/receipts remain; checkout,
  build virtual environment, and smoke environment are removed.
- `publish` requires local verification first. If the content-addressed tag
  already matches the expected digest, it skips the push and re-admits the
  remote artifact. Mismatched existing tag fails closed.
- Registry credentials and re-fetch cache are in temporary storage only.
- On TrueNAS or any hardened Linux substrate with a possible `noexec`
  system `/tmp`, the publisher places `regctl`, OCI re-hydration data, and the
  admission smoke virtual environment inside a **temporary user-owned
  executable directory alongside the already-verified artifact**. Ephemeral
  registry credentials remain separately under the system temporary directory
  (0700) to avoid accidental home-dataset snapshots. Both are removed even on
  failed publication. No mount-option changes or privilege escalation.
- If the repository main branch advances after a successful local build, the
  original verified output directory remains the authority for publication.
  Do not derive a **new** output name from the refreshed main SHA or rebuild
  merely because the producer code changed. Supply `--output` with the exact
  previously verified artifact path.
  If the push succeeds but admission fails, record `PUBLISH_UNVERIFIED`;
  do not call the artifact BUILD_ADMITTED or infer actor qualification.
- Reversal means deleting the user-owned local output path and, if authorized,
  the unused GHCR tag/package independently. No appliance system changes
  were made. Do not delete preexisting artifacts referenced by receipts.

## Red/blue experimental handoff

This first OpenWorker build isolates Python/ABI and dependency realization
rather than asserting a speed improvement. Once a sovereign artifact is
mechanically admitted, compare its task behavior with the historical GHA
OpenWorker artifact on the **same execution venue, installed model digest,
task, tool projection, inference endpoint, authority and verifier**. Record
both payload digests and actor realization profiles. Do not attribute timing
improvements to the build while the model or transport differs.

#139 actor interviews may proceed separately using existing admitted
artifacts; foundry publication is not their gate.
