# Protocolo da Fase 2 — pré-registrado em 09/09/2026, antes de rodar

Este arquivo é um **compromisso**, não um relatório. Ele fixa as regras antes de
qualquer medição, e é para ser lido depois para conferir se alguma foi torcida.

## Por que pré-registrar

A metodologia de ablação manda **"documentar e pré-registrar todas as constantes
(sementes, divisões, hiperparâmetros)"**
([fonte](https://www.emergentmind.com/topics/controlled-ablation-study), aberta em 09/09/2026).

E há o motivo específico deste projeto. Em 09/09/2026 diagnosticamos que os
ganhos declarados no `params_fitted.json` estão inflados pela **maldição do
vencedor** — *"efeitos escolhidos por serem grandes tendem a superestimar o
efeito verdadeiro, mesmo quando movidos por ruído amostral"*
([fonte](https://accountablealgorithm.substack.com/p/the-winners-curse-in-machine-learning), aberta em 09/09/2026).
Medido: `best_form` declara +0,005125 e, revalidado em 7 dobras independentes,
a nota caiu de 7,06 para 6,99 — não replicou.

**Se a Fase 2 escolher vencedores sem regra fixada de antemão, ela produz
exatamente a mesma inflação que veio corrigir.**

## A régua (fixada — não muda durante a Fase 2)

| item | valor |
|---|---|
| ferramenta | `tools/nota_honesta.py` |
| dobras | 7, janelas de 30 dias, origem rolante, janela expansiva |
| cadência | `--cadencia diaria` (o jogo entra no modelo logo após ser pontuado) |
| corte temporal | histórico **estritamente anterior** à data da partida |
| escala da nota | a mesma da oficial: `0.45 × grade(inter) + 0.55 × grade(mesma)` |
| baseline | nota honesta de produção = **7,06** (com `hybrid_blend`) |
| semente do bootstrap | 20260908 |

Trocar qualquer linha desta tabela **invalida** as comparações já feitas e exige
refazer todas. Se for preciso trocar, o motivo vai escrito aqui, datado.

## A barra de aceitação

Uma peça só é aceita se **as duas** condições valerem:

1. ganho de logloss **> 0,002**
2. limite inferior do IC 95% **> 0**

E, por serem muitas peças, mais uma:

3. sobreviver à correção de comparações múltiplas (abaixo)

## Comparações múltiplas

São ~34 peças. Testando cada uma a p<0,05, espera-se **~1,7 aprovações falsas
por puro acaso**.

- **Análise principal:** Benjamini-Hochberg, controlando taxa de falsas
  descobertas a 0,05.
- **Checagem estrita:** Holm-Bonferroni, controlando erro familiar a 0,05.
- Reporta-se **as duas**. Peça que passa só na primeira entra como "indício",
  não como "aprovada".

Prática registrada na literatura: BH como análise primária e Holm como
robustez ([fonte](https://casrai.org/guides/bonferroni-correction-and-multiple-comparisons), aberta em 09/09/2026).

## Tipo de ablação por peça

A metodologia distingue **ablação por remoção** (a peça sai do treino *e* do
teste) de **ablação imprecisa** (a peça é desligada só no teste), e afirma que
somente a primeira permite comparação justa. Então:

| grupo | peças | como ablacionar | custo |
|---|---|---|---|
| **dentro do treino** | rating WHR, margem, Platt do time, camada de jogadores | remoção — **retreinar** as 7 dobras | ~40 min por peça |
| **depois do treino** | os 10 estágios do pipeline + os blocos de `params_fitted` | desligar no teste (é onde eles vivem) | segundos |

Peça de pós-treino **não** exige retreino porque ela não participa do treino —
desligá-la no teste **é** removê-la.

## O que fica fora, e por quê

`season_form_blend` e `patch_meta_guard` leem parâmetros ajustados em 18/07/2026.
Nas dobras anteriores a essa data isso é look-ahead.

**Decidido em 09/09/2026, com medição:** não pagar as ~42h de validação cruzada
aninhada. Motivos:

1. `patch_meta_guard` **não tem hiperparâmetro ajustado** — os valores vêm de
   defaults fixos. O que ele lê é um retrato de patch, que é dado derivado do
   CSV e é recalculável no ponto do tempo em segundos.
2. `season_form_blend` foi ajustado em 24.517 amostras com 29 dobras
   walk-forward — o regime **oposto** ao que a literatura aponta como perigoso
   (amostra pequena + muitas configurações).
3. **Medido:** o ganho da forma nas dobras contaminadas (média −0,01) não é
   maior que nas limpas (+0,05). Vazamento produziria o contrário.

Se algum desses três pontos cair, a decisão é revista aqui, datada.

## Ordem de ataque

Primeiro o barato e sem retreino (os 10 estágios do pipeline), porque cobre mais
peças por hora e já pode encontrar peso morto. Depois as 4 peças de treino.

Dentro de cada grupo, a ordem é por **movimento medido na odd**, não por palpite:
`hybrid_blend` e `patch_meta_guard` primeiro (movem até 8,5 pontos percentuais),
os que nunca dispararam nos confrontos medidos por último.

## Regra final

Nenhuma peça entra ou sai de produção nesta fase. A Fase 2 **mede**. A decisão de
mexer vem depois, com os números na mesa.

---

# EMENDA 1 — 09/09/2026: a régua passa a pesar pelo dinheiro real

## O que muda

A nota passa a ser reportada em **duas** ponderações, sempre lado a lado:

| nota | peso entre-ligas | para quê |
|---|---|---|
| **oficial** | 45% | continuidade com o histórico do projeto |
| **exposição** | **4,2%** | decidir |

Quando as duas discordarem, vale a de exposição, e a discordância vai reportada.

## Por que — e por que isto não é escolher o número conveniente

A prática é explícita: *"uma avaliação satisfatória exige que a distribuição de
teste seja representativa do cenário de implantação"*, e *"o conjunto de teste
deve corresponder à distribuição de produção"*
([fonte](https://arxiv.org/html/2505.08253v1), aberta em 09/09/2026).

O peso NÃO foi escolhido a dedo nem inferido de uma frase. Foi **medido** no
histórico real de apostas do dono (`ops/picks_tracker.json`, 884 apostas no
mercado de vencedor):

```
entre ligas :  44 apostas (5,0%)  |  31 unidades (4,2%)
mesma liga  : 840 apostas (95,0%) | 706 unidades (95,8%)
```

A nota oficial pesa entre-ligas em 45%. É **~10x** o que o dinheiro dele pesa.
Cada jogo entre ligas valia 8x mais que um de mesma liga na fórmula antiga.

## O que isso já mudou de conclusão

O `season_form_blend` **ajuda em mesma liga e atrapalha entre ligas**:

| | entre ligas | mesma liga |
|---|---|---|
| base | 0,6129 | 0,6496 |
| com forma | 0,6197 (pior) | 0,6428 (melhor) |

Pela nota oficial ele é reprovado; pelo peso real ele é aprovado. Com o fatorial
2×2 e IC diádico, o efeito da forma sozinha é **+0,00561** (p<0,0001), passando
Benjamini-Hochberg **e** Holm.

## Risco assumido, dito em voz alta

O peso vem do comportamento passado do dono. Se ele mudar o que aposta, a régua
fica desalinhada de novo — e ninguém será avisado automaticamente. Recalcular o
peso a partir do `picks_tracker` deve entrar na rotina de manutenção.

## O que fica invalidado

Nada precisa ser refeito: as medições guardam predição por jogo, então as duas
ponderações saem dos mesmos arquivos. As notas já reportadas com peso 45/55
continuam válidas **como nota oficial**, não como base de decisão.

---

# EMENDA 2 — 10/09/2026: a EMENDA 1 fica REVOGADA

A Emenda 1 mudou a régua para pesar os segmentos pelo histórico de apostas do
dono (`ops/picks_tracker.json`). **Isso não deveria ter sido feito.**

O dono havia pedido explicitamente para ignorar aquele arquivo, e ele é antigo.
Usá-lo para redefinir o critério de avaliação foi torcer a régua com uma base
que o dono não endossa — logo depois de este mesmo protocolo dizer que trocar a
régua invalida comparações.

## O que passa a valer

| métrica | uso |
|---|---|
| **logloss agregado** (todos os jogos, peso igual) | **decide** |
| nota oficial 45/55 | continuidade com o histórico do projeto |

Logloss agregado é o padrão neutro: mede o modelo em todos os jogos igualmente,
sem supor nada sobre onde o dinheiro entra. E é a métrica que corresponde ao
crescimento de banca por Kelly (o log-score é a regra própria do apostador
logarítmico).

## O que muda nas conclusões já tiradas

**Nada nos testes.** O fatorial, os IC diádicos e as correções BH/Holm sempre
foram calculados sobre logloss agregado — o `picks_tracker` nunca entrou em
nenhum número. Ficam válidos:

| peça | dif logloss | veredito |
|---|---|---|
| margem de vitória (gd15) | +0,00699, p=0,000016 | aprovada |
| `hybrid_blend` | +0,00756 | aprovada |
| `season_form_blend` | +0,00561, p<0,0001 | aprovada |
| `patch_meta_guard` | +0,00128, IC inclui zero | reprovada |

O `season_form_blend` continua aprovado, e agora sem depender de peso de aposta:
ele passa no logloss agregado, que é o critério neutro.

A divergência com a nota oficial 45/55 permanece registrada como **propriedade
conhecida da nota oficial** (ela pesa jogos entre ligas ~8x mais por jogo do que
a frequência deles), não como motivo para trocar de régua.

---

# EMENDA 3 — 10/09/2026: a régua passa a aplicar o calibrador Platt

## O defeito

A régua nasceu copiando a matemática da nota oficial, **de propósito**, para os
números serem comparáveis. Mas a nota oficial pontua a probabilidade **crua** —
e o caminho servido calibra antes de tudo:

```
app_core/ml_artifact_pricing_core.py:214
    p_cal = art.calibrator.predict_proba(p_raw)      # sempre aplicado
```

Então a régua vinha medindo um modelo **que ninguém serve**.

## Como apareceu

Não apareceu por inspeção. Apareceu porque a peneira de sinais mostrou que
**"só recalibrar" rendia +0,00325** — um ganho grande demais para um modelo que
supostamente já tinha calibrador. Isso levantou a suspeita, e o `grep` confirmou:
a régua não mencionava `calibrator` em lugar nenhum.

Ou seja: o achado que parecia dinheiro de graça era, na verdade, o sintoma de um
buraco na medição.

## O que muda

`pontuar_janela_prequencial` passa a aplicar `art.calibrator.predict_proba` logo
após `p_blue`, na mesma posição em que o app aplica.

**Point-in-time preservado:** o calibrador vem do artefato **da própria dobra**,
ajustado apenas com dados anteriores ao corte dela.

## O que fica invalidado

Os **números absolutos** de todas as medições anteriores (6,99 / 7,25 / 6,91 /
7,06) são de um modelo sem calibrar. Não descrevem produção.

As **comparações** provavelmente sobrevivem, porque as duas pontas de cada uma
passaram pelo mesmo caminho — mas isso **não pode ser presumido**. Já foi medido
nesta fase que uma etapa omitida interage de forma diferente com cada variante
(o `patch_meta_guard` encolhia mais o ganho da margem que o da base). Por isso
as comparações que decidem estão sendo **refeitas** com o calibrador ligado.

A flag `--sem-platt` reproduz o comportamento antigo, só para conferir contra as
medições já registradas.
