# Dedicated operator configuration. Values are only installed in the operator child process.
function Read-OperatorConfig([string]$RootDirectory) {
    $config = @{}
    $path = Join-Path $RootDirectory '.env.operator'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Create the private .env.operator file described in OPERATOR.md.' }
    foreach ($line in [IO.File]::ReadAllLines($path)) {
        $value = $line.Trim()
        if (-not $value -or $value.StartsWith('#')) { continue }
        if ($value -notmatch '^(OPERATOR_SECRET|INGESTION_DATABASE_URL)=(.+)$') { throw 'Unsupported operator configuration entry.' }
        $key = $Matches[1]
        if ($config.ContainsKey($key)) { throw 'Duplicate operator configuration entry.' }
        $config[$key] = $Matches[2].Trim().Trim('"').Trim("'")
    }
    if (-not $config.OPERATOR_SECRET -or $config.OPERATOR_SECRET.Length -lt 32) { throw 'OPERATOR_SECRET must contain at least 32 characters.' }
    $null = Get-LocalDatabase $config.INGESTION_DATABASE_URL 'INGESTION_DATABASE_URL'
    $student = Read-WorkflowConfig $RootDirectory
    $null = Get-LocalDatabase $student.DATABASE_URL 'DATABASE_URL'
    $operatorUrl = [Uri]$config.INGESTION_DATABASE_URL
    $studentUrl = [Uri]$student.DATABASE_URL
    if ([Uri]::UnescapeDataString($operatorUrl.UserInfo.Split(':')[0]) -ceq [Uri]::UnescapeDataString($studentUrl.UserInfo.Split(':')[0])) {
        throw 'Configure a distinct ingestion database role; the public API role must not own import/publication privileges.'
    }
    return $config
}
