param(
  [string]$CrmStatePath = $env:CRM_TEST_STATE_PATH,
  [string]$CrmWorkspaceId = 'imperial-test',
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dockerCandidates = @(
  (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
  'docker.exe'
)
$dockerCommand = $dockerCandidates |
  Where-Object { $_ -eq 'docker.exe' -or (Test-Path -LiteralPath $_ -PathType Leaf) } |
  Select-Object -First 1

if (-not $dockerCommand) {
  throw 'Docker Desktop or docker.exe was not found.'
}

function Test-DockerEngine {
  & $dockerCommand info *> $null
  return $LASTEXITCODE -eq 0
}

function New-RandomSecret([int]$ByteCount = 32) {
  $bytes = New-Object byte[] $ByteCount
  $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $generator.GetBytes($bytes)
  } finally {
    $generator.Dispose()
  }
  return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

function Resolve-OrCreateLocalSecret(
  [string]$EnvironmentVariable,
  [string]$FileName
) {
  $configuredPath = [Environment]::GetEnvironmentVariable($EnvironmentVariable)
  $siblingPlatformRoot = Join-Path (Split-Path $repositoryRoot -Parent) 'imperial_web_structure_platform'
  $runtimeSecretRoot = Join-Path $env:ProgramData 'ImperialMigration\runtime-secrets'
  $candidates = @(
    $configuredPath,
    (Join-Path $repositoryRoot "secrets\$FileName"),
    (Join-Path $siblingPlatformRoot "secrets\$FileName"),
    (Join-Path $runtimeSecretRoot $FileName)
  ) | Where-Object { $_ }

  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      return (Resolve-Path -LiteralPath $candidate).Path -replace '\\', '/'
    }
  }

  New-Item -ItemType Directory -Path $runtimeSecretRoot -Force | Out-Null
  $secretPath = Join-Path $runtimeSecretRoot $FileName
  [IO.File]::WriteAllText(
    $secretPath,
    (New-RandomSecret),
    [Text.UTF8Encoding]::new($false)
  )
  return $secretPath -replace '\\', '/'
}

if (-not (Test-DockerEngine)) {
  & $dockerCommand desktop start
  if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop could not be started.'
  }
}

$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline -and -not (Test-DockerEngine)) {
  Start-Sleep -Seconds 5
}
if (-not (Test-DockerEngine)) {
  throw 'The Docker engine did not become available within three minutes.'
}

if ($CrmStatePath) {
  $resolvedCrmState = (Resolve-Path -LiteralPath $CrmStatePath).Path
  if (-not (Test-Path -LiteralPath $resolvedCrmState -PathType Container)) {
    throw 'The supplied CRM state path is not a directory.'
  }
  $env:CRM_TEST_STATE_PATH = $resolvedCrmState -replace '\\', '/'
}

$env:CRM_WORKSPACE_ID = $CrmWorkspaceId
$env:CRM_TEST_PORT = '18787'
$env:HUB_TEST_PORT = '18080'
$env:ITEP_TEST_PORT = '13000'
$env:MOCK_TEST_PORT = '19010'
$env:CRM_MIGRATION_TOKEN = New-RandomSecret
$env:ITEP_CRM_READ_TOKEN = New-RandomSecret
$env:ITEP_IDENTITY_SHARED_SECRET = New-RandomSecret
$env:PLATFORM_DB_PASSWORD_FILE = Resolve-OrCreateLocalSecret `
  'PLATFORM_DB_PASSWORD_FILE' 'platform_db_password.txt'
$env:DPM_DB_PASSWORD_FILE = Resolve-OrCreateLocalSecret `
  'DPM_DB_PASSWORD_FILE' 'dpm_db_password.txt'
$env:DPM_AUTH_HS256_SECRET_FILE = Resolve-OrCreateLocalSecret `
  'DPM_AUTH_HS256_SECRET_FILE' 'dpm_auth_hs256_secret.txt'

Push-Location $repositoryRoot
try {
  & $dockerCommand compose --profile digital-pm up `
    --detach --build --force-recreate --wait --wait-timeout 180
  if ($LASTEXITCODE -ne 0) {
    throw 'The visual platform and Digital PM stack could not be started.'
  }

  & $dockerCommand compose `
    --project-name imperial-complete-test `
    --file docker-compose.github-test.yml `
    up --detach --build --wait --wait-timeout 240
  if ($LASTEXITCODE -ne 0) {
    throw 'The live CRM, ITEP and Integration Hub stack could not be started.'
  }
} finally {
  Pop-Location
}

if (-not $NoBrowser) {
  Start-Process -FilePath 'http://localhost:8080/workspace/'
  Start-Process -FilePath 'http://localhost:18787/'
}

Write-Output 'Imperial Intelligence complete local test environment is ready:'
Write-Output '  Platform workspace: http://localhost:8080/workspace/'
Write-Output '  Live CRM:          http://localhost:18787/'
Write-Output '  Digital PM:        http://localhost:8080/digital-project-managers/'
Write-Output '  ITEP health:       http://localhost:13000/health/ready'
Write-Output '  Integration Hub:   http://localhost:18080/ready'
