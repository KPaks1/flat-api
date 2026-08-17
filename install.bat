@echo off
setlocal enabledelayedexpansion

echo.
echo  Flat Plant API - Dev Setup
echo ====================================
echo.

:: ---- Python ----------------------------------------------------------------
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found.
    echo  Install Python 3.11+ from https://python.org ^(add to PATH^)
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Python : %%v

:: ---- Virtual environment ---------------------------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo  Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo  ERROR: Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo  Venv   : already exists
)

:: ---- Dependencies ----------------------------------------------------------
echo  Installing Python packages...
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo  ERROR: pip install failed. Check requirements.txt and your internet connection.
    exit /b 1
)
echo  Packages installed.

:: ---- VAPID keys ------------------------------------------------------------
echo  Setting up VAPID keys...
python setup_keys.py
if %errorlevel% neq 0 (
    echo  ERROR: VAPID key generation failed.
    exit /b 1
)

:: ---- Azurite (local Azure Storage emulator) --------------------------------
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  NOTE: Node.js not found - needed to run Azurite ^(local storage emulator^).
    echo  Install Node.js from https://nodejs.org then re-run install.bat.
) else (
    npx azurite --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo  Installing Azurite...
        npm install -g azurite --quiet
    ) else (
        echo  Azurite: already installed
    )
)

:: ---- Azure Functions Core Tools --------------------------------------------
func --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  NOTE: Azure Functions Core Tools not found.
    echo  Install with:  npm install -g azure-functions-core-tools@4
) else (
    for /f "tokens=*" %%v in ('func --version 2^>^&1') do echo  func   : v%%v
)

:: ---- Done ------------------------------------------------------------------
echo.
echo ====================================
echo  Setup complete!
echo ====================================
echo.
echo  To start developing:
echo.
echo  1. Open a new terminal and start the storage emulator:
echo       npx azurite --location ./azurite-data
echo.
echo  2. In this terminal, start the API:
echo       call .venv\Scripts\activate.bat
echo       func start
echo.
echo  3. Open in browser:
echo       Subscribe page : http://localhost:7071/api/subscribe
echo       Plants API     : http://localhost:7071/api/plants
echo.
echo  For Web Push testing ^(requires HTTPS^):
echo       ngrok http 7071
echo       Open the ngrok URL at /api/subscribe
echo.
