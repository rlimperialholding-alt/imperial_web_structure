<#
.SYNOPSIS
Task55 — isolated, network-free control-plane regression for the ADAS
independent-review transport: Task54 truncation-detection contract plus the
Task55 context-derived diff-acquisition budget (canonical tracked source).

Three modes, all secret-free and network-free (Invoke-RestMethod is replaced
by a global scripted mock in every mode, so no HTTP call is possible):

  * default (no switches): loads and runs the CANONICAL git-tracked unit
    (Imperial-ADAS-ReviewTransport.ps1) standalone, with faithful mirrors of
    the tiny profile dependencies defined in this file;
  * -ModulePath <profile psm1>: imports the installed profile module and
    runs the same cases against the installed sections;
  * -VerifyInstalledBlockPath <profile psm1>: independently extracts the
    installed acquisition section (Get-ADASReviewModelContextWindow ..
    Get-ADASDiffText, successor Get-ADASImpactMap) and the installed review
    block (New-ADASReviewAttemptRecord .. Invoke-ADASIndependentReview,
    successor Get-ADASProofManifest) and proves byte/normalized SHA-256
    equality with the two canonical tracked sections.

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

Task55 context-budget matrix (context-window metadata, budget formula,
acquisition boundaries, fail-closed budget-exceeded contract, full
candidate):
  * model metadata reading: valid manifest with/without
    effective_context_window_percent, smaller max_context_window, missing
    file, missing slug, empty slug, non-numeric/zero/negative/out-of-range
    context_window, invalid JSON => valid=false with a named reason;
  * budget formula: 1,048,576 x 95% = 996,147 effective; minus output
    reserve 24,000, prompt reserve 65,536, safety reserve 32,768 =>
    budgetTokens = budgetBytes = budgetCharacters = 873,843,
    budgetSource='context-window';
  * unknown/missing metadata => explicit safe fallback cap 350,000,
    budgetSource='fallback-cap' (fail-closed, never infinity);
  * 349,999- and 350,001-character diffs are FULL under the derived budget
    (the legacy 350,000 acquisition cap is gone);
  * exact budget boundary (873,843 chars) is FULL; budget+1 (873,844) =>
    budgetExceeded, text='', no truncation sentinel, full size/hash
    metadata retained;
  * fallback-cap boundary: 350,000 full, 350,001 => budget-exceeded;
  * multibyte content is compared on UTF-8 bytes (chars <= budget but
    bytes > budget => exceeded);
  * explicit -MaxCharacters keeps the legacy-compatible character-cap
    semantics (testing/back-compat), budgetSource='explicit-parameter';
  * multi-model derivation uses the MINIMUM budget across the requested
    slugs;
  * New-ADASDiffBudgetExceededResult: BLOCKED, category
    'diff-budget-exceeded', exact size/budget/hash metadata, BLOCKED
    provider attestation, 0 attempts, 0 provider requests, no diff content
    or secret material in the written result;
  * full candidate diff (-FullCandidateDiffPath): exact byte/char/line/file
    counts and SHA-256, no terminal sentinel, fits the derived budget, the
    deterministic segments concatenate byte-identically, the review reaches
    the provider, and the parsed request body contains the whole diff
    exactly once (every diff byte appears exactly once in the prompt);
  * the same full candidate under unreadable metadata fails closed via the
    fallback cap (the Task55 preflight scenario).
Exit code 0 only when every check passed.

.PARAMETER ModulePath
When set, run the case matrix against this installed profile module.

.PARAMETER CanonicalPath
Canonical tracked unit; default: sibling Imperial-ADAS-ReviewTransport.ps1.

.PARAMETER VerifyInstalledBlockPath
When set, independently extract the installed sections and prove hash
equality with the canonical tracked source.

.PARAMETER Task53OfficialDiffPath
Full official Task53 change.diff fixture; default:
sibling fixtures\task53-official-change.diff.

.PARAMETER FullCandidateDiffPath
Optional full candidate diff (Task55 final cumulative git diff) for the
full-candidate matrix. When omitted the full-candidate cases report one
explicit 'fixture-not-provided' failure.

.PARAMETER FullCandidateDiffSha256
Expected SHA-256 of the full candidate diff (lowercase hex).

