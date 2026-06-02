# Validacao Unica de Entrega

Use um comando para rodar:
- suite completa de testes
- check de trace combinado
- relatorio de saude do modelo (walk-forward + calibracao)

## Comando (Windows)

```powershell
tools\run_release_checks.bat
```

Ou:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_release_checks.ps1
```

## Saida

Cria uma pasta em:

`evidence\release_check_YYYYMMDD_HHMMSS`

Com:
- `summary.txt`
- `tests.log`
- `trace_check.log`
- `health.log`
- `model_health_report.json` (quando houver csv+artifacts disponiveis)

