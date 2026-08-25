@echo off
REM Double-click this to check your setup when something is not working.
REM It changes nothing - it just reports what is and is not in place.
REM
REM See setup.bat for why the PowerShell flags are here.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Verify %*
echo.
pause
