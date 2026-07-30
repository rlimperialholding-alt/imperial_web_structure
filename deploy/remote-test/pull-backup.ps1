[CmdletBinding()]
param(
    [string]$Server = "91.99.93.80",
    [string]$RemoteUser = "imperialadmin",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\imperial-intelligence-admin",
    [string]$DestinationDirectory = "$env:USERPROFILE\Documents\Imperial Intelligence Backups"
)

$ErrorActionPreference = "Stop"
$sshArguments = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes"
)
$remote = "$RemoteUser@$Server"

New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null

$latestBackup = (
    & ssh @sshArguments $remote `
        "find /opt/imperial-intelligence/backups -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1"
).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not query the latest remote backup."
}
if ($latestBackup -notmatch "^/opt/imperial-intelligence/backups/([0-9]{8}T[0-9]{6}Z)$") {
    throw "The remote backup path was not in the expected format."
}

$backupName = $Matches[1]
$archiveName = "imperial-intelligence-backup-$backupName.tar.gz"
$remoteArchive = "/tmp/$archiveName"
$localArchive = Join-Path $DestinationDirectory $archiveName
$partialArchive = "$localArchive.part"
$checksumFile = "$localArchive.sha256"

try {
    $checksumOutput = (
        & ssh @sshArguments $remote `
            "tar -C /opt/imperial-intelligence/backups -czf '$remoteArchive' '$backupName' && sha256sum '$remoteArchive'"
    ).Trim()
    if ($LASTEXITCODE -ne 0 -or $checksumOutput -notmatch "^([0-9a-f]{64})\s+") {
        throw "Could not create or checksum the remote backup archive."
    }
    $expectedHash = $Matches[1].ToUpperInvariant()

    if (Test-Path -LiteralPath $partialArchive) {
        Remove-Item -LiteralPath $partialArchive -Force
    }
    & scp @sshArguments "${remote}:$remoteArchive" $partialArchive
    if ($LASTEXITCODE -ne 0) {
        throw "Could not download the remote backup archive."
    }

    $actualHash = (Get-FileHash -LiteralPath $partialArchive -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) {
        throw "The downloaded backup checksum does not match the remote checksum."
    }

    Move-Item -LiteralPath $partialArchive -Destination $localArchive -Force
    [System.IO.File]::WriteAllText(
        $checksumFile,
        "$expectedHash  $archiveName`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Output "Backup copied and verified: $localArchive"
}
finally {
    & ssh @sshArguments $remote "rm -f -- '$remoteArchive'" | Out-Null
}
