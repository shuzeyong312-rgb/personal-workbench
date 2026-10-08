$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root 'frontend'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $Root 'dev.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'dev.ps1 has syntax errors' }
$functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false))
foreach ($name in @('Get-ProcessTreeIds', 'Get-ProjectProcessIds')) {
    Invoke-Expression ($functions | Where-Object Name -eq $name).Extent.Text
}
$start = $functions | Where-Object Name -eq 'Start-Project'
# Execute the actual port-selection statements, without migrations or backend startup.
$selection = @($start.Body.EndBlock.Statements | Select-Object -First 2)
1..3 | ForEach-Object {
    foreach ($statement in $selection) { Invoke-Expression $statement.Extent.Text }
    if ($FrontendPort -le 0) { throw 'No port selected' }
    $vite = Join-Path $FrontendDir 'node_modules\vite\bin\vite.js'
    $process = Start-Process node.exe -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru -ArgumentList @(('"' + $vite + '"'), '--host', '127.0.0.1', '--port', $FrontendPort, '--strictPort')
    try {
        $ready = $false
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            if ($process.HasExited) { throw "Vite failed on port $FrontendPort" }
            try {
                $response = Invoke-WebRequest "http://127.0.0.1:$FrontendPort/" -UseBasicParsing -TimeoutSec 1
                $ready = $response.StatusCode -eq 200
            } catch { }
            if ($ready) { break }
            Start-Sleep -Milliseconds 250
        }
        if (-not $ready) { throw 'Frontend did not return HTTP 200' }
        $processes = @(Get-CimInstance Win32_Process)
        $ids = @(Get-ProjectProcessIds $null 'Frontend' $processes @())
        if ($ids -notcontains $process.Id) { throw 'Launcher cannot identify frontend for stopping' }
        Write-Host "PASS: port $FrontendPort, HTTP 200, project process identified"
    } finally {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}
