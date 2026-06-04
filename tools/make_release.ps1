# Empacota o MODELO + DADOS (arquivos que NÃO vão no git) num zip para enviar a
# outra máquina. O código vai pelo git; este zip leva o "cérebro" + os CSVs.
# O destinatário descompacta na RAIZ do repositório (sobrescrevendo).
#
#   .\tools\make_release.ps1
#
# Gera: release\gabinete_data_<timestamp>.zip
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$stage = Join-Path $env:TEMP ("gab_release_" + $ts)
$relDir = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path $relDir | Out-Null

$included = New-Object System.Collections.Generic.List[string]

# Arquivos de runtime (modelo/calibração/params) na raiz.
foreach ($f in @("ml_artifact.json", "players_artifact.json", "params_fitted.json", "achievements.json", "team_state_artifact.json")) {
    $src = Join-Path $root $f
    if (Test-Path $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $stage $f) -Force
        $included.Add($f)
    }
}

# Pastas de CSV (dados).
foreach ($d in @("CSV_HISTORICO", "CSV_DIARIO")) {
    $srcDir = Join-Path $root $d
    if (Test-Path $srcDir) {
        $csvs = Get-ChildItem -Path $srcDir -Filter *.csv -File -ErrorAction SilentlyContinue
        if ($csvs) {
            $dstDir = Join-Path $stage $d
            New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
            foreach ($c in $csvs) { Copy-Item -LiteralPath $c.FullName -Destination (Join-Path $dstDir $c.Name) -Force }
            $included.Add(("{0}\ ({1} CSV)" -f $d, $csvs.Count))
        }
    }
}

if ($included.Count -eq 0) {
    Write-Host "Nada para empacotar (modelo/CSVs ausentes). Rode tools/atualizar_modelo.py primeiro."
    exit 1
}

$zip = Join-Path $relDir ("gabinete_data_" + $ts + ".zip")
if (Test-Path $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -LiteralPath $stage -Recurse -Force

$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "OK: bundle criado -> $zip ($sizeMB MB)"
Write-Host "Conteudo:"
foreach ($i in $included) { Write-Host "  - $i" }
Write-Host ""
Write-Host "ENVIE este zip junto do codigo. Na outra maquina, descompacte na RAIZ do repo"
Write-Host "(de forma que ml_artifact.json fique na raiz e os CSVs em CSV_HISTORICO/ e CSV_DIARIO/),"
Write-Host "depois rode:  python tools/setup_check.py"
