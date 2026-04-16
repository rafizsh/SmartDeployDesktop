# ============================================================================
# SmartDeploy WinPE Injection Script
# Run this as Administrator in PowerShell
# ============================================================================

Write-Host ""
Write-Host "=== SmartDeploy WinPE Injection ===" -ForegroundColor Cyan
Write-Host ""

$BootWim = "C:\RemoteInstall\sources\boot.wim"
$MountDir = "E:\SmartDeploy_WinPE_Mount"

# --- Step 0: Clean up any stale mounts ---
Write-Host "[0/6] Cleaning up stale mounts..." -ForegroundColor Yellow
dism /Cleanup-Mountpoints 2>$null | Out-Null
dism /Get-MountedWimInfo 2>$null | ForEach-Object {
    if ($_ -match "Mount Dir : (.+)") {
        $dir = $Matches[1].Trim()
        Write-Host "  Unmounting: $dir"
        dism /Unmount-Wim /MountDir:"$dir" /Discard 2>$null | Out-Null
    }
}
dism /Cleanup-Mountpoints 2>$null | Out-Null

if (Test-Path $MountDir) {
    Remove-Item $MountDir -Recurse -Force -ErrorAction SilentlyContinue
}

# --- Step 1: Verify boot.wim ---
Write-Host "[1/6] Verifying boot.wim..." -ForegroundColor Yellow
if (-not (Test-Path $BootWim)) {
    Write-Host "  ERROR: $BootWim not found!" -ForegroundColor Red
    exit 1
}
$wimSize = (Get-Item $BootWim).Length / 1MB
Write-Host "  Found: $BootWim ($([math]::Round($wimSize))MB)"

dism /Get-WimInfo /WimFile:"$BootWim" /Index:1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Invalid WIM file!" -ForegroundColor Red
    exit 1
}

# --- Step 2: Mount ---
Write-Host ""
Write-Host "[2/6] Mounting boot.wim..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $MountDir -Force | Out-Null

dism /Mount-Wim /WimFile:"$BootWim" /Index:1 /MountDir:"$MountDir"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Mount failed!" -ForegroundColor Red
    Remove-Item $MountDir -Force -ErrorAction SilentlyContinue
    exit 1
}

# Verify mount worked
$sys32 = Join-Path $MountDir "Windows\System32"
if (-not (Test-Path $sys32)) {
    Write-Host "  ERROR: Mount appears empty - System32 not found!" -ForegroundColor Red
    dism /Unmount-Wim /MountDir:"$MountDir" /Discard
    Remove-Item $MountDir -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "  Mounted successfully to $MountDir"

# --- Step 3: Create startnet.cmd ---
Write-Host ""
Write-Host "[3/6] Creating startnet.cmd..." -ForegroundColor Yellow

$startnetContent = @"
@echo off
wpeinit
echo.
echo ============================================
echo   SmartDeploy WinPE Agent v1.0
echo ============================================
echo.
echo Initializing network...
ping -n 5 127.0.0.1 >nul

set SERVER_IP=10.10.10.1
set API=http://%SERVER_IP%:8000/api

echo Waiting for server at %SERVER_IP%...
:wait_net
ping -n 1 %SERVER_IP% >nul 2>&1
if errorlevel 1 (
    echo   No response, retrying...
    ping -n 3 127.0.0.1 >nul
    goto :wait_net
)
echo   Server reachable!
echo.

REM Get IP address
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr "IPv4"') do (
    set IP=%%a
)
set IP=%IP: =%

REM Get MAC address
for /f "skip=3 tokens=1" %%a in ('getmac /fo table /nh 2^>nul') do (
    set MAC=%%a
    goto :got_mac
)
:got_mac

echo   IP:  %IP%
echo   MAC: %MAC%
echo.

REM Report to server
echo Registering with SmartDeploy server...
curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"hostname\":\"\",\"event\":\"winpe_start\",\"detail\":\"WinPE booted - ready for deployment\"}" >nul 2>&1

echo.
echo ============================================
echo   READY FOR DEPLOYMENT
echo.
echo   Type 'deploy' to start Windows install
echo   Type 'diskpart' to manage disks
echo   Type 'ipconfig' to check network
echo   Type 'exit' for command prompt
echo ============================================
echo.

:menu
set /p CMD="SmartDeploy> "
if /i "%CMD%"=="deploy" goto :do_deploy
if /i "%CMD%"=="diskpart" (diskpart & goto :menu)
if /i "%CMD%"=="ipconfig" (ipconfig & goto :menu)
if /i "%CMD%"=="ping" (ping %SERVER_IP% & goto :menu)
if /i "%CMD%"=="exit" goto :eof
if /i "%CMD%"=="help" (
    echo   deploy   - Partition disk and apply Windows image
    echo   diskpart - Disk management
    echo   ipconfig - Network info
    echo   ping     - Ping server
    echo   exit     - Command prompt
    goto :menu
)
echo Unknown command. Type 'help' for list.
goto :menu

:do_deploy
echo.
echo === STARTING DEPLOYMENT ===
echo.

