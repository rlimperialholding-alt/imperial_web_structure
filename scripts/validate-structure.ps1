$ErrorActionPreference = 'Stop'

$requiredSites = @(
  'imperial',
  'danish-fabrik',
  'bautica',
  'prefab',
  'casa-moderna',
  'family-homes',
  'everyday-homes',
  'property-360',
  'budapesti-magasepito-vallalat',
  'baufreund',
  'red-property',
  'timberhaus'
)

foreach ($site in $requiredSites) {
  $indexFile = Join-Path $PSScriptRoot "..\sites\$site\index.html"

  if (-not (Test-Path -LiteralPath $indexFile -PathType Leaf)) {
    throw "Missing required site entry point: sites/$site/index.html"
  }

  $content = Get-Content -LiteralPath $indexFile -Raw
  if ($content -notmatch 'name="robots" content="noindex,nofollow"') {
    throw "Missing noindex directive: sites/$site/index.html"
  }
}

$requiredFiles = @(
  '.env.example',
  'compose.yaml',
  'docker/nginx/nginx.conf',
  'docker/nginx/conf.d/staging.conf',
  'sites/_portal/index.html',
  'sites/_shared/assets/site.css'
)

$repositoryRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

foreach ($requiredFile in $requiredFiles) {
  $fullPath = Join-Path $repositoryRoot $requiredFile
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    throw "Missing required file: $requiredFile"
  }
}

Write-Output 'Structure validation passed.'
