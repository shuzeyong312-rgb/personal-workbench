param([ValidateSet('a19', 'five')][string]$Scope = 'a19')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$projectProfilePath = (Resolve-Path (Join-Path $root '.browser-profile')).Path
$chrome = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($projectProfilePath)
})
$locks = @(
    Get-ChildItem -LiteralPath $projectProfilePath -Filter 'Singleton*' -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath (Join-Path $projectProfilePath 'Default') -Filter 'Singleton*' -Force -ErrorAction SilentlyContinue
)
if ($chrome.Count -gt 0 -or $locks.Count -gt 0) {
    throw "Profile is occupied or locked (chrome=$($chrome.Count), locks=$($locks.Count)); no browser started."
}
& (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'probe.py') --scope $Scope
exit $LASTEXITCODE
