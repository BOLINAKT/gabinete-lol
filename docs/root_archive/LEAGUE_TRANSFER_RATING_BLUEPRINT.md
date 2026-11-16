# League Transfer Rating Blueprint

## Objetivo

Resolver o problema de times dominantes em ligas fracas ou pouco conectadas,
sem inflar demais a odd em confrontos entre ligas.

A regra central e:

- nao medir so `quem domina`
- medir `o que continua forte quando o ambiente deixa de ajudar`

O projeto ja tem uma base boa para isso:

- forca estrutural por liga em [mlcore/tiers.py](C:/Users/steam/Desktop/gabinetelolweb3.1/mlcore/tiers.py)
- baseline entreligas em [app_core/interleague_baseline_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/interleague_baseline_core.py)
- calibracao hierarquica em [app_core/hier_calibration_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/hier_calibration_core.py)
- camada de players em [mlcore/players_layer.py](C:/Users/steam/Desktop/gabinetelolweb3.1/mlcore/players_layer.py)
- runtime pre-engine em [app_core/ml_pre_engine_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/ml_pre_engine_core.py)

O que falta e adicionar uma camada de `forca portatil`.

## Estrutura final

O modelo deve separar 4 blocos.

### 1. League Profile

Cada liga ganha um perfil, nao uma nota unica.

Features alvo:

- `league_strength`
- `league_depth`
- `league_reliability`
- `league_domestic_inflation`
- `league_patch_stability`
- `league_translation_score`

### 2. Team Profile

Cada time passa a ter leitura local e leitura exportavel.

Features alvo:

- `team_domestic_power`
- `team_transfer_power`
- `team_strength_of_schedule`
- `team_stomp_dependency`
- `team_out_of_script_strength`
- `team_closeout_efficiency`

### 3. Player / Lineup Profile

Players e lineup deixam de ser so delta de roster e viram sensores de portabilidade.

Features alvo:

- `player_domestic_rating`
- `player_portability`
- `player_consistency`
- `role_portability`
- `lineup_strength`
- `lineup_stability`
- `lineup_synergy`
- `lineup_transfer_power`

### 4. Cross-League Pricing Layer

O entreligas deixa de usar so `league_pair -> tier_pair -> macro_pair` e passa a usar:

- `league_translation_score`
- `league_reliability`
- `league_depth`
- `team_transfer_power`
- `player_portability`

com desconto em:

- `league_domestic_inflation`
- `team_stomp_dependency`
- `shallow_league_penalty`

## Colunas do Oracle a usar

As colunas abaixo existem no dump atual de 2026 e sao suficientes para a primeira versao.

### Base de resultado / contexto

- `league`
- `year`
- `split`
- `playoffs`
- `date`
- `patch`
- `side`
- `position`
- `playername`
- `teamname`
- `gamelength`
- `result`

### Resultado de time / ritmo

- `kills`
- `deaths`
- `assists`
- `teamkills`
- `teamdeaths`
- `ckpm`
- `team kpm`
- `totalgold`
- `earnedgold`
- `earned gpm`
- `gspd`
- `gpr`
- `towers`
- `opp_towers`
- `dragons`
- `opp_dragons`
- `barons`
- `opp_barons`
- `inhibitors`
- `opp_inhibitors`

### Early game / pressao

- `firstblood`
- `firstdragon`
- `firstherald`
- `firstbaron`
- `firsttower`
- `firsttothreetowers`
- `goldat10`
- `xpat10`
- `csat10`
- `golddiffat10`
- `xpdiffat10`
- `csdiffat10`
- `goldat15`
- `xpat15`
- `csat15`
- `golddiffat15`
- `xpdiffat15`
- `csdiffat15`
- `goldat20`
- `golddiffat20`
- `xpdiffat20`
- `csdiffat20`

### Player quality / role portability

- `damagetochampions`
- `dpm`
- `damageshare`
- `damagetakenperminute`
- `damagemitigatedperminute`
- `visionscore`
- `vspm`
- `wpm`
- `wcpm`
- `controlwardsbought`
- `cspm`
- `earnedgoldshare`

## Formulas de primeira implementacao

Nao comecar com embedding latente. Comecar com sinais simples, auditaveis e shrinkados.

### League signals

#### `league_strength`

Ja existe parcialmente.

Fonte:

- [mlcore/tiers.py](C:/Users/steam/Desktop/gabinetelolweb3.1/mlcore/tiers.py)
- [app_core/interleague_baseline_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/interleague_baseline_core.py)

Uso:

- continua como prior estrutural
- nao substitui sinais novos

#### `league_depth`

Pergunta: quao dificil e o ambiente abaixo do top 1?

Versao v1:

