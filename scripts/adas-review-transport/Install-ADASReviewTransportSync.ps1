<#
.SYNOPSIS
Deterministic atomic install/sync of the canonical, git-tracked ADAS
independent-review control-plane unit into the live profile module
(pro\bin\Imperial-ADAS.psm1, outside the git worktree).

The canonical tracked source is
scripts/adas-review-transport/Imperial-ADAS-ReviewTransport.ps1. This
installer inserts exactly that source into the named function/helper block
(New-ADASReviewAttemptRecord .. Invoke-ADASIndependentReview) of the
profile module and proves byte/normalized-hash equality afterwards.
Nothing else in the profile may change.

Guarantees, in order:

  1. Boundary discipline: the block is located structurally with the
     PowerShell AST, never by regex guessing. It spans the eight canonical
     functions (New-ADASReviewAttemptRecord .. Invoke-ADASIndependentReview)
     in canonical order, and the successor function that follows it in
     document order must be exactly `Get-ADASProofManifest`. A legacy
     profile without the new block is located by its standalone
     `Invoke-ADASIndependentReview` region with the same successor check.
     Duplication, reordering, or successor drift fails closed; only the
     named block can ever be modified.
  2. Pre-sync proof: module SHA-256, size, ACL (icacls), a timestamped
     backup copy whose hash must equal the before-hash, and prefix/suffix
     SHA-256 of the untouched regions.
  3. Atomic replace: the new content is written to a temp file in the
     module directory and swapped in with [IO.File]::Replace (Windows
     ReplaceFile), so readers never observe a partially written module.
  4. Post-sync proof: the installed block is extracted back and must match
     the canonical tracked source byte-identically or by normalized
     (CRLF-insensitive) SHA-256; the prefix/suffix hashes must equal the
     pre-sync values; the module must parse with 0 PowerShell parser
     errors. Any mismatch restores the backup (fail-closed rollback) and
     exits nonzero.
  5. Idempotent: when the installed block already equals the canonical
     source, the sync records a `noop-identical` proof and changes nothing.

The installer never reads, copies or logs any key file, request body,
review content or reasoning trace: proofs carry only paths, hashes,
sizes, counts and ACL lines. Dry-run (`-DryRun`) computes and reports the
full plan without touching the module.

.PARAMETER ModulePath
The live profile module (pro\bin\Imperial-ADAS.psm1).

.PARAMETER CanonicalPath
The git-tracked canonical unit (Imperial-ADAS-ReviewTransport.ps1).

.PARAMETER BackupDir
Backup directory; default `<module dir>\backups`.

.PARAMETER ProofPath
Proof JSON output path; default `<module dir>\Imperial-ADAS.sync-proof.<timestamp>.json`.

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
$ErrorActionPreference = 'Stop'

$EXPECTED_SUCCESSOR = 'Get-ADASProofManifest'

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

