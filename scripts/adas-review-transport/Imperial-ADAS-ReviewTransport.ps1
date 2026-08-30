function Get-ADASReviewModelContextWindow {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ReviewerModel,
        [string]$ModelMetadataPath = ''
    )
    # Task55 — reliable local context-window lookup for the actual requested
    # reviewer model slug. Reads ONLY the profile codex models capability
    # manifest (a JSON of model capability fields); no key, token, credential
    # or personal data is ever read or returned. Unknown/missing/invalid
    # metadata => valid=false with a named reason; callers must fail closed or
    # use the documented safe fallback cap, never assume infinity.
    # Default metadata path: <profile root>\codex-home\models.json, resolved
    # from the module directory ($PSScriptRoot of the installed profile module).
    $invalid = [pscustomobject]@{
        requestedModel = $ReviewerModel; contextWindow = [int64]0; maxContextWindow = [int64]0;
        effectivePercent = [int]0; effectiveWindow = [int64]0; sourcePath = ''; valid = $false; reason = ''
    }
    if ([string]::IsNullOrWhiteSpace($ReviewerModel)) {
        $invalid.reason = 'reviewer-model-not-specified'
        return $invalid
    }
    $path = $ModelMetadataPath
    if ([string]::IsNullOrWhiteSpace($path)) {
        $profileRoot = Split-Path -Parent $PSScriptRoot
        $path = Join-Path $profileRoot 'codex-home\models.json'
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $invalid.reason = 'metadata-file-not-found'
        $invalid.sourcePath = $path
        return $invalid
    }
    try {
        $raw = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
        $manifest = $raw | ConvertFrom-Json
    }
    catch {
        $invalid.reason = 'metadata-json-invalid'
        $invalid.sourcePath = $path
        return $invalid
    }
    $models = @(Get-ADASObjectPropertyInternal $manifest 'models' @())
    $match = $null
    foreach ($model in $models) {
        if ([string](Get-ADASObjectPropertyInternal $model 'slug' '') -eq $ReviewerModel) { $match = $model; break }
    }
    if ($null -eq $match) {
        $invalid.reason = 'model-slug-not-found'
        $invalid.sourcePath = $path
        return $invalid
    }
    $contextWindow = [int64]0
    if (-not [int64]::TryParse([string](Get-ADASObjectPropertyInternal $match 'context_window' ''), [ref]$contextWindow)) {
        $invalid.reason = 'context-window-not-numeric'
        $invalid.sourcePath = $path
        return $invalid
    }
    # Sanity range: positive and at most 256M tokens (2^28); anything else is metadata corruption.
    if ($contextWindow -le 0 -or $contextWindow -gt 268435456) {
        $invalid.reason = 'context-window-out-of-range'
        $invalid.sourcePath = $path
        return $invalid
    }
    $maxWindow = $contextWindow
    $maxParsed = [int64]0
    if ([int64]::TryParse([string](Get-ADASObjectPropertyInternal $match 'max_context_window' ''), [ref]$maxParsed) -and $maxParsed -gt 0 -and $maxParsed -lt $maxWindow) {
        $maxWindow = $maxParsed
    }
    $percent = [int]0
    $hasPercent = $false
    $percentValue = Get-ADASObjectPropertyInternal $match 'effective_context_window_percent' $null
    if ($null -ne $percentValue) {
        if ([int]::TryParse([string]$percentValue, [ref]$percent) -and $percent -gt 0 -and $percent -le 100) { $hasPercent = $true }
        else { $percent = [int]0 }
    }
    $effectiveWindow = $maxWindow
    if ($hasPercent) { $effectiveWindow = [int64][Math]::Floor([double]$maxWindow * [double]$percent / 100.0) }
    return [pscustomobject]@{
        requestedModel = $ReviewerModel
        contextWindow = $contextWindow
        maxContextWindow = $maxWindow
        effectivePercent = $(if ($hasPercent) { $percent } else { [int]0 })
        effectiveWindow = $effectiveWindow
        sourcePath = $path
        valid = $true
        reason = ''
    }
}

