@echo off
REM Duplo-clique para reiniciar o app de forma limpa (mata Streamlit duplicado
REM e sobe UMA so na porta 8501). Chama o reiniciar_app.ps1 com a politica de
REM execucao liberada so para esta execucao (nao mexe nas configs do Windows).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reiniciar_app.ps1"
echo.
echo (App parado. Pode fechar esta janela.)
pause
