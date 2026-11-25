param([ValidateSet(8011)][int]$Port = 8011)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install requirements.txt first; see README.md.' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'frontend\dist\index.html'))) { throw 'Build the frontend first: cd frontend; npm ci; npm run build.' }
Push-Location $taskRoot
try { & $taskPython -m uvicorn relay.app:app --app-dir backend --host 127.0.0.1 --port $Port }
finally { Pop-Location }
