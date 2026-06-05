# Empacota TUDO num UNICO zip pronto para enviar a outra maquina:
# codigo + modelo (artifacts) + dados (CSVs) + logos. Exclui o lixo que nao
# deve viajar (.git, .venv, __pycache__, backups, evidence, etc.) e segredos.
#
# Diferenca pro make_release.ps1: aquele leva SO modelo+dados (codigo vai pelo
# git). Este aqui e auto-suficiente: o amigo so descompacta, instala as deps e
# roda. Use quando for mandar "a pasta inteira".
#
#   .\tools\make_full_release.ps1
#
# Gera: release\gabinete_full_<timestamp>.zip
#
# Na outra maquina (Windows, Python 3.13):
#   1) descompacte o zip
#   2) python -m venv .venv ; .\.venv\Scripts\Activate.ps1
#   3) pip install -r requirements.txt
#   4) python tools/setup_check.py        (valida modelo/dados)
#   5) streamlit run plays_app.py
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$stage = Join-Path $env:TEMP ("gab_full_" + $ts)
$relDir = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path $relDir | Out-Null

# Pastas que NAO viajam (machine-specific, lixo, ou regeneravel).
$excludeDirs = @(
    ".git", ".venv", "venv", "env", "ENV", "__pycache__", ".ruff_cache",
    ".pytest_cache", ".mypy_cache", ".vscode", ".idea", "backups", "evidence",
    "tmp", "ops", "release", "dist", "build", ".eggs", "bootstrap_cache",
    "live_models", "node_modules"
)
# Arquivos que NAO viajam (compilados, logs, backups, segredos).
$excludeFiles = @(
    "*.pyc", "*.pyo", "*.pyd", "*.log", "*.bak", "*.swp", "*.swo",
    "*.before_fullfit_*", "*.monitoring.json", "desktop.ini", "Thumbs.db",
    ".DS_Store", "secrets.toml", ".env"
)

# robocopy /MIR copia a arvore inteira; /XD e /XF aplicam as exclusoes por nome.
# Codigos de saida 0..7 = sucesso (8+ = erro real).
$rcArgs = @($root, $stage, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
$rcArgs += "/XD"; $rcArgs += $excludeDirs
$rcArgs += "/XF"; $rcArgs += $excludeFiles
& robocopy @rcArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "ERRO: robocopy falhou (codigo $LASTEXITCODE)."
    exit 1
}

# Confere que o "cerebro" e os dados entraram (eles sao gitignored, entao sao a
# razao de ser deste bundle).
$brain = @("ml_artifact.json", "players_artifact.json", "params_fitted.json")
$missing = @()
foreach ($b in $brain) { if (-not (Test-Path (Join-Path $stage $b))) { $missing += $b } }
$nHist = 0; $nDiario = 0
if (Test-Path (Join-Path $stage "CSV_HISTORICO")) { $nHist = (Get-ChildItem (Join-Path $stage "CSV_HISTORICO") -Filter *.csv -File -ErrorAction SilentlyContinue).Count }
if (Test-Path (Join-Path $stage "CSV_DIARIO"))   { $nDiario = (Get-ChildItem (Join-Path $stage "CSV_DIARIO") -Filter *.csv -File -ErrorAction SilentlyContinue).Count }

$zip = Join-Path $relDir ("gabinete_full_" + $ts + ".zip")
if (Test-Path $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -LiteralPath $stage -Recurse -Force

$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "OK: bundle completo -> $zip ($sizeMB MB)"
Write-Host ("  modelo: {0}" -f $(if ($missing.Count -eq 0) { "ml/players/params OK" } else { "FALTANDO -> " + ($missing -join ", ") }))
Write-Host ("  dados:  CSV_HISTORICO={0} CSV  |  CSV_DIARIO={1} CSV" -f $nHist, $nDiario)
if ($missing.Count -gt 0) {
    Write-Host "  AVISO: rode 'python tools/atualizar_modelo.py' antes p/ gerar o modelo."
}
Write-Host ""
Write-Host "Na outra maquina: descompacte, depois:"
Write-Host "  python -m venv .venv ; .\.venv\Scripts\Activate.ps1"
Write-Host "  pip install -r requirements.txt"
Write-Host "  python tools/setup_check.py"
Write-Host "  streamlit run plays_app.py"

# robocopy deixa $LASTEXITCODE em 1..7 mesmo no sucesso; normalizamos para 0.
exit 0
