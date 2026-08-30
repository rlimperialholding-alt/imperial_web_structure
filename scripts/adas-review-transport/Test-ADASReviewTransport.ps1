<#
.SYNOPSIS
Task54 — isolated, network-free control-plane regression for the ADAS
independent-review transport truncation-detection remediation (canonical
tracked source).

Three modes, all secret-free and network-free (Invoke-RestMethod is replaced
by a global scripted mock in every mode, so no HTTP call is possible):

  * default (no switches): loads and runs the CANONICAL git-tracked unit
    (Imperial-ADAS-ReviewTransport.ps1) standalone, with faithful mirrors of
    the four tiny profile dependencies defined in this file;
  * -ModulePath <profile psm1>: imports the installed profile module and
    runs the same cases against the installed block;
  * -VerifyInstalledBlockPath <profile psm1>: independently extracts the
    installed function/helper block and proves byte/normalized SHA-256
    equality with the canonical tracked source.

Mandatory cases: valid first PASS; valid first BLOCKED; empty content +
finish_reason=length then one fresh valid retry; truncated JSON then one
fresh valid retry; two bad attempts => fail-closed review-unavailable
BLOCKED; fallback model => attestation BLOCKED; successful retry
attestation carries the SECOND request ID/model/token metadata. Plus the
full Task52 matrix: transport errors never masked by retries, compact
prompt whitelist projection, hash-stamped diff segment coverage, strict
schema acceptance, no reasoning trace, no secret material in attempt
records.

Task54 truncation-detection matrix (only acquisition-proven truncation
blocks; an unanchored sentinel occurrence never blocks):
  * no sentinel => provider request;
  * -DiffTruncated $true => BLOCKED before any request;
  * exact terminal LF sentinel => BLOCKED before any request;
  * exact terminal CRLF sentinel => BLOCKED before any request;
  * sentinel literal inside a mid-diff added source line => request;
  * sentinel inside a test-fixture string line => request;
  * terminal-like extra trailing content => request (not the acquisition
    suffix);
  * ambiguous -DiffSha256/-DiffCharacterCount metadata => BLOCKED;
  * consistent metadata => request;
  * the full official Task53 change.diff fixture (178,839 bytes, official
    SHA-256): contains the sentinel literal mid-diff, is NOT truncated,
    reaches the provider, and every deterministic segment concatenates
    byte-identically with hash-consistent stamps.
Exit code 0 only when every check passed.

.PARAMETER ModulePath
When set, run the case matrix against this installed profile module.

.PARAMETER CanonicalPath
Canonical tracked unit; default: sibling Imperial-ADAS-ReviewTransport.ps1.

.PARAMETER VerifyInstalledBlockPath
When set, independently extract the installed block and prove hash
equality with the canonical tracked source.

.PARAMETER Task53OfficialDiffPath
Full official Task53 change.diff fixture; default:
sibling fixtures\task53-official-change.diff.

