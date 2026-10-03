$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimePath = if ($env:STICKERME_DATA_DIR) { $env:STICKERME_DATA_DIR } else { Join-Path $projectRoot 'runtime' }
$modelPath = Join-Path $runtimePath 'models\models\u2netp\u2netp.onnx'
$frontendPath = Join-Path $projectRoot 'frontend\dist\index.html'

if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first' }
if (-not (Test-Path -LiteralPath $frontendPath)) { throw 'Run setup.ps1 to build the frontend' }
if (-not (Test-Path -LiteralPath $modelPath)) { throw 'Run setup.ps1 -DownloadModel to install background removal' }
$portProbe = New-Object System.Net.Sockets.TcpClient
try {
    $portProbe.Connect('127.0.0.1', 8000)
    $portBusy = $true
} catch {
    $portBusy = $false
} finally {
    $portProbe.Dispose()
}
if ($portBusy) { throw 'Port 8000 is already in use. Open the existing app or stop its API before starting another instance.' }

Push-Location $projectRoot
try {
    & $pythonPath -m scripts.services start
    if ($LASTEXITCODE -ne 0) { throw 'Service startup failed; inspect runtime/engine.log and runtime/worker.log' }
    Write-Host 'StickerMe: http://127.0.0.1:8000'
    & $pythonPath -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
} finally {
    & (Join-Path $projectRoot 'stop.ps1')
    Pop-Location
}
