# Reinicia o app de forma LIMPA: mata qualquer Streamlit rodando (evita o bug de
# 2 instancias em portas diferentes que confunde qual codigo esta no ar) e sobe
# UMA so, na porta 8501, num console visivel (Ctrl+C volta a parar de verdade).
#
#   .\reiniciar_app.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "Parando instancias do Streamlit..."
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'streamlit run' }
foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
}
Start-Sleep -Seconds 2

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "Subindo UMA instancia em http://localhost:8501 ..."
Write-Host "(Deixe ESTE console aberto. Para parar o app: Ctrl+C aqui.)"
& $py -m streamlit run "plays_app.py" --server.port 8501
