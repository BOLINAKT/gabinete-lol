# Plano de separação — a "força-tarefa final" (arquivo-a-arquivo)

> Complementa [ARQUITETURA_ALVO.md](ARQUITETURA_ALVO.md). Aquele diz o **destino**
> (5 camadas). Este diz **onde cada um dos 235 módulos de `app_core/` mora** e
> **como mover sem quebrar o app no ar**. Começado na força-tarefa de 23/07.

## Os 3 pilares (pedido dele, 23/07)
1. **Separar tudo no seu devido lugar** — mexer com segurança: o que quebrar está
   onde você pôs a coisa nova.
2. **Testes nas partes importantes** — junto com a separação.
3. **Validação com a internet** — ver se já fizeram e como, pra melhorar.
   *(Feito: a arquitetura-alvo bate com o consenso 2025 — separar UI de lógica,
   camada de serviço sem Streamlit, entrada fina. Fontes no histórico da sessão.)*

Depois disso, só falta o **polimento das abas** (aba por aba, com ele).

---

## O RISCO que reordena tudo (achado 23/07)

`plays_app.py` passa `ctx=globals()` para os renderers, que puxam dezenas de
`core_*` **por string** (`ctx.get("core_x")`). Quando fatiamos um módulo pra fora,
o padrão atual é **re-importar no plays_app** pra o nome cair no `globals()`. Logo:

> **Mover um módulo de lugar = mudar o import no `plays_app`. Se o nome não cair
> no `globals()`, o `ctx.get` vira `None` CALADO e explode longe** (é o bug
> documentado no plays_app linha ~1785: "35 nomes viravam None → aba sumia").

Consequência: **a reorg de pastas depende da espinha estar explícita.** Já existe
a semente certa — `app_core/render_ctx_core.build_render_ctx` deriva as chaves da
fonte do renderer e **valida `core_*` com erro ALTO**. O caminho seguro é:
tornar a espinha explícita (todos os `ctx=globals()` → `build_render_ctx(...)`)
**antes ou junto** de mover os módulos. Isso é trabalho **supervisionado** (a
prova é o E2E + você clicando cada tela).

---

## Método por peça (provado: state_team, hier_calibration)
1. **Rede primeiro**: golden de equivalência (`tools/equivalence_check.py`, agora
   sem quebrar no Windows) + suíte (4577) + E2E.
2. **Mover** para a subpasta certa.
3. **Re-exportar** no lugar antigo (shim) OU atualizar o import no `plays_app`
   garantindo o nome no `globals()`.
4. **Provar idêntico** (golden + suíte + E2E). Só então commit.

---

## Classificação dos 235 módulos (destino de cada um)

Camada por convenção de nome + se importa `streamlit`. Total: config 2 · state 15
· domain 146 · runtime 31 · ui 41.

### → `app_core/config/` (2) — fonte única
`app_settings_config_core`, `stats_config`
*(o registro de mercados já é fonte única — passo 1 FEITO)*

### → `app_core/state/` (15) — session_state, params, persist
`app_state`, `bootstrap_maintenance_state_core`, `analysis_runtime_state_core`,
`schedule_state_core`, `resumo_state_core`, `runtime_session_state_core`,
`navigation_state_core`, `results_runtime_state_core`, `team_state_persist_core`,
`ui_stale_state_core`, `statscamps_state_core`, `ml_confidence_baseline_persist_core`,
`champions_state_core`, `tab_state_core`, `settings_state_core`

### → `app_core/runtime/` (31) — orquestra estado→domínio→resultado
`csv_bootstrap_flow_core`, `text_normalization`, `viewer_mode_core`,
`ml_session_runtime_core`, `csv_bootstrap_runtime_core`, `fit_runtime_core`,
`matchup_selection_core`, `lineup_runtime_core`, `flow_runtime_core`,
`resumo_runtime_core`, `maintenance_runtime_core`, `live_state_runtime_core`,
`ml_league_runtime_core`, `daily_pipeline_runtime_core`, `live_markets_runtime_core`,
`ml_adjust_helpers_core`, `visao_geral_runtime_core`, `ml_settings_runtime_core`,
`live_player_props_runtime_core`, `live_first_markets_runtime_core`,
`pre_delivery_runtime_core`, `confidence_runtime_core`, `diagnostics_helpers_core`,
`artifact_loaders_core`, `runtime_wrappers_core`, `nav_pages_core`, `ui_cache_core`,
`governance_runtime_core`, `streamlit_apptest_core`, `settings_ui`,
`players_artifact_runtime_core`

### → `app_core/ui/` (41) — abas e componentes (prova VISUAL, dele)
As 7 gordas primeiro (candidatas a fatiar por dentro também):
`line_analysis_tab_core` (1725), `consistencia_tab_core` (1228),
`live_bet_tab_core` (1220), `players_tab_core` (1154), `resumo_tab_core` (1143),
`visao_tab_core` (1137), `radar_tab_core` (1025). + 34 menores
(`params_tab_core`, `*_ui_core`, `*_panel_ui_core`, `*_cards_ui_core`, ...).

