function Get-ADASReviewModelContextWindow {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$ReviewerModel, [string]$ModelMetadataPath = '')
    # Task55/56 — local context-window lookup for the requested model slug; reads ONLY the codex models capability manifest; invalid metadata => valid=false + named reason (fail-closed).
    $invalid = [pscustomobject]@{ requestedModel = $ReviewerModel; contextWindow = [int64]0; maxContextWindow = [int64]0; effectivePercent = [int]0; effectiveWindow = [int64]0; sourcePath = ''; valid = $false; reason = '' }
    if ([string]::IsNullOrWhiteSpace($ReviewerModel)) { $invalid.reason = 'reviewer-model-not-specified'; return $invalid }
    $path = $ModelMetadataPath
    if ([string]::IsNullOrWhiteSpace($path)) { $path = Join-Path (Split-Path -Parent $PSScriptRoot) 'codex-home\models.json' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { $invalid.reason = 'metadata-file-not-found'; $invalid.sourcePath = $path; return $invalid }
    try { $manifest = ([IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)) | ConvertFrom-Json }
    catch { $invalid.reason = 'metadata-json-invalid'; $invalid.sourcePath = $path; return $invalid }
    $match = $null
    foreach ($model in @(Get-ADASObjectPropertyInternal $manifest 'models' @())) {
        if ([string](Get-ADASObjectPropertyInternal $model 'slug' '') -eq $ReviewerModel) { $match = $model; break }
    }
    if ($null -eq $match) { $invalid.reason = 'model-slug-not-found'; $invalid.sourcePath = $path; return $invalid }
    $contextWindow = [int64]0
    if (-not [int64]::TryParse([string](Get-ADASObjectPropertyInternal $match 'context_window' ''), [ref]$contextWindow)) {
        $invalid.reason = 'context-window-not-numeric'; $invalid.sourcePath = $path; return $invalid
    }
    # Sanity range: positive and at most 2^28 (256M) tokens; anything else is metadata corruption.
    if ($contextWindow -le 0 -or $contextWindow -gt 268435456) { $invalid.reason = 'context-window-out-of-range'; $invalid.sourcePath = $path; return $invalid }
    $maxWindow = $contextWindow; $maxParsed = [int64]0
    if ([int64]::TryParse([string](Get-ADASObjectPropertyInternal $match 'max_context_window' ''), [ref]$maxParsed) -and $maxParsed -gt 0 -and $maxParsed -lt $maxWindow) { $maxWindow = $maxParsed }
    $percent = [int]0; $hasPercent = $false
    $percentValue = Get-ADASObjectPropertyInternal $match 'effective_context_window_percent' $null
    if ($null -ne $percentValue -and [int]::TryParse([string]$percentValue, [ref]$percent) -and $percent -gt 0 -and $percent -le 100) { $hasPercent = $true }
    $effectiveWindow = $maxWindow
    if ($hasPercent) { $effectiveWindow = [int64][Math]::Floor([double]$maxWindow * [double]$percent / 100.0) }
    return [pscustomobject]@{ requestedModel = $ReviewerModel; contextWindow = $contextWindow; maxContextWindow = $maxWindow; effectivePercent = $(if ($hasPercent) { $percent } else { [int]0 }); effectiveWindow = $effectiveWindow; sourcePath = $path; valid = $true; reason = '' }
}
function Get-ADASReviewDiffBudget {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$ReviewerModel, [string]$ModelMetadataPath = '', [int64]$MaxOutputTokens = 24000, [int64]$PromptReserveTokens = 65536, [int64]$SafetyReserveTokens = 32768, [int64]$FallbackBudgetCharacters = 350000)
    # Task55/56 — conservative diff-input budget: budgetTokens = effectiveWindow - 24,000 (output) - 65,536 (prompt) - 32,768 (safety); budgetBytes = budgetCharacters = budgetTokens. Task56 state machine: budgetTokens>0 => 'context-window'; <=0 => explicit ZERO budget (350,000 fallback FORBIDDEN, context-capacity BLOCKED, 0 provider requests); invalid metadata => legacy fallback cap 350,000.
    $window = Get-ADASReviewModelContextWindow -ReviewerModel $ReviewerModel -ModelMetadataPath $ModelMetadataPath
    $budgetTokens = [int64]0; $budgetValue = [int64]0; $source = 'context-window'; $fallbackReason = ''
    if (-not [bool]$window.valid) {
        $source = 'fallback-cap'
        $fallbackReason = [string]$window.reason
        $budgetValue = [int64]$FallbackBudgetCharacters
    }
    else {
        $budgetTokens = [int64]$window.effectiveWindow - [int64]$MaxOutputTokens - [int64]$PromptReserveTokens - [int64]$SafetyReserveTokens
        if ($budgetTokens -le 0) { $budgetTokens = [int64]0; $fallbackReason = 'context-window-too-small-for-reserves' }
        else { $budgetValue = $budgetTokens }
    }
    return [pscustomobject]@{ requestedModel = $ReviewerModel; contextWindow = [int64]$window.contextWindow; effectiveWindow = [int64]$window.effectiveWindow; outputReserveTokens = [int64]$MaxOutputTokens; promptReserveTokens = [int64]$PromptReserveTokens; safetyReserveTokens = [int64]$SafetyReserveTokens; budgetTokens = $budgetTokens; budgetBytes = $budgetValue; budgetCharacters = $budgetValue; budgetSource = $source; fallbackReason = $fallbackReason; metadataPath = [string]$window.sourcePath; modelMetadataValid = [bool]$window.valid }
}
function Get-ADASDiffAcquisitionMeta {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$DiffText, [int64]$MaxCharacters = 0, [string[]]$ReviewerModel = @(), [string]$ModelMetadataPath = '')
    # Task55/56 — full-diff acquisition metadata + conservative context-derived input budget.
    # NEVER truncates: over-budget fails closed (budgetExceeded=true, truncated=true, text='')
    # with exact counts and the full sha256; no terminal sentinel. Precedence: explicit -MaxCharacters > 0 else the context-derived budget; multiple slugs => MINIMUM budget wins (zero budget wins in any order); UTF-8 bytes: byteCount > budgetBytes.
    $characterCount = $DiffText.Length; $byteCount = [int64][Text.Encoding]::UTF8.GetByteCount($DiffText)
    $lineCount = ([regex]::Matches($DiffText, "`n")).Count
    if ($characterCount -gt 0 -and -not $DiffText.EndsWith("`n")) { $lineCount++ }
    $fileCount = ([regex]::Matches($DiffText, '(?m)^diff --git ')).Count; $sha256 = Get-ADASSha256Text $DiffText
    $budgetSource = ''; $budgetTokens = [int64]0; $budgetBytes = [int64]0; $budgetCharacters = [int64]0
    $contextWindow = [int64]0; $effectiveWindow = [int64]0; $fallbackReason = ''; $metadataPath = ''
    $perModel = New-Object 'System.Collections.Generic.List[object]'
    if ($MaxCharacters -gt 0) {
        $budgetSource = 'explicit-parameter'
        $budgetBytes = [int64]$MaxCharacters
        $budgetCharacters = [int64]$MaxCharacters
    }
    else {
        $slugs = @($ReviewerModel | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($slugs.Count -eq 0) { $slugs = @('') }
        $haveBudget = $false
        foreach ($slug in $slugs) {
            $entry = Get-ADASReviewDiffBudget -ReviewerModel $slug -ModelMetadataPath $ModelMetadataPath
            $perModel.Add($entry)
            if (-not $haveBudget -or [int64]$entry.budgetBytes -lt $budgetBytes) {
                $haveBudget = $true; $budgetTokens = [int64]$entry.budgetTokens; $budgetBytes = [int64]$entry.budgetBytes; $budgetCharacters = [int64]$entry.budgetCharacters
                $budgetSource = [string]$entry.budgetSource; $contextWindow = [int64]$entry.contextWindow; $effectiveWindow = [int64]$entry.effectiveWindow
                $fallbackReason = [string]$entry.fallbackReason; $metadataPath = [string]$entry.metadataPath
            }
        }
        if ($slugs.Count -gt 1) { $budgetSource = $budgetSource + '-min-over-models' }
    }
    $budgetExceeded = ($byteCount -gt $budgetBytes)
    return [pscustomobject]@{ text = $(if ($budgetExceeded) { '' } else { $DiffText }); truncated = $budgetExceeded; budgetExceeded = $budgetExceeded; characterCount = [int64]$characterCount; byteCount = $byteCount; lineCount = [int64]$lineCount; fileCount = [int64]$fileCount; sha256 = $sha256; budgetSource = $budgetSource; budgetTokens = $budgetTokens; budgetBytes = $budgetBytes; budgetCharacters = $budgetCharacters; contextWindow = $contextWindow; effectiveWindow = $effectiveWindow; fallbackReason = $fallbackReason; metadataPath = $metadataPath; requestedModels = @($perModel | ForEach-Object { [string]$_.requestedModel }); perModelBudgets = @($perModel | ForEach-Object { $_ }) }
}
function New-ADASDiffBudgetExceededResult {
    param([Parameter(Mandatory = $true)][string]$RequestedModel, [Parameter(Mandatory = $true)][int64]$DiffCharacterCount, [Parameter(Mandatory = $true)][int64]$DiffByteCount, [Parameter(Mandatory = $true)][string]$DiffSha256, [Parameter(Mandatory = $true)][int64]$BudgetCharacters, [Parameter(Mandatory = $true)][int64]$BudgetBytes, [string]$BudgetSource = '', [string]$FallbackReason = '', [string]$OutputPath = '')
    # Task55/56 — fail-closed diff-budget-exceeded review result, produced BEFORE any provider
    # request: exact size/budget/hash metadata (no diff content, no secrets), BLOCKED provider attestation; contextCapacityBlocked=true marks the Task56 zero-budget state.
    $contextCapacityBlocked = [bool]($BudgetBytes -le 0); $sourceText = $(if ($BudgetSource) { $BudgetSource } else { 'ismeretlen' })
    $capacityNote = $(if ($contextCapacityBlocked) { '; a reviewer context window nem fedezi a kötelező output/prompt/safety reserve-eket (context-capacity BLOCKED)' } else { '' })
    $evidenceText = "a teljes diff ($DiffCharacterCount karakter, $DiffByteCount bájt, sha256=$DiffSha256) meghaladja a reviewer input budgetet ($BudgetCharacters karakter, $BudgetBytes bájt, forrás: $sourceText$capacityNote); csonkítás nem történt, provider request nem indult"
    $providerMeta = [pscustomobject]@{ schemaVersion = '1.0'; status = 'BLOCKED'; provider = 'DeepSeek'; endpointFamily = 'https://api.deepseek.com'; requestedModel = $RequestedModel; actualModel = ''; providerRequestId = $null; requestIdentifier = ''; requestIdentifierType = 'request_id'; inputTokens = 0; outputTokens = 0; totalTokens = 0; fallbackAllowed = $false; fallbackObserved = $false; observedAt = (Get-Date).ToUniversalTime().ToString('o'); secretMaterialRecorded = $false }
    $result = [pscustomobject]@{ verdict = 'BLOCKED'; confidence = 0; summary = 'A teljes diff meghaladja a konfigurált reviewer context windowból származtatott konzervatív input budgetet; a review csonkítás és provider request nélkül fail-closed.'; findings = @(@{ severity = 'HIGH'; category = 'diff-budget-exceeded'; file = $null; line = $null; evidence = $evidenceText; requiredFix = 'A változtatást kisebb, review-zható egységekre kell bontani, vagy a reviewer model konfigurációját felül kell vizsgálni.' }); missingEvidence = @('independent-review'); businessRisks = @()
        _adasDiffBudget = [pscustomobject]@{ schemaVersion = '1.0'; diffSha256 = $DiffSha256; diffCharacterCount = $DiffCharacterCount; diffByteCount = $DiffByteCount; budgetCharacters = $BudgetCharacters; budgetBytes = $BudgetBytes; budgetSource = $BudgetSource; budgetExceeded = $true; truncationPerformed = $false; sentinelAppended = $false; fallbackReason = $FallbackReason; contextCapacityBlocked = $contextCapacityBlocked; secretMaterialRecorded = $false }
        _adasProvider = $providerMeta
        _adasAttempts = @()
    }
    if ($OutputPath) { Write-ADASJson -Path $OutputPath -Value $result }
    return $result
}
function Get-ADASDiffText {
    param([Parameter(Mandatory = $true)][string]$GitPath, [Parameter(Mandatory = $true)][string]$WorktreePath, [Parameter(Mandatory = $true)][string]$BeforeCommit, [Parameter(Mandatory = $true)][string]$AfterCommit, [int64]$MaxCharacters = 0, [string[]]$ReviewerModel = @(), [string]$ModelMetadataPath = '', [ref]$Truncated)
    # Task55/56 — structured diff-acquisition entry point: byte-faithful capture via git
    # --output=<path> + UTF-8 decode; no truncation, no sentinel: over-budget fails closed in the returned metadata (budgetExceeded=true, text=''); [ref]$Truncated reports that state.
    $tempFile = Join-Path ([IO.Path]::GetTempPath()) ("adas-diff-" + [Guid]::NewGuid().ToString('N') + ".diff")
    try {
        & $GitPath -C $WorktreePath diff --no-ext-diff --unified=5 "$BeforeCommit..$AfterCommit" --output=$tempFile
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { throw "Git diff parancs sikertelen ($exitCode): $BeforeCommit..$AfterCommit" }
        if (-not (Test-Path -LiteralPath $tempFile -PathType Leaf)) { throw 'A git diff nem állított elő kimeneti fájlt.' }
        $text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($tempFile))
    }
    finally { Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue }
    $meta = Get-ADASDiffAcquisitionMeta -DiffText $text -MaxCharacters $MaxCharacters -ReviewerModel @($ReviewerModel) -ModelMetadataPath $ModelMetadataPath
    if ($null -ne $Truncated) { $Truncated.Value = [bool]$meta.budgetExceeded }; return $meta
}
function New-ADASReviewAttemptRecord {
    param([Parameter(Mandatory = $true)][int]$Attempt, [Parameter(Mandatory = $true)][string]$RequestedModel, [Parameter(Mandatory = $true)][string]$Disposition, [string]$ErrorClass = '', [string]$FinishReason = '', [string]$ActualModel = '', [string]$RequestId = '', [int64]$InputTokens = 0, [int64]$OutputTokens = 0, [int64]$TotalTokens = 0)
    return [pscustomobject]@{ attempt = $Attempt; disposition = $Disposition; errorClass = $ErrorClass; finishReason = $FinishReason; requestedModel = $RequestedModel; actualModel = $ActualModel; providerRequestId = $(if ($RequestId) { $RequestId } else { $null }); inputTokens = $InputTokens; outputTokens = $OutputTokens; totalTokens = $TotalTokens; secretMaterialRecorded = $false; observedAt = (Get-Date).ToUniversalTime().ToString('o') }
}
function Get-ADASReviewGateCompact {
    param([Parameter(Mandatory = $true)][object[]]$GateSummaries)
    # Deterministic whitelist projection: gate name/status/summary/findings only; evidence blobs, log paths and timestamps never reach the reviewer prompt.
    $compact = @($GateSummaries | ForEach-Object {
        $gateObj = $_
        [pscustomobject]@{ gate = Get-ADASObjectPropertyInternal $gateObj 'gate' $null; name = [string](Get-ADASObjectPropertyInternal $gateObj 'name' ''); status = [string](Get-ADASObjectPropertyInternal $gateObj 'status' ''); summary = [string](Get-ADASObjectPropertyInternal $gateObj 'summary' ''); findings = @(Get-ADASObjectPropertyInternal $gateObj 'findings' @() | ForEach-Object { $_ }) }
    })
    return ,$compact
}
function Get-ADASReviewDiffSections {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$DiffText, [int]$MaxSectionCharacters = 60000)
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
    $fileStarts = New-Object 'System.Collections.Generic.List[int]'; $hunkStarts = New-Object 'System.Collections.Generic.List[int]'
    foreach ($lineStart in $lineStarts) {
        $headLength = [Math]::Min(11, $DiffText.Length - $lineStart)
        if ($headLength -ge 11 -and $DiffText.Substring($lineStart, 11) -eq 'diff --git ') { $fileStarts.Add($lineStart) }
        elseif ($headLength -ge 3 -and $DiffText.Substring($lineStart, 3) -eq '@@ ') { $hunkStarts.Add($lineStart) }
    }
    # Byte-contiguous deterministic segments (file, else hunk, else line, else hard cut); the concatenation of all segment texts equals the original DiffText byte-for-byte.
    $sections = New-Object 'System.Collections.Generic.List[object]'
    $cursor = 0
    while ($cursor -lt $DiffText.Length) {
        if ($DiffText.Length - $cursor -le $MaxSectionCharacters) { $sections.Add([pscustomobject]@{ start = $cursor; length = $DiffText.Length - $cursor }); break }
        $cut = $cursor + $MaxSectionCharacters
        $best = -1
        foreach ($fileStart in $fileStarts) { if ($fileStart -gt $cursor -and $fileStart -le $cut) { $best = $fileStart } }
        if ($best -lt 0) { foreach ($hunkStart in $hunkStarts) { if ($hunkStart -gt $cursor -and $hunkStart -le $cut) { $best = $hunkStart } } }
        if ($best -lt 0) { foreach ($lineStart in $lineStarts) { if ($lineStart -gt $cursor -and $lineStart -le $cut) { $best = $lineStart } } }
        if ($best -le $cursor) { $best = $cut }
        $sections.Add([pscustomobject]@{ start = $cursor; length = $best - $cursor })
        $cursor = $best
    }
    $result = New-Object 'System.Collections.Generic.List[object]'
    $count = $sections.Count
    for ($i = 0; $i -lt $count; $i++) {
        $section = $sections[$i]; $text = $DiffText.Substring([int]$section.start, [int]$section.length)
        $result.Add([pscustomobject]@{ segment = $i + 1; segmentCount = $count; diffSha256 = $diffSha256; segmentSha256 = Get-ADASSha256Text $text; text = $text })
    }
    return ,@($result | ForEach-Object { $_ })
}
function Invoke-ADASDeepSeekCompletion {
    param([Parameter(Mandatory = $true)][string]$ApiKey, [Parameter(Mandatory = $true)][string]$Model, [Parameter(Mandatory = $true)][string]$UserPrompt, [int]$TimeoutSeconds = 240)
    # Single fresh, conversation-independent request: mandatory model only, no fallback.
    $body = [ordered]@{ model = $Model; messages = @(@{ role = 'system'; content = 'You are a strict independent software assurance reviewer. Output valid JSON only.' }, @{ role = 'user'; content = $UserPrompt }); temperature = 0; max_tokens = 24000; response_format = @{ type = 'json_object' } }
    $result = [pscustomobject]@{ ok = $false; transportErrorClass = ''; content = ''; finishReason = ''; actualModel = ''; requestId = ''; inputTokens = [int64]0; outputTokens = [int64]0; totalTokens = [int64]0 }
    try {
        $response = Invoke-RestMethod -Method Post -Uri 'https://api.deepseek.com/chat/completions' -Headers @{ Authorization = "Bearer $ApiKey" } -ContentType 'application/json; charset=utf-8' -Body ($body | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec $TimeoutSeconds
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
        $result.content = [string](Get-ADASObjectPropertyInternal $message 'content' ''); $result.finishReason = [string](Get-ADASObjectPropertyInternal $choices[0] 'finish_reason' '')
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
    # Returns '' when the review satisfies the compact output contract, else a technical error
    # class. Task56: every finding needs non-empty severity/category/evidence/requiredFix. Task57: optional finding file/line must be exclusively null or string (else schema-error).
    if ($null -eq $Parsed -or $Parsed -isnot [pscustomobject]) { return 'schema-error' }
    foreach ($name in @('verdict','confidence','summary','findings','missingEvidence','businessRisks')) {
        if (-not ($Parsed.PSObject.Properties.Name -contains $name)) { return 'schema-error' }
    }
    if (@('PASS','BLOCKED') -notcontains [string]$Parsed.verdict) { return 'schema-error' }
    if ($null -eq $Parsed.confidence -or $Parsed.confidence -is [bool]) { return 'schema-error' }
    $confidence = 0.0
    try { $confidence = [double]$Parsed.confidence } catch { return 'schema-error' }
    if ($confidence -lt 0.0 -or $confidence -gt 1.0) { return 'schema-error' }
    if ([string]::IsNullOrWhiteSpace([string]$Parsed.summary)) { return 'schema-error' }
    $findings = @($Parsed.findings)
    if ($findings.Count -gt 5) { return 'finding-limit-exceeded' }
    foreach ($finding in $findings) {
        if ($finding -isnot [pscustomobject]) { return 'schema-error' }
        foreach ($name in @('severity','category','evidence','requiredFix')) {
            if (-not ($finding.PSObject.Properties.Name -contains $name)) { return 'schema-error' }
        }
        if (@('CRITICAL','HIGH','MEDIUM','LOW') -notcontains [string]$finding.severity) { return 'schema-error' }
        foreach ($name in @('category','evidence','requiredFix')) {
            if ([string]::IsNullOrWhiteSpace([string]$finding.$name)) { return 'schema-error' }
        }
        foreach ($name in @('file','line')) {
            if ($finding.PSObject.Properties.Name -contains $name -and $null -ne $finding.$name -and $finding.$name -isnot [string]) { return 'schema-error' }
        }
    }
    foreach ($item in @($Parsed.missingEvidence)) { if ($null -eq $item) { return 'schema-error' } }
    foreach ($item in @($Parsed.businessRisks)) { if ($null -eq $item) { return 'schema-error' } }
    return ''
}
function ConvertTo-ADASReviewContractObject {
    param([Parameter(Mandatory = $true)]$Parsed)
    # Only the schema fields are accepted; everything else is dropped (non-emptiness already enforced).
    $findings = @($Parsed.findings | ForEach-Object {
        $finding = $_
        [pscustomobject]@{
            severity = [string]$finding.severity
            category = [string]$finding.category
            file = $(if ($finding.PSObject.Properties.Name -contains 'file' -and $null -ne $finding.file) { [string]$finding.file } else { $null })
            line = $(if ($finding.PSObject.Properties.Name -contains 'line' -and $null -ne $finding.line) { [string]$finding.line } else { $null })
            evidence = $(if ($finding.PSObject.Properties.Name -contains 'evidence') { [string]$finding.evidence } else { '' })
            requiredFix = $(if ($finding.PSObject.Properties.Name -contains 'requiredFix') { [string]$finding.requiredFix } else { '' })
        }
    })
    return [pscustomobject]@{ verdict = [string]$Parsed.verdict; confidence = [double]$Parsed.confidence; summary = [string]$Parsed.summary; findings = $findings; missingEvidence = @($Parsed.missingEvidence | ForEach-Object { [string]$_ }); businessRisks = @($Parsed.businessRisks | ForEach-Object { [string]$_ }) }
}
function New-ADASReviewUnavailableResult {
    param([Parameter(Mandatory = $true)][string]$RequestedModel, [Parameter(Mandatory = $true)][string]$Evidence, [object[]]$Attempts = @(), [bool]$FallbackObserved = $false, [string]$FailureClass = 'review-unavailable')
    # Fail-closed review-unavailable BLOCKED; attempts never become a PASS attestation. Task57:
    # fallbackObserved is true ONLY for an actually observed different model; generic failures carry their precise unavailabilityClass instead (verdict stays BLOCKED).
    $providerMeta = [pscustomobject]@{ schemaVersion = '1.0'; status = 'BLOCKED'; provider = 'DeepSeek'; endpointFamily = 'https://api.deepseek.com'; requestedModel = $RequestedModel; actualModel = ''; providerRequestId = $null; requestIdentifier = ''; requestIdentifierType = 'request_id'; inputTokens = 0; outputTokens = 0; totalTokens = 0; fallbackAllowed = $false; fallbackObserved = $FallbackObserved; unavailabilityClass = $FailureClass; observedAt = (Get-Date).ToUniversalTime().ToString('o'); secretMaterialRecorded = $false }
    return [pscustomobject]@{ verdict = 'BLOCKED'; confidence = 0; summary = 'A független AI-review technikai hiba miatt nem áll rendelkezésre; fail-closed döntés.'; findings = @(@{ severity = 'HIGH'; category = 'review-unavailable'; file = $null; line = $null; evidence = $Evidence; requiredFix = 'A review-t sikeresen újra kell futtatni.' }); missingEvidence = @('independent-review'); businessRisks = @(); _adasProvider = $providerMeta; _adasAttempts = @($Attempts | ForEach-Object { $_ }) }
}
function Invoke-ADASIndependentReview {
    param([Parameter(Mandatory = $true)][string]$ApiKey, [Parameter(Mandatory = $true)][string]$Model, [Parameter(Mandatory = $true)][string]$TaskText, [Parameter(Mandatory = $true)][string]$DiffText, [Parameter(Mandatory = $true)][bool]$DiffTruncated, [Parameter(Mandatory = $true)]$RiskProfile, [Parameter(Mandatory = $true)][object[]]$GateSummaries, [Parameter(Mandatory = $true)][string]$OutputPath, [int]$TimeoutSeconds = 240, [string]$DiffSha256 = '', [int64]$DiffCharacterCount = -1)
    # Coverage preflight (Task54 detection contract): a diff is truncated ONLY when the
    # diff-acquisition layer actually truncated it. Proofs, in order: (1) the mandatory
    # -DiffTruncated acquisition flag (authoritative); (2) the exact terminal sentinel "--- DIFF
    # TRUNCATED BY ADAS ---" as the very last characters, preceded by a line break (a mid-diff
    # occurrence can never match: diff lines carry '+'/'-'/' ' prefixes); (3) ambiguous -DiffSha256/-DiffCharacterCount metadata that mismatches the text fails closed.
    $truncationEvidence = ''
    if ($DiffTruncated) {
        $truncationEvidence = 'a diff-acquisition réteg explicit truncated metadata flaget adott'
    }
    elseif ($DiffText.EndsWith("`n--- DIFF TRUNCATED BY ADAS ---")) {
        $truncationEvidence = 'a diff a Get-ADASDiffText által hozzáfűzött terminális csonkolási sentinellel zárul'
    }
    elseif ((-not [string]::IsNullOrEmpty($DiffSha256)) -and ((Get-ADASSha256Text $DiffText) -ne $DiffSha256)) {
        $truncationEvidence = 'a diff-acquisition SHA-256 metadata nem egyezik a review alá vont diff szövegével'
    }
    elseif (($DiffCharacterCount -ge 0) -and ($DiffText.Length -ne $DiffCharacterCount)) {
        $truncationEvidence = 'a diff-acquisition karakterszám-metadata nem egyezik a review alá vont diff szövegével'
    }
    if ($truncationEvidence) {
        $truncatedResult = New-ADASReviewUnavailableResult -RequestedModel $Model -Attempts @() -FailureClass 'truncation-evidence' -Evidence ("A diff nem bizonyítható teljesnek (" + $truncationEvidence + "); a teljes changed-file/hunk lefedettség nem bizonyítható, ezért a review kérés nélkül fail-closed BLOCKED.")
        Write-ADASJson -Path $OutputPath -Value $truncatedResult; return $truncatedResult
    }
    $attempts = New-Object 'System.Collections.Generic.List[object]'
    # Deterministic compact gate/risk projection: whitelisted fields only (no blobs/log paths/timestamps).
    $gateJson = (Get-ADASReviewGateCompact -GateSummaries $GateSummaries) | ConvertTo-Json -Depth 8 -Compress
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
        $sectionLines.Add([string]$section.text); if ($sectionCount -gt 1) { $sectionLines.Add("[END DIFF SEGMENT $($section.segment)]") }
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
    $terminalErrorClass = 'review-unavailable'
    for ($attemptNumber = 1; $attemptNumber -le 2; $attemptNumber++) {
        $repairHeader = if ($attemptNumber -gt 1) {
            "REPAIR REQUEST: the previous attempt for this exact task and diff was unusable ($repairReason). Produce the complete review now, freshly: output ONLY the single JSON object per the contract below - no prose, no markdown, no reasoning, complete and well-formed.`n`n"
        } else { '' }
        $completion = Invoke-ADASDeepSeekCompletion -ApiKey $ApiKey -Model $Model -UserPrompt ($repairHeader + $prompt) -TimeoutSeconds $TimeoutSeconds
        if (-not $completion.ok) {
            $attempts.Add((New-ADASReviewAttemptRecord -Attempt $attemptNumber -RequestedModel $Model -Disposition 'failed-terminal' -ErrorClass ([string]$completion.transportErrorClass) -ActualModel ([string]$completion.actualModel) -TotalTokens $completion.totalTokens))
            $terminalEvidence = "A DeepSeek hívás transport hibát adott ($($completion.transportErrorClass)); ilyen hibára retry nem engedélyezett."
            $terminalErrorClass = 'transport-' + ([string]$completion.transportErrorClass)
            break
        }
        $errorClass = ''; $parsed = $null
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
            $terminalErrorClass = $errorClass
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
        # Provider attestation only from the finally parsed, accepted attempt. Task57: PASS
        # requires a non-empty actualModel that exactly equals the requested model, a non-empty
        # requestId, positive totalTokens and no observed fallback; a failed attestation is fail-closed BLOCKED while the attempt records keep the provider/model/token/request data.
        $fallbackObserved = (-not [string]::IsNullOrWhiteSpace($completion.actualModel) -and $completion.actualModel -ne $Model)
        $modelAttested = (-not [string]::IsNullOrWhiteSpace($completion.actualModel) -and $completion.actualModel -eq $Model)
        $attestationPass = ($modelAttested -and -not [string]::IsNullOrWhiteSpace($completion.requestId) -and $completion.totalTokens -gt 0 -and -not $fallbackObserved)
        $providerMeta = [pscustomobject]@{ schemaVersion = '1.0'; status = $(if ($attestationPass) { 'PASS' } else { 'BLOCKED' }); provider = 'DeepSeek'; endpointFamily = 'https://api.deepseek.com'; requestedModel = $Model; actualModel = $completion.actualModel; providerRequestId = $(if ($completion.requestId) { $completion.requestId } else { $null }); requestIdentifier = $(if ($completion.requestId) { $completion.requestId } else { '' }); requestIdentifierType = 'request_id'; inputTokens = $completion.inputTokens; outputTokens = $completion.outputTokens; totalTokens = $completion.totalTokens; fallbackAllowed = $false; fallbackObserved = $fallbackObserved; observedAt = (Get-Date).ToUniversalTime().ToString('o'); secretMaterialRecorded = $false }
        $attempts.Add((New-ADASReviewAttemptRecord -Attempt $attemptNumber -RequestedModel $Model -Disposition 'accepted' -FinishReason ([string]$completion.finishReason) -ActualModel ([string]$completion.actualModel) -RequestId ([string]$completion.requestId) -InputTokens $completion.inputTokens -OutputTokens $completion.outputTokens -TotalTokens $completion.totalTokens))
        $review = ConvertTo-ADASReviewContractObject -Parsed $parsed
        if (-not $attestationPass) {
            # Task58 fail-closed terminal: a parsed review can never return PASS with failed
            # provider attestation. The FINAL persisted verdict is overridden to BLOCKED with one
            # deduplicated HIGH provider-attestation-invalid finding (concrete evidence/requiredFix); every attempt record stays untouched. Common review-1/review-2 path.
            $review.verdict = 'BLOCKED'
            $attestationReasons = New-Object 'System.Collections.Generic.List[string]'
            if ([string]::IsNullOrWhiteSpace([string]$completion.actualModel)) { $attestationReasons.Add('actualModel üres') }
            elseif (-not $modelAttested) { $attestationReasons.Add("actualModel '$($completion.actualModel)' eltér a kért '$Model' modelltől") }
            if ([string]::IsNullOrWhiteSpace([string]$completion.requestId)) { $attestationReasons.Add('requestId üres') }
            if ([int64]$completion.totalTokens -le 0) { $attestationReasons.Add("totalTokens=$($completion.totalTokens) nem pozitív") }
            if ($fallbackObserved) { $attestationReasons.Add('tényleges fallback figyelhető meg') }
            $attestationFinding = [pscustomobject]@{ severity = 'HIGH'; category = 'provider-attestation-invalid'; file = $null; line = $null; evidence = 'A provider attesztáció sikertelen: ' + ($attestationReasons -join '; ') + '; a review verdikt ezért BLOCKED-re lett felülírva, az attempt rekordok változatlanul megmaradtak.'; requiredFix = 'A review csak érvényes provider attesztációval kaphat PASS verdiktet: nem üres, a kért modellel pontosan egyező actualModel, nem üres requestId, pozitív totalTokens, megfigyelt fallback nélkül.' }
            $keptFindings = New-Object 'System.Collections.Generic.List[object]'
            foreach ($existingFinding in @($review.findings)) {
                if (-not (([string]$existingFinding.category -eq 'provider-attestation-invalid') -and ([string]$existingFinding.severity -eq 'HIGH'))) { $keptFindings.Add($existingFinding) }
            }
            $keptFindings.Add($attestationFinding)
            # Compact contract: at most 5 findings — deterministic severity-rank slice (stable Sort-Object), the attestation finding always kept.
            $severityRank = @{ CRITICAL = 4; HIGH = 3; MEDIUM = 2; LOW = 1 }
            $review.findings = @($keptFindings | Sort-Object { if ([string]$_.category -eq 'provider-attestation-invalid') { 5 } else { $severityRank[[string]$_.severity] } } -Descending | Select-Object -First 5)
        }
        $review | Add-Member -NotePropertyName '_adasProvider' -NotePropertyValue $providerMeta
        $review | Add-Member -NotePropertyName '_adasAttempts' -NotePropertyValue @($attempts | ForEach-Object { $_ })
        Write-ADASJson -Path $OutputPath -Value $review; return $review
    }
    if ([string]::IsNullOrWhiteSpace($terminalEvidence)) { $terminalEvidence = 'A független review nem készült el; fail-closed.' }
    # Task57: fallbackObserved ONLY from an actually observed different model; transport/parse/schema failures keep the precise failure class instead. (.ToArray(): PS 5.1-safe unwrap.)
    $terminalFallbackObserved = $false
    foreach ($attempt in $attempts.ToArray()) {
        if (-not [string]::IsNullOrWhiteSpace([string]$attempt.actualModel) -and ([string]$attempt.actualModel -ne $Model)) { $terminalFallbackObserved = $true }
    }
    $fallback = New-ADASReviewUnavailableResult -RequestedModel $Model -Evidence $terminalEvidence -Attempts @($attempts | ForEach-Object { $_ }) -FallbackObserved $terminalFallbackObserved -FailureClass $terminalErrorClass
    Write-ADASJson -Path $OutputPath -Value $fallback; return $fallback
}