function Find-AdasSyncBlock {
    param([Parameter(Mandatory = $true)][string]$ModuleText)
    # Structural (AST) block location, never regex guessing: the block is the
    # region from the first helper function through the named function, up to
    # the successor function that follows it in document order. The successor
    # must be exactly the expected profile function, and the block must contain
    # the eight canonical functions in canonical order; any drift fails closed.
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($ModuleText, [ref]$tokens, [ref]$errors)
    if ($errors.Count -ne 0) {
        throw "INSTALL-FAIL-CLOSED: module has $($errors.Count) parser error(s); the block cannot be located safely."
    }
    $functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
    $firstIndex = -1
    for ($i = 0; $i -lt $functions.Count; $i++) {
        if ([string]$functions[$i].Name -eq 'New-ADASReviewAttemptRecord') { $firstIndex = $i; break }
    }
    if ($firstIndex -ge 0) {
        $mode = 'task52-block'
        $namedIndex = -1
        for ($i = $firstIndex; $i -lt $functions.Count; $i++) {
            if ([string]$functions[$i].Name -eq 'Invoke-ADASIndependentReview') { $namedIndex = $i; break }
        }
        if ($namedIndex -lt 0) {
            throw 'INSTALL-FAIL-CLOSED: block start helper exists but the named function Invoke-ADASIndependentReview does not follow it; profile structure drifted.'
        }
        $expected = @('New-ADASReviewAttemptRecord', 'Get-ADASReviewGateCompact', 'Get-ADASReviewDiffSections',
            'Invoke-ADASDeepSeekCompletion', 'Test-ADASReviewContract', 'ConvertTo-ADASReviewContractObject',
            'New-ADASReviewUnavailableResult', 'Invoke-ADASIndependentReview')
        for ($i = 0; $i -lt $expected.Count; $i++) {
            $actualName = [string]$functions[$firstIndex + $i].Name
            if ($actualName -ne $expected[$i]) {
                throw "INSTALL-FAIL-CLOSED: block function #$($i + 1) is '$actualName', expected '$($expected[$i])'; profile structure drifted."
            }
        }
        $successorIndex = $namedIndex + 1
    }
    else {
        $namedIndex = -1
        for ($i = 0; $i -lt $functions.Count; $i++) {
            if ([string]$functions[$i].Name -eq 'Invoke-ADASIndependentReview') { $namedIndex = $i; break }
        }
        if ($namedIndex -lt 0) {
            throw 'INSTALL-FAIL-CLOSED: neither the canonical block nor the legacy Invoke-ADASIndependentReview function exists; profile structure drifted, refusing to modify anything.'
        }
        $mode = 'legacy-block'
        $firstIndex = $namedIndex
        $successorIndex = $namedIndex + 1
    }
    if ($successorIndex -ge $functions.Count) {
        throw 'INSTALL-FAIL-CLOSED: no successor function after the block; profile structure drifted.'
    }
    $successor = [string]$functions[$successorIndex].Name
    if ($successor -ne $EXPECTED_SUCCESSOR) {
        throw "INSTALL-FAIL-CLOSED: successor function is '$successor', expected '$EXPECTED_SUCCESSOR'; profile structure drifted."
    }
    $start = [int]$functions[$firstIndex].Extent.StartOffset
    $end = [int]$functions[$successorIndex].Extent.StartOffset
    if ($end -le $start) {
        throw 'INSTALL-FAIL-CLOSED: block boundaries are not ordered; profile structure drifted.'
    }
    return [pscustomobject]@{ mode = $mode; start = $start; end = $end; successor = $successor }
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

$modulePath = Resolve-AdasSyncFullPath $ModulePath
$canonicalPath = Resolve-AdasSyncFullPath $CanonicalPath
$moduleDir = Split-Path -Parent $modulePath
$backupDir = if ($BackupDir) { Resolve-AdasSyncFullPath $BackupDir } else { Join-Path $moduleDir 'backups' }
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
if (-not $ProofPath) { $ProofPath = Join-Path $moduleDir ("Imperial-ADAS.sync-proof.$stamp.json") }
$proofPath = Resolve-AdasSyncFullPath $ProofPath

$proof = [ordered]@{
    tool = 'Install-ADASReviewTransportSync'
    dryRun = [bool]$DryRun
    modulePath = $modulePath
    canonicalPath = $canonicalPath
    generatedAt = (Get-Date).ToUniversalTime().ToString('o')
    result = 'started'
    failureReason = ''
}

try {
    if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
        throw "INSTALL-FAIL-CLOSED: module file not found: $modulePath"
    }
    if (-not (Test-Path -LiteralPath $canonicalPath -PathType Leaf)) {
        throw "INSTALL-FAIL-CLOSED: canonical source file not found: $canonicalPath"
    }

    # --- Canonical source must itself be structurally sound before any sync ---
    $canonicalTokens = $null
    $canonicalErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($canonicalPath, [ref]$canonicalTokens, [ref]$canonicalErrors) | Out-Null
    if ($canonicalErrors.Count -ne 0) {
        throw "INSTALL-FAIL-CLOSED: canonical source has $($canonicalErrors.Count) parser error(s); refusing to sync a broken unit."
    }
    $canonicalBytes = [IO.File]::ReadAllBytes($canonicalPath)
    $canonicalText = [Text.Encoding]::UTF8.GetString($canonicalBytes)
    $canonicalText = $canonicalText -replace "^\uFEFF", ''
    $canonicalRawHash = Get-AdasSyncSha256File $canonicalPath
    $canonicalNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $canonicalText)

    # --- Module before-state ---
    $moduleBytes = [IO.File]::ReadAllBytes($modulePath)
    $moduleBeforeHash = Get-AdasSyncSha256File $modulePath
    $moduleBeforeSize = (Get-Item -LiteralPath $modulePath).Length
    $moduleBeforeAcl = Get-AdasSyncAclSummary $modulePath
    $hasBom = ($moduleBytes.Length -ge 3 -and $moduleBytes[0] -eq 0xEF -and $moduleBytes[1] -eq 0xBB -and $moduleBytes[2] -eq 0xBF)
    $moduleText = [Text.Encoding]::UTF8.GetString($moduleBytes)
    $moduleText = $moduleText -replace "^\uFEFF", ''

    $boundaries = Find-AdasSyncBlock -ModuleText $moduleText
    $start = [int]$boundaries.start
    $end = [int]$boundaries.end
    $prefixText = $moduleText.Substring(0, $start)
    $suffixText = $moduleText.Substring($end)
    $prefixHash = Get-AdasSyncSha256Text $prefixText
    $suffixHash = Get-AdasSyncSha256Text $suffixText
    $installedBlockText = $moduleText.Substring($start, $end - $start)
    $installedBlockRawHash = Get-AdasSyncSha256Text $installedBlockText
    $installedBlockNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $installedBlockText)

    $newModuleText = $prefixText + $canonicalText + $suffixText
    $byteEqual = ($newModuleText -ceq $moduleText)
    $action = if ($byteEqual) { 'noop-identical' } else { 'replace-block' }

    # --- Planned content must parse (fail-closed posture; -SkipParseVerify opts out) ---
    $plannedParseErrors = 0
    if (-not $SkipParseVerify) {
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseInput($newModuleText, [ref]$tokens, [ref]$errors) | Out-Null
        $plannedParseErrors = $errors.Count
        if ($plannedParseErrors -ne 0) {
            throw "INSTALL-FAIL-CLOSED: planned module content has $plannedParseErrors parser error(s); refusing to sync."
        }
    }

    $backupName = "Imperial-ADAS.psm1.pre-sync-$($moduleBeforeHash.Substring(0, 8))-$stamp.bak"
    $backupPath = Join-Path $backupDir $backupName

    $proof.mode = [string]$boundaries.mode
    $proof.successor = [string]$boundaries.successor
    $proof.action = $action
    $proof.moduleBeforeHash = $moduleBeforeHash
    $proof.moduleBeforeSize = $moduleBeforeSize
    $proof.moduleBeforeAcl = @($moduleBeforeAcl)
    $proof.prefixHash = $prefixHash
    $proof.suffixHash = $suffixHash
    $proof.canonicalRawSha256 = $canonicalRawHash
    $proof.canonicalNormalizedSha256 = $canonicalNormalizedHash
    $proof.installedBlockRawSha256 = $installedBlockRawHash
    $proof.installedBlockNormalizedSha256 = $installedBlockNormalizedHash
    $proof.plannedParseErrors = $plannedParseErrors
    $proof.backupPath = $backupPath
    $proof.backupHash = $null
    $proof.moduleAfterHash = $null
    $proof.blockByteEqual = $null
    $proof.blockNormalizedEqual = $null
    $proof.prefixSuffixPreserved = $null
    $proof.syncedParseErrors = $null
    $proof.rollbackPerformed = $false

    if ($DryRun) {
        $proof.result = 'dry-run-plan'
        $proof.moduleAfterHash = $moduleBeforeHash
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "DRY-RUN OK: action=$action mode=$($boundaries.mode); no file was modified. proof=$proofPath"
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
        $proof.result = 'synced-noop-identical'
        $proof.moduleAfterHash = $moduleBeforeHash
        $proof.blockByteEqual = $true
        $proof.blockNormalizedEqual = $true
        $proof.prefixSuffixPreserved = $true
        $proof.syncedParseErrors = $plannedParseErrors
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "SYNC OK (noop-identical): installed block already equals the canonical source. proof=$proofPath"
        exit 0
    }

    # --- Atomic swap via ReplaceFile; temp lives in the module directory.
    # ReplaceFile also writes the displaced previous module to its own backup
    # name; that copy is hash-checked against the before-hash (an extra
    # atomicity witness) and then removed. ---
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
        $afterBytes = [IO.File]::ReadAllBytes($modulePath)
        $afterText = [Text.Encoding]::UTF8.GetString($afterBytes)
        $afterText = $afterText -replace "^\uFEFF", ''
        $afterBoundaries = Find-AdasSyncBlock -ModuleText $afterText
        if ([string]$afterBoundaries.mode -ne 'task52-block') {
            throw "INSTALL-FAIL-CLOSED: post-sync block mode is '$($afterBoundaries.mode)', expected 'task52-block'."
        }
        $afterBlock = $afterText.Substring([int]$afterBoundaries.start, [int]$afterBoundaries.end - [int]$afterBoundaries.start)
        $afterPrefix = $afterText.Substring(0, [int]$afterBoundaries.start)
        $afterSuffix = $afterText.Substring([int]$afterBoundaries.end)
        $afterBlockRawHash = Get-AdasSyncSha256Text $afterBlock
        $afterBlockNormalizedHash = Get-AdasSyncSha256Text (Get-AdasSyncNormalizedText $afterBlock)
        $blockByteEqual = ($afterBlockRawHash -eq $canonicalRawHash)
        $blockNormalizedEqual = ($afterBlockNormalizedHash -eq $canonicalNormalizedHash)
        $prefixSuffixPreserved = ((Get-AdasSyncSha256Text $afterPrefix) -eq $prefixHash -and (Get-AdasSyncSha256Text $afterSuffix) -eq $suffixHash)
        $syncedParseErrors = 0
        if (-not $SkipParseVerify) {
            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile($modulePath, [ref]$tokens, [ref]$errors) | Out-Null
            $syncedParseErrors = $errors.Count
        }
        if (-not $blockNormalizedEqual) {
            throw "INSTALL-FAIL-CLOSED: extracted installed block normalized hash $afterBlockNormalizedHash != canonical $canonicalNormalizedHash."
        }
        if (-not $prefixSuffixPreserved) {
            throw "INSTALL-FAIL-CLOSED: prefix/suffix hashes changed during sync; only the named block may change."
        }
        if ($syncedParseErrors -ne 0) {
            throw "INSTALL-FAIL-CLOSED: synced module has $syncedParseErrors parser error(s)."
        }
        $moduleAfterHash = Get-AdasSyncSha256File $modulePath
        $proof.result = 'synced-ok'
        $proof.moduleAfterHash = $moduleAfterHash
        $proof.blockByteEqual = [bool]$blockByteEqual
        $proof.blockNormalizedEqual = [bool]$blockNormalizedEqual
        $proof.prefixSuffixPreserved = [bool]$prefixSuffixPreserved
        $proof.syncedParseErrors = $syncedParseErrors
        $proof.installedBlockRawSha256 = $afterBlockRawHash
        $proof.installedBlockNormalizedSha256 = $afterBlockNormalizedHash
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        Write-Output "SYNC OK: mode=$($boundaries.mode) action=$action byteEqual=$blockByteEqual normalizedEqual=$blockNormalizedEqual prefixSuffixPreserved=$prefixSuffixPreserved parseErrors=$syncedParseErrors. proof=$proofPath"
        exit 0
    }
    catch {
        # Fail-closed rollback: atomically restore the verified backup.
        $rollbackError = ''
        $rollbackDisplaced = Join-Path $moduleDir ("Imperial-ADAS.psm1.rollback-displaced-$([Guid]::NewGuid().ToString('N')).tmp")
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
        $proof.result = 'verify-failed-rolled-back'
        $proof.failureReason = $_.Exception.Message
        $proof.rollbackPerformed = $true
        $proof.rollbackError = $rollbackError
        Write-AdasSyncProof -Proof $proof -Path $proofPath
        [Console]::Error.WriteLine("INSTALL-FAIL-CLOSED: $($_.Exception.Message) rollbackPerformed=$(-not [bool]$rollbackError) rollbackError=$rollbackError proof=$proofPath")
        exit 1
    }
}
catch {
    $proof.result = 'failed-closed'
    $proof.failureReason = $_.Exception.Message
    $proof.moduleAfterHash = if (Test-Path -LiteralPath $modulePath) { Get-AdasSyncSha256File $modulePath } else { $null }
    Write-AdasSyncProof -Proof $proof -Path $proofPath
    [Console]::Error.WriteLine("INSTALL-FAIL-CLOSED: $($_.Exception.Message) proof=$proofPath")
    exit 1
}
