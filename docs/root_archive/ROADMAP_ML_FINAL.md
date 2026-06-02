# Roadmap ML Final (Top Quality, Sem Retrabalho)

Objetivo: fechar lacunas de modelagem com critérios rígidos de aceite, sem mudanças “meia-boca”.

## Status Snapshot (2026-02-28)

- Guardrail final: `promote` (`lacuna_guardrail_report.json`)
- `prod_refresh` (quick + promote-on-pass): `final_decision=promote`, `action_ok=true`
- `prod_refresh` mais recente: `generated_at=2026-02-28T14:12:41+00:00`, `action=promote_baseline`, `returncode=0`
- Fases (strict coverage):
  - phase1_data_contract: `promote`
  - phase12_roster: `promote`
  - phase2_areal: `promote`
  - phase2b_areal_tuning: `promote`
  - phase3_breal: `promote`
  - phase4_ranksos: `promote`
  - phase5_hier_calibration: `promote`
  - phase6_series_bo: `promote`
  - phase7_layer_uncertainty: `promote`
  - phase8_operations: `promote`

Observação: esse snapshot é o estado operacional atual. Qualquer evolução nova deve ser promovida novamente via guardrail + `prod_refresh`.

## Princípios de execução

- Toda fase deve terminar com:
  - testes automatizados verdes
  - relatório de ganho/perda (logloss/brier/ece)
  - decisão de promoção via guardrail único (`lacuna_guardrail_report.json`)
  - rollback viável (`tools/rollback_baseline.py`)
- Nenhuma mudança sobe por “sensação”. Só por evidência.
- Se KPI piorar fora da tolerância: `shadow_only` ou `reject`.

## KPIs oficiais (contrato)

- Logloss global e por liga
- Brier global e por liga
- Calibração (ECE) por faixa de probabilidade
- Bateria de âncoras sem regressão semântica
- Cobertura de dados (ligas/times/aliases/team blank)

## Fases

### Fase 0 — Governança e baseline (congelamento)

Status esperado: concluída.

Checklist:
- [ ] snapshot baseline criado (`tools/create_baseline_snapshot.py`)
- [ ] guardrail único operacional (`tools/run_lacuna_guardrails.py`)
- [ ] promoção/rollback validados no app

Saída:
- `lacuna_guardrail_report.json`
- `rollback_baseline_report.json`

---

### Fase 1 — Dados e causalidade (anti-leakage)

Objetivo:
- Garantir que features usadas no pré-jogo são causais.
- Garantir consistência de rótulo por BO/side/playoffs/patch.

Checklist:
- [ ] `tools/check_data_leakage_and_labels.py` sem erro crítico
- [ ] cobertura mínima de ligas/times aprovada
- [ ] contrato de dados diário validado
- [ ] gate consolidado Fase 1 aprovado

Saída:
- `data_leakage_label_report.json`
- `phase1_data_contract_report.json`

---

### Fase 2 — A-real incremental (estado robusto)

Objetivo:
- Atualização incremental de estado `mu/sigma` por jogos novos.
- Backfill seguro e drift por patch/liga.

Checklist:
- [ ] incremental + backfill passam sem crash
- [ ] estabilidade em ligas principais
- [ ] melhora ou neutralidade controlada vs baseline

Saída:
- artefato de estado atualizado
- relatório de comparação shadow

---

### Fase 3 — B-real rolling (style/matchup robusto)

Objetivo:
- Matchup por contexto patch/liga sem overfit.
- Gates de confiabilidade e fallback automáticos.

Checklist:
- [ ] contexto forte usa submodelo contextual
- [ ] contexto fraco cai para global/lite
- [ ] ganhos OOS por liga sem instabilidade

---

### Fase 4 — Rank-SOS definitivo

Objetivo:
- Resolver de forma definitiva força de calendário intra-liga.

Checklist:
- [ ] janela recente + força adversário
- [ ] regularização em ligas curtas
- [ ] casos âncora do tipo S2G/Bushido/Misa coerentes

---

### Fase 5 — Calibração hierárquica final

Objetivo:
- Calibração global -> liga -> segmento (BO/playoffs/inter) com shrink por evidência.

Checklist:
- [ ] baseline com `by_segment` estável
- [ ] ECE melhora (global + ligas principais)
- [ ] trace explica escopo/weights aplicados

---

### Fase 6 — Série BO (side-aware/DP avançado)

Objetivo:
- Refinar modelagem de série com dinâmica robusta por mapa.

Checklist:
- [ ] consistência BO3/BO5 em backtest
- [ ] sem explosão em extremos
- [ ] fallback estável

---

### Fase 7 — Incerteza formal por camada

Objetivo:
- Transformar confiança em sinal operacional (não só cosmético).

Checklist:
- [ ] incerteza por camada A/B/C no trace
- [ ] shrink conservador coerente com evidência
- [ ] zona de baixa acionabilidade bem sinalizada

---

### Fase 8 — Operação contínua

Objetivo:
- Troca diária de CSV com validação automática e previsível.

Checklist:
- [ ] checagem pré-operação automática
- [ ] monitoramento contínuo por liga/faixa
- [ ] regressão semântica automatizada (âncoras)

## Comandos padrão (rotina)

1. Validar contrato de dados (Fase 1):
`python tools/run_phase1_data_contract.py`

2. Rodar guardrail único:
`python tools/run_lacuna_guardrails.py --timeout 600`

3. Ver decisão:
- `promote`: pode promover baseline
- `shadow_only`: manter em observação
- `reject`: rollback/correção obrigatória

## Política de promoção

- Só promover quando:
  - guardrail final = `promote`
  - nenhum KPI crítico piorou acima da tolerância
  - âncoras sem regressão relevante

## Política de rollback

- Se `reject` ou regressão crítica de odds/kpi:
  - `python tools/rollback_baseline.py`
  - rerodar validações antes de novo promote
