$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../workflow.ps1')
. (Join-Path $PSScriptRoot '../operator-config.ps1')
$repository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
foreach ($file in @('operator.ps1','scripts/operator-config.ps1','scripts/operator-worker.ps1')) {
    $tokens = $null; $syntaxErrors = $null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $repository $file), [ref]$tokens, [ref]$syntaxErrors) | Out-Null
    if ($syntaxErrors.Count) { throw 'Operator PowerShell syntax failed.' }
}
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('utscvacant-operator-config-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$previousDatabase = $env:DATABASE_URL
$previousSecret = $env:OPERATOR_SECRET
function Expect-Rejected([scriptblock]$Action) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Expected unsafe operator configuration to be rejected.' }
}
try {
    $env:DATABASE_URL = $null
    $env:OPERATOR_SECRET = 'synthetic-parent-secret'
    Set-Content -LiteralPath (Join-Path $testRoot '.env.local') 'DATABASE_URL=postgresql://reader@127.0.0.1:5432/campus'
    $file = Join-Path $testRoot '.env.operator'
    Expect-Rejected { Read-OperatorConfig $testRoot }
    Set-Content -LiteralPath $file @('OPERATOR_SECRET=short','INGESTION_DATABASE_URL=postgresql://writer@127.0.0.1:5432/campus')
    Expect-Rejected { Read-OperatorConfig $testRoot }
    Set-Content -LiteralPath $file @('OPERATOR_SECRET=synthetic-long-operator-secret-123456789','INGESTION_DATABASE_URL=postgresql://reader@127.0.0.1:5432/campus')
    Expect-Rejected { Read-OperatorConfig $testRoot }
    Set-Content -LiteralPath $file @('OPERATOR_SECRET=synthetic-long-operator-secret-123456789','INGESTION_DATABASE_URL=postgresql://writer@127.0.0.1:5432/campus')
    $result = Read-OperatorConfig $testRoot
    if ($result.OPERATOR_SECRET.Length -lt 32 -or $env:OPERATOR_SECRET -ne 'synthetic-parent-secret') { throw 'Operator environment isolation failed.' }
    Add-Content -LiteralPath $file 'UNEXPECTED=bad'
    Expect-Rejected { Read-OperatorConfig $testRoot }
    Write-Host 'Operator configuration and syntax regressions passed.'
} finally {
    $env:DATABASE_URL = $previousDatabase
    $env:OPERATOR_SECRET = $previousSecret
    $resolved = [IO.Path]::GetFullPath($testRoot)
    if ($resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolved -Leaf) -like 'utscvacant-operator-config-*') { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
