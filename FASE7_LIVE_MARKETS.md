# Fase 7: Modelos calibrados de mercados live

**Data:** 2026-05-29
**Versão:** phase7_markets_v1
**Status:** ✅ **16/20 gates ACCEPT** (4 mercados ativos × 4 snapshots cada)

---

## Resumo

Substituí as heurísticas de mercados live (Over/Under kills, towers, drakes, tempo)
por modelos LightGBM treinados em snapshots históricos. Para cada par
(mercado × minuto) treinei um regressor que prediz o total final dado o estado
do jogo, e a probabilidade de over/under é calculada via CDF normal sobre o
desvio do resíduo histórico.

## Resultados — todos os 20 modelos testados

| Mercado | Min | n_test | RMSE base | RMSE live | Δ RMSE | p-value | Gate |
|---|---|---|---|---|---|---|---|
| total_kills | 10 | 2.688 | 10.086 | 8.613 | **+1.474** | 0.0000 | ✅ ACCEPT |
| total_kills | 15 | 2.688 | 10.086 | 7.807 | **+2.280** | 0.0000 | ✅ ACCEPT |
| total_kills | 20 | 2.684 | 10.092 | 6.818 | **+3.274** | 0.0000 | ✅ ACCEPT |
| total_kills | 25 | 2.501 | 10.165 | 5.753 | **+4.412** | 0.0000 | ✅ ACCEPT |
| total_towers | 10 | 2.688 | 2.223 | 2.165 | +0.057 | 0.0000 | ✅ ACCEPT |
| total_towers | 15 | 2.688 | 2.223 | 2.127 | +0.095 | 0.0000 | ✅ ACCEPT |
| total_towers | 20 | 2.684 | 2.222 | 2.070 | +0.152 | 0.0000 | ✅ ACCEPT |
| total_towers | 25 | 2.501 | 2.210 | 2.040 | +0.171 | 0.0000 | ✅ ACCEPT |
| total_dragons | 10 | 2.684 | 1.080 | 1.008 | +0.072 | 0.0000 | ✅ ACCEPT |
| total_dragons | 15 | 2.684 | 1.080 | 0.964 | +0.116 | 0.0000 | ✅ ACCEPT |
| total_dragons | 20 | 2.680 | 1.075 | 0.909 | +0.167 | 0.0000 | ✅ ACCEPT |
| total_dragons | 25 | 2.498 | 1.012 | 0.839 | +0.173 | 0.0000 | ✅ ACCEPT |
| total_barons | 10 | 2.563 | 0.619 | 0.612 | +0.006 | 0.0000 | ❌ REJECT |
| total_barons | 15 | 2.563 | 0.619 | 0.608 | +0.011 | 0.0000 | ❌ REJECT |
| total_barons | 20 | 2.563 | 0.619 | 0.598 | +0.021 | 0.0000 | ❌ REJECT |
| total_barons | 25 | 2.410 | 0.630 | 0.607 | +0.022 | 0.0000 | ❌ REJECT |
| gamelength_min | 10 | 2.688 | 5.397 | 4.991 | +0.406 | 0.0000 | ✅ ACCEPT |
| gamelength_min | 15 | 2.688 | 5.397 | 4.764 | +0.633 | 0.0000 | ✅ ACCEPT |
| gamelength_min | 20 | 2.684 | 5.379 | 4.398 | +0.981 | 0.0000 | ✅ ACCEPT |
| gamelength_min | 25 | 2.501 | 5.049 | 3.938 | +1.112 | 0.0000 | ✅ ACCEPT |

## Por que `total_barons` foi rejeitado

Os modelos de barons APRENDERAM (delta positivo, p=0.0000), mas o ganho
absoluto é muito pequeno (Δ RMSE < 0.05) porque:
- Variância natural pequena: média de ~0.68 barons/jogo, sigma baixo
- Baseline mean é difícil de bater quando a distribuição é quase binária

**Decisão**: modelos de barons foram removidos. O mercado de barons continua
mostrando heurística (`baron_pressure`). Re-validar quando dataset crescer.

## Arquivos / código

### Treino e validação
- `tools/run_phase7_markets_gate.py` — pipeline completo (treino + bootstrap)

### Modelos salvos
```
live_models/markets/
    gamelength_min/minute_{10,15,20,25}/
    total_dragons/minute_{10,15,20,25}/
    total_kills/minute_{10,15,20,25}/
    total_towers/minute_{10,15,20,25}/
```
Cada subdiretório: `lgb_model.txt` + `metadata.json` (residual_sigma e
feature_importance preservados).

### Runtime
- `app_core/live_markets_runtime_core.py` — `predict_market(...)` retorna
  `{mean, p_over, sigma, ...}`. Compartilha o flag
  `ml_live_state_model_enabled` com Fase 6.

### Integração UI
- Painel `Análise em tempo real` da aba live-bet agora mostra:
  - P(team_a vence) calibrado (Fase 6)
  - State edge heurístico (referência)
  - **Mercados calibrados (Fase 7)**: predição + linha editável + P(over/under)
- Auto-retreino mantém-se: aviso de freshness e botão "Retreinar agora"

## Testes

- `mlcore/tests/test_live_market_models.py` (15 testes — `LiveMarketModel`)
- `mlcore/tests/test_live_markets_runtime_core.py` (10 testes — runtime helper)
- **Suite total: 3.750 testes, 0 failures, 1 skip**

## Quando esses ganhos viram realidade

O painel **já está ativo por default** (mesmo flag da Fase 6). Quando você
abrir a aba `Live-Bet` no app, vai ver o expander "Análise em tempo real" com:

- Banner de freshness (manifest data + recomendação)
- Inputs de estado (minuto, gold diff, kills, towers...)
- P(vence) calibrado
- **4 mercados** com linha editável + P(over) calibrada

## Impacto

| Mercado | Erro médio antes (RMSE) | Erro médio depois | Redução |
|---|---|---|---|
| kills @25min | 10.16 | 5.75 | **−43%** |
| towers @25min | 2.21 | 2.04 | −8% |
| dragons @25min | 1.01 | 0.84 | −17% |
| gamelength @25min | 5.05 | 3.94 | −22% |

Os mercados de **kills** e **tempo** ficam dramaticamente mais precisos. O
modelo absorve a informação de gold/xp/cs/kills até o minuto t para refinar
a predição do total final.
