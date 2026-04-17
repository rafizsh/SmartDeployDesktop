@echo off
REM ============================================================================
REM SmartDeploy WinPE Startup Script
REM This script runs automatically when WinPE boots via PXE.
REM It registers with the SmartDeploy server, maps the deployment share,
REM and starts the imaging process.
REM ============================================================================

setlocal enabledelayedexpansion

REM --- Configuration (set by DHCP/BCD or manually) ---
set SERVER_IP=10.10.10.1
set SERVER_PORT=8000
set API_URL=http://%SERVER_IP%:%SERVER_PORT%/api

REM --- Gather system info ---
echo.
echo ============================================
echo   SmartDeploy WinPE Agent
echo ============================================
echo.

REM Get MAC address
for /f "tokens=2 delims=:" %%a in ('getmac /fo csv /nh ^| findstr /r "."') do (
    set MAC=%%~a
    goto :got_mac
)
:got_mac

REM Get IP address
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr "IPv4"') do (
    set IP=%%~a
    set IP=!IP: =!
    goto :got_ip
)
:got_ip

echo  Server:  %SERVER_IP%
echo  My IP:   %IP%
echo  My MAC:  %MAC%
echo.

REM --- Wait for network ---
echo Waiting for network...
:wait_network
ping -n 1 %SERVER_IP% >nul 2>&1
if errorlevel 1 (
    echo   No response from server, retrying in 3 seconds...
    ping -n 4 127.0.0.1 >nul
    goto :wait_network
)
echo   Server reachable!
echo.

REM --- Register with server ---
echo Registering with SmartDeploy server...
curl -s -X POST "%API_URL%/pipeline/client-event" ^
    -H "Content-Type: application/json" ^
    -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"hostname\":\"\",\"event\":\"winpe_start\",\"detail\":\"WinPE booted successfully\"}"
echo.

REM --- Map deployment share ---
echo Mapping deployment share...
net use Z: \\%SERVER_IP%\SmartDeploy /user:HIROFUMI\Administrator * 2>nul
if errorlevel 1 (
    echo   Could not map share. Trying without credentials...
    net use Z: \\%SERVER_IP%\SmartDeploy 2>nul
)

REM --- Check for install.wim ---
echo.
echo Checking for Windows image...
if exist "Z:\Images\install.wim" (
    echo   Found: Z:\Images\install.wim
) else if exist "C:\SmartDeploy\Images\install.wim" (
    echo   Found: C:\SmartDeploy\Images\install.wim
) else (
    echo   WARNING: No install.wim found
    echo   Place install.wim in C:\SmartDeploy\Images\ on the server
)

REM --- Report ready ---
curl -s -X POST "%API_URL%/pipeline/client-event" ^
    -H "Content-Type: application/json" ^
    -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"hostname\":\"\",\"event\":\"pipeline_step\",\"detail\":\"2: WinPE ready - awaiting deployment task\"}"

echo.
echo ============================================
echo   WinPE Agent Ready
echo   Server: %API_URL%
echo   Waiting for deployment task...
echo ============================================
echo.
echo Type 'deploy' to start manual deployment
echo Type 'exit' to drop to command prompt
echo.

REM --- Interactive menu ---
:menu
set /p CHOICE="SmartDeploy> "
if /i "%CHOICE%"=="deploy" goto :deploy
if /i "%CHOICE%"=="exit" goto :end
if /i "%CHOICE%"=="diskpart" diskpart & goto :menu
if /i "%CHOICE%"=="ipconfig" ipconfig & goto :menu
if /i "%CHOICE%"=="help" (
    echo Commands: deploy, diskpart, ipconfig, exit, help
    goto :menu
)
goto :menu

:deploy
echo.
echo Starting deployment...

REM Step 1: Partition disk
curl -s -X POST "%API_URL%/pipeline/client-event" ^
    -H "Content-Type: application/json" ^
    -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_step\",\"detail\":\"3: Partitioning disk\"}"

echo Creating UEFI partitions...
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

REM Step 2: Apply image
curl -s -X POST "%API_URL%/pipeline/client-event" ^
    -H "Content-Type: application/json" ^
    -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_step\",\"detail\":\"7: Applying Windows image\"}"

set WIM_PATH=
if exist "Z:\Images\install.wim" set WIM_PATH=Z:\Images\install.wim
if exist "C:\SmartDeploy\Images\install.wim" set WIM_PATH=C:\SmartDeploy\Images\install.wim

if "%WIM_PATH%"=="" (
    echo ERROR: No install.wim found!
    curl -s -X POST "%API_URL%/pipeline/client-event" ^
        -H "Content-Type: application/json" ^
        -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_failed\",\"detail\":\"No install.wim found\"}"
    goto :menu
)

echo Applying %WIM_PATH% to W:\ (this will take 10-20 minutes)...
dism /Apply-Image /ImageFile:"%WIM_PATH%" /Index:1 /ApplyDir:W:\

if errorlevel 1 (
    echo DISM apply failed!
    curl -s -X POST "%API_URL%/pipeline/client-event" ^
        -H "Content-Type: application/json" ^
        -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_failed\",\"detail\":\"DISM apply image failed\"}"
    goto :menu
)

REM Step 3: Configure boot
curl -s -X POST "%API_URL%/pipeline/client-event" ^
    -H "Content-Type: application/json" ^
    -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_step\",\"detail\":\"10: Configuring boot manager\"}"

echo Configuring boot files...
bcdboot W:\Windows /s S: /f UEFI

REM Step 4: Complete
curl -s -X POST "%API_URL%/pipeline/client-event" ^
    -H "Content-Type: application/json" ^
    -d "{\"mac\":\"%MAC%\",\"ip\":\"%IP%\",\"event\":\"pipeline_complete\",\"detail\":\"Deployment complete - rebooting\"}"

echo.
echo ============================================
echo   Deployment Complete!
echo   Rebooting in 10 seconds...
echo ============================================
echo Press Ctrl+C to cancel reboot
ping -n 11 127.0.0.1 >nul
wpeutil reboot

:end
echo Dropping to command prompt...
cmd /k
