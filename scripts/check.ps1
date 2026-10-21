$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create venv and install requirements-dev.txt first. See README.md.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js is required for the browser audio tests.'
}

Push-Location -LiteralPath $projectRoot
try {
    & $pythonExecutable -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    & node --test tests/javascript/audio-worklet.test.cjs tests/javascript/auth.test.cjs tests/javascript/live-transport.test.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Audio worklet tests failed.' }
    & node --check tools/voice_client/client.js
    if ($LASTEXITCODE -ne 0) { throw 'Voice client syntax check failed.' }
    & node --check tools/voice_client/auth.js
    if ($LASTEXITCODE -ne 0) { throw 'Authentication client syntax check failed.' }
    & node --check tools/voice_client/live-transport.js
    if ($LASTEXITCODE -ne 0) { throw 'Live transport syntax check failed.' }
    & node --check tools/voice_client/capture-worklet.js
    if ($LASTEXITCODE -ne 0) { throw 'Audio worklet syntax check failed.' }
    & $pythonExecutable -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
}
finally {
    Pop-Location
}
