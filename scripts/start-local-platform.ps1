param(
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

Push-Location $repositoryRoot
try {
  & $dockerCommand compose --profile digital-pm up --detach --wait --wait-timeout 120
  if ($LASTEXITCODE -ne 0) {
    throw 'The Imperial Intelligence Compose stack could not be started.'
  }
} finally {
  Pop-Location
}

if (-not $NoBrowser) {
  Start-Process -FilePath 'http://localhost:8080/workspace/'
}

Write-Output 'Imperial Intelligence and Digital Project Managers are available.'
