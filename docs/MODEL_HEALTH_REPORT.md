# Relatorio de Saude do Modelo

Gera um JSON unico com:
- Walk-forward mensal (logloss, brier, roi_proxy e drift por liga)
- Diagnostico de calibracao (team_only, players_only, fused_active), inclusive bins de confiabilidade

## Comando

```powershell
python tools/model_health_report.py `
  --csv C:\caminho\arquivo1.csv `
  --csv C:\caminho\arquivo2.csv `
  --artifact C:\Users\steam\Desktop\gabinetelolweb3.1\ml_artifact.json `
  --players-artifact C:\Users\steam\Desktop\gabinetelolweb3.1\players_artifact.json `
  --out C:\Users\steam\Desktop\gabinetelolweb3.1\model_health_report.json
```

## Leitura rapida

- `walkforward.overall.logloss_mean`:
  menor = melhor.
- `walkforward.by_league[*].drift_mean`:
  acima de zero de forma persistente = liga degradando.
- `calibration.models.fused_active.ece`:
  menor = melhor calibracao.
- `calibration.by_league[*].fused_active`:
  compara calibracao por liga.

## Uso recomendado

1. Rodar semanalmente.
2. Comparar com relatorio anterior.
3. Se drift subir ou ECE piorar, rodar retreino/walk-forward e revalidar.

