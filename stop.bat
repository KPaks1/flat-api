@echo off
setlocal enabledelayedexpansion

echo.
echo  Flat Plant API - Stopping Servers
echo ====================================
echo.

:: --- Azure Functions (port 7071) ---
set FUNC_STOPPED=
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7071" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        taskkill /PID %%a /F /T >nul 2>&1
        set FUNC_STOPPED=1
    )
)
if defined FUNC_STOPPED (
    echo  Azure Functions stopped.
) else (
    echo  Azure Functions: not running.
)

:: --- Azurite (port 10000) ---
set AZURITE_STOPPED=
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":10000" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        taskkill /PID %%a /F /T >nul 2>&1
        set AZURITE_STOPPED=1
    )
)
if defined AZURITE_STOPPED (
    echo  Azurite stopped. ^(its window can be closed manually^)
) else (
    echo  Azurite: not running.
)

echo.
echo  Done.
echo.
