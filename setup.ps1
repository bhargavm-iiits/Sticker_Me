param([switch]$DownloadModel)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$dataRoot = if ($env:STICKERME_DATA_DIR) { $env:STICKERME_DATA_DIR } else { Join-Path $projectRoot 'runtime' }
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools\python'
$env:NPM_CONFIG_CACHE = Join-Path $projectRoot '.cache\npm'
$uvPath = Join-Path $projectRoot '.tools\bin\uv.exe'

if (-not (Test-Path -LiteralPath $uvPath)) {
    $availableUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($availableUv) {
        $uvPath = $availableUv.Source
    } else {
        python -m pip install --target (Join-Path $projectRoot '.tools') uv
        if ($LASTEXITCODE -ne 0) { throw 'Could not install uv' }
    }
}

$pythonPath = $null
if (Test-Path -LiteralPath $env:UV_PYTHON_INSTALL_DIR) {
    $pythonPath = Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Recurse -Filter python.exe |
        Where-Object { $_.FullName -notmatch '\\Lib\\venv\\' } |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $pythonPath) {
    & $uvPath python install 3.12 --install-dir $env:UV_PYTHON_INSTALL_DIR
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 installation failed' }
    $pythonPath = Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Recurse -Filter python.exe |
        Where-Object { $_.FullName -notmatch '\\Lib\\venv\\' } |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $pythonPath) { throw 'Python 3.12 was not found after installation' }

Push-Location $projectRoot
try {
    & $uvPath sync --python $pythonPath --locked
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed' }
    npm.cmd ci --prefix frontend --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
    npm.cmd run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    if ($DownloadModel) {
        $env:U2NET_HOME = Join-Path $dataRoot 'models'
        & (Join-Path $projectRoot '.venv\Scripts\python.exe') -c "from rembg import new_session; new_session('u2netp'); print('U2-NetP ready')"
        if ($LASTEXITCODE -ne 0) { throw 'U2-NetP model download failed' }
        & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m scripts.download_face_models
        if ($LASTEXITCODE -ne 0) { throw 'Face model download failed' }
        & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m scripts.download_liveportrait
        if ($LASTEXITCODE -ne 0) { throw 'LivePortrait download or SHA-256 verification failed' }
    }
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -m scripts.doctor
} finally {
    Pop-Location
}
