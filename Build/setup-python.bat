@echo off
REM ============================================================================
REM SmartDeploy Desktop - Setup Embedded Python
REM Downloads Python embeddable package and installs server dependencies.
REM Run this once before building to enable "no Python required" distribution.
REM ============================================================================

set PYTHON_VERSION=3.12.4
set PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip
set BUILD_DIR=%~dp0
set EMBED_DIR=%BUILD_DIR%python-embed
set TEMP_ZIP=%BUILD_DIR%python-embed.zip

echo.
echo ========================================
echo  SmartDeploy Desktop - Python Setup
echo ========================================
echo.

REM --- Download ---
echo [1/4] Downloading Python %PYTHON_VERSION% embeddable package...
if exist "%TEMP_ZIP%" del "%TEMP_ZIP%"
powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%TEMP_ZIP%'"
if errorlevel 1 (
    echo ERROR: Download failed. Check your internet connection.
    exit /b 1
)

REM --- Extract ---
echo [2/4] Extracting...
if exist "%EMBED_DIR%" rmdir /S /Q "%EMBED_DIR%"
powershell -Command "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%EMBED_DIR%' -Force"
del "%TEMP_ZIP%"

REM --- Enable pip ---
REM The embeddable distribution disables site-packages by default.
REM We need to uncomment the import site line in python312._pth
echo [3/4] Enabling pip and site-packages...
set PTH_FILE=%EMBED_DIR%\python312._pth
if exist "%PTH_FILE%" (
    powershell -Command "(Get-Content '%PTH_FILE%') -replace '#import site', 'import site' | Set-Content '%PTH_FILE%'"
)

REM Install pip
"%EMBED_DIR%\python.exe" -m ensurepip --default-pip 2>nul
if errorlevel 1 (
    echo Downloading get-pip.py...
    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%BUILD_DIR%get-pip.py'"
    "%EMBED_DIR%\python.exe" "%BUILD_DIR%get-pip.py"
    del "%BUILD_DIR%get-pip.py"
)

REM --- Install dependencies ---
echo [4/4] Installing server dependencies...
"%EMBED_DIR%\python.exe" -m pip install -r "%BUILD_DIR%..\Server\requirements.txt" --quiet

echo.
echo ========================================
echo  Setup complete!
echo ========================================
echo.
echo Embedded Python: %EMBED_DIR%
echo.
echo Now run build.bat to create the distributable package.
echo.
pause
