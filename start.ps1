param([switch]$Install)
$ErrorActionPreference = 'Stop'
$backendPath = Join-Path $PSScriptRoot 'backend'
$venvPython = Join-Path $backendPath '.venv/Scripts/python.exe'
$runnerArgs = @()
if (Test-Path -LiteralPath $venvPython) { $runner = $venvPython }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $runner = (Get-Command python).Source }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $runner = (Get-Command py).Source; $runnerArgs = @('-3') }
else { throw 'Python 3.11+ was not found. Activate your installed Python environment first.' }
Set-Location -LiteralPath $backendPath
if ($Install) {
    & $runner @runnerArgs -m pip install -r (Join-Path $backendPath 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& $runner @runnerArgs -m uvicorn app.main:app --app-dir $backendPath --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Check your Python environment; use -Install if dependencies are missing.' }
