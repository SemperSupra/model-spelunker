#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Workcell,
    [Parameter(Mandatory = $true)][string]$TestProof,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory = $true)][string]$BillingEvidenceRef,
    [string]$LocalStorePath = (Join-Path $HOME '.local/credentials/gemini-api-key.clixml')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'GeminiReadiness.psm1') -Force
$modulePath = Join-Path $PSScriptRoot 'GeminiReadiness.psm1'
$proof = Get-Content -LiteralPath $TestProof -Raw | ConvertFrom-Json
if ($proof.failed -ne 0 -or $proof.passed -lt 20 -or
    $proof.module_sha256 -cne (Get-FileHash -LiteralPath $modulePath).Hash.ToLowerInvariant() -or
    $proof.entry_sha256 -cne (Get-FileHash -LiteralPath $PSCommandPath).Hash.ToLowerInvariant()) {
    throw 'HOLD: passing fake-test proof does not match these exact diagnostic sources.'
}
$expectedPrompt = 'Return exactly READY as a synthetic connectivity check without tools.'
$root = Get-Item -LiteralPath $Workcell -Force
if (-not $root.PSIsContainer -or ($root.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'HOLD: invalid public workcell.' }
$entries = @(Get-ChildItem -LiteralPath $root.FullName -Force)
if ($entries.Count -ne 2) { throw 'HOLD: unapproved workcell entries.' }
foreach ($item in $entries) {
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.Name -cnotin @('prompt.txt', '.public-ai-approval.json')) { throw 'HOLD: unapproved workcell item.' }
}
$manifest = Get-Content -LiteralPath (Join-Path $root.FullName '.public-ai-approval.json') -Raw | ConvertFrom-Json
$promptFile = Join-Path $root.FullName 'prompt.txt'
if ($manifest.classification -cne 'PUBLIC_RELEASE_APPROVED' -or $manifest.authority -cne 'SemperSupra/model-spelunker#199' -or
    $manifest.prompt_sha256 -cne (Get-FileHash -LiteralPath $promptFile).Hash.ToLowerInvariant() -or
    [IO.File]::ReadAllText($promptFile) -cne $expectedPrompt) { throw 'HOLD: synthetic data admission failed.' }
if ($BillingEvidenceRef -cne 'https://github.com/SemperSupra/agent-dispatch-private/issues/830#issuecomment-6956025254') { throw 'HOLD: unrecognized owner free-tier evidence.' }

$receipt = [ordered]@{
    schema_version = 1; kind = 'provider-readiness-diagnostic'; authority = 'SemperSupra/model-spelunker#199'
    run_id = ([datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-gemini-diag-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    source_commit = $SourceCommit; source_sha256 = @{ module = $proof.module_sha256; entry = $proof.entry_sha256 }
    substrate = @{ os = 'Windows'; powershell = $PSVersionTable.PSVersion.ToString(); tools = 'none' }
    admission = @{ classification = 'PUBLIC_RELEASE_APPROVED'; prompt_sha256 = $manifest.prompt_sha256; original_synthetic = $true }
    billing = @{ state = 'owner-verified-free-tier-billing-disabled'; evidence_ref = $BillingEvidenceRef; independently_reverified = $false; account_changes = $false }
    limits = @{ generation_attempts = 3; first_model_attempts = 2; alternate_attempts = 1; metadata_requests = 1; max_wait_seconds = 30; paid_fallback = $false }
    pricing_ref = 'https://aistudio.google.com/docs/pricing'; metadata = $null; attempts = @(); total_generation_attempts = 0
    result = 'HOLD'; agy = @{ state = 'NOT_EXECUTED'; reason = 'direct-success-required-then-independent-OS-isolation' }
}
$credential = $null; $key = $null; $pointer = [IntPtr]::Zero
try {
    $credential = Import-Clixml -LiteralPath $LocalStorePath
    if ($credential -isnot [Management.Automation.PSCredential] -or $credential.UserName -cne 'GEMINI_API_KEY') { throw 'HOLD: credential type/identifier mismatch.' }
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.Password)
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $metadata = Invoke-GeminiHttp -Uri 'https://generativelanguage.googleapis.com/v1beta/models' -Method GET -ApiKey $key
    $metadataObservation = ConvertTo-GeminiObservation $metadata 'metadata' $key
    $metadataObservation.operation = 'models.list'
    $metadataObservation.endpoint = 'https://generativelanguage.googleapis.com/v1beta/models'
    $metadataObservation.classification = $(if ($metadata.status -eq 200 -and -not $metadata.transport_error) { 'metadata-http-200' } else { $metadataObservation.classification })
    $receipt.metadata = $metadataObservation
    if ($metadata.status -ne 200 -or $metadata.transport_error -or $metadata.truncated) { $receipt.result = 'HOLD-metadata'; return }
    try { $catalog = $metadata.body | ConvertFrom-Json } catch { $receipt.result = 'HOLD-metadata-json'; return }
    $models = @('gemini-3.8-flash', 'gemini-3.6-flash')
    $selected = @()
    foreach ($model in $models) {
        $modelMatches = @($catalog.models | Where-Object { $_.name -ceq ('models/' + $model) -and $_.supportedGenerationMethods -contains 'generateContent' })
        if ($modelMatches.Count -ne 1) { $receipt.result = 'HOLD-model-not-confirmed'; return }
        $selected += @{ name = $modelMatches[0].name; supported_method = 'generateContent'; version = $modelMatches[0].version }
    }
    $receipt.metadata['selected_models'] = $selected
    $body = @{ contents = @(@{ role = 'user'; parts = @(@{ text = $expectedPrompt }) }); generationConfig = @{ maxOutputTokens = 256; temperature = 0 } } | ConvertTo-Json -Depth 8 -Compress
    $treatment = Invoke-GeminiTreatment -ApiKey $key -Body $body
    $receipt.attempts = $treatment.attempts
    $receipt.total_generation_attempts = $treatment.total_generation_attempts
    $receipt.result = $treatment.result
} catch {
    # No raw exception surface: it may contain key/path/transport details.
    $receipt.result = 'HOLD-local-procedure-UNKNOWN'
} finally {
    $key = $null; $credential = $null
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $receipt['completed_utc'] = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $receipt | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
}
