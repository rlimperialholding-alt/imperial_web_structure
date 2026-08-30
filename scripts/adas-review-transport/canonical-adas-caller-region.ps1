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
    $riskProfile = Get-ADASRiskProfile -ChangeSet $changeSet -ImpactMap $impactMap -DiffText $diffText -RiskFloor $riskFloor -TaskText $intent.desiredBehavior
    $risk = [string]$riskProfile.level
    $env:ADAS_RISK = $risk
    $codeChanged = Test-CodeChanged $changeSet

    Write-ADASJson -Path (Join-Path $proofDirectory 'change-set.json') -Value $changeSet
    Write-ADASJson -Path (Join-Path $proofDirectory 'impact-map.json') -Value $impactMap
    Write-ADASJson -Path (Join-Path $proofDirectory 'intent-contract.json') -Value $intent
    Write-ADASJson -Path (Join-Path $proofDirectory 'risk-profile.json') -Value $riskProfile
    Write-ADASUtf8NoBom -Path (Join-Path $proofDirectory 'change.diff') -Text $diffText
    if ($diffBudgetExceeded) {
        # Fail-closed audit record: exact full-diff size/budget/hash metadata,
        # no diff content, no secrets. change.diff stays empty (nothing was truncated).
        Write-ADASJson -Path (Join-Path $proofDirectory 'change.diff.budget-exceeded-meta.json') -Value $acquisition
    }
