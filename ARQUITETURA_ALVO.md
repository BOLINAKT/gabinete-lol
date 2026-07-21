# Mapa-alvo da arquitetura — "tudo no seu devido lugar"

> Objetivo (seu, 21/07): um código onde **adicionar ou consertar algo não dói**,
> porque cada coisa tem um lugar óbvio. Não é "zero bug"; é "sei exatamente
> onde mexer, e mexer aqui não quebra lá".
>
> Este é o ALVO. A migração é incremental e protegida por rede (testes +
> equivalência), nunca um rewrite. O modelo no ar nunca quebra.

---

## O diagnóstico real (não é o que parecia)

O código **não é monolítico** — é o oposto: **233 módulos planos** em `app_core/`,
58 em `mlcore/`. O problema não é falta de fatiamento; é **falta de arrumação**.
Os nomes já sugerem uma estrutura que nada impõe:

- Sufixos de camada: `tab_core` (15), `ui_core` (25), `runtime_core` (19),
  `state_core` (12), `persist_core`, `config_core`.
- Prefixos de domínio: `ml` (28), `live` (15), `resumo` (10), `players` (10),
  `csv`/`maintenance` (12), `lines`/`line` (8), `market` (6), `schedule` (5),
  `matchup` (4).

Ou seja: a taxonomia existe na sua cabeça e nos nomes — só não está nas pastas.
**Quando você vai adicionar um mercado, não há um lugar; há seis.**

---

## As 3 regras que definem "pronto"

1. **Um lugar só para cada conceito** (fonte única). Um mercado é definido uma
   vez; todo o resto DERIVA dele. *(já começamos: `STATS_MARKET_CONFIG`)*
2. **Dependência numa direção só e explícita.** Dado → cálculo → runtime → tela.
   Nunca de volta. Sem `globals()→ctx` (passar na mão, com tipo).
3. **Peças pequenas e testáveis, com rede.** Sem função-monstro, sem closure
   enterrado. Cada regra é uma função que se testa sozinha.

---

## As camadas (o "onde mora cada coisa")

Direção da seta = quem PODE importar quem. Nunca ao contrário.

```
  [1] modelo puro        mlcore/            WHR, calibração, fit, matemática.
        ↑                                   NÃO conhece app, UI nem Streamlit.
  [2] domínio do app     app_core/domain/   regras de negócio: mercados, linhas,
        ↑                                   players, meta. Puro, testável.
  [3] estado + config    app_core/state/    session_state, params, persistência,
        ↑                app_core/config/   registros centrais (mercados etc.).
  [4] runtime            app_core/runtime/  orquestra: pega estado → chama
        ↑                                   domínio/modelo → devolve resultado.
  [5] apresentação       app_core/ui/       abas, componentes, HTML. SÓ desenha
        ↑                                   o que o runtime já calculou.
  [6] entrada            plays_app.py       fino: monta a página e delega.
```

**A regra de ouro:** UI nunca calcula; domínio nunca desenha; modelo nunca sabe
que existe um app. Hoje essas fronteiras estão borradas (o `plays_app` calcula E
desenha E orquestra; abas às vezes calculam).

O split `mlcore` ← `app_core` JÁ existe e a régua já o vigia (mlcore não importa
app_core). O trabalho é organizar o `app_core` por dentro nessas 5 sub-camadas.

---

## "Quando eu quiser adicionar X, vá aqui" (o payoff)

| Você quer... | Hoje | No alvo |
|---|---|---|
| **um mercado novo** | mexer em ~6 arquivos | 1 entrada em `config/markets` — o resto deriva |
| **uma aba/análise nova** | copiar uma aba, rezar pelo ctx | 1 módulo em `ui/` implementando a interface de aba + 1 registro |
| **uma alavanca do modelo** | achar no meio do pipeline | 1 função em `domain/` + 1 config; o runtime só chama |
| **consertar um cálculo** | achar dentro de uma função de 300 linhas | 1 função pequena em `domain/`, com teste e rede |

---

## Como migrar SEM quebrar (o método, já provado hoje)

