<#
.SYNOPSIS
Deterministic atomic install/sync of the canonical, git-tracked ADAS
independent-review control-plane unit into the live profile module
(pro\bin\Imperial-ADAS.psm1, outside the git worktree).

The canonical tracked source (Imperial-ADAS-ReviewTransport.ps1) carries TWO
canonical sections in one file: Section A (Task55/56 diff acquisition,
Get-ADASReviewModelContextWindow .. Get-ADASDiffText, successor
Get-ADASImpactMap) and Section B (Task52-54 independent review,
New-ADASReviewAttemptRecord .. Invoke-ADASIndependentReview, successor
Get-ADASProofManifest). The installer inserts exactly those two sections into
the two named regions of the profile module in ONE atomic swap and proves
byte/normalized-hash equality afterwards. Nothing else in the profile may change.

Guarantees: (1) boundary discipline — both regions located structurally with the
PowerShell AST, never regex guessing; each region is located by its anchor
function (Get-ADASDiffText / Invoke-ADASIndependentReview) as the full canonical
block around the anchor or the legacy single-function region, up to the expected
successor; duplication, reordering, overlap or successor drift fails closed;
(2) canonical discipline — the source must parse with 0 errors and contain
EXACTLY the 13 canonical functions (5 + 8) in canonical order (section A = file
start .. start of New-ADASReviewAttemptRecord, section B = that start .. file
end); (3) pre-sync proof — module SHA-256, size, ACL (icacls), a timestamped
backup copy whose hash must equal the before-hash, and prefix/middle/suffix
SHA-256 of the untouched regions; (4) atomic replace — temp file in the module
directory swapped in with [IO.File]::Replace (Windows ReplaceFile); (5) post-sync
proof — both installed sections extracted back and matched byte-identically or
by normalized (CRLF-insensitive) SHA-256 against the canonical sections, prefix/
middle/suffix hashes unchanged, module parses with 0 errors; any mismatch
restores the backup (fail-closed rollback) and exits nonzero; (6) idempotent —
when both installed sections already equal the canonical source the sync records
a noop-identical proof and changes nothing.

The installer never reads, copies or logs any key file, request body, review
content or reasoning trace: proofs carry only paths, hashes, sizes, counts and
ACL lines. Dry-run (-DryRun) computes and reports the full plan without touching
the module. -SkipParseVerify opts out of the parse verification (default on,
fail-closed).

.PARAMETER ModulePath
The live profile module (pro\bin\Imperial-ADAS.psm1).

.PARAMETER CanonicalPath
The git-tracked canonical unit (Imperial-ADAS-ReviewTransport.ps1).

.PARAMETER BackupDir
Backup directory; default <module dir>\backups.

.PARAMETER ProofPath
Proof JSON output path; default <module dir>\Imperial-ADAS.sync-proof.<timestamp>.json.

.PARAMETER DryRun
Compute the plan (boundaries, hashes, action) without modifying anything.

