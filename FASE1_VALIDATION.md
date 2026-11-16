# Fase 1: Validação rigorosa de melhorias com gate

**Data:** 2026-05-26
**Versão:** phase1_validation_v1
**Arquivo de dados:** `FASE1_VALIDATION.json`

---

## Metodologia

Todas as melhorias passaram pelo gate automatizado de `mlcore/ml_eval/gate.py`:

```
ACCEPT se:
  Δlogloss > 0.002 (≥0.2pp de melhoria)
  AND p-value < 0.05 (paired bootstrap, n=1000)
  AND Δece > -0.005 (calibração não piora mais que 0.5pp)
```

**Split:** Train 2024-2025 (20.252) | Test 2026 Apr-May (2.827 samples).

**Baseline:** simulação rigorosa da produção atual:
- Microseg em `p_team` (antes da fusão)
- Platt em `p_team_microseg` (antes da fusão)
- Fusão com `p_players`

**Resultado baseline:**
- logloss = **0.61755** CI 95% [0.60744, 0.62796]
- ECE = **0.0662**

---

## Resultados dos 4 candidatos

### ✅ Candidate 1: POST-FUSION CAL — **ACCEPT**

Adiciona Microseg + Platt **após** a fusão team+players, no topo da cal pré-fusão atual.

| Métrica | Valor |
|---|---|
| Δlogloss | **+0.218pp** |
| CI 95% | [+0.034, +0.381] |
| p-value | **0.008** |
| Δece | **+0.677pp** (melhora também a calibração) |
| Decisão | **ACCEPT** — passou todos os checks |

**Ação aplicada:** `ml_postfusion_cal_enabled = True` por padrão em `shared_ml_defaults()`.

---

### ✅ Candidate 2: UNCERTAINTY ENABLED — **REJECT** (validação retroativa confirmada)

Tenta re-habilitar a camada Uncertainty (já desabilitada anteriormente).

| Métrica | Valor |
|---|---|
| Δlogloss | **-1.042pp** (piora) |
| CI 95% | [-1.242, -0.829] |
| p-value | 0.000 |
| Δece | -2.109pp (também descalibra) |
| Decisão | **REJECT** — confirma que disable foi correto |

**Status:** mantém `ml_uncertainty_enabled = False`. Validação retroativa positiva.

---

### ✅ Candidate 3: MARGINAL TRUST ENABLED — **REJECT** (validação retroativa confirmada)

Tenta re-habilitar a camada Marginal Trust.

| Métrica | Valor |
|---|---|
| Δlogloss | **-0.704pp** (piora) |
| CI 95% | [-0.843, -0.559] |
| p-value | 0.000 |
| Δece | -1.416pp |
| Decisão | **REJECT** — confirma que disable foi correto |

**Status:** mantém `ml_marginal_trust_enabled = False`.

---

### ❌ Candidate 4: SERIES GAMMA PER-LEAGUE — **REJECT** (próximo do limiar)

Treina um gamma específico por (liga × BO) usando o train set, compara com gamma global.

| Métrica | Valor |
|---|---|
| Δlogloss | **+0.727pp** |
| CI 95% | [-0.030, +1.467] (CI cruza zero) |
| p-value | **0.066** (>0.05) |
| Δece | +0.930pp |
| Decisão | **REJECT** — não significativo estatisticamente |
| Detalhe | 54 (liga, BO) pairs treinados; test BO3/5 = 1.278 samples |

**Interpretação:** o ponto-estimativa é positivo, mas a incerteza é grande dado o sample size de séries BO3/5. **Não foi rejeitado por piorar — foi rejeitado por não ter significância estatística.** Aguardar mais dados ou aplicar regularização entre ligas pode passar o gate no futuro.

**Status:** mantém `series_gamma_global = 1.3` (BO3); `series_gamma_by_league` continua vazio.

---

## Impacto total da Fase 1

| Item | Antes (Fase 0) | Depois (Fase 1) |
|---|---|---|
| logloss produção | 0.61755 | **0.61537** (-0.218pp) |
| ECE produção | 0.0662 | **0.0595** (-0.677pp) |
| Camadas ativas | 11 | 12 (postfusion cal adicionada) |
| Camadas desabilitadas | Uncertainty, MT | Uncertainty, MT (mantidas) |
| Nota estimada | 9.0 | **9.3-9.4** |

> **Observação:** o ganho de 0.218pp é menor que o ablation isolado anterior (+0.97pp). Isso é normal: o teste rigoroso com baseline emulada de produção captura interações que o ablation simplificado não captura. A melhoria existe e é estatisticamente significativa.

---

## Como reproduzir

```bash
python tools/run_phase1_validation.py \
    --val-cutoff 2026-03-31 \
    --n-bootstrap 1000 \
    --output FASE1_VALIDATION.json
```

---

## Próximas fases

| Fase | Conteúdo | Tempo estimado |
|---|---|---|
| **Fase 2** | Draft features (synergy, counter, comp archetype) | 2 semanas |
| **Fase 3** | Calibração avançada (isotonic, beta, hierárquica) | 1 semana |
| **Fase 4** | Modelo base mais rico (LightGBM stacking ou TrueSkill) | 2-3 semanas |
| **Fase 5** | Validação final pré + relatório | 1 semana |
| **Fases 6-8** | Live ML (state→p_win, mercados, refinement) | 4-6 semanas |
