@echo off
REM Double-click this to remove civ4-advisor. See setup.bat for why the flags.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
if errorlevel 1 pause
