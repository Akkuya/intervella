#Requires -Version 5.1
param([switch]$Fast)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/workflow.ps1')
$savedEnvironment = @{}
foreach ($name in @('DATABASE_URL', 'TEST_DATABASE_URL', 'INGESTION_DATABASE_URL', 'MIGRATION_DATABASE_URL', 'CI')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$results = New-Object 'System.Collections.Generic.List[object]'
try {
    $configuration = Read-WorkflowConfig $PSScriptRoot
    $tools = Get-WorkflowTools $PSScriptRoot -Database:(-not $Fast)
    if (-not $Fast) {
        $development = Get-LocalDatabase $configuration.DATABASE_URL 'DATABASE_URL'
        $maintenance = Get-LocalDatabase $configuration.TEST_DATABASE_URL 'TEST_DATABASE_URL'
        Assert-SafeTestDatabase $development $maintenance
        Ensure-LocalPostgres $tools.docker $configuration.POSTGRES_CONTAINER $maintenance
    }
    # Tests never inherit development, ingestion or migration connections.
    foreach ($name in @('DATABASE_URL', 'INGESTION_DATABASE_URL', 'MIGRATION_DATABASE_URL', 'TEST_DATABASE_URL')) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    if (-not $Fast) { $env:TEST_DATABASE_URL = $configuration.TEST_DATABASE_URL }
    $backend = Join-Path $PSScriptRoot 'backend'
    $frontend = Join-Path $PSScriptRoot 'frontend'
    $shell = (Get-Process -Id $PID).Path
    Invoke-WorkflowCheck Workflow 'PowerShell regression' $shell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'scripts/tests/workflow.tests.ps1')) $PSScriptRoot $results
    Invoke-WorkflowCheck Backend 'Ruff lint' $tools.uv @('run', '--no-env-file', '--no-sync', 'ruff', 'check', '.') $backend $results
    Invoke-WorkflowCheck Backend 'Ruff format' $tools.uv @('run', '--no-env-file', '--no-sync', 'ruff', 'format', '--check', '.') $backend $results
    Invoke-WorkflowCheck Backend mypy $tools.uv @('run', '--no-env-file', '--no-sync', 'mypy', '.') $backend $results
    $pytest = if ($Fast) { @('run', '--no-env-file', '--no-sync', 'pytest', '-m', 'not postgres') } else { @('run', '--no-env-file', '--no-sync', 'pytest', '--require-postgres') }
    Invoke-WorkflowCheck Backend pytest $tools.uv $pytest $backend $results
    foreach ($entry in @(@('ESLint', 'lint'), @('Prettier', 'format:check'), @('TypeScript', 'typecheck'), @('Unit tests', 'test'), @('Build', 'build'))) {
        Invoke-WorkflowCheck Frontend $entry[0] $tools.'npm.cmd' @('run', $entry[1]) $frontend $results
    }
    Invoke-WorkflowCheck Frontend 'Dependency audit' $tools.'npm.cmd' @('audit', '--audit-level=high') $frontend $results
    if ($Fast) {
        Write-Host "`nFAST: PostgreSQL integration tests and Playwright browser tests were SKIPPED." -ForegroundColor Yellow
        $results.Add([pscustomobject]@{ Group = 'Backend'; Name = 'PostgreSQL integration'; Status = 'SKIP' })
        $results.Add([pscustomobject]@{ Group = 'Frontend'; Name = 'Playwright'; Status = 'SKIP' })
    } elseif (($results | Where-Object { $_.Name -eq 'Build' }).Status -ne 'PASS') {
        Write-Host 'Playwright skipped because Build failed; refusing to test stale production assets.'
        $results.Add([pscustomobject]@{ Group = 'Frontend'; Name = 'Playwright'; Status = 'SKIP' })
    } else {
        try {
            Assert-FreePort 4173
            # Force a fresh preview server, matching CI instead of reusing somebody else's server.
            $env:CI = 'true'
            Invoke-WorkflowCheck Frontend Playwright $tools.'npm.cmd' @('run', 'test:e2e') $frontend $results
        } catch {
            Write-Host $_.Exception.Message -ForegroundColor Red
            $results.Add([pscustomobject]@{ Group = 'Frontend'; Name = 'Playwright'; Status = 'FAIL' })
        }
    }
    Write-Host "`nUTSCVacant - Project Checks"
    foreach ($group in @('Workflow', 'Backend', 'Frontend')) {
        Write-Host "`n$group"
        foreach ($result in $results | Where-Object { $_.Group -eq $group }) { Write-Host ('  {0,-24} {1}' -f $result.Name, $result.Status) }
    }
    if (@($results | Where-Object { $_.Status -eq 'FAIL' }).Count) { Write-Host "`nOverall: CHECKS FAILED" -ForegroundColor Red; exit 1 }
    Write-Host $(if ($Fast) { "`nOverall: FAST CHECKS PASSED (integration/browser checks skipped)" } else { "`nOverall: ALL CHECKS PASSED" }) -ForegroundColor Green
} catch { Write-Host "Setup FAIL: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
}
