#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts/workflow.ps1')
$previousDatabase = $env:DATABASE_URL
$job = $null
try {
    $configuration = Read-WorkflowConfig $PSScriptRoot
    $database = Get-LocalDatabase $configuration.DATABASE_URL 'DATABASE_URL'
    $tools = Get-WorkflowTools $PSScriptRoot -Database
    Assert-FreePort 8000
    Assert-FreePort 5173
    Ensure-LocalPostgres $tools.docker $configuration.POSTGRES_CONTAINER $database
    $env:DATABASE_URL = $configuration.DATABASE_URL
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try {
        # A read-only connection/schema probe, never a migration, seed or publication.
        $probe = @'
import sys
from sqlalchemy import text
from app.db import create_db_engine
engine = create_db_engine()
try:
    with engine.connect().execution_options(postgresql_readonly=True) as connection:
        assert connection.scalar(text("SELECT to_regclass('utscvacant.dataset_state') IS NOT NULL"))
except Exception:
    print('Existing database/schema could not be reached. Check DATABASE_URL and reviewed migration status; startup never creates or migrates data.')
    sys.exit(1)
finally:
    engine.dispose()
'@
        $probe | & $tools.uv run --no-env-file --no-sync python -
        if ($LASTEXITCODE -ne 0) { throw 'Database preflight failed. See README.md for safe initial setup/migration instructions.' }
    } finally { Pop-Location }
    if (-not ('UtscVacant.DevProcesses' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'scripts/DevProcesses.cs') }
    $job = New-Object UtscVacant.DevProcesses
    $shell = (Get-Process -Id $PID).Path
    $worker = Join-Path $PSScriptRoot 'scripts/dev-worker.ps1'
    $backend = $job.Start($shell, [string[]]@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $worker, '-Service', 'backend'), $PSScriptRoot, 'backend')
    $frontend = $job.Start($shell, [string[]]@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $worker, '-Service', 'frontend'), $PSScriptRoot, 'frontend')
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $ready = $false
    $backendReady = $false
    $frontendReady = $false
    Write-Host 'Starting application servers. Ctrl+C stops ONLY these servers; PostgreSQL stays running.'
    while ($true) {
        [string]$line = ''
        while ($job.TryRead([ref]$line)) { Write-Host $line }
        if ($backend.HasExited -or $frontend.HasExited) { throw 'An application server exited. See its prefixed output above. Both application trees will be stopped.' }
        if (-not $ready) {
            if (-not $backendReady) {
                try { $backendReady = (Invoke-WebRequest 'http://127.0.0.1:8000/health/live' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200 } catch { }
            }
            if (-not $frontendReady) {
                try { $frontendReady = (Invoke-WebRequest 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200 } catch { }
            }
            if ($backendReady -and $frontendReady) {
                $ready = $true
                Write-Host "`nREADY - App: http://127.0.0.1:5173  API docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
                Write-Host 'Liveness: http://127.0.0.1:8000/health/live  Dataset readiness: http://127.0.0.1:8000/health/ready'
                Write-Host 'Reachable services do not certify current dataset coverage. No data was imported or changed.'
            } elseif ([DateTime]::UtcNow -ge $deadline) { throw 'Startup timed out. Neither service is reported ready; application processes will be stopped.' }
        }
        Start-Sleep -Milliseconds 150
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    $env:DATABASE_URL = $previousDatabase
    if ($job) {
        $job.Dispose()
        [string]$line = ''
        while ($job.TryRead([ref]$line)) { Write-Host $line }
        Write-Host 'Application processes stopped. PostgreSQL was left running.'
    }
}
