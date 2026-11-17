#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Protect-DiagnosticText {
    param([AllowNull()][object]$Text, [string]$Secret = '', [int]$Limit = 512)
    $value = [string]$Text
    if ($Secret) { $value = $value.Replace($Secret, '[REDACTED]') }
    $value = [regex]::Replace($value, '(?i)https?://[^\s"<>]+', '[REDACTED_URL]')
    $value = [regex]::Replace($value, '(?i)(?:authorization\s*[:=]\s*)?bearer\s+[^\s,;"<>]+', '[REDACTED_CREDENTIAL]')
    $value = [regex]::Replace($value, '(?i)(bearer\s+|(?:api[_-]?key|authorization|cookie|token|password)\s*[:=]\s*)[^\s,;"<>]+', '[REDACTED_CREDENTIAL]')
    $value = [regex]::Replace($value, '(?i)(?:[a-z]:\\|/Users/|/home/)[^\s"<>]+', '[REDACTED_PATH]')
    $value = [regex]::Replace($value, '[\x00-\x1f\x7f]', ' ')
    if ($value.Length -gt $Limit) { $value = $value.Substring(0, $Limit) + '[TRUNCATED]' }
    return $value
}

function Invoke-GeminiHttp {
    param([uri]$Uri, [string]$ApiKey, [ValidateSet('GET', 'POST')][string]$Method,
        [string]$Body = '', [int]$TimeoutMs = 15000, [switch]$AllowLoopbackForTest)
    $production = $Uri.Scheme -eq 'https' -and $Uri.Host -ceq 'generativelanguage.googleapis.com' -and $Uri.IsDefaultPort
    $test = $AllowLoopbackForTest -and $Uri.IsLoopback -and $Uri.Scheme -eq 'http' -and $ApiKey -ceq 'synthetic-test-key'
    if ((-not $production -and -not $test) -or $Uri.Query -or $Uri.UserInfo -or $Uri.Fragment) { throw 'Unapproved diagnostic route.' }
    if ($TimeoutMs -lt 50 -or $TimeoutMs -gt 30000) { throw 'Unapproved diagnostic timeout.' }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $response = $null
    $transport = $null
    try {
        $request = [Net.HttpWebRequest]::Create($Uri)
        $request.Method = $Method
        $request.AllowAutoRedirect = $false
        $request.Timeout = $TimeoutMs
        $request.ReadWriteTimeout = $TimeoutMs
        $request.Headers.Add('x-goog-api-key', $ApiKey)
        if ($Method -eq 'POST') {
            $request.ContentType = 'application/json'
            $bytes = [Text.Encoding]::UTF8.GetBytes($Body)
            $request.ContentLength = $bytes.Length
            $stream = $request.GetRequestStream()
            try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        }
        try { $response = $request.GetResponse() }
        catch [Net.WebException] {
            if ($null -ne $_.Exception.Response) { $response = $_.Exception.Response }
            else { $transport = [string]$_.Exception.Status }
        }
        if ($null -eq $response) {
            return @{ http_received = $false; transport_error = $transport; elapsed_ms = $timer.ElapsedMilliseconds; status = $null; headers = @{}; body = ''; truncated = $false }
        }
        $headers = @{}
        foreach ($name in @('Retry-After', 'x-request-id', 'x-goog-request-id', 'x-correlation-id', 'Date', 'Content-Type')) {
            if ($response.Headers[$name]) { $headers[$name.ToLowerInvariant()] = Protect-DiagnosticText $response.Headers[$name] $ApiKey 256 }
        }
        $reader = New-Object IO.StreamReader($response.GetResponseStream())
        try {
            $buffer = New-Object char[] 131073
            $count = 0
            while ($count -lt $buffer.Length) {
                $read = $reader.Read($buffer, $count, $buffer.Length - $count)
                if ($read -eq 0) { break }
                $count += $read
            }
            $raw = -join $buffer[0..([Math]::Max(0, $count - 1))]
            if ($count -eq 0) { $raw = '' }
        } finally { $reader.Dispose() }
        return @{ http_received = $true; transport_error = $null; elapsed_ms = $timer.ElapsedMilliseconds; status = [int]$response.StatusCode; headers = $headers; body = $raw; truncated = ($count -gt 131072) }
    } catch {
        # Exception objects/messages can contain secrets, routes or local paths.
        $exception = $_.Exception
        while ($exception.InnerException) { $exception = $exception.InnerException }
        $kind = 'UnknownTransportOrRunnerError'
        if ($exception -is [Net.WebException]) { $kind = [string]$exception.Status }
        return @{ http_received = ($null -ne $response); transport_error = $kind; elapsed_ms = $timer.ElapsedMilliseconds; status = $(if ($response) { [int]$response.StatusCode } else { $null }); headers = @{}; body = ''; truncated = $false }
    } finally {
        $timer.Stop()
        if ($response) { $response.Dispose() }
    }
}

