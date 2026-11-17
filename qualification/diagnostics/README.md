# Gemini readiness diagnosis (#199)

This is a bounded operator diagnostic, not a task benchmark, agent adapter,
model ranking, or accepted configured-actor receipt. It follows the existing
diagnostic/evidence pattern alongside `diagnose_openworker_boundary.py` and
`probe_openrouter_admission.py`; it does not change `run_task.py`, v2 receipts,
or the reducer. Authority: Model Spelunker #199; parent #198; data boundary:
Agent Dispatch Private #830. Canonical WoW v0.0.4, GOV-AGENT-001 and
GOV-EXEC-001 apply. No governance proposal is activated here.

## Live-first operating method

Owner correction in #199 and IaC #426 is authoritative: observe real authorized
systems, plan from evidence, apply within authority, then verify. Safe live
discovery and bounded approved synthetic inference do not require a mock suite.
R4 means reproducible procedure, repeatable observation, reversible local
tooling and idempotent intended state; stochastic model output need not be
byte-identical. Use these focused fault tests only for hazardous or unavailable
conditions and protocol regressions.

## Focused offline fault tests

From the repository root on Windows with Python 3.12 and native PS5.1:

```powershell
$env:GEMINI_DIAG_TEST_PROOF = Join-Path $env:TEMP 'gemini-fake-tests.json'
python qualification/diagnostics/test_gemini_readiness.py
```

The Python stdlib fake HTTP server binds only loopback and logs no request
content. Child PowerShell processes use `-NoProfile`, a disposable user home
and allowlisted environment. They never load the operator credential. Tests
cover actual HTTP 200/401/403/404/429/503, missing/malformed/misleading JSON,
Retry-After seconds/date/invalid/over-bound values, structured RetryInfo,
redaction, timeouts, no redirect/key-query routes, admission failure, stale
proof and the exact three-call/no-auth-fallback treatment. DNS, TLS and proxy
failure classifications use fabricated typed transport observations; they
are not live network fault injection.

The live entry always records both exact PowerShell source hashes. A fake-test
proof is optional supporting evidence; when supplied it must match the source.
Neither a fake pass nor its absence determines live authorization/readiness.

## Approved live invocation

Only the user-authorized #199 activation may make the bounded live requests.
Do not repeatedly rerun this command to reset its per-invocation budget.
The issue records consumption across activations. No automatic retry in an
SDK, scheduler or caller is permitted.

Create a disposable directory outside repositories with exactly two regular
files. `prompt.txt` must contain exactly these UTF-8 bytes, without a newline:

```text
Return exactly READY as a synthetic connectivity check without tools.
```

`.public-ai-approval.json` contains:

```json
{
  "classification": "PUBLIC_RELEASE_APPROVED",
  "authority": "SemperSupra/model-spelunker#199",
  "prompt_sha256": "<SHA-256 of prompt.txt>"
}
```

Run native `powershell.exe -NoProfile -NonInteractive -File` with:

```text
qualification/diagnostics/Invoke-GeminiReadiness.ps1
  -Workcell <approved disposable workcell>
  [-TestProof <optional matching fault-test evidence>]
  -OutputPath <new diagnostic receipt outside the workcell>
  -SourceCommit <exact committed source SHA>
  -BillingEvidenceRef <current authorized owner evidence reference>
  -LocalStorePath <existing Windows-user DPAPI credential file>
```

The existing #830 owner verification of Free tier/billing disabled is the
admitted account evidence, not a programmatic account inspection. The current
activation must reconcile it; never claim model listing independently proves
billing. The optional credential path lets the deterministic client run with
an empty USERPROFILE and no ambient OAuth/environment credentials. DPAPI still
uses the same Windows account token. Never pass a key value as an argument,
copy an OAuth session, persist plaintext environment credentials, or change
an account. Only this known script reads/decrypts the credential in memory.

The fixed official route is HTTPS `generativelanguage.googleapis.com`, API
version `v1beta`. TLS verification and system proxy behavior are retained;
redirects are refused. One metadata request must confirm `generateContent`
for both pinned identifiers `gemini-3.8-flash` and `gemini-3.6-flash`; no
`latest` router or speculative model is tried. Current official pricing must
independently confirm their standard free-tier input/output before activation:
<https://aistudio.google.com/docs/pricing>.

The treatment allows at most two calls to the first model and one to the
verified alternate, never more than three total. Success stops immediately.
401/403, request/billing ambiguity and transport errors stop. Only 429/503
get backoff (1s, then 2s minimum); valid Retry-After or structured RetryInfo
is honored. Guidance exceeding 30s stops rather than retrying too early.
A 404 may move directly to the independently verified alternate, once.
The alternate is an explicit diagnostic treatment, never a paid fallback.

## Evidence and limits

Receipts contain source/fixture hashes, runtime, UTC, exact requested and
exposed resolved model, observed HTTP vs typed transport failure, elapsed
time, bounded redacted `error.code/status/message`, JSON state, only
Retry-After/request-ID/date/content-type headers, structured retry guidance,
and numeric token usage only if returned. Raw headers/body, response text,
exception objects, key fingerprints, paths, environment and credentials are
not emitted. Scrubbing occurs before truncation. Unknown causes remain
UNKNOWN: HTTP 503 proves service unavailability along the route, not its
origin or provider capacity. Provider status is corroboration only.

The direct client has no model tools and sends only the fixed synthetic
sentence. An empty home/environment is not an OS sandbox. **AGY is separate**:
after direct success, independently qualify real filesystem/process/network
containment before one API invocation. Never treat `--sandbox` help text,
YOLO admission, a Job Object or changed USERPROFILE as proof that private
user-readable files are inaccessible. If no verified isolation exists,
record AGY HOLD without running it. Direct success does not release W1+.

Rollback is removal/revert of these diagnostic files through normal review.
No service, credential, account or GitHub environment is modified. Preserve
only reviewed redacted receipts in owning DLEs; temporary fake workcells can
be discarded. Never promote a connectivity result to a model-quality score
or public Foundry artifact.
