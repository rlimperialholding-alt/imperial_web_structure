function New-ADASReviewAttemptRecord {
    param(
        [Parameter(Mandatory = $true)][int]$Attempt,
        [Parameter(Mandatory = $true)][string]$RequestedModel,
        [Parameter(Mandatory = $true)][string]$Disposition,
        [string]$ErrorClass = '',
        [string]$FinishReason = '',
        [string]$ActualModel = '',
        [string]$RequestId = '',
        [int64]$InputTokens = 0,
        [int64]$OutputTokens = 0,
        [int64]$TotalTokens = 0
    )
    return [pscustomobject]@{
        attempt = $Attempt
        disposition = $Disposition
        errorClass = $ErrorClass
        finishReason = $FinishReason
        requestedModel = $RequestedModel
        actualModel = $ActualModel
        providerRequestId = $(if ($RequestId) { $RequestId } else { $null })
        inputTokens = $InputTokens
        outputTokens = $OutputTokens
        totalTokens = $TotalTokens
        secretMaterialRecorded = $false
        observedAt = (Get-Date).ToUniversalTime().ToString('o')
    }
}

function Get-ADASReviewGateCompact {
    param([Parameter(Mandatory = $true)][object[]]$GateSummaries)
    # Deterministic whitelist projection: gate name/status/summary/findings only.
    # Evidence blobs, long log paths, checkedAt timestamps and redundant metadata never reach the reviewer prompt.
    $compact = @($GateSummaries | ForEach-Object {
        $gateObj = $_
        [pscustomobject]@{
            gate = Get-ADASObjectPropertyInternal $gateObj 'gate' $null
            name = [string](Get-ADASObjectPropertyInternal $gateObj 'name' '')
            status = [string](Get-ADASObjectPropertyInternal $gateObj 'status' '')
            summary = [string](Get-ADASObjectPropertyInternal $gateObj 'summary' '')
            findings = @(Get-ADASObjectPropertyInternal $gateObj 'findings' @() | ForEach-Object { $_ })
        }
    })
    return ,$compact
}

function Get-ADASReviewDiffSections {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$DiffText,
        [int]$MaxSectionCharacters = 60000
    )
    if ($MaxSectionCharacters -lt 4000) { throw "Get-ADASReviewDiffSections: a szekció-korlát ($MaxSectionCharacters) túl kicsi; minimum 4000 karakter." }
    $diffSha256 = Get-ADASSha256Text $DiffText
    if ([string]::IsNullOrEmpty($DiffText)) {
        return ,@([pscustomobject]@{ segment = 1; segmentCount = 1; diffSha256 = $diffSha256; segmentSha256 = Get-ADASSha256Text ''; text = '' })
    }
    $lineStarts = New-Object 'System.Collections.Generic.List[int]'
    $lineStarts.Add(0)
    for ($i = 0; $i -lt $DiffText.Length - 1; $i++) {
        if ($DiffText[$i] -eq "`n") { $lineStarts.Add($i + 1) }
    }
    $fileStarts = New-Object 'System.Collections.Generic.List[int]'
    $hunkStarts = New-Object 'System.Collections.Generic.List[int]'
    foreach ($lineStart in $lineStarts) {
        $headLength = [Math]::Min(11, $DiffText.Length - $lineStart)
        if ($headLength -ge 11 -and $DiffText.Substring($lineStart, 11) -eq 'diff --git ') { $fileStarts.Add($lineStart) }
        elseif ($headLength -ge 3 -and $DiffText.Substring($lineStart, 3) -eq '@@ ') { $hunkStarts.Add($lineStart) }
    }
    # Byte-contiguous deterministic segments: cut at file boundaries, else hunk boundaries, else line boundaries, else a hard cut.
    # The concatenation of all segment texts equals the original DiffText byte-for-byte, so every changed file/hunk is covered exactly once.
    $sections = New-Object 'System.Collections.Generic.List[object]'
    $cursor = 0
    while ($cursor -lt $DiffText.Length) {
        if ($DiffText.Length - $cursor -le $MaxSectionCharacters) {
            $sections.Add([pscustomobject]@{ start = $cursor; length = $DiffText.Length - $cursor })
            break
        }
        $cut = $cursor + $MaxSectionCharacters
        $best = -1
        foreach ($fileStart in $fileStarts) { if ($fileStart -gt $cursor -and $fileStart -le $cut) { $best = $fileStart } }
        if ($best -lt 0) {
            foreach ($hunkStart in $hunkStarts) { if ($hunkStart -gt $cursor -and $hunkStart -le $cut) { $best = $hunkStart } }
        }
        if ($best -lt 0) {
            foreach ($lineStart in $lineStarts) { if ($lineStart -gt $cursor -and $lineStart -le $cut) { $best = $lineStart } }
        }
        if ($best -le $cursor) { $best = $cut }
        $sections.Add([pscustomobject]@{ start = $cursor; length = $best - $cursor })
        $cursor = $best
    }
    $result = New-Object 'System.Collections.Generic.List[object]'
    $count = $sections.Count
    for ($i = 0; $i -lt $count; $i++) {
        $section = $sections[$i]
        $text = $DiffText.Substring([int]$section.start, [int]$section.length)
        $result.Add([pscustomobject]@{
            segment = $i + 1
            segmentCount = $count
            diffSha256 = $diffSha256
            segmentSha256 = Get-ADASSha256Text $text
            text = $text
        })
    }
    return ,@($result | ForEach-Object { $_ })
}

