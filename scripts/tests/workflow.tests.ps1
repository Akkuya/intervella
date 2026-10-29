$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../workflow.ps1')

$repository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
foreach ($file in @((Join-Path $repository 'dev.ps1'), (Join-Path $repository 'check.ps1'), (Join-Path $PSScriptRoot '../dev-worker.ps1'))) {
    $tokens = $null
    $parseErrors = $null
    [Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw "PowerShell syntax error in $file" }
}

function Assert-True($Condition, $Message) {
    if (-not $Condition) { throw $Message }
}
function Assert-Rejected([scriptblock]$Action) {
    $rejected = $false
    try { & $Action } catch { $rejected = $true }
    Assert-True $rejected 'Expected unsafe input to be rejected.'
}

Assert-Rejected { Get-LocalDatabase 'postgresql://postgres@remote.example/dev' 'DATABASE_URL' }
Assert-Rejected { Get-LocalDatabase 'postgresql://postgres@127.0.0.1/dev?host=remote' 'DATABASE_URL' }
Assert-Rejected { Get-LocalDatabase 'not-a-url' 'DATABASE_URL' }
$development = Get-LocalDatabase 'postgresql+psycopg://postgres@127.0.0.1:55433/utscvacant_dev' 'DATABASE_URL'
$maintenance = Get-LocalDatabase 'postgresql+psycopg://postgres@localhost:55433/postgres' 'TEST_DATABASE_URL'
Assert-SafeTestDatabase $development $maintenance
Assert-Rejected { Assert-SafeTestDatabase $development $development }
Assert-Rejected { Assert-SafeTestDatabase $maintenance $maintenance }
Assert-Rejected { Assert-SafeTestDatabase $development (Get-LocalDatabase 'postgresql://postgres@localhost:5432/postgres' 'TEST_DATABASE_URL') }

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('utscvacant workflow ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$savedDatabase = $env:DATABASE_URL
try {
    $env:DATABASE_URL = $null
    Set-Content -LiteralPath (Join-Path $temporary '.env.local') -Value @(
        '# Literal values only', 'DATABASE_URL="postgresql://postgres@localhost/demo"', 'POSTGRES_CONTAINER=synthetic-pg'
    )
    $configuration = Read-WorkflowConfig $temporary
    Assert-True ($configuration.DATABASE_URL -eq 'postgresql://postgres@localhost/demo') 'Literal configuration failed.'
    $env:DATABASE_URL = 'postgresql://postgres@localhost/override'
    Assert-True ((Read-WorkflowConfig $temporary).DATABASE_URL -eq $env:DATABASE_URL) 'Process environment must win.'
    Set-Content -LiteralPath (Join-Path $temporary '.env.local') -Value 'UNEXPECTED_KEY=ignored'
    Assert-Rejected { Read-WorkflowConfig $temporary }
    Set-Content -LiteralPath (Join-Path $temporary '.env.local') -Value 'DATABASE_URL=$(throw "must not execute")'
    $env:DATABASE_URL = $null
    Assert-True ((Read-WorkflowConfig $temporary).DATABASE_URL -eq '$(throw "must not execute")') 'Configuration was evaluated as code.'

    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { Assert-Rejected { Assert-FreePort $listener.LocalEndpoint.Port } } finally { $listener.Stop() }

    $results = New-Object 'System.Collections.Generic.List[object]'
    $shell = (Get-Process -Id $PID).Path
    Write-Host 'The following nonzero fixture is expected; testing failure aggregation.'
    Invoke-WorkflowCheck 'Harness' 'expected nonzero fixture' $shell @('-NoProfile', '-Command', 'Write-Output expected-command-output; exit 7') $temporary $results
    Invoke-WorkflowCheck 'Harness' 'independent success' $shell @('-NoProfile', '-Command', 'exit 0') $temporary $results
    Assert-True ($results.Count -eq 2 -and $results[0].Status -eq 'FAIL' -and $results[1].Status -eq 'PASS') 'Independent failures were not retained.'

    if (-not ('UtscVacant.DevProcesses' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot '../DevProcesses.cs') }
    $worker = Join-Path $temporary 'synthetic worker.ps1'
    $childPidFile = Join-Path $temporary 'child.pid'
    $argumentFile = Join-Path $temporary 'arguments.json'
    Set-Content -LiteralPath $worker -Value @'
Start-Sleep -Milliseconds 500
$gate = [Threading.EventWaitHandle]::OpenExisting($env:UTSCVACANT_START_GATE)
if (-not $gate.WaitOne(15000)) { exit 9 }
$gate.Dispose()
if ($args[1] -eq 'fail') { Write-Output 'synthetic-startup-failure'; exit 9 }
$args[1..($args.Length - 1)] | ConvertTo-Json | Set-Content -LiteralPath (Join-Path (Split-Path $args[0]) 'arguments.json')
$child = Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList '-NoProfile -Command Start-Sleep -Seconds 120' -PassThru -WindowStyle Hidden
Set-Content -LiteralPath $args[0] -Value $child.Id
Write-Output 'synthetic-ready'
Start-Sleep -Seconds 120
'@
    $job = New-Object UtscVacant.DevProcesses
    try {
        $arguments = [string[]]@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $worker, $childPidFile, 'space and slash\', 'a"b\')
        $process = $job.Start($shell, $arguments, $temporary, 'synthetic')
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while (-not (Test-Path -LiteralPath $childPidFile) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
        Assert-True (Test-Path -LiteralPath $childPidFile) 'Assigned worker did not start its child.'
        $childId = [int](Get-Content -LiteralPath $childPidFile)
        $actual = Get-Content -LiteralPath $argumentFile -Raw | ConvertFrom-Json
        Assert-True ($actual[0] -ceq 'space and slash\' -and $actual[1] -ceq 'a"b\') 'Windows argument escaping changed values.'
    } finally { $job.Dispose() }
    Start-Sleep -Milliseconds 300
    Assert-True (-not (Get-Process -Id $childId -ErrorAction SilentlyContinue)) 'Worker descendant survived cleanup.'
    Assert-True $process.HasExited 'Worker survived cleanup.'
    $job = New-Object UtscVacant.DevProcesses
    try {
        $failed = $job.Start($shell, [string[]]@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $worker, $childPidFile, 'fail'), $temporary, 'failure')
        Assert-True ($failed.WaitForExit(10000)) 'Failing worker did not exit.'
        $failed.WaitForExit()
        Assert-True ($failed.ExitCode -eq 9) 'Worker failure code was lost.'
        [string]$line = ''
        $lines = @()
        while ($job.TryRead([ref]$line)) { $lines += $line }
        Assert-True ($lines -contains '[failure] synthetic-startup-failure') 'Prefixed worker error output was lost.'
    } finally { $job.Dispose() }
} finally {
    $env:DATABASE_URL = $savedDatabase
    # Only these synthetic files belong to this test; no recursive cleanup.
    foreach ($name in @('.env.local', 'synthetic worker.ps1', 'child.pid', 'arguments.json')) {
        $file = Join-Path $temporary $name
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    }
    Remove-Item -LiteralPath $temporary
}
Write-Host 'Workflow regression checks: PASS'
