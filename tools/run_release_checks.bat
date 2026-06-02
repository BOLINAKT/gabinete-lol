@echo off
setlocal
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -File ".\tools\run_release_checks.ps1" %*
endlocal

