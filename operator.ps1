#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/workflow.ps1')
. (Join-Path $PSScriptRoot 'scripts/operator-config.ps1')
$job = $null
try {
    $null = Read-OperatorConfig $PSScriptRoot
    $tools = Get-WorkflowTools $PSScriptRoot
    Assert-FreePort 8765
    Push-Location (Join-Path $PSScriptRoot 'frontend')
    try {
        & $tools.'npm.cmd' run build:operator
        if ($LASTEXITCODE -ne 0) { throw 'Operator frontend build failed.' }
    } finally { Pop-Location }
    if (-not ('UtscVacant.DevProcesses' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'scripts/DevProcesses.cs') }
    $job = New-Object UtscVacant.DevProcesses
    $shell = (Get-Process -Id $PID).Path
    $worker = Join-Path $PSScriptRoot 'scripts/operator-worker.ps1'
    $process = $job.Start($shell, [string[]]@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $worker), $PSScriptRoot, 'operator')
    Write-Host 'Private operator: http://127.0.0.1:8765 . Sign in with your operator secret. Ctrl+C stops this service only.'
    while (-not $process.HasExited) {
        [string]$line = ''
        while ($job.TryRead([ref]$line)) { Write-Host $line }
        Start-Sleep -Milliseconds 150
    }
    if ($process.ExitCode -ne 0) { throw 'Operator service exited. Check OPERATOR.md and private configuration.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally { if ($job) { $job.Dispose() } }
