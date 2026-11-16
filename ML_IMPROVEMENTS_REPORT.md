# Relatório de Melhorias do ML — Resultado da Sessão

**Data:** 2026-05-26 (sessão de ablation studies)
**Holdout usado:** 1.313 samples (75/25 split do CSV diário de 2026)
**Status do test suite:** 3.565 testes, 8 failures pré-existentes (fixture regressions, não relacionadas)

---

## Mudanças aplicadas ✅

### 1. `ml_uncertainty_enabled` → **False** por padrão

**Arquivo:** `app_core/ml_settings_runtime_core.py`

**Evidência:** 0/7 configurações testadas (strength × prior_games) beat baseline.
Pior config: -0.38pp logloss, melhor (strength=0.05): -0.085pp.

**Ganho esperado em produção:** +1.30pp logloss (vs default anterior de strength=0.55).

A camada PIORA em todos os buckets de tamanho de amostra, inclusive nos que teoricamente
"mais precisariam" (n_team < 10: -2.21pp).

### 2. `ml_marginal_trust_enabled` → **False** por padrão

**Arquivo:** `app_core/ml_settings_runtime_core.py`

**Evidência:** 0/21 configurações testadas (7 confidence_scores × 3 strengths) beat baseline.
Pior config: -3.34pp, melhor: -0.25pp.

**Ganho esperado em produção:** +0.89pp logloss.

---

## Mudanças recomendadas (não aplicadas — exigem revisão humana) ⚠️

### 3. Adicionar Microseg + Platt APÓS a fusão team+players

**Local sugerido:** `app_core/ml_pre_engine_core.py`, após linha 583 (`p_map = float(fus.get("p_fused", ...))`).

**Evidência empírica (validada em 1.313 samples de holdout):**

```
Variant                                            Logloss    ECE
------------------------------------------------------------------
A  Cal BEFORE fusion (pipeline ATUAL)              0.61511   0.0851
B  Cal AFTER fusion                                0.60609   0.0872   +0.90pp
C  Cal BOTH (before AND after fusion)              0.60545   0.0440   +0.97pp + ECE -48%
D  No cal (naive)                                  0.63847   0.1024
```

**Ganho:** +0.97pp logloss + redução de **48% no ECE** (calibração quase pela metade do erro).

**Por que não foi aplicado automaticamente:**
- `ml_pre_engine_core.py` é grande (1075 linhas) com múltiplos paths de fusão (manual lineup, ML players layer, etc.)
- Mudança afeta todas as camadas live subsequentes (form_blend, hybrid, guards)
- Necessita teste de integração ou validação manual no app

**Patch sugerido (pseudocódigo):**

```python
# Após fusão team+players (~ linha 583)
p_map = float(fus.get("p_fused", p_map_team_local))

# === NOVA CALIBRACAO POS-FUSAO (recomendada) ===
if math.isfinite(p_map) and ss.get("ml_postfusion_cal_enabled", False):
    try:
        # Microseg em p_fused
        p_map, _ms_info = apply_microseg_fn(
            float(p_map),
            league=match_league, split=split_hint, side="blue",
            bo=str(int(bo_i)), phase=phase_hint,
            table=microseg_table,
            min_n=int(ss.get("ml_microseg_min_n", 30)),
            strength=float(ss.get("ml_microseg_strength", 0.60)),
            cap_pp=float(ss.get("ml_microseg_cap_pp", 8.0)),
            hierarchical=True, hierarchy_decay=0.80,
        )
        fusion_info["postfusion_microseg"] = _ms_info
        # Platt pos-fusao
        p_map, _pc_info = apply_postfusion_platt_fn(
            float(p_map), league_hint=match_league,
        )
        fusion_info["postfusion_platt"] = _pc_info
    except Exception as e:
        pass
```

A nova flag `ml_postfusion_cal_enabled` permite ligar/desligar para A/B testing.

---

## Achados secundários documentados (não aplicados)

### A-lite layer está piorando o modelo

**Fonte:** `backtest_pipeline_abc_by_league_report.json` (21.775 samples oficiais)

```
Base (team+players+season_form):  0.6437
+A (A-lite runtime):              0.6452  -0.15pp  PIORA
+B (style matchup):               0.6362  +1.05pp  ajuda
+C (meta blend):                  0.6315  +0.47pp  ajuda
```

Camada A (A-lite) com mesma assinatura empírica das duas que já desliguei: piora o modelo
quando aplicada. **Investigar em detalhe** antes de desabilitar (talvez seja apenas
overconfidence em alguns cenários — não é tão consistente quanto Uncertainty/Marginal Trust).

### Series gamma já está calibrado mas usado parcialmente

`series_gamma_global.bo3.gamma = 1.3` com melhoria documentada de **+0.42pp logloss** em 319 samples BO3.
`series_gamma_by_league` e `series_gamma_by_macro` estão **vazios** — só usa o global.

**Próximo passo:** rodar fit per-league para refinar (provavelmente +0.1 a +0.3pp adicional).

---

## Ferramentas criadas (reutilizáveis em CI)

| Script | Propósito |
|---|---|
| `tools/run_ablation_study.py` | Ablation de camadas de TREINAMENTO (Elo, Platt, players, microseg) |
| `tools/run_ablation_live_layers.py` | Ablation CUMULATIVO das camadas live (uncertainty, marginal trust, microseg) |
| `tools/run_ablation_isolated_layers.py` | Ablation ISOLADO + parameter sweep |
| `tools/run_ablation_confidence_sweep.py` | Validação Marginal Trust com múltiplos confidence_scores |
| `tools/run_ablation_calibration_order.py` | Ordem das calibrações (Platt vs Microseg vs ambos) |
| `tools/run_ablation_cal_position.py` | **Posição** das calibrações (antes vs depois da fusão) |

---

## Ganho total potencial em produção

| Item | Ganho esperado | Status |
|---|---|---|
| Desabilitar Uncertainty | +1.30pp | ✅ aplicado |
| Desabilitar Marginal Trust | +0.89pp | ✅ aplicado |
| Cal pós-fusão (Microseg + Platt) | +0.97pp + ECE -48% | ⚠️ recomendado |
| Investigar A-lite | ~+0.15pp | 🔬 pendente |
| Series gamma per-league | ~+0.10-0.30pp | 🔬 pendente |
| **TOTAL POTENCIAL** | **+3.4 a +3.6pp** | |

---

## Como continuar

1. **Validar mudanças aplicadas em produção** — rodar `tools/run_ablation_confidence_sweep.py`
   após próximo treino para confirmar que desabilitar continua sendo melhor.

2. **Aplicar patch da cal pós-fusão** — modificar `ml_pre_engine_core.py` com a flag
   `ml_postfusion_cal_enabled` (default `False`), depois testar no app real, depois ligar.

3. **Re-rodar `tools/update_regression_fixtures.py`** após próximo treino para resolver
   os 8 failures pré-existentes (mismatch de hash de artifact).

4. **Adicionar gate de aceitação para nova camada** — antes de adicionar qualquer camada
   nova ao pipeline, exigir:
   - Δlogloss_oos > 0.002
   - p-value < 0.05
   - ECE não piora

   Este gate evita o problema atual de camadas legacy que não foram validadas individualmente.
