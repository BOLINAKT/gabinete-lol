# Live ML Models

Modelos LightGBM treinados para predição de vitória em tempo real (state→p_win).

## Estrutura

```
live_models/
    minute_10/
        lgb_model.txt       # LightGBM booster
        platt.json          # Calibrador Platt
        metadata.json       # Configuração, features, importance
    minute_15/   (mesma estrutura)
    minute_20/   (mesma estrutura)
    minute_25/   (mesma estrutura)
```

## Como usar (recomendado: helper de alto nível)

A forma mais simples é usar `app_core.live_state_runtime_core.predict_live_p_win()`,
que verifica feature flag, faz lazy load, e retorna `None` quando o app deve
usar a heurística antiga:

```python
from app_core.live_state_runtime_core import predict_live_p_win

p_live = predict_live_p_win(
    session_state=st.session_state,
    minute=15,
    gameid="LOLTMNT05_171038",
    side="Blue",
    p_map_pre=0.62,
    league="LCK",
    bo=5,
    is_playoffs=True,
    state_features={
        "goldat15": 30000, "xpat15": 32000, "csat15": 500,
        "killsat15": 5, "deathsat15": 2, "assistsat15": 8,
        "opp_goldat15": 28000, "opp_xpat15": 30000, "opp_csat15": 480,
        "opp_killsat15": 2, "opp_deathsat15": 5, "opp_assistsat15": 3,
    },
)
if p_live is not None:
    # Usar a predicao calibrada
    ...
else:
    # Cair na heuristica antiga (flag off ou modelo indisponivel)
    ...
```

### Como ATIVAR

Defina `ml_live_state_model_enabled = True` no `session_state` (UI ou direto):

```python
st.session_state["ml_live_state_model_enabled"] = True
```

Antes da ativação, o helper retorna `None` para todos os chamadores, então o
app continua usando heurísticas existentes. **Nenhum código precisa mudar** —
apenas chamar `predict_live_p_win()` onde quiser refinar a predição.

## Uso de baixo nível (controle total)

Se preferir carregar os modelos diretamente:

```python
from mlcore.live_ml import StateToWinModel, build_snapshot_features

models = {
    minute: StateToWinModel.load(f"live_models/minute_{minute:02d}")
    for minute in (10, 15, 20, 25)
}

snapshots = build_snapshot_features(
    team_rows,
    minute=15,
    p_map_pre_by_gameid_side={(gameid, "Blue"): p_pre_blue, (gameid, "Red"): 1.0 - p_pre_blue},
)
for snap in snapshots:
    p_live = models[snap.minute].predict_proba_one(snap)
```

## Métricas oficiais (test set Apr-Mai 2026)

| Snapshot | n_test | Baseline logloss | Live logloss | Δlogloss | p-value |
|---|---|---|---|---|---|
| @10 min | 5.376 | 0.61417 | **0.51547** | +9.87pp | 0.0000 |
| @15 min | 5.376 | 0.61417 | **0.46567** | +14.85pp | 0.0000 |
| @20 min | 5.368 | 0.61445 | **0.40502** | +20.94pp | 0.0000 |
| @25 min | 5.002 | 0.62234 | **0.32957** | +29.28pp | 0.0000 |

Todos passaram o gate (Δlogloss > 0.002, p < 0.05, ECE não piora).

## Re-treinar

Para re-treinar quando o dataset crescer:

```bash
python tools/run_phase6_live_gate.py \
    --val-cutoff 2026-XX-XX \
    --save-models-dir live_models
```

O cutoff deve ser ajustado conforme dados de 2026 crescem (ex: setembro/2026 use `--val-cutoff 2026-06-30`).

## Status de integração

- ✅ **Modelos treinados e salvos** (este diretório)
- ✅ **Feature flag adicionada** (`ml_live_state_model_enabled`, default `False`)
- ✅ **Helper runtime pronto** (`app_core/live_state_runtime_core.py`, 15 testes)
- ⏳ **Aguardando chamada explícita** no live-bet tab — qualquer ponto do app pode chamar
  `predict_live_p_win()` para obter a predição calibrada

O app continua funcionando exatamente como antes enquanto a flag estiver `False`.
Para começar a usar, basta:
1. Setar a flag para `True` (UI ou direto no session_state)
2. Chamar `predict_live_p_win()` onde quiser usar a predição refinada