Cada peça se move assim (foi o que fiz no `state_team` e no `hier_calibration`):

1. **Rede de equivalência primeiro** — golden da saída com dados reais.
2. **Mover** a peça para o lugar certo (novo módulo/pasta).
3. **Re-exportar** no lugar antigo → importadores não percebem.
4. **Provar idêntico** (golden + suíte + emulador). Só então commit.

Nunca movemos o que não temos como provar. O modelo no ar nunca vê a diferença.

---

## Ordem sugerida (risco↑, do mais seguro ao mais delicado)

1. **Config / fonte única** *(começar aqui — maior alívio, menor risco)*
   Consolidar o registro de mercados/linhas/limiares em `config/`. Ataca DIRETO
   sua dor de "adicionar mercado". Já temos o padrão (`STATS_MARKET_CONFIG`).
2. **Estado** → `state/`: juntar as chaves de `session_state`, params, persist
   sob um dono claro. (Mata a família do incidente do fit.)
3. **Domínio** → `domain/`: mover a matemática/regras puras (muitas já em
   `mlcore` e nos `_core`); dar a cada uma teste próprio.
4. **UI** → `ui/`: as 40 `tab_core`/`ui_core` viram uma pasta com interface de
   aba comum. Aqui você valida visualmente cada uma.
5. **A espinha (`plays_app` + `globals→ctx`)** *(por último, o mais delicado)*:
   trocar a reflexão por um contexto explícito e tipado. É o trabalho longo, e
   o que exige você validando cada tela.

**Prazo honesto:** o passo 1 começa e rende hoje. Os passos 4-5 são um arco de
algumas sessões. Mas a partir do momento que o mapa existe, cada adição futura
já tem destino — o alívio começa antes da migração terminar.

---

## O que fica decidido quando você aprovar este mapa

- As 5 sub-camadas de `app_core` e a direção das setas.
- O nome/lugar de cada pasta (`config/`, `state/`, `domain/`, `runtime/`, `ui/`).
- A ordem de migração (config → estado → domínio → ui → espinha).
- A regra: nada se move sem rede provando idêntico.

Reaja em cima: o que está certo, o que você quer diferente, e por onde começar.

---

## STATUS (atualizado 21/07, sessão autônoma)

**Passo 1 (config / fonte única) — FEITO na parte segura:**
- ✅ **Mercados** são fonte única de verdade. Eliminada a última cópia escondida
  (`FRIENDLY_MARKET_CONFIG` no perfil do oponente, que tinha Dragões/Barões à
  mão). Varredura do código inteiro confirmou: nenhuma outra cópia. Adicionar/
  remover mercado = **1 lugar** (`STATS_MARKET_CONFIG`). Commit b2019e6.
- ✅ **Limiares** (`sc_th_*`) derivam do registro (eram literais em app_state).
  Commit 68735eb.
- ✅ Dedup real: `_node_base_stats` comum entre `_node_stats`/`_pair_stats` no
  hier_calibration. Commit 35d3cf8.

**Onde parei e POR QUÊ (o que precisa de VOCÊ):**
- Os outros "duplicados" (`_safe_logit`, `_safe_sigmoid`, `_norm_team_key` em
  2-3 lugares) são **VARIANTES**, não cópias — assinaturas/corpos diferentes.
  Consolidá-los mudaria comportamento (ex.: o matching de time do `resumo`
  trata mojibake, os outros não). **Precisa da sua decisão** sobre qual é a
  canônica antes de unificar. Não mexi.
- **Passos 2-5** (estado, domínio, UI, espinha `plays_app`): os que sobram de
  peso são UI e a espinha `globals→ctx`. A prova deles é **visual, sua** — o
  E2E prova o caminho feliz, mas quem pega o problema é você clicando (lição do
  microseg). **Esperam por você.**

**Próximo passo quando você voltar:** decidir a canônica dos helpers-variante
(rápido) e/ou começar o passo 2 (estado) OU o fatiamento de UI com validação
visual. A base já está bem mais arrumada: adicionar mercado/limiar não dói mais.