### → `app_core/domain/` (146) — matemática/regras puras, cada uma com teste
Maiores: `live_bet_draft_core`, `ml_pre_live_pipeline_core`, `market_v3_analysis_core`,
`hier_calibration_core`, `resumo_core`, `ml_pre_engine_core`, `interleague_baseline_core`,
`consistency_core`, `ml_confidence_baseline_core`, `league_rank_sos_core`,
`state_strength_areal_core`, `resumo_score_core`, `players_core`,
`ml_probability_adjustments_core`, `comp_archetype_core`, `odds_core`,
`radar_confronto_core`, `opponent_profile_core`, `ml_prediction_core`, ... (lista
completa em `scratchpad/sep_classif.json`).
**Nota:** alguns "domain" ainda importam `streamlit` indiretamente ou leem
`st.session_state` (ex.: `ml_adjust_helpers_core` foi pra runtime) — checar caso a
caso; o alvo é domain NÃO conhecer Streamlit.

---

## Espinha `globals→ctx` — COMPLETA (23/07)

**✅ 18/18 `ctx=globals()` reais eliminados do plays_app.** Cada renderer/wrapper
recebe agora só as chaves que a árvore (incl. transitiva cross-módulo) de fato
usa. Ferramentas: dict nomeado direto (imports, falha alta), `_pick_ctx(*chaves)`
(runtime, globals().get preserva None-se-ausente), `_pick_ctx_from_modules(...)`
(fecho cross-módulo auto-derivado das fontes, à prova de drift). Tudo E2E-verde;
aba Parâmetros e gate de boot testados. Reorg de pastas agora está DESTRAVADA.

_(histórico abaixo)_

**11 de 19 `ctx=globals()` convertidos para contrato EXPLÍCITO** (dict nomeado com
as chaves que a árvore usa, ou `build_render_ctx` auto-derivado quando o renderer
não repassa ctx). Cada um auditado (chaves + repasse) e verificado por E2E.
Commits 60a264a, ddabc44, (feature_trace). Feitos: confidence trio, series_gamma,
calibrate_p, resolve_players_artifact, patch_meta_guard, ach_layer,
generate_and_persist_team_state, render_calibracoes (Técnico), append_feature_trace.

**ATUALIZAÇÃO 23/07 (2ª passada, supervisionada):** +5 convertidos (elo,
series_totals, rank_table, 2 de manutenção) → **16/18**. Sobram 2 DEFERIDOS.

**LIÇÃO (peguei quebrando o E2E):** a transitividade do ctx **cruza MÓDULOS**.
`rank_table_v2` repassa ctx a `ach_layer_for_artifact` de OUTRO módulo
(achievements), que lê `_load_achievements_cached` — grep só do módulo direto
PERDE isso → `'NoneType' object is not callable` no boot. Regra: para converter
um que repassa ctx, rastrear o fecho CROSS-módulo inteiro (todos os `ctx=ctx`,
recursivo) e conferir que cada alvo lê só `ctx.get("literal")`.

**2 DEFERIDOS (ctx=globals() de propósito, com nota no código):**
- `csv_bootstrap_gate`: fecho de **31 chaves em 3 módulos** (repassa a
  ensure_csv_runtime_ready E collect_maintenance_status). Um dict na mão apodrece
  e é crítico no boot → só com **redesign de contexto TIPADO** (com você).
- `render_params_tab`: repassa a `_render_manutencao_ml`/`_render_governanca_ml`
  (fecho incerto) e a aba **não é coberta pelo E2E** → fazer clicando a aba Params.

**A converter no futuro (antigo texto, alguns já feitos):**
1. **Valores de runtime na chave** (NameError-vs-None): `series_totals`
   (bo/n_sims/p_map_cal/totals_mode) e `csv_bootstrap_gate` (fp_key/owner_token/
   run_id). Um dict explícito estoura NameError num caminho onde `globals().get`
   dava None de boa — mudança de comportamento. Decidir caso a caso com você.
2. **Repasse de ctx pra baixo** (auto-derive incompleto): `rank_table_v2`,
   `collect_maintenance_status` (15 chaves), `run_auto_maintenance_now` (15).
3. **Não coberto pelo E2E** (prova visual sua): `render_params_tab` (73 chaves +
   repasse) — precisa você clicar a aba Params. Um dict de 73 chaves seria PIOR
   que globals(); ali o certo é `build_render_ctx`, mas só com sua validação visual.

## Ordem recomendada (revisada pelo risco do ctx)
1. **Espinha explícita primeiro (supervisionado):** converter os `ctx=globals()`
   restantes do `plays_app` para `build_render_ctx(...)`. Destrava as reorgs com
   segurança (contrato explícito + validação alta). Prova: E2E + você clicando.
2. **state/ e config/** (baixo risco, provável por suíte): 17 módulos.
3. **runtime/** (31): depende de 1 e 2.
4. **domain/** (146) com teste por peça — a maior parte, provável por
   equivalência+suíte.
5. **ui/** (41): a reorg é estrutural; o **polimento visual** é a fase final dele.

---

## Estado (23/07, sessão autônoma)
**Feito com segurança (sem tocar no app no ar):**
- Pilar 3: arquitetura validada na web (bate com consenso 2025).
- Pilar 2: testes novos em lógica pura sem cobertura — `meta_patch_core` (15),
  `live_between_maps_core` (11), guard de `app_settings_config_core` (3).
- Rede: `equivalence_check.py` não quebra mais no Windows; golden re-salvo.
- Este plano (classificação dos 235 + ordem + risco).

**Pulado pra quando ele voltar (precisa dele — a prova é visual/decisão):**
- A espinha `globals→ctx` (passo 1 acima) e as reorgs dependentes.
- Decidir a **canônica** dos helpers-variante (`_safe_logit`, `_norm_team_key`:
  corpos diferentes — unificar muda comportamento).
- O polimento visual aba por aba.