.PARAMETER SkipParseVerify
Do not require 0 PowerShell parser errors on the planned/synced module.
The default (parse-verify on) is the safe, fail-closed posture.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ModulePath,
    [Parameter(Mandatory = $true)][string]$CanonicalPath,
    [string]$BackupDir = '',
    [string]$ProofPath = '',
    [switch]$DryRun,
    [switch]$SkipParseVerify
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'; $EXPECTED_SUCCESSOR_A = 'Get-ADASImpactMap'
$EXPECTED_SUCCESSOR_B = 'Get-ADASProofManifest'
$CANONICAL_FUNCTIONS_A = @(
    'Get-ADASReviewModelContextWindow', 'Get-ADASReviewDiffBudget', 'Get-ADASDiffAcquisitionMeta',
    'New-ADASDiffBudgetExceededResult', 'Get-ADASDiffText'
)
$CANONICAL_FUNCTIONS_B = @(
    'New-ADASReviewAttemptRecord', 'Get-ADASReviewGateCompact', 'Get-ADASReviewDiffSections',
    'Invoke-ADASDeepSeekCompletion', 'Test-ADASReviewContract', 'ConvertTo-ADASReviewContractObject',
    'New-ADASReviewUnavailableResult', 'Invoke-ADASIndependentReview'
)
function Get-AdasSyncSha256Text {
    param([AllowEmptyString()][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$Text))) -replace '-', '').ToLowerInvariant()
    }
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
function Get-AdasSyncAclSummary {
    param([Parameter(Mandatory = $true)][string]$Path)
    $lines = @(& icacls.exe $Path 2>$null)
    return @($lines | ForEach-Object { [string]$_ })
}
function Find-AdasSyncRegion {
    param([Parameter(Mandatory = $true)][string]$ModuleText, [Parameter(Mandatory = $true)][string[]]$BlockNames, [Parameter(Mandatory = $true)][string]$Successor, [Parameter(Mandatory = $true)][string]$Label)
    # Structural (AST) region location, never regex guessing. BlockNames is the canonical
    # ordered function sequence of the region; its LAST name is the anchor function the region
    # ends with. The region is the whole canonical block around the anchor, or the legacy
    # single-function region, up to the successor function that follows it in document order.
    # The successor must be exactly $Successor; any drift fails closed.
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($ModuleText, [ref]$tokens, [ref]$errors)
    if ($errors.Count -ne 0) {
        throw "INSTALL-FAIL-CLOSED: module has $($errors.Count) parser error(s); region $Label cannot be located safely."
    }
    $functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
    $anchorName = [string]$BlockNames[-1]; $anchorIndex = -1
    for ($i = 0; $i -lt $functions.Count; $i++) {
        if ([string]$functions[$i].Name -eq $anchorName) { $anchorIndex = $i; break }
    }
    if ($anchorIndex -lt 0) {
        throw "INSTALL-FAIL-CLOSED: $anchorName does not exist in the module; profile structure drifted, refusing to modify anything."
    }
    $n = $BlockNames.Count; $mode = 'legacy-block'
    $startIndex = $anchorIndex
    if ($anchorIndex -ge $n - 1 -and [string]$functions[$anchorIndex - $n + 1].Name -eq $BlockNames[0]) {
        for ($i = 0; $i -lt $n; $i++) {
            $actualName = [string]$functions[$anchorIndex - $n + 1 + $i].Name
            if ($actualName -ne $BlockNames[$i]) {
                throw "INSTALL-FAIL-CLOSED: region $Label function #$($i + 1) is '$actualName', expected '$($BlockNames[$i])'; profile structure drifted."
            }
        }
        $mode = 'canonical-block'; $startIndex = $anchorIndex - $n + 1
    }
    $successorIndex = $anchorIndex + 1
    if ($successorIndex -ge $functions.Count) {
        throw "INSTALL-FAIL-CLOSED: no successor function after region $Label; profile structure drifted."
    }
    $successor = [string]$functions[$successorIndex].Name
    if ($successor -ne $Successor) {
        throw "INSTALL-FAIL-CLOSED: region $Label successor function is '$successor', expected '$Successor'; profile structure drifted."
    }
    $start = [int]$functions[$startIndex].Extent.StartOffset; $end = [int]$functions[$successorIndex].Extent.StartOffset
    if ($end -le $start) {
        throw "INSTALL-FAIL-CLOSED: region $Label boundaries are not ordered; profile structure drifted."
    }
    return [pscustomobject]@{ mode = $mode; start = $start; end = $end; successor = $successor }
}
function Split-AdasCanonicalSections {
    param([Parameter(Mandatory = $true)][string]$CanonicalText)
    # Canonical discipline: the source must contain EXACTLY the 13 canonical functions
    # (5 acquisition + 8 review) in canonical order. Section A = file start .. start of
    # New-ADASReviewAttemptRecord; section B = that start .. file end. Any extra/missing/
    # reordered function fails closed.
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($CanonicalText, [ref]$tokens, [ref]$errors)
    if ($errors.Count -ne 0) {
        throw "INSTALL-FAIL-CLOSED: canonical source has $($errors.Count) parser error(s); refusing to sync a broken unit."
    }
    $functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
    $expectedAll = @($CANONICAL_FUNCTIONS_A) + @($CANONICAL_FUNCTIONS_B)
    if ($functions.Count -ne $expectedAll.Count) {
        throw "INSTALL-FAIL-CLOSED: canonical source has $($functions.Count) functions, expected exactly $($expectedAll.Count)."
    }
    for ($i = 0; $i -lt $expectedAll.Count; $i++) {
        $actualName = [string]$functions[$i].Name
        if ($actualName -ne $expectedAll[$i]) {
            throw "INSTALL-FAIL-CLOSED: canonical function #$($i + 1) is '$actualName', expected '$($expectedAll[$i])'."
        }
    }
    $sectionBStart = [int]$functions[$CANONICAL_FUNCTIONS_A.Count].Extent.StartOffset
    if ($sectionBStart -le 0) {
        throw 'INSTALL-FAIL-CLOSED: canonical section boundaries are not ordered.'
    }
    $sectionA = $CanonicalText.Substring(0, $sectionBStart); $sectionB = $CanonicalText.Substring($sectionBStart)
    return [pscustomobject]@{
        sectionA = $sectionA
        sectionB = $sectionB
        sectionARawHash = Get-AdasSyncSha256Text $sectionA
        sectionBRawHash = Get-AdasSyncSha256Text $sectionB
        sectionANormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $sectionA)
        sectionBNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $sectionB)
    }
}
function Write-AdasSyncProof {
    param([Parameter(Mandatory = $true)]$Proof, [Parameter(Mandatory = $true)][string]$Path)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $json = $Proof | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}
