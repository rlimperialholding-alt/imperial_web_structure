# Task55 — context-derived diff-acquisition budget: the reviewer budget is
    # derived from the requested model context window (canonical acquisition
    # section of the synced module); over-budget diffs fail closed without any
    # truncation or provider request.
    $reviewBudgetModel = if ([string]::IsNullOrWhiteSpace([string]$config.CodexModel)) { 'deepseek-v4-pro' } else { [string]$config.CodexModel }
    $reviewBudgetModels = @($reviewBudgetModel)
    if ($reviewBudgetModel -ne 'deepseek-v4-pro') { $reviewBudgetModels += 'deepseek-v4-pro' }
    $diffTruncated = $false
    $acquisition = Get-ADASDiffText -GitPath $gitPath -WorktreePath $worktree -BeforeCommit $BeforeCommit -AfterCommit $AfterCommit -ReviewerModel @($reviewBudgetModels) -Truncated ([ref]$diffTruncated)
    $diffText = [string]$acquisition.text
    $diffBudgetExceeded = [bool]$acquisition.budgetExceeded
    $impactMap = Get-ADASImpactMap -ChangeSet $changeSet
    $riskFloor = [string](Get-ObjectProperty $project 'riskFloor' 'R0')
    if ($intent.requestedRiskFloor) { $riskFloor = Get-ADASMaxRisk $riskFloor ([string]$intent.requestedRiskFloor) }
    # Task58: an exceeded diff has no reviewable text and the mandatory -DiffText parameter
    # rejects '' — the risk profile runs only on the non-exceeded path; the exceeded path
    # defaults to the fail-closed R3 maximum (both independent review slots).
    $risk = 'R3'
    if (-not $diffBudgetExceeded) {
        $riskProfile = Get-ADASRiskProfile -ChangeSet $changeSet -ImpactMap $impactMap -DiffText $diffText -RiskFloor $riskFloor -TaskText $intent.desiredBehavior
        $risk = [string]$riskProfile.level
    }
    $env:ADAS_RISK = $risk
    $codeChanged = Test-CodeChanged $changeSet

    Write-ADASJson -Path (Join-Path $proofDirectory 'change-set.json') -Value $changeSet
    Write-ADASJson -Path (Join-Path $proofDirectory 'impact-map.json') -Value $impactMap
    Write-ADASJson -Path (Join-Path $proofDirectory 'intent-contract.json') -Value $intent
    if (-not $diffBudgetExceeded) { Write-ADASJson -Path (Join-Path $proofDirectory 'risk-profile.json') -Value $riskProfile }
    Write-ADASUtf8NoBom -Path (Join-Path $proofDirectory 'change.diff') -Text $diffText
    if ($diffBudgetExceeded) {
        # Fail-closed audit record: exact full-diff size/budget/hash metadata,
        # no diff content, no secrets. change.diff stays empty (nothing was truncated).
        Write-ADASJson -Path (Join-Path $proofDirectory 'change.diff.budget-exceeded-meta.json') -Value $acquisition
        # Task58 budget-terminal: materialize the BLOCKED review result for BOTH independent
        # review slots BEFORE any provider section, then stop the pipeline (exit 80 = fail-closed BLOCKED). Provider requests/attempts here: exactly 0; no later code can overwrite.
        $diffSha256 = [string]$acquisition.sha256
        $budgetModel1 = if ([string]::IsNullOrWhiteSpace([string]$config.CodexModel)) { 'deepseek-v4-pro' } else { [string]$config.CodexModel }
        $null = New-ADASDiffBudgetExceededResult -RequestedModel $budgetModel1 -DiffCharacterCount ([int64]$acquisition.characterCount) -DiffByteCount ([int64]$acquisition.byteCount) -DiffSha256 $diffSha256 -BudgetCharacters ([int64]$acquisition.budgetCharacters) -BudgetBytes ([int64]$acquisition.budgetBytes) -BudgetSource ([string]$acquisition.budgetSource) -FallbackReason ([string]$acquisition.fallbackReason) -OutputPath (Join-Path $proofDirectory 'review-1.json')
        $null = New-ADASDiffBudgetExceededResult -RequestedModel 'deepseek-v4-pro' -DiffCharacterCount ([int64]$acquisition.characterCount) -DiffByteCount ([int64]$acquisition.byteCount) -DiffSha256 $diffSha256 -BudgetCharacters ([int64]$acquisition.budgetCharacters) -BudgetBytes ([int64]$acquisition.budgetBytes) -BudgetSource ([string]$acquisition.budgetSource) -FallbackReason ([string]$acquisition.fallbackReason) -OutputPath (Join-Path $proofDirectory 'review-2.json')
        exit 80
    }
