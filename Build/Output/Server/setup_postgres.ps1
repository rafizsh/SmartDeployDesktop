param(
    [string]$PostgresPassword = "postgres",
    [string]$DbName = "smartdeploy",
    [string]$DbUser = "smartdeploy",
    [string]$DbPassword = "SmartDeploy2026!",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

Write-Host ""
Write-Host "=== SmartDeploy PostgreSQL Setup ===" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Check if PostgreSQL is installed ──
Write-Host "[1/6] Checking PostgreSQL installation..." -ForegroundColor Yellow

$pgDir = "C:\Program Files\PostgreSQL"
$pgInstalled = $false
$pgVersion = ""
$pgBin = ""

# Find installed version
if (Test-Path $pgDir) {
    $versions = Get-ChildItem $pgDir -Directory | Sort-Object Name -Descending
    if ($versions.Count -gt 0) {
        $pgVersion = $versions[0].Name
        $pgBin = Join-Path $versions[0].FullName "bin"
        if (Test-Path (Join-Path $pgBin "psql.exe")) {
            $pgInstalled = $true
        }
    }
}

# Also check PATH
if (-not $pgInstalled) {
    try {
        $psqlPath = (Get-Command psql -ErrorAction SilentlyContinue).Source
        if ($psqlPath) {
            $pgInstalled = $true
            $pgBin = Split-Path $psqlPath
            $pgVersion = "PATH"
        }
    } catch {}
}

if ($pgInstalled) {
    Write-Host "  PostgreSQL found: $pgBin" -ForegroundColor Green
    Write-Host "  Version: $pgVersion"
} else {
    if ($SkipInstall) {
        Write-Host "  PostgreSQL NOT installed. -SkipInstall specified." -ForegroundColor Red
        Write-Host "  Install from: https://www.postgresql.org/download/windows/"
        exit 1
    }

    Write-Host "  PostgreSQL NOT installed. Installing..." -ForegroundColor Yellow
    
    # Download installer
    $installerUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.8-1-windows-x64.exe"
    $installerPath = Join-Path $env:TEMP "postgresql-installer.exe"
    
    Write-Host "  Downloading PostgreSQL 16..."
    Write-Host "  URL: $installerUrl"
    
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Write-Host "  Downloaded to $installerPath" -ForegroundColor Green
    } catch {
        Write-Host "  Download failed: $_" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Please download and install PostgreSQL manually:" -ForegroundColor Yellow
        Write-Host "    https://www.postgresql.org/download/windows/"
        Write-Host "  Then run this script again with -SkipInstall"
        exit 1
    }

    # Silent install
    Write-Host "  Installing PostgreSQL (silent mode)..."
    Write-Host "  This may take a few minutes..."

    # Build a single, quoted argument string so paths with spaces are preserved
    $installArgs = "--mode unattended --unattendedmodeui none --superpassword `"$PostgresPassword`" --serverport 5432 --datadir `"C:\Program Files\PostgreSQL\16\data`" --install_runtimes 0"

    $proc = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru
    
    if ($proc.ExitCode -eq 0) {
        Write-Host "  PostgreSQL installed successfully!" -ForegroundColor Green
        $pgBin = "C:\Program Files\PostgreSQL\16\bin"
        $pgVersion = "16"
    } else {
        Write-Host "  Installation failed (exit code: $($proc.ExitCode))" -ForegroundColor Red
        Write-Host "  Install manually from: https://www.postgresql.org/download/windows/"
        exit 1
    }
    
    # Cleanup installer
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
}

$psql = Join-Path $pgBin "psql.exe"
$env:PGPASSWORD = $PostgresPassword

# ── Step 2: Check service ──
Write-Host ""
Write-Host "[2/6] Checking PostgreSQL service..." -ForegroundColor Yellow

$svcName = Get-Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1 -ExpandProperty Name

