@echo off

call stop.bat

echo  Waiting for ports to release...
timeout /t 3 /nobreak >nul

call start.bat