function Invoke-ADASDeepSeekCompletion {
    param(
        [Parameter(Mandatory = $true)][string]$ApiKey,
        [Parameter(Mandatory = $true)][string]$Model,
        [Parameter(Mandatory = $true)][string]$UserPrompt,
        [int]$TimeoutSeconds = 240
    )
    # Single fresh, conversation-independent request: system instruction + compact prompt, mandatory model only, no fallback.
    # No provider-specific thinking/non-thinking parameter is sent because none is documented for the current endpoint/model.
    $body = [ordered]@{
        model = $Model
        messages = @(
            @{ role = 'system'; content = 'You are a strict independent software assurance reviewer. Output valid JSON only.' },
            @{ role = 'user'; content = $UserPrompt }
        )
        temperature = 0
        max_tokens = 24000
        response_format = @{ type = 'json_object' }
    }
    $headers = @{ Authorization = "Bearer $ApiKey" }
    $result = [pscustomobject]@{
        ok = $false
        transportErrorClass = ''
        content = ''
        finishReason = ''
        actualModel = ''
        requestId = ''
        inputTokens = [int64]0
        outputTokens = [int64]0
        totalTokens = [int64]0
    }
    try {
        $response = Invoke-RestMethod -Method Post -Uri 'https://api.deepseek.com/chat/completions' -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ($body | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec $TimeoutSeconds
    }
    catch {
        # Transport/auth/rate-limit/timeout errors are classified and never masked by retries.
        if ($_.Exception.Message -match 'status code does not indicate success:\s*(\d{3})') { $result.transportErrorClass = "http-$($Matches[1])" }
        elseif ($_.Exception.Message -match '\((\d{3})\)') { $result.transportErrorClass = "http-$($Matches[1])" }
        elseif ($_.Exception.Message -match 'timed?\s?out|időtúllépés') { $result.transportErrorClass = 'timeout' }
        else { $result.transportErrorClass = 'network-or-protocol-error' }
        return $result
    }
    $result.ok = $true
    $choices = @(Get-ADASObjectPropertyInternal $response 'choices' @())
    if ($choices.Count -gt 0) {
        $message = Get-ADASObjectPropertyInternal $choices[0] 'message' $null
        $result.content = [string](Get-ADASObjectPropertyInternal $message 'content' '')
        $result.finishReason = [string](Get-ADASObjectPropertyInternal $choices[0] 'finish_reason' '')
    }
    $result.actualModel = [string](Get-ADASObjectPropertyInternal $response 'model' '')
    $result.requestId = [string](Get-ADASObjectPropertyInternal $response 'id' '')
    $usage = Get-ADASObjectPropertyInternal $response 'usage' $null
    $result.inputTokens = [int64](Get-ADASObjectPropertyInternal $usage 'prompt_tokens' 0)
    $result.outputTokens = [int64](Get-ADASObjectPropertyInternal $usage 'completion_tokens' 0)
    $result.totalTokens = [int64](Get-ADASObjectPropertyInternal $usage 'total_tokens' ($result.inputTokens + $result.outputTokens))
    return $result
}

function Test-ADASReviewContract {
    param([Parameter(Mandatory = $true)]$Parsed)
    # Returns '' when the parsed review satisfies the compact output contract; otherwise a technical error class.
    # Truncated JSON is never repaired by guessing; only a fully parsed, complete object can pass.
    if ($null -eq $Parsed) { return 'schema-error' }
    if ($Parsed -isnot [pscustomobject]) { return 'schema-error' }
    foreach ($name in @('verdict','confidence','summary','findings','missingEvidence','businessRisks')) {
        if (-not ($Parsed.PSObject.Properties.Name -contains $name)) { return 'schema-error' }
    }
    $verdict = [string]$Parsed.verdict
    if (@('PASS','BLOCKED') -notcontains $verdict) { return 'schema-error' }
    if ($null -eq $Parsed.confidence -or $Parsed.confidence -is [bool]) { return 'schema-error' }
    $confidence = 0.0
    try { $confidence = [double]$Parsed.confidence } catch { return 'schema-error' }
    if ($confidence -lt 0.0 -or $confidence -gt 1.0) { return 'schema-error' }
    if ([string]::IsNullOrWhiteSpace([string]$Parsed.summary)) { return 'schema-error' }
    $findings = @($Parsed.findings)
    if ($findings.Count -gt 5) { return 'finding-limit-exceeded' }
    foreach ($finding in $findings) {
        if ($finding -isnot [pscustomobject]) { return 'schema-error' }
        foreach ($name in @('severity','category')) {
            if (-not ($finding.PSObject.Properties.Name -contains $name)) { return 'schema-error' }
        }
        if (@('CRITICAL','HIGH','MEDIUM','LOW') -notcontains [string]$finding.severity) { return 'schema-error' }
        if ([string]::IsNullOrWhiteSpace([string]$finding.category)) { return 'schema-error' }
    }
    foreach ($item in @($Parsed.missingEvidence)) { if ($null -eq $item) { return 'schema-error' } }
    foreach ($item in @($Parsed.businessRisks)) { if ($null -eq $item) { return 'schema-error' } }
    return ''
}

function ConvertTo-ADASReviewContractObject {
    param([Parameter(Mandatory = $true)]$Parsed)
    # From the full valid JSON only the schema fields are accepted; everything else is dropped.
    $findings = @($Parsed.findings | ForEach-Object {
        $finding = $_
        $fileValue = $null
        if ($finding.PSObject.Properties.Name -contains 'file' -and $null -ne $finding.file) { $fileValue = [string]$finding.file }
        $lineValue = $null
        if ($finding.PSObject.Properties.Name -contains 'line' -and $null -ne $finding.line) { $lineValue = [string]$finding.line }
        $evidenceValue = ''
        if ($finding.PSObject.Properties.Name -contains 'evidence' -and $null -ne $finding.evidence) { $evidenceValue = [string]$finding.evidence }
        $fixValue = ''
        if ($finding.PSObject.Properties.Name -contains 'requiredFix' -and $null -ne $finding.requiredFix) { $fixValue = [string]$finding.requiredFix }
        [pscustomobject]@{
            severity = [string]$finding.severity
            category = [string]$finding.category
            file = $fileValue
            line = $lineValue
            evidence = $evidenceValue
            requiredFix = $fixValue
        }
    })
    return [pscustomobject]@{
        verdict = [string]$Parsed.verdict
        confidence = [double]$Parsed.confidence
        summary = [string]$Parsed.summary
        findings = $findings
        missingEvidence = @($Parsed.missingEvidence | ForEach-Object { [string]$_ })
        businessRisks = @($Parsed.businessRisks | ForEach-Object { [string]$_ })
    }
}

function New-ADASReviewUnavailableResult {
    param(
        [Parameter(Mandatory = $true)][string]$RequestedModel,
        [Parameter(Mandatory = $true)][string]$Evidence,
        [object[]]$Attempts = @()
    )
    # Fail-closed review-unavailable BLOCKED; attempt records stay audit-ready but never become a PASS attestation.
    $providerMeta = [pscustomobject]@{
        schemaVersion = '1.0'; status = 'BLOCKED'; provider = 'DeepSeek'; endpointFamily = 'https://api.deepseek.com';
        requestedModel = $RequestedModel; actualModel = '';
        providerRequestId = $null; requestIdentifier = ''; requestIdentifierType = 'request_id';
        inputTokens = 0; outputTokens = 0; totalTokens = 0;
        fallbackAllowed = $false; fallbackObserved = $true;
        observedAt = (Get-Date).ToUniversalTime().ToString('o'); secretMaterialRecorded = $false
    }
    return [pscustomobject]@{
        verdict = 'BLOCKED'
        confidence = 0
        summary = 'A független AI-review technikai hiba miatt nem áll rendelkezésre; fail-closed döntés.'
        findings = @(@{ severity = 'HIGH'; category = 'review-unavailable'; file = $null; line = $null; evidence = $Evidence; requiredFix = 'A review-t sikeresen újra kell futtatni.' })
        missingEvidence = @('independent-review')
        businessRisks = @()
        _adasProvider = $providerMeta
        _adasAttempts = @($Attempts | ForEach-Object { $_ })
    }
}

function Invoke-ADASIndependentReview {
    param(
        [Parameter(Mandatory = $true)][string]$ApiKey,
        [Parameter(Mandatory = $true)][string]$Model,
        [Parameter(Mandatory = $true)][string]$TaskText,
        [Parameter(Mandatory = $true)][string]$DiffText,
        [Parameter(Mandatory = $true)]$RiskProfile,
        [Parameter(Mandatory = $true)][object[]]$GateSummaries,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [int]$TimeoutSeconds = 240
    )
    # Coverage preflight: a truncated diff cannot prove full changed-file/hunk coverage; fail closed without any request.
    if ($DiffText -match '--- DIFF TRUNCATED BY ADAS ---') {
        $truncatedResult = New-ADASReviewUnavailableResult -RequestedModel $Model -Attempts @() -Evidence 'A diff szövege ADAS-csonkolt (DIFF TRUNCATED BY ADAS); a teljes changed-file/hunk lefedettség nem bizonyítható, ezért a review kérés nélkül fail-closed BLOCKED.'
        Write-ADASJson -Path $OutputPath -Value $truncatedResult
        return $truncatedResult
    }
    $attempts = New-Object 'System.Collections.Generic.List[object]'
    # Deterministic compact gate projection: name/status/summary/findings only; no evidence blobs, log paths or timestamps.
    $gateJson = (Get-ADASReviewGateCompact -GateSummaries $GateSummaries) | ConvertTo-Json -Depth 8 -Compress
    # Deterministic compact risk projection: level/score/reasons and booleans only; no classifiedAt timestamp.
    $riskJson = ([pscustomobject]@{
        level = [string](Get-ADASObjectPropertyInternal $RiskProfile 'level' 'R0')
        score = [int](Get-ADASObjectPropertyInternal $RiskProfile 'score' 0)
        reasons = @(Get-ADASObjectPropertyInternal $RiskProfile 'reasons' @() | ForEach-Object { [string]$_ })
        reversibility = [string](Get-ADASObjectPropertyInternal $RiskProfile 'reversibility' '')
        externalExposure = [bool](Get-ADASObjectPropertyInternal $RiskProfile 'externalExposure' $false)
        personalDataPossible = [bool](Get-ADASObjectPropertyInternal $RiskProfile 'personalDataPossible' $false)
    }) | ConvertTo-Json -Depth 8 -Compress
    # Task kept in full; diff kept byte-identical in hash-stamped deterministic segments so every changed file/hunk is reviewed exactly once.
    $diffSections = Get-ADASReviewDiffSections -DiffText $DiffText
    $diffSha256 = [string]$diffSections[0].diffSha256
    $sectionCount = $diffSections.Count
    $sectionLines = New-Object 'System.Collections.Generic.List[string]'
    foreach ($section in $diffSections) {
        if ($sectionCount -eq 1) {
            $sectionLines.Add("[DIFF sha256=$diffSha256 - one complete segment]")
        }
        else {
            $sectionLines.Add("[DIFF SEGMENT $($section.segment)/$($section.segmentCount) of diff-sha256=$diffSha256; segment-sha256=$($section.segmentSha256)]")
        }
        $sectionLines.Add([string]$section.text)
        if ($sectionCount -gt 1) { $sectionLines.Add("[END DIFF SEGMENT $($section.segment)]") }
    }
    $diffSectionBlock = $sectionLines -join [Environment]::NewLine
    $prompt = @"
You are an independent adversarial code reviewer. You did not author this change. Review only the task, diff and deterministic evidence below. Do not assume that the author's report is true. Look for functional defects, security flaws, authorization bypasses, data loss, missing tests, business invariant violations, migration/rollback failures, observability gaps and hidden side effects.

Return ONE JSON object and nothing else: no markdown fences, no prose, no reasoning trace, no text outside the JSON. The object must have exactly these fields and no others:
{
  "verdict": "PASS" | "BLOCKED",
  "confidence": 0.0-1.0,
  "summary": "short factual summary, at most 3 sentences",
  "findings": [
    {"severity":"CRITICAL|HIGH|MEDIUM|LOW","category":"string","file":"string or null","line":"string or null","evidence":"one specific short sentence","requiredFix":"one specific short sentence"}
  ],
  "missingEvidence": ["string"],
  "businessRisks": ["string"]
}
Hard output limits: at most 5 findings in total; keep every string field short and specific. With no findings, return an empty findings array.

PASS is allowed only when there is no CRITICAL/HIGH finding and no missing local evidence required for the stated risk level. Unknowns are not PASS.

This independent review is intentionally executed before RemoteCI. Therefore a deterministic gate status of PENDING_CI, and the absence of CodeQL/Semgrep/remote-CI attestation at this pre-CI stage, are expected lifecycle state and MUST NOT by themselves cause a BLOCKED verdict or be listed as missing evidence. RemoteCI, Gate 9 and the owner gate remain fail-closed and will prevent merge/release later. Do not claim release approval. Block only for concrete defects, required local evidence missing beyond the expected remote-CI stage, or other review findings supported by the task/diff/deterministic local evidence.

RISK PROFILE:
$riskJson

DETERMINISTIC GATE SUMMARY:
$gateJson

TASK:
$TaskText

DIFF:
$diffSectionBlock
"@
    $repairReason = ''
    $terminalEvidence = ''
    for ($attemptNumber = 1; $attemptNumber -le 2; $attemptNumber++) {
        $repairHeader = if ($attemptNumber -gt 1) {
            "REPAIR REQUEST: the previous attempt for this exact task and diff was unusable ($repairReason). Produce the complete review now, freshly: output ONLY the single JSON object per the contract below - no prose, no markdown, no reasoning, complete and well-formed.`n`n"
        } else { '' }
        $completion = Invoke-ADASDeepSeekCompletion -ApiKey $ApiKey -Model $Model -UserPrompt ($repairHeader + $prompt) -TimeoutSeconds $TimeoutSeconds
        if (-not $completion.ok) {
            $attempts.Add((New-ADASReviewAttemptRecord -Attempt $attemptNumber -RequestedModel $Model -Disposition 'failed-terminal' -ErrorClass ([string]$completion.transportErrorClass) -ActualModel ([string]$completion.actualModel) -TotalTokens $completion.totalTokens))
            $terminalEvidence = "A DeepSeek hívás transport hibát adott ($($completion.transportErrorClass)); ilyen hibára retry nem engedélyezett."
            break
        }
        $errorClass = ''
        $parsed = $null
        if ([string]::IsNullOrWhiteSpace($completion.content)) {
            $errorClass = 'empty-content'
        }
        elseif ([string]$completion.finishReason -eq 'length') {
            $errorClass = 'finish-reason-length'
        }
        else {
            try { $parsed = $completion.content | ConvertFrom-Json }
            catch { $errorClass = 'json-parse-error' }
            if (-not $errorClass) { $errorClass = Test-ADASReviewContract -Parsed $parsed }
        }
        if ($errorClass) {
            $retryable = @('empty-content','finish-reason-length','json-parse-error','schema-error') -contains $errorClass
            $attempts.Add((New-ADASReviewAttemptRecord -Attempt $attemptNumber -RequestedModel $Model -Disposition $(if ($retryable) { 'failed-retryable' } else { 'failed-terminal' }) -ErrorClass $errorClass -FinishReason ([string]$completion.finishReason) -ActualModel ([string]$completion.actualModel) -RequestId ([string]$completion.requestId) -InputTokens $completion.inputTokens -OutputTokens $completion.outputTokens -TotalTokens $completion.totalTokens))
            if (-not $retryable) {
                $terminalEvidence = "A reviewer kimenete a kimeneti kontraktust sérti ($errorClass); erre az osztályra retry nem engedélyezett."
                break
            }
            if ($attemptNumber -ge 2) {
                $terminalEvidence = "Mindkét reviewer attempt hibás volt (utolsó hibaosztály: $errorClass); fail-closed."
                break
            }
            $repairReason = $errorClass
            continue
        }
        # Provider attestation only from the finally parsed, accepted attempt: its request id, actual/requested model and token counters.
        $fallbackObserved = (-not [string]::IsNullOrWhiteSpace($completion.actualModel) -and $completion.actualModel -ne $Model)
        $attestationPass = (-not [string]::IsNullOrWhiteSpace($completion.requestId) -and $completion.totalTokens -gt 0 -and -not $fallbackObserved)
        $providerMeta = [pscustomobject]@{
            schemaVersion = '1.0'; status = $(if ($attestationPass) { 'PASS' } else { 'BLOCKED' });
            provider = 'DeepSeek'; endpointFamily = 'https://api.deepseek.com'; requestedModel = $Model; actualModel = $completion.actualModel;
            providerRequestId = $(if ($completion.requestId) { $completion.requestId } else { $null }); requestIdentifier = $(if ($completion.requestId) { $completion.requestId } else { '' }); requestIdentifierType = 'request_id';
            inputTokens = $completion.inputTokens; outputTokens = $completion.outputTokens; totalTokens = $completion.totalTokens;
            fallbackAllowed = $false; fallbackObserved = $fallbackObserved;
            observedAt = (Get-Date).ToUniversalTime().ToString('o'); secretMaterialRecorded = $false
        }
        $attempts.Add((New-ADASReviewAttemptRecord -Attempt $attemptNumber -RequestedModel $Model -Disposition 'accepted' -FinishReason ([string]$completion.finishReason) -ActualModel ([string]$completion.actualModel) -RequestId ([string]$completion.requestId) -InputTokens $completion.inputTokens -OutputTokens $completion.outputTokens -TotalTokens $completion.totalTokens))
        $review = ConvertTo-ADASReviewContractObject -Parsed $parsed
        $review | Add-Member -NotePropertyName '_adasProvider' -NotePropertyValue $providerMeta
        $review | Add-Member -NotePropertyName '_adasAttempts' -NotePropertyValue @($attempts | ForEach-Object { $_ })
        Write-ADASJson -Path $OutputPath -Value $review
        return $review
    }
    if ([string]::IsNullOrWhiteSpace($terminalEvidence)) { $terminalEvidence = 'A független review nem készült el; fail-closed.' }
    $fallback = New-ADASReviewUnavailableResult -RequestedModel $Model -Evidence $terminalEvidence -Attempts @($attempts | ForEach-Object { $_ })
    Write-ADASJson -Path $OutputPath -Value $fallback
    return $fallback
}

