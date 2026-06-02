# Fase 0: Baseline rigoroso do ML

**Data:** 2026-05-26
**Versão:** phase0_baseline_v1
**Arquivo de dados:** `FASE0_BASELINE.json` (numérico completo, para reprodução)

---

## O que foi feito nesta fase

### 1. Resolução de 8 failures pré-existentes
- Rodado `tools/update_regression_fixtures.py` para regenerar fixtures com o `ml_artifact.json` atual.
- **Resultado:** suite passou de "3565 tests, 8 failures" para "3580 tests, 0 failures, 1 skip".

### 2. Harness unificado de avaliação ML
Novo package: **`mlcore/ml_eval/`**

| Módulo | Função |
|---|---|
| `splits.py` | Holdout cronológico train/val/test (sem leakage) |
| `metrics.py` | logloss, ECE, Brier com bootstrap CI (95%) |
| `gate.py` | Acceptance gate automatizado (Δlogloss > 0.002, p<0.05, ECE não piora) |

**26 testes unitários** em `mlcore/tests/test_ml_eval_harness.py`. Todas as fases seguintes vão usar este harness.

### 3. Baseline numérico documentado

**Split usado:**
| Bucket | Período | Samples |
|---|---|---|
| TRAIN | 2024-01-01 → 2025-12-29 | 20.252 |
| VAL | 2026-01-08 → 2026-03-31 | 2.427 |
| TEST | 2026-04-01 → 2026-05-28 | 2.827 |

> **Nota sobre o split:** o CSV de 2026 cresce diariamente conforme você atualiza. O cutoff `2026-03-31` foi escolhido para garantir TEST ≥ 2.000 samples no momento do baseline. Ao avançar a temporada, o cutoff deve ser reajustado mensalmente (eg, `2026-08-31` quando tivermos 5 meses de TEST disponível). O script é parametrizado.

### 4. Resultados do baseline atual (TEST set, 2.827 samples)

| Layer | logloss | CI 95% | ECE |
|---|---|---|---|
| L0 Elo team only | 0.65111 | [0.6456, 0.6565] | 0.1071 |
| L1 + Players fusion (raw) | 0.63898 | [0.6329, 0.6450] | 0.1103 |
| L2 + Platt on fused | 0.61732 | [0.6063, 0.6286] | 0.0481 |
| L3 + Microseg on fused | 0.63295 | [0.6265, 0.6392] | 0.1177 |
| **L4 final (Microseg + Platt)** | **0.60949** | **[0.5985, 0.6213]** | **0.0479** |

**Layer de produção atual:** L4 (Microseg + Platt sequencial)
**Logloss de referência: 0.60949** — qualquer melhoria deve ser medida contra esse número.

### 5. Per-league breakdown (TEST set)

Top 15 ligas por volume:

| Liga | n | logloss | ECE |
|---|---|---|---|
| LCKC | 204 | 0.62869 | 0.0668 |
| LCK | 190 | 0.55085 | 0.1022 |
| LPL | 189 | 0.63640 | 0.0587 |
| LAS | 170 | 0.57377 | 0.1001 |
| EWC | 151 | 0.61540 | 0.1063 |
| LJL | 138 | 0.60943 | 0.1942 |
| CD | 113 | 0.67029 | 0.1050 |
| NACL | 110 | 0.62467 | 0.0806 |
| AL | 109 | 0.61817 | 0.1669 |
| PRM | 105 | 0.52958 | 0.1553 |
| LEC | 104 | 0.57636 | 0.0964 |
| LIT | 91 | 0.62947 | 0.1161 |
| CBLOL | 84 | 0.62367 | 0.1108 |
| TCL | 83 | 0.56070 | 0.1358 |
| LCS | 79 | 0.60178 | 0.0839 |

---

## Gate de aceitação para mudanças futuras

A partir de agora, **qualquer nova camada/feature/modelo no pipeline ML deve passar pelo gate**:

```python
from mlcore.ml_eval import acceptance_gate

decision = acceptance_gate(
    y=test_labels,
    p_baseline=p_current,
    p_candidate=p_with_new_layer,
    min_delta_logloss=0.002,  # melhoria mínima de 0.2pp
    alpha=0.05,                # significância estatística
    ece_tolerance=0.005,       # ECE pode piorar no máximo 0.5pp
    n_bootstrap=1000,
)
if not decision.accept:
    raise ValueError(f"Gate rejected: {decision.reason}")
```

Critérios cumulativos:
1. **Δlogloss > 0.002** (melhoria de pelo menos 0.2pp)
2. **p-value < 0.05** (paired bootstrap, estatisticamente significativo)
3. **Δece > -0.005** (calibração não pode piorar mais que 0.5pp)

Se qualquer um falha → REJECT.

---

## Estado das melhorias anteriores (já aplicadas, mas SEM passar pelo gate antes)

Estas mudanças foram aplicadas antes do gate existir. **Vão ser validadas retroativamente na Fase 1**:

| Mudança | Status |
|---|---|
| `ml_uncertainty_enabled = False` | Aplicada — validar com gate |
| `ml_marginal_trust_enabled = False` | Aplicada — validar com gate |
| `ml_postfusion_cal_enabled = False` (helper pronto) | Helper feito — gate vai decidir se aceita |

---

## Próximas fases (Fase 1+)

Cada fase produz um delta vs L4 baseline e passa pelo gate.

| Fase | Conteúdo | Estimativa de tempo |
|---|---|---|
| **Fase 1** | Quick wins (postfusion cal, A-lite ablation, series_gamma per-league) | 1 semana |
| **Fase 2** | Draft features (synergy, counter, comp archetype) | 2 semanas |
| **Fase 3** | Calibração avançada (isotonic, beta) | 1 semana |
| **Fase 4** | Modelo base mais rico (LightGBM stacking ou TrueSkill) | 2-3 semanas |
| **Fase 5** | Validação final do pré + relatório | 1 semana |
| **Fase 6** | Live: modelo state→p_win por snapshot | 2-3 semanas |
| **Fase 7** | Live: mercados (kills, towers, tempo) | 1-2 semanas |
| **Fase 8** | Live: refinement (decay, volatility) | 1 semana |

**Total: 12 semanas** para chegar em **pré ~9.7-9.8 + live ~85-90% do pré**.

---

## Como reproduzir

```bash
# Atualizar fixtures (resolve failures de regressão)
python tools/update_regression_fixtures.py

# Rodar baseline (atualiza FASE0_BASELINE.json)
python tools/run_baseline_phase0.py --val-cutoff 2026-03-31 --n-bootstrap 1000
```

O `--val-cutoff` deve ser reajustado conforme dados de 2026 crescem (regra: garantir TEST ≥ 2.000 samples).
