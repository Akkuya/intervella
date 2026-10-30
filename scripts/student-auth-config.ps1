function Read-StudentAuthConfig([string]$RootDirectory) {
    $allowed = @('STUDENT_AUTH_MODE','STUDENT_AUTH_ORIGIN','STUDENT_AUTH_EPOCH','STUDENT_AUTH_DATABASE_URL','STUDENT_BETA_PASSWORD_HASH','STUDENT_BETA_ENDS_AT','STUDENT_AUTH_TTL_SECONDS','STUDENT_SUPABASE_URL','STUDENT_SUPABASE_PUBLISHABLE_KEY','STUDENT_AUTH_ENCRYPTION_KEY','STUDENT_AUTH_EMAIL_DOMAINS','STUDENT_AUTH_ELIGIBILITY','STUDENT_SUPABASE_AUDIENCE')
    $values = @{}
    $file = Join-Path $RootDirectory '.env.student'
    if (Test-Path -LiteralPath $file) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if (-not $line.Trim() -or $line.TrimStart().StartsWith('#')) { continue }
            if ($line -notmatch '^\s*(STUDENT_[A-Z_]+)=(.*)$' -or $matches[1] -notin $allowed -or $values.ContainsKey($matches[1])) { throw 'Unsupported or duplicate student auth configuration entry.' }
            $key = $matches[1]; $value = $matches[2].Trim()
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) { $value = $value.Substring(1, $value.Length - 2) }
            $values[$key] = $value
        }
    }
    foreach ($key in $allowed) {
        $value = [Environment]::GetEnvironmentVariable($key, 'Process')
        if (-not [string]::IsNullOrWhiteSpace($value)) { $values[$key] = $value }
    }
    return $values
}
