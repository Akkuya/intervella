function Read-WorkflowConfig([string]$RootDirectory) {
    $configuration = @{ DATABASE_URL = ''; TEST_DATABASE_URL = ''; POSTGRES_CONTAINER = 'utscvacant-pg-local' }
    $file = Join-Path $RootDirectory '.env.local'
    if (Test-Path -LiteralPath $file) {
        $seen = @{}
        $number = 0
        foreach ($line in Get-Content -LiteralPath $file) {
            $number++
            if ($line.Trim() -eq '' -or $line.TrimStart().StartsWith('#')) { continue }
            if ($line -notmatch '^\s*([A-Z_]+)\s*=(.*)$') { throw "Invalid .env.local line $number. Use literal KEY=value entries." }
            $key = $matches[1]
            $value = $matches[2].Trim()
            if (-not $configuration.ContainsKey($key) -or $seen.ContainsKey($key)) { throw "Unknown or duplicate .env.local key on line $number. See .env.example." }
            $seen[$key] = $true
            if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $configuration[$key] = $value
        }
    }
    foreach ($key in @($configuration.Keys)) {
        $value = [Environment]::GetEnvironmentVariable($key, 'Process')
        if (-not [string]::IsNullOrWhiteSpace($value)) { $configuration[$key] = $value }
    }
    if ($configuration.POSTGRES_CONTAINER -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]*$') { throw 'Invalid POSTGRES_CONTAINER name.' }
    return $configuration
}

function Get-LocalDatabase([string]$Value, [string]$Variable) {
    if ([string]::IsNullOrWhiteSpace($Value)) { throw "$Variable is missing. Copy .env.example to .env.local and select your EXISTING database, or set the process environment. No database is created automatically." }
    try {
        $uri = [Uri]$Value
        $database = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
        if ($uri.Scheme -notin @('postgresql', 'postgresql+psycopg') -or $uri.Host.Trim('[', ']') -notin @('localhost', '127.0.0.1', '::1') -or $uri.Query -or $uri.Fragment -or -not $uri.UserInfo -or $database -notmatch '^[a-zA-Z0-9_-]{1,63}$') { throw 'invalid' }
        $port = if ($uri.Port -eq -1) { 5432 } else { $uri.Port }
        return [pscustomobject]@{ Database = $database; Port = $port }
    } catch { throw "$Variable must be an explicit local PostgreSQL TCP URL, with a user and database, no query/fragment. Connection values are not printed." }
}

function Assert-SafeTestDatabase($Development, $Maintenance) {
    if ($Maintenance.Database -cne 'postgres' -or $Development.Database -ieq $Maintenance.Database -or $Development.Port -ne $Maintenance.Port) {
        throw 'Unsafe TEST_DATABASE_URL: use the same local server, maintenance database /postgres, distinct from DATABASE_URL. Tests may only create/drop their own random utscvacant_test_* databases.'
    }
}

function Get-WorkflowTools([string]$RootDirectory, [switch]$Database) {
    if ($env:OS -ne 'Windows_NT') { throw 'These launchers require Windows PowerShell 5.1+ or PowerShell 7 on Windows.' }
    $tools = @{}
    foreach ($name in @('uv', 'node', 'npm.cmd')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw "Missing $name. Install the prerequisites in README.md, then reopen PowerShell." }
        $tools[$name] = $command.Source
    }
    $version = [version](& $tools.node -p 'process.versions.node')
    if ($version -lt [version]'22.18.0') { throw 'Node.js 22.18 or newer is required.' }
    if (-not (Test-Path -LiteralPath (Join-Path $RootDirectory 'backend/.venv/Scripts/python.exe'))) { throw 'Backend dependencies missing. From backend run: uv sync --locked (Python 3.13+).' }
    if (-not (Test-Path -LiteralPath (Join-Path $RootDirectory 'frontend/node_modules/.bin/vite.cmd'))) { throw 'Frontend dependencies missing. From frontend run: npm.cmd ci.' }
    Push-Location (Join-Path $RootDirectory 'backend')
    try {
        & $tools.uv run --no-env-file --no-sync python -c 'import sys,fastapi,uvicorn,sqlmodel,psycopg; assert sys.version_info >= (3,13)' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Backend environment incomplete. Run uv sync --locked in backend.' }
    } finally { Pop-Location }
    if ($Database) {
        $command = Get-Command docker -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
        if ($command) { $tools.docker = $command.Source }
        elseif (Test-Path -LiteralPath $candidate) { $tools.docker = $candidate }
        else { throw 'Docker CLI missing. Install/start Docker Desktop; see README.md.' }
    }
    return $tools
}

function Ensure-LocalPostgres([string]$Docker, [string]$Container, $Database) {
    & $Docker info --format '{{.ServerVersion}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is not reachable. Start Docker Desktop first.' }
    $image = & $Docker inspect --format '{{.Config.Image}}' $Container
    if ($LASTEXITCODE -ne 0) { throw "Existing PostgreSQL container '$Container' not found. Startup never creates/replaces containers. See README.md." }
    if ($image -notmatch '(^|/)postgres:17($|-)') { throw 'The selected container must use the tested PostgreSQL 17 image.' }
    $bindings = (& $Docker inspect --format '{{json .HostConfig.PortBindings}}' $Container) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect PostgreSQL port bindings.' }
    $matching = @($bindings.'5432/tcp' | Where-Object { $_.HostIp -in @('127.0.0.1', '::1') -and [int]$_.HostPort -eq $Database.Port })
    if (-not $matching.Count) { throw 'Database URL port does not match a loopback binding on the selected container. Check .env.local.' }
    $running = & $Docker inspect --format '{{.State.Running}}' $Container
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect PostgreSQL state.' }
    if ($running -ne 'true') {
        Write-Host "Starting existing PostgreSQL container '$Container' (no reset or migration)."
        & $Docker start $Container | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not start the existing PostgreSQL container.' }
    }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & $Docker exec $Container pg_isready -q -h 127.0.0.1 -t 1
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw 'PostgreSQL did not become reachable within 30 seconds. Inspect Docker logs; no data was reset.'
}

function Assert-FreePort([int]$Port) {
    $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() }
    catch { throw "Port $Port is already in use. Stop the existing application yourself (Ctrl+C in its launcher) or close the conflicting service. No unrelated process was stopped." }
    finally { $listener.Stop() }
}

function Invoke-WorkflowCheck([string]$Group, [string]$Name, [string]$Command, [string[]]$Arguments, [string]$Directory, $Results) {
    Write-Host "`n[$Group] $Name"
    $status = 'FAIL'
    Push-Location $Directory
    try {
        & $Command @Arguments
        if ($LASTEXITCODE -eq 0) { $status = 'PASS' }
    } catch { Write-Host $_.Exception.Message -ForegroundColor Red }
    finally { Pop-Location }
    $Results.Add([pscustomobject]@{ Group = $Group; Name = $Name; Status = $status })
}
