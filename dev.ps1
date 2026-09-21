$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Vite = Join-Path $FrontendDir 'node_modules\.bin\vite.cmd'
$FrontendPort = 5200

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Error "Backend Python virtual environment not found: $Python"
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules') -PathType Container)) {
    Write-Error "Frontend dependencies not found: $FrontendDir\node_modules"
    exit 1
}

if (-not (Test-Path -LiteralPath $Vite -PathType Leaf)) {
    Write-Error "Vite executable not found: $Vite"
    exit 1
}

$backendCommand = "Set-Location -LiteralPath '$BackendDir'; & '$Python' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8100"
$frontendCommand = "Set-Location -LiteralPath '$FrontendDir'; & '$Vite' --host 127.0.0.1 --port $FrontendPort --strictPort --open"

Start-Process powershell.exe -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $backendCommand)
Start-Process powershell.exe -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $frontendCommand)

Write-Host 'Backend started in a new PowerShell window: http://127.0.0.1:8100'
Write-Host "Frontend started in a new PowerShell window: http://127.0.0.1:$FrontendPort"
