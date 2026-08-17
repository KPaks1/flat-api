@echo off
setlocal enabledelayedexpansion

echo.
echo  Flat Plant API - Starting Dev Server
echo ====================================
echo.

:: ---- Pre-flight checks -----------------------------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo  ERROR: Virtual environment not found.
    echo  Run install.bat first.
    exit /b 1
)

if not exist "local.settings.json" (
    echo  ERROR: local.settings.json not found.
    echo  Run install.bat first.
    exit /b 1
)

:: Check VAPID keys are real (not placeholder)
python -c "import json,sys; s=json.load(open('local.settings.json')); k=s['Values'].get('VAPID_PUBLIC_KEY',''); sys.exit(0 if k and not k.startswith('<') else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: VAPID keys are not configured in local.settings.json.
    echo  Run install.bat to generate them.
    exit /b 1
)

:: ---- Start Azurite in a separate window ------------------------------------
echo  Starting Azurite (storage emulator)...
if not exist "azurite-data" mkdir azurite-data
start "Azurite - Storage Emulator" cmd /k "npx azurite --location ./azurite-data && pause"

:: Give Azurite a moment to initialise before func connects
timeout /t 2 /nobreak >nul

:: ---- Activate venv and start Functions -------------------------------------
echo  Starting Azure Functions...
echo.
call .venv\Scripts\activate.bat
func start
