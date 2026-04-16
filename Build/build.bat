@echo off
REM ============================================================================
REM SmartDeploy Desktop - Build Script
REM Builds the WPF application and bundles the Python server.
REM ============================================================================

echo.
echo ========================================
echo  SmartDeploy Desktop - Build
echo ========================================
echo.

set SOLUTION_DIR=%~dp0..
set WPF_DIR=%SOLUTION_DIR%\WPF
set SERVER_DIR=%SOLUTION_DIR%\Server
set OUTPUT_DIR=%SOLUTION_DIR%\Build\Output

REM --- Step 1: Build WPF ---
echo [1/4] Building WPF application...
dotnet publish "%WPF_DIR%\SmartDeployDesktop.csproj" -c Release -r win-x64 --self-contained false -o "%OUTPUT_DIR%"
if errorlevel 1 (
    echo ERROR: WPF build failed.
    exit /b 1
)

REM --- Step 2: Copy Server ---
echo [2/4] Copying Python server...
xcopy "%SERVER_DIR%" "%OUTPUT_DIR%\Server\" /E /Y /Q
if errorlevel 1 (
    echo ERROR: Server copy failed.
    exit /b 1
)

REM --- Step 3: Bundle Python (optional - if embeddable Python is present) ---
echo [3/4] Checking for bundled Python...
if exist "%SOLUTION_DIR%\Build\python-embed" (
    echo Copying embedded Python distribution...
    xcopy "%SOLUTION_DIR%\Build\python-embed" "%OUTPUT_DIR%\Server\python\" /E /Y /Q

    REM Install pip into embedded Python
    echo Installing pip and dependencies...
    "%OUTPUT_DIR%\Server\python\python.exe" -m ensurepip --default-pip 2>nul
    "%OUTPUT_DIR%\Server\python\python.exe" -m pip install -r "%SERVER_DIR%\requirements.txt" --quiet

    echo Bundled Python configured.
) else (
    echo No embedded Python found in Build\python-embed.
    echo The application will use system Python at runtime.
    echo.
    echo To bundle Python:
    echo   1. Download Python embeddable package from python.org
    echo   2. Extract to Build\python-embed\
    echo   3. Re-run this script
)

REM --- Step 4: Done ---
echo.
echo [4/4] Build complete!
echo.
echo Output: %OUTPUT_DIR%
echo.
echo Files:
dir "%OUTPUT_DIR%\SmartDeployDesktop.exe" /B 2>nul
echo Server\ (Python API backend)
echo.
echo To run: SmartDeployDesktop.exe
echo.
pause
