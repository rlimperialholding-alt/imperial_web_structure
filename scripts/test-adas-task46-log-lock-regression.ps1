<#
.SYNOPSIS
Direct behavioral regression for the Task46 control-plane stdout/stderr
log-lock fix (Task47 remediation).

The checks load the ACTUAL shipped helper code: every helper body and call
site is extracted from the on-disk control-plane files with the PowerShell
AST (structural, never regex pattern matching on source text) and executed
on temporary copies with real Windows lock contention. The evidence chain:

  1. SHA-256 identity: all four control-plane files (worker canonical,
     worker active, module canonical, module active) match the Task46
     post-fix hashes recorded in the committed audit manifest; the Task46
     proof directory, its four pre-fix backups and its four fix diffs exist,
     and every backup matches its manifest hash.
  2. Instance identity: the fixed helper bodies (Read-WorkerTextFile,
     Read-ADASProcessOutput) are byte-identical between the canonical and
     active instances.
  3. Loaded helper behavior, on temporary files with real Windows
     FileShare.None lock contention:
     - missing file -> '' without exception;
     - empty file -> '' without exception;
     - short exclusive lock (proven active by a marker) released after
       ~1.2 s: full, exact read after a measurable retry;
     - persistent exclusive lock: bounded wait, then the original
       System.IO.IOException rethrown (fail-closed, no infinite retry).
  4. stdout/stderr order through the real fixed call sites:
     - worker Invoke-ADASPipelineChild (loaded from the worker file, real
       powershell child process): OutputLog = stdout lines, then the
       STDERR marker, then stderr lines; exit code propagated; redirect
       scratch removed.
     - module Invoke-ADASProcess (loaded from the active module file, real
       cmd child process): combined log keeps stdout before marker before
       stderr; exit code propagated.
  5. Structural call-site checks (AST): the fixed sites call the helpers
     with the redirect path variables, and no direct ReadAllText remains on
     any stdout/stderr redirect path inside the fixed scopes.

No file content and no secret material is printed anywhere; only paths,
hashes, counts and pass/fail outcomes. Results are written as
machine-readable JSON (default: the git-ignored runtime directory) and the
process exit code is 0 only when every check passed.
#>
[CmdletBinding()]
param(
    [string]$ManifestPath = '',
    [string]$ResultPath = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:Results = New-Object 'System.Collections.Generic.List[object]'

function Add-Check {
    param([string]$Name, [bool]$Pass, [string]$Detail)
    $script:Results.Add([pscustomobject]@{
        name = $Name
        outcome = $(if ($Pass) { 'PASS' } else { 'FAIL' })
        detail = $Detail
    })
    Write-Output ("[{0}] {1} - {2}" -f $(if ($Pass) { 'PASS' } else { 'FAIL' }), $Name, $Detail)
}

function Join-Chunks {
    param([Parameter(Mandatory = $true)][object[]]$Chunks)
    return (($Chunks -join '').ToLowerInvariant())
}

function Get-FunctionAst {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Name)
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        throw ("parse errors in " + $Path + ": " + $errors[0].Message)
    }
    $found = @($ast.FindAll(
        { param($node) ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and ($node.Name -eq $Name) },
        $true))
    if ($found.Count -ne 1) {
        throw ("function " + $Name + " not found exactly once in " + $Path)
    }
    return $found[0]
}

function Import-FunctionText {
    param([Parameter(Mandatory = $true)][string]$Text)
    # Dot-sourcing inside a function would confine the definition to this
    # function's scope, so the definitions are collected by the caller and
    # dot-sourced once at the caller's scope instead. This helper only
    # persists the extracted, actual shipped code to a temporary copy.
    $tmp = Join-Path $env:TEMP ('task46-helper-' + [Guid]::NewGuid().ToString('N') + '.ps1')
    [IO.File]::WriteAllText($tmp, $Text, (New-Object Text.UTF8Encoding($false)))
    return $tmp
}