if ($svcName) {
    $svc = Get-Service $svcName
    if ($svc.Status -eq "Running") {
        Write-Host "  Service '$svcName' is RUNNING" -ForegroundColor Green
    } else {
        Write-Host "  Starting service '$svcName'..."
        Start-Service $svcName
        Start-Sleep -Seconds 3
        $svc = Get-Service $svcName
        if ($svc.Status -eq "Running") {
            Write-Host "  Service started" -ForegroundColor Green
        } else {
            Write-Host "  Failed to start service" -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host "  No PostgreSQL service found!" -ForegroundColor Red
    Write-Host "  The installation may need a reboot."
    exit 1
}

# ── Step 3: Create user ──
Write-Host ""
Write-Host "[3/6] Creating database user '$DbUser'..." -ForegroundColor Yellow

$createUserSql = "DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DbUser') THEN CREATE ROLE $DbUser WITH LOGIN PASSWORD '$DbPassword' CREATEDB; END IF; END `$`$;"

$result = & "$psql" -U postgres -h localhost -p 5432 -c $createUserSql 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  User '$DbUser' ready" -ForegroundColor Green
} else {
    Write-Host "  Note: $result" -ForegroundColor Yellow
}

# ── Step 4: Create database ──
Write-Host ""
Write-Host "[4/6] Creating database '$DbName'..." -ForegroundColor Yellow

$checkDb = & "$psql" -U postgres -h localhost -p 5432 -tc "SELECT 1 FROM pg_database WHERE datname = '$DbName'" 2>&1
if ($checkDb -match "1") {
    Write-Host "  Database '$DbName' already exists" -ForegroundColor Green
} else {
    & "$psql" -U postgres -h localhost -p 5432 -c "CREATE DATABASE $DbName OWNER $DbUser" 2>&1 | Out-Null
    Write-Host "  Database '$DbName' created" -ForegroundColor Green
}

# Grant privileges
& "$psql" -U postgres -h localhost -p 5432 -c "GRANT ALL PRIVILEGES ON DATABASE $DbName TO $DbUser" 2>&1 | Out-Null
& "$psql" -U postgres -h localhost -p 5432 -d $DbName -c "GRANT ALL ON SCHEMA public TO $DbUser" 2>&1 | Out-Null

# ── Step 5: Schema (applied by API server after this script) ──
Write-Host ""
Write-Host "[5/6] Database schema..." -ForegroundColor Yellow
$schemaFile = Join-Path $PSScriptRoot "schema.sql"
$env:PGPASSWORD = $DbPassword
if (Test-Path $schemaFile) {
    & "$psql" -U $DbUser -h localhost -p 5432 -d $DbName -v ON_ERROR_STOP=1 -f $schemaFile 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  schema.sql failed (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Schema applied from schema.sql" -ForegroundColor Green
} else {
    # No schema.sql: the FastAPI /api/db/setup handler runs init_schema via asyncpg after this script.
    Write-Host "  (Schema will be applied automatically by the SmartDeploy server.)" -ForegroundColor Green
}

# ── Step 6: Save config ──
Write-Host ""
Write-Host "[6/6] Saving configuration..." -ForegroundColor Yellow

$configDir = Join-Path $env:LOCALAPPDATA "SmartDeployDesktop"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null

$dbConfig = @{
    host = "localhost"
    port = 5432
    database = $DbName
    user = $DbUser
    password = $DbPassword
} | ConvertTo-Json

[System.IO.File]::WriteAllText(
    (Join-Path $configDir "db_config.json"),
    $dbConfig,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "  Config saved to: $(Join-Path $configDir 'db_config.json')" -ForegroundColor Green

# ── Done ──
Write-Host ""
Write-Host "=== PostgreSQL Setup Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Host:     localhost:5432"
Write-Host "  Database: $DbName"
Write-Host "  User:     $DbUser"
Write-Host "  Password: $DbPassword"
Write-Host ""
Write-Host "  Connection string:"
Write-Host "    postgresql://${DbUser}:${DbPassword}@localhost:5432/$DbName" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Test connection:" 
Write-Host "    `"$psql`" -U $DbUser -h localhost -d $DbName -c 'SELECT version();'" 
Write-Host ""

# Install Python asyncpg driver
Write-Host "Installing Python PostgreSQL driver..."
$pythonExe = "python3.13"
try { & $pythonExe --version 2>$null } catch { $pythonExe = "python" }
& $pythonExe -m pip install asyncpg --quiet 2>&1 | Out-Null
Write-Host "  asyncpg installed" -ForegroundColor Green
Write-Host ""
