@echo off
REM Double-click this to set up civ4-advisor.
REM
REM It just runs setup.ps1. The flags matter: Windows blocks PowerShell scripts
REM by default, and a repo downloaded as a ZIP is additionally marked as coming
REM from the internet. -ExecutionPolicy Bypass applies to THIS ONE RUN only and
REM changes nothing about your machine.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 pause
