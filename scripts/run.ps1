param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create venv and install requirements first. See README.md.'
}

Push-Location -LiteralPath $projectRoot
try {
    & $pythonExecutable -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers --ws-max-size 8192 --ws-max-queue 8
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