- inferir rating domestico por time
- ordenar times da liga por `team_domestic_power`
- medir media do rank 2 ao rank 6
- medir gap entre rank 1 e media rank 2-6
- medir dispersao entre rank 3 e rank 8

Formula sugerida:

`league_depth = mean(rank_2_to_6) - 0.5 * max(0, rank_1 - mean(rank_2_to_6))`

Shrink:

- shrink para media historica da propria liga
- shrink extra se houver poucos times / poucos jogos

#### `league_reliability`

Pergunta: quao confiavel e usar os numeros dessa liga como sinal de precificacao?

Componentes v1:

- previsibilidade residual da liga
- estabilidade entre patches
- completude de dados
- quantidade de jogos validos

Formula sugerida:

`league_reliability = 0.45 * predictability + 0.25 * patch_stability + 0.20 * sample_reliability + 0.10 * data_completeness`

Onde:

- `predictability` vem de logloss/brier/ECE residual da liga
- `patch_stability` mede desvio por patch dentro da liga
- `sample_reliability` usa tamanho amostral efetivo

#### `league_domestic_inflation`

Pergunta: quanto a liga infla dominio local?

Sinais v1:

- gap entre top 1 e top 6
- frequencia de stomp
- baixa profundidade
- baixa traducao historica

Formula sugerida:

`league_domestic_inflation = sigmoid( + gap_top1_top6 + stomp_rate_league - league_depth - translation_score )`

#### `league_patch_stability`

Pergunta: a liga muda demais de cara entre patches?

Sinais:

- variacao de `kills`, `gamelength`, `golddiffat15`, `objective control`
- desvio de perfil entre patch atual e patch historico

#### `league_translation_score`

Pergunta: o que acontece quando o ecossistema sai do proprio habitat?

Sinais v1:

- desempenho entreligas historico do bloco
- traducao de players quando trocam de liga
- traducao de academy/challenger para main league

Se nao houver evidencia suficiente:

- shrink para `league_strength` estrutural

### Team signals

#### `team_domestic_power`

Pergunta: quao dominante o time e dentro do seu ecossistema?

Sinais v1:

- win rate
- `golddiffat15`, `xpdiffat15`, `csdiffat15`
- controle de `towers`, `dragons`, `barons`
- `closeout_efficiency`

#### `team_strength_of_schedule`

Pergunta: contra quem esse time construiu seus numeros?

Sinais v1:

- qualidade media dos adversarios enfrentados
- peso extra para playoffs
- peso maior para top 5 da liga

#### `team_stomp_dependency`

Pergunta: quanto da forca depende de jogos fora do roteiro competitivo?

Sinais v1:

- percentual de vitorias com `golddiffat15` muito alto
- percentual de vitorias curtas com objetivo dominante
- diferenca entre metricas em jogos stomp e jogos contestados

#### `team_out_of_script_strength`

Pergunta: o time continua forte quando nao consegue o roteiro ideal?

Sinais v1:

- win rate sem `firstblood`
- win rate sem lead aos 15
- win rate quando perde `firstdragon` ou `firstherald`
- win rate em jogos longos

Formula sugerida:

`team_out_of_script_strength = mean([wr_no_fb, wr_no_lead15, wr_when_behind, wr_long_games])`

#### `team_closeout_efficiency`

Pergunta: quando abre vantagem, o time fecha?

Sinais v1:

- win rate com lead aos 15
- taxa de baron apos lead
- taxa de fechamento apos +X gold

#### `team_transfer_power`

Pergunta central do projeto.

Formula v1:

`team_transfer_power = team_domestic_power * league_reliability * (1 - league_domestic_inflation) * (0.55 + 0.45 * team_out_of_script_strength)`

Depois ajustar por:

- `team_strength_of_schedule`
- `lineup_transfer_power`

### Player / Lineup signals

#### `player_domestic_rating`

Por role, com ajuste de liga e role.

Sinais v1:

- `dpm`
- `damageshare`
- `earnedgoldshare`
- `visionscore`
- `vspm`
- `cspm`
- `golddiffat15`, `xpdiffat15`, `csdiffat15`

Sempre comparar contra:

- media da role na liga
- desvio da role na liga

#### `player_portability`

Pergunta: o player continua bem sem o habitat ideal?

Sinais v1:

- consistencia sem stomp
- performance em jogos contestados
- traducao historica entre ligas quando houver
- penalidade por role de baixa profundidade na liga

#### `lineup_strength`

Composicao do quinteto atual.

Versao v1:

- soma ponderada de `player_domestic_rating`
- ajuste por sinergia/stabilidade

#### `lineup_transfer_power`

Versao exportavel do quinteto.

Versao v1:

- soma ponderada de `player_portability`
- multiplicada por `lineup_stability`

## Onde isso entra no ML atual

