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
  'sites/_portal/data/artifacts.json',
  'sites/_portal/data/platform.json',
  'sites/_portal/data/system.json',
  'sites/_shared/assets/tokens.css',
  'sites/_shared/assets/components.css',
  'sites/_shared/assets/admin.css',
  'sites/_shared/assets/admin.js',
  'sites/_shared/assets/preview-bootstrap.css',
  'sites/_shared/assets/review-bridge.css',
  'sites/_shared/assets/review-bridge.js',
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

$artifactsFile = Join-Path $repositoryRoot 'sites\_portal\data\artifacts.json'
$artifactsData = Get-Content -LiteralPath $artifactsFile -Raw | ConvertFrom-Json

if ($artifactsData.meta.containsCustomerData -ne $false) {
  throw 'artifacts.json must explicitly declare containsCustomerData=false.'
}

if ($artifactsData.meta.runtimeExternalApis -ne $false) {
  throw 'artifacts.json must explicitly declare runtimeExternalApis=false.'
}

$platformData = Get-Content -LiteralPath (Join-Path $repositoryRoot 'sites\_portal\data\platform.json') -Raw | ConvertFrom-Json
$systemData = Get-Content -LiteralPath (Join-Path $repositoryRoot 'sites\_portal\data\system.json') -Raw | ConvertFrom-Json

if (@($platformData.modules).Count -ne 40) {
  throw "Expected 40 registered Imperial Intelligence modules, found $(@($platformData.modules).Count)."
}

if (@($systemData.roles).Count -lt 10 -or @($systemData.eventContracts).Count -lt 12) {
  throw 'system.json requires role workspaces and canonical event contracts.'
}

if ($systemData.meta.containsCustomerData -ne $false -or
    $systemData.meta.usesExternalApis -ne $false -or
    $systemData.meta.containsProductionSecrets -ne $false) {
  throw 'system.json must remain synthetic and offline without production secrets.'
}

$totalTestPages = 0
foreach ($brand in $brandsData.brands) {
  $artifactBrand = $artifactsData.brands.PSObject.Properties[$brand.id].Value
  $artifactPages = if ($null -eq $artifactBrand) { @() } else { @($artifactBrand.pages) }
  $configuredCount = $artifactPages.Count

  if ($brand.pageCount -ne $configuredCount) {
    throw "Page count mismatch for $($brand.id): brands.json=$($brand.pageCount), artifacts.json=$configuredCount"
  }

  $totalTestPages += $configuredCount
  foreach ($page in $artifactPages) {
    $relativePath = if ($page.path -eq '/') {
      "sites\$($brand.id)\index.html"
    } else {
      "sites\$($brand.id)$($page.path.Replace('/', '\'))"
    }
    $previewFile = Join-Path $repositoryRoot $relativePath

    if (-not (Test-Path -LiteralPath $previewFile -PathType Leaf)) {
      throw "Missing configured preview file: $relativePath"
    }

    if ($page.kind -like 'drive-*') {
      if ([string]::IsNullOrWhiteSpace($page.sourceId)) {
        throw "Missing Drive sourceId for $($brand.id)$($page.path)"
      }

      $previewContent = Get-Content -LiteralPath $previewFile -Raw
      if ($previewContent -notmatch 'name="robots" content="noindex,nofollow"') {
        throw "Missing noindex directive in imported preview: $relativePath"
      }
      if ($previewContent -notmatch '/assets/review-bridge.js') {
        throw "Missing review bridge in imported preview: $relativePath"
      }
      if ($previewContent -match 'cdn\.jsdelivr\.net/npm/bootstrap') {
        throw "External Bootstrap runtime dependency remains in: $relativePath"
      }
    }
  }
}

if ($totalTestPages -ne 50) {
  throw "Expected 50 configured test pages, found $totalTestPages."
}

$remoteCssAssets = Get-ChildItem (Join-Path $repositoryRoot 'sites') -Recurse -File -Filter '*.css' |
  Where-Object { $_.FullName -match '[\\/]drive[\\/]' } |
  Where-Object { (Get-Content -LiteralPath $_.FullName -Raw) -match 'url\(["'']?https?://' }

if ($remoteCssAssets) {
  throw "Imported preview CSS contains remote runtime assets: $($remoteCssAssets.FullName -join ', ')"
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
  'id="page-select"',
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
