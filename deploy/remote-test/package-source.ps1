[CmdletBinding()]
param(
    [string]$DestinationDirectory = "$env:USERPROFILE\Downloads"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archiveName = "imperial-intelligence-remote-test-$timestamp.zip"
$archivePath = Join-Path $DestinationDirectory $archiveName

New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null

$sourceCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sourceCommit)) {
    throw "Could not determine the source commit."
}
$workingTreeState = & git -C $repoRoot status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0) {
    throw "Could not determine the working tree state."
}
$sourceRevision = if ($workingTreeState) { "$sourceCommit-dirty" } else { $sourceCommit }
$revisionPath = Join-Path $repoRoot ".source-commit"
if (Test-Path -LiteralPath $revisionPath) {
    throw "Refusing to overwrite existing source metadata: $revisionPath"
}

$tar = Get-Command tar.exe -ErrorAction Stop
$arguments = @(
    "-a", "-c", "-f", $archivePath,
    "--exclude=.git",
    "--exclude=node_modules",
    "--exclude=.venv",
    "--exclude=dist",
    "--exclude=coverage",
    "--exclude=.next",
    "--exclude=.wrangler",
    "--exclude=services/platform-core/data/platform_demo_runtime.json",
    "--exclude=services/platform-core/data/*.db",
    "--exclude=secrets/*.txt",
    "--exclude=*.log",
    "."
)

# Exclude every real environment file by its exact relative path while keeping
# secret-free .env.example files in the source package.
$environmentFiles = Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -File -Filter ".env*" |
    Where-Object { $_.Name -ne ".env.example" }
foreach ($environmentFile in $environmentFiles) {
    $relativeEnvironmentPath = $environmentFile.FullName.Substring(
        $repoRoot.Length
    ).TrimStart([char[]]"\/").Replace("\", "/")
    $arguments = @("--exclude=$relativeEnvironmentPath") + $arguments
}

[System.IO.File]::WriteAllText(
    $revisionPath,
    "$sourceRevision`n",
    [System.Text.UTF8Encoding]::new($false)
)

Push-Location $repoRoot
try {
    & $tar.Source @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Archive creation failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
    [System.IO.File]::Delete($revisionPath)
}

$hash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
Write-Output ([pscustomobject]@{
    Archive = $archivePath
    SizeBytes = (Get-Item -LiteralPath $archivePath).Length
    SHA256 = $hash.Hash
})