function Get-ADASReviewDiffBudget {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ReviewerModel,
        [string]$ModelMetadataPath = '',
        [int64]$MaxOutputTokens = 24000,
        [int64]$PromptReserveTokens = 65536,
        [int64]$SafetyReserveTokens = 32768,
        [int64]$FallbackBudgetCharacters = 350000
    )
    # Task55 — conservative, auditable diff-input budget derived from the
    # configured reviewer context window. Formula (all values recorded):
    #   budgetTokens = effectiveContextWindow - MaxOutputTokens - PromptReserveTokens - SafetyReserveTokens
    #   budgetBytes  = budgetTokens
    #   budgetCharacters = budgetTokens (chars <= bytes; recorded for audit)
    # Reserve contract:
    #   - MaxOutputTokens 24,000: the request max_tokens output cap, which also
    #     consumes context window;
    #   - PromptReserveTokens 65,536: system instruction, task text, compact gate
    #     summary, compact risk profile, section framing and the JSON envelope;
    #   - SafetyReserveTokens 32,768: tokenizer variance and JSON escaping
    #     inflation (a git diff is prefixed text lines; inflation stays far below
    #     the reserve even at the budget boundary).
    # Hard token guarantee: the provider uses a byte-level tokenizer, so token
    # count <= byte count; requiring byteCount <= budgetTokens therefore bounds
    # the prompt inside the effective window together with the reserves.
    # Unknown/missing/invalid metadata => explicit safe fallback cap of 350,000
    # characters/bytes (the documented legacy cap), budgetSource='fallback-cap'
    # with a named fallbackReason — fail-closed, never infinity, never silent.
    $window = Get-ADASReviewModelContextWindow -ReviewerModel $ReviewerModel -ModelMetadataPath $ModelMetadataPath
    if (-not [bool]$window.valid) {
        return [pscustomobject]@{
            requestedModel = $ReviewerModel
            contextWindow = [int64]0
            effectiveWindow = [int64]0
            outputReserveTokens = [int64]$MaxOutputTokens
            promptReserveTokens = [int64]$PromptReserveTokens
            safetyReserveTokens = [int64]$SafetyReserveTokens
            budgetTokens = [int64]0
            budgetBytes = [int64]$FallbackBudgetCharacters
            budgetCharacters = [int64]$FallbackBudgetCharacters
            budgetSource = 'fallback-cap'
            fallbackReason = [string]$window.reason
            metadataPath = [string]$window.sourcePath
            modelMetadataValid = $false
        }
    }
    $budgetTokens = [int64]$window.effectiveWindow - [int64]$MaxOutputTokens - [int64]$PromptReserveTokens - [int64]$SafetyReserveTokens
    if ($budgetTokens -le 0) {
        return [pscustomobject]@{
            requestedModel = $ReviewerModel
            contextWindow = [int64]$window.contextWindow
            effectiveWindow = [int64]$window.effectiveWindow
            outputReserveTokens = [int64]$MaxOutputTokens
            promptReserveTokens = [int64]$PromptReserveTokens
            safetyReserveTokens = [int64]$SafetyReserveTokens
            budgetTokens = [int64]0
            budgetBytes = [int64]$FallbackBudgetCharacters
            budgetCharacters = [int64]$FallbackBudgetCharacters
            budgetSource = 'fallback-cap'
            fallbackReason = 'context-window-too-small-for-reserves'
            metadataPath = [string]$window.sourcePath
            modelMetadataValid = $true
        }
    }
    return [pscustomobject]@{
        requestedModel = $ReviewerModel
        contextWindow = [int64]$window.contextWindow
        effectiveWindow = [int64]$window.effectiveWindow
        outputReserveTokens = [int64]$MaxOutputTokens
        promptReserveTokens = [int64]$PromptReserveTokens
        safetyReserveTokens = [int64]$SafetyReserveTokens
        budgetTokens = $budgetTokens
        budgetBytes = $budgetTokens
        budgetCharacters = $budgetTokens
        budgetSource = 'context-window'
        fallbackReason = ''
        metadataPath = [string]$window.sourcePath
        modelMetadataValid = $true
    }
}

