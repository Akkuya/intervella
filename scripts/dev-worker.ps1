param([ValidateSet('backend', 'frontend')][string]$Service)
$ErrorActionPreference = 'Stop'
$gate = [Threading.EventWaitHandle]::OpenExisting($env:UTSCVACANT_START_GATE)
try { if (-not $gate.WaitOne(15000)) { exit 1 } } finally { $gate.Dispose() }
$env:UTSCVACANT_START_GATE = $null
$rootDirectory = Split-Path $PSScriptRoot -Parent
Set-Location (Join-Path $rootDirectory $Service)
if ($Service -eq 'backend') {
    & uv run --no-env-file --no-sync uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
} else {
    & npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort --clearScreen false
}
exit $LASTEXITCODE
