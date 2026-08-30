# One-shot provenance extraction used ONLY by Task53 author to create the
# canonical tracked unit from the Task52 live profile block (byte-exact).
# Not part of the runtime tooling; kept for reviewability of the extraction.
# Task55 guard: the canonical source now carries TWO sections (acquisition +
# review); this Task53 one-shot tool must never overwrite it, so it refuses to
# run when the target already contains the Task55 acquisition section.
[CmdletBinding()]
param(
    [string]$ModulePath = 'C:/Users/user/AppData/Local/ImperialAI/projects/imperial-intelligence-r2/pro/bin/Imperial-ADAS.psm1',
    [string]$TargetPath = 'C:/Users/user/Documents/.imperial-ai-worktrees/imperial-intelligence-r2/scripts/adas-review-transport/Imperial-ADAS-ReviewTransport.ps1'
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
    $existing = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($TargetPath))
    if ($existing.Contains('function Get-ADASReviewModelContextWindow {')) {
        throw 'Task55 guard: the target already carries the Task55 acquisition section; this Task53 one-shot extraction must not overwrite the two-section canonical source.'
    }
}
$bytes = [IO.File]::ReadAllBytes($ModulePath)
$text = [Text.Encoding]::UTF8.GetString($bytes)
$startMarker = 'function New-ADASReviewAttemptRecord {'
$endMarker = 'function Get-ADASProofManifest {'
$start = $text.IndexOf($startMarker)
$end = $text.IndexOf($endMarker, $start)
if ($start -lt 0 -or $end -lt 0) { throw 'block markers not found in module' }
$prefix = $text.Substring(0, $start)
if ($prefix.Length -gt 0 -and $prefix[$prefix.Length - 1] -ne "`n") { throw 'start marker not at line start' }
$preEnd = $text.Substring(0, $end)
if ($preEnd.Length -gt 0 -and $preEnd[$preEnd.Length - 1] -ne "`n") { throw 'end marker not at line start' }
$block = $text.Substring($start, $end - $start)
if (-not $block.Contains('function Invoke-ADASIndependentReview {')) { throw 'named function missing in block' }
$trimmedEnd = $block.TrimEnd()
if (-not ($trimmedEnd.EndsWith('}'))) { throw 'block does not end at closing brace' }
[IO.File]::WriteAllBytes($TargetPath, [Text.Encoding]::UTF8.GetBytes($block))
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $blockHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($block))) -replace '-', '').ToLowerInvariant()
    $normalized = $block -replace "`r`n", "`n"
    $normHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized))) -replace '-', '').ToLowerInvariant()
}
finally { $sha.Dispose() }
# Structural sanity: all eight named functions present in canonical order
$expected = @(
    'New-ADASReviewAttemptRecord', 'Get-ADASReviewGateCompact', 'Get-ADASReviewDiffSections',
    'Invoke-ADASDeepSeekCompletion', 'Test-ADASReviewContract', 'ConvertTo-ADASReviewContractObject',
    'New-ADASReviewUnavailableResult', 'Invoke-ADASIndependentReview'
)
$position = -1
foreach ($name in $expected) {
    $idx = $block.IndexOf("function $name {", $position + 1)
    if ($idx -lt 0) { throw "expected function $name not found in canonical order" }
    $position = $idx
}
$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($TargetPath, [ref]$tokens, [ref]$errors) | Out-Null
Write-Output "blockLength=$($block.Length)"
Write-Output "blockRawSha256=$blockHash"
Write-Output "blockNormalizedSha256=$normHash"
Write-Output "parseErrors=$($errors.Count)"
Write-Output "firstLine=$($block.Substring(0, [Math]::Min(60, $block.Length)).TrimEnd())"
Write-Output "lastLines=$($block.Substring([Math]::Max(0, $block.Length - 80)).TrimEnd())"