function Get-ADASDiffAcquisitionMeta {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$DiffText,
        [int64]$MaxCharacters = 0,
        [string[]]$ReviewerModel = @(),
        [string]$ModelMetadataPath = ''
    )
    # Task55 — full-diff acquisition metadata plus the conservative,
    # context-derived input budget. NEVER truncates: when the diff exceeds the
    # budget the result fails closed (budgetExceeded=true, truncated=true,
    # text='') while the exact character/byte/line/file counts and the full
    # sha256 stay available for the audit record. No terminal sentinel is ever
    # appended; the Task54 review-side sentinel detection remains as
    # defense-in-depth for legacy artifacts.
    # Budget source precedence:
    #   1. explicit -MaxCharacters > 0 => legacy-compatible character cap
    #      (back-compat/testing only), budgetSource='explicit-parameter';
    #   2. otherwise the context-derived budget of the requested reviewer
    #      model(s); with multiple slugs the MINIMUM budget wins (conservative).
    # Comparison is on UTF-8 bytes: byteCount > budgetBytes => exceeded.
    $characterCount = $DiffText.Length
    $byteCount = [int64][Text.Encoding]::UTF8.GetByteCount($DiffText)
    $lineCount = ([regex]::Matches($DiffText, "`n")).Count
    if ($characterCount -gt 0 -and -not $DiffText.EndsWith("`n")) { $lineCount++ }
    $fileCount = ([regex]::Matches($DiffText, '(?m)^diff --git ')).Count
    $sha256 = Get-ADASSha256Text $DiffText
    $budgetSource = ''
    $budgetTokens = [int64]0
    $budgetBytes = [int64]0
    $budgetCharacters = [int64]0
    $contextWindow = [int64]0
    $effectiveWindow = [int64]0
    $fallbackReason = ''
    $metadataPath = ''
    $perModel = New-Object 'System.Collections.Generic.List[object]'
    if ($MaxCharacters -gt 0) {
        $budgetSource = 'explicit-parameter'
        $budgetTokens = [int64]0
        $budgetBytes = [int64]$MaxCharacters
        $budgetCharacters = [int64]$MaxCharacters
    }
    else {
        $slugs = @($ReviewerModel | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        if ($slugs.Count -eq 0) { $slugs = @('') }
        foreach ($slug in $slugs) {
            $entry = Get-ADASReviewDiffBudget -ReviewerModel $slug -ModelMetadataPath $ModelMetadataPath
            $perModel.Add($entry)
            if ($budgetBytes -le 0 -or [int64]$entry.budgetBytes -lt $budgetBytes) {
                $budgetTokens = [int64]$entry.budgetTokens
                $budgetBytes = [int64]$entry.budgetBytes
                $budgetCharacters = [int64]$entry.budgetCharacters
                $budgetSource = [string]$entry.budgetSource
                $contextWindow = [int64]$entry.contextWindow
                $effectiveWindow = [int64]$entry.effectiveWindow
                $fallbackReason = [string]$entry.fallbackReason
                $metadataPath = [string]$entry.metadataPath
            }
        }
        if ($slugs.Count -gt 1) { $budgetSource = $budgetSource + '-min-over-models' }
    }
    $budgetExceeded = ($byteCount -gt $budgetBytes)
    return [pscustomobject]@{
        text = $(if ($budgetExceeded) { '' } else { $DiffText })
        truncated = $budgetExceeded
        budgetExceeded = $budgetExceeded
        characterCount = [int64]$characterCount
        byteCount = $byteCount
        lineCount = [int64]$lineCount
        fileCount = [int64]$fileCount
        sha256 = $sha256
        budgetSource = $budgetSource
        budgetTokens = $budgetTokens
        budgetBytes = $budgetBytes
        budgetCharacters = $budgetCharacters
        contextWindow = $contextWindow
        effectiveWindow = $effectiveWindow
        fallbackReason = $fallbackReason
        metadataPath = $metadataPath
        requestedModels = @($perModel | ForEach-Object { [string]$_.requestedModel })
        perModelBudgets = @($perModel | ForEach-Object { $_ })
    }
}

