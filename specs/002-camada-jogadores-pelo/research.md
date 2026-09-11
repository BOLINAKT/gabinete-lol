# Pesquisa — camada de jogadores pelo caminho servido

**Data**: 11/09/2026 | **Feature**: 002-camada-jogadores-pelo

Todas as fontes abaixo foram **abertas**, não citadas a partir do resumo da
busca. Onde não consegui abrir, está dito que não consegui — a dívida D2 do
`RETOMAR.md` existe porque isso já foi feito errado antes.

---

## 1. O que a Fase 2 deixou medido, e por que não subiu

A camada de jogadores com pesos aprendidos por rota rendeu **+0,00346** de
logloss na régua honesta, IC 95% [+0,00243, +0,00450]. Passa na barra da casa
(> 0,002, p < 0,05, limite inferior acima de zero).

Não subiu porque **a régua aplicou o sinal por um caminho, e o app aplica por
outro**. Isso é violação do Princípio V da constituição.

### O que o app realmente faz — lido no código, não suposto

`app_core/ml_pre_engine_core.py`, linhas ~565–595:

```
logit_used  = logit(p_raw_do_time) + w_lineup * delta_eff_used
p_players   = calibrar(sigmoide(logit_used))
p_final     = fundir_por_precisao(p_team=p_map, p_players=p_players, ...)
```

**Correção de uma afirmação minha anterior.** Eu vinha dizendo que o app "não
usa deslocamento no logit, usa fusão por precisão". **Está errado, e a
diferença importa.** O app faz as *duas* coisas: desloca o logit exatamente
como a régua fez, e **depois** encolhe o resultado de volta na direção da
probabilidade só-de-time, com peso de precisão (variância inversa), com trava
de coerência.

Consequência prática: o **+0,00346 é um teto, não a entrega**. A fusão por
precisão amortece o deslocamento. Quanto ela amortece é a pergunta central
desta spec, e é mensurável.

### Os dois portões

| portão | valor hoje | efeito |
|---|---|---|
| `use_lineup_adjust` | `False` | fecha **os dois** pontos de fusão; o trecho acima nunca executa |
| `w_lineup_used` | `0,85` | em `params_fitted.json`; é o peso do deslocamento |

**Precedente na casa para exatamente este problema:** o calibrador com grupo
vivia dentro do mesmo ramo `use_lineup` e, medido em 08/09, nunca era
alcançado — o ganho de +0,02 que o gate media não chegava à tela. A solução
adotada foi uma **aplicação de reserva** fora do ramo. O comentário está em
`ml_pre_engine_core.py` linha ~864. Esta spec deve considerar o mesmo desenho.

### Achado de higiene (não é fogo)

`params_fitted.json` grava `players_artifact` apontando para
`C:\Users\steam\Desktop\...` — caminho da **máquina antiga**, que não existe.
Conferido: `os.path.exists` dá `False`. Não quebra porque
`app_core/players_artifact_runtime_core.py` cai num fallback que resolve
`players_artifact.json` ao lado do artefato. Fica registrado como sujeira, não
como defeito.

---

## 2. PandaSkill — o desenho de referência

**PandaSkill: Player Performance and Skill Rating in Esports: Application to
League of Legends**, arXiv 2501.10049.
https://arxiv.org/html/2501.10049 (aberta em 11/09/2026)

É o artigo mais próximo do nosso problema: LoL profissional, dados de fim de
jogo, e o objetivo explícito de **avaliar jogador sem creditá-lo só por estar
no time que ganhou**.

### Estágio 1 — nota de desempenho (PScore)

> "For each role, we train a machine learning model that predicts the
> probability of a player winning the game based on their end-game
> statistics... The predicted probabilities are then transformed into
> percentiles."

**É o que eu já construí** em `NotaDeJogadorAprendida`: regressão logística por
rota, sobre estatísticas de fim de jogo padronizadas.

**Uma diferença:** eles transformam a probabilidade em **percentil**; eu uso o
logit cru. Diferença testável, custo baixo.

### Estágio 2 — nota de habilidade — ESTE É O GAP

> "In this setting, all players compete against each other. After a game, they
> are ranked based on their individual PScore and their skill ratings are
> updated based on this ranking."

Ou seja: cada partida vira um **confronto de todos contra todos entre os 10
jogadores**, ordenados pelo PScore, e a nota de habilidade é atualizada por
esse ranking.

**O que eu faço hoje é mais pobre:** média acumulada do PScore, com
encolhimento (`cumsum / (n + BETA)`). Média acumulada não sabe contra quem o
jogador jogou, não tem incerteza, e converge devagar para quem tem poucos
jogos.

### Estágio 3 — decomposição contextual/meta

