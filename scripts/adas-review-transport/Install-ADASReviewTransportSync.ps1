<#
.SYNOPSIS
Deterministic atomic install/sync of the canonical, git-tracked ADAS independent-review
control-plane unit into the live profile: module sections A + B (Imperial-ADAS.psm1) and,
optionally, the structured Get-ADASDiffText caller region (Invoke-ADASPipeline.ps1) derived
from the git-tracked canonical caller source (canonical-adas-caller-region.ps1, Task57).
Discipline: (1) boundaries — module regions located with the PowerShell AST (anchor +
successor, canonical-block or legacy mode; drift fails closed); the caller region by its
line-anchored start comment and single successor line, each exactly once; (2) canonical —
module source parses clean and carries EXACTLY the 13 canonical functions in order; caller
canonical parses clean and carries EXACTLY ONE structured call site (.text/.budgetExceeded),
the exceeded branch, no sentinel, no whole-object coercion; (3) pre-sync proof — per-file
hash/size/ACL, a hash-verified backup copy, untouched-region hashes; (4) atomic replace —
[IO.File]::Replace with the displaced witness hash-checked against the verified before-hash;
(5) Task57 rollback contract — a witness mismatch or a post-sync verification failure
restores the VERIFIED backup atomically and re-verifies the live hash; the report claims
intact ONLY when hash-proven; backups are never deleted; (6) post-sync proof — installed
regions extracted back and matched byte/normalized-hash against the canonical sources, 0
parser errors; (7) idempotent — byte-equal regions record a noop-identical proof.
Proofs carry only paths, hashes, sizes, counts and ACL lines (never key/review content).
-DryRun plans without modifying. -SkipParseVerify opts out of parse checks.
-FaultInjectReplaceBackupHashMismatch is TEST-ONLY: it corrupts the displaced witness by one
byte after each successful ReplaceFile so the rollback path is exercised deterministically.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ModulePath,
    [Parameter(Mandatory = $true)][string]$CanonicalPath,
    [string]$CallerPath = '',
    [string]$CallerCanonicalPath = '',
    [string]$BackupDir = '',
    [string]$ProofPath = '',
    [switch]$DryRun,
    [switch]$SkipParseVerify,
    [switch]$FaultInjectReplaceBackupHashMismatch
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'; $EXPECTED_SUCCESSOR_A = 'Get-ADASImpactMap'
$EXPECTED_SUCCESSOR_B = 'Get-ADASProofManifest'
$CANONICAL_FUNCTIONS_A = @('Get-ADASReviewModelContextWindow', 'Get-ADASReviewDiffBudget', 'Get-ADASDiffAcquisitionMeta', 'New-ADASDiffBudgetExceededResult', 'Get-ADASDiffText')
$CANONICAL_FUNCTIONS_B = @('New-ADASReviewAttemptRecord', 'Get-ADASReviewGateCompact', 'Get-ADASReviewDiffSections', 'Invoke-ADASDeepSeekCompletion', 'Test-ADASReviewContract', 'ConvertTo-ADASReviewContractObject', 'New-ADASReviewUnavailableResult', 'Invoke-ADASIndependentReview')
function Get-AdasSyncSha256Text {
    param([AllowEmptyString()][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$Text))) -replace '-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Get-AdasSyncSha256File {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Get-AdasSyncNormalizedText {
    param([AllowEmptyString()][string]$Text)
    return ([string]$Text) -replace "`r`n", "`n"
}
function Remove-AdasSyncBom {
    param([AllowEmptyString()][string]$Text)
    # ASCII-safe BOM strip (a literal U+FEFF would be mangled by PS 5.1 on BOM-less scripts).
    if ([string]$Text -and $Text[0] -eq [char]0xFEFF) { return $Text.Substring(1) }
    return $Text
}
function Get-AdasSyncAclSummary {
    param([Parameter(Mandatory = $true)][string]$Path)
    return @((& icacls.exe $Path 2>$null) | ForEach-Object { [string]$_ })
}
function Find-AdasSyncRegion {
    param([Parameter(Mandatory = $true)][string]$ModuleText, [Parameter(Mandatory = $true)][string[]]$BlockNames, [Parameter(Mandatory = $true)][string]$Successor, [Parameter(Mandatory = $true)][string]$Label)
    # Structural (AST) region location, never regex guessing; the region runs to the successor.
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($ModuleText, [ref]$tokens, [ref]$errors)
    if ($errors.Count -ne 0) { throw "INSTALL-FAIL-CLOSED: module has $($errors.Count) parser error(s); region $Label cannot be located safely." }
    $functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
    $anchorName = [string]$BlockNames[-1]; $anchorIndex = -1
    for ($i = 0; $i -lt $functions.Count; $i++) {
        if ([string]$functions[$i].Name -eq $anchorName) { $anchorIndex = $i; break }
    }
    if ($anchorIndex -lt 0) { throw "INSTALL-FAIL-CLOSED: $anchorName does not exist in the module; profile structure drifted, refusing to modify anything." }
    $n = $BlockNames.Count; $mode = 'legacy-block'; $startIndex = $anchorIndex
    if ($anchorIndex -ge $n - 1 -and [string]$functions[$anchorIndex - $n + 1].Name -eq $BlockNames[0]) {
        for ($i = 0; $i -lt $n; $i++) {
            $actualName = [string]$functions[$anchorIndex - $n + 1 + $i].Name
            if ($actualName -ne $BlockNames[$i]) { throw "INSTALL-FAIL-CLOSED: region $Label function #$($i + 1) is '$actualName', expected '$($BlockNames[$i])'; profile structure drifted." }
        }
        $mode = 'canonical-block'; $startIndex = $anchorIndex - $n + 1
    }
    $successorIndex = $anchorIndex + 1
    if ($successorIndex -ge $functions.Count) { throw "INSTALL-FAIL-CLOSED: no successor function after region $Label; profile structure drifted." }
    $successor = [string]$functions[$successorIndex].Name
    if ($successor -ne $Successor) { throw "INSTALL-FAIL-CLOSED: region $Label successor function is '$successor', expected '$Successor'; profile structure drifted." }
    $start = [int]$functions[$startIndex].Extent.StartOffset; $end = [int]$functions[$successorIndex].Extent.StartOffset
    if ($end -le $start) { throw "INSTALL-FAIL-CLOSED: region $Label boundaries are not ordered; profile structure drifted." }
    return [pscustomobject]@{ mode = $mode; start = $start; end = $end; successor = $successor }
}
function Split-AdasCanonicalSections {
    param([Parameter(Mandatory = $true)][string]$CanonicalText)
    # Canonical discipline: EXACTLY the 13 canonical functions (5 + 8) in canonical order;
    # section A = file start .. New-ADASReviewAttemptRecord, section B = that start .. file end.
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($CanonicalText, [ref]$tokens, [ref]$errors)
    if ($errors.Count -ne 0) { throw "INSTALL-FAIL-CLOSED: canonical source has $($errors.Count) parser error(s); refusing to sync a broken unit." }
    $functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
    $expectedAll = @($CANONICAL_FUNCTIONS_A) + @($CANONICAL_FUNCTIONS_B)
    if ($functions.Count -ne $expectedAll.Count) { throw "INSTALL-FAIL-CLOSED: canonical source has $($functions.Count) functions, expected exactly $($expectedAll.Count)." }
    for ($i = 0; $i -lt $expectedAll.Count; $i++) {
        $actualName = [string]$functions[$i].Name
        if ($actualName -ne $expectedAll[$i]) { throw "INSTALL-FAIL-CLOSED: canonical function #$($i + 1) is '$actualName', expected '$($expectedAll[$i])'." }
    }
    $sectionBStart = [int]$functions[$CANONICAL_FUNCTIONS_A.Count].Extent.StartOffset
    if ($sectionBStart -le 0) { throw 'INSTALL-FAIL-CLOSED: canonical section boundaries are not ordered.' }
    $sectionA = $CanonicalText.Substring(0, $sectionBStart); $sectionB = $CanonicalText.Substring($sectionBStart)
    return [pscustomobject]@{ sectionA = $sectionA; sectionB = $sectionB; sectionARawHash = Get-AdasSyncSha256Text $sectionA; sectionBRawHash = Get-AdasSyncSha256Text $sectionB; sectionANormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $sectionA); sectionBNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $sectionB) }
}
function Test-AdasSyncCallerCanonical {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    # Task57 canonical caller discipline: parses clean, EXACTLY ONE structured call site
    # (.text/.budgetExceeded), exceeded branch present, no sentinel, no whole-object coercion.
    if ([string]::IsNullOrWhiteSpace($Text)) { return 'caller canonical source is empty' }
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseInput($Text, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -ne 0) { return "caller canonical source has $($errors.Count) parser error(s); refusing to sync a broken unit." }
    if (([regex]::Matches($Text, 'Get-ADASDiffText')).Count -ne 1) { return 'caller canonical source must contain EXACTLY ONE Get-ADASDiffText call site.' }
    if (-not $Text.Contains('$acquisition = Get-ADASDiffText -GitPath $gitPath -WorktreePath $worktree -BeforeCommit $BeforeCommit -AfterCommit $AfterCommit -ReviewerModel @($reviewBudgetModels) -Truncated ([ref]$diffTruncated)')) { return 'caller canonical source must use the exact structured acquisition call.' }
    if (-not $Text.Contains('$diffText = [string]$acquisition.text') -or -not $Text.Contains('$diffBudgetExceeded = [bool]$acquisition.budgetExceeded')) { return 'caller canonical source must read the structured .text/.budgetExceeded properties only.' }
    if (-not $Text.Contains('change.diff.budget-exceeded-meta.json')) { return 'caller canonical source must carry the fail-closed exceeded branch.' }
    if ($Text.Contains('DIFF TRUNCATED BY ADAS')) { return 'caller canonical source must not rely on the legacy truncation sentinel.' }
    if (([regex]::Matches($Text, '\[string\]\s*\$acquisition(?![\.\[])')).Count -gt 0) { return 'caller canonical source must never string-coerce the whole acquisition object.' }
    return ''
}
function Find-AdasSyncCallerRegion {
    param([Parameter(Mandatory = $true)][string]$CallerText)
    # Marker-based caller-region location: start comment and single successor line each occur
    # exactly once; the region ends at the exceeded-branch closing brace. Markers are pure ASCII.
    $successorLine = 'Copy-Item -LiteralPath $TaskPath'
    $offsets = New-Object 'System.Collections.Generic.List[int]'
    $offsets.Add(0); $nl = 0
    while (($nl = $CallerText.IndexOf("`n", $nl + 1)) -ge 0) { $offsets.Add($nl + 1) }
    $startLine = -1; $successorIndex = -1
    for ($i = 0; $i -lt $offsets.Count; $i++) {
        $next = if ($i + 1 -lt $offsets.Count) { [int]$offsets[$i + 1] } else { $CallerText.Length }
        $trimmed = ($CallerText.Substring([int]$offsets[$i], $next - [int]$offsets[$i]) -replace "`r", '').Trim()
        if ($trimmed.StartsWith('# Task55') -and $trimmed.Contains('context-derived diff-acquisition budget')) {
            if ($startLine -ge 0) { throw 'INSTALL-FAIL-CLOSED: caller region start marker occurs more than once; profile structure drifted.' }
            $startLine = $i
        }
        if ($trimmed.StartsWith($successorLine)) {
            if ($successorIndex -ge 0) { throw 'INSTALL-FAIL-CLOSED: caller region successor line occurs more than once; profile structure drifted.' }
            $successorIndex = $i
        }
    }
    if ($startLine -lt 0) { throw 'INSTALL-FAIL-CLOSED: caller region start marker not found; profile structure drifted, refusing to modify anything.' }
    if ($successorIndex -lt 0) { throw 'INSTALL-FAIL-CLOSED: caller region successor line not found; profile structure drifted, refusing to modify anything.' }
    if ($successorIndex -le $startLine) { throw 'INSTALL-FAIL-CLOSED: caller region boundaries are not ordered; profile structure drifted.' }
    $start = [int]$offsets[$startLine]; $end = [int]$offsets[$successorIndex]
    $lastNonEmpty = @(($CallerText.Substring($start, $end - $start) -split "`n") | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) | Select-Object -Last 1
    if (([string]$lastNonEmpty).Trim() -ne '}') { throw 'INSTALL-FAIL-CLOSED: caller region does not end at the exceeded-branch closing brace; profile structure drifted.' }
    return [pscustomobject]@{ start = $start; end = $end }
}
function Restore-AdasSyncBackup {
    param([Parameter(Mandatory = $true)][string]$BackupPath, [Parameter(Mandatory = $true)][string]$TargetPath, [Parameter(Mandatory = $true)][string]$ExpectedHash, [Parameter(Mandatory = $true)][string]$ModuleDir)
    # Task57 atomic rollback: a working copy of the VERIFIED backup is swapped in via
    # ReplaceFile (the backup itself is preserved), then the live hash is re-verified.
    $sourceCopy = Join-Path $ModuleDir ("restore-source-$([Guid]::NewGuid().ToString('N')).tmp")
    $displaced = Join-Path $ModuleDir ("restore-displaced-$([Guid]::NewGuid().ToString('N')).tmp")
    try {
        Copy-Item -LiteralPath $BackupPath -Destination $sourceCopy -Force
        [IO.File]::Replace($sourceCopy, $TargetPath, $displaced)
        Remove-Item -LiteralPath $displaced -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $sourceCopy -Force -ErrorAction SilentlyContinue
        $restoredHash = Get-AdasSyncSha256File $TargetPath
        if ($restoredHash -ne $ExpectedHash) { return "restore hash $restoredHash does not equal the verified pre-sync hash $ExpectedHash" }
        return ''
    }
    catch {
        Remove-Item -LiteralPath $displaced -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $sourceCopy -Force -ErrorAction SilentlyContinue
        return "restore failed: $($_.Exception.Message)"
    }
}
function Write-AdasSyncProof {
    param([Parameter(Mandatory = $true)]$Proof, [Parameter(Mandatory = $true)][string]$Path)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    [IO.File]::WriteAllText($Path, ($Proof | ConvertTo-Json -Depth 6) + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}
function Resolve-AdasSyncFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}
$modulePath = Resolve-AdasSyncFullPath $ModulePath; $canonicalPath = Resolve-AdasSyncFullPath $CanonicalPath
$hasCallerSync = -not [string]::IsNullOrWhiteSpace($CallerPath) -or -not [string]::IsNullOrWhiteSpace($CallerCanonicalPath)
if ($hasCallerSync -and ([string]::IsNullOrWhiteSpace($CallerPath) -or [string]::IsNullOrWhiteSpace($CallerCanonicalPath))) { throw 'INSTALL-FAIL-CLOSED: -CallerPath and -CallerCanonicalPath must be provided together (both or neither).' }
$callerPath = if ($hasCallerSync) { Resolve-AdasSyncFullPath $CallerPath } else { '' }
$callerCanonicalPath = if ($hasCallerSync) { Resolve-AdasSyncFullPath $CallerCanonicalPath } else { '' }
$moduleDir = Split-Path -Parent $modulePath; $backupDir = if ($BackupDir) { Resolve-AdasSyncFullPath $BackupDir } else { Join-Path $moduleDir 'backups' }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
if (-not $ProofPath) { $ProofPath = Join-Path $moduleDir ("Imperial-ADAS.sync-proof.$stamp.json") }
$proofPath = Resolve-AdasSyncFullPath $ProofPath
$proof = [ordered]@{
    tool = 'Install-ADASReviewTransportSync'; dryRun = [bool]$DryRun
    modulePath = $modulePath; canonicalPath = $canonicalPath
    callerPath = $(if ($hasCallerSync) { $callerPath } else { $null }); callerCanonicalPath = $(if ($hasCallerSync) { $callerCanonicalPath } else { $null })
    generatedAt = (Get-Date).ToUniversalTime().ToString('o'); result = 'started'; failureReason = ''
    # Placeholder so the fail-closed catch can always record caller state; overwritten later.
    caller = [ordered]@{ action = $null; beforeHash = $null; beforeSize = 0; beforeAcl = @(); canonicalRawSha256 = ''; canonicalNormalizedSha256 = ''; installedRawSha256 = ''; installedNormalizedSha256 = ''; extractedRawSha256 = $null; extractedNormalizedSha256 = $null; regionByteEqual = $null; regionNormalizedEqual = $null; prefixSuffixPreserved = $null; singleCallSiteBefore = $false; singleCallSiteAfter = $null; plannedParseErrors = 0; syncedParseErrors = $null; backupPath = $null; backupHash = $null; afterHash = $null; replaceBackupWitnessed = $null }
}
$moduleReplaced = $false; $callerReplaced = $false
$moduleBackupPath = ''; $callerBackupPath = ''
$moduleReplaceWitness = ''; $callerReplaceWitness = ''
try {
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "INSTALL-FAIL-CLOSED: module file not found: $modulePath" }
    if (-not (Test-Path -LiteralPath $canonicalPath -PathType Leaf)) { throw "INSTALL-FAIL-CLOSED: canonical source file not found: $canonicalPath" }
    # --- Canonical source must itself be structurally sound before any sync ---
    $canonicalText = Remove-AdasSyncBom ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($canonicalPath)))
    $canonicalRawHash = Get-AdasSyncSha256File $canonicalPath; $canonicalNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $canonicalText)
    $sections = Split-AdasCanonicalSections -CanonicalText $canonicalText
    # --- Module before-state ---
    $moduleBytes = [IO.File]::ReadAllBytes($modulePath); $moduleBeforeHash = Get-AdasSyncSha256File $modulePath
    $moduleBeforeSize = (Get-Item -LiteralPath $modulePath).Length; $moduleBeforeAcl = Get-AdasSyncAclSummary $modulePath
    $hasBom = ($moduleBytes.Length -ge 3 -and $moduleBytes[0] -eq 0xEF -and $moduleBytes[1] -eq 0xBB -and $moduleBytes[2] -eq 0xBF)
    $moduleText = Remove-AdasSyncBom ([Text.Encoding]::UTF8.GetString($moduleBytes))
    $boundariesA = Find-AdasSyncRegion -ModuleText $moduleText -BlockNames $CANONICAL_FUNCTIONS_A -Successor $EXPECTED_SUCCESSOR_A -Label 'A'
    $boundariesB = Find-AdasSyncRegion -ModuleText $moduleText -BlockNames $CANONICAL_FUNCTIONS_B -Successor $EXPECTED_SUCCESSOR_B -Label 'B'
    if ([int]$boundariesB.start -lt [int]$boundariesA.end) { throw "INSTALL-FAIL-CLOSED: region B starts before region A ends (A end $($boundariesA.end), B start $($boundariesB.start)); regions overlap or are out of order." }
    $startA = [int]$boundariesA.start; $endA = [int]$boundariesA.end; $startB = [int]$boundariesB.start; $endB = [int]$boundariesB.end
    $prefixAText = $moduleText.Substring(0, $startA); $middleText = $moduleText.Substring($endA, $startB - $endA); $suffixBText = $moduleText.Substring($endB)
    $prefixAHash = Get-AdasSyncSha256Text $prefixAText; $middleHash = Get-AdasSyncSha256Text $middleText; $suffixBHash = Get-AdasSyncSha256Text $suffixBText
    $installedRegionAText = $moduleText.Substring($startA, $endA - $startA); $installedRegionBText = $moduleText.Substring($startB, $endB - $startB)
    $installedRegionARawHash = Get-AdasSyncSha256Text $installedRegionAText; $installedRegionANormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $installedRegionAText)
    $installedRegionBRawHash = Get-AdasSyncSha256Text $installedRegionBText; $installedRegionBNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $installedRegionBText)
    $newModuleText = $prefixAText + $sections.sectionA + $middleText + $sections.sectionB + $suffixBText; $byteEqual = ($newModuleText -ceq $moduleText)
    $action = if ($byteEqual) { 'noop-identical' } else { 'replace-both-regions' }
    # --- Planned module content must parse (fail-closed posture; -SkipParseVerify opts out) ---
    $plannedParseErrors = 0
    if (-not $SkipParseVerify) {
        $tokens = $null; $errors = $null
        [System.Management.Automation.Language.Parser]::ParseInput($newModuleText, [ref]$tokens, [ref]$errors) | Out-Null
        $plannedParseErrors = $errors.Count
        if ($plannedParseErrors -ne 0) { throw "INSTALL-FAIL-CLOSED: planned module content has $plannedParseErrors parser error(s); refusing to sync." }
    }
    # --- Caller canonical discipline + before-state (Task57) ---
    $callerAction = ''; $callerBeforeHash = $null; $callerBeforeSize = 0; $callerBeforeAcl = @(); $callerPrefixHash = ''; $callerSuffixHash = ''; $callerInstalledRawHash = ''; $callerInstalledNormalizedHash = ''
    $callerSingleCallSiteBefore = $false; $callerPlannedParseErrors = 0; $callerCanonicalRawHash = ''; $callerCanonicalNormalizedHash = ''
    if ($hasCallerSync) {
        if (-not (Test-Path -LiteralPath $callerPath -PathType Leaf)) { throw "INSTALL-FAIL-CLOSED: caller file not found: $callerPath" }
        if (-not (Test-Path -LiteralPath $callerCanonicalPath -PathType Leaf)) { throw "INSTALL-FAIL-CLOSED: caller canonical source file not found: $callerCanonicalPath" }
        $callerCanonicalText = Remove-AdasSyncBom ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($callerCanonicalPath)))
        $callerCanonicalRawHash = Get-AdasSyncSha256File $callerCanonicalPath; $callerCanonicalNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $callerCanonicalText)
        $callerCanonicalError = Test-AdasSyncCallerCanonical -Text $callerCanonicalText
        if ($callerCanonicalError) { throw "INSTALL-FAIL-CLOSED: $callerCanonicalError" }
        $callerBytes = [IO.File]::ReadAllBytes($callerPath); $callerBeforeHash = Get-AdasSyncSha256File $callerPath
        $callerBeforeSize = (Get-Item -LiteralPath $callerPath).Length; $callerBeforeAcl = Get-AdasSyncAclSummary $callerPath
        $callerText = Remove-AdasSyncBom ([Text.Encoding]::UTF8.GetString($callerBytes))
        $callerCallSiteCount = ([regex]::Matches($callerText, 'Get-ADASDiffText')).Count
        if ($callerCallSiteCount -ne 1) { throw "INSTALL-FAIL-CLOSED: live caller has $callerCallSiteCount Get-ADASDiffText occurrence(s), expected exactly ONE call site; refusing to sync." }
        $callerSingleCallSiteBefore = $true; $callerRegion = Find-AdasSyncCallerRegion -CallerText $callerText
        $callerPrefixText = $callerText.Substring(0, [int]$callerRegion.start); $callerSuffixText = $callerText.Substring([int]$callerRegion.end)
        $callerPrefixHash = Get-AdasSyncSha256Text $callerPrefixText; $callerSuffixHash = Get-AdasSyncSha256Text $callerSuffixText
        $installedCallerRegion = $callerText.Substring([int]$callerRegion.start, [int]$callerRegion.end - [int]$callerRegion.start)
        $callerInstalledRawHash = Get-AdasSyncSha256Text $installedCallerRegion; $callerInstalledNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $installedCallerRegion)
        $newCallerText = $callerPrefixText + $callerCanonicalText + $callerSuffixText; $callerByteEqual = ($newCallerText -ceq $callerText)
        $callerAction = if ($callerByteEqual) { 'noop-identical' } else { 'replace-caller-region' }
        if (-not $SkipParseVerify) {
            $tokens = $null; $errors = $null
            [System.Management.Automation.Language.Parser]::ParseInput($newCallerText, [ref]$tokens, [ref]$errors) | Out-Null
            $callerPlannedParseErrors = $errors.Count
            if ($callerPlannedParseErrors -ne 0) { throw "INSTALL-FAIL-CLOSED: planned caller content has $callerPlannedParseErrors parser error(s); refusing to sync." }
        }
    }
    $proof.mode = [string]$boundariesB.mode; $proof.successor = [string]$boundariesB.successor; $proof.action = $action
    $proof.moduleBeforeHash = $moduleBeforeHash; $proof.moduleBeforeSize = $moduleBeforeSize; $proof.moduleBeforeAcl = @($moduleBeforeAcl)
    $proof.prefixAHash = $prefixAHash; $proof.middleHash = $middleHash; $proof.suffixBHash = $suffixBHash
    $proof.canonical = [ordered]@{ rawSha256 = $canonicalRawHash; normalizedSha256 = $canonicalNormalizedHash; sectionARawSha256 = [string]$sections.sectionARawHash; sectionANormalizedSha256 = [string]$sections.sectionANormalizedHash; sectionBRawSha256 = [string]$sections.sectionBRawHash; sectionBNormalizedSha256 = [string]$sections.sectionBNormalizedHash; sectionACharacterCount = $sections.sectionA.Length; sectionBCharacterCount = $sections.sectionB.Length }
    $proof.regionA = [ordered]@{ mode = [string]$boundariesA.mode; successor = [string]$boundariesA.successor; installedRawSha256 = $installedRegionARawHash; installedNormalizedSha256 = $installedRegionANormalizedHash; extractedRawSha256 = $null; extractedNormalizedSha256 = $null; blockByteEqual = $null; blockNormalizedEqual = $null }
    $proof.regionB = [ordered]@{ mode = [string]$boundariesB.mode; successor = [string]$boundariesB.successor; installedRawSha256 = $installedRegionBRawHash; installedNormalizedSha256 = $installedRegionBNormalizedHash; extractedRawSha256 = $null; extractedNormalizedSha256 = $null; blockByteEqual = $null; blockNormalizedEqual = $null }
    $proof.plannedParseErrors = $plannedParseErrors; $proof.backupPath = $null; $proof.backupHash = $null
    $proof.moduleAfterHash = $null; $proof.prefixMiddleSuffixPreserved = $null; $proof.syncedParseErrors = $null; $proof.rollbackPerformed = $false
    $proof.rollbackError = ''; $proof.replaceBackupWitnessed = $null; $proof.replaceWitnessHash = $null; $proof.replaceWitnessPreserved = $null
    $proof.caller = [ordered]@{ action = $(if ($hasCallerSync) { $callerAction } else { $null }); beforeHash = $callerBeforeHash; beforeSize = $callerBeforeSize; beforeAcl = @($callerBeforeAcl); canonicalRawSha256 = $callerCanonicalRawHash; canonicalNormalizedSha256 = $callerCanonicalNormalizedHash; installedRawSha256 = $callerInstalledRawHash; installedNormalizedSha256 = $callerInstalledNormalizedHash; extractedRawSha256 = $null; extractedNormalizedSha256 = $null; regionByteEqual = $null; regionNormalizedEqual = $null; prefixSuffixPreserved = $null; singleCallSiteBefore = $callerSingleCallSiteBefore; singleCallSiteAfter = $null; plannedParseErrors = $callerPlannedParseErrors; syncedParseErrors = $null; backupPath = $null; backupHash = $null; afterHash = $null; replaceBackupWitnessed = $null }
    if ($DryRun) {
        $proof.result = 'dry-run-plan'; $proof.moduleAfterHash = $moduleBeforeHash
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "DRY-RUN OK: action=$action callerAction=$callerAction modeA=$($boundariesA.mode) modeB=$($boundariesB.mode); no file was modified. proof=$proofPath"
        exit 0
    }
    # --- Real sync (idempotent); verified pre-sync backups first ---
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $moduleBackupPath = Join-Path $backupDir ("Imperial-ADAS.psm1.pre-sync-$($moduleBeforeHash.Substring(0, 8))-$stamp.bak")
    Copy-Item -LiteralPath $modulePath -Destination $moduleBackupPath -Force
    $backupHash = Get-AdasSyncSha256File $moduleBackupPath
    if ($backupHash -ne $moduleBeforeHash) {
        Remove-Item -LiteralPath $moduleBackupPath -Force -ErrorAction SilentlyContinue
        throw "INSTALL-FAIL-CLOSED: module backup hash $backupHash does not equal the before-hash $moduleBeforeHash; module was not modified."
    }
    $proof.backupPath = $moduleBackupPath; $proof.backupHash = $backupHash
    if ($hasCallerSync -and $callerAction -ne 'noop-identical') {
        $callerBackupPath = Join-Path $backupDir ("Invoke-ADASPipeline.ps1.pre-sync-$($callerBeforeHash.Substring(0, 8))-$stamp.bak")
        Copy-Item -LiteralPath $callerPath -Destination $callerBackupPath -Force
        $callerBackupHash = Get-AdasSyncSha256File $callerBackupPath
        if ($callerBackupHash -ne $callerBeforeHash) {
            Remove-Item -LiteralPath $callerBackupPath -Force -ErrorAction SilentlyContinue
            throw "INSTALL-FAIL-CLOSED: caller backup hash $callerBackupHash does not equal the caller before-hash $callerBeforeHash; caller was not modified."
        }
        $proof.caller.backupPath = $callerBackupPath; $proof.caller.backupHash = $callerBackupHash
    }
    $noopAll = ($action -eq 'noop-identical') -and ((-not $hasCallerSync) -or ($callerAction -eq 'noop-identical'))
    if ($noopAll) {
        $proof.result = 'synced-noop-identical'; $proof.moduleAfterHash = $moduleBeforeHash
        $proof.regionA.blockByteEqual = $true; $proof.regionA.blockNormalizedEqual = $true; $proof.regionB.blockByteEqual = $true; $proof.regionB.blockNormalizedEqual = $true
        $proof.prefixMiddleSuffixPreserved = $true; $proof.syncedParseErrors = $plannedParseErrors
        if ($hasCallerSync) { $proof.caller.regionByteEqual = $true; $proof.caller.regionNormalizedEqual = $true; $proof.caller.prefixSuffixPreserved = $true; $proof.caller.singleCallSiteAfter = $callerSingleCallSiteBefore }
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "SYNC OK (noop-identical): installed sections and caller region already equal the canonical sources. proof=$proofPath"
        exit 0
    }
    # --- Atomic swap via ReplaceFile. The displaced previous file is hash-checked against the
    # verified before-hash (atomicity witness); a mismatch throws and the shared catch restores
    # the VERIFIED pre-sync backup atomically (Task57 rollback). ---
    $encoding = if ($hasBom) { New-Object Text.UTF8Encoding($true) } else { New-Object Text.UTF8Encoding($false) }
    if ($action -ne 'noop-identical') {
        $tempPath = Join-Path $moduleDir ("Imperial-ADAS.psm1.sync-tmp-$([Guid]::NewGuid().ToString('N')).tmp")
        $moduleReplaceWitness = Join-Path $moduleDir ("Imperial-ADAS.psm1.replace-backup-$([Guid]::NewGuid().ToString('N')).bak")
        [IO.File]::WriteAllText($tempPath, $newModuleText, $encoding)
        try {
            [IO.File]::Replace($tempPath, $modulePath, $moduleReplaceWitness)
            $moduleReplaced = $true
            if ($FaultInjectReplaceBackupHashMismatch) {
                # TEST-ONLY deterministic fault injection for the post-replace witness branch.
                [IO.File]::AppendAllText($moduleReplaceWitness, 'x', (New-Object Text.UTF8Encoding($false)))
            }
            $replaceBackupHash = Get-AdasSyncSha256File $moduleReplaceWitness
            if ($replaceBackupHash -ne $moduleBeforeHash) { throw "replace-backup witness hash $replaceBackupHash does not equal the verified before-hash $moduleBeforeHash." }
            Remove-Item -LiteralPath $moduleReplaceWitness -Force -ErrorAction SilentlyContinue
            $proof.replaceBackupWitnessed = $true; $proof.replaceWitnessHash = $replaceBackupHash
        }
        finally { Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue }
    }
    if ($hasCallerSync -and $callerAction -ne 'noop-identical') {
        $callerEncoding = if ($callerBytes.Length -ge 3 -and $callerBytes[0] -eq 0xEF -and $callerBytes[1] -eq 0xBB -and $callerBytes[2] -eq 0xBF) { New-Object Text.UTF8Encoding($true) } else { New-Object Text.UTF8Encoding($false) }
        $callerTempPath = Join-Path $moduleDir ("Invoke-ADASPipeline.ps1.sync-tmp-$([Guid]::NewGuid().ToString('N')).tmp")
        $callerReplaceWitness = Join-Path $moduleDir ("Invoke-ADASPipeline.ps1.replace-backup-$([Guid]::NewGuid().ToString('N')).bak")
        [IO.File]::WriteAllText($callerTempPath, $newCallerText, $callerEncoding)
        try {
            [IO.File]::Replace($callerTempPath, $callerPath, $callerReplaceWitness)
            $callerReplaced = $true
            if ($FaultInjectReplaceBackupHashMismatch) { [IO.File]::AppendAllText($callerReplaceWitness, 'x', (New-Object Text.UTF8Encoding($false))) }
            $callerReplaceBackupHash = Get-AdasSyncSha256File $callerReplaceWitness
            if ($callerReplaceBackupHash -ne $callerBeforeHash) { throw "caller replace-backup witness hash $callerReplaceBackupHash does not equal the verified caller before-hash $callerBeforeHash." }
            Remove-Item -LiteralPath $callerReplaceWitness -Force -ErrorAction SilentlyContinue
            $proof.caller.replaceBackupWitnessed = $true
        }
        finally { Remove-Item -LiteralPath $callerTempPath -Force -ErrorAction SilentlyContinue }
    }
    # --- Post-sync verification: extract back, compare, parse; any mismatch rolls back ---
    if ($action -ne 'noop-identical') {
        $afterText = Remove-AdasSyncBom ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($modulePath)))
        $afterBoundariesA = Find-AdasSyncRegion -ModuleText $afterText -BlockNames $CANONICAL_FUNCTIONS_A -Successor $EXPECTED_SUCCESSOR_A -Label 'A'
        $afterBoundariesB = Find-AdasSyncRegion -ModuleText $afterText -BlockNames $CANONICAL_FUNCTIONS_B -Successor $EXPECTED_SUCCESSOR_B -Label 'B'
        if ([string]$afterBoundariesA.mode -ne 'canonical-block') { throw "INSTALL-FAIL-CLOSED: post-sync region A mode is '$($afterBoundariesA.mode)', expected 'canonical-block'." }
        if ([string]$afterBoundariesB.mode -ne 'canonical-block') { throw "INSTALL-FAIL-CLOSED: post-sync region B mode is '$($afterBoundariesB.mode)', expected 'canonical-block'." }
        $afterRegionA = $afterText.Substring([int]$afterBoundariesA.start, [int]$afterBoundariesA.end - [int]$afterBoundariesA.start); $afterRegionB = $afterText.Substring([int]$afterBoundariesB.start, [int]$afterBoundariesB.end - [int]$afterBoundariesB.start)
        $afterPrefixA = $afterText.Substring(0, [int]$afterBoundariesA.start); $afterMiddle = $afterText.Substring([int]$afterBoundariesA.end, [int]$afterBoundariesB.start - [int]$afterBoundariesA.end); $afterSuffixB = $afterText.Substring([int]$afterBoundariesB.end)
        $afterRegionARawHash = Get-AdasSyncSha256Text $afterRegionA; $afterRegionANormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $afterRegionA)
        $afterRegionBRawHash = Get-AdasSyncSha256Text $afterRegionB; $afterRegionBNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $afterRegionB)
        $regionAByteEqual = ($afterRegionARawHash -eq [string]$sections.sectionARawHash); $regionANormalizedEqual = ($afterRegionANormalizedHash -eq [string]$sections.sectionANormalizedHash)
        $regionBByteEqual = ($afterRegionBRawHash -eq [string]$sections.sectionBRawHash); $regionBNormalizedEqual = ($afterRegionBNormalizedHash -eq [string]$sections.sectionBNormalizedHash)
        $prefixMiddleSuffixPreserved = ((Get-AdasSyncSha256Text $afterPrefixA) -eq $prefixAHash -and (Get-AdasSyncSha256Text $afterMiddle) -eq $middleHash -and (Get-AdasSyncSha256Text $afterSuffixB) -eq $suffixBHash)
        $syncedParseErrors = 0
        if (-not $SkipParseVerify) {
            # ParseInput on the UTF-8-decoded text: ParseFile would misread BOM-less UTF-8.
            $tokens = $null; $errors = $null
            [System.Management.Automation.Language.Parser]::ParseInput($afterText, [ref]$tokens, [ref]$errors) | Out-Null
            $syncedParseErrors = $errors.Count
        }
        if (-not $regionANormalizedEqual) { throw "INSTALL-FAIL-CLOSED: extracted installed region A normalized hash $afterRegionANormalizedHash != canonical $($sections.sectionANormalizedHash)." }
        if (-not $regionBNormalizedEqual) { throw "INSTALL-FAIL-CLOSED: extracted installed region B normalized hash $afterRegionBNormalizedHash != canonical $($sections.sectionBNormalizedHash)." }
        if (-not $prefixMiddleSuffixPreserved) { throw 'INSTALL-FAIL-CLOSED: prefix/middle/suffix hashes changed during sync; only the two named regions may change.' }
        if ($syncedParseErrors -ne 0) { throw "INSTALL-FAIL-CLOSED: synced module has $syncedParseErrors parser error(s)." }
        $moduleAfterHash = Get-AdasSyncSha256File $modulePath; $proof.moduleAfterHash = $moduleAfterHash
        $proof.regionA.extractedRawSha256 = $afterRegionARawHash; $proof.regionA.extractedNormalizedSha256 = $afterRegionANormalizedHash
        $proof.regionA.blockByteEqual = [bool]$regionAByteEqual; $proof.regionA.blockNormalizedEqual = [bool]$regionANormalizedEqual
        $proof.regionB.extractedRawSha256 = $afterRegionBRawHash; $proof.regionB.extractedNormalizedSha256 = $afterRegionBNormalizedHash
        $proof.regionB.blockByteEqual = [bool]$regionBByteEqual; $proof.regionB.blockNormalizedEqual = [bool]$regionBNormalizedEqual
        $proof.prefixMiddleSuffixPreserved = [bool]$prefixMiddleSuffixPreserved; $proof.syncedParseErrors = $syncedParseErrors
    }
    elseif ($action -eq 'noop-identical') {
        $proof.moduleAfterHash = $moduleBeforeHash; $proof.regionA.blockByteEqual = $true; $proof.regionA.blockNormalizedEqual = $true; $proof.regionB.blockByteEqual = $true; $proof.regionB.blockNormalizedEqual = $true
        $proof.prefixMiddleSuffixPreserved = $true; $proof.syncedParseErrors = $plannedParseErrors
    }
    if ($hasCallerSync -and $callerAction -ne 'noop-identical') {
        $callerAfterText = Remove-AdasSyncBom ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($callerPath)))
        $callerAfterRegion = Find-AdasSyncCallerRegion -CallerText $callerAfterText
        $afterCallerRegion = $callerAfterText.Substring([int]$callerAfterRegion.start, [int]$callerAfterRegion.end - [int]$callerAfterRegion.start)
        $afterCallerPrefix = $callerAfterText.Substring(0, [int]$callerAfterRegion.start); $afterCallerSuffix = $callerAfterText.Substring([int]$callerAfterRegion.end)
        $afterCallerRawHash = Get-AdasSyncSha256Text $afterCallerRegion; $afterCallerNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $afterCallerRegion)
        $callerRegionByteEqual = ($afterCallerRawHash -eq $callerCanonicalRawHash); $callerRegionNormalizedEqual = ($afterCallerNormalizedHash -eq $callerCanonicalNormalizedHash)
        $callerPrefixSuffixPreserved = ((Get-AdasSyncSha256Text $afterCallerPrefix) -eq $callerPrefixHash -and (Get-AdasSyncSha256Text $afterCallerSuffix) -eq $callerSuffixHash)
        $callerCallSiteCount = ([regex]::Matches($callerAfterText, 'Get-ADASDiffText')).Count
        $callerSyncedParseErrors = 0
        if (-not $SkipParseVerify) {
            $tokens = $null; $errors = $null
            [System.Management.Automation.Language.Parser]::ParseInput($callerAfterText, [ref]$tokens, [ref]$errors) | Out-Null
            $callerSyncedParseErrors = $errors.Count
        }
        if (-not $callerRegionNormalizedEqual) { throw "INSTALL-FAIL-CLOSED: extracted installed caller region normalized hash $afterCallerNormalizedHash != canonical $callerCanonicalNormalizedHash." }
        if (-not $callerPrefixSuffixPreserved) { throw 'INSTALL-FAIL-CLOSED: caller prefix/suffix hashes changed during sync; only the caller region may change.' }
        if ($callerCallSiteCount -ne 1) { throw "INSTALL-FAIL-CLOSED: synced caller has $callerCallSiteCount Get-ADASDiffText occurrence(s), expected exactly ONE call site." }
        if ($callerSyncedParseErrors -ne 0) { throw "INSTALL-FAIL-CLOSED: synced caller has $callerSyncedParseErrors parser error(s)." }
        $proof.caller.extractedRawSha256 = $afterCallerRawHash; $proof.caller.extractedNormalizedSha256 = $afterCallerNormalizedHash
        $proof.caller.regionByteEqual = [bool]$callerRegionByteEqual; $proof.caller.regionNormalizedEqual = [bool]$callerRegionNormalizedEqual
        $proof.caller.prefixSuffixPreserved = [bool]$callerPrefixSuffixPreserved; $proof.caller.singleCallSiteAfter = ($callerCallSiteCount -eq 1)
        $proof.caller.syncedParseErrors = $callerSyncedParseErrors; $proof.caller.afterHash = Get-AdasSyncSha256File $callerPath
    }
    elseif ($hasCallerSync) {
        $proof.caller.afterHash = $callerBeforeHash; $proof.caller.regionByteEqual = $true; $proof.caller.regionNormalizedEqual = $true
        $proof.caller.prefixSuffixPreserved = $true; $proof.caller.singleCallSiteAfter = $callerSingleCallSiteBefore
    }
    $proof.result = 'synced-ok'
    Write-AdasSyncProof -Proof $proof -Path $proofPath
    Write-Output "SYNC OK: action=$action callerAction=$callerAction regionAByteEqual=$($proof.regionA.blockByteEqual) regionANormalizedEqual=$($proof.regionA.blockNormalizedEqual) regionBByteEqual=$($proof.regionB.blockByteEqual) regionBNormalizedEqual=$($proof.regionB.blockNormalizedEqual) prefixMiddleSuffixPreserved=$($proof.prefixMiddleSuffixPreserved) parseErrors=$($proof.syncedParseErrors) callerRegionByteEqual=$($proof.caller.regionByteEqual) callerRegionNormalizedEqual=$($proof.caller.regionNormalizedEqual) callerSingleCallSiteAfter=$($proof.caller.singleCallSiteAfter). proof=$proofPath"
    exit 0
}
catch {
    # Task57 rollback contract: restore every replaced file from its VERIFIED pre-sync
    # backup atomically and re-verify the live hash. The report claims a target intact ONLY
    # when the restore is hash-proven; backups are never deleted.
    $rollbackErrors = New-Object 'System.Collections.Generic.List[string]'
    if ($callerReplaced -and $callerBackupPath) { $callerRollbackError = Restore-AdasSyncBackup -BackupPath $callerBackupPath -TargetPath $callerPath -ExpectedHash $callerBeforeHash -ModuleDir $moduleDir; if ($callerRollbackError) { $rollbackErrors.Add("caller: $callerRollbackError") } }
    if ($moduleReplaced -and $moduleBackupPath) { $moduleRollbackError = Restore-AdasSyncBackup -BackupPath $moduleBackupPath -TargetPath $modulePath -ExpectedHash $moduleBeforeHash -ModuleDir $moduleDir; if ($moduleRollbackError) { $rollbackErrors.Add("module: $moduleRollbackError") } }
    $proof.result = 'failed-closed-rolled-back'; $proof.failureReason = $_.Exception.Message
    $proof.rollbackPerformed = ($moduleReplaced -or $callerReplaced); $proof.rollbackError = ($rollbackErrors -join '; ')
    $proof.moduleAfterHash = if (Test-Path -LiteralPath $modulePath) { Get-AdasSyncSha256File $modulePath } else { $null }
    $proof.caller.afterHash = if ($hasCallerSync -and (Test-Path -LiteralPath $callerPath)) { Get-AdasSyncSha256File $callerPath } else { $null }
    $proof.replaceWitnessPreserved = if ($moduleReplaceWitness -and (Test-Path -LiteralPath $moduleReplaceWitness)) { $true } else { $null }
    $proof.caller.replaceWitnessPreserved = if ($hasCallerSync -and $callerReplaceWitness -and (Test-Path -LiteralPath $callerReplaceWitness)) { $true } else { $null }
    Write-AdasSyncProof -Proof $proof -Path $proofPath
    $moduleProven = ($proof.moduleAfterHash -eq $moduleBeforeHash)
    $callerProven = ((-not $hasCallerSync) -or ($proof.caller.afterHash -eq $callerBeforeHash))
    $restoreProven = ($proof.rollbackError -eq '' -and $moduleProven -and $callerProven)
    $targetState = if ($restoreProven) { 'restored and hash-verified to the pre-sync state' } else { 'NOT PROVEN intact' }
    [Console]::Error.WriteLine("INSTALL-FAIL-CLOSED: $($_.Exception.Message) rollbackPerformed=$($proof.rollbackPerformed) rollbackError='$($proof.rollbackError)' moduleAfterHash=$($proof.moduleAfterHash) callerAfterHash=$($proof.caller.afterHash) targetState=$targetState proof=$proofPath")
    exit 1
}