function ConvertTo-GeminiObservation {
    param([hashtable]$Response, [string]$Model, [string]$Secret = '')
    $parsed = $null
    $jsonState = 'absent'
    if ($Response.body) {
        try { $parsed = $Response.body | ConvertFrom-Json; $jsonState = 'valid' }
        catch { $jsonState = 'malformed' }
    }
    $errorCode = $null; $errorStatus = $null; $errorMessage = $null; $retryInfo = $null
    $resolved = $null; $usage = @{}; $syntheticPass = $false; $finish = $null
    if ($null -ne $parsed -and $parsed.PSObject.Properties['error']) {
        $errorObject = $parsed.error
        foreach ($field in @('code', 'status', 'message')) {
            if ($errorObject -and $errorObject.PSObject.Properties[$field]) {
                $safe = Protect-DiagnosticText $errorObject.$field $Secret
                switch ($field) { 'code' { $errorCode = $safe } 'status' { $errorStatus = $safe } 'message' { $errorMessage = $safe } }
            }
        }
        if ($errorObject -and $errorObject.PSObject.Properties['details']) {
            foreach ($detail in @($errorObject.details)) {
                if ($detail.PSObject.Properties['@type'] -and $detail.'@type' -ceq 'type.googleapis.com/google.rpc.RetryInfo' -and
                    $detail.PSObject.Properties['retryDelay'] -and $detail.retryDelay -match '^([0-9]{1,6}(?:\.[0-9]{1,9})?)s$') {
                    $retryInfo = [double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture)
                }
            }
        }
    }
    if ($null -ne $parsed -and $parsed.PSObject.Properties['modelVersion']) { $resolved = Protect-DiagnosticText $parsed.modelVersion $Secret 128 }
    if ($null -ne $parsed -and $parsed.PSObject.Properties['usageMetadata']) {
        foreach ($field in @('promptTokenCount', 'candidatesTokenCount', 'totalTokenCount', 'thoughtsTokenCount')) {
            if ($parsed.usageMetadata.PSObject.Properties[$field] -and $parsed.usageMetadata.$field -is [ValueType]) { $usage[$field] = $parsed.usageMetadata.$field }
        }
    }
    if ($null -ne $parsed -and $parsed.PSObject.Properties['candidates'] -and @($parsed.candidates).Count -gt 0) {
        $candidate = $parsed.candidates[0]
        if ($candidate.PSObject.Properties['finishReason']) { $finish = Protect-DiagnosticText $candidate.finishReason $Secret 64 }
        if ($candidate.PSObject.Properties['content'] -and $candidate.content.PSObject.Properties['parts']) {
            $texts = @($candidate.content.parts | Where-Object { $_.PSObject.Properties['text'] -and (-not $_.PSObject.Properties['thought'] -or -not $_.thought) } | ForEach-Object { $_.text })
            $syntheticPass = (($texts -join '').Trim() -ceq 'READY')
        }
    }
    $classification = 'UNKNOWN'
    $hypothesis = 'UNKNOWN'
    if (-not $Response.http_received) {
        switch ($Response.transport_error) {
            'NameResolutionFailure' { $classification = 'transport-dns' }
            'ProxyNameResolutionFailure' { $classification = 'transport-proxy-dns' }
            'TrustFailure' { $classification = 'transport-tls' }
            'SecureChannelFailure' { $classification = 'transport-tls' }
            'Timeout' { $classification = 'transport-timeout' }
            'ConnectFailure' { $classification = 'transport-connect' }
            default { $classification = 'transport-or-runner-UNKNOWN' }
        }
    } elseif ($Response.transport_error) { $classification = 'http-response-read-failed' }
    else {
        switch ($Response.status) {
            200 { $classification = 'http-200-invalid-or-unexpected'; if ($syntheticPass -and -not $errorCode -and -not $errorStatus -and -not $errorMessage) { $classification = 'direct-synthetic-success' } }
            401 { $classification = 'http-authentication' }
            403 { $classification = 'http-permission-or-entitlement' }
            404 { $classification = 'http-model-or-route-not-found' }
            429 { $classification = 'http-quota-or-rate-limit' }
            503 { $classification = 'http-service-unavailable'; $hypothesis = 'provider-or-gateway-transient-possible-not-proven' }
            default { $classification = 'http-other' }
        }
    }
    $billingSignal = [bool]($errorMessage -match '(?i)billing|payment|paid tier|free tier.*(?:unavailable|not available|not supported)')
    return [ordered]@{
        utc = [datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
        requested_model = $Model; api_version = 'v1beta'; operation = 'generateContent'
        endpoint = ('https://generativelanguage.googleapis.com/v1beta/models/{0}:generateContent' -f $Model)
        http_received = [bool]$Response.http_received; http_status = $Response.status
        elapsed_ms = $Response.elapsed_ms; transport_error = $Response.transport_error
        response_headers = $Response.headers; response_json = $jsonState; response_truncated = $Response.truncated
        error = @{ code = $errorCode; status = $errorStatus; message = $errorMessage }
        retry_info_seconds = $retryInfo
        classification = $classification; hypothesis = $hypothesis; billing_signal = $billingSignal
        resolved_model = $resolved; finish_reason = $finish; usage = $usage
        synthetic_check_passed = $syntheticPass; tools = 'none'; agy_executed = $false
    }
}

function Get-GeminiNextStep {
    param([System.Collections.IDictionary]$Observation, [int]$Attempt, [datetime]$Now = [datetime]::UtcNow)
    $Now = $Now.ToUniversalTime()
    $plan = @{ action = 'stop'; wait_seconds = 0; reason = 'non-retryable-or-unclassified' }
    if ($Observation.classification -eq 'direct-synthetic-success') { $plan.reason = 'direct-success-AGY-separate'; return $plan }
    if ($Observation.billing_signal -or $Observation.http_status -in @(400, 401, 403)) { $plan.reason = 'auth-permission-billing-or-request-HOLD'; return $plan }
    if ($Attempt -ge 3) { $plan.reason = 'three-attempt-budget-exhausted'; return $plan }
    if ($Observation.http_status -notin @(429, 503, 404) -or $Observation.transport_error) { return $plan }
    if ($Observation.http_status -in @(429, 503)) {
        $wait = [Math]::Pow(2, $Attempt - 1)
        if ($null -ne $Observation.retry_info_seconds) { $wait = [Math]::Max($wait, [Math]::Ceiling($Observation.retry_info_seconds)) }
        if ($Observation.response_headers.ContainsKey('retry-after')) {
            $retry = $Observation.response_headers['retry-after']
            $seconds = 0.0; $date = [datetimeoffset]::MinValue
            if ([double]::TryParse($retry, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$seconds) -and $seconds -ge 0 -and -not [double]::IsInfinity($seconds) -and -not [double]::IsNaN($seconds)) { $wait = [Math]::Max($wait, [Math]::Ceiling($seconds)) }
            elseif ([datetimeoffset]::TryParse($retry, [ref]$date)) { $wait = [Math]::Max($wait, [Math]::Ceiling(($date.UtcDateTime - $Now).TotalSeconds)) }
        }
        if ($wait -gt 30) { $plan.reason = 'retry-after-exceeds-30s-bound-HOLD'; return $plan }
        $plan.wait_seconds = [int]$wait
    }
    $plan.action = $(if ($Attempt -eq 1 -and $Observation.http_status -ne 404) { 'retry-first' } else { 'probe-verified-alternate' })
    $plan.reason = 'explicit-bounded-diagnostic-treatment-not-fallback'
    return $plan
}

function Invoke-GeminiTreatment {
    param([string]$ApiKey, [string]$Body, [uri]$BaseUri = 'https://generativelanguage.googleapis.com', [switch]$AllowLoopbackForTest)
    $models = @('gemini-3.8-flash', 'gemini-3.6-flash')
    $model = $models[0]
    $attempts = @(); $result = 'HOLD'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $route = [uri]::new($BaseUri, ('/v1beta/models/{0}:generateContent' -f $model))
        $response = Invoke-GeminiHttp -Uri $route -Method POST -ApiKey $ApiKey -Body $Body -AllowLoopbackForTest:$AllowLoopbackForTest
        $observation = ConvertTo-GeminiObservation $response $model $ApiKey
        $observation['attempt'] = $attempt
        $plan = Get-GeminiNextStep $observation $attempt
        if ($model -eq $models[1] -and $plan.action -ne 'stop') { $plan = @{ action = 'stop'; wait_seconds = 0; reason = 'alternate-one-attempt-budget-exhausted' } }
        $observation['next_step'] = $plan
        $attempts += $observation
        if ($observation.classification -eq 'direct-synthetic-success') { $result = 'DIRECT_CONNECTIVITY_ONLY'; break }
        if ($plan.action -eq 'stop') { $result = 'HOLD-' + $plan.reason; break }
        if ($plan.wait_seconds -gt 0) { Start-Sleep -Seconds $plan.wait_seconds }
        if ($plan.action -eq 'probe-verified-alternate') { $model = $models[1] }
    }
    return @{ attempts = $attempts; result = $result; total_generation_attempts = $attempts.Count }
}

Export-ModuleMember -Function Protect-DiagnosticText, Invoke-GeminiHttp, ConvertTo-GeminiObservation, Get-GeminiNextStep, Invoke-GeminiTreatment
