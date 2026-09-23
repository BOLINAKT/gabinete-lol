@echo off
setlocal
cd /d "%~dp0"

set "PYEXE=python"
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"

rem Traz o que o robo publicou no GitHub ANTES de abrir (tools\sincronizar.py).
rem Nunca impede o app de abrir: qualquer problema vira so um aviso aqui.
"%PYEXE%" "tools\sincronizar.py"

"%PYEXE%" -m streamlit run "plays_app.py"

pause
