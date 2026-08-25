@echo off
REM Sets up the advisor for one game. Double-click it: it lists the games it
REM can see and lets you pick one, then creates a folder for it.
REM
REM To choose the location yourself, run it from a command prompt:
REM   new_game.bat -Destination %USERPROFILE%\Desktop\my-game
REM
REM See setup.bat for why the PowerShell flags are here.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0new_game.ps1" %*
REM Always pause: this prints the folder it made and the prompt to paste into
REM Claude Code, and double-clicking would close the window before either is read.
echo.
pause