> "The contextual rating represents the player's skill within their context
> (e.g., region), while the meta rating represents the skill level of the
> context itself."

Serve para região isolada não inflar nota. **Nós temos isso no nível de TIME**
(`league_sos.py`, `league_transfer_*.py`), e **não temos no nível de JOGADOR**.
Gap real.

### A validação deles é fora da amostra, e no mesmo formato da nossa régua

> "To account for the gradual changes in the rating distribution and potential
> meta shifts in the video game, we used a rolling window of one month. We
> trained a logistic regression model on one year of data and tested it on the
> subsequent month."

Isso importa: o resultado deles **não** é do tipo "prever o jogo com as
estatísticas do próprio jogo". É previsão de jogo futuro a partir de histórico,
que é o nosso caso de uso. Acurácia relatada: **64,98%** no geral, **70,07%**
entre regiões contra **64,86%** dentro da mesma região.

O detalhe inter-região ser o melhor reforça o estágio 3: é justamente onde a
correção de contexto age.

---

## 3. O que foi procurado e NÃO serve

**Action2Score** — arXiv 2207.10297, https://arxiv.org/abs/2207.10297
(aberta em 11/09/2026). Pontua a **contribuição de cada ação** com um modelo
sequencial (GRU) e uma função de perda sobre a partida do time.

Não serve para nós por um motivo de dado, não de mérito: exige o **registro de
ações** dentro da partida. Nossa fonte é Oracle's Elixir, que dá estatística de
**fim de jogo**. Sem log de ações, não há o que alimentar. Descartado.

**Role-Sensitive Analysis / métrica "Victory Contribution"** — a busca aponta
um trabalho com 10.390 partidas de 2023 e teste em 9.670 de 2024, com a métrica
VC repartida em ataque, defesa, rota e ouro, e ganho consistente sobre a base
em LR/MLP/SVM/XGB.

**NÃO PUDE ABRIR.** Tanto o SAGE (10.1177/17479541251381652) quanto o
ResearchGate devolveram **HTTP 403**. Portanto:

- **não uso isto como fonte de nada nesta spec**;
- fica registrada a suspeita, **não confirmada**, de que a "win prediction"
  deles é feita com estatísticas **da própria partida**, o que seria pós-hoc e
  não valeria para previsão pré-jogo. Não afirmo que seja — não li.

Isto está escrito porque a lição da dívida D2 é que **bloco de fontes que não
dá para conferir é pior que bloco nenhum**.

**Ressalva sobre uma citação já no código.** O bloco FONTES de
`NotaDeJogadorAprendida` cita esse mesmo trabalho do SAGE com uma frase entre
aspas sobre avaliação por rota. Como hoje não consegui abrir a página, **essa
citação passa a ser não-conferida**. Tarefa desta spec: reabrir ou rebaixar a
citação para inferência minha.

---

## 4. As três frentes candidatas que saem da pesquisa

Em ordem de (ganho esperado ÷ risco), todas mensuráveis na régua honesta:

| # | mudança | de onde vem | custo |
|---|---|---|---|
| **A** | medir pelo caminho **servido** (deslocamento no logit **+ fusão por precisão**), não só pelo deslocamento | Princípio V; leitura do código | obrigatória — sem isto nada pode subir |
| **B** | nota de habilidade por **ranking dos 10 pelo PScore**, no lugar da média acumulada | PandaSkill, estágio 2 | médio |
| **C** | decomposição **contextual/meta** por região no nível de jogador | PandaSkill, estágio 3 | médio |
| D | PScore em **percentil** em vez de logit cru | PandaSkill, estágio 1 | baixo |

**A vem primeiro e não é opcional.** Sem ela, B, C e D seriam medidos de novo
por um caminho que o app não roda, e o número voltaria a não poder subir. É
exatamente o erro que esta spec existe para não repetir.

---

## 5. Perguntas ainda em aberto

1. **Quanto a fusão por precisão amortece o +0,00346?** Não sei. É a primeira
   medição a fazer, e pode derrubar a frente inteira.
2. **Ligar `use_lineup_adjust` mexe em mais o quê?** Ele abre dois pontos de
   fusão, não um. O segundo (linha ~747) ainda não foi lido com cuidado.
3. **`w_lineup_used = 0,85` foi ajustado quando, e com qual régua?** Se foi com
   a régua velha (dentro da amostra), o valor é suspeito e talvez precise ser
   reajustado na régua honesta.
4. **A nota de jogador deve decair com o tempo?** Testado em 11/09 com
   meia-vida de 180 dias e **piorou** (7,41 → 7,31). PandaSkill não usa
   decaimento no PScore. Mantido sem decaimento.