function Invoke-LockCase {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [int]$HoldMs,
        [int]$RetrySeconds
    )
    $file = Join-Path $env:TEMP ('task46-lock-' + [Guid]::NewGuid().ToString('N') + '.txt')
    $content = "line-one`r`nline-two`r`n"
    [IO.File]::WriteAllText($file, $content, (New-Object Text.UTF8Encoding($false)))
    $marker = $file + '.held'
    $job = Start-Job -ScriptBlock {
        param($path, $markerPath, $holdMs)
        try {
            $fs = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            [IO.File]::WriteAllText($markerPath, 'held')
            Start-Sleep -Milliseconds $holdMs
            $fs.Dispose()
        }
        finally {
            Remove-Item -LiteralPath $markerPath -Force -ErrorAction SilentlyContinue
        }
    } -ArgumentList $file, $marker, $HoldMs
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while (-not (Test-Path -LiteralPath $marker)) {
            if ([DateTime]::UtcNow -gt $deadline) {
                Add-Check ($Label + ':lock-holder') $false 'lock holder did not acquire the file in time'
                return
            }
            Start-Sleep -Milliseconds 50
        }
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $threw = $false
        $exception = $null
        $result = $null
        try {
            $result = & $Action $file $RetrySeconds
        }
        catch {
            $threw = $true
            $exception = $_.Exception
        }
        $sw.Stop()
        return @{ result = $result; elapsedMs = $sw.Elapsed.TotalMilliseconds; threw = $threw; exception = $exception; content = $content }
    }
    finally {
        Stop-Job $job -ErrorAction SilentlyContinue | Out-Null
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $file, $marker -Force -ErrorAction SilentlyContinue
    }
}

function Test-HelperBehavior {
    param([Parameter(Mandatory = $true)][string]$Label, [Parameter(Mandatory = $true)][string]$HelperName)

    # Missing file: '' without exception.
    $missing = Join-Path $env:TEMP ('task46-missing-' + [Guid]::NewGuid().ToString('N') + '.txt')
    $threw = $false
    $result = $null
    try { $result = & $HelperName -Path $missing }
    catch { $threw = $true }
    Add-Check ($Label + ':missing-file') ((-not $threw) -and ($result -eq '')) 'missing file returned empty string, no exception'

    # Empty file: '' without exception.
    $empty = Join-Path $env:TEMP ('task46-empty-' + [Guid]::NewGuid().ToString('N') + '.txt')
    [IO.File]::WriteAllText($empty, '', (New-Object Text.UTF8Encoding($false)))
    $threw = $false
    $result = $null
    try { $result = & $HelperName -Path $empty }
    catch { $threw = $true }
    Remove-Item -LiteralPath $empty -Force -ErrorAction SilentlyContinue
    Add-Check ($Label + ':empty-file') ((-not $threw) -and ($result -eq '')) 'empty file returned empty string, no exception'

    # Short exclusive lock (marker-proven active), released after ~1.2 s:
    # full, exact read after a measurable retry.
    $case = Invoke-LockCase -Label ($Label + ':short-lock') -Action ([scriptblock]::Create(('param($f,$rs) {0} -Path $f -RetrySeconds $rs' -f $HelperName))) -HoldMs 1200 -RetrySeconds 30
    if ($null -ne $case) {
        Add-Check ($Label + ':short-lock') ((-not $case.threw) -and ($case.result -eq $case.content) -and ($case.elapsedMs -ge 700) -and ($case.elapsedMs -lt 15000)) ('full exact read after retry, elapsed ' + [int]$case.elapsedMs + ' ms')
    }

    # Persistent exclusive lock: bounded wait, then the original IOException
    # rethrown (fail-closed). PowerShell wraps a scriptblock exception in a
    # MethodInvocationException, so the chain is unwrapped to verify the
    # original exception type.
    $case = Invoke-LockCase -Label ($Label + ':persistent-lock') -Action ([scriptblock]::Create(('param($f,$rs) {0} -Path $f -RetrySeconds $rs' -f $HelperName))) -HoldMs 8000 -RetrySeconds 2
    if ($null -ne $case) {
        $isIo = $false
        $unwrapped = $case.exception
        while ($null -ne $unwrapped) {
            if ($unwrapped.GetType().FullName -eq 'System.IO.IOException') { $isIo = $true; break }
            $unwrapped = $unwrapped.InnerException
        }
        Add-Check ($Label + ':persistent-lock') ($isIo -and ($case.elapsedMs -ge 1500) -and ($case.elapsedMs -le 7000)) ('bounded fail-closed, elapsed ' + [int]$case.elapsedMs + ' ms, exception ' + $(if ($case.threw) { $case.exception.GetType().Name } else { 'none' }))
    }
}

