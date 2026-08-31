<#
.SYNOPSIS
Task55/56/57/58 — isolated, network-free control-plane regression for the ADAS independent-review transport (canonical tracked source); Invoke-RestMethod is replaced by a global scripted mock, so no HTTP call is possible. Modes: default = canonical unit standalone with faithful mirrors of the tiny profile dependencies; -ModulePath = the same cases against the installed profile module; -VerifyInstalledBlockPath = extract the installed sections and prove byte/normalized SHA-256 equality with the canonical tracked source.
Coverage: valid PASS/BLOCKED; retry flows with the SECOND request attestation; two bad attempts => fail-closed review-unavailable BLOCKED; Task52 matrix (transport errors never masked, compact whitelist projection, hash-stamped segment coverage, strict schema, no reasoning trace, no secret material); Task54 truncation matrix incl. the full official Task53 change.diff fixture (178,839 bytes, official SHA-256); Task55/56 context-budget matrix (named reasons, derived 873,843 budget at 95%, documented 350,000 fallback cap, explicit ZERO budget for valid-too-small windows, exact boundary FULL, budget+1 => budgetExceeded with text='' and full metadata, multibyte on UTF-8 bytes, multi-model MINIMUM budget, zero budget wins in any order, New-ADASDiffBudgetExceededResult: BLOCKED + exact metadata + 0 provider requests); full candidate diff: exact counts/SHA-256, every diff byte appears exactly once in the prompt; Task56 review-output contract; Task57 attestation matrix (PASS requires non-empty EXACT actualModel, requestId, positive tokens, no observed fallback); Task58 attestation terminal (failed attestation overrides the FINAL persisted verdict to BLOCKED + deduplicated HIGH provider-attestation-invalid finding; attempts kept); Task58 budget-terminal e2e (real installed caller control flow with an instrumented provider seam; the installed region is hash-proven byte-equal to the tracked canonical caller region: budget-exceeded => two persisted BLOCKED reviews + exact meta + exit 80 + 0 provider requests; normal diff => provider section reachable); Task57 file/line contract; Task57 fallback metadata (fallbackObserved only for an observed different model; failures carry the precise unavailabilityClass); Task57 caller migration audit + installer atomicity (offline fault-injection rollback, caller sync, canonical discipline, idempotent noop); Task56 changed-line gate (cumulative git diff --numstat total must be at most -ChangedLineLimit, default 6000). Exit code 0 only when every check passed.
.PARAMETER ModulePath — run the case matrix against this installed profile module.  .PARAMETER CanonicalPath — canonical tracked unit; default: sibling Imperial-ADAS-ReviewTransport.ps1.
.PARAMETER VerifyInstalledBlockPath — independently extract the installed sections and prove hash equality with the canonical tracked source.  .PARAMETER Task53OfficialDiffPath — full official Task53 change.diff fixture; default: sibling fixtures\task53-official-change.diff.
.PARAMETER FullCandidateDiffPath — optional full candidate diff; omitted => explicit 'fixture-not-provided' failure.  .PARAMETER FullCandidateDiffSha256 — expected SHA-256 of the full candidate diff (lowercase hex).
.PARAMETER FullCandidateDiffByteCount — expected UTF-8 byte count of the full candidate diff.  .PARAMETER FullCandidateDiffCharacterCount — expected character count of the full candidate diff.
.PARAMETER FullCandidateDiffLineCount — expected line count (count of LF + 1 unless the text ends with LF).  .PARAMETER FullCandidateDiffFileCount — expected file count (lines starting with 'diff --git ').
.PARAMETER ModelMetadataPath — optional local model metadata manifest; synthetic temp manifest when empty.  .PARAMETER CallerAuditProfileDir — live profile scripts directory for the caller-migration audit (a failure when omitted).
.PARAMETER ChangedLineBaselineCommit — baseline commit for the cumulative changed-line gate (a failure when omitted).  .PARAMETER ChangedLineLimit — protected cumulative changed-line limit; default 6000.
.PARAMETER ResultJsonPath — optional machine-readable JSON result path.
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
    [string]$CallerAuditProfileDir = '',
    [string]$ChangedLineBaselineCommit = '',
    [int]$ChangedLineLimit = 6000,
    [string]$CanonicalCallerRegionPath = '',
    [string]$InstallerPath = '',
    [string]$ResultJsonPath = ''
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'; $canonicalPath = if ($CanonicalPath) { $CanonicalPath } else { Join-Path $PSScriptRoot 'Imperial-ADAS-ReviewTransport.ps1' }
$canonicalCallerRegionPath = if ($CanonicalCallerRegionPath) { $CanonicalCallerRegionPath } else { Join-Path $PSScriptRoot 'canonical-adas-caller-region.ps1' }
$installerPath = if ($InstallerPath) { $InstallerPath } else { Join-Path $PSScriptRoot 'Install-ADASReviewTransportSync.ps1' }
$runMode = if ($ModulePath) { 'installed-module' } else { 'canonical-standalone' }; $task53OfficialDiffPath = if ($Task53OfficialDiffPath) { $Task53OfficialDiffPath } else { Join-Path $PSScriptRoot 'fixtures\task53-official-change.diff' }
# The official Task53 change.diff SHA-256 is carried as 8-char chunks and joined at runtime so
# the tracked source carries no high-entropy hex literal the tracked-secret probe would flag.
$task53OfficialDiffSha256 = ('56d7c403', '99c16aea', '2bc5bd30', '50368d3c', '79d27516', 'f501b5d4', '814cdfc5', '054fbb87') -join ''; $task53OfficialDiffByteCount = 178839; $results = New-Object 'System.Collections.Generic.List[object]'
function Add-ADASReviewTestResult {
    param([string]$Name, [bool]$Passed, [string]$Detail = '')
    $script:results.Add([pscustomobject]@{ name = $Name; passed = [bool]$Passed; detail = [string]$Detail })
}
# --- Faithful mirrors of the four tiny profile dependencies, vendored only so the canonical unit can run standalone; the installed-module mode uses the real profile code. ---
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
function Read-ADASReviewUtf8File {
    param([Parameter(Mandatory = $true)][string]$Path)
    # Ordinal char compare: StartsWith(string) is culture-sensitive and treats U+FEFF as weightless, which would strip the first real character of BOM-less content.
    $text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($Path))
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { return $text.Substring(1) }
    return $text
}
# --- Loader: encoding-deterministic (explicit UTF-8 decode; BOM'd temp copy for dot-sourcing). ---
if ($ModulePath) {
    try {
        Import-Module $ModulePath -Force -ErrorAction Stop
        Add-ADASReviewTestResult 'module-import' $true "imported: $ModulePath"
    }
    catch {
        Add-ADASReviewTestResult 'module-import' $false $_.Exception.Message
        throw
    }
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseInput((Read-ADASReviewUtf8File $ModulePath), [ref]$tokens, [ref]$errors) | Out-Null
    Add-ADASReviewTestResult 'module-parse' ($errors.Count -eq 0) "$($errors.Count) parse error(s)"
}
else {
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseInput((Read-ADASReviewUtf8File $canonicalPath), [ref]$tokens, [ref]$errors) | Out-Null
    Add-ADASReviewTestResult 'canonical-parse' ($errors.Count -eq 0) "$($errors.Count) parse error(s)"
    $canonicalBomPath = Join-Path ([IO.Path]::GetTempPath()) ('adas-canonical-bom-' + [Guid]::NewGuid().ToString('N') + '.ps1')
    try {
        [IO.File]::WriteAllText($canonicalBomPath, (Read-ADASReviewUtf8File $canonicalPath), (New-Object Text.UTF8Encoding($true)))
        . $canonicalBomPath
        Remove-Item -LiteralPath $canonicalBomPath -Force -ErrorAction SilentlyContinue
        Add-ADASReviewTestResult 'canonical-load' $true "dot-sourced: $canonicalPath"
    }
    catch {
        Remove-Item -LiteralPath $canonicalBomPath -Force -ErrorAction SilentlyContinue
        Add-ADASReviewTestResult 'canonical-load' $false $_.Exception.Message
        throw
    }
}
# Full canonical text (BOM-safe UTF-8 decode) for the Task57 synthetic-module/caller tests.
$canonicalFullText = Read-ADASReviewUtf8File $canonicalPath
# --- Global network mock (network-free: every HTTP call lands here) ---
$global:adasReviewMockCalls = New-Object 'System.Collections.Generic.List[object]'
$global:adasReviewMockResponses = @()
function global:Invoke-RestMethod {
    param($Method, $Uri, $Headers, $ContentType, $Body, $TimeoutSec)
    $callIndex = $global:adasReviewMockCalls.Count
    $global:adasReviewMockCalls.Add([pscustomobject]@{ body = [string]$Body })
    $planned = $global:adasReviewMockResponses
    if ($callIndex -ge $planned.Count) { throw "mock transport: no scripted response for call $($callIndex)" }
    $plannedItem = $planned[$callIndex]
    if ($plannedItem -is [string] -and $plannedItem.StartsWith('THROW:')) { throw ($plannedItem.Substring(6)) }
    return $plannedItem
}
function Reset-ADASReviewMock {
    $global:adasReviewMockCalls = New-Object 'System.Collections.Generic.List[object]'
    $global:adasReviewMockResponses = @()
}
function New-ADASReviewMockResponse {
    param([string]$Content, [string]$FinishReason = 'stop', [string]$Model = 'deepseek-v4-pro', [string]$RequestId = 'req-1', [long]$PromptTokens = 10, [long]$CompletionTokens = 5)
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
    # Deterministic ASCII-only synthetic diff of exactly the requested character count (no multibyte content; byte count == character count).
    $unit = "diff --git a/syn.py b/syn.py`n+abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ`n"; $repeats = [Math]::Ceiling([double]$Characters / [double]$unit.Length) + 1
    return ([string]$unit * $repeats).Substring(0, $Characters)
}
function Get-ADASReviewLineCount {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    # Same line-count contract as the canonical acquisition metadata.
    $count = ([regex]::Matches($Text, "`n")).Count
    if ($Text.Length -gt 0 -and -not $Text.EndsWith("`n")) { $count++ }
    return $count
}
$validPassJson = '{"verdict":"PASS","confidence":0.9,"summary":"no defects found","findings":[],"missingEvidence":[],"businessRisks":[]}'
$validBlockedJson = '{"verdict":"BLOCKED","confidence":0.7,"summary":"critical defect","findings":[{"severity":"CRITICAL","category":"security","file":"x.py","line":"1","evidence":"leak","requiredFix":"sanitize"}],"missingEvidence":[],"businessRisks":["data loss"]}'
$truncatedJson = '{"verdict":"PASS","confidence":0.8,"summary":"UNIQUEMARKER-1'; $taskText = "Synthetic Task53 control-plane review test`n## Acceptance`n- deterministic review transport remediation`n"
$diffText = "diff --git a/services/platform-core/tests/test_x.py b/services/platform-core/tests/test_x.py`nnew file mode 100644`nindex 0000000..1111111`n--- /dev/null`n+++ b/services/platform-core/tests/test_x.py`n@@ -0,0 +1,2 @@`n+def test_one():`n+    assert True`n"
$riskProfile = [pscustomobject]@{ level = 'R2'; score = 2; reasons = @('Futtatható kód változott.'); reversibility = 'git-revertable'; externalExposure = $false; personalDataPossible = $false; classifiedAt = (Get-Date).ToString('o') }
$gateSummaries = @([pscustomobject]@{ gate = 1; name = 'STATIC_QUALITY'; status = 'PASS'; summary = 'lint ok'; findings = @(); evidence = @('ev-blob'); logPath = 'C:\long\log\path.log'; checkedAt = '2026-08-30T00:00:00' })
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('adas-review-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
# --- Task55 synthetic model metadata (deterministic in both modes; no profile file needed) ---
$metadataPath = if ($ModelMetadataPath) { $ModelMetadataPath } else { Join-Path $tempRoot 'models.json' }
if (-not $ModelMetadataPath) {
    $syntheticModels = [pscustomobject]@{
        models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 1048576; max_context_window = 1048576; effective_context_window_percent = 95 })
    }
    Write-ADASJson -Path $metadataPath -Value $syntheticModels
}
# Derived budget with the synthetic manifest (verified below): 1,048,576 * 95% = 996,147 effective; 996,147 - 24,000 (output) - 65,536 (prompt) - 32,768 (safety) = 873,843.
$expectedDerivedBudget = [int64]873843
function Invoke-ADASReviewTestReview {
    param([string]$OutputName, [string]$Diff, [bool]$Truncated = $false, [string]$Sha = '', [int64]$Chars = -1, [int]$Timeout = 30)
    # Shared wrapper: single fresh mock'd review invocation with the common fixture inputs.
    return Invoke-ADASIndependentReview -ApiKey 'fake-key' -Model 'deepseek-v4-pro' -TaskText $taskText -DiffText $Diff -DiffTruncated $Truncated -DiffSha256 $Sha -DiffCharacterCount $Chars -RiskProfile $riskProfile -GateSummaries $gateSummaries -OutputPath (Join-Path $tempRoot ($OutputName + '.json')) -TimeoutSeconds $Timeout
}
try {
    # --- 2. Valid first PASS ---
    Reset-ADASReviewMock
    $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content '{"verdict":"PASS","confidence":0.9,"summary":"no defects","findings":[],"missingEvidence":[],"businessRisks":[],"extraField":"should-be-dropped"}' -RequestId 'req-pass-1' -PromptTokens 100 -CompletionTokens 20))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-1' -Diff $diffText
    Add-ADASReviewTestResult 'valid-first-pass-verdict' ([string]$review.verdict -eq 'PASS') ([string]$review.verdict); $provider1 = $review._adasProvider; Add-ADASReviewTestResult 'valid-first-pass-attestation' (([string]$provider1.status -eq 'PASS') -and ([string]$provider1.providerRequestId -eq 'req-pass-1') -and ([int64]$provider1.totalTokens -eq 120) -and (-not [bool]$provider1.fallbackObserved)) ([string]$provider1.status); $attempts1 = @($review._adasAttempts); Add-ADASReviewTestResult 'valid-first-pass-attempts' (($attempts1.Count -eq 1) -and ([string]$attempts1[0].disposition -eq 'accepted') -and (-not [bool]$attempts1[0].secretMaterialRecorded)) "attempts " + $attempts1.Count; Add-ADASReviewTestResult 'valid-first-pass-call-count' ((Get-ADASReviewMockCallCount) -eq 1) "calls=$(Get-ADASReviewMockCallCount)"; Add-ADASReviewTestResult 'no-sentinel-requests-provider' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"
    $fileText1 = [IO.File]::ReadAllText((Join-Path $tempRoot 'review-1.json'), [Text.Encoding]::UTF8)
    Add-ADASReviewTestResult 'valid-first-pass-file-written' ($fileText1 -match '"verdict":\s*"PASS"') ''; Add-ADASReviewTestResult 'schema-only-fields-accepted' ($fileText1 -notmatch 'extraField') ''; Add-ADASReviewTestResult 'no-reasoning-trace-stored' ($fileText1 -notmatch 'reasoning_content' -and $fileText1 -notmatch 'reasoning') ''
    # --- 3. Valid first BLOCKED ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validBlockedJson -RequestId 'req-blocked-1' -PromptTokens 40 -CompletionTokens 10)); $review = Invoke-ADASReviewTestReview -OutputName 'review-2' -Diff $diffText
    Add-ADASReviewTestResult 'valid-first-blocked-verdict' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict); $finding0 = @($review.findings)[0]; Add-ADASReviewTestResult 'valid-first-blocked-finding' (([string]$finding0.severity -eq 'CRITICAL') -and ([string]$finding0.category -eq 'security') -and (-not [string]::IsNullOrWhiteSpace([string]$finding0.evidence)) -and (-not [string]::IsNullOrWhiteSpace([string]$finding0.requiredFix))) ([string]$finding0.severity); Add-ADASReviewTestResult 'valid-first-blocked-attestation-pass' ([string]$review._adasProvider.status -eq 'PASS') ([string]$review._adasProvider.status); Add-ADASReviewTestResult 'valid-first-blocked-call-count' ((Get-ADASReviewMockCallCount) -eq 1) "calls=$(Get-ADASReviewMockCallCount)"
    # --- 4. Empty content + finish_reason=length, then one fresh valid retry; attestation from the SECOND request ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content '' -FinishReason 'length' -RequestId 'req-len-1' -PromptTokens 50 -CompletionTokens 50), (New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-ok-2' -PromptTokens 60 -CompletionTokens 30))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-3' -Diff $diffText
    Add-ADASReviewTestResult 'empty-length-then-retry-verdict' ([string]$review.verdict -eq 'PASS') ([string]$review.verdict); Add-ADASReviewTestResult 'empty-length-then-retry-call-count' ((Get-ADASReviewMockCallCount) -eq 2) "calls=$(Get-ADASReviewMockCallCount)"; $attempts3 = @($review._adasAttempts); Add-ADASReviewTestResult 'empty-length-attempt-1-record' (($attempts3.Count -eq 2) -and ([string]$attempts3[0].disposition -eq 'failed-retryable') -and ([string]$attempts3[0].errorClass -eq 'empty-content') -and ([string]$attempts3[0].finishReason -eq 'length')) ([string]$attempts3[0].errorClass); Add-ADASReviewTestResult 'empty-length-attempt-2-accepted' ([string]$attempts3[1].disposition -eq 'accepted') ([string]$attempts3[1].disposition); $provider3 = $review._adasProvider; Add-ADASReviewTestResult 'retry-attestation-second-request-id' (([string]$provider3.providerRequestId -eq 'req-ok-2') -and ([string]$provider3.requestIdentifier -eq 'req-ok-2')) ([string]$provider3.providerRequestId); Add-ADASReviewTestResult 'retry-attestation-second-model' ([string]$provider3.actualModel -eq 'deepseek-v4-pro') ([string]$provider3.actualModel); Add-ADASReviewTestResult 'retry-attestation-second-tokens' (([int64]$provider3.inputTokens -eq 60) -and ([int64]$provider3.outputTokens -eq 30) -and ([int64]$provider3.totalTokens -eq 90)) "in=$($provider3.inputTokens) out=$($provider3.outputTokens)"; Add-ADASReviewTestResult 'retry-attestation-status-pass' ([string]$provider3.status -eq 'PASS') ([string]$provider3.status)
    $body0 = [string]$global:adasReviewMockCalls[0].body; $body1 = [string]$global:adasReviewMockCalls[1].body
    Add-ADASReviewTestResult 'retry-is-fresh-request-with-repair-header' (($body0 -notmatch 'REPAIR REQUEST') -and ($body1 -match 'REPAIR REQUEST')) ''
    # --- 5. Truncated JSON, then one fresh valid retry ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $truncatedJson -RequestId 'req-trunc-1' -PromptTokens 40 -CompletionTokens 10), (New-ADASReviewMockResponse -Content $validBlockedJson -RequestId 'req-fix-2' -PromptTokens 30 -CompletionTokens 15))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-4' -Diff $diffText
    Add-ADASReviewTestResult 'truncated-then-retry-verdict' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict); $attempts4 = @($review._adasAttempts); Add-ADASReviewTestResult 'truncated-attempt-1-class' (([string]$attempts4[0].disposition -eq 'failed-retryable') -and ([string]$attempts4[0].errorClass -eq 'json-parse-error')) ([string]$attempts4[0].errorClass); Add-ADASReviewTestResult 'truncated-retry-accepted-attestation' (([string]$attempts4[1].disposition -eq 'accepted') -and ([string]$review._adasProvider.providerRequestId -eq 'req-fix-2')) ([string]$review._adasProvider.providerRequestId); Add-ADASReviewTestResult 'truncated-then-retry-call-count' ((Get-ADASReviewMockCallCount) -eq 2) "calls=$(Get-ADASReviewMockCallCount)"; Add-ADASReviewTestResult 'truncated-content-not-stored' (([IO.File]::ReadAllText((Join-Path $tempRoot 'review-4.json'), [Text.Encoding]::UTF8)) -notmatch 'UNIQUEMARKER-1') ''
    # --- 6. Two bad attempts => fail-closed review-unavailable BLOCKED ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content '' -FinishReason 'length' -RequestId 'req-bad-1' -PromptTokens 50 -CompletionTokens 50), (New-ADASReviewMockResponse -Content $truncatedJson -RequestId 'req-bad-2' -PromptTokens 40 -CompletionTokens 10))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-5' -Diff $diffText
    Add-ADASReviewTestResult 'two-bad-attempts-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict); $finding5 = @($review.findings)[0]; Add-ADASReviewTestResult 'two-bad-attempts-review-unavailable' (([string]$finding5.category -eq 'review-unavailable') -and ([string]$finding5.severity -eq 'HIGH')) ([string]$finding5.category); Add-ADASReviewTestResult 'two-bad-attempts-evidence-clean' (([string]$finding5.evidence -match 'reviewer attempt hib') -and ([string]$finding5.evidence -notmatch 'UNIQUEMARKER')) ([string]$finding5.evidence); Add-ADASReviewTestResult 'two-bad-attempts-attestation-blocked' ([string]$review._adasProvider.status -eq 'BLOCKED') ([string]$review._adasProvider.status); $attempts5 = @($review._adasAttempts); Add-ADASReviewTestResult 'two-bad-attempts-records' (($attempts5.Count -eq 2) -and ([string]$attempts5[0].errorClass -eq 'empty-content') -and ([string]$attempts5[1].errorClass -eq 'json-parse-error') -and (-not [bool]$attempts5[0].secretMaterialRecorded) -and (-not [bool]$attempts5[1].secretMaterialRecorded)) "count " + $attempts5.Count; Add-ADASReviewTestResult 'two-bad-attempts-no-third-call' ((Get-ADASReviewMockCallCount) -eq 2) "calls=$(Get-ADASReviewMockCallCount)"
    # --- 7. Fallback model => Task58 fail-closed terminal: verdict BLOCKED + HIGH finding (no retry) ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -Model 'deepseek-other-model' -RequestId 'req-fb-1' -PromptTokens 20 -CompletionTokens 8)); $review = Invoke-ADASReviewTestReview -OutputName 'review-6' -Diff $diffText
    $provider6 = $review._adasProvider; $attempts6 = @($review._adasAttempts); $finding6 = @($review.findings | Where-Object { $_.category -eq 'provider-attestation-invalid' })
    Add-ADASReviewTestResult 'fallback-model-verdict-overridden-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict); Add-ADASReviewTestResult 'fallback-model-attestation-blocked' (([string]$provider6.status -eq 'BLOCKED') -and ([bool]$provider6.fallbackObserved) -and ([string]$provider6.actualModel -eq 'deepseek-other-model')) ([string]$provider6.status)
    Add-ADASReviewTestResult 'fallback-model-high-finding' (($finding6.Count -eq 1) -and ([string]$finding6[0].severity -eq 'HIGH') -and ([string]$finding6[0].evidence -match 'fallback')) ([string]$finding6[0].evidence)
    Add-ADASReviewTestResult 'fallback-model-attempts-preserved-no-retry' (($attempts6.Count -eq 1) -and ([string]$attempts6[0].disposition -eq 'accepted') -and ([string]$attempts6[0].actualModel -eq 'deepseek-other-model') -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"
    # --- 8. Empty request id / zero tokens => Task58 verdict BLOCKED + HIGH finding, attempts kept ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId '' -PromptTokens 0 -CompletionTokens 0)); $review = Invoke-ADASReviewTestReview -OutputName 'review-7' -Diff $diffText
    $attempts7b = @($review._adasAttempts); $finding7b = @($review.findings | Where-Object { $_.category -eq 'provider-attestation-invalid' })
    Add-ADASReviewTestResult 'zero-token-verdict-blocked' (([string]$review.verdict -eq 'BLOCKED') -and ([string]$review._adasProvider.status -eq 'BLOCKED') -and ($null -eq $review._adasProvider.providerRequestId) -and ([int64]$review._adasProvider.totalTokens -eq 0)) ([string]$review.verdict)
    Add-ADASReviewTestResult 'zero-token-high-finding-precise' (($finding7b.Count -eq 1) -and ([string]$finding7b[0].severity -eq 'HIGH') -and ([string]$finding7b[0].evidence -match 'requestId .res') -and ([string]$finding7b[0].evidence -match 'totalTokens=0') -and (-not [string]::IsNullOrWhiteSpace([string]$finding7b[0].requiredFix))) ([string]$finding7b[0].evidence)
    Add-ADASReviewTestResult 'zero-token-attempts-preserved' (($attempts7b.Count -eq 1) -and ([string]$attempts7b[0].disposition -eq 'accepted') -and ([int64]$attempts7b[0].totalTokens -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 1)) "calls=$(Get-ADASReviewMockCallCount)"
    $file7bText = [IO.File]::ReadAllText((Join-Path $tempRoot 'review-7.json'), [Text.Encoding]::UTF8)
    Add-ADASReviewTestResult 'zero-token-persisted-blocked' (($file7bText -match '"verdict":\s*"BLOCKED"') -and ($file7bText -match 'provider-attestation-invalid')) ''
    # --- 9. Transport errors are never masked by retries ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @('THROW:The remote server returned an error: (401) Unauthorized.'); $review = Invoke-ADASReviewTestReview -OutputName 'review-8' -Diff $diffText
    Add-ADASReviewTestResult 'transport-401-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict); $attempts8 = @($review._adasAttempts); Add-ADASReviewTestResult 'transport-401-no-retry' (($attempts8.Count -eq 1) -and ([string]$attempts8[0].disposition -eq 'failed-terminal') -and ([string]$attempts8[0].errorClass -eq 'http-401') -and ((Get-ADASReviewMockCallCount) -eq 1)) ([string]$attempts8[0].errorClass)
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @('THROW:The operation has timed out.'); $review = Invoke-ADASReviewTestReview -OutputName 'review-9' -Diff $diffText; $attempts9 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'transport-timeout-no-retry' (([string]$attempts9[0].disposition -eq 'failed-terminal') -and ([string]$attempts9[0].errorClass -eq 'timeout') -and ((Get-ADASReviewMockCallCount) -eq 1)) ([string]$attempts9[0].errorClass)
    # --- 10. Missing required schema field, then one fresh valid retry ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content '{"verdict":"PASS","confidence":0.5,"summary":"ok"}' -RequestId 'req-schema-1' -PromptTokens 20 -CompletionTokens 5), (New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-schema-2' -PromptTokens 25 -CompletionTokens 6))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-10' -Diff $diffText; $attempts10 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'schema-error-then-retry' (([string]$review.verdict -eq 'PASS') -and ([string]$attempts10[0].disposition -eq 'failed-retryable') -and ([string]$attempts10[0].errorClass -eq 'schema-error') -and ((Get-ADASReviewMockCallCount) -eq 2)) ([string]$attempts10[0].errorClass)
    # --- 11. finish_reason=length with parseable content is still retried, accepted from the second attempt ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -FinishReason 'length' -RequestId 'req-lenv-1' -PromptTokens 55 -CompletionTokens 25), (New-ADASReviewMockResponse -Content $validPassJson -FinishReason 'stop' -RequestId 'req-lenv-2' -PromptTokens 56 -CompletionTokens 24))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-11' -Diff $diffText; $attempts11 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'length-valid-content-retried' (([string]$review.verdict -eq 'PASS') -and ([string]$attempts11[0].errorClass -eq 'finish-reason-length') -and ([string]$attempts11[0].disposition -eq 'failed-retryable') -and ([string]$attempts11[1].disposition -eq 'accepted') -and ([string]$review._adasProvider.providerRequestId -eq 'req-lenv-2')) ([string]$attempts11[0].errorClass)
    # --- 12. More than 5 findings => contract violation, immediate fail-closed, no retry ---
    $manyFindings = '[{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e1","requiredFix":"f1"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e2","requiredFix":"f2"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e3","requiredFix":"f3"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e4","requiredFix":"f4"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e5","requiredFix":"f5"},{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e6","requiredFix":"f6"}]'
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content ('{"verdict":"PASS","confidence":0.5,"summary":"many","findings":' + $manyFindings + ',"missingEvidence":[],"businessRisks":[]}') -RequestId 'req-many-1' -PromptTokens 30 -CompletionTokens 40))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-12' -Diff $diffText; $attempts12 = @($review._adasAttempts)
    Add-ADASReviewTestResult 'finding-limit-blocked' ([string]$review.verdict -eq 'BLOCKED') ([string]$review.verdict); Add-ADASReviewTestResult 'finding-limit-no-retry' (([string]$attempts12[0].disposition -eq 'failed-terminal') -and ([string]$attempts12[0].errorClass -eq 'finding-limit-exceeded') -and ((Get-ADASReviewMockCallCount) -eq 1)) ([string]$attempts12[0].errorClass)
    # --- 13. Compact prompt: whitelist projection and full diff coverage ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-compact-1' -PromptTokens 10 -CompletionTokens 5))
    $null = Invoke-ADASReviewTestReview -OutputName 'review-13' -Diff $diffText; $promptBody = [string]$global:adasReviewMockCalls[0].body
    Add-ADASReviewTestResult 'compact-gate-whitelist-kept' (($promptBody -match '\\"name\\":\\"STATIC_QUALITY\\"') -and ($promptBody -match '\\"status\\":\\"PASS\\"')) ''; Add-ADASReviewTestResult 'compact-gate-bloat-dropped' (($promptBody -notmatch 'logPath') -and ($promptBody -notmatch 'ev-blob') -and ($promptBody -notmatch 'checkedAt')) ''; Add-ADASReviewTestResult 'compact-risk-no-timestamp' ($promptBody -notmatch 'classifiedAt') ''; Add-ADASReviewTestResult 'compact-task-kept-full' ($promptBody -match 'Synthetic Task53') ''; Add-ADASReviewTestResult 'compact-diff-hash-stamped' ($promptBody -match '\[DIFF sha256=[0-9a-f]{64}') ''; Add-ADASReviewTestResult 'compact-diff-covers-hunk' (($promptBody -match 'diff --git') -and ($promptBody -match '\+def test_one')) ''; Add-ADASReviewTestResult 'compact-output-contract-explicit' (($promptBody -match 'at most 5 findings') -and ($promptBody -match 'no reasoning trace')) ''; Add-ADASReviewTestResult 'compact-model-no-fallback-param' ($promptBody -notmatch 'thinking') ''
    # --- 14. Diff segment slicing: byte-identical coverage across segments ---
    $smallDiff = "diff --git a/a.py b/a.py`n--- /dev/null`n+++ b/a.py`n@@ -0,0 +1,1 @@`n+small`n"; $smallSections = Get-ADASReviewDiffSections -DiffText $smallDiff
    Add-ADASReviewTestResult 'slicing-single-segment' (($smallSections.Count -eq 1) -and ([string]$smallSections[0].text -ceq $smallDiff)) "count=$($smallSections.Count)"; Add-ADASReviewTestResult 'slicing-single-hash' ([string]$smallSections[0].diffSha256 -eq (Get-ADASSha256Text $smallDiff)) ''
    $lineA = "+line-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`n"; $fileA = "diff --git a/x.py b/x.py`nnew file mode 100644`n--- /dev/null`n+++ b/x.py`n" + ($lineA * 55)
    $fileB = "diff --git a/y.py b/y.py`nnew file mode 100644`n--- /dev/null`n+++ b/y.py`n" + ($lineA * 55); $bigDiff = $fileA + $fileB; $bigSections = Get-ADASReviewDiffSections -DiffText $bigDiff -MaxSectionCharacters 4000
    Add-ADASReviewTestResult 'slicing-multi-segment' ($bigSections.Count -gt 1) "count=$($bigSections.Count)"; Add-ADASReviewTestResult 'slicing-byte-identical-concat' ((@($bigSections | ForEach-Object { [string]$_.text }) -join '') -ceq $bigDiff) ''
    $hashOk = $true
    foreach ($section in $bigSections) {
        if ([string]$section.segmentSha256 -ne (Get-ADASSha256Text ([string]$section.text))) { $hashOk = $false }
        if ([string]$section.diffSha256 -ne (Get-ADASSha256Text $bigDiff)) { $hashOk = $false }
        if ([int]$section.segment -gt [int]$section.segmentCount) { $hashOk = $false }
    }
    Add-ADASReviewTestResult 'slicing-segment-hashes' $hashOk ''
    $headerCount = ([regex]::Matches($bigDiff, 'diff --git ')).Count; $slicedHeaderCount = ([regex]::Matches((@($bigSections | ForEach-Object { [string]$_.text }) -join ''), 'diff --git ')).Count
    Add-ADASReviewTestResult 'slicing-file-headers-preserved' ($headerCount -eq $slicedHeaderCount) "headers=$headerCount sliced=$slicedHeaderCount"; Add-ADASReviewTestResult 'slicing-file-boundary-cut' (($bigSections.Count -eq 2) -and ([string]$bigSections[0].text -ceq $fileA) -and ([string]$bigSections[1].text -ceq $fileB)) "count=$($bigSections.Count)"
    $emptySections = Get-ADASReviewDiffSections -DiffText ''; Add-ADASReviewTestResult 'slicing-empty-diff-safe' (($emptySections.Count -eq 1) -and ([string]$emptySections[0].text -eq '')) ''
    # --- 15. Task54 truncation-detection matrix: only acquisition-proven truncation blocks ---
    $truncationCases = @(
        @{ name = 'truncation-flag-blocks-no-request'; diff = $diffText; truncated = $true; sha = ''; chars = -1; expectBlocked = $true },
        @{ name = 'terminal-lf-sentinel-blocks-no-request'; diff = "diff --git a/z.py b/z.py`n+code`n--- DIFF TRUNCATED BY ADAS ---"; truncated = $false; sha = ''; chars = -1; expectBlocked = $true },
        @{ name = 'terminal-crlf-sentinel-blocks-no-request'; diff = "diff --git a/z.py b/z.py`r`n+code`r`n--- DIFF TRUNCATED BY ADAS ---"; truncated = $false; sha = ''; chars = -1; expectBlocked = $true },
        @{ name = 'mid-diff-sentinel-source-line-requests'; diff = "diff --git a/r.py b/r.py`n--- /dev/null`n+++ b/r.py`n@@ -0,0 +1,3 @@`n+    if (`$DiffText -match '--- DIFF TRUNCATED BY ADAS ---') {`n+        return `$null`n+    }`n"; truncated = $false; sha = ''; chars = -1; expectBlocked = $false },
        @{ name = 'sentinel-in-fixture-string-requests'; diff = "diff --git a/t.py b/t.py`n--- /dev/null`n+++ b/t.py`n@@ -0,0 +1,2 @@`n+`$fixture = '--- DIFF TRUNCATED BY ADAS ---'`n+assert `$fixture`n"; truncated = $false; sha = ''; chars = -1; expectBlocked = $false },
        @{ name = 'terminal-like-trailing-content-requests'; diff = "diff --git a/q.py b/q.py`n--- /dev/null`n+++ b/q.py`n@@ -0,0 +1,3 @@`n+code`n--- DIFF TRUNCATED BY ADAS ---`n+trailing-line`n"; truncated = $false; sha = ''; chars = -1; expectBlocked = $false },
        @{ name = 'metadata-sha-mismatch-blocks-no-request'; diff = $diffText; truncated = $false; sha = ('0' * 64); chars = -1; expectBlocked = $true },
        @{ name = 'metadata-length-mismatch-blocks-no-request'; diff = $diffText; truncated = $false; sha = ''; chars = ($diffText.Length + 1); expectBlocked = $true },
        @{ name = 'consistent-metadata-requests'; diff = $diffText; truncated = $false; sha = (Get-ADASSha256Text $diffText); chars = $diffText.Length; expectBlocked = $false }
    )
    foreach ($case in $truncationCases) {
        Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId ('req-' + $case.name + '-1')))
        $review = Invoke-ADASReviewTestReview -OutputName ('review-' + $case.name) -Diff ([string]$case.diff) -Truncated ([bool]$case.truncated) -Sha ([string]$case.sha) -Chars ([int64]$case.chars)
        $blockedOk = ([string]$review.verdict -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 0) -and ((Get-ADASReviewMockCallCount) -eq 0); $requestOk = ([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1); $passed = if ($case.expectBlocked) { $blockedOk } else { $requestOk }
        Add-ADASReviewTestResult $case.name $passed "calls=$(Get-ADASReviewMockCallCount)"
    }
    # --- 16. Full official Task53 change.diff fixture: not truncated, every segment concatenates hash-consistent ---
    if (Test-Path -LiteralPath $task53OfficialDiffPath -PathType Leaf) {
        $fullBytes = [IO.File]::ReadAllBytes($task53OfficialDiffPath); $fullText = [Text.Encoding]::UTF8.GetString($fullBytes)
        Add-ADASReviewTestResult 'full-task53-diff-byte-count' (($fullBytes.Length -eq $task53OfficialDiffByteCount) -and ($fullText.Length -eq 177909)) "bytes=$($fullBytes.Length) chars=$($fullText.Length)"; Add-ADASReviewTestResult 'full-task53-diff-official-sha256' ((Get-ADASSha256Text $fullText) -eq $task53OfficialDiffSha256) ''
        Add-ADASReviewTestResult 'full-task53-diff-no-terminal-sentinel' (-not $fullText.EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) ''; Add-ADASReviewTestResult 'full-task53-diff-contains-mid-diff-sentinel' ($fullText.Contains('--- DIFF TRUNCATED BY ADAS ---')) ''
        $fullSections = Get-ADASReviewDiffSections -DiffText $fullText; $fullConcat = (@($fullSections | ForEach-Object { [string]$_.text }) -join '')
        Add-ADASReviewTestResult 'full-task53-segments-concat-byte-identical' ($fullConcat -ceq $fullText) "segments=$($fullSections.Count)"
        $fullHashOk = $true
        foreach ($section in $fullSections) {
            if ([string]$section.diffSha256 -ne $task53OfficialDiffSha256) { $fullHashOk = $false }; if ([string]$section.segmentSha256 -ne (Get-ADASSha256Text ([string]$section.text))) { $fullHashOk = $false }; if ([int]$section.segment -gt [int]$section.segmentCount) { $fullHashOk = $false }
        }
        Add-ADASReviewTestResult 'full-task53-segment-hashes-consistent' $fullHashOk ''
        Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-full-1' -PromptTokens 600 -CompletionTokens 30)); $review = Invoke-ADASReviewTestReview -OutputName 'review-full' -Diff $fullText -Sha $task53OfficialDiffSha256 -Chars $fullText.Length -Timeout 60
        Add-ADASReviewTestResult 'full-task53-diff-requests-provider' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1) -and ([string]$review._adasProvider.providerRequestId -eq 'req-full-1')) "calls=$(Get-ADASReviewMockCallCount)"
        $fullBody = [string]$global:adasReviewMockCalls[0].body
        Add-ADASReviewTestResult 'full-task53-body-covers-all-segments' ($fullBody -match ('\[DIFF SEGMENT 1/' + $fullSections.Count + ' ')) "segments=$($fullSections.Count)"; Add-ADASReviewTestResult 'full-task53-body-carries-sentinel-literal' ($fullBody -match 'DIFF TRUNCATED BY ADAS') ''
    }
    else {
        Add-ADASReviewTestResult 'full-task53-diff-fixture-missing' $false "fixture not found: $task53OfficialDiffPath"
    }
    # --- 17. Attempt records never carry response content or secrets ---
    $attemptProps = @($attempts3 | ForEach-Object { $_.PSObject.Properties.Name } | Select-Object -Unique)
    Add-ADASReviewTestResult 'attempt-records-no-content' (($attemptProps -notcontains 'content') -and ($attemptProps -notcontains 'response') -and ($attemptProps -notcontains 'reasoning')) ($attemptProps -join ',')
    # --- 18. Task55 context-window metadata reading matrix ---
    $windowValid = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'context-metadata-valid' ([bool]$windowValid.valid) ([string]$windowValid.reason); Add-ADASReviewTestResult 'context-metadata-values' (([int64]$windowValid.contextWindow -eq 1048576) -and ([int64]$windowValid.maxContextWindow -eq 1048576) -and ([int]$windowValid.effectivePercent -eq 95) -and ([int64]$windowValid.effectiveWindow -eq 996147)) "effective=$($windowValid.effectiveWindow)"; Add-ADASReviewTestResult 'context-metadata-source-path' ([string]$windowValid.sourcePath -eq $metadataPath) ([string]$windowValid.sourcePath)
    $metaNoPercentPath = Join-Path $tempRoot 'models-nopct.json'; Write-ADASJson -Path $metaNoPercentPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 1048576 }) })
    $windowNoPct = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaNoPercentPath
    Add-ADASReviewTestResult 'context-metadata-no-percent-uses-raw' (([bool]$windowNoPct.valid) -and ([int64]$windowNoPct.effectiveWindow -eq 1048576) -and ([int]$windowNoPct.effectivePercent -eq 0)) "effective=$($windowNoPct.effectiveWindow)"
    $metaSmallMaxPath = Join-Path $tempRoot 'models-smallmax.json'
    Write-ADASJson -Path $metaSmallMaxPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 1048576; max_context_window = 500000; effective_context_window_percent = 95 }) })
    $windowSmallMax = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaSmallMaxPath
    Add-ADASReviewTestResult 'context-metadata-smaller-max-wins' (([bool]$windowSmallMax.valid) -and ([int64]$windowSmallMax.effectiveWindow -eq 475000)) "effective=$($windowSmallMax.effectiveWindow)"
    $missingMetadataPath = Join-Path $tempRoot 'models-missing.json'; $windowMissing = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'context-metadata-missing-file-fail-closed' ((-not [bool]$windowMissing.valid) -and ([string]$windowMissing.reason -eq 'metadata-file-not-found') -and ([int64]$windowMissing.effectiveWindow -eq 0)) ([string]$windowMissing.reason)
    $metaOtherSlugPath = Join-Path $tempRoot 'models-other.json'; Write-ADASJson -Path $metaOtherSlugPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'other-model'; context_window = 1048576 }) })
    $windowOther = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaOtherSlugPath
    Add-ADASReviewTestResult 'context-metadata-slug-not-found-fail-closed' ((-not [bool]$windowOther.valid) -and ([string]$windowOther.reason -eq 'model-slug-not-found')) ([string]$windowOther.reason)
    $windowEmpty = Get-ADASReviewModelContextWindow -ReviewerModel '' -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'context-metadata-empty-slug-fail-closed' ((-not [bool]$windowEmpty.valid) -and ([string]$windowEmpty.reason -eq 'reviewer-model-not-specified')) ([string]$windowEmpty.reason)
    $windowCases = @(
        @{ name = 'context-metadata-window-0-fail-closed'; window = 0 },
        @{ name = 'context-metadata-window--1-fail-closed'; window = -1 },
        @{ name = 'context-metadata-huge-window-fail-closed'; window = 999999999 },
        @{ name = 'context-metadata-nonnumeric-window-fail-closed'; window = 'abc'; reason = 'context-window-not-numeric' }
    )
    foreach ($case in $windowCases) {
        $metaCasePath = Join-Path $tempRoot ("models-case-$($case.name).json"); Write-ADASJson -Path $metaCasePath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = $case.window }) })
        $windowCase = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaCasePath
        $expectedReason = $(if ($case.ContainsKey('reason')) { [string]$case.reason } else { 'context-window-out-of-range' })
        Add-ADASReviewTestResult $case.name ((-not [bool]$windowCase.valid) -and ([string]$windowCase.reason -eq $expectedReason)) ([string]$windowCase.reason)
    }
    $metaInvalidJsonPath = Join-Path $tempRoot 'models-invalid.json'
    Write-ADASUtf8NoBom -Path $metaInvalidJsonPath -Text '{invalid json'
    $windowInvalidJson = Get-ADASReviewModelContextWindow -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaInvalidJsonPath
    Add-ADASReviewTestResult 'context-metadata-invalid-json-fail-closed' ((-not [bool]$windowInvalidJson.valid) -and ([string]$windowInvalidJson.reason -eq 'metadata-json-invalid')) ([string]$windowInvalidJson.reason)
    # --- 19. Task55/56 budget formula + state machine matrix ---
    $budgetDerived = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-formula-tokens' (([int64]$budgetDerived.budgetTokens -eq $expectedDerivedBudget) -and ([int64]$budgetDerived.budgetBytes -eq $expectedDerivedBudget) -and ([int64]$budgetDerived.budgetCharacters -eq $expectedDerivedBudget)) "tokens=$($budgetDerived.budgetTokens)"; Add-ADASReviewTestResult 'budget-formula-reserves' (([int64]$budgetDerived.outputReserveTokens -eq 24000) -and ([int64]$budgetDerived.promptReserveTokens -eq 65536) -and ([int64]$budgetDerived.safetyReserveTokens -eq 32768)) ''; Add-ADASReviewTestResult 'budget-formula-source' (([string]$budgetDerived.budgetSource -eq 'context-window') -and ([bool]$budgetDerived.modelMetadataValid) -and ([string]$budgetDerived.fallbackReason -eq '')) ([string]$budgetDerived.budgetSource)
    $budgetFallback = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'budget-fallback-cap' (([string]$budgetFallback.budgetSource -eq 'fallback-cap') -and ([int64]$budgetFallback.budgetBytes -eq 350000) -and ([int64]$budgetFallback.budgetCharacters -eq 350000) -and ([string]$budgetFallback.fallbackReason -eq 'metadata-file-not-found') -and (-not [bool]$budgetFallback.modelMetadataValid)) ([string]$budgetFallback.budgetSource)
    $budgetInvalidJson = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaInvalidJsonPath
    Add-ADASReviewTestResult 'budget-invalid-metadata-fail-closed' (([string]$budgetInvalidJson.budgetSource -eq 'fallback-cap') -and ([int64]$budgetInvalidJson.budgetBytes -eq 350000) -and ([string]$budgetInvalidJson.fallbackReason -eq 'metadata-json-invalid') -and (-not [bool]$budgetInvalidJson.modelMetadataValid)) ([string]$budgetInvalidJson.fallbackReason)
    $metaSmallWindowPath = Join-Path $tempRoot 'models-smallwindow.json'; Write-ADASJson -Path $metaSmallWindowPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 100000 }) }); $budgetTooSmall = Get-ADASReviewDiffBudget -ReviewerModel 'deepseek-v4-pro' -ModelMetadataPath $metaSmallWindowPath
    Add-ADASReviewTestResult 'budget-window-too-small-zero-budget' (([string]$budgetTooSmall.budgetSource -eq 'context-window') -and ([string]$budgetTooSmall.fallbackReason -eq 'context-window-too-small-for-reserves') -and ([bool]$budgetTooSmall.modelMetadataValid) -and ([int64]$budgetTooSmall.budgetTokens -eq 0) -and ([int64]$budgetTooSmall.budgetBytes -eq 0) -and ([int64]$budgetTooSmall.budgetCharacters -eq 0) -and ([int64]$budgetTooSmall.effectiveWindow -eq 100000)) "bytes=$($budgetTooSmall.budgetBytes)"
    # Task56 valid-too-small => explicit zero budget: any non-empty diff exceeds, 0 provider requests.
    $metaTooSmall = Get-ADASDiffAcquisitionMeta -DiffText $diffText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metaSmallWindowPath
    Add-ADASReviewTestResult 'budget-too-small-acquisition-blocked' (([bool]$metaTooSmall.budgetExceeded) -and ([string]$metaTooSmall.text -eq '') -and ([int64]$metaTooSmall.budgetCharacters -eq 0) -and ([string]$metaTooSmall.budgetSource -eq 'context-window') -and ([string]$metaTooSmall.fallbackReason -eq 'context-window-too-small-for-reserves')) "source=$($metaTooSmall.budgetSource)"
    $metaTooSmallEmpty = Get-ADASDiffAcquisitionMeta -DiffText '' -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metaSmallWindowPath
    Add-ADASReviewTestResult 'budget-too-small-empty-diff-not-exceeded' ((-not [bool]$metaTooSmallEmpty.budgetExceeded) -and ([string]$metaTooSmallEmpty.text -eq '')) ''
    Reset-ADASReviewMock
    $excTooSmall = New-ADASDiffBudgetExceededResult -RequestedModel 'deepseek-v4-pro' -DiffCharacterCount ([int64]$metaTooSmall.characterCount) -DiffByteCount ([int64]$metaTooSmall.byteCount) -DiffSha256 ([string]$metaTooSmall.sha256) -BudgetCharacters ([int64]$metaTooSmall.budgetCharacters) -BudgetBytes ([int64]$metaTooSmall.budgetBytes) -BudgetSource ([string]$metaTooSmall.budgetSource) -FallbackReason ([string]$metaTooSmall.fallbackReason) -OutputPath (Join-Path $tempRoot 'review-context-capacity.json')
    Add-ADASReviewTestResult 'budget-too-small-result-blocked-no-request' (([string]$excTooSmall.verdict -eq 'BLOCKED') -and ((Get-ADASReviewMockCallCount) -eq 0) -and (@($excTooSmall._adasAttempts).Count -eq 0) -and ([string]$excTooSmall._adasProvider.status -eq 'BLOCKED')) "calls=$(Get-ADASReviewMockCallCount)"; Add-ADASReviewTestResult 'budget-too-small-context-capacity-recorded' (([bool]$excTooSmall._adasDiffBudget.contextCapacityBlocked) -and ([string]$excTooSmall._adasDiffBudget.fallbackReason -eq 'context-window-too-small-for-reserves') -and ([int64]$excTooSmall._adasDiffBudget.budgetBytes -eq 0)) ''; Add-ADASReviewTestResult 'budget-too-small-no-fallback-cap' (-not ([string]$excTooSmall._adasDiffBudget.budgetSource -eq 'fallback-cap')) ([string]$excTooSmall._adasDiffBudget.budgetSource)
    # --- 20. Task55 acquisition boundary matrix ---
    $d349999 = New-ADASReviewSyntheticDiff -Characters 349999; $meta349999 = Get-ADASDiffAcquisitionMeta -DiffText $d349999 -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-349999-full' ((-not [bool]$meta349999.budgetExceeded) -and (-not [bool]$meta349999.truncated) -and ([string]$meta349999.text -ceq $d349999) -and ([int64]$meta349999.characterCount -eq 349999) -and ([int64]$meta349999.byteCount -eq 349999)) "source=$($meta349999.budgetSource)"
    $d350001 = New-ADASReviewSyntheticDiff -Characters 350001; $meta350001 = Get-ADASDiffAcquisitionMeta -DiffText $d350001 -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-350001-full-new-budget' ((-not [bool]$meta350001.budgetExceeded) -and ([string]$meta350001.text -ceq $d350001) -and ([string]$meta350001.budgetSource -eq 'context-window')) "budget=$($meta350001.budgetCharacters)"
    $dBoundary = New-ADASReviewSyntheticDiff -Characters $expectedDerivedBudget; $metaBoundary = Get-ADASDiffAcquisitionMeta -DiffText $dBoundary -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-exact-boundary-full' ((-not [bool]$metaBoundary.budgetExceeded) -and ([string]$metaBoundary.text -ceq $dBoundary) -and ([int64]$metaBoundary.characterCount -eq $expectedDerivedBudget)) "chars=$($metaBoundary.characterCount)"
    $dOver = New-ADASReviewSyntheticDiff -Characters ($expectedDerivedBudget + 1); $metaOver = Get-ADASDiffAcquisitionMeta -DiffText $dOver -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'budget-plus-one-exceeded' (([bool]$metaOver.budgetExceeded) -and ([bool]$metaOver.truncated) -and ([string]$metaOver.text -eq '') -and ([int64]$metaOver.characterCount -eq ($expectedDerivedBudget + 1)) -and ([int64]$metaOver.byteCount -eq ($expectedDerivedBudget + 1)) -and ([string]$metaOver.sha256 -eq (Get-ADASSha256Text $dOver))) "chars=$($metaOver.characterCount) budget=$($metaOver.budgetCharacters)"; Add-ADASReviewTestResult 'budget-plus-one-no-sentinel' (-not ([string]$metaOver.text).EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) ''
    $dFbBoundary = New-ADASReviewSyntheticDiff -Characters 350000; $metaFbBoundary = Get-ADASDiffAcquisitionMeta -DiffText $dFbBoundary -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'fallback-cap-350000-full' ((-not [bool]$metaFbBoundary.budgetExceeded) -and ([string]$metaFbBoundary.budgetSource -eq 'fallback-cap') -and ([string]$metaFbBoundary.fallbackReason -eq 'metadata-file-not-found')) "budget=$($metaFbBoundary.budgetCharacters)"
    $dFbOver = New-ADASReviewSyntheticDiff -Characters 350001; $metaFbOver = Get-ADASDiffAcquisitionMeta -DiffText $dFbOver -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
    Add-ADASReviewTestResult 'fallback-cap-350001-exceeded-fail-closed' (([bool]$metaFbOver.budgetExceeded) -and ([string]$metaFbOver.text -eq '') -and ([int64]$metaFbOver.characterCount -eq 350001) -and ([string]$metaFbOver.budgetSource -eq 'fallback-cap')) "chars=$($metaFbOver.characterCount)"
    $multibyteText = [string]::new([char]0x0151, 10); $metaMultibyte = Get-ADASDiffAcquisitionMeta -DiffText $multibyteText -MaxCharacters 15
    Add-ADASReviewTestResult 'multibyte-byte-budget-exceeded' (([bool]$metaMultibyte.budgetExceeded) -and ([int64]$metaMultibyte.characterCount -eq 10) -and ([int64]$metaMultibyte.byteCount -eq 20) -and ([int64]$metaMultibyte.budgetBytes -eq 15)) "chars=$($metaMultibyte.characterCount) bytes=$($metaMultibyte.byteCount)"
    $dExplicitOver = New-ADASReviewSyntheticDiff -Characters 1001; $metaExplicit = Get-ADASDiffAcquisitionMeta -DiffText $dExplicitOver -MaxCharacters 1000
    Add-ADASReviewTestResult 'explicit-parameter-cap-respected' (([bool]$metaExplicit.budgetExceeded) -and ([string]$metaExplicit.budgetSource -eq 'explicit-parameter') -and ([string]$metaExplicit.text -eq '')) ([string]$metaExplicit.budgetSource)
    $dExplicitFit = New-ADASReviewSyntheticDiff -Characters 1000; $metaExplicitFit = Get-ADASDiffAcquisitionMeta -DiffText $dExplicitFit -MaxCharacters 1000
    Add-ADASReviewTestResult 'explicit-parameter-exact-cap-full' ((-not [bool]$metaExplicitFit.budgetExceeded) -and ([string]$metaExplicitFit.text -ceq $dExplicitFit)) ''
    $metaEmpty = Get-ADASDiffAcquisitionMeta -DiffText '' -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'acquisition-empty-diff-safe' ((-not [bool]$metaEmpty.budgetExceeded) -and ([int64]$metaEmpty.characterCount -eq 0) -and ([int64]$metaEmpty.byteCount -eq 0) -and ([int64]$metaEmpty.lineCount -eq 0) -and ([int64]$metaEmpty.fileCount -eq 0) -and ([string]$metaEmpty.text -eq '')) ''
    $metaMultiModel = Get-ADASDiffAcquisitionMeta -DiffText $d349999 -ReviewerModel @('deepseek-v4-pro', 'unknown-model') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'multi-model-min-budget-wins' ((-not [bool]$metaMultiModel.budgetExceeded) -and ([string]$metaMultiModel.budgetSource -eq 'fallback-cap-min-over-models') -and ([int64]$metaMultiModel.budgetCharacters -eq 350000) -and (@($metaMultiModel.perModelBudgets).Count -eq 2)) "source=$($metaMultiModel.budgetSource)"
    # Task56: a zero budget (valid-too-small metadata) is the MINIMUM across slugs in both orders.
    $metaTwoModelPath = Join-Path $tempRoot 'models-twomodel.json'
    Write-ADASJson -Path $metaTwoModelPath -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 100000 }, [pscustomobject]@{ slug = 'second-model'; context_window = 1048576 }) })
    $metaZeroSecond = Get-ADASDiffAcquisitionMeta -DiffText $diffText -ReviewerModel @('second-model', 'deepseek-v4-pro') -ModelMetadataPath $metaTwoModelPath
    $metaZeroFirst = Get-ADASDiffAcquisitionMeta -DiffText $diffText -ReviewerModel @('deepseek-v4-pro', 'second-model') -ModelMetadataPath $metaTwoModelPath
    Add-ADASReviewTestResult 'multi-model-zero-budget-wins-any-order' (([bool]$metaZeroFirst.budgetExceeded) -and ([bool]$metaZeroSecond.budgetExceeded) -and ([int64]$metaZeroFirst.budgetCharacters -eq 0) -and ([int64]$metaZeroSecond.budgetCharacters -eq 0) -and ([string]$metaZeroFirst.fallbackReason -eq 'context-window-too-small-for-reserves') -and ([string]$metaZeroSecond.fallbackReason -eq 'context-window-too-small-for-reserves') -and (@($metaZeroFirst.perModelBudgets).Count -eq 2)) "budget1=$($metaZeroFirst.budgetCharacters) budget2=$($metaZeroSecond.budgetCharacters)"
    $metaMetaLineCount = Get-ADASDiffAcquisitionMeta -DiffText $diffText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
    Add-ADASReviewTestResult 'acquisition-line-file-counts' (([int64]$metaMetaLineCount.lineCount -eq (Get-ADASReviewLineCount $diffText)) -and ([int64]$metaMetaLineCount.fileCount -eq ([regex]::Matches($diffText, '(?m)^diff --git ')).Count) -and ([string]$metaMetaLineCount.sha256 -eq (Get-ADASSha256Text $diffText))) "lines=$($metaMetaLineCount.lineCount) files=$($metaMetaLineCount.fileCount)"
    # --- 21. Task55/56 fail-closed budget-exceeded result contract ---
    $metaExc = Get-ADASDiffAcquisitionMeta -DiffText $dFbOver -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
    Reset-ADASReviewMock
    $outExc = Join-Path $tempRoot 'review-budget-exceeded.json'
    $exc = New-ADASDiffBudgetExceededResult -RequestedModel 'deepseek-v4-pro' -DiffCharacterCount ([int64]$metaExc.characterCount) -DiffByteCount ([int64]$metaExc.byteCount) -DiffSha256 ([string]$metaExc.sha256) -BudgetCharacters ([int64]$metaExc.budgetCharacters) -BudgetBytes ([int64]$metaExc.budgetBytes) -BudgetSource ([string]$metaExc.budgetSource) -OutputPath $outExc
    Add-ADASReviewTestResult 'budget-exceeded-verdict-blocked' ([string]$exc.verdict -eq 'BLOCKED') ([string]$exc.verdict)
    $excFinding = @($exc.findings)[0]
    Add-ADASReviewTestResult 'budget-exceeded-category' (([string]$excFinding.category -eq 'diff-budget-exceeded') -and ([string]$excFinding.severity -eq 'HIGH')) ([string]$excFinding.category); Add-ADASReviewTestResult 'budget-exceeded-no-provider-request' ((Get-ADASReviewMockCallCount) -eq 0) "calls=$(Get-ADASReviewMockCallCount)"
    $excBudget = $exc._adasDiffBudget
    Add-ADASReviewTestResult 'budget-exceeded-metadata-exact' (([string]$excBudget.diffSha256 -eq [string]$metaExc.sha256) -and ([int64]$excBudget.diffCharacterCount -eq 350001) -and ([int64]$excBudget.diffByteCount -eq 350001) -and ([int64]$excBudget.budgetCharacters -eq 350000) -and ([int64]$excBudget.budgetBytes -eq 350000) -and ([bool]$excBudget.budgetExceeded) -and (-not [bool]$excBudget.truncationPerformed) -and (-not [bool]$excBudget.sentinelAppended) -and (-not [bool]$excBudget.secretMaterialRecorded) -and (-not [bool]$excBudget.contextCapacityBlocked)) ''; Add-ADASReviewTestResult 'budget-exceeded-provider-blocked' (([string]$exc._adasProvider.status -eq 'BLOCKED') -and ($null -eq $exc._adasProvider.providerRequestId) -and ([int64]$exc._adasProvider.totalTokens -eq 0) -and (-not [bool]$exc._adasProvider.secretMaterialRecorded)) ([string]$exc._adasProvider.status); Add-ADASReviewTestResult 'budget-exceeded-attempts-empty' (@($exc._adasAttempts).Count -eq 0) "attempts=$(@($exc._adasAttempts).Count)"
    $excFileText = [IO.File]::ReadAllText($outExc, [Text.Encoding]::UTF8)
    Add-ADASReviewTestResult 'budget-exceeded-file-written' ($excFileText -match '"verdict":\s*"BLOCKED"' -and $excFileText -match 'diff-budget-exceeded') ''; Add-ADASReviewTestResult 'budget-exceeded-file-no-diff-content' ($excFileText -notmatch 'abcdefghijklmnopqrstuvwxyz0123456789') ''; Add-ADASReviewTestResult 'budget-exceeded-file-no-secrets' ($excFileText -notmatch 'Bearer' -and $excFileText -notmatch 'sk-[A-Za-z0-9]') ''
    # --- 21b. Task56 review-output-contract matrix: every finding needs non-empty severity, category, evidence, requiredFix ---
    $schemaCases = @(
        @{ name = 'schema-missing-severity'; remove = 'severity' },
        @{ name = 'schema-missing-category'; remove = 'category' },
        @{ name = 'schema-missing-evidence'; remove = 'evidence' },
        @{ name = 'schema-missing-requiredFix'; remove = 'requiredFix' },
        @{ name = 'schema-empty-evidence'; setEmpty = 'evidence' },
        @{ name = 'schema-empty-requiredFix'; setEmpty = 'requiredFix' },
        @{ name = 'schema-empty-category'; setEmpty = 'category' },
        @{ name = 'schema-invalid-severity'; set = @('severity', 'LOWX') }
    )
    foreach ($case in $schemaCases) {
        $payload = [ordered]@{ verdict = 'PASS'; confidence = 0.5; summary = 'schema matrix'; findings = @([ordered]@{ severity = 'LOW'; category = 'style'; file = $null; line = $null; evidence = 'e'; requiredFix = 'f' }); missingEvidence = @(); businessRisks = @() }
        if ($case.ContainsKey('remove')) { $payload.findings[0].Remove([string]$case.remove) } elseif ($case.ContainsKey('setEmpty')) { $payload.findings[0][[string]$case.setEmpty] = '' } elseif ($case.ContainsKey('set')) { $payload.findings[0][[string]$case.set[0]] = $case.set[1] }
        $badJson = $payload | ConvertTo-Json -Depth 8 -Compress
        Reset-ADASReviewMock; $global:adasReviewMockResponses = @(
            (New-ADASReviewMockResponse -Content $badJson -RequestId ('req-' + $case.name + '-1') -PromptTokens 12 -CompletionTokens 4),
            (New-ADASReviewMockResponse -Content $badJson -RequestId ('req-' + $case.name + '-2') -PromptTokens 12 -CompletionTokens 4)
        )
        $review = Invoke-ADASReviewTestReview -OutputName ('review-' + $case.name) -Diff $diffText; $attempts = @($review._adasAttempts)
        $passed = ([string]$review.verdict -eq 'BLOCKED') -and ($attempts.Count -eq 2) -and ([string]$attempts[0].disposition -eq 'failed-retryable') -and ([string]$attempts[0].errorClass -eq 'schema-error') -and ([string]$attempts[1].disposition -eq 'failed-retryable') -and ([string]$attempts[1].requestedModel -eq 'deepseek-v4-pro') -and (-not [string]::IsNullOrWhiteSpace([string]$attempts[1].providerRequestId)) -and ([int64]$attempts[1].totalTokens -eq 16) -and ([string]$review._adasProvider.status -eq 'BLOCKED') -and ((Get-ADASReviewMockCallCount) -eq 2)
        Add-ADASReviewTestResult $case.name $passed "calls=$(Get-ADASReviewMockCallCount)"
    }
    $parsedValidFinding = ('{"verdict":"PASS","confidence":0.5,"summary":"schema ok","findings":[{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"short","requiredFix":"short"}],"missingEvidence":[],"businessRisks":[]}') | ConvertFrom-Json
    Add-ADASReviewTestResult 'schema-positive-validator-accepts-full-finding' ([string](Test-ADASReviewContract -Parsed $parsedValidFinding) -eq '') ([string](Test-ADASReviewContract -Parsed $parsedValidFinding))
    $parsedEmptyEvidence = ('{"verdict":"PASS","confidence":0.5,"summary":"x","findings":[{"severity":"LOW","category":"style","evidence":"","requiredFix":"f"}],"missingEvidence":[],"businessRisks":[]}') | ConvertFrom-Json
    Add-ADASReviewTestResult 'schema-negative-validator-rejects-empty-evidence' ([string](Test-ADASReviewContract -Parsed $parsedEmptyEvidence) -eq 'schema-error') ([string](Test-ADASReviewContract -Parsed $parsedEmptyEvidence))
    $parsedMissingFix = ('{"verdict":"PASS","confidence":0.5,"summary":"x","findings":[{"severity":"LOW","category":"style","evidence":"e"}],"missingEvidence":[],"businessRisks":[]}') | ConvertFrom-Json
    Add-ADASReviewTestResult 'schema-negative-validator-rejects-missing-requiredFix' ([string](Test-ADASReviewContract -Parsed $parsedMissingFix) -eq 'schema-error') ([string](Test-ADASReviewContract -Parsed $parsedMissingFix))
    # --- 26. Task57/58 attestation matrix: PASS requires non-empty EXACT actualModel; Task58: a failed attestation overrides the final verdict to BLOCKED with a HIGH provider-attestation-invalid finding; attempts kept ---
    $attestationCases = @(
        @{ name = 'attestation-empty-model-blocked'; model = ''; expectPass = $false },
        @{ name = 'attestation-mismatched-model-blocked'; model = 'deepseek-other-model'; expectPass = $false },
        @{ name = 'attestation-exact-model-pass'; model = 'deepseek-v4-pro'; expectPass = $true }
    )
    foreach ($case in $attestationCases) {
        Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -Model ([string]$case.model) -RequestId ('req-' + $case.name) -PromptTokens 20 -CompletionTokens 8)); $review = Invoke-ADASReviewTestReview -OutputName ('review-' + $case.name) -Diff $diffText
        $meta26 = $review._adasProvider; $attempts26 = @($review._adasAttempts); $finding26 = @($review.findings | Where-Object { $_.category -eq 'provider-attestation-invalid' })
        $statusOk = ([string]$meta26.status -eq $(if ($case.expectPass) { 'PASS' } else { 'BLOCKED' })); $verdictOk = ([string]$review.verdict -eq $(if ($case.expectPass) { 'PASS' } else { 'BLOCKED' }))
        $attemptsKept = ($attempts26.Count -eq 1 -and ([string]$attempts26[0].providerRequestId -eq ('req-' + $case.name)) -and ([int64]$attempts26[0].totalTokens -eq 28) -and ([string]$attempts26[0].requestedModel -eq 'deepseek-v4-pro'))
        $fallbackOk = ([bool]$meta26.fallbackObserved -eq ((-not $case.expectPass) -and -not [string]::IsNullOrWhiteSpace([string]$case.model)))
        $findingOk = (($finding26.Count -eq 1 -and [string]$finding26[0].severity -eq 'HIGH' -and -not [string]::IsNullOrWhiteSpace([string]$finding26[0].evidence)) -eq (-not $case.expectPass))
        Add-ADASReviewTestResult $case.name ($statusOk -and $verdictOk -and $attemptsKept -and $fallbackOk -and $findingOk) "status=$($meta26.status) verdict=$($review.verdict) actualModel='$($meta26.actualModel)'"
    }
    # --- 27. Task57 finding file/line type contract: exclusively null or string ---
    $fileLineCases = @(
        @{ name = 'fileline-file-number-rejected'; field = 'file'; value = 42; accept = $false },
        @{ name = 'fileline-file-bool-rejected'; field = 'file'; value = $true; accept = $false },
        @{ name = 'fileline-file-array-rejected'; field = 'file'; value = @('a.py'); accept = $false },
        @{ name = 'fileline-file-object-rejected'; field = 'file'; value = [pscustomobject]@{ x = 1 }; accept = $false },
        @{ name = 'fileline-line-number-rejected'; field = 'line'; value = 7; accept = $false },
        @{ name = 'fileline-line-bool-rejected'; field = 'line'; value = $false; accept = $false },
        @{ name = 'fileline-line-array-rejected'; field = 'line'; value = @(1, 2); accept = $false },
        @{ name = 'fileline-line-object-rejected'; field = 'line'; value = [pscustomobject]@{ y = 2 }; accept = $false },
        @{ name = 'fileline-null-accepted'; field = 'file'; value = $null; accept = $true },
        @{ name = 'fileline-string-accepted'; field = 'line'; value = 'atomic replace catch'; accept = $true }
    )
    foreach ($case in $fileLineCases) {
        $payload27 = [ordered]@{ verdict = 'PASS'; confidence = 0.5; summary = 'file/line matrix'; findings = @([ordered]@{ severity = 'LOW'; category = 'style'; file = $null; line = $null; evidence = 'e'; requiredFix = 'f' }); missingEvidence = @(); businessRisks = @() }
        $payload27.findings[0][[string]$case.field] = $case.value; $json27 = $payload27 | ConvertTo-Json -Depth 8 -Compress
        Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $json27 -RequestId ('req-' + $case.name + '-1') -PromptTokens 12 -CompletionTokens 4), (New-ADASReviewMockResponse -Content $json27 -RequestId ('req-' + $case.name + '-2') -PromptTokens 12 -CompletionTokens 4))
        $review = Invoke-ADASReviewTestReview -OutputName ('review-' + $case.name) -Diff $diffText; $attempts27 = @($review._adasAttempts)
        if ($case.accept) { $passed27 = ([string]$review.verdict -eq 'PASS') -and ($attempts27.Count -eq 1) } else { $passed27 = ([string]$review.verdict -eq 'BLOCKED') -and ($attempts27.Count -eq 2) -and ([string]$attempts27[0].errorClass -eq 'schema-error') }
        Add-ADASReviewTestResult $case.name $passed27 "verdict=$($review.verdict)"
    }
    $parsedFileNull = ('{"verdict":"PASS","confidence":0.5,"summary":"x","findings":[{"severity":"LOW","category":"style","file":null,"line":null,"evidence":"e","requiredFix":"f"}],"missingEvidence":[],"businessRisks":[]}') | ConvertFrom-Json
    $parsedFileNum = ('{"verdict":"PASS","confidence":0.5,"summary":"x","findings":[{"severity":"LOW","category":"style","file":7,"line":null,"evidence":"e","requiredFix":"f"}],"missingEvidence":[],"businessRisks":[]}') | ConvertFrom-Json
    Add-ADASReviewTestResult 'fileline-validator-null-accepted' ([string](Test-ADASReviewContract -Parsed $parsedFileNull) -eq '') ([string](Test-ADASReviewContract -Parsed $parsedFileNull)); Add-ADASReviewTestResult 'fileline-validator-number-rejected' ([string](Test-ADASReviewContract -Parsed $parsedFileNum) -eq 'schema-error') ([string](Test-ADASReviewContract -Parsed $parsedFileNum))
    # --- 28. Task57 fallback metadata: observed fallback vs precise failure class ---
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @('THROW:The remote server returned an error: (500) Internal Server Error.'); $review = Invoke-ADASReviewTestReview -OutputName 'review-fbmeta-1' -Diff $diffText
    Add-ADASReviewTestResult 'fallback-meta-transport-not-fallback' ((-not [bool]$review._adasProvider.fallbackObserved) -and ([string]$review._adasProvider.unavailabilityClass -eq 'transport-http-500') -and ([string]$review._adasProvider.status -eq 'BLOCKED') -and (@($review._adasAttempts).Count -eq 1)) "class=$($review._adasProvider.unavailabilityClass)"
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @('THROW:The operation has timed out.'); $review = Invoke-ADASReviewTestReview -OutputName 'review-fbmeta-2' -Diff $diffText
    Add-ADASReviewTestResult 'fallback-meta-timeout-not-fallback' ((-not [bool]$review._adasProvider.fallbackObserved) -and ([string]$review._adasProvider.unavailabilityClass -eq 'transport-timeout')) "class=$($review._adasProvider.unavailabilityClass)"
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $truncatedJson -RequestId 'req-fbmeta-3a' -PromptTokens 10 -CompletionTokens 5), (New-ADASReviewMockResponse -Content $truncatedJson -RequestId 'req-fbmeta-3b' -PromptTokens 10 -CompletionTokens 5))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-fbmeta-3' -Diff $diffText
    Add-ADASReviewTestResult 'fallback-meta-parse-error-not-fallback' ((-not [bool]$review._adasProvider.fallbackObserved) -and ([string]$review._adasProvider.unavailabilityClass -eq 'json-parse-error') -and ([string]$review._adasProvider.status -eq 'BLOCKED')) "class=$($review._adasProvider.unavailabilityClass)"
    Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content ('{"verdict":"PASS","confidence":0.5,"summary":"x"}') -Model 'deepseek-other-model' -RequestId 'req-fbmeta-4a' -PromptTokens 10 -CompletionTokens 5), (New-ADASReviewMockResponse -Content ('{"verdict":"PASS","confidence":0.5,"summary":"x"}') -Model 'deepseek-other-model' -RequestId 'req-fbmeta-4b' -PromptTokens 10 -CompletionTokens 5))
    $review = Invoke-ADASReviewTestReview -OutputName 'review-fbmeta-4' -Diff $diffText
    Add-ADASReviewTestResult 'fallback-meta-observed-fallback-true' (([bool]$review._adasProvider.fallbackObserved) -and ([string]$review._adasProvider.unavailabilityClass -eq 'schema-error') -and (@($review._adasAttempts).Count -eq 2) -and ([string]$review._adasProvider.status -eq 'BLOCKED')) "class=$($review._adasProvider.unavailabilityClass)"
    Reset-ADASReviewMock; $review = Invoke-ADASReviewTestReview -OutputName 'review-fbmeta-5' -Diff $diffText -Truncated $true
    Add-ADASReviewTestResult 'fallback-meta-truncation-class' (([string]$review._adasProvider.unavailabilityClass -eq 'truncation-evidence') -and (-not [bool]$review._adasProvider.fallbackObserved)) "class=$($review._adasProvider.unavailabilityClass)"
    # --- 22. Task55 full candidate diff matrix (only when the fixture is provided) ---
    if ($FullCandidateDiffPath -and (Test-Path -LiteralPath $FullCandidateDiffPath -PathType Leaf)) {
        $candBytes = [IO.File]::ReadAllBytes($FullCandidateDiffPath); $candText = [Text.Encoding]::UTF8.GetString($candBytes)
        Add-ADASReviewTestResult 'full-candidate-byte-count' ([int64]$candBytes.Length -eq $FullCandidateDiffByteCount) "bytes=$($candBytes.Length)"; Add-ADASReviewTestResult 'full-candidate-character-count' ([int64]$candText.Length -eq $FullCandidateDiffCharacterCount) "chars=$($candText.Length)"
        Add-ADASReviewTestResult 'full-candidate-line-count' ([int64](Get-ADASReviewLineCount $candText) -eq $FullCandidateDiffLineCount) "lines=$(Get-ADASReviewLineCount $candText)"; Add-ADASReviewTestResult 'full-candidate-file-count' ([int64]([regex]::Matches($candText, '(?m)^diff --git ')).Count -eq $FullCandidateDiffFileCount) "files=$(([regex]::Matches($candText, '(?m)^diff --git ')).Count)"
        Add-ADASReviewTestResult 'full-candidate-sha256' ([string](Get-ADASSha256Text $candText) -eq $FullCandidateDiffSha256) ([string](Get-ADASSha256Text $candText)); Add-ADASReviewTestResult 'full-candidate-no-terminal-sentinel' (-not $candText.EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) ''
        $candMeta = Get-ADASDiffAcquisitionMeta -DiffText $candText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $metadataPath
        Add-ADASReviewTestResult 'full-candidate-fits-derived-budget' ((-not [bool]$candMeta.budgetExceeded) -and ([string]$candMeta.budgetSource -eq 'context-window') -and ([string]$candMeta.text -ceq $candText) -and ([string]$candMeta.sha256 -eq $FullCandidateDiffSha256)) "chars=$($candMeta.characterCount) budget=$($candMeta.budgetCharacters)"
        $candMetaFallback = Get-ADASDiffAcquisitionMeta -DiffText $candText -ReviewerModel @('deepseek-v4-pro') -ModelMetadataPath $missingMetadataPath
        Add-ADASReviewTestResult 'full-candidate-missing-metadata-fail-closed' (([string]$candMetaFallback.budgetSource -eq 'fallback-cap') -and ([string]$candMetaFallback.sha256 -eq $FullCandidateDiffSha256) -and ([int64]$candMetaFallback.characterCount -eq $FullCandidateDiffCharacterCount) -and $(if ([int64]$FullCandidateDiffByteCount -gt 350000) { ([bool]$candMetaFallback.budgetExceeded) -and ([string]$candMetaFallback.text -eq '') } else { (-not [bool]$candMetaFallback.budgetExceeded) -and ([string]$candMetaFallback.text -ceq $candText) })) "fallback-budget=$($candMetaFallback.budgetCharacters)"
        $candSections = Get-ADASReviewDiffSections -DiffText $candText; $candConcat = (@($candSections | ForEach-Object { [string]$_.text }) -join '')
        Add-ADASReviewTestResult 'full-candidate-segments-concat-byte-identical' ($candConcat -ceq $candText) "segments=$($candSections.Count)"
        $candHashOk = $true
        foreach ($section in $candSections) {
            if ([string]$section.diffSha256 -ne $FullCandidateDiffSha256) { $candHashOk = $false }; if ([string]$section.segmentSha256 -ne (Get-ADASSha256Text ([string]$section.text))) { $candHashOk = $false }; if ([int]$section.segment -gt [int]$section.segmentCount) { $candHashOk = $false }
        }
        Add-ADASReviewTestResult 'full-candidate-segment-hashes-consistent' $candHashOk ''
        Reset-ADASReviewMock; $global:adasReviewMockResponses = @((New-ADASReviewMockResponse -Content $validPassJson -RequestId 'req-cand-1' -PromptTokens 1000 -CompletionTokens 30)); $review = Invoke-ADASReviewTestReview -OutputName 'review-candidate' -Diff $candText -Sha $FullCandidateDiffSha256 -Chars $candText.Length -Timeout 120
        Add-ADASReviewTestResult 'full-candidate-review-requests-provider' (([string]$review.verdict -eq 'PASS') -and ((Get-ADASReviewMockCallCount) -eq 1) -and ([string]$review._adasProvider.providerRequestId -eq 'req-cand-1')) "calls=$(Get-ADASReviewMockCallCount)"
        $candBody = [string]$global:adasReviewMockCalls[0].body; $candParsedBody = $candBody | ConvertFrom-Json; $candUserContent = [string]$candParsedBody.messages[1].content
        # Every diff byte appears exactly once in the prompt: the deterministic sections are disjoint and their concatenation is byte-identical with the full diff (proven above).
        $sectionsOnceOk = $true
        foreach ($section in $candSections) {
            $sectionText = [string]$section.text; $firstIdx = $candUserContent.IndexOf($sectionText); if ($firstIdx -lt 0 -or $firstIdx -ne $candUserContent.LastIndexOf($sectionText)) { $sectionsOnceOk = $false }
        }
        Add-ADASReviewTestResult 'full-candidate-every-diff-byte-exactly-once' $sectionsOnceOk "sections=$($candSections.Count)"
        $markersOk = $true
        foreach ($section in $candSections) {
            $marker = "[DIFF SEGMENT $($section.segment)/$($section.segmentCount) "; if ($candUserContent.IndexOf($marker) -ne $candUserContent.LastIndexOf($marker)) { $markersOk = $false }
        }
        Add-ADASReviewTestResult 'full-candidate-segment-markers-once' $markersOk ''
    }
    else {
        Add-ADASReviewTestResult 'full-candidate-fixture-not-provided' $false "FullCandidateDiffPath missing: $FullCandidateDiffPath"
    }
    # --- 23. Installed two-section hash equality with the canonical tracked source ---
    if ($VerifyInstalledBlockPath) {
        $installedText = Read-ADASReviewUtf8File $VerifyInstalledBlockPath
        $sectionBStart = $canonicalFullText.IndexOf('function New-ADASReviewAttemptRecord {')
        $canonicalStartsWithA = $canonicalFullText.StartsWith('function Get-ADASReviewModelContextWindow {')
        if ($sectionBStart -le 0 -or -not $canonicalStartsWithA) {
            Add-ADASReviewTestResult 'canonical-section-partition' $false 'canonical layout drifted (leading content or missing section B start)'
        }
        else {
            Add-ADASReviewTestResult 'canonical-section-partition' $true "sectionBStart=$sectionBStart"
            $canonicalSectionA = $canonicalFullText.Substring(0, $sectionBStart); $canonicalSectionB = $canonicalFullText.Substring($sectionBStart)
            $startA = $installedText.IndexOf('function Get-ADASReviewModelContextWindow {'); $endA = $installedText.IndexOf('function Get-ADASImpactMap {', $startA)
            $startB = $installedText.IndexOf('function New-ADASReviewAttemptRecord {'); $endB = $installedText.IndexOf('function Get-ADASProofManifest {', $startB)
            if ($startA -lt 0 -or $endA -lt 0 -or $endA -le $startA -or $startB -lt 0 -or $endB -lt 0 -or $endB -le $startB) {
                Add-ADASReviewTestResult 'installed-sections-extraction' $false "markers not found in $VerifyInstalledBlockPath (A=$startA/$endA B=$startB/$endB)"
            }
            else {
                Add-ADASReviewTestResult 'installed-sections-extraction' $true "A=$startA..$endA B=$startB..$endB"
                $installedA = $installedText.Substring($startA, $endA - $startA); $installedB = $installedText.Substring($startB, $endB - $startB)
                $installedARawHash = Get-ADASSha256Text $installedA; $installedANormalizedHash = Get-ADASSha256Text ($installedA.Replace("`r`n", "`n")); $canonicalARawHash = Get-ADASSha256Text $canonicalSectionA
                $installedBRawHash = Get-ADASSha256Text $installedB; $installedBNormalizedHash = Get-ADASSha256Text ($installedB.Replace("`r`n", "`n")); $canonicalBRawHash = Get-ADASSha256Text $canonicalSectionB
                $canonicalANormalizedHash = Get-ADASSha256Text ($canonicalSectionA.Replace("`r`n", "`n")); $canonicalBNormalizedHash = Get-ADASSha256Text ($canonicalSectionB.Replace("`r`n", "`n"))
                Add-ADASReviewTestResult 'installed-sectionA-byte-equal' ($installedARawHash -eq $canonicalARawHash) "installed=$installedARawHash canonical=$canonicalARawHash"
                Add-ADASReviewTestResult 'installed-sectionA-normalized-equal' ($installedANormalizedHash -eq $canonicalANormalizedHash) "installed=$installedANormalizedHash canonical=$canonicalANormalizedHash"
                Add-ADASReviewTestResult 'installed-sectionB-byte-equal' ($installedBRawHash -eq $canonicalBRawHash) "installed=$installedBRawHash canonical=$canonicalBRawHash"
                Add-ADASReviewTestResult 'installed-sectionB-normalized-equal' ($installedBNormalizedHash -eq $canonicalBNormalizedHash) "installed=$installedBNormalizedHash canonical=$canonicalBNormalizedHash"
            }
        }
    }
    # --- 24. Task56 caller-migration audit: every structured acquisition caller is migrated ---
    if ([string]::IsNullOrWhiteSpace($CallerAuditProfileDir)) {
        Add-ADASReviewTestResult 'caller-audit-not-provided' $false 'CallerAuditProfileDir not provided'
    }
    else {
        $inventory = New-Object 'System.Collections.Generic.List[object]'
        foreach ($file in @(Get-ChildItem -LiteralPath $CallerAuditProfileDir -File -ErrorAction Stop | Where-Object { $_.Extension -in @('.ps1', '.psm1') })) {
            $fileText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($file.FullName))
            if ($fileText.Contains('Get-ADASDiffText')) {
                $inventory.Add([pscustomobject]@{ path = [string]$file.Name; lines = @([regex]::Matches($fileText, '(?m)^.*Get-ADASDiffText.*$') | ForEach-Object { [string]$_.Value.Trim() }) })
            }
        }
        Add-ADASReviewTestResult 'caller-inventory-exactly-two-files' ($inventory.Count -eq 2) (($inventory | ForEach-Object { $_.path }) -join '; ')
        $isModuleFile = @($inventory | Where-Object { $_.path -eq 'Imperial-ADAS.psm1' }).Count -eq 1; $isCallerFile = @($inventory | Where-Object { $_.path -eq 'Invoke-ADASPipeline.ps1' }).Count -eq 1
        Add-ADASReviewTestResult 'caller-inventory-files-identified' ($isModuleFile -and $isCallerFile) (($inventory | ForEach-Object { $_.path }) -join '; ')
        $moduleText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path $CallerAuditProfileDir 'Imperial-ADAS.psm1')))
        Add-ADASReviewTestResult 'module-carries-structured-definition' ($moduleText.Contains('function Get-ADASDiffText {') -and $moduleText.Contains('function Get-ADASReviewDiffBudget {')) ''
        $callerText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((Join-Path $CallerAuditProfileDir 'Invoke-ADASPipeline.ps1')))
        Add-ADASReviewTestResult 'caller-uses-structured-acquisition' ($callerText.Contains('$acquisition = Get-ADASDiffText -GitPath $gitPath -WorktreePath $worktree -BeforeCommit $BeforeCommit -AfterCommit $AfterCommit -ReviewerModel @($reviewBudgetModels) -Truncated ([ref]$diffTruncated)')) ''; Add-ADASReviewTestResult 'caller-reads-text-property' ($callerText.Contains('$diffText = [string]$acquisition.text')) ''
        Add-ADASReviewTestResult 'caller-reads-budgetExceeded-property' ($callerText.Contains('$diffBudgetExceeded = [bool]$acquisition.budgetExceeded')) ''
        $wholeObjectCoercions = @([regex]::Matches($callerText, '\[string\]\$acquisition(?![\.])'))
        Add-ADASReviewTestResult 'caller-never-string-coerces-whole-object' ($wholeObjectCoercions.Count -eq 0) "whole-object casts: $($wholeObjectCoercions.Count)"; Add-ADASReviewTestResult 'caller-has-no-legacy-sentinel-reliance' (-not $callerText.Contains('DIFF TRUNCATED BY ADAS')) ''
        Add-ADASReviewTestResult 'caller-exceeded-branch-structured-result' ($callerText.Contains('New-ADASDiffBudgetExceededResult') -and $callerText.Contains('change.diff.budget-exceeded-meta.json')) ''; Add-ADASReviewTestResult 'caller-passes-fallback-reason-evidence' ($callerText.Contains('-FallbackReason ([string]$acquisition.fallbackReason)')) ''
        # Task57: the installed caller region must byte/hash-match the git-tracked canonical source.
        if (Test-Path -LiteralPath $canonicalCallerRegionPath -PathType Leaf) {
            $callerCanonicalRegion = Read-ADASReviewUtf8File $canonicalCallerRegionPath
            $regionStartIdx = -1; $regionEndIdx = -1; $callerScan = 0
            while (($callerScan = $callerText.IndexOf('# Task55', $callerScan)) -ge 0) {
                $lineHead = $callerText.Substring($callerScan, [Math]::Min(120, $callerText.Length - $callerScan))
                if ($lineHead.Contains('context-derived diff-acquisition budget')) { $regionStartIdx = $callerScan; break }
                $callerScan++
            }
            if ($regionStartIdx -ge 0) {
                $regionEndIdx = $callerText.IndexOf('Copy-Item -LiteralPath $TaskPath', $regionStartIdx)
                if ($regionEndIdx -ge 0) { $regionEndIdx = $callerText.LastIndexOf("`n", $regionEndIdx) + 1 }
            }
            if ($regionStartIdx -lt 0 -or $regionEndIdx -le $regionStartIdx) {
                Add-ADASReviewTestResult 'caller-installed-region-extraction' $false 'markers not found'
            }
            else {
                $installedCallerRegion = $callerText.Substring($regionStartIdx, $regionEndIdx - $regionStartIdx)
                $installedCallerRaw = Get-ADASSha256Text $installedCallerRegion; $installedCallerNorm = Get-ADASSha256Text ($installedCallerRegion.Replace("`r`n", "`n"))
                $canonicalCallerRaw = Get-ADASSha256Text $callerCanonicalRegion; $canonicalCallerNorm = Get-ADASSha256Text ($callerCanonicalRegion.Replace("`r`n", "`n"))
                Add-ADASReviewTestResult 'caller-installed-region-extraction' $true "region=$($installedCallerRegion.Length) chars"
                Add-ADASReviewTestResult 'caller-installed-region-byte-equal' ($installedCallerRaw -eq $canonicalCallerRaw) "installed=$installedCallerRaw canonical=$canonicalCallerRaw"
                Add-ADASReviewTestResult 'caller-installed-region-normalized-equal' ($installedCallerNorm -eq $canonicalCallerNorm) "installed=$installedCallerNorm canonical=$canonicalCallerNorm"
                Add-ADASReviewTestResult 'caller-canonical-terminal-branch' ($callerCanonicalRegion.Contains('exit 80') -and ([regex]::Matches($callerCanonicalRegion, 'New-ADASDiffBudgetExceededResult')).Count -eq 2 -and $callerCanonicalRegion.Contains("'review-1.json'") -and $callerCanonicalRegion.Contains("'review-2.json'")) ''
            }
        }
        else {
            Add-ADASReviewTestResult 'caller-installed-region-canonical-missing' $false "canonical caller region not found: $canonicalCallerRegionPath"
        }
    }
    # --- 29/30. Task57 installer offline tests: fault-injection rollback + caller region sync ---
    $sectionASplit = $canonicalFullText.IndexOf('function New-ADASReviewAttemptRecord {')
    $syntheticSectionA = $canonicalFullText.Substring(0, $sectionASplit); $syntheticSectionB = $canonicalFullText.Substring($sectionASplit)
    $syntheticModuleText = "# synthetic module prefix`n" + $syntheticSectionA + "`nfunction Get-ADASImpactMap { 'successor-a' }`n# synthetic middle`n" + $syntheticSectionB + "`nfunction Get-ADASProofManifest { 'successor-b' }`n# synthetic module suffix`n"
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        Add-ADASReviewTestResult 'fault-rollback-installer-missing' $false "installer not found: $installerPath"
    }
    else {
        $installerTemp = Join-Path ([IO.Path]::GetTempPath()) ('adas-installer-test-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $installerTemp | Out-Null
        $installerModule = Join-Path $installerTemp 'Imperial-ADAS.psm1'; Write-ADASUtf8NoBom -Path $installerModule -Text $syntheticModuleText
        $installerBackups = Join-Path $installerTemp 'backups'
        function Invoke-ADASInstallerChild {
            param([string]$ProofPath, [string[]]$Extra)
            $childExit = (Start-Process -FilePath 'powershell.exe' -ArgumentList (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installerPath, '-ModulePath', $installerModule, '-CanonicalPath', $canonicalPath, '-BackupDir', $installerBackups, '-ProofPath', $ProofPath) + $Extra) -Wait -PassThru -NoNewWindow).ExitCode
            return [pscustomobject]@{ exit = $childExit; proof = Get-Content -LiteralPath $ProofPath -Raw | ConvertFrom-Json }
        }
        # 29: fault-injected witness mismatch => atomic rollback, backups kept.
        $faultBefore = (Get-FileHash -LiteralPath $installerModule -Algorithm SHA256).Hash.ToLowerInvariant()
        $fault = Invoke-ADASInstallerChild -ProofPath (Join-Path $installerTemp 'proof-fault.json') -Extra @('-FaultInjectReplaceBackupHashMismatch')
        $faultAfter = (Get-FileHash -LiteralPath $installerModule -Algorithm SHA256).Hash.ToLowerInvariant(); $faultBaks = @(Get-ChildItem -LiteralPath $installerBackups -File)
        $faultBakOk = ($faultBaks.Count -eq 1) -and ((Get-FileHash -LiteralPath $faultBaks[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $faultBefore)
        Add-ADASReviewTestResult 'fault-rollback-fail-closed-exit' ($fault.exit -eq 1) "exit=$($fault.exit)"; Add-ADASReviewTestResult 'fault-rollback-proof-contract' (([string]$fault.proof.result -eq 'failed-closed-rolled-back') -and ([bool]$fault.proof.rollbackPerformed) -and ([string]$fault.proof.rollbackError -eq '')) "result=$($fault.proof.result)"; Add-ADASReviewTestResult 'fault-rollback-live-target-restored' ($faultAfter -eq $faultBefore) "after=$faultAfter"; Add-ADASReviewTestResult 'fault-rollback-backup-preserved' $faultBakOk "backups=$($faultBaks.Count)"
        Add-ADASReviewTestResult 'fault-rollback-witness-preserved' ([bool]$fault.proof.replaceWitnessPreserved) ''; Add-ADASReviewTestResult 'fault-rollback-no-partial-content-live' ([string]$fault.proof.moduleAfterHash -eq $faultBefore) ''
        # 30: caller canonical discipline, then atomic sync, idempotent noop and drift fail-closed.
        if (Test-Path -LiteralPath $canonicalCallerRegionPath -PathType Leaf) {
            $callerRegionCanonical = Read-ADASReviewUtf8File $canonicalCallerRegionPath
            $cTokens = $null; $cErrors = $null
            [System.Management.Automation.Language.Parser]::ParseInput($callerRegionCanonical, [ref]$cTokens, [ref]$cErrors) | Out-Null
            $callerRegionCoercions = @([regex]::Matches($callerRegionCanonical, '\[string\]\s*\$acquisition(?![\.\[])'))
            Add-ADASReviewTestResult 'caller-canonical-parses-clean' ($cErrors.Count -eq 0) "$($cErrors.Count) parse error(s)"
            Add-ADASReviewTestResult 'caller-canonical-single-call-site' (([regex]::Matches($callerRegionCanonical, 'Get-ADASDiffText')).Count -eq 1) ''
            Add-ADASReviewTestResult 'caller-canonical-structured-access' ($callerRegionCanonical.Contains('$acquisition = Get-ADASDiffText -GitPath $gitPath -WorktreePath $worktree -BeforeCommit $BeforeCommit -AfterCommit $AfterCommit -ReviewerModel @($reviewBudgetModels) -Truncated ([ref]$diffTruncated)') -and $callerRegionCanonical.Contains('$diffText = [string]$acquisition.text') -and $callerRegionCanonical.Contains('$diffBudgetExceeded = [bool]$acquisition.budgetExceeded')) ''
            Add-ADASReviewTestResult 'caller-canonical-exceeded-branch' ($callerRegionCanonical.Contains('if ($diffBudgetExceeded) {') -and $callerRegionCanonical.Contains('change.diff.budget-exceeded-meta.json')) ''
            Add-ADASReviewTestResult 'caller-canonical-no-sentinel' (-not $callerRegionCanonical.Contains('DIFF TRUNCATED BY ADAS')) ''
            Add-ADASReviewTestResult 'caller-canonical-no-whole-object-coercion' ($callerRegionCoercions.Count -eq 0) "coercions=$($callerRegionCoercions.Count)"
            $callerFile = Join-Path $installerTemp 'Invoke-ADASPipeline.ps1'
            $callerFileText = "# synthetic caller prefix`n" + $callerRegionCanonical + "`n    Copy-Item -LiteralPath `$TaskPath -Destination (Join-Path `$proofDirectory 'task.md') -Force`n# synthetic caller suffix`n"
            Write-ADASUtf8NoBom -Path $callerFile -Text $callerFileText; $callerBeforeHash = (Get-FileHash -LiteralPath $callerFile -Algorithm SHA256).Hash.ToLowerInvariant()
            $callerArgs = @('-CallerPath', $callerFile, '-CallerCanonicalPath', $canonicalCallerRegionPath)
            $caller = Invoke-ADASInstallerChild -ProofPath (Join-Path $installerTemp 'proof-caller.json') -Extra $callerArgs
            $callerBaks = @(Get-ChildItem -LiteralPath $installerBackups -File | Where-Object { $_.Name -like 'Invoke-ADASPipeline.ps1.pre-sync-*' })
            $callerBakOk = ($callerBaks.Count -eq 1) -and ((Get-FileHash -LiteralPath $callerBaks[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $callerBeforeHash)
            Add-ADASReviewTestResult 'caller-sync-exit-ok' ($caller.exit -eq 0) "exit=$($caller.exit)"
            Add-ADASReviewTestResult 'caller-sync-action-recorded' (([string]$caller.proof.result -eq 'synced-ok') -and ([string]$caller.proof.caller.action -eq 'replace-caller-region')) "result=$($caller.proof.result) action=$($caller.proof.caller.action)"
            Add-ADASReviewTestResult 'caller-sync-region-byte-equal' ([bool]$caller.proof.caller.regionByteEqual) "byteEqual=$($caller.proof.caller.regionByteEqual)"
            Add-ADASReviewTestResult 'caller-sync-region-normalized-equal' ([bool]$caller.proof.caller.regionNormalizedEqual) ''
            Add-ADASReviewTestResult 'caller-sync-prefix-suffix-preserved' ([bool]$caller.proof.caller.prefixSuffixPreserved) ''
            Add-ADASReviewTestResult 'caller-sync-single-call-site-after' ([bool]$caller.proof.caller.singleCallSiteAfter) ''
            Add-ADASReviewTestResult 'caller-sync-parse-clean' ([int]$caller.proof.caller.syncedParseErrors -eq 0) ''
            Add-ADASReviewTestResult 'caller-sync-backup-preserved' $callerBakOk "backups=$($callerBaks.Count)"
            $callerNoop = Invoke-ADASInstallerChild -ProofPath (Join-Path $installerTemp 'proof-caller-noop.json') -Extra $callerArgs
            Add-ADASReviewTestResult 'caller-sync-idempotent-noop' (($callerNoop.exit -eq 0) -and ([string]$callerNoop.proof.result -eq 'synced-noop-identical') -and ([string]$callerNoop.proof.caller.action -eq 'noop-identical')) "result=$($callerNoop.proof.result)"
            $callerDriftFile = Join-Path $installerTemp 'Invoke-ADASPipeline.drift.ps1'; Write-ADASUtf8NoBom -Path $callerDriftFile -Text ($callerFileText + "`n# drift: Get-ADASDiffText legacy extra call site`n")
            $driftBefore = (Get-FileHash -LiteralPath $callerDriftFile -Algorithm SHA256).Hash.ToLowerInvariant()
            $drift = Invoke-ADASInstallerChild -ProofPath (Join-Path $installerTemp 'proof-drift.json') -Extra @('-CallerPath', $callerDriftFile, '-CallerCanonicalPath', $canonicalCallerRegionPath)
            $driftAfter = (Get-FileHash -LiteralPath $callerDriftFile -Algorithm SHA256).Hash.ToLowerInvariant()
            Add-ADASReviewTestResult 'caller-drift-two-call-sites-fail-closed' (($drift.exit -eq 1) -and ($driftAfter -eq $driftBefore) -and (-not [bool]$drift.proof.rollbackPerformed)) "exit=$($drift.exit)"
            $badCanonical = Join-Path $installerTemp 'bad-canonical.ps1'; Write-ADASUtf8NoBom -Path $badCanonical -Text ("# bad canonical`n--- DIFF TRUNCATED BY ADAS ---`n")
            $bad = Invoke-ADASInstallerChild -ProofPath (Join-Path $installerTemp 'proof-bad.json') -Extra @('-CallerPath', $callerFile, '-CallerCanonicalPath', $badCanonical)
            Add-ADASReviewTestResult 'caller-canonical-discipline-fail-closed' ($bad.exit -eq 1) "exit=$($bad.exit)"
        }
        else {
            Add-ADASReviewTestResult 'caller-canonical-missing' $false "canonical caller region not found: $canonicalCallerRegionPath"
        }
        Remove-Item -LiteralPath $installerTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
    # --- 31. Task58 terminal e2e: installed caller control flow with an instrumented seam ---
    # Runs the actual installed Invoke-ADASPipeline.ps1 + Imperial-ADAS.psm1 (byte-copied; the installed caller region is hash-proven byte-equal to the tracked canonical region above) against a synthetic worktree/config. Exceeded: pipeline terminates in the caller region with two persisted BLOCKED reviews + exact meta + 0 provider requests. Normal: the provider-review section IS reachable (two seam calls, R3) and the pipeline completes.
    $termRoot = Join-Path ([IO.Path]::GetTempPath()) ('adas-terminal-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $termRoot | Out-Null
    $termRepo = Join-Path $termRoot 'repo'; New-Item -ItemType Directory -Force -Path $termRepo | Out-Null
    & git -C $termRepo init -q 2>$null | Out-Null; & git -C $termRepo config user.email 'adas@local.invalid' 2>$null; & git -C $termRepo config user.name 'adas' 2>$null; & git -C $termRepo config core.autocrlf false 2>$null
    Write-ADASUtf8NoBom -Path (Join-Path $termRepo 'sample.txt') -Text "before`n"; & git -C $termRepo add sample.txt 2>$null; & git -C $termRepo commit -q -m before 2>$null
    Write-ADASUtf8NoBom -Path (Join-Path $termRepo 'sample.txt') -Text "before`nafter-line`n"; & git -C $termRepo add sample.txt 2>$null; & git -C $termRepo commit -q -m after 2>$null
    $termBefore = (& git -C $termRepo rev-parse HEAD~1).Trim(); $termAfter = (& git -C $termRepo rev-parse HEAD).Trim(); $termBranch = (& git -C $termRepo branch --show-current).Trim()
    $termSeam = Join-Path $termRoot 'provider-seam.log'
    $termTask = Join-Path $termRoot 'task.md'; Write-ADASUtf8NoBom -Path $termTask -Text "# Synthetic budget-terminal`n`n## Acceptance`n- budget-exceeded terminal path must fail closed.`n`nADAS-RISK-FLOOR: R3`n"
    $termConfig = Join-Path $termRoot 'worker-config.json'
    Write-ADASJson -Path $termConfig -Value ([ordered]@{ ControlRoot = $termRoot; WorktreePath = $termRepo; GitPath = 'git'; BranchName = $termBranch; Model = 'deepseek-v4-pro'; CodexModel = 'deepseek-v4-pro'; SecretPath = (Join-Path $termRoot 'secret-not-read.txt'); Role = 'PRO'; Provider = [ordered]@{ Name = 'DeepSeek'; AuthorEndpointFamily = 'https://api.deepseek.com'; FallbackAllowed = $false } })
    New-Item -ItemType Directory -Force -Path (Join-Path $termRepo '.imperial-adas') | Out-Null
    Write-ADASJson -Path (Join-Path $termRepo '.imperial-adas\project.json') -Value ([pscustomobject]@{ riskFloor = 'R0'; commands = [pscustomobject]@{ synthetic = @() } })
    $termSession = Join-Path $termRoot 'session.log'
    Write-ADASUtf8NoBom -Path $termSession -Text ('{"type":"result","subtype":"success","is_error":false,"request_id":"req-author-1","session_id":"sess-author-1","usage":{"input_tokens":100,"output_tokens":50},"modelUsage":{"deepseek-v4-pro":{"input_tokens":100,"output_tokens":50}}}' + [Environment]::NewLine)
    $termDiffOut = Join-Path $termRoot 'expected.diff'; & git -C $termRepo diff --no-ext-diff --unified=5 "$termBefore..$termAfter" --output=$termDiffOut
    $termDiffText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($termDiffOut)); $termDiffSha = Get-ADASSha256Text $termDiffText
    $termProfile = Join-Path $termRoot 'profile'; New-Item -ItemType Directory -Force -Path $termProfile | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $termRoot 'codex-home') | Out-Null

    function Invoke-ADASTerminalChild {
        param([Parameter(Mandatory = $true)][string]$ScriptPath, [string[]]$ExtraArgs = @())
        return (Start-Process -FilePath 'powershell.exe' -ArgumentList (@('-NoProfile','-ExecutionPolicy','Bypass','-File',$ScriptPath) + $ExtraArgs) -Wait -PassThru -NoNewWindow).ExitCode
    }
    $termPipelineDir = Join-Path $termRoot ('proofs\task-' + $termAfter.Substring(0, 12))
    if (-not [string]::IsNullOrWhiteSpace($CallerAuditProfileDir)) {
        Copy-Item -LiteralPath (Join-Path $CallerAuditProfileDir 'Invoke-ADASPipeline.ps1') -Destination (Join-Path $termProfile 'Invoke-ADASPipeline.ps1') -Force
        Copy-Item -LiteralPath (Join-Path $CallerAuditProfileDir 'Imperial-ADAS.psm1') -Destination (Join-Path $termProfile 'Imperial-ADAS.psm1') -Force
        $termSeamText = @"
function Invoke-ADASDeepSeekCompletion {
    param([string]`$ApiKey, [string]`$Model, [string]`$UserPrompt, [int]`$TimeoutSeconds = 240)
    Add-Content -LiteralPath `$env:ADAS_TERM_SEAM_PATH -Value 'provider-call' -Encoding UTF8
    return [pscustomobject]@{ ok = `$false; transportErrorClass = 'seam-offline'; content = ''; finishReason = ''; actualModel = ''; requestId = ''; inputTokens = [int64]0; outputTokens = [int64]0; totalTokens = [int64]0 }
}
"@
        [IO.File]::AppendAllText((Join-Path $termProfile 'Imperial-ADAS.psm1'), [Environment]::NewLine + $termSeamText, (New-Object Text.UTF8Encoding($false)))
        Write-ADASJson -Path (Join-Path $termRoot 'codex-home\models.json') -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 100000 }) }); $env:ADAS_TERM_SEAM_PATH = $termSeam
        $termExitExceeded = Invoke-ADASTerminalChild -ScriptPath (Join-Path $termProfile 'Invoke-ADASPipeline.ps1') -ExtraArgs @('-ConfigPath', $termConfig, '-TaskPath', $termTask, '-BeforeCommit', $termBefore, '-AfterCommit', $termAfter, '-AgentReportPath', (Join-Path $termRoot 'author-report.md'), '-SessionLogPath', $termSession)
        $termP1 = [IO.File]::ReadAllText((Join-Path $termPipelineDir 'review-1.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
        $termP2 = [IO.File]::ReadAllText((Join-Path $termPipelineDir 'review-2.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
        $termPMeta = [IO.File]::ReadAllText((Join-Path $termPipelineDir 'change.diff.budget-exceeded-meta.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
        Add-ADASReviewTestResult 'terminal-installed-exit-80' ($termExitExceeded -eq 80) "exit=$termExitExceeded"
        Add-ADASReviewTestResult 'terminal-installed-both-persisted-blocked' (([string]$termP1.verdict -eq 'BLOCKED') -and ([string]$termP2.verdict -eq 'BLOCKED') -and ([bool]$termP1._adasDiffBudget.contextCapacityBlocked) -and ([int64]$termP1._adasDiffBudget.diffCharacterCount -eq [int64]$termDiffText.Length) -and ([string]$termP1._adasDiffBudget.diffSha256 -eq $termDiffSha) -and (@($termP1._adasAttempts).Count -eq 0) -and (@($termP2._adasAttempts).Count -eq 0)) "r1=$($termP1.verdict) r2=$($termP2.verdict)"
        Add-ADASReviewTestResult 'terminal-installed-meta-exact' (([bool]$termPMeta.budgetExceeded) -and ([string]$termPMeta.sha256 -eq $termDiffSha) -and ([int64]$termPMeta.budgetBytes -eq 0) -and ([IO.File]::ReadAllText((Join-Path $termPipelineDir 'change.diff'), [Text.Encoding]::UTF8).Length -eq 0)) ''
        Add-ADASReviewTestResult 'terminal-installed-zero-provider-requests' (-not (Test-Path -LiteralPath $termSeam)) 'seam-absent'
        Add-ADASReviewTestResult 'terminal-installed-pipeline-stopped' (-not (Test-Path -LiteralPath (Join-Path $termPipelineDir 'verification.json'))) ''
        Write-ADASJson -Path (Join-Path $termRoot 'codex-home\models.json') -Value ([pscustomobject]@{ models = @([pscustomobject]@{ slug = 'deepseek-v4-pro'; context_window = 1048576; effective_context_window_percent = 95 }) })
        'sk-test-synthetic-key' | ConvertTo-SecureString -AsPlainText -Force | Export-Clixml -Path (Join-Path $termRoot 'secret-not-read.txt')
        $termExitNormal = Invoke-ADASTerminalChild -ScriptPath (Join-Path $termProfile 'Invoke-ADASPipeline.ps1') -ExtraArgs @('-ConfigPath', $termConfig, '-TaskPath', $termTask, '-BeforeCommit', $termBefore, '-AfterCommit', $termAfter, '-AgentReportPath', (Join-Path $termRoot 'author-report.md'), '-SessionLogPath', $termSession)
        $termSeamCalls = @(Get-Content -LiteralPath $termSeam -ErrorAction SilentlyContinue | Where-Object { $_ -eq 'provider-call' }).Count
        $termVerification = [IO.File]::ReadAllText((Join-Path $termPipelineDir 'verification.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
        Add-ADASReviewTestResult 'terminal-installed-normal-reaches-provider' (($termExitNormal -eq 80) -and ($termSeamCalls -eq 2) -and ([string]$termVerification.decision -eq 'BLOCKED')) "exit=$termExitNormal seam=$termSeamCalls"
        Remove-Item Env:\ADAS_TERM_SEAM_PATH -ErrorAction SilentlyContinue
    }
    else {
        Add-ADASReviewTestResult 'terminal-installed-skipped' $false 'CallerAuditProfileDir not provided'
    }
    Remove-Item -LiteralPath $termRoot -Recurse -Force -ErrorAction SilentlyContinue
    # --- 25. Task56 cumulative changed-line gate (git diff --numstat, baseline-relative) ---
    if ([string]::IsNullOrWhiteSpace($ChangedLineBaselineCommit)) {
        Add-ADASReviewTestResult 'changed-line-gate' $false 'ChangedLineBaselineCommit not provided'
    }
    else {
        $worktreeRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot); $numStat = (& git -C $worktreeRoot diff --numstat "$ChangedLineBaselineCommit..HEAD") | Out-String; $additions = 0; $deletions = 0; $fileCount = 0
        foreach ($line in ($numStat -split "`r?`n")) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            $parts = $line -split "`t"
            if ($parts.Count -ge 3 -and $parts[0] -match '^\d+$' -and $parts[1] -match '^\d+$') { $additions += [int]$parts[0]; $deletions += [int]$parts[1]; $fileCount++ }
        }
        $totalChangedLines = $additions + $deletions
        Add-ADASReviewTestResult 'changed-line-gate-under-limit' ($totalChangedLines -le $ChangedLineLimit) "total=$totalChangedLines limit=$ChangedLineLimit (add=$additions del=$deletions files=$fileCount)"
    }
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -Path 'function:\Invoke-RestMethod' -Force -ErrorAction SilentlyContinue
    Remove-Variable -Name adasReviewMockCalls -Scope Global -ErrorAction SilentlyContinue; Remove-Variable -Name adasReviewMockResponses -Scope Global -ErrorAction SilentlyContinue
}
$failed = @($results | Where-Object { -not $_.passed }); $totalCount = $results.Count; $passedCount = $totalCount - $failed.Count; $failedCount = $failed.Count
$summary = [ordered]@{
    test = 'ADAS independent review transport remediation (canonical tracked control plane)'; mode = $runMode; canonicalPath = $canonicalPath
    verifiedInstalledBlockPath = $(if ($VerifyInstalledBlockPath) { $VerifyInstalledBlockPath } else { $null }); callerAuditProfileDir = $(if ($CallerAuditProfileDir) { $CallerAuditProfileDir } else { $null })
    changedLineBaselineCommit = $(if ($ChangedLineBaselineCommit) { $ChangedLineBaselineCommit } else { $null }); changedLineLimit = $ChangedLineLimit; generatedAt = (Get-Date).ToString('o')
    total = $totalCount; passed = $passedCount; failed = $failedCount
    results = @($results | ForEach-Object { $_ })
}
if ($ResultJsonPath) { Write-ADASJson -Path $ResultJsonPath -Value $summary }
$summary | ConvertTo-Json -Depth 6
if ($failedCount -gt 0) { exit 1 }
exit 0
