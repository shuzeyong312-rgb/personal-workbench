$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Vite = Join-Path $FrontendDir 'node_modules\.bin\vite.cmd'
$BackendPort = 8200
$FrontendPort = 5300
$LogsDir = Join-Path $Root 'logs'

if (-not (Test-Path -LiteralPath $LogsDir -PathType Container)) {
    New-Item -ItemType Directory -Path $LogsDir | Out-Null
}

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

function Get-ProcessTreeIds($SeedIds, $Processes) {
    $ids = @($SeedIds | Where-Object { $_ } | Sort-Object -Unique)
    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $Processes) {
            if ($ids -contains $process.ParentProcessId -and $ids -notcontains $process.ProcessId) {
                $ids += $process.ProcessId
                $changed = $true
            }
        }
    }
    return @($ids | Sort-Object -Unique)
}

function Get-ProjectProcessIds($Port, $Kind, $Processes, $ListenerIds) {
    if ($Kind -eq 'Backend') {
        $roots = @($Processes | Where-Object {
            $_.CommandLine -like "*$Python*" -and $_.CommandLine -match "-m uvicorn .*--port $Port"
        })
    } else {
        $roots = @($Processes | Where-Object {
            $_.Name -eq 'node.exe' -and $_.CommandLine -like "*$FrontendDir*node_modules*vite*--port $Port*"
        })
    }

    if (-not $roots) {
        return @()
    }

    $rootIds = @($roots | Select-Object -ExpandProperty ProcessId)
    $treeIds = @(Get-ProcessTreeIds $rootIds $Processes)
    $hasProjectListener = @($ListenerIds | Where-Object { $treeIds -contains $_ }).Count -gt 0
    if ($hasProjectListener -or $ListenerIds.Count -eq 0) {
        return $treeIds
    }
    return @()
}

function Stop-ProjectService($Ids) {
    foreach ($processId in $Ids | Where-Object { $_ } | Sort-Object -Unique) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Start-Project {
    $backendLog = Join-Path $LogsDir 'backend.log'
    $frontendLog = Join-Path $LogsDir 'frontend.log'
    Push-Location $BackendDir
    try {
        & $Python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Database migration failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
    $backendCommand = "Set-Location -LiteralPath '$BackendDir'; & '$Python' -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort *> '$backendLog'"
    $frontendCommand = "Set-Location -LiteralPath '$FrontendDir'; & '$Vite' --host 127.0.0.1 --port $FrontendPort --strictPort --open *> '$frontendLog'"

    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-ExecutionPolicy', 'Bypass', '-Command', $backendCommand)
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-ExecutionPolicy', 'Bypass', '-Command', $frontendCommand)
}

$processes = @(Get-CimInstance Win32_Process)
$backendListeners = @(Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue)
$frontendListeners = @(Get-NetTCPConnection -State Listen -LocalPort $FrontendPort -ErrorAction SilentlyContinue)
$backendListenerIds = @($backendListeners | Select-Object -ExpandProperty OwningProcess -Unique)
$frontendListenerIds = @($frontendListeners | Select-Object -ExpandProperty OwningProcess -Unique)
$backendIds = @(Get-ProjectProcessIds $BackendPort 'Backend' $processes $backendListenerIds)
$frontendIds = @(Get-ProjectProcessIds $FrontendPort 'Frontend' $processes $frontendListenerIds)
$backendRunning = $backendIds.Count -gt 0
$frontendRunning = $frontendIds.Count -gt 0

if ($backendRunning -and $frontendRunning) {
    Stop-ProjectService $backendIds
    Stop-ProjectService $frontendIds
    Write-Host 'Project stopped'
    exit 0
}

if ($backendRunning -or $frontendRunning) {
    Stop-ProjectService $backendIds
    Stop-ProjectService $frontendIds
    Start-Project
    Write-Host 'Detected leftovers; project restarted'
    exit 0
}

Start-Project
Write-Host 'Project started'