function Test-FixedCallSites {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$FunctionName,
        [Parameter(Mandatory = $true)][string]$HelperName,
        [Parameter(Mandatory = $true)][string[]]$ArgumentNames,
        [Parameter(Mandatory = $true)][string[]]$ForbiddenReadVariables
    )
    $fnAst = Get-FunctionAst -Path $Path -Name $FunctionName
    $body = $fnAst.Body
    $calls = @($body.FindAll(
        { param($node) ($node -is [System.Management.Automation.Language.CommandAst]) -and ($node.GetCommandName() -eq $HelperName) },
        $true))
    foreach ($arg in $ArgumentNames) {
        $has = @($calls | Where-Object {
            @($_.FindAll(
                { param($node) ($node -is [System.Management.Automation.Language.VariableExpressionAst]) -and ($node.VariablePath.UserPath -eq $arg) },
                $true)).Count -gt 0
        }).Count -gt 0
        Add-Check ($Label + ':calls-' + $HelperName + '-with-' + $arg) $has ("AST: " + $FunctionName + " reads $" + $arg + " through " + $HelperName)
    }
    # No direct ReadAllText remains on any stdout/stderr redirect path
    # inside the fixed scope. (The documented exitcode.txt ASCII read and
    # the helper bodies' own ReadAllText are intentionally untouched.)
    $forbidden = @($body.FindAll(
        { param($node) $node -is [System.Management.Automation.Language.MemberExpressionAst] -and $null -ne $node.Member -and $node.Member.Value -eq 'ReadAllText' },
        $true) | Where-Object {
        $invoke = $_.Parent
        ($invoke -is [System.Management.Automation.Language.InvokeMemberExpressionAst]) -and @($invoke.Arguments | Where-Object {
            ($_ -is [System.Management.Automation.Language.VariableExpressionAst]) -and ($ForbiddenReadVariables -contains $_.VariablePath.UserPath)
        }).Count -gt 0
    })
    Add-Check ($Label + ':no-direct-ReadAllText-on-redirects') ($forbidden.Count -eq 0) ('AST: no direct ReadAllText on stdout/stderr redirect paths inside ' + $FunctionName)
}

