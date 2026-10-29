param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [string]$PublicOrigin = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create venv and install requirements first. See README.md.'
}

Push-Location -LiteralPath $projectRoot
$previousEnvironment = $env:ENVIRONMENT
$previousOrigin = $env:PUBLIC_ORIGIN
try {
    if ($PublicOrigin) {
        $env:ENVIRONMENT = 'tunnel'
        $env:PUBLIC_ORIGIN = $PublicOrigin
    }
    $effectiveEnvironment = & $pythonExecutable -c 'from app.core.config import Settings; print(Settings().environment)'
    if ($LASTEXITCODE -ne 0) { throw 'Invalid backend configuration' }
    if ($effectiveEnvironment -eq 'tunnel') {
        # Only the local tunnel agent can supply trusted forwarded client/scheme headers.
        & $pythonExecutable -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 --proxy-headers --forwarded-allow-ips '127.0.0.1,::1' --ws-max-size 8192 --ws-max-queue 8
    }
    else {
        & $pythonExecutable -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1 --no-proxy-headers --ws-max-size 8192 --ws-max-queue 8
    }
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
}
finally {
    $env:ENVIRONMENT = $previousEnvironment
    $env:PUBLIC_ORIGIN = $previousOrigin
    Pop-Location
}
