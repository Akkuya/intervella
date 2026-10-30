$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../student-auth-config.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('intervella-auth-config-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
function Expect-Rejected([scriptblock]$Action) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Unsafe auth configuration was accepted.' }
}
try {
    $file = Join-Path $testRoot '.env.student'
    Set-Content -LiteralPath $file @('STUDENT_AUTH_MODE=beta','STUDENT_AUTH_EPOCH="synthetic-$literal-not-expanded"')
    $config = Read-StudentAuthConfig $testRoot
    if ($config.STUDENT_AUTH_MODE -ne 'beta' -or $config.STUDENT_AUTH_EPOCH -ne 'synthetic-$literal-not-expanded') { throw 'Literal configuration parsing failed.' }
    Add-Content -LiteralPath $file 'STUDENT_AUTH_ADMIN_DATABASE_URL=forbidden'
    Expect-Rejected { Read-StudentAuthConfig $testRoot }
    Set-Content -LiteralPath $file @('STUDENT_AUTH_MODE=beta','STUDENT_AUTH_MODE=university')
    Expect-Rejected { Read-StudentAuthConfig $testRoot }
    Set-Content -LiteralPath $file 'OPERATOR_SECRET=forbidden'
    Expect-Rejected { Read-StudentAuthConfig $testRoot }
    $repository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    foreach ($name in @('check.ps1','scripts/dev-worker.ps1','scripts/operator-worker.ps1','scripts/student-auth-config.ps1')) {
        $tokens = $null; $errors = $null
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $repository $name), [ref]$tokens, [ref]$errors) | Out-Null
        if ($errors.Count) { throw 'Student auth workflow syntax failed.' }
    }
    Write-Host 'Student auth configuration and workflow regressions passed.'
} finally {
    $resolved = [IO.Path]::GetFullPath($testRoot)
    if ($resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolved -Leaf) -like 'intervella-auth-config-*') { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
