# Fase 0 — Pesquisa

**Feature**: 001-ligar-margem-vitoria | **Data**: 2026-09-11

Um desconhecido foi levantado no plano. Ele foi resolvido, e a investigação
revelou um risco que não estava no radar.

---

## NEEDS CLARIFICATION resolvido

> *Quanto do ganho medido (+0,00573) se perde porque o robô aplica os jogos novos
> sem margem entre um treino completo e outro?*

**Resposta: nada. O buraco já está embutido na medição.**

A régua (`tools/nota_honesta.py`, função `pontuar_janela_prequencial`) atualiza o
modelo dentro da janela com:

```python
art.model.update(blue, red, y, blue_league=bl, red_league=rl,
                 blue_tier=bt, red_tier=rt)
```

Sem o argumento `mov`. `EloModel.update` aceita `mov` e o default é `None` — ou
seja, **a régua já atualiza sem margem, exatamente como o robô faz**.

Portanto o +0,00573 medido **já é o ganho realista** de um artefato treinado com
margem sofrendo updates incrementais sem ela. Não há desconto a aplicar.

---

## O risco que apareceu na investigação

Resolver o item acima expôs uma propriedade do sistema que ninguém tinha
examinado: **produção roda um híbrido de dois sistemas de rating diferentes.**

- a **base** vem do WHR — método *batch*, que refaz a trajetória inteira por MAP
- os **updates diários** vêm do Elo — método *incremental*

### O que a literatura diz sobre essa mistura

> *"O algoritmo Elo online ajusta o rating incrementalmente após cada partida, e a
> sequência em que as partidas são processadas afeta significativamente os
> ratings finais."*
> — [Chatbot Arena and the Elo rating system, parte 2](https://bryanyzhu.github.io/posts/2024-08-16-elo-part2/) (lido em 11/09/2026)

O WHR não tem essa propriedade: sendo um MAP sobre a história inteira, a ordem
não altera o resultado. Então os dois lados do híbrido têm garantias diferentes.

E o ponto que importa para nós:

> *"Depois que ocorre uma deriva, modelos incrementais têm dificuldade de
> convergir, ao contrário dos aprendizes batch."*
> — [Online Learning vs. Batch Retraining](https://apxml.com/courses/monitoring-managing-ml-models-production/chapter-4-automated-retraining-updates/online-learning-vs-batch) (lido em 11/09/2026)

LoL tem deriva **constante e conhecida**: patch novo a cada duas semanas, troca
de elenco entre splits. É o cenário em que o lado incremental é mais fraco.

### O dado que fecha o raciocínio

Frequência real de treino completo neste repositório (`git log` do artefato):

```
2026-08-16   Modelo REFEITO com o fix do reset de tier
2026-07-15   artifacts do modelo versionados
2026-06-02   Estado inicial
```

Aproximadamente mensal, **mas sem agenda** — os três foram disparados por evento
(um conserto, uma mudança de infraestrutura, um marco), não por rotina. O robô
só faz incremental; não existe treino completo programado.

Hoje faz **26 dias** desde o último.

### Consequência prática

O ganho de +0,00573 foi medido com janelas de 30 dias entre o treino e o fim da
medição — por sorte, próximo da cadência real. **Se um treino completo demorar
dois ou três meses, o benefício da margem decai**, porque todos os jogos daquele
período entram pelo caminho antigo, e o lado incremental é justamente o que pior
lida com patch novo.

**Quanto decai: NÃO MEDIDO.** Fica como pendência honesta.

---

## Decisões

| # | Decisão | Justificativa |
|---|---|---|
| D1 | **Não descontar** o ganho medido | O buraco do incremental já está dentro da medição, verificado no código |
| D2 | **Não levar a margem ao `update_incremental`** nesta entrega | É modelagem de verdade (o Elo tem MOVDA próprio, com outra parametrização) e merece especificação própria |
| D3 | **Registrar a dependência de cadência** como risco declarado | O ganho pressupõe treino completo ~mensal, e hoje isso depende de alguém lembrar |
| D4 | **Recomendar treino completo programado** como frente separada | Fora do escopo desta entrega, mas é o que protege o ganho ao longo do tempo |

---

## O que NÃO precisou de pesquisa

A margem em si. Mecanismo, forma matemática, escolha do sinal e parâmetros já
foram pesquisados e medidos antes desta especificação — fontes abertas e citadas
em `mlcore/whr_core.py`, `tools/eval_whr_mov.py` e `mlcore/tests/test_whr_mov.py`.

Esta fase não repetiu esse trabalho; ela cuidou apenas do que a **aplicação em
produção** trazia de novo.
