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

$tar = Get-Command tar.exe -ErrorAction Stop
$arguments = @(
    "-a", "-c", "-f", $archivePath,
    "--exclude=.git",
    "--exclude=.env",
    "--exclude=.env.*",
    "--exclude=node_modules",
    "--exclude=.venv",
    "--exclude=dist",
    "--exclude=build",
    "--exclude=coverage",
    "--exclude=.next",
    "--exclude=.wrangler",
    "--exclude=secrets/*.txt",
    "--exclude=*.log",
    "."
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
}

$hash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
Write-Output ([pscustomobject]@{
    Archive = $archivePath
    SizeBytes = (Get-Item -LiteralPath $archivePath).Length
    SHA256 = $hash.Hash
})
