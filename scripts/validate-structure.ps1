$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
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
  $indexFile = Join-Path $repositoryRoot "sites\$site\index.html"

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
  'docker-compose.yml',
  'docker/nginx/nginx.conf',
  'docker/nginx/conf.d/staging.conf',
  'sites/_portal/index.html',
  'sites/_portal/data/brands.json',
  'sites/_shared/assets/tokens.css',
  'sites/_shared/assets/components.css',
  'sites/_shared/assets/admin.css',
  'sites/_shared/assets/admin.js',
  'sites/_shared/assets/imperial.css',
  'sites/_shared/assets/imperial.js',
  'sites/_shared/assets/data/imperial-home.json'
)

foreach ($requiredFile in $requiredFiles) {
  $fullPath = Join-Path $repositoryRoot $requiredFile
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    throw "Missing required file: $requiredFile"
  }
}

$brandsFile = Join-Path $repositoryRoot 'sites\_portal\data\brands.json'
$brandsData = Get-Content -LiteralPath $brandsFile -Raw | ConvertFrom-Json
$brandIds = @($brandsData.brands | ForEach-Object { $_.id })

if ($brandIds.Count -ne 12) {
  throw "Expected exactly 12 brands in brands.json, found $($brandIds.Count)."
}

foreach ($site in $requiredSites) {
  if ($site -notin $brandIds) {
    throw "Missing brand configuration for site: $site"
  }
}

$homeDataFile = Join-Path $repositoryRoot 'sites\_shared\assets\data\imperial-home.json'
$homeData = Get-Content -LiteralPath $homeDataFile -Raw | ConvertFrom-Json
$homePageFile = Join-Path $repositoryRoot 'sites\imperial\index.html'
$homePage = Get-Content -LiteralPath $homePageFile -Raw

if ($homeData.meta.containsCustomerData -ne $false) {
  throw 'imperial-home.json must explicitly declare containsCustomerData=false.'
}

foreach ($section in $homeData.sections) {
  $idPattern = 'id="' + [regex]::Escape($section.id) + '"'
  if ($homePage -notmatch $idPattern) {
    throw "Missing stable content section ID in Imperial homepage: $($section.id)"
  }
}

$portalPage = Get-Content -LiteralPath (Join-Path $repositoryRoot 'sites\_portal\index.html') -Raw
$requiredPortalMarkers = @(
  'id="brand-select"',
  'data-device="desktop"',
  'data-device="tablet"',
  'data-device="mobile"',
  'id="review-panel"',
  'id="site-preview"'
)

foreach ($marker in $requiredPortalMarkers) {
  if ($portalPage -notmatch [regex]::Escape($marker)) {
    throw "Missing required portal marker: $marker"
  }
}

Write-Output 'Platform structure and prototype data validation passed.'
