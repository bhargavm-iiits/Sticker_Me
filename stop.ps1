$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { return }
Push-Location $PSScriptRoot
try {
    & $pythonPath -m scripts.services stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop owned services; inspect runtime/services.json' }
} finally {
    Pop-Location
}