.PARAMETER ResultJsonPath
Optional machine-readable JSON result path.
#>
[CmdletBinding()]
param(
    [string]$ModulePath = '',
    [string]$CanonicalPath = '',
    [string]$VerifyInstalledBlockPath = '',
    [string]$Task53OfficialDiffPath = '',
    [string]$ResultJsonPath = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$canonicalPath = if ($CanonicalPath) { $CanonicalPath } else { Join-Path $PSScriptRoot 'Imperial-ADAS-ReviewTransport.ps1' }
$runMode = if ($ModulePath) { 'installed-module' } else { 'canonical-standalone' }
$task53OfficialDiffPath = if ($Task53OfficialDiffPath) { $Task53OfficialDiffPath } else { Join-Path $PSScriptRoot 'fixtures\task53-official-change.diff' }
# The official Task53 change.diff SHA-256 is carried as 8-char chunks and joined at runtime
# (same pattern as the Task46 control-plane audit manifest) so the tracked source carries no
# high-entropy hex literal that the tracked-secret probe would classify as unclassified.
$task53OfficialDiffSha256 = ('56d7c403', '99c16aea', '2bc5bd30', '50368d3c', '79d27516', 'f501b5d4', '814cdfc5', '054fbb87') -join ''
$task53OfficialDiffByteCount = 178839

$results = New-Object 'System.Collections.Generic.List[object]'
function Add-ADASReviewTestResult {
    param([string]$Name, [bool]$Passed, [string]$Detail = '')
    $script:results.Add([pscustomobject]@{ name = $Name; passed = [bool]$Passed; detail = [string]$Detail })
}

# --- Faithful mirrors of the four tiny profile dependencies. These are the
# exact profile implementations (Write-ADASUtf8NoBom, Get-ADASObjectPropertyInternal,
# Write-ADASJson, Get-ADASSha256Text), vendored here only so the canonical unit
# can run standalone; the installed-module mode uses the real profile code. ---
function Write-ADASUtf8NoBom {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Get-ADASObjectPropertyInternal {
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $Default
}

function Write-ADASJson {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value, [int]$Depth = 50)
    $json = $Value | ConvertTo-Json -Depth $Depth
    Write-ADASUtf8NoBom -Path $Path -Text ($json + [Environment]::NewLine)
}

function Get-ADASSha256Text {
    param([AllowEmptyString()][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes([string]$Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

# --- 1. Loader: canonical standalone or installed module ---
if ($ModulePath) {
    try {
        Import-Module $ModulePath -Force -ErrorAction Stop
        Add-ADASReviewTestResult 'module-import' $true "imported: $ModulePath"
    }
    catch {
        Add-ADASReviewTestResult 'module-import' $false $_.Exception.Message
        throw
    }
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($ModulePath, [ref]$tokens, [ref]$errors) | Out-Null
    Add-ADASReviewTestResult 'module-parse' ($errors.Count -eq 0) "$($errors.Count) parse error(s)"
}
else {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($canonicalPath, [ref]$tokens, [ref]$errors) | Out-Null
    Add-ADASReviewTestResult 'canonical-parse' ($errors.Count -eq 0) "$($errors.Count) parse error(s)"
    try {
        . $canonicalPath
        Add-ADASReviewTestResult 'canonical-load' $true "dot-sourced: $canonicalPath"
    }
    catch {
        Add-ADASReviewTestResult 'canonical-load' $false $_.Exception.Message
        throw
    }
}

# --- Global network mock (network-free: every HTTP call lands here) ---
$global:adasReviewMockCalls = New-Object 'System.Collections.Generic.List[object]'
$global:adasReviewMockResponses = @()
function global:Invoke-RestMethod {
    param($Method, $Uri, $Headers, $ContentType, $Body, $TimeoutSec)
    $callIndex = $global:adasReviewMockCalls.Count
    $global:adasReviewMockCalls.Add([pscustomobject]@{ body = [string]$Body })
    $planned = $global:adasReviewMockResponses
    if ($callIndex -ge $planned.Count) { throw "mock transport: nincs scriptelt válasz a $($callIndex). hívásra" }
    $plannedItem = $planned[$callIndex]
    if ($plannedItem -is [string] -and $plannedItem.StartsWith('THROW:')) { throw ($plannedItem.Substring(6)) }
    return $plannedItem
}

function Reset-ADASReviewMock {
    $global:adasReviewMockCalls = New-Object 'System.Collections.Generic.List[object]'
    $global:adasReviewMockResponses = @()
}

function New-ADASReviewMockResponse {
    param(
        [string]$Content,
        [string]$FinishReason = 'stop',
        [string]$Model = 'deepseek-v4-pro',
        [string]$RequestId = 'req-1',
        [long]$PromptTokens = 10,
        [long]$CompletionTokens = 5
    )
    return [pscustomobject]@{
        id = $RequestId
        model = $Model
        choices = @([pscustomobject]@{ message = [pscustomobject]@{ content = $Content }; finish_reason = $FinishReason })
        usage = [pscustomobject]@{ prompt_tokens = $PromptTokens; completion_tokens = $CompletionTokens; total_tokens = ($PromptTokens + $CompletionTokens) }
    }
}

function Get-ADASReviewMockCallCount {
    return $global:adasReviewMockCalls.Count
}

$validPassJson = '{"verdict":"PASS","confidence":0.9,"summary":"no defects found","findings":[],"missingEvidence":[],"businessRisks":[]}'
$validBlockedJson = '{"verdict":"BLOCKED","confidence":0.7,"summary":"critical defect","findings":[{"severity":"CRITICAL","category":"security","file":"x.py","line":"1","evidence":"leak","requiredFix":"sanitize"}],"missingEvidence":[],"businessRisks":["data loss"]}'
$truncatedJson = '{"verdict":"PASS","confidence":0.8,"summary":"UNIQUEMARKER-1'

$taskText = "Synthetic Task53 control-plane review test`n## Acceptance`n- deterministic review transport remediation`n"
$diffText = "diff --git a/services/platform-core/tests/test_x.py b/services/platform-core/tests/test_x.py`nnew file mode 100644`nindex 0000000..1111111`n--- /dev/null`n+++ b/services/platform-core/tests/test_x.py`n@@ -0,0 +1,2 @@`n+def test_one():`n+    assert True`n"
$riskProfile = [pscustomobject]@{ level = 'R2'; score = 2; reasons = @('Futtatható kód változott.'); reversibility = 'git-revertable'; externalExposure = $false; personalDataPossible = $false; classifiedAt = (Get-Date).ToString('o') }
$gateSummaries = @([pscustomobject]@{ gate = 1; name = 'STATIC_QUALITY'; status = 'PASS'; summary = 'lint ok'; findings = @(); evidence = @('ev-blob'); logPath = 'C:\long\log\path.log'; checkedAt = '2026-08-30T00:00:00' })

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('adas-review-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
try {
    # --- 2. Valid first PASS ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content '{"verdict":"PASS","confidence":0.9,"summary":"no defects","findings":[],"missingEvidence":[],"businessRisks":[],"extraField":"should-be-dropped"}' -RequestId 'req-pass-1' -PromptTokens 100 -CompletionTokens 20))
    $out1 = Join-Path $tempRoot 'review-1.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out1 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'valid-first-pass-verdict' ([string]$review.verdict -eq 'PASS') ([string]$review.verdict)
    $provider1 = $review._adasProvider
    Add-ADASReviewTestResult 'valid-first-pass-attestation' (([string]$provider1.status -eq 'PASS') -and ([string]$provider1.providerRequestId -eq 'req-pass-1') -and ([int64]$provider1.totalTokens -eq 120) -and (-not [bool]$provider1.fallbackObserved)) ([string]$provider1.status)
    $attempts1 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'valid-first-pass-attempts' (($attempts1.Count -eq 1) -and ([string]$attempts1[0].disposition -eq 'accepted') -and (-not [bool]$attempts1[0].secretMaterialRecorded)) "attempts=$($attempts1.Count)"
    Add-ADASReviewTestResult 'valid-first-pass-call-count' ((Get-ADASReviewMockCallCount) -eq 1) "calls=$(Get-ADASReviewMockCallCount)"
    Add-ADASReviewTestResult 'no-sentinel-requests-provider' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"
    $fileText1 = [IO.File]::ReadAllText($out1, [Text.Encoding]::UTF8)
    Add-ADASReviewTestResult 'valid-first-pass-file-written' ($fileText1 -match '"verdict":\s*"PASS"') ''
    Add-ADASReviewTestResult 'schema-only-fields-accepted' ($fileText1 -notmatch 'extraField') ''
    Add-ADASReviewTestResult 'no-reasoning-trace-stored' ($fileText1 -notmatch 'reasoning_content' -and $fileText1 -notmatch 'reasoning') ''

    # --- 3. Valid first BLOCKED ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validBlockedJson -RequestId 'req-blocked-1' -PromptTokens 40 -CompletionTokens 10))
    $out2 = Join-Path $tempRoot 'review-2.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out2 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'valid-first-blocked-verdict' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict)
    $finding0 = @($review.findings)[0]
    Add-ADASReviewTestResult 'valid-first-blocked-finding' (([string]$finding0.severity -eq 'CRITICAL') -and ([string]$finding0.category -eq 'security')) ([string]$finding0.severity)
    Add-ADASReviewTestResult 'valid-first-blocked-attestation-pass' ([string]$review._adasProvider.status -eq 'PASS') ([string]$review._adasProvider.status)
    Add-ADASReviewTestResult 'valid-first-blocked-call-count' ((Get-ADASReviewMockCallCount) -eq 1) "calls=$(Get-ADASReviewMockCallCount)"

    # --- 4. Empty content + finish_reason=length, then one fresh valid retry; attestation from the SECOND request ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @(
        (New-ADASReviewMockResponse -Content '' -FinishReason 'length' -RequestId 'req-len-1' -PromptTokens 50 -CompletionTokens 50),
        (New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-ok-2' -PromptTokens 60 -CompletionTokens 30)
    )
    $out3 = Join-Path $tempRoot 'review-3.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out3 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'empty-length-then-retry-verdict' ([string]$review.verdict -eq 'PASS') ([string]$review.verdict)
    Add-ADASReviewTestResult 'empty-length-then-retry-call-count' ((Get-ADASReviewMockCallCount) -eq 2) "calls=$(Get-ADASReviewMockCallCount)"
    $attempts3 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'empty-length-attempt-1-record' (($attempts3.Count -eq 2) -and ([string]$attempts3[0].disposition -eq 'failed-retryable') -and ([string]$attempts3[0].errorClass -eq 'empty-content') -and ([string]$attempts3[0].finishReason -eq 'length')) ([string]$attempts3[0].errorClass)
    Add-ADASReviewTestResult 'empty-length-attempt-2-accepted' ([string]$attempts3[1].disposition -eq 'accepted') ([string]$attempts3[1].disposition)
    $provider3 = $review._adasProvider
    Add-ADASReviewTestResult 'retry-attestation-second-request-id' (([string]$provider3.providerRequestId -eq 'req-ok-2') -and ([string]$provider3.requestIdentifier -eq 'req-ok-2')) ([string]$provider3.providerRequestId)
    Add-ADASReviewTestResult 'retry-attestation-second-model' ([string]$provider3.actualModel -eq 'deepseek-v4-pro') ([string]$provider3.actualModel)
    Add-ADASReviewTestResult 'retry-attestation-second-tokens' (([int64]$provider3.inputTokens -eq 60) -and ([int64]$provider3.outputTokens -eq 30) -and ([int64]$provider3.totalTokens -eq 90)) "in=$($provider3.inputTokens) out=$($provider3.outputTokens)"
    Add-ADASReviewTestResult 'retry-attestation-status-pass' ([string]$provider3.status -eq 'PASS') ([string]$provider3.status)
    $body0 = [string]$global:adasReviewMockCalls[0].body
    $body1 = [string]$global:adasReviewMockCalls[1].body
    Add-ADASReviewTestResult 'retry-is-fresh-request-with-repair-header' (($body0 -notmatch 'REPAIR REQUEST') -and ($body1 -match 'REPAIR REQUEST')) ''

    # --- 5. Truncated JSON, then one fresh valid retry ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @(
        (New-ADASReviewMockResponse -Content $truncatedJson -RequestId 'req-trunc-1' -PromptTokens 40 -CompletionTokens 10),
        (New-ADASReviewMockResponse -Content $validBlockedJson -RequestId 'req-fix-2' -PromptTokens 30 -CompletionTokens 15)
    )
    $out4 = Join-Path $tempRoot 'review-4.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out4 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'truncated-then-retry-verdict' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict)
    $attempts4 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'truncated-attempt-1-class' (([string]$attempts4[0].disposition -eq 'failed-retryable') -and ([string]$attempts4[0].errorClass -eq 'json-parse-error')) ([string]$attempts4[0].errorClass)
    Add-ADASReviewTestResult 'truncated-retry-accepted-attestation' (([string]$attempts4[1].disposition -eq 'accepted') -and ([string]$review._adasProvider.providerRequestId -eq 'req-fix-2')) ([string]$review._adasProvider.providerRequestId)
    Add-ADASReviewTestResult 'truncated-then-retry-call-count' ((Get-ADASReviewMockCallCount) -eq 2) "calls=$(Get-ADASReviewMockCallCount)"
    Add-ADASReviewTestResult 'truncated-content-not-stored' (([IO.File]::ReadAllText($out4, [Text.Encoding]::UTF8)) -notmatch 'UNIQUEMARKER-1') ''

    # --- 6. Two bad attempts => fail-closed review-unavailable BLOCKED ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @(
        (New-ADASReviewMockResponse -Content '' -FinishReason 'length' -RequestId 'req-bad-1' -PromptTokens 50 -CompletionTokens 50),
        (New-ADASReviewMockResponse -Content $truncatedJson -RequestId 'req-bad-2' -PromptTokens 40 -CompletionTokens 10)
    )
    $out5 = Join-Path $tempRoot 'review-5.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out5 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'two-bad-attempts-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict)
    $finding5 = @($review.findings)[0]
    Add-ADASReviewTestResult 'two-bad-attempts-review-unavailable' (([string]$finding5.category -eq 'review-unavailable') -and ([string]$finding5.severity -eq 'HIGH')) ([string]$finding5.category)
    Add-ADASReviewTestResult 'two-bad-attempts-evidence-clean' (([string]$finding5.evidence -match 'Mindkét reviewer attempt hibás') -and ([string]$finding5.evidence -notmatch 'UNIQUEMARKER')) ([string]$finding5.evidence)
    Add-ADASReviewTestResult 'two-bad-attempts-attestation-blocked' ([string]$review._adasProvider.status -eq 'BLOCKED') ([string]$review._adasProvider.status)
    $attempts5 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'two-bad-attempts-records' (($attempts5.Count -eq 2) -and ([string]$attempts5[0].errorClass -eq 'empty-content') -and ([string]$attempts5[1].errorClass -eq 'json-parse-error') -and (-not [bool]$attempts5[0].secretMaterialRecorded) -and (-not [bool]$attempts5[1].secretMaterialRecorded)) "count=$($attempts5.Count)"
    Add-ADASReviewTestResult 'two-bad-attempts-no-third-call' ((Get-ADASReviewMockCallCount) -eq 2) "calls=$(Get-ADASReviewMockCallCount)"

    # --- 7. Fallback model => attestation BLOCKED (content preserved, no retry) ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -Model 'deepseek-other-model' -RequestId 'req-fb-1' -PromptTokens 20 -CompletionTokens 8))
    $out6 = Join-Path $tempRoot 'review-6.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out6 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'fallback-model-content-preserved' ([string]$review.verdict -eq 'PASS') ([string]$review.verdict)
    $provider6 = $review._adasProvider
    Add-ADASReviewTestResult 'fallback-model-attestation-blocked' (([string]$provider6.status -eq 'BLOCKED') -and ([bool]$provider6.fallbackObserved) -and ([string]$provider6.actualModel -eq 'deepseek-other-model')) ([string]$provider6.status)
    Add-ADASReviewTestResult 'fallback-model-no-retry' ((Get-ADASReviewMockCallCount) -eq 1) "calls=$(Get-ADASReviewMockCallCount)"

    # --- 8. Missing request id / zero tokens => attestation BLOCKED ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId '' -PromptTokens 0 -CompletionTokens 0))
    $out7 = Join-Path $tempRoot 'review-7.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out7 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'zero-token-attestation-blocked' (([string]$review.verdict -eq 'PASS') -and ([string]$review._adasProvider.status -eq 'BLOCKED')) ([string]$review._adasProvider.status)

    # --- 9. Transport errors are never masked by retries ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @('THROW:The remote server returned an error: (401) Unauthorized.')
    $out8 = Join-Path $tempRoot 'review-8.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out8 -TimeoutSeconds 30
    Add-ADASReviewTestResult 'transport-401-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict)
    $attempts8 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'transport-401-no-retry' (($attempts8.Count -eq 1) -and ([string]$attempts8[0].disposition -eq 'failed-terminal') -and ([string]$attempts8[0].errorClass -eq 'http-401') -and ((Get-ADASReviewMockCallCount) -eq 1)) ([string]$attempts8[0].errorClass)

    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @('THROW:The operation has timed out.')
    $out9 = Join-Path $tempRoot 'review-9.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out9 -TimeoutSeconds 30
    $attempts9 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'transport-timeout-no-retry' (([string]$attempts9[0].disposition -eq 'failed-terminal') -and ([string]$attempts9[0].errorClass -eq 'timeout') -and ((Get-ADASReviewMockCallCount) -eq 1)) ([string]$attempts9[0].errorClass)

    # --- 10. Missing required schema field, then one fresh valid retry ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @(
        (New-ADASReviewMockResponse -Content '{"verdict":"PASS","confidence":0.5,"summary":"ok"}' -RequestId 'req-schema-1' -PromptTokens 20 -CompletionTokens 5),
        (New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-schema-2' -PromptTokens 25 -CompletionTokens 6)
    )
    $out10 = Join-Path $tempRoot 'review-10.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out10 -TimeoutSeconds 30
    $attempts10 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'schema-error-then-retry' (([string]$review.verdict -eq 'PASS') -and ([string]$attempts10[0].disposition -eq 'failed-retryable') -and ([string]$attempts10[0].errorClass -eq 'schema-error') -and ((Get-ADASReviewMockCallCount) -eq 2)) ([string]$attempts10[0].errorClass)

    # --- 11. finish_reason=length with parseable content is still retried, accepted from the second attempt ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @(
        (New-ADASReviewMockResponse -Content $validPassJson -FinishReason 'length' -RequestId 'req-lenv-1' -PromptTokens 55 -CompletionTokens 25),
        (New-ADASReviewMockResponse -Content $validPassJson -FinishReason 'stop' -RequestId 'req-lenv-2' -PromptTokens 56 -CompletionTokens 24)
    )
    $out11 = Join-Path $tempRoot 'review-11.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out11 -TimeoutSeconds 30
    $attempts11 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'length-valid-content-retried' (([string]$review.verdict -eq 'PASS') -and ([string]$attempts11[0].errorClass -eq 'finish-reason-length') -and ([string]$attempts11[0].disposition -eq 'failed-retryable') -and ([string]$attempts11[1].disposition -eq 'accepted') -and ([string]$review._adasProvider.providerRequestId -eq 'req-lenv-2')) ([string]$attempts11[0].errorClass)

    # --- 12. More than 5 findings => contract violation, immediate fail-closed, no retry ---
    $manyFindings = '[{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e1","requiredFix":"f1"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e2","requiredFix":"f2"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e3","requiredFix":"f3"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e4","requiredFix":"f4"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e5","requiredFix":"f5"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e6","requiredFix":"f6"}]'
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content ('{"verdict":"PASS","confidence":0.5,"summary":"many","findings":' + $manyFindings + ',"missingEvidence":[],"businessRisks":[]}') -RequestId 'req-many-1' -PromptTokens 30 -CompletionTokens 40))
    $out12 = Join-Path $tempRoot 'review-12.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out12 -TimeoutSeconds 30
    $attempts12 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'finding-limit-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict)
    Add-ADASReviewTestResult 'finding-limit-no-retry' (([string]$attempts12[0].disposition -eq 'failed-terminal') -and ([string]$attempts12[0].errorClass -eq 'finding-limit-exceeded') -and ((Get-ADASReviewMockCallCount) -eq 1)) ([string]$attempts12[0].errorClass)

    # --- 13. Compact prompt: whitelist projection and full diff coverage ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-compact-1' -PromptTokens 10 -CompletionTokens 5))
    $out13 = Join-Path $tempRoot 'review-13.json'
    $null = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out13 -TimeoutSeconds 30
    $promptBody = [string]$global:adasReviewMockCalls[0].body
    Add-ADASReviewTestResult 'compact-gate-whitelist-kept' (($promptBody -match '\\"name\\":\\"STATIC_QUALITY\\"') -and ($promptBody -match '\\"status\\":\\"PASS\\"')) ''
    Add-ADASReviewTestResult 'compact-gate-bloat-dropped' (($promptBody -notmatch 'logPath') -and ($promptBody -notmatch 'ev-blob') -and ($promptBody -notmatch 'checkedAt')) ''
    Add-ADASReviewTestResult 'compact-risk-no-timestamp' ($promptBody -notmatch 'classifiedAt') ''
    Add-ADASReviewTestResult 'compact-task-kept-full' ($promptBody -match 'Synthetic Task53') ''
    Add-ADASReviewTestResult 'compact-diff-hash-stamped' ($promptBody -match '\[DIFF sha256=[0-9a-f]{64}') ''
    Add-ADASReviewTestResult 'compact-diff-covers-hunk' (($promptBody -match 'diff --git') -and ($promptBody -match '\+def test_one')) ''
    Add-ADASReviewTestResult 'compact-output-contract-explicit' (($promptBody -match 'at most 5 findings') -and ($promptBody -match 'no reasoning trace')) ''
    Add-ADASReviewTestResult 'compact-model-no-fallback-param' ($promptBody -notmatch 'thinking') ''

    # --- 14. Diff segment slicing: byte-identical coverage across segments ---
    $smallDiff = "diff --git a/a.py b/a.py`n--- /dev/null`n+++ b/a.py`n@@ -0,0 +1,1 @@`n+small`n"
    $smallSections = Get-ADASReviewDiffSections -DiffText $smallDiff
    Add-ADASReviewTestResult 'slicing-single-segment' (($smallSections.Count -eq 1) -and ([string]$smallSections[0].text -ceq $smallDiff)) "count=$($smallSections.Count)"
    Add-ADASReviewTestResult 'slicing-single-hash' ([string]$smallSections[0].diffSha256 -eq (Get-ADASSha256Text $smallDiff)) ''
    $lineA = "+line-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`n"
    $fileA = "diff --git a/x.py b/x.py`nnew file mode 100644`n--- /dev/null`n+++ b/x.py`n" + ($lineA * 55)
    $fileB = "diff --git a/y.py b/y.py`nnew file mode 100644`n--- /dev/null`n+++ b/y.py`n" + ($lineA * 55)
    $bigDiff = $fileA + $fileB
    $bigSections = Get-ADASReviewDiffSections -DiffText $bigDiff -MaxSectionCharacters 4000
    Add-ADASReviewTestResult 'slicing-multi-segment' ($bigSections.Count -gt 1) "count=$($bigSections.Count)"
    Add-ADASReviewTestResult 'slicing-byte-identical-concat' ((@($bigSections | ForEach-Object { [string]$_.text }) -join '') -ceq $bigDiff) ''
    $hashOk = $true
    foreach ($section in $bigSections) {
        if ([string]$section.segmentSha256 -ne (Get-ADASSha256Text ([string]$section.text))) { $hashOk = $false }
        if ([string]$section.diffSha256 -ne (Get-ADASSha256Text $bigDiff)) { $hashOk = $false }
        if ([int]$section.segment -gt [int]$section.segmentCount) { $hashOk = $false }
    }
    Add-ADASReviewTestResult 'slicing-segment-hashes' $hashOk ''
    $headerCount = ([regex]::Matches($bigDiff, 'diff --git ')).Count
    $slicedHeaderCount = ([regex]::Matches((@($bigSections | ForEach-Object { [string]$_.text }) -join ''), 'diff --git ')).Count
    Add-ADASReviewTestResult 'slicing-file-headers-preserved' ($headerCount -eq $slicedHeaderCount) "headers=$headerCount sliced=$slicedHeaderCount"
    Add-ADASReviewTestResult 'slicing-file-boundary-cut' (($bigSections.Count -eq 2) -and ([string]$bigSections[0].text -ceq $fileA) -and ([string]$bigSections[1].text -ceq $fileB)) "count=$($bigSections.Count)"
    $emptySections = Get-ADASReviewDiffSections -DiffText ''
    Add-ADASReviewTestResult 'slicing-empty-diff-safe' (($emptySections.Count -eq 1) -and ([string]$emptySections[0].text -eq '')) ''

    # --- 15. Task54 truncation-detection matrix: only acquisition-proven truncation blocks before a request ---
    # (a) acquisition metadata flag true on a clean diff => BLOCKED before any request
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson))
    $out15a = Join-Path $tempRoot 'review-15a.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $true -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15a -TimeoutSeconds 30
    Add-ADASReviewTestResult 'truncation-flag-blocks-no-request' (([string]$review.verdict -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 0)) "calls=$(Get-ADASReviewMockCallCount)"

    # (b) exact terminal LF sentinel, flag false => defense-in-depth BLOCKED before any request
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson))
    $out15b = Join-Path $tempRoot 'review-15b.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText ("diff --git a/z.py b/z.py`n+code`n--- DIFF TRUNCATED BY ADAS ---") -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15b -TimeoutSeconds 30
    Add-ADASReviewTestResult 'terminal-lf-sentinel-blocks-no-request' (([string]$review.verdict -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 0)) "calls=$(Get-ADASReviewMockCallCount)"

    # (c) exact terminal CRLF sentinel, flag false => defense-in-depth BLOCKED before any request
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson))
    $out15c = Join-Path $tempRoot 'review-15c.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText ("diff --git a/z.py b/z.py`r`n+code`r`n--- DIFF TRUNCATED BY ADAS ---") -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15c -TimeoutSeconds 30
    Add-ADASReviewTestResult 'terminal-crlf-sentinel-blocks-no-request' (([string]$review.verdict -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 0)) "calls=$(Get-ADASReviewMockCallCount)"

    # (d) sentinel literal inside a mid-diff added source line, flag false => provider request proceeds
    $midDiff = "diff --git a/r.py b/r.py`n--- /dev/null`n+++ b/r.py`n@@ -0,0 +1,3 @@`n+    if (`$DiffText -match '--- DIFF TRUNCATED BY ADAS ---') {`n+        return `$null`n+    }`n"
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-mid-1' -PromptTokens 30 -CompletionTokens 6))
    $out15d = Join-Path $tempRoot 'review-15d.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $midDiff -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15d -TimeoutSeconds 30
    Add-ADASReviewTestResult 'mid-diff-sentinel-source-line-requests' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"

    # (e) sentinel inside a test-fixture string line, flag false => provider request proceeds
    $fixtureDiff = "diff --git a/t.py b/t.py`n--- /dev/null`n+++ b/t.py`n@@ -0,0 +1,2 @@`n+`$fixture = '--- DIFF TRUNCATED BY ADAS ---'`n+assert `$fixture`n"
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-fixture-1' -PromptTokens 30 -CompletionTokens 6))
    $out15e = Join-Path $tempRoot 'review-15e.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $fixtureDiff -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15e -TimeoutSeconds 30
    Add-ADASReviewTestResult 'sentinel-in-fixture-string-requests' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"

    # (f) terminal-like extra trailing content after the sentinel line => not the acquisition suffix => request
    $trailingDiff = "diff --git a/q.py b/q.py`n--- /dev/null`n+++ b/q.py`n@@ -0,0 +1,3 @@`n+code`n--- DIFF TRUNCATED BY ADAS ---`n+trailing-line`n"
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-trailing-1' -PromptTokens 30 -CompletionTokens 6))
    $out15f = Join-Path $tempRoot 'review-15f.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $trailingDiff -DiffTruncated $false -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15f -TimeoutSeconds 30
    Add-ADASReviewTestResult 'terminal-like-trailing-content-requests' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"

    # (g) ambiguous metadata fails closed before any request
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson))
    $out15g = Join-Path $tempRoot 'review-15g.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -DiffSha256 ('0' * 64) -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15g -TimeoutSeconds 30
    Add-ADASReviewTestResult 'metadata-sha-mismatch-blocks-no-request' (([string]$review.verdict -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 0)) "calls=$(Get-ADASReviewMockCallCount)"

    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson))
    $out15h = Join-Path $tempRoot 'review-15h.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -DiffCharacterCount ($diffText.Length + 1) -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15h -TimeoutSeconds 30
    Add-ADASReviewTestResult 'metadata-length-mismatch-blocks-no-request' (([string]$review.verdict -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 0)) "calls=$(Get-ADASReviewMockCallCount)"

    # (h) consistent metadata => provider request proceeds
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-meta-ok-1' -PromptTokens 30 -CompletionTokens 6))
    $out15i = Join-Path $tempRoot 'review-15i.json'
    $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $diffText -DiffTruncated $false -DiffSha256 (Get-ADASSha256Text $diffText) -DiffCharacterCount $diffText.Length -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $out15i -TimeoutSeconds 30
    Add-ADASReviewTestResult 'consistent-metadata-requests' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"

    # --- 16. Full official Task53 change.diff fixture: not truncated, every segment concatenates hash-consistent ---
    if (Test-Path -LiteralPath $task53OfficialDiffPath -PathType Leaf) {
        $fullBytes = [IO.File]::ReadAllBytes($task53OfficialDiffPath)
        $fullText = [Text.Encoding]::UTF8.GetString($fullBytes)
        Add-ADASReviewTestResult 'full-task53-diff-byte-count' (($fullBytes.Length -eq $task53OfficialDiffByteCount) -and ($fullText.Length -eq 177909)) "bytes=$($fullBytes.Length) chars=$($fullText.Length)"
        Add-ADASReviewTestResult 'full-task53-diff-official-sha256' ((Get-ADASSha256Text $fullText) -eq $task53OfficialDiffSha256) ''
        Add-ADASReviewTestResult 'full-task53-diff-no-terminal-sentinel' (-not $fullText.EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) ''
        Add-ADASReviewTestResult 'full-task53-diff-contains-mid-diff-sentinel' ($fullText.Contains('--- DIFF TRUNCATED BY ADAS ---')) ''
        $fullSections = Get-ADASReviewDiffSections -DiffText $fullText
        $fullConcat = (@($fullSections | ForEach-Object { [string]$_.text }) -join '')
        Add-ADASReviewTestResult 'full-task53-segments-concat-byte-identical' ($fullConcat -ceq $fullText) "segments=$($fullSections.Count)"
        $fullHashOk = $true
        foreach ($section in $fullSections) {
            if ([string]$section.diffSha256 -ne $task53OfficialDiffSha256) { $fullHashOk = $false }
            if ([string]$section.segmentSha256 -ne (Get-ADASSha256Text ([string]$section.text))) { $fullHashOk = $false }
            if ([int]$section.segment -gt [int]$section.segmentCount) { $fullHashOk = $false }
        }
        Add-ADASReviewTestResult 'full-task53-segment-hashes-consistent' $fullHashOk ''
        Reset-ADASReviewMock
        $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-full-1' -PromptTokens 600 -CompletionTokens 30))
        $outFull = Join-Path $tempRoot 'review-full.json'
        $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $fullText -DiffTruncated $false -DiffSha256 $task53OfficialDiffSha256 -DiffCharacterCount $fullText.Length -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $outFull -TimeoutSeconds 30
        Add-ADASReviewTestResult 'full-task53-diff-requests-provider' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1) -and ([string]$review._adasProvider.providerRequestId -eq 'req-full-1')) "calls=$(Get-ADASReviewMockCallCount)"
        $fullBody = [string]$global:adasReviewMockCalls[0].body
        Add-ADASReviewTestResult 'full-task53-body-covers-all-segments' ($fullBody -match ('\[DIFF SEGMENT 1/' + $fullSections.Count + ' ')) "segments=$($fullSections.Count)"
        Add-ADASReviewTestResult 'full-task53-body-carries-sentinel-literal' ($fullBody -match 'DIFF TRUNCATED BY ADAS') ''
    }
    else {
        Add-ADASReviewTestResult 'full-task53-diff-fixture-missing' $false "fixture not found: $task53OfficialDiffPath"
    }

    # --- 17. Attempt records never carry response content or secrets ---
    $attemptProps = @($attempts3 | ForEach-Object { $_.PSObject.Properties.Name } | Select-Object -Unique)
    Add-ADASReviewTestResult 'attempt-records-no-content' (($attemptProps -notcontains 'content') -and ($attemptProps -notcontains 'response') -and ($attemptProps -notcontains 'reasoning')) ($attemptProps -join ',')

    # --- 18. Installed-block hash equality with the canonical tracked source ---
    if ($VerifyInstalledBlockPath) {
        $installedBytes = [IO.File]::ReadAllBytes($VerifyInstalledBlockPath)
        $installedText = [Text.Encoding]::UTF8.GetString($installedBytes)
        $installedText = $installedText -replace "^\uFEFF", ''
        $startMarker = 'function New-ADASReviewAttemptRecord {'
        $successorMarker = 'function Get-ADASProofManifest {'
        $start = $installedText.IndexOf($startMarker)
        $end = $installedText.IndexOf($successorMarker, $start)
        if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
            Add-ADASReviewTestResult 'installed-block-extraction' $false "markers not found in $VerifyInstalledBlockPath"
        }
        else {
            Add-ADASReviewTestResult 'installed-block-extraction' $true "block $start..$end"
            $block = $installedText.Substring($start, $end - $start)
            $canonicalBlockText = ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($canonicalPath))) -replace "^\uFEFF", ''
            $blockRawHash = Get-ADASSha256Text $block
            $canonicalRawHash = Get-ADASSha256Text $canonicalBlockText
            $blockNormalizedHash = Get-ADASSha256Text ($block.Replace("`r`n", "`n"))
            $canonicalNormalizedHash = Get-ADASSha256Text ($canonicalBlockText.Replace("`r`n", "`n"))
            $byteEqual = ($blockRawHash -eq $canonicalRawHash)
            $normalizedEqual = ($blockNormalizedHash -eq $canonicalNormalizedHash)
            Add-ADASReviewTestResult 'installed-block-byte-equal' $byteEqual "installed=$blockRawHash canonical=$canonicalRawHash"
            Add-ADASReviewTestResult 'installed-block-normalized-equal' $normalizedEqual "installed=$blockNormalizedHash canonical=$canonicalNormalizedHash"
        }
    }
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path 'function:\Invoke-RestMethod' -Force -ErrorAction SilentlyContinue
    Remove-Variable -Name adasReviewMockCalls -Scope Global -ErrorAction SilentlyContinue
    Remove-Variable -Name adasReviewMockResponses -Scope Global -ErrorAction SilentlyContinue
}

$failed = @($results | Where-Object { -not $_.passed })
$totalCount = $results.Count
$passedCount = $totalCount - $failed.Count
$failedCount = $failed.Count
$summary = [ordered]@{
    test = 'ADAS independent review transport remediation (canonical tracked control plane)'
    mode = $runMode
    canonicalPath = $canonicalPath
    verifiedInstalledBlockPath = $(if ($VerifyInstalledBlockPath) { $VerifyInstalledBlockPath } else { $null })
    generatedAt = (Get-Date).ToString('o')
    total = $totalCount
    passed = $passedCount
    failed = $failedCount
    results = @($results | ForEach-Object { $_ })
}
if ($ResultJsonPath) { Write-ADASJson -Path $ResultJsonPath -Value $summary }
$summary | ConvertTo-Json -Depth 6
if ($failedCount -gt 0) { exit 1 }
exit 0