### Antes do `fit full`

Implementar offline e runtime sem mudar o fit pesado ainda.

1. Novo builder offline de sinais

Arquivo sugerido:

- `mlcore/build_league_transfer_features.py`

Saida sugerida:

- `league_transfer_features.json`

Blocos:

- `by_league`
- `by_team`
- `by_player`
- `by_lineup`

2. Runtime pre-engine

Arquivos alvo:

- [app_core/ml_pre_engine_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/ml_pre_engine_core.py)
- [mlcore/players_layer.py](C:/Users/steam/Desktop/gabinetelolweb3.1/mlcore/players_layer.py)

Uso:

- aplicar `team_transfer_power`
- aplicar `player_portability`
- reduzir exagero de lineup dominante em liga inflada

3. Runtime interleague

Arquivos alvo:

- [app_core/interleague_baseline_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/interleague_baseline_core.py)
- [app_core/hier_calibration_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/hier_calibration_core.py)

Uso:

- `league_depth`
- `league_reliability`
- `league_domestic_inflation`
- `league_translation_score`

4. Estado / style / SOS

Arquivos alvo:

- [app_core/state_strength_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/state_strength_core.py)
- [app_core/style_matchup_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/style_matchup_core.py)
- [app_core/league_rank_sos_core.py](C:/Users/steam/Desktop/gabinetelolweb3.1/app_core/league_rank_sos_core.py)

Uso:

- aliviar ou apertar o peso de state/style quando a liga for pouco confiavel
- melhorar `strength_of_schedule` domestico

### Dentro do `fit full`

So depois do pipeline estar estavel.

Arquivos alvo:

- [mlcore/fit_ml_params.py](C:/Users/steam/Desktop/gabinetelolweb3.1/mlcore/fit_ml_params.py)

Objetivo:

- calibrar pesos de:
  - `team_transfer_power`
  - `league_reliability`
  - `league_domestic_inflation`
  - `player_portability`
  - `team_out_of_script_strength`

## Ordem recomendada de implementacao

### Fase A

Sem mexer no `fit full`.

1. Builder offline de `league_depth`
2. Builder offline de `league_reliability`
3. Builder offline de `team_domestic_power`
4. Builder offline de `team_out_of_script_strength`
5. Builder offline de `team_transfer_power`
6. Trace e golden tests dedicados

### Fase B

Ainda sem `fit full`.

7. `player_portability`
8. `lineup_transfer_power`
9. integracao no `players_layer`

### Fase C

Com tudo acima validado.

10. promover sinais para o `fit full`
11. retunar pesos
12. rerodar gates entreligas

## Guardrails para evitar erro "nao contava com isso"

### Schema

Todo builder novo deve validar:

- colunas obrigatorias presentes
- `participantid` em `{100, 200}` para camada de time
- role valida para camada de player
- patch/date parseados

### Fallbacks

Se faltar sinal:

- cair para prior estrutural existente
- nunca inventar liga, player ou lineup

### Gating por amostra

Nao usar sinal cru abaixo de amostra minima:

- liga: `n_games_eff`
- time: `n_games_eff`
- player: `n_games_eff` por role

### Trace

Adicionar no trace:

- `league_transfer_features_used`
- `team_transfer_power_a/b`
- `league_domestic_inflation_a/b`
- `league_reliability_a/b`
- `player_portability_summary`
- `lineup_transfer_power_a/b`

### Regressao

Criar tests/golden para:

- time dominante de liga fraca vs time medio de liga forte
- ERL forte vs ERL fraca
- academy/challenger vs main league
- time muito stomp-dependent vs time robusto

## Regra de negocio final

Em confrontos entreligas, a odd nao deve refletir so:

- recorde
- dominancia local
- ou nome da liga

Ela deve refletir:

- forca estrutural da liga
- profundidade da liga
- confiabilidade da liga
- inflacao domestica
- forca portatil do time
- portabilidade do lineup
- portabilidade dos players

## Criterio de sucesso

Essa arquitetura esta funcionando quando:

1. times `16-0`, `17-0`, `19-1` de liga rasa deixam de ser superestimados
2. times fortes de ligas medias, mas com lineup realmente forte, recuperam parte do credito
3. entreligas fica menos dependente de `macro_pair` grosseiro
4. confrontos suspeitos param de gerar odds que parecem "habitat only"
5. os ganhos aparecem principalmente em:
   - `inter_mixed`
   - `inter_minor_minor`
   - confrontos de ERL / cross-conference

## Decisao pratica

O melhor proximo passo tecnico nao e `fit full`.

O melhor proximo passo e:

1. builder offline `league_transfer_features`
2. plug de `team_transfer_power` + `league_reliability` no runtime
3. regressao dedicada
4. so depois disso, `fit full`
