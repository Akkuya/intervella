$ErrorActionPreference = 'Stop'
$gate = [Threading.EventWaitHandle]::OpenExisting($env:UTSCVACANT_START_GATE)
try { if (-not $gate.WaitOne(15000)) { exit 1 } } finally { $gate.Dispose() }
$env:UTSCVACANT_START_GATE = $null
$rootDirectory = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'workflow.ps1')
. (Join-Path $PSScriptRoot 'operator-config.ps1')
try {
    $configuration = Read-OperatorConfig $rootDirectory
    $env:INGESTION_DATABASE_URL = $configuration.INGESTION_DATABASE_URL
    $env:OPERATOR_SECRET = $configuration.OPERATOR_SECRET
    $env:DATABASE_URL = $null
    $env:TEST_DATABASE_URL = $null
    $env:MIGRATION_DATABASE_URL = $null
    Set-Location (Join-Path $rootDirectory 'backend')
    & uv run --no-env-file --no-sync uvicorn app.operator.app:create_operator_app --factory --host 127.0.0.1 --port 8765 --no-access-log --limit-concurrency 8
    exit $LASTEXITCODE
} catch {
    Write-Host 'Operator startup failed. Check private configuration and OPERATOR.md; no database was altered.'
    exit 1
}
