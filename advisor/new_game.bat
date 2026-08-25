@echo off
REM Sets up the advisor for one game. Double-click it: it lists the games it
REM can see and lets you pick one, then creates a folder on your Desktop.
REM
REM To choose the location yourself, run it from a command prompt:
REM   new_game.bat -Destination %USERPROFILE%\Desktop\my-game
REM
REM See setup.bat for why the PowerShell flags are here.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0new_game.ps1" %*
if errorlevel 1 pause
