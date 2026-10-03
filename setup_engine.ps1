param([switch]$SkipDownloads)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$uvPath = Join-Path $projectRoot '.tools\bin\uv.exe'
$appPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$enginePython = Join-Path $projectRoot 'runtime\engine-env\Scripts\python.exe'
$comfyPath = Join-Path $projectRoot 'runtime\comfyui'
$ggufPath = Join-Path $comfyPath 'custom_nodes\ComfyUI-GGUF'
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'

if (-not (Test-Path -LiteralPath $appPython)) { throw 'Run setup.ps1 -DownloadModel first' }

function Install-PinnedRepository($repository, $destination, $revision) {
    if (-not (Test-Path -LiteralPath $destination)) {
        git clone --depth 1 $repository $destination
        if ($LASTEXITCODE -ne 0) { throw "Clone failed: $repository" }
    }
    $safePath = $destination.Replace('\', '/')
    $current = git -c "safe.directory=$safePath" -C $destination rev-parse HEAD
    if ($current -ne $revision) {
        $changes = git -c "safe.directory=$safePath" -C $destination status --porcelain --untracked-files=no
        if ($changes) { throw "Refusing to replace modified engine source: $destination" }
        git -c "safe.directory=$safePath" -C $destination fetch --depth 1 origin $revision
        if ($LASTEXITCODE -ne 0) { throw "Could not fetch pinned revision: $revision" }
        git -c "safe.directory=$safePath" -C $destination checkout --detach $revision
        if ($LASTEXITCODE -ne 0) { throw 'Could not select pinned revision' }
    }
}

Push-Location $projectRoot
try {
    Install-PinnedRepository 'https://github.com/Comfy-Org/ComfyUI.git' $comfyPath 'e9027f2b30f37bb3052714eb08fcf479542f4fc0'
    Install-PinnedRepository 'https://github.com/city96/ComfyUI-GGUF.git' $ggufPath '6ea2651e7df66d7585f6ffee804b20e92fb38b8a'
    if (-not (Test-Path -LiteralPath $enginePython)) {
        & $uvPath venv (Join-Path $projectRoot 'runtime\engine-env') --python $appPython
        if ($LASTEXITCODE -ne 0) { throw 'Engine environment creation failed' }
    }
    & $uvPath pip install --python $enginePython 'torch==2.11.0+cu128' 'torchvision==0.26.0+cu128' --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed' }
    & $uvPath pip install --python $enginePython -r workflows/engine-requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Engine dependency installation failed' }
    & $enginePython -c "import torch; assert torch.cuda.is_available(), 'CUDA GPU unavailable'; print(torch.cuda.get_device_name(0))"
    if ($LASTEXITCODE -ne 0) { throw 'GPU validation failed' }
    if (-not $SkipDownloads) {
        & $appPython -m scripts.download_engine
        if ($LASTEXITCODE -ne 0) { throw 'Model download or SHA-256 verification failed' }
    }
    Write-Host 'Cartoon engine installed. Run start.ps1, then open http://127.0.0.1:8000.'
} finally {
    Pop-Location
}
