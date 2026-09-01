[CmdletBinding()]
param(
    [switch]$DispatchSelfTest
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Test-ADASWindowsPlatform {
    # Windows PowerShell 5.1 does not define the PowerShell Core IsWindows automatic variable.
    if ([string]$PSVersionTable.PSEdition -eq 'Desktop') { return $true }
    $platformVariable = Get-Variable -Name IsWindows -Scope Global -ErrorAction SilentlyContinue
    if ($null -ne $platformVariable) { return [bool]$platformVariable.Value }
    return ([string]$env:OS -eq 'Windows_NT')
}

function Invoke-ADASCICommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][ref]$ExitCode
    )

    if (Test-ADASWindowsPlatform) {
        $shell = if ([string]::IsNullOrWhiteSpace([string]$env:ComSpec)) { 'cmd.exe' } else { [string]$env:ComSpec }
        & $shell /d /s /c $Command
    }
    else {
        & bash -lc $Command
    }

    $currentExitCode = $LASTEXITCODE
    if ($null -eq $currentExitCode) { $currentExitCode = 0 }
    $ExitCode.Value = [int]$currentExitCode
}

function Get-ADASCIAttestationResults {
    # A generic List[object] expanded directly with @(...) throws "Argument types
    # do not match", which would abort every attestation write. Enumerate it
    # through the pipeline first so ConvertTo-Json receives a normal object
    # array. Same defect and same workaround as in Initialize-ADASProject.ps1.
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Results)
    return @($Results | ForEach-Object { $_ })
}

if ($DispatchSelfTest) {
    $marker = Join-Path ([IO.Path]::GetTempPath()) ("imperial-adas-dispatch-{0}.txt" -f [guid]::NewGuid().ToString('N'))
    $previousMarker = [Environment]::GetEnvironmentVariable('ADAS_DISPATCH_MARKER', 'Process')
    try {
        $env:ADAS_DISPATCH_MARKER = $marker
        $testCommand = if (Test-ADASWindowsPlatform) { 'echo ADAS_DISPATCH>>"%ADAS_DISPATCH_MARKER%"' } else { 'printf ''ADAS_DISPATCH\n'' >> "$ADAS_DISPATCH_MARKER"' }
        $testExitCode = 0
        Invoke-ADASCICommand -Command $testCommand -ExitCode ([ref]$testExitCode)
        if ($testExitCode -ne 0) { throw "ADAS CI dispatch self-test command failed with exit code $testExitCode." }
        $markerLines = @(Get-Content -LiteralPath $marker -Encoding UTF8 | Where-Object { [string]$_ -eq 'ADAS_DISPATCH' })
        if ($markerLines.Count -ne 1) { throw "ADAS CI command dispatch must execute exactly once; observed $($markerLines.Count) executions." }
    }
    finally {
        Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
        if ($null -eq $previousMarker) { Remove-Item Env:ADAS_DISPATCH_MARKER -ErrorAction SilentlyContinue }
        else { $env:ADAS_DISPATCH_MARKER = $previousMarker }
    }
    Write-Host 'ADAS CI command dispatch self-test: PASS (exactly one execution).'
    exit 0
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$configPath = Join-Path $root '.imperial-adas\project.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$results = New-Object 'System.Collections.Generic.List[object]'
$manifestPath = Join-Path $root '.imperial-adas\protected-corpus-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Protected corpus manifest missing.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($entry in @($manifest.files)) {
    $relative = ([string]$entry.path).Replace('/', [IO.Path]::DirectorySeparatorChar)
    $path = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Protected corpus file missing: $relative" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "Protected corpus hash mismatch: $relative" }
}
$results.Add([pscustomobject]@{ group='protected-corpus'; name='SHA-256 manifest verification'; command='Get-FileHash'; exitCode=0; passed=$true; durationMs=0 })
$groups = @('restore','build','format','lint','typecheck','unit','integration','contract','e2e','coverage','dependencyAudit','sast')
foreach ($group in $groups) {
    if (-not ($config.commands.PSObject.Properties.Name -contains $group)) { continue }
    foreach ($entry in @($config.commands.$group)) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.command)) { continue }
        Write-Host "::group::ADAS $group / $($entry.name)"
        $started = Get-Date
        $code = 0
        Invoke-ADASCICommand -Command ([string]$entry.command) -ExitCode ([ref]$code)
        Write-Host '::endgroup::'
        $results.Add([pscustomobject]@{ group=$group; name=$entry.name; command=$entry.command; exitCode=[int]$code; passed=([int]$code -eq 0); durationMs=[int]((Get-Date)-$started).TotalMilliseconds })
        if ([int]$code -ne 0) {
            $attestation = [ordered]@{ schemaVersion='2.1'; commit=$env:GITHUB_SHA; runId=$env:GITHUB_RUN_ID; status='BLOCKED'; generatedAt=(Get-Date).ToUniversalTime().ToString('o'); results=(Get-ADASCIAttestationResults -Results $results) }
            $attestation | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $root 'ci-attestation.json') -Encoding UTF8
            exit [int]$code
        }
    }
}
$attestation = [ordered]@{ schemaVersion='2.1'; commit=$env:GITHUB_SHA; runId=$env:GITHUB_RUN_ID; status='PASS'; generatedAt=(Get-Date).ToUniversalTime().ToString('o'); results=(Get-ADASCIAttestationResults -Results $results) }
$attestation | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $root 'ci-attestation.json') -Encoding UTF8
exit 0