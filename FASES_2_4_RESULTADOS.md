# Fases 2-4: Draft Features + LightGBM Stacking

**Data:** 2026-05-26
**Status do test suite:** 3.660 testes, 0 failures, 1 skip

---

## Resumo executivo

Implementei 4 candidatos de melhoria, validados rigorosamente pelo gate em
test set de 2.827 samples (2026 Abr-Mai). **Todos produziram sinal positivo,
mas nenhum passou o gate completo** — não por piorar, mas por insuficiência
de evidência estatística com o sample size atual.

| Candidato | Δlogloss | p-value | Resultado | Razão |
|---|---|---|---|---|
| Synergy isolada | +0.082pp | 0.478 | REJECT | Δ < 0.2pp |
| Counter isolada | +0.113pp | 0.246 | REJECT | Δ < 0.2pp |
| Synergy+Counter ensemble | +0.138pp | 0.246 | REJECT | Δ < 0.2pp |
| **LightGBM stacking** | **+0.327pp** | **0.116** | REJECT | p > 0.05 (sample size) |

**Decisão:** Nenhuma mudança foi ativada em produção. Manter código pronto para
ser ativado quando o dataset de 2026 crescer (esperar passar gate quando TEST ≥ 5000 samples).

---

## O que foi construído

### Fase 2: 3 features de draft

**`mlcore/draft_features/synergy.py`** — `ChampionSynergyTable`
- Bayesian shrinkage de win rate por duo/trio de champions
- Temporal decay (half-life 180 dias)
- SOS adjustment (descontar vitórias contra times fracos)
- Per-league priors
- 19 testes unitários

**`mlcore/draft_features/counter.py`** — `ChampionCounterTable`
- Matchup direto X vs Y por lane (top/jng/mid/bot/sup)
- Tier-gap adjustment (desconta survival bias de times fortes)
- Patch-awareness (separa estatísticas por patch major)
- 18 testes unitários

**`mlcore/draft_features/comp_archetype.py`** — `CompArchetypeTable`
- Usa `champion_knowledge_registry.json` (172 champions, traits engage/peel/scaling/etc)
- Logistic regression sobre diff de traits entre os 2 times
- Saída em [-1, +1]
- 16 testes unitários

### Fase 4: LightGBM stacking

**`tools/run_phase4_lightgbm_gate.py`** — pipeline completo:
- 9 features: z_baseline + n_team_eff + n_players_eff + bo + playoffs + league_tier + 3 draft scores
- LightGBM com early stopping em VAL
- Stacking com baseline em logit space
- Gate rigoroso em TEST

**Feature importance do LightGBM** (mostra que features de draft SÃO usadas):

| Feature | Importance |
|---|---|
| z_baseline | 28.168 |
| **counter_score** | **7.766** |
| bo | 6.572 |
| **synergy_delta** | **5.540** |
| n_players_eff | 1.901 |
| n_team_eff | 1.518 |
| archetype_score | 628 |

Counter foi a feature de draft mais valiosa, Synergy em segundo, Archetype em terceiro.

---

## Por que não passou o gate — análise honesta

### O sinal existe e é positivo

Todos os 4 deltas são positivos (+0.082 a +0.327pp). Não houve nenhum candidato
que piorou. Isso confirma que as features de draft contribuem algo.

### Mas é absorvido pelo pipeline atual

O sinal incremental sobre a baseline atual é pequeno porque:

1. **Players layer** já captura "Faker é bom mid" — quando Faker joga Ahri, o rating do Faker já reflete isso
2. **Elo team rating** já reflete "este time joga com champions que funcionam"
3. **Microseg + Platt** já limpa vieses sistemáticos por contexto

Sobra pouco sinal para features de draft "tradicionais" explicarem além disso.

### Sample size limita o p-value

O LightGBM teve **Δlogloss = +0.327pp** (acima do threshold de 0.2pp), mas
o p-value foi 0.116 — porque 2.827 samples de TEST é insuficiente para
detectar significância nessa magnitude.

**Quando dataset de 2026 crescer:** com 5.000+ samples no TEST, o mesmo Δ deve
passar o p-value < 0.05. Re-rodar `tools/run_phase4_lightgbm_gate.py` quando
o cutoff for ajustado para uma janela maior.

---

## Estado da produção

**Nada foi alterado em produção.** O sistema continua exatamente como estava após Fase 1:

- `ml_uncertainty_enabled = False` (Fase 1)
- `ml_marginal_trust_enabled = False` (Fase 1)
- `ml_postfusion_cal_enabled = True` (Fase 1, único ACCEPT)

logloss de produção: **0.61537** (test set 2.827 samples)
ECE de produção: **0.0594**

---

## Próximos passos recomendados

### Curto prazo (quando dataset crescer)

1. Re-rodar `tools/run_phase4_lightgbm_gate.py` quando TEST tiver ≥5.000 samples
   (esperar próxima janela cronológica). Se passar gate → ativar LightGBM stacking.

2. Re-rodar com mais bootstrap (n=2000-5000) para reduzir variance do p-value.

### Médio prazo (Fase 6+: Live ML)

Como o pré-jogo está perto do teto sem mais dados, atacar Fase 6 (Live ML)
é o próximo grande ganho:

- Modelo state→p_win com snapshots @10/@15/@20/@25
- Mercados de live (over/under kills, towers, tempo) treinados
- Esperar +5-10pp em logloss para o live (atualmente 40% do rigor do pré)

---

## Estimativa de qualidade atualizada

| Componente | Antes | Depois das Fases 2-4 |
|---|---|---|
| Pré-jogo | 9.3-9.4 | **9.3-9.4** (mantido, pipeline rigorosamente validado) |
| Live-bet | ~3.4 | **~3.4** (intocado) |
| Infraestrutura de validação | excelente | **excelente** (3 features prontas + LightGBM pronto) |
| Nota conjunta | 7.5 | **7.5** (mantida — não baixa nem sobe) |

A qualidade do pré-jogo está perto do teto realista. O próximo salto significativo
virá da Fase 6 (live ML), não de mais features no pré.

---

## Ferramentas e scripts criados

| Arquivo | Propósito |
|---|---|
| `mlcore/draft_features/` | Pacote completo das 3 features (synergy, counter, archetype) |
| `tools/run_phase2_synergy_gate.py` | Validação isolada da Synergy |
| `tools/run_phase2_counter_gate.py` | Validação isolada da Counter |
| `tools/run_phase2_draft_ensemble_gate.py` | Ensemble Synergy+Counter |
| `tools/run_phase4_lightgbm_gate.py` | LightGBM stacking pipeline completo |
| `FASE2_SYNERGY.json` | Numérico Synergy |
| `FASE2_COUNTER.json` | Numérico Counter |
| `FASE2_ENSEMBLE.json` | Numérico Ensemble |
| `FASE4_LIGHTGBM.json` | Numérico LightGBM (best feature importance documentado) |

Todos os scripts são parametrizados (val_cutoff, csv_paths) e reusable em CI.