function Resolve-AdasSyncFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}
$modulePath = Resolve-AdasSyncFullPath $ModulePath; $canonicalPath = Resolve-AdasSyncFullPath $CanonicalPath
$moduleDir = Split-Path -Parent $modulePath; $backupDir = if ($BackupDir) { Resolve-AdasSyncFullPath $BackupDir } else { Join-Path $moduleDir 'backups' }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
if (-not $ProofPath) { $ProofPath = Join-Path $moduleDir ("Imperial-ADAS.sync-proof.$stamp.json") }
$proofPath = Resolve-AdasSyncFullPath $ProofPath
$proof = [ordered]@{
    tool = 'Install-ADASReviewTransportSync'; dryRun = [bool]$DryRun
    modulePath = $modulePath; canonicalPath = $canonicalPath
    generatedAt = (Get-Date).ToUniversalTime().ToString('o'); result = 'started'; failureReason = ''
}
try {
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
        throw "INSTALL-FAIL-CLOSED: module file not found: $modulePath"
    }
    if (-not (Test-Path -LiteralPath $canonicalPath -PathType Leaf)) {
        throw "INSTALL-FAIL-CLOSED: canonical source file not found: $canonicalPath"
    }
    # --- Canonical source must itself be structurally sound before any sync ---
    $canonicalText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($canonicalPath)); $canonicalText = $canonicalText -replace "^\uFEFF", ''
    $canonicalRawHash = Get-AdasSyncSha256File $canonicalPath; $canonicalNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $canonicalText)
    $sections = Split-AdasCanonicalSections -CanonicalText $canonicalText
    # --- Module before-state ---
    $moduleBytes = [IO.File]::ReadAllBytes($modulePath); $moduleBeforeHash = Get-AdasSyncSha256File $modulePath
    $moduleBeforeSize = (Get-Item -LiteralPath $modulePath).Length; $moduleBeforeAcl = Get-AdasSyncAclSummary $modulePath
    $hasBom = ($moduleBytes.Length -ge 3 -and $moduleBytes[0] -eq 0xEF -and $moduleBytes[1] -eq 0xBB -and $moduleBytes[2] -eq 0xBF)
    $moduleText = [Text.Encoding]::UTF8.GetString($moduleBytes); $moduleText = $moduleText -replace "^\uFEFF", ''
    $boundariesA = Find-AdasSyncRegion -ModuleText $moduleText -BlockNames $CANONICAL_FUNCTIONS_A -Successor $EXPECTED_SUCCESSOR_A -Label 'A'
    $boundariesB = Find-AdasSyncRegion -ModuleText $moduleText -BlockNames $CANONICAL_FUNCTIONS_B -Successor $EXPECTED_SUCCESSOR_B -Label 'B'
    if ([int]$boundariesB.start -lt [int]$boundariesA.end) {
        throw "INSTALL-FAIL-CLOSED: region B starts before region A ends (A end $($boundariesA.end), B start $($boundariesB.start)); regions overlap or are out of order."
    }
    $startA = [int]$boundariesA.start; $endA = [int]$boundariesA.end; $startB = [int]$boundariesB.start; $endB = [int]$boundariesB.end
    $prefixAText = $moduleText.Substring(0, $startA); $middleText = $moduleText.Substring($endA, $startB - $endA)
    $suffixBText = $moduleText.Substring($endB); $prefixAHash = Get-AdasSyncSha256Text $prefixAText
    $middleHash = Get-AdasSyncSha256Text $middleText; $suffixBHash = Get-AdasSyncSha256Text $suffixBText
    $installedRegionAText = $moduleText.Substring($startA, $endA - $startA); $installedRegionBText = $moduleText.Substring($startB, $endB - $startB)
    $installedRegionARawHash = Get-AdasSyncSha256Text $installedRegionAText
    $installedRegionANormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $installedRegionAText)
    $installedRegionBRawHash = Get-AdasSyncSha256Text $installedRegionBText
    $installedRegionBNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $installedRegionBText)
    $newModuleText = $prefixAText + $sections.sectionA + $middleText + $sections.sectionB + $suffixBText; $byteEqual = ($newModuleText -ceq $moduleText)
    $action = if ($byteEqual) { 'noop-identical' } else { 'replace-both-regions' }
    # --- Planned content must parse (fail-closed posture; -SkipParseVerify opts out) ---
    $plannedParseErrors = 0
    if (-not $SkipParseVerify) {
        $tokens = $null; $errors = $null
        [System.Management.Automation.Language.Parser]::ParseInput($newModuleText, [ref]$tokens, [ref]$errors) | Out-Null
        $plannedParseErrors = $errors.Count
        if ($plannedParseErrors -ne 0) {
            throw "INSTALL-FAIL-CLOSED: planned module content has $plannedParseErrors parser error(s); refusing to sync."
        }
    }
    $backupName = "Imperial-ADAS.psm1.pre-sync-$($moduleBeforeHash.Substring(0, 8))-$stamp.bak"; $backupPath = Join-Path $backupDir $backupName
    $proof.mode = [string]$boundariesB.mode; $proof.successor = [string]$boundariesB.successor; $proof.action = $action
    $proof.moduleBeforeHash = $moduleBeforeHash; $proof.moduleBeforeSize = $moduleBeforeSize; $proof.moduleBeforeAcl = @($moduleBeforeAcl)
    $proof.prefixAHash = $prefixAHash; $proof.middleHash = $middleHash; $proof.suffixBHash = $suffixBHash
    $proof.canonical = [ordered]@{ rawSha256 = $canonicalRawHash; normalizedSha256 = $canonicalNormalizedHash; sectionARawSha256 = [string]$sections.sectionARawHash; sectionANormalizedSha256 = [string]$sections.sectionANormalizedHash; sectionBRawSha256 = [string]$sections.sectionBRawHash; sectionBNormalizedSha256 = [string]$sections.sectionBNormalizedHash; sectionACharacterCount = $sections.sectionA.Length; sectionBCharacterCount = $sections.sectionB.Length }
    $proof.regionA = [ordered]@{ mode = [string]$boundariesA.mode; successor = [string]$boundariesA.successor; installedRawSha256 = $installedRegionARawHash; installedNormalizedSha256 = $installedRegionANormalizedHash; extractedRawSha256 = $null; extractedNormalizedSha256 = $null; blockByteEqual = $null; blockNormalizedEqual = $null }
    $proof.regionB = [ordered]@{ mode = [string]$boundariesB.mode; successor = [string]$boundariesB.successor; installedRawSha256 = $installedRegionBRawHash; installedNormalizedSha256 = $installedRegionBNormalizedHash; extractedRawSha256 = $null; extractedNormalizedSha256 = $null; blockByteEqual = $null; blockNormalizedEqual = $null }
    $proof.plannedParseErrors = $plannedParseErrors; $proof.backupPath = $backupPath; $proof.backupHash = $null
    $proof.moduleAfterHash = $null; $proof.prefixMiddleSuffixPreserved = $null; $proof.syncedParseErrors = $null; $proof.rollbackPerformed = $false
    if ($DryRun) {
        $proof.result = 'dry-run-plan'
        $proof.moduleAfterHash = $moduleBeforeHash
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "DRY-RUN OK: action=$action modeA=$($boundariesA.mode) modeB=$($boundariesB.mode); no file was modified. proof=$proofPath"
        exit 0
    }
    # --- Real sync (idempotent) ---
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item -LiteralPath $modulePath -Destination $backupPath -Force
    $backupHash = Get-AdasSyncSha256File $backupPath
    if ($backupHash -ne $moduleBeforeHash) {
        Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        throw "INSTALL-FAIL-CLOSED: backup hash $backupHash does not equal the before-hash $moduleBeforeHash; module was not modified."
    }
    $proof.backupHash = $backupHash
    if ($action -eq 'noop-identical') {
        $proof.result = 'synced-noop-identical'; $proof.moduleAfterHash = $moduleBeforeHash
        $proof.regionA.blockByteEqual = $true; $proof.regionA.blockNormalizedEqual = $true
        $proof.regionB.blockByteEqual = $true; $proof.regionB.blockNormalizedEqual = $true
        $proof.prefixMiddleSuffixPreserved = $true; $proof.syncedParseErrors = $plannedParseErrors
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "SYNC OK (noop-identical): installed sections already equal the canonical source. proof=$proofPath"
        exit 0
    }
    # --- Atomic swap via ReplaceFile; temp lives in the module directory. ReplaceFile also
    # writes the displaced previous module to its own backup name; that copy is hash-checked
    # against the before-hash (an extra atomicity witness) and then removed. ---
    $encoding = if ($hasBom) { New-Object Text.UTF8Encoding($true) } else { New-Object Text.UTF8Encoding($false) }
    $tempPath = Join-Path $moduleDir ("Imperial-ADAS.psm1.sync-tmp-$([Guid]::NewGuid().ToString('N')).tmp")
    $replaceBackup = Join-Path $moduleDir ("Imperial-ADAS.psm1.replace-backup-$([Guid]::NewGuid().ToString('N')).bak")
    [IO.File]::WriteAllText($tempPath, $newModuleText, $encoding)
    try {
        [IO.File]::Replace($tempPath, $modulePath, $replaceBackup)
        $replaceBackupHash = Get-AdasSyncSha256File $replaceBackup
        if ($replaceBackupHash -ne $moduleBeforeHash) {
            throw "replace-backup hash $replaceBackupHash does not equal the before-hash $moduleBeforeHash."
        }
        Remove-Item -LiteralPath $replaceBackup -Force -ErrorAction SilentlyContinue
        $proof.replaceBackupWitnessed = $true
    }
    catch {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $replaceBackup -Force -ErrorAction SilentlyContinue
        throw "INSTALL-FAIL-CLOSED: atomic replace failed ($($_.Exception.Message)); the pre-sync module is untouched at $modulePath."
    }
    # --- Post-sync verification: extract back, compare, parse; rollback on any mismatch ---
    try {
        $afterText = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($modulePath)); $afterText = $afterText -replace "^\uFEFF", ''
        $afterBoundariesA = Find-AdasSyncRegion -ModuleText $afterText -BlockNames $CANONICAL_FUNCTIONS_A -Successor $EXPECTED_SUCCESSOR_A -Label 'A'
        $afterBoundariesB = Find-AdasSyncRegion -ModuleText $afterText -BlockNames $CANONICAL_FUNCTIONS_B -Successor $EXPECTED_SUCCESSOR_B -Label 'B'
        if ([string]$afterBoundariesA.mode -ne 'canonical-block') {
            throw "INSTALL-FAIL-CLOSED: post-sync region A mode is '$($afterBoundariesA.mode)', expected 'canonical-block'."
        }
        if ([string]$afterBoundariesB.mode -ne 'canonical-block') {
            throw "INSTALL-FAIL-CLOSED: post-sync region B mode is '$($afterBoundariesB.mode)', expected 'canonical-block'."
        }
        $afterRegionA = $afterText.Substring([int]$afterBoundariesA.start, [int]$afterBoundariesA.end - [int]$afterBoundariesA.start); $afterRegionB = $afterText.Substring([int]$afterBoundariesB.start, [int]$afterBoundariesB.end - [int]$afterBoundariesB.start)
        $afterPrefixA = $afterText.Substring(0, [int]$afterBoundariesA.start); $afterMiddle = $afterText.Substring([int]$afterBoundariesA.end, [int]$afterBoundariesB.start - [int]$afterBoundariesA.end)
        $afterSuffixB = $afterText.Substring([int]$afterBoundariesB.end); $afterRegionARawHash = Get-AdasSyncSha256Text $afterRegionA
        $afterRegionANormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $afterRegionA)
        $afterRegionBRawHash = Get-AdasSyncSha256Text $afterRegionB
        $afterRegionBNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $afterRegionB)
        $regionAByteEqual = ($afterRegionARawHash -eq [string]$sections.sectionARawHash); $regionANormalizedEqual = ($afterRegionANormalizedHash -eq [string]$sections.sectionANormalizedHash)
        $regionBByteEqual = ($afterRegionBRawHash -eq [string]$sections.sectionBRawHash); $regionBNormalizedEqual = ($afterRegionBNormalizedHash -eq [string]$sections.sectionBNormalizedHash)
        $prefixMiddleSuffixPreserved = ((Get-AdasSyncSha256Text $afterPrefixA) -eq $prefixAHash -and (Get-AdasSyncSha256Text $afterMiddle) -eq $middleHash -and (Get-AdasSyncSha256Text $afterSuffixB) -eq $suffixBHash)
        $syncedParseErrors = 0
        if (-not $SkipParseVerify) {
            $tokens = $null; $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile($modulePath, [ref]$tokens, [ref]$errors) | Out-Null
            $syncedParseErrors = $errors.Count
        }
        if (-not $regionANormalizedEqual) {
            throw "INSTALL-FAIL-CLOSED: extracted installed region A normalized hash $afterRegionANormalizedHash != canonical $($sections.sectionANormalizedHash)."
        }
        if (-not $regionBNormalizedEqual) {
            throw "INSTALL-FAIL-CLOSED: extracted installed region B normalized hash $afterRegionBNormalizedHash != canonical $($sections.sectionBNormalizedHash)."
        }
        if (-not $prefixMiddleSuffixPreserved) {
            throw 'INSTALL-FAIL-CLOSED: prefix/middle/suffix hashes changed during sync; only the two named regions may change.'
        }
        if ($syncedParseErrors -ne 0) {
            throw "INSTALL-FAIL-CLOSED: synced module has $syncedParseErrors parser error(s)."
        }
        $moduleAfterHash = Get-AdasSyncSha256File $modulePath
        $proof.result = 'synced-ok'; $proof.moduleAfterHash = $moduleAfterHash
        $proof.regionA.extractedRawSha256 = $afterRegionARawHash; $proof.regionA.extractedNormalizedSha256 = $afterRegionANormalizedHash
        $proof.regionA.blockByteEqual = [bool]$regionAByteEqual; $proof.regionA.blockNormalizedEqual = [bool]$regionANormalizedEqual
        $proof.regionB.extractedRawSha256 = $afterRegionBRawHash; $proof.regionB.extractedNormalizedSha256 = $afterRegionBNormalizedHash
        $proof.regionB.blockByteEqual = [bool]$regionBByteEqual; $proof.regionB.blockNormalizedEqual = [bool]$regionBNormalizedEqual
        $proof.prefixMiddleSuffixPreserved = [bool]$prefixMiddleSuffixPreserved; $proof.syncedParseErrors = $syncedParseErrors
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "SYNC OK: action=$action modeA=$($boundariesA.mode) modeB=$($boundariesB.mode) regionAByteEqual=$regionAByteEqual regionANormalizedEqual=$regionANormalizedEqual regionBByteEqual=$regionBByteEqual regionBNormalizedEqual=$regionBNormalizedEqual prefixMiddleSuffixPreserved=$prefixMiddleSuffixPreserved parseErrors=$syncedParseErrors. proof=$proofPath"
        exit 0
    }
    catch {
        # Fail-closed rollback: atomically restore the verified backup.
        $rollbackError = ''; $rollbackDisplaced = Join-Path $moduleDir ("Imperial-ADAS.psm1.rollback-displaced-$([Guid]::NewGuid().ToString('N')).tmp")
        try {
            [IO.File]::Replace($backupPath, $modulePath, $rollbackDisplaced)
            Remove-Item -LiteralPath $rollbackDisplaced -Force -ErrorAction SilentlyContinue
            $restoredHash = Get-AdasSyncSha256File $modulePath
            if ($restoredHash -ne $moduleBeforeHash) {
                $rollbackError = "rollback restore hash mismatch: $restoredHash != $moduleBeforeHash"
            }
        }
        catch {
            Remove-Item -LiteralPath $rollbackDisplaced -Force -ErrorAction SilentlyContinue
            $rollbackError = "rollback failed: $($_.Exception.Message)"
        }
        $proof.result = 'verify-failed-rolled-back'; $proof.failureReason = $_.Exception.Message
        $proof.rollbackPerformed = $true; $proof.rollbackError = $rollbackError
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        [Console]::Error.WriteLine("INSTALL-FAIL-CLOSED: $($_.Exception.Message) rollbackPerformed=$(-not [bool]$rollbackError) rollbackError=$rollbackError proof=$proofPath")
        exit 1
    }
}
catch {
    $proof.result = 'failed-closed'; $proof.failureReason = $_.Exception.Message
    $proof.moduleAfterHash = if (Test-Path -LiteralPath $modulePath) { Get-AdasSyncSha256File $modulePath } else { $null }
    Write-AdasSyncProof -Proof $proof -Path $proofPath
    [Console]::Error.WriteLine("INSTALL-FAIL-CLOSED: $($_.Exception.Message) proof=$proofPath")
    exit 1
}