function New-ADASDiffBudgetExceededResult {
    param(
        [Parameter(Mandatory = $true)][string]$RequestedModel,
        [Parameter(Mandatory = $true)][int64]$DiffCharacterCount,
        [Parameter(Mandatory = $true)][int64]$DiffByteCount,
        [Parameter(Mandatory = $true)][string]$DiffSha256,
        [Parameter(Mandatory = $true)][int64]$BudgetCharacters,
        [Parameter(Mandatory = $true)][int64]$BudgetBytes,
        [string]$BudgetSource = '',
        [string]$OutputPath = ''
    )
    # Task55 — fail-closed structured diff-budget-exceeded review result,
    # produced BEFORE any provider request. Carries the exact size/budget/hash
    # metadata (no diff content, no secrets) and a BLOCKED provider attestation
    # so the gate assembly records the review as unavailable without any
    # provider attempt. Half-done segment aggregation is never produced: this
    # result replaces the whole review fail-closed.
    $evidenceText = "a teljes diff ($DiffCharacterCount karakter, $DiffByteCount bájt, sha256=$DiffSha256) meghaladja a reviewer input budgetet ($BudgetCharacters karakter, $BudgetBytes bájt, forrás: $(if ($BudgetSource) { $BudgetSource } else { 'ismeretlen' })); csonkítás nem történt, provider request nem indult"
    $providerMeta = [pscustomobject]@{
        schemaVersion = '1.0'; status = 'BLOCKED'; provider = 'DeepSeek'; endpointFamily = 'https://api.deepseek.com';
        requestedModel = $RequestedModel; actualModel = '';
        providerRequestId = $null; requestIdentifier = ''; requestIdentifierType = 'request_id';
        inputTokens = 0; outputTokens = 0; totalTokens = 0;
        fallbackAllowed = $false; fallbackObserved = $false;
        observedAt = (Get-Date).ToUniversalTime().ToString('o'); secretMaterialRecorded = $false
    }
    $result = [pscustomobject]@{
        verdict = 'BLOCKED'
        confidence = 0
        summary = 'A teljes diff meghaladja a konfigurált reviewer context windowból származtatott konzervatív input budgetet; a review csonkítás és provider request nélkül fail-closed.'
        findings = @(@{ severity = 'HIGH'; category = 'diff-budget-exceeded'; file = $null; line = $null; evidence = $evidenceText; requiredFix = 'A változtatást kisebb, review-zható egységekre kell bontani, vagy a reviewer model konfigurációját felül kell vizsgálni.' })
        missingEvidence = @('independent-review')
        businessRisks = @()
        _adasDiffBudget = [pscustomobject]@{
            schemaVersion = '1.0'
            diffSha256 = $DiffSha256
            diffCharacterCount = $DiffCharacterCount
            diffByteCount = $DiffByteCount
            budgetCharacters = $BudgetCharacters
            budgetBytes = $BudgetBytes
            budgetSource = $BudgetSource
            budgetExceeded = $true
            truncationPerformed = $false
            sentinelAppended = $false
            secretMaterialRecorded = $false
        }
        _adasProvider = $providerMeta
        _adasAttempts = @()
    }
    if ($OutputPath) { Write-ADASJson -Path $OutputPath -Value $result }
    return $result
}