function Run-All {
    if (-not $ManifestPath) { $ManifestPath = Join-Path $PSScriptRoot 'task46-control-plane-audit-manifest.json' }
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $repoRoot = Split-Path -Parent $PSScriptRoot

    # 1. Hash identity of the four control-plane files + proof/backup checks.
    $proofPath = $manifest.proof.pathPrefix + (Join-Chunks -Chunks $manifest.proof.commitSuffixChunks)
    Add-Check 'proof-directory-exists' (Test-Path -LiteralPath $proofPath -PathType Container) ('path=' + $proofPath)
    $backupDir = Join-Path $proofPath ($manifest.proof.backupDirName)
    Add-Check 'proof-backup-directory-exists' (Test-Path -LiteralPath $backupDir -PathType Container) ('path=' + $backupDir)
    foreach ($entry in $manifest.controlPlaneFiles) {
        $file = [IO.Path]::GetFullPath($entry.path)
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
            $expected = Join-Chunks -Chunks $entry.sha256Chunks
            Add-Check ('hash-identity:' + $entry.role) ($actual -eq $expected) ('path=' + $file)
        }
        else {
            Add-Check ('hash-identity:' + $entry.role) $false ('missing control-plane file: ' + $file)
        }
        $backupFile = Join-Path $backupDir $entry.backup.name
        if (Test-Path -LiteralPath $backupFile -PathType Leaf) {
            $backupActual = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash.ToLowerInvariant()
            $backupExpected = Join-Chunks -Chunks $entry.backup.sha256Chunks
            Add-Check ('backup-identity:' + $entry.role) ($backupActual -eq $backupExpected) ('path=' + $backupFile)
        }
        else {
            Add-Check ('backup-identity:' + $entry.role) $false ('missing backup file: ' + $backupFile)
        }
    }
    foreach ($diff in $manifest.proof.fixDiffs) {
        $diffFile = Join-Path $proofPath $diff
        Add-Check ('proof-fix-diff:' + [IO.Path]::GetFileName($diff)) (Test-Path -LiteralPath $diffFile -PathType Leaf) ('path=' + $diffFile)
    }

    # 2. Instance identity of the fixed helper bodies (AST-extracted, byte
    # compared in memory).
    $workerCanonical = $manifest.controlPlaneFiles | Where-Object { $_.role -eq 'worker-canonical' }
    $workerActive = $manifest.controlPlaneFiles | Where-Object { $_.role -eq 'worker-active' }
    $moduleCanonical = $manifest.controlPlaneFiles | Where-Object { $_.role -eq 'module-canonical' }
    $moduleActive = $manifest.controlPlaneFiles | Where-Object { $_.role -eq 'module-active' }

    $workerHelperCanonical = (Get-FunctionAst -Path $workerCanonical.path -Name 'Read-WorkerTextFile').Extent.Text
    $workerHelperActive = (Get-FunctionAst -Path $workerActive.path -Name 'Read-WorkerTextFile').Extent.Text
    Add-Check 'instance-identity:worker-helper' ([string]::Equals($workerHelperCanonical, $workerHelperActive)) 'Read-WorkerTextFile byte-identical across canonical and active instances'
    $moduleHelperCanonical = (Get-FunctionAst -Path $moduleCanonical.path -Name 'Read-ADASProcessOutput').Extent.Text
    $moduleHelperActive = (Get-FunctionAst -Path $moduleActive.path -Name 'Read-ADASProcessOutput').Extent.Text
    Add-Check 'instance-identity:module-helper' ([string]::Equals($moduleHelperCanonical, $moduleHelperActive)) 'Read-ADASProcessOutput byte-identical across canonical and active instances'

    # 3. Loaded helper behavior with real lock contention on temporary files.
    # All extracted bodies are written to one temporary file and dot-sourced
    # here at the Run-All scope, so the definitions are the actual shipped
    # code and stay visible to every check below (redefinitions are the
    # asserted byte-identical instance pairs).
    $loadedText = @(
        $workerHelperCanonical,
        $workerHelperActive,
        $moduleHelperCanonical,
        $moduleHelperActive,
        (Get-FunctionAst -Path $workerCanonical.path -Name 'Invoke-ADASPipelineChild').Extent.Text,
        (Get-FunctionAst -Path $moduleActive.path -Name 'Write-ADASUtf8NoBom').Extent.Text,
        (Get-FunctionAst -Path $moduleActive.path -Name 'Invoke-ADASProcess').Extent.Text
    ) -join "`r`n`r`n"
    $loadedFile = Import-FunctionText -Text ($loadedText + "`r`n")
    try {
        . $loadedFile

        Test-HelperBehavior -Label 'worker-helper-canonical' -HelperName 'Read-WorkerTextFile'
        Test-HelperBehavior -Label 'worker-helper-active' -HelperName 'Read-WorkerTextFile'
        Test-HelperBehavior -Label 'module-helper-canonical' -HelperName 'Read-ADASProcessOutput'
        Test-HelperBehavior -Label 'module-helper-active' -HelperName 'Read-ADASProcessOutput'

        # 4a. stdout/stderr order through the real worker call site.
        $tmpDir = Join-Path $env:TEMP ('task46-e2e-worker-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
        try {
            $childScript = Join-Path $tmpDir 'child.ps1'
            $childText = @'
param([string]$ConfigPath,[string]$TaskPath,[string]$BeforeCommit,[string]$AfterCommit,[string]$AgentReportPath,[string]$SessionLogPath)
[Console]::Out.WriteLine('out-line-one')
[Console]::Out.WriteLine('out-line-two')
[Console]::Error.WriteLine('err-line-one')
exit 7
'@
            [IO.File]::WriteAllText($childScript, $childText, (New-Object Text.UTF8Encoding($false)))
            $configFile = Join-Path $tmpDir 'config.json'
            [IO.File]::WriteAllText($configFile, '{}', (New-Object Text.UTF8Encoding($false)))
            $taskFile = Join-Path $tmpDir 'task.md'
            [IO.File]::WriteAllText($taskFile, 'synthetic task input', (New-Object Text.UTF8Encoding($false)))
            $agentFile = Join-Path $tmpDir 'agent-report.json'
            [IO.File]::WriteAllText($agentFile, '{}', (New-Object Text.UTF8Encoding($false)))
            $sessionFile = Join-Path $tmpDir 'session.log'
            $outputLog = Join-Path $tmpDir 'output.log'
            $code = Invoke-ADASPipelineChild -PipelinePath $childScript -ConfigPath $configFile -TaskPath $taskFile -BeforeCommit '' -AfterCommit '' -AgentReportPath $agentFile -SessionLogPath $sessionFile -OutputLogPath $outputLog
            Add-Check 'e2e-worker-exit-code' ($code -eq 7) ('exit code propagated: ' + $code)
            if (Test-Path -LiteralPath $outputLog -PathType Leaf) {
                $log = [IO.File]::ReadAllText($outputLog, [Text.Encoding]::UTF8)
                $marker = '--- STDERR ---'
                $parts = $log -split [regex]::Escape($marker)
                $stdoutOk = ($parts.Count -ge 2) -and ($parts[0].Contains('out-line-one')) -and ($parts[0].Contains('out-line-two')) -and (-not $parts[0].Contains('err-line-one'))
                Add-Check 'e2e-worker-stdout-before-marker' $stdoutOk 'stdout lines before the STDERR marker'
                $stderrOk = ($parts.Count -ge 2) -and ($parts[1].Contains('err-line-one')) -and (-not $parts[1].Contains('out-line'))
                Add-Check 'e2e-worker-stderr-after-marker' $stderrOk 'stderr lines after the STDERR marker'
            }
            else {
                Add-Check 'e2e-worker-stdout-before-marker' $false 'output log missing'
                Add-Check 'e2e-worker-stderr-after-marker' $false 'output log missing'
            }
            $redirectGone = (-not (Test-Path -LiteralPath ($outputLog + '.stdout'))) -and (-not (Test-Path -LiteralPath ($outputLog + '.stderr')))
            Add-Check 'e2e-worker-redirect-cleanup' $redirectGone 'redirect scratch files removed'
        }
        finally {
            Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        }

        # 4b. stdout/stderr order through the real module call site (the
        # instance whose redirect read provably failed in the Task45 log).
        $workDir = Join-Path $env:TEMP ('task46-e2e-module-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $workDir | Out-Null
        try {
            $logPath = Join-Path $workDir 'combined.log'
            # A nested ``cmd /c exit 5`` sets errorlevel without terminating
            # the generated batch, so the active module's documented
            # exitcode.txt recording path also runs (the same path the
            # Task45 pipeline used).
            $run = Invoke-ADASProcess -Command 'echo out-one&echo err-one 1>&2&cmd /c exit 5' -WorkingDirectory $workDir -LogPath $logPath -TimeoutSeconds 30
            Add-Check 'e2e-module-exit-code' ($run.ExitCode -eq 5) ('exit code propagated: ' + $run.ExitCode)
            $combined = [IO.File]::ReadAllText($logPath, [Text.Encoding]::UTF8)
            $lines = @($combined -split "`r?`n" | ForEach-Object { $_.TrimEnd() })
            $markerIdx = [Array]::IndexOf($lines, '--- STDERR ---')
            $outIdx = [Array]::IndexOf($lines, 'out-one')
            $errIdx = [Array]::IndexOf($lines, 'err-one')
            $orderOk = ($markerIdx -ge 0) -and ($outIdx -ge 0) -and ($errIdx -ge 0) -and ($outIdx -lt $markerIdx) -and ($markerIdx -lt $errIdx)
            Add-Check 'e2e-module-stdout-before-stderr' $orderOk 'stdout line before the STDERR marker, stderr line after'
        }
        finally {
            Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    finally {
        Remove-Item -LiteralPath $loadedFile -Force -ErrorAction SilentlyContinue
    }

    # 5. Structural call-site checks on all four files (AST, auxiliary to
    # the behavioral evidence above).
    Test-FixedCallSites -Label 'call-site-worker-canonical' -Path $workerCanonical.path -FunctionName 'Invoke-ADASPipelineChild' -HelperName 'Read-WorkerTextFile' -ArgumentNames @('stdout', 'stderr') -ForbiddenReadVariables @('stdout', 'stderr')
    Test-FixedCallSites -Label 'call-site-worker-active' -Path $workerActive.path -FunctionName 'Invoke-ADASPipelineChild' -HelperName 'Read-WorkerTextFile' -ArgumentNames @('stdout', 'stderr') -ForbiddenReadVariables @('stdout', 'stderr')
    Test-FixedCallSites -Label 'call-site-module-canonical' -Path $moduleCanonical.path -FunctionName 'Invoke-ADASProcess' -HelperName 'Read-ADASProcessOutput' -ArgumentNames @('stdoutPath', 'stderrPath') -ForbiddenReadVariables @('stdoutPath', 'stderrPath')
    Test-FixedCallSites -Label 'call-site-module-active' -Path $moduleActive.path -FunctionName 'Invoke-ADASProcess' -HelperName 'Read-ADASProcessOutput' -ArgumentNames @('stdoutPath', 'stderrPath') -ForbiddenReadVariables @('stdoutPath', 'stderrPath')

    # Machine-readable results + exit code.
    $total = $script:Results.Count
    $passed = @($script:Results | Where-Object { $_.outcome -eq 'PASS' }).Count
    $failed = $total - $passed
    $commit = ''
    try {
        $commit = ((& git -C $repoRoot rev-parse HEAD 2>$null) | Select-Object -First 1).Trim()
    }
    catch {
        $commit = ''
    }
    $document = [pscustomobject]@{
        schemaVersion = '1.0'
        kind = 'task46-control-plane-lock-regression-results'
        checkTotal = $total
        checkPassed = $passed
        checkFailed = $failed
        outcome = $(if ($failed -eq 0) { 'PASS' } else { 'FAIL' })
        checks = $script:Results
        environment = [pscustomobject]@{
            powerShellVersion = $PSVersionTable.PSVersion.ToString()
            windowsVersion = [System.Environment]::OSVersion.VersionString
            commit = $commit
        }
    }
    $resultPath = $ResultPath
    if (-not $resultPath) {
        $resultPath = Join-Path $repoRoot 'services\platform-core\runtime\task46-log-lock-regression-results.json'
    }
    $parent = Split-Path -Parent $resultPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $document | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Output ("RESULT: {0} ({1}/{2} checks) -> {3}" -f $(if ($failed -eq 0) { 'PASS' } else { 'FAIL' }), $passed, $total, $resultPath)
    if ($failed -eq 0) { exit 0 } else { exit 1 }
}

Run-All
