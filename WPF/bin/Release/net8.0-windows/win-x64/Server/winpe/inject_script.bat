@echo off
REM ============================================================================
REM Inject SmartDeploy startup script into WinPE boot.wim
REM Run this as Administrator
REM ============================================================================

set BOOT_WIM=C:\RemoteInstall\sources\boot.wim
set MOUNT_DIR=C:\SmartDeploy\Mount\winpe_inject
set SCRIPT_DIR=%~dp0

echo.
echo === SmartDeploy WinPE Script Injector ===
echo.
echo Boot WIM: %BOOT_WIM%
echo Mount to: %MOUNT_DIR%
echo.

REM Create mount directory
mkdir "%MOUNT_DIR%" 2>nul

REM Step 1: Mount
echo [1/4] Mounting boot.wim...
dism /Mount-Wim /WimFile:"%BOOT_WIM%" /Index:1 /MountDir:"%MOUNT_DIR%"
if errorlevel 1 (
    echo FAILED to mount. Is the WIM in use or read-only?
    pause
    exit /b 1
)

REM Step 2: Copy startup script
echo [2/4] Injecting startup script...
copy /Y "%SCRIPT_DIR%startnet.cmd" "%MOUNT_DIR%\Windows\System32\startnet.cmd"
echo   Copied startnet.cmd

REM Also add curl.exe if not present (needed for API calls)
if not exist "%MOUNT_DIR%\Windows\System32\curl.exe" (
    echo   Adding curl.exe...
    copy /Y "C:\Windows\System32\curl.exe" "%MOUNT_DIR%\Windows\System32\curl.exe" 2>nul
)

REM Step 3: Unmount and commit
echo [3/4] Saving changes...
dism /Unmount-Wim /MountDir:"%MOUNT_DIR%" /Commit
if errorlevel 1 (
    echo FAILED to commit. Discarding changes...
    dism /Unmount-Wim /MountDir:"%MOUNT_DIR%" /Discard
    pause
    exit /b 1
)

REM Step 4: Cleanup
echo [4/4] Cleaning up...
rmdir "%MOUNT_DIR%" 2>nul

echo.
echo === Done! ===
echo The boot.wim now contains the SmartDeploy startup script.
echo PXE boot a machine to test.
echo.
pause