function Get-ADASDiffText {
    param(
        [Parameter(Mandatory = $true)][string]$GitPath,
        [Parameter(Mandatory = $true)][string]$WorktreePath,
        [Parameter(Mandatory = $true)][string]$BeforeCommit,
        [Parameter(Mandatory = $true)][string]$AfterCommit,
        [int64]$MaxCharacters = 0,
        [string[]]$ReviewerModel = @(),
        [string]$ModelMetadataPath = '',
        [ref]$Truncated
    )
    # Task55 — structured diff-acquisition entry point (replaces the legacy
    # 350,000-character truncating Get-ADASDiffText). The diff is captured
    # byte-faithfully: git writes it to a temp file with --output=<path> and
    # the bytes are decoded as UTF-8, so the acquisition text is exactly the
    # git output (no console-encoding loss, no trailing-string surgery).
    # No truncation and no terminal sentinel are ever applied: an over-budget
    # diff fails closed in the returned metadata (budgetExceeded=true,
    # text=''), and the legacy [ref]$Truncated out-flag now reports exactly
    # that fail-closed budget state.
    $tempFile = Join-Path ([IO.Path]::GetTempPath()) ("adas-diff-" + [Guid]::NewGuid().ToString('N') + ".diff")
    try {
        & $GitPath -C $WorktreePath diff --no-ext-diff --unified=5 "$BeforeCommit..$AfterCommit" --output=$tempFile
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw "Git diff parancs sikertelen ($exitCode): $BeforeCommit..$AfterCommit"
        }
        if (-not (Test-Path -LiteralPath $tempFile -PathType Leaf)) {
            throw 'A git diff nem állított elő kimeneti fájlt.'
        }
        $bytes = [IO.File]::ReadAllBytes($tempFile)
        $text = [Text.Encoding]::UTF8.GetString($bytes)
    }
    finally {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
    $meta = Get-ADASDiffAcquisitionMeta -DiffText $text -MaxCharacters $MaxCharacters -ReviewerModel @($ReviewerModel) -ModelMetadataPath $ModelMetadataPath
    if ($null -ne $Truncated) { $Truncated.Value = [bool]$meta.budgetExceeded }
    return $meta
}

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
        [Parameter(Mandatory = $true)][bool]$DiffTruncated,
        [Parameter(Mandatory = $true)]$RiskProfile,
        [Parameter(Mandatory = $true)][object[]]$GateSummaries,
        [Parameter(Mandatory = $true)][string]$OutputPath,
        [int]$TimeoutSeconds = 240,
        [string]$DiffSha256 = '',
        [int64]$DiffCharacterCount = -1
    )
    # Coverage preflight (Task54 detection contract): a diff is treated as truncated ONLY when the
    # diff-acquisition layer actually truncated it, never on an unanchored sentinel match anywhere
    # in the text. Proofs accepted, in order:
    #   1. the mandatory -DiffTruncated acquisition metadata flag (authoritative);
    #   2. the exact terminal suffix sentinel that Get-ADASDiffText appends when it truncates:
    #      the literal line "--- DIFF TRUNCATED BY ADAS ---" as the very last characters of the
    #      text, preceded by a line break. This is deterministic for both line endings: acquisition
    #      appends CRLF before the sentinel line, and the LF-suffix EndsWith check matches the CRLF
    #      form as well. A mid-diff occurrence of the literal inside an added source/test line can
    #      never match: acquisition appends the suffix only after the final byte it kept, and every
    #      git diff content line carries a '+'/'-'/' ' prefix while headers carry path parts, so a
    #      real diff line can never be byte-identical with the suffix line;
    #   3. ambiguous metadata: a provided -DiffSha256 or -DiffCharacterCount that does not match the
    #      text under review fails closed instead of guessing.
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
        $truncatedResult = New-ADASReviewUnavailableResult -RequestedModel $Model -Attempts @() -Evidence ("A diff nem bizonyítható teljesnek (" + $truncationEvidence + "); a teljes changed-file/hunk lefedettség nem bizonyítható, ezért a review kérés nélkül fail-closed BLOCKED.")
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

