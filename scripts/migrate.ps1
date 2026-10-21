$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create venv and install requirements first. See README.md.'
}

Push-Location -LiteralPath $projectRoot
try {
    & $pythonExecutable -m alembic -c alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
}
finally {
    Pop-Location
}
