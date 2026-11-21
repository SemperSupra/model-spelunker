# Qwen Code public disposable capsule — issue #220

This is a **public-safe build and qualification fixture** for the official [Qwen Code](https://github.com/QwenLM/qwen-code) Apache-2.0 **v0.28.3** standalone runtime. It contains no private repository source, addresses, credentials, workstation identities, model endpoint URLs, or private DLE text.

## What public GitHub Actions builds
The native Windows and Linux jobs download official release assets only from a versioned GitHub Release and verify their publisher-recorded SHA-256 digests, archive entry safety, exact native `qwen --version`, and source-neutral negative tests. Each job emits a portable ZIP kit with:
- `kit.json`: upstream release, platform, expected immutable archive digest, classification and *no production authority*.
- `upstream/qwen-code-{platform}.{zip|tar.gz}`: unchanged, SHA-verified upstream standalone release (includes its own Node runtime).
- `Observe-QwenHost.ps1`: read-only, redacted Windows PowerShell 5.1 hardware/Hyper-V/WSL/tool census (safe on control host).
- `Invoke-QwenCapsule.ps1`: Windows PowerShell 5.1 Observe, Plan, Apply, Verify, Rollback **inside the admitted guest only**.
- `compile-routes.mjs`: Node 22+ standard-library compiler for class-separated Qwen model role catalogs, with no embedded keys.
- `release-manifest.json` and this README, plus JSON evidence for the GitHub run.

Public runners are disposable, stateless build/test surfaces. Jobs use standard public hosted runners only, with no self-hosted runner labels, no API secrets, no host mounts, and no live sovereign endpoints. Assets uploaded through GitHub Actions are **not** signed by the owner and are temporary; production must additionally bind an approved source, artifact digest, workcell lease, and external admission verifier.

## Local use: only in the externally admitted disposable guest

No global Node/npm/Go/Python installation is needed for the Qwen standalone runtime. Running this installer on a persistent Windows development machine is **not** part of the accepted procedure. A trusted workcell controller first creates/attests an owned disposable guest (e.g., isolated CoW Hyper-V VM), stages the verified kit, and owns its lifecycle and teardown.

Within the guest:
1. `Observe` and `Plan` are read-only. Provide an **absolute** guest-local path to the checked-in release manifest and the unmodified pinned official ZIP.
2. The `Plan` JSON provides a deterministic `planSha256`. No staged files should exist yet.
3. The *external* workcell/Agent Dispatch admission controller authenticates the exact workset, VM generation, effect, plan digest, lease and authorized key. A writable JSON receipt or an approval hash from the model is **not sufficient**.
4. Only after the external controller has admitted the operation, use `Apply -Mode Production` with a separately pinned trusted admission verifier executable. Its signature and provenance belong to the private control plane, not public GHA. Use the exact plan SHA.
5. Run `Verify` and an independent model/tool-call/egress oracle. The guest-local payload PASS does not imply provider or MCP PASS.
6. On failure or completion, `Rollback` removes only the exact owned stage/active generation, then the existing host controller revokes credentials and destroys the owned VM/CoW disk. Verify no host taint independently.

**Do not enable the `SyntheticCI` mode on production hosts**. It merely allows native filesystem installation/rollback tests inside free disposable GitHub Actions runners and does not authenticate workcell admission. Shell environment variables are not attestation.

## Manual guest syntax (illustrative, never a host install)

```powershell
$script = '.\Invoke-QwenCapsule.ps1'
$manifest = '.\release-manifest.json'
$zip = '.\upstream\qwen-code-win-x64.zip'
$root = 'C:\QwenGuestTemp\capsule'
& $script -Phase Observe -ManifestPath $manifest -ArchivePath $zip -Root $root
& $script -Phase Plan -ManifestPath $manifest -ArchivePath $zip -Root $root
# The trusted controller must admit exact plan SHA and guest generation BEFORE Apply.
```

## Synthetics and qualification boundaries

The public runner is **not** a substitute for a native Hyper-V guest. It cannot validate host Hyper-V permissions, private network routes, resident services, rollback of non-GHA VMs, external authentication keys or the observed physical machine. No cloud-hosted runner should attempt to access an owner's home LAN or private repository. For live acceptance use the pre-existing private DLE and workcell authority, and keep those credentials and observations entirely off public GitHub.

No generic automatic `latest` downloads, `irm|iex`, registry writes, PATH changes, global installs, cloud model fallback, unsupported media processing, or self-authorized YOLO privilege are part of this kit.

## Classified model routing (guest only)

Use the standalone Node runtime inside the **admitted** disposable guest to compile a route manifest from current, operator-approved observed endpoints. Example public-safe fixture:

```powershell
# Within disposable guest; Node is packaged in the upstream standalone archive.
& '.\qwen-code\node\node.exe' .\compile-routes.mjs --manifest .\routes.public.example.json
```

The example points at `example.invalid`, so it cannot make a model call. Production routes, model IDs and secret values are supplied privately by the approved workcell controller. Output references only environment variable names (`envKey`), not credentials. Its `agents.modelGrades` can select models across providers, but classification and network permissions must be enforced *outside Qwen*. In particular, private and cloud roles do **not** share an execution context or prompt history; an Agent Dispatch workset can coordinate them while preserving data boundaries. The `privateNetworkAdmitted` input is merely configuration consistency; it cannot itself grant network access.

## B0 native control-surface preflight

`Observe-QwenHost.ps1` may be run from an existing trusted Windows console without elevation. It only reports sanitized counts/capabilities, never raw VM names, SSH credentials, addresses or host identifiers. A DENIED result for Get-VM/Get-VMSwitch is a management-admission blocker, **not** evidence that VMs/switches are absent. It performs no host or private endpoint writes.