REM Report step
curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_start\",\"detail\":\"Deployment started\"}" >nul 2>&1

REM Step 1: Partition
echo [1/4] Partitioning disk (GPT/UEFI)...
curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_step\",\"detail\":\"3: Partitioning disk\"}" >nul 2>&1

(
echo select disk 0
echo clean
echo convert gpt
echo create partition efi size=260
echo format fs=fat32 quick label="System"
echo assign letter=S
echo create partition msr size=16
echo create partition primary
echo format fs=ntfs quick label="Windows"
echo assign letter=W
echo exit
) | diskpart

if errorlevel 1 (
    echo   ERROR: Disk partitioning failed!
    curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_failed\",\"detail\":\"Disk partitioning failed\"}" >nul 2>&1
    goto :menu
)
echo   Done.
echo.

REM Step 2: Apply image
echo [2/4] Applying Windows image...
echo   Looking for install.wim...

set WIM_PATH=
if exist "\\%SERVER_IP%\SmartDeploy\Images\install.wim" (
    set WIM_PATH=\\%SERVER_IP%\SmartDeploy\Images\install.wim
    echo   Found: \\%SERVER_IP%\SmartDeploy\Images\install.wim
)
if "%WIM_PATH%"=="" if exist "\\%SERVER_IP%\Images\install.wim" (
    set WIM_PATH=\\%SERVER_IP%\Images\install.wim
    echo   Found: \\%SERVER_IP%\Images\install.wim
)

if "%WIM_PATH%"=="" (
    echo   No install.wim found on server share.
    echo   Enter the full path to install.wim:
    set /p WIM_PATH="Path: "
)

if "%WIM_PATH%"=="" (
    echo   ERROR: No WIM path specified!
    curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_failed\",\"detail\":\"No install.wim found\"}" >nul 2>&1
    goto :menu
)

curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_step\",\"detail\":\"7: Applying Windows image (this takes 10-20 min)\"}" >nul 2>&1

echo   Applying %WIM_PATH% to W:\
echo   This will take 10-20 minutes...
echo.
dism /Apply-Image /ImageFile:"%WIM_PATH%" /Index:1 /ApplyDir:W:\

if errorlevel 1 (
    echo.
    echo   ERROR: Image apply failed!
    curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_failed\",\"detail\":\"DISM apply image failed\"}" >nul 2>&1
    goto :menu
)
echo   Done.
echo.

REM Step 3: Boot files
echo [3/4] Configuring boot manager...
curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_step\",\"detail\":\"10: Configuring UEFI boot\"}" >nul 2>&1

bcdboot W:\Windows /s S: /f UEFI

if errorlevel 1 (
    echo   ERROR: Boot configuration failed!
    curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_failed\",\"detail\":\"Boot configuration failed\"}" >nul 2>&1
    goto :menu
)
echo   Done.
echo.

REM Step 4: Complete
echo [4/4] Deployment complete!
curl -s -X POST "%API%/pipeline/client-event" -H "Content-Type: application/json" -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_complete\",\"detail\":\"Windows deployed successfully\"}" >nul 2>&1

echo.
echo ============================================
echo   DEPLOYMENT COMPLETE
echo   Rebooting in 15 seconds...
echo   Press Ctrl+C to cancel
echo ============================================
ping -n 16 127.0.0.1 >nul
wpeutil reboot
"@

[System.IO.File]::WriteAllText("$sys32\startnet.cmd", $startnetContent, [System.Text.Encoding]::ASCII)

if (Test-Path "$sys32\startnet.cmd") {
    Write-Host "  Created startnet.cmd" -ForegroundColor Green
} else {
    Write-Host "  ERROR: Failed to create startnet.cmd!" -ForegroundColor Red
    dism /Unmount-Wim /MountDir:"$MountDir" /Discard
    exit 1
}

# --- Step 4: Copy curl.exe ---
Write-Host ""
Write-Host "[4/6] Copying curl.exe into WinPE..." -ForegroundColor Yellow

copy "C:\Windows\System32\curl.exe" "$sys32\curl.exe" | Out-Null
if (Test-Path "$sys32\curl.exe") {
    Write-Host "  Copied curl.exe" -ForegroundColor Green
} else {
    Write-Host "  WARNING: curl.exe copy failed - API reporting won't work" -ForegroundColor Yellow
}

# --- Step 5: Unmount and commit ---
Write-Host ""
Write-Host "[5/6] Committing changes and unmounting..." -ForegroundColor Yellow
Write-Host "  This may take a minute..."

dism /Unmount-Wim /MountDir:"$MountDir" /Commit
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Commit failed! Discarding..." -ForegroundColor Red
    dism /Unmount-Wim /MountDir:"$MountDir" /Discard
    exit 1
}

# --- Step 6: Cleanup ---
Write-Host ""
Write-Host "[6/6] Cleaning up..." -ForegroundColor Yellow
Remove-Item $MountDir -Force -Recurse -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "boot.wim now contains the SmartDeploy WinPE agent."
Write-Host "PXE boot a machine to test."
Write-Host ""