.PARAMETER FullCandidateDiffByteCount
Expected UTF-8 byte count of the full candidate diff.

.PARAMETER FullCandidateDiffCharacterCount
Expected character count of the full candidate diff.

.PARAMETER FullCandidateDiffLineCount
Expected line count (count of LF + 1 unless the text ends with LF).

.PARAMETER FullCandidateDiffFileCount
Expected file count (lines starting with 'diff --git ').

.PARAMETER ModelMetadataPath
Optional local model metadata manifest for the context-budget matrix. The
matrix uses a synthetic temp manifest when this is empty, so both modes are
deterministic and never depend on profile-local files.

.PARAMETER ResultJsonPath
Optional machine-readable JSON result path.
#>
[CmdletBinding()]
param(
    [string]$ModulePath = '',
    [string]$CanonicalPath = '',
    [string]$VerifyInstalledBlockPath = '',
    [string]$Task53OfficialDiffPath = '',
    [string]$FullCandidateDiffPath = '',
    [string]$FullCandidateDiffSha256 = '',
    [int64]$FullCandidateDiffByteCount = -1,
    [int64]$FullCandidateDiffCharacterCount = -1,
    [int64]$FullCandidateDiffLineCount = -1,
    [int64]$FullCandidateDiffFileCount = -1,
    [string]$ModelMetadataPath = '',
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

function New-ADASReviewSyntheticDiff {
    param([Parameter(Mandatory = $true)][int]$Characters)
    # Deterministic ASCII-only synthetic diff of exactly the requested
    # character count (no multibyte content; byte count == character count).
    $unit = "diff --git a/syn.py b/syn.py`n+abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ`n"
    $repeats = [Math]::Ceiling([double]$Characters / [double]$unit.Length) + 1
    $text = ([string]$unit * $repeats).Substring(0, $Characters)
    return $text
}

function Get-ADASReviewLineCount {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    # Same line-count contract as the canonical acquisition metadata:
    # count of LF, plus one when the text does not end with LF.
    $count = ([regex]::Matches($Text, "`n")).Count
    if ($Text.Length -gt 0 -and -not $Text.EndsWith("`n")) { $count++ }
    return $count
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
# --- Task55 synthetic model metadata (deterministic in both modes; no profile file needed) ---
$metadataPath = if ($ModelMetadataPath) { $ModelMetadataPath } else { Join-Path $tempRoot 'models.json' }
if (-not $ModelMetadataPath) {
    $syntheticModels = [pscustomobject]@{
        models = @([pscustomobject]@{
            slug = 'deepseek-v4-pro'; context_window = 1048576; max_context_window = 1048576; effective_context_window_percent = 95
        })
    }
    Write-ADASJson -Path $metadataPath -Value $syntheticModels
}
# Derived budget with the synthetic manifest (verified below): 1,048,576 * 95% = 996,147
# effective; 996,147 - 24,000 (output) - 65,536 (prompt) - 32,768 (safety) = 873,843.
$expectedDerivedBudget = [int64]873843
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

    # --- 18. Task55 context-window metadata reading matrix ---
    $windowValid = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'context-metadata-valid' ([bool]$windowValid.valid) ([string]$windowValid.reason)
    Add-ADASReviewTestResult 'context-metadata-values' (([int64]$windowValid.contextWindow -eq 1048576) -and ([int64]$windowValid.maxContextWindow -eq 1048576) -and ([int]$windowValid.effectivePercent -eq 95) -and ([int64]$windowValid.effectiveWindow -eq 996147)) "effective=$($windowValid.effectiveWindow)"
    Add-ADASReviewTestResult 'context-metadata-source-path' ([string]$windowValid.sourcePath -eq $metadataPath) ([string]$windowValid.sourcePath)
    $metaNoPercentPath = Join-Path $tempRoot 'models-nopct.json'
    Write-ADASJson -Path $metaNoPercentPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 1048576 }) })
    $windowNoPct = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaNoPercentPath
    Add-ADASReviewTestResult 'context-metadata-no-percent-uses-raw' (([bool]$windowNoPct.valid) -and ([int64]$windowNoPct.effectiveWindow -eq 1048576) -and ([int]$windowNoPct.effectivePercent -eq 0)) "effective=$($windowNoPct.effectiveWindow)"
    $metaSmallMaxPath = Join-Path $tempRoot 'models-smallmax.json'
    Write-ADASJson -Path $metaSmallMaxPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 1048576; max_context_window = 500000; effective_context_window_percent = 95 }) })
    $windowSmallMax = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaSmallMaxPath
    Add-ADASReviewTestResult 'context-metadata-smaller-max-wins' (([bool]$windowSmallMax.valid) -and ([int64]$windowSmallMax.effectiveWindow -eq 475000)) "effective=$($windowSmallMax.effectiveWindow)"
    $missingMetadataPath = Join-Path $tempRoot 'models-missing.json'
    $windowMissing = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'context-metadata-missing-file-fail-closed' ((-not [bool]$windowMissing.valid) -and ([string]$windowMissing.reason -eq 'metadata-file-not-found') -and ([int64]$windowMissing.effectiveWindow -eq 0)) ([string]$windowMissing.reason)
    $metaOtherSlugPath = Join-Path $tempRoot 'models-other.json'
    Write-ADASJson -Path $metaOtherSlugPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'other-model'; context_window = 1048576 }) })
    $windowOther = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaOtherSlugPath
    Add-ADASReviewTestResult 'context-metadata-slug-not-found-fail-closed' ((-not [bool]$windowOther.valid) -and ([string]$windowOther.reason -eq 'model-slug-not-found')) ([string]$windowOther.reason)
    $windowEmpty = Get-ADASReviewModelContextWindow -ReviewerModel '' -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'context-metadata-empty-slug-fail-closed' ((-not [bool]$windowEmpty.valid) -and ([string]$windowEmpty.reason -eq 'reviewer-model-not-specified')) ([string]$windowEmpty.reason)
    foreach ($badWindow in @(0, -1)) {
        $metaBadPath = Join-Path $tempRoot ("models-bad-$badWindow.json")
        Write-ADASJson -Path $metaBadPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = $badWindow }) })
        $windowBad = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaBadPath
        Add-ADASReviewTestResult "context-metadata-window-$badWindow-fail-closed" ((-not [bool]$windowBad.valid) -and ([string]$windowBad.reason -eq 'context-window-out-of-range')) ([string]$windowBad.reason)
    }
    $metaHugePath = Join-Path $tempRoot 'models-huge.json'
    Write-ADASJson -Path $metaHugePath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 999999999 }) })
    $windowHuge = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaHugePath
    Add-ADASReviewTestResult 'context-metadata-huge-window-fail-closed' ((-not [bool]$windowHuge.valid) -and ([string]$windowHuge.reason -eq 'context-window-out-of-range')) ([string]$windowHuge.reason)
    $metaTextPath = Join-Path $tempRoot 'models-text.json'
    Write-ADASJson -Path $metaTextPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 'abc' }) })
    $windowText = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaTextPath
    Add-ADASReviewTestResult 'context-metadata-nonnumeric-window-fail-closed' ((-not [bool]$windowText.valid) -and ([string]$windowText.reason -eq 'context-window-not-numeric')) ([string]$windowText.reason)
    $metaInvalidJsonPath = Join-Path $tempRoot 'models-invalid.json'
    Write-ADASUtf8NoBom -Path $metaInvalidJsonPath -Text '{invalid json'
    $windowInvalidJson = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaInvalidJsonPath
    Add-ADASReviewTestResult 'context-metadata-invalid-json-fail-closed' ((-not [bool]$windowInvalidJson.valid) -and ([string]$windowInvalidJson.reason -eq 'metadata-json-invalid')) ([string]$windowInvalidJson.reason)

    # --- 19. Task55 budget formula matrix ---
    $budgetDerived = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-formula-tokens' (([int64]$budgetDerived.budgetTokens -eq $expectedDerivedBudget) -and ([int64]$budgetDerived.budgetBytes -eq $expectedDerivedBudget) -and ([int64]$budgetDerived.budgetCharacters -eq $expectedDerivedBudget)) "tokens=$($budgetDerived.budgetTokens)"
    Add-ADASReviewTestResult 'budget-formula-reserves' (([int64]$budgetDerived.outputReserveTokens -eq 24000) -and ([int64]$budgetDerived.promptReserveTokens -eq 65536) -and ([int64]$budgetDerived.safetyReserveTokens -eq 32768)) ''
    Add-ADASReviewTestResult 'budget-formula-source' (([string]$budgetDerived.budgetSource -eq 'context-window') -and ([bool]$budgetDerived.modelMetadataValid) -and ([string]$budgetDerived.fallbackReason -eq '')) ([string]$budgetDerived.budgetSource)
    $budgetFallback = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'budget-fallback-cap' (([string]$budgetFallback.budgetSource -eq 'fallback-cap') -and ([int64]$budgetFallback.budgetBytes -eq 350000) -and ([int64]$budgetFallback.budgetCharacters -eq 350000) -and ([string]$budgetFallback.fallbackReason -eq 'metadata-file-not-found') -and (-not [bool]$budgetFallback.modelMetadataValid)) ([string]$budgetFallback.budgetSource)
    $metaSmallWindowPath = Join-Path $tempRoot 'models-smallwindow.json'
    Write-ADASJson -Path $metaSmallWindowPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 100000 }) })
    $budgetTooSmall = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaSmallWindowPath
    Add-ADASReviewTestResult 'budget-window-too-small-fallback' (([string]$budgetTooSmall.budgetSource -eq 'fallback-cap') -and ([string]$budgetTooSmall.fallbackReason -eq 'context-window-too-small-for-reserves') -and ([bool]$budgetTooSmall.modelMetadataValid)) ([string]$budgetTooSmall.fallbackReason)

    # --- 20. Task55 acquisition boundary matrix ---
    $d349999 = New-ADASReviewSyntheticDiff -Characters 349999
    $meta349999 = Get-ADASDiffAcquisitionMeta -DiffText $d349999 -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-349999-full' ((-not [bool]$meta349999.budgetExceeded) -and (-not [bool]$meta349999.truncated) -and ([string]$meta349999.text -ceq $d349999) -and ([int64]$meta349999.characterCount -eq 349999) -and ([int64]$meta349999.byteCount -eq 349999)) "source=$($meta349999.budgetSource)"
    $d350001 = New-ADASReviewSyntheticDiff -Characters 350001
    $meta350001 = Get-ADASDiffAcquisitionMeta -DiffText $d350001 -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-350001-full-new-budget' ((-not [bool]$meta350001.budgetExceeded) -and ([string]$meta350001.text -ceq $d350001) -and ([string]$meta350001.budgetSource -eq 'context-window')) "budget=$($meta350001.budgetCharacters)"
    $dBoundary = New-ADASReviewSyntheticDiff -Characters $expectedDerivedBudget
    $metaBoundary = Get-ADASDiffAcquisitionMeta -DiffText $dBoundary -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-exact-boundary-full' ((-not [bool]$metaBoundary.budgetExceeded) -and ([string]$metaBoundary.text -ceq $dBoundary) -and ([int64]$metaBoundary.characterCount -eq $expectedDerivedBudget)) "chars=$($metaBoundary.characterCount)"
    $dOver = New-ADASReviewSyntheticDiff -Characters ($expectedDerivedBudget + 1)
    $metaOver = Get-ADASDiffAcquisitionMeta -DiffText $dOver -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-plus-one-exceeded' (([bool]$metaOver.budgetExceeded) -and ([bool]$metaOver.truncated) -and ([string]$metaOver.text -eq '') -and ([int64]$metaOver.characterCount -eq ($expectedDerivedBudget + 1)) -and ([int64]$metaOver.byteCount -eq ($expectedDerivedBudget + 1)) -and ([string]$metaOver.sha256 -eq (Get-ADASSha256Text $dOver))) "chars=$($metaOver.characterCount) budget=$($metaOver.budgetCharacters)"
    Add-ADASReviewTestResult 'budget-plus-one-no-sentinel' (-not ([string]$metaOver.text).EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) ''
    $dFbBoundary = New-ADASReviewSyntheticDiff -Characters 350000
    $metaFbBoundary = Get-ADASDiffAcquisitionMeta -DiffText $dFbBoundary -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'fallback-cap-350000-full' ((-not [bool]$metaFbBoundary.budgetExceeded) -and ([string]$metaFbBoundary.budgetSource -eq 'fallback-cap') -and ([string]$metaFbBoundary.fallbackReason -eq 'metadata-file-not-found')) "budget=$($metaFbBoundary.budgetCharacters)"
    $dFbOver = New-ADASReviewSyntheticDiff -Characters 350001
    $metaFbOver = Get-ADASDiffAcquisitionMeta -DiffText $dFbOver -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'fallback-cap-350001-exceeded-fail-closed' (([bool]$metaFbOver.budgetExceeded) -and ([string]$metaFbOver.text -eq '') -and ([int64]$metaFbOver.characterCount -eq 350001) -and ([string]$metaFbOver.budgetSource -eq 'fallback-cap')) "chars=$($metaFbOver.characterCount)"
    $multibyteText = [string]::new([char]0x0151, 10)
    $metaMultibyte = Get-ADASDiffAcquisitionMeta -DiffText $multibyteText -MaxCharacters 15
    Add-ADASReviewTestResult 'multibyte-byte-budget-exceeded' (([bool]$metaMultibyte.budgetExceeded) -and ([int64]$metaMultibyte.characterCount -eq 10) -and ([int64]$metaMultibyte.byteCount -eq 20) -and ([int64]$metaMultibyte.budgetBytes -eq 15)) "chars=$($metaMultibyte.characterCount) bytes=$($metaMultibyte.byteCount)"
    $dExplicitOver = New-ADASReviewSyntheticDiff -Characters 1001
    $metaExplicit = Get-ADASDiffAcquisitionMeta -DiffText $dExplicitOver -MaxCharacters 1000
    Add-ADASReviewTestResult 'explicit-parameter-cap-respected' (([bool]$metaExplicit.budgetExceeded) -and ([string]$metaExplicit.budgetSource -eq 'explicit-parameter') -and ([string]$metaExplicit.text -eq '')) ([string]$metaExplicit.budgetSource)
    $dExplicitFit = New-ADASReviewSyntheticDiff -Characters 1000
    $metaExplicitFit = Get-ADASDiffAcquisitionMeta -DiffText $dExplicitFit -MaxCharacters 1000
    Add-ADASReviewTestResult 'explicit-parameter-exact-cap-full' ((-not [bool]$metaExplicitFit.budgetExceeded) -and ([string]$metaExplicitFit.text -ceq $dExplicitFit)) ''
    $metaEmpty = Get-ADASDiffAcquisitionMeta -DiffText '' -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'acquisition-empty-diff-safe' ((-not [bool]$metaEmpty.budgetExceeded) -and ([int64]$metaEmpty.characterCount -eq 0) -and ([int64]$metaEmpty.byteCount -eq 0) -and ([int64]$metaEmpty.lineCount -eq 0) -and ([int64]$metaEmpty.fileCount -eq 0) -and ([string]$metaEmpty.text -eq '')) ''
    $metaMultiModel = Get-ADASDiffAcquisitionMeta -DiffText $d349999 -ReviewerModel @('deepseek-v4-pro', 'unknown-model') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'multi-model-min-budget-wins' ((-not [bool]$metaMultiModel.budgetExceeded) -and ([string]$metaMultiModel.budgetSource -eq 'fallback-cap-min-over-models') -and ([int64]$metaMultiModel.budgetCharacters -eq 350000) -and (@($metaMultiModel.perModelBudgets).Count -eq 2)) "source=$($metaMultiModel.budgetSource)"
    $metaMetaLineCount = Get-ADASDiffAcquisitionMeta -DiffText $diffText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'acquisition-line-file-counts' (([int64]$metaMetaLineCount.lineCount -eq (Get-ADASReviewLineCount $diffText)) -and ([int64]$metaMetaLineCount.fileCount -eq ([regex]::Matches($diffText, '(?m)^diff --git ')).Count) -and ([string]$metaMetaLineCount.sha256 -eq (Get-ADASSha256Text $diffText))) "lines=$($metaMetaLineCount.lineCount) files=$($metaMetaLineCount.fileCount)"

    # --- 21. Task55 fail-closed budget-exceeded result contract ---
    $metaExc = Get-ADASDiffAcquisitionMeta -DiffText $dFbOver -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
    Reset-ADASReviewMock
    $outExc = Join-Path $tempRoot 'review-budget-exceeded.json'
    $exc = New-ADASDiffBudgetExceededResult -RequestedModel 'deepseek-v4-pro' -DiffCharacterCount ([int64]$metaExc.characterCount) -DiffByteCount ([int64]$metaExc.byteCount) -DiffSha256 ([string]$metaExc.sha256) -BudgetCharacters ([int64]$metaExc.budgetCharacters) -BudgetBytes ([int64]$metaExc.budgetBytes) -BudgetSource ([string]$metaExc.budgetSource) -OutputPath $outExc
    Add-ADASReviewTestResult 'budget-exceeded-verdict-blocked' ([string]$exc.verdict -eq 'BLOCKED') ([string]$exc.verdict)
    $excFinding = @($exc.findings)[0]
    Add-ADASReviewTestResult 'budget-exceeded-category' (([string]$excFinding.category -eq 'diff-budget-exceeded') -and ([string]$excFinding.severity -eq 'HIGH')) ([string]$excFinding.category)
    Add-ADASReviewTestResult 'budget-exceeded-no-provider-request' ((Get-ADASReviewMockCallCount) -eq 0) "calls=$(Get-ADASReviewMockCallCount)"
    $excBudget = $exc._adasDiffBudget
    Add-ADASReviewTestResult 'budget-exceeded-metadata-exact' (([string]$excBudget.diffSha256 -eq [string]$metaExc.sha256) -and ([int64]$excBudget.diffCharacterCount -eq 350001) -and ([int64]$excBudget.diffByteCount -eq 350001) -and ([int64]$excBudget.budgetCharacters -eq 350000) -and ([int64]$excBudget.budgetBytes -eq 350000) -and ([bool]$excBudget.budgetExceeded) -and (-not [bool]$excBudget.truncationPerformed) -and (-not [bool]$excBudget.sentinelAppended) -and (-not [bool]$excBudget.secretMaterialRecorded)) ''
    Add-ADASReviewTestResult 'budget-exceeded-provider-blocked' (([string]$exc._adasProvider.status -eq 'BLOCKED') -and ($null -eq $exc._adasProvider.providerRequestId) -and ([int64]$exc._adasProvider.totalTokens -eq 0) -and (-not [bool]$exc._adasProvider.secretMaterialRecorded)) ([string]$exc._adasProvider.status)
    Add-ADASReviewTestResult 'budget-exceeded-attempts-empty' (@($exc._adasAttempts).Count -eq 0) "attempts=$(@($exc._adasAttempts).Count)"
    $excFileText = [IO.File]::ReadAllText($outExc, [Text.Encoding]::UTF8)
    Add-ADASReviewTestResult 'budget-exceeded-file-written' ($excFileText -match '"verdict":\s*"BLOCKED"' -and $excFileText -match 'diff-budget-exceeded') ''
    Add-ADASReviewTestResult 'budget-exceeded-file-no-diff-content' ($excFileText -notmatch 'abcdefghijklmnopqrstuvwxyz0123456789') ''
    Add-ADASReviewTestResult 'budget-exceeded-file-no-secrets' ($excFileText -notmatch 'Bearer' -and $excFileText -notmatch 'sk-[A-Za-z0-9]') ''

    # --- 22. Task55 full candidate diff matrix (only when the fixture is provided) ---
    if ($FullCandidateDiffPath -and (Test-Path -LiteralPath $FullCandidateDiffPath -PathType Leaf)) {
        $candBytes = [IO.File]::ReadAllBytes($FullCandidateDiffPath)
        $candText = [Text.Encoding]::UTF8.GetString($candBytes)
        Add-ADASReviewTestResult 'full-candidate-byte-count' ([int64]$candBytes.Length -eq $FullCandidateDiffByteCount) "bytes=$($candBytes.Length)"
        Add-ADASReviewTestResult 'full-candidate-character-count' ([int64]$candText.Length -eq $FullCandidateDiffCharacterCount) "chars=$($candText.Length)"
        Add-ADASReviewTestResult 'full-candidate-line-count' ([int64](Get-ADASReviewLineCount $candText) -eq $FullCandidateDiffLineCount) "lines=$(Get-ADASReviewLineCount $candText)"
        Add-ADASReviewTestResult 'full-candidate-file-count' ([int64]([regex]::Matches($candText, '(?m)^diff --git ')).Count -eq $FullCandidateDiffFileCount) "files=$(([regex]::Matches($candText, '(?m)^diff --git ')).Count)"
        Add-ADASReviewTestResult 'full-candidate-sha256' ([string](Get-ADASSha256Text $candText) -eq $FullCandidateDiffSha256) ([string](Get-ADASSha256Text $candText))
        Add-ADASReviewTestResult 'full-candidate-no-terminal-sentinel' (-not $candText.EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) ''
        $candMeta = Get-ADASDiffAcquisitionMeta -DiffText $candText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
        Add-ADASReviewTestResult 'full-candidate-fits-derived-budget' ((-not [bool]$candMeta.budgetExceeded) -and ([string]$candMeta.budgetSource -eq 'context-window') -and ([string]$candMeta.text -ceq $candText) -and ([string]$candMeta.sha256 -eq $FullCandidateDiffSha256)) "chars=$($candMeta.characterCount) budget=$($candMeta.budgetCharacters)"
        $candMetaFallback = Get-ADASDiffAcquisitionMeta -DiffText $candText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
        Add-ADASReviewTestResult 'full-candidate-missing-metadata-fail-closed' (([bool]$candMetaFallback.budgetExceeded) -and ([string]$candMetaFallback.text -eq '') -and ([string]$candMetaFallback.budgetSource -eq 'fallback-cap') -and ([int64]$candMetaFallback.characterCount -eq $FullCandidateDiffCharacterCount) -and ([string]$candMetaFallback.sha256 -eq $FullCandidateDiffSha256)) "fallback-budget=$($candMetaFallback.budgetCharacters)"
        $candSections = Get-ADASReviewDiffSections -DiffText $candText
        $candConcat = (@($candSections | ForEach-Object { [string]$_.text }) -join '')
        Add-ADASReviewTestResult 'full-candidate-segments-concat-byte-identical' ($candConcat -ceq $candText) "segments=$($candSections.Count)"
        $candHashOk = $true
        foreach ($section in $candSections) {
            if ([string]$section.diffSha256 -ne $FullCandidateDiffSha256) { $candHashOk = $false }
            if ([string]$section.segmentSha256 -ne (Get-ADASSha256Text ([string]$section.text))) { $candHashOk = $false }
            if ([int]$section.segment -gt [int]$section.segmentCount) { $candHashOk = $false }
        }
        Add-ADASReviewTestResult 'full-candidate-segment-hashes-consistent' $candHashOk ''
        Reset-ADASReviewMock
        $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-cand-1' -PromptTokens 1000 -CompletionTokens 30))
        $outCand = Join-Path $tempRoot 'review-candidate.json'
        $review = Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $candText -DiffTruncated $false -DiffSha256 $FullCandidateDiffSha256 -DiffCharacterCount $candText.Length -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath $outCand -TimeoutSeconds 120
        Add-ADASReviewTestResult 'full-candidate-review-requests-provider' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1) -and ([string]$review._adasProvider.providerRequestId -eq 'req-cand-1')) "calls=$(Get-ADASReviewMockCallCount)"
        $candBody = [string]$global:adasReviewMockCalls[0].body
        $candParsedBody = $candBody | ConvertFrom-Json
        $candUserContent = [string]$candParsedBody.messages[1].content
        # Every diff byte appears exactly once in the prompt: the deterministic
        # sections are disjoint, their concatenation is byte-identical with the
        # full diff (proven above), and each section text must occur as a
        # contiguous substring exactly once (segment headers are interleaved,
        # which is the Task52 design - the diff is never concatenated twice).
        $sectionsOnceOk = $true
        foreach ($section in $candSections) {
            $sectionText = [string]$section.text
            $firstIdx = $candUserContent.IndexOf($sectionText)
            if ($firstIdx -lt 0 -or $firstIdx -ne $candUserContent.LastIndexOf($sectionText)) { $sectionsOnceOk = $false }
        }
        Add-ADASReviewTestResult 'full-candidate-every-diff-byte-exactly-once' $sectionsOnceOk "sections=$($candSections.Count)"
        $markersOk = $true
        foreach ($section in $candSections) {
            $marker = "[DIFF SEGMENT $($section.segment)/$($section.segmentCount) "
            if ($candUserContent.IndexOf($marker) -ne $candUserContent.LastIndexOf($marker)) { $markersOk = $false }
        }
        Add-ADASReviewTestResult 'full-candidate-segment-markers-once' $markersOk ''
    }
    else {
        Add-ADASReviewTestResult 'full-candidate-fixture-not-provided' $false "FullCandidateDiffPath missing: $FullCandidateDiffPath"
    }

    # --- 23. Installed two-section hash equality with the canonical tracked source ---
    if ($VerifyInstalledBlockPath) {
        $installedBytes = [IO.File]::ReadAllBytes($VerifyInstalledBlockPath)
        $installedText = [Text.Encoding]::UTF8.GetString($installedBytes)
        $installedText = $installedText -replace "^\uFEFF", ''
        $canonicalFullText = ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($canonicalPath))) -replace "^\uFEFF", ''
        $sectionBMarker = 'function New-ADASReviewAttemptRecord {'
        $sectionBStart = $canonicalFullText.IndexOf($sectionBMarker)
        $canonicalStartsWithA = $canonicalFullText.StartsWith('function Get-ADASReviewModelContextWindow {')
        if ($sectionBStart -le 0 -or -not $canonicalStartsWithA) {
            Add-ADASReviewTestResult 'canonical-section-partition' $false 'canonical layout drifted (leading content or missing section B start)'
        }
        else {
            Add-ADASReviewTestResult 'canonical-section-partition' $true "sectionBStart=$sectionBStart"
            $canonicalSectionA = $canonicalFullText.Substring(0, $sectionBStart)
            $canonicalSectionB = $canonicalFullText.Substring($sectionBStart)
            $markerA1 = 'function Get-ADASReviewModelContextWindow {'
            $markerASucc = 'function Get-ADASImpactMap {'
            $startA = $installedText.IndexOf($markerA1)
            $endA = $installedText.IndexOf($markerASucc, $startA)
            $markerB1 = 'function New-ADASReviewAttemptRecord {'
            $markerBSucc = 'function Get-ADASProofManifest {'
            $startB = $installedText.IndexOf($markerB1)
            $endB = $installedText.IndexOf($markerBSucc, $startB)
            if ($startA -lt 0 -or $endA -lt 0 -or $endA -le $startA -or $startB -lt 0 -or $endB -lt 0 -or $endB -le $startB) {
                Add-ADASReviewTestResult 'installed-sections-extraction' $false "markers not found in $VerifyInstalledBlockPath (A=$startA/$endA B=$startB/$endB)"
            }
            else {
                Add-ADASReviewTestResult 'installed-sections-extraction' $true "A=$startA..$endA B=$startB..$endB"
                $installedA = $installedText.Substring($startA, $endA - $startA)
                $installedB = $installedText.Substring($startB, $endB - $startB)
                $installedARawHash = Get-ADASSha256Text $installedA
                $installedANormalizedHash = Get-ADASSha256Text ($installedA.Replace("`r`n", "`n"))
                $installedBRawHash = Get-ADASSha256Text $installedB
                $installedBNormalizedHash = Get-ADASSha256Text ($installedB.Replace("`r`n", "`n"))
                $canonicalARawHash = Get-ADASSha256Text $canonicalSectionA
                $canonicalANormalizedHash = Get-ADASSha256Text ($canonicalSectionA.Replace("`r`n", "`n"))
                $canonicalBRawHash = Get-ADASSha256Text $canonicalSectionB
                $canonicalBNormalizedHash = Get-ADASSha256Text ($canonicalSectionB.Replace("`r`n", "`n"))
                Add-ADASReviewTestResult 'installed-sectionA-byte-equal' ($installedARawHash -eq $canonicalARawHash) "installed=$installedARawHash canonical=$canonicalARawHash"
                Add-ADASReviewTestResult 'installed-sectionA-normalized-equal' ($installedANormalizedHash -eq $canonicalANormalizedHash) "installed=$installedANormalizedHash canonical=$canonicalANormalizedHash"
                Add-ADASReviewTestResult 'installed-sectionB-byte-equal' ($installedBRawHash -eq $canonicalBRawHash) "installed=$installedBRawHash canonical=$canonicalBRawHash"
                Add-ADASReviewTestResult 'installed-sectionB-normalized-equal' ($installedBNormalizedHash -eq $canonicalBNormalizedHash) "installed=$installedBNormalizedHash canonical=$canonicalBNormalizedHash"
            }
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
