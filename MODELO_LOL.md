# O MODELO DO LoL, PEÇA POR PEÇA — inventário com nota

Escrito em 27/08/2026, antes de trocar de máquina (i7-3770 + 16 GB DDR3 →
5700X + 32 GB DDR4). Só LoL. O Dota fica para depois.

## Para que serve este arquivo

É a fila de trabalho. Cada linha da tabela é uma peça do modelo, e a nota diz
**o quanto se SABE que aquela peça presta** — não o quanto ela é boa. São coisas
diferentes, e confundir as duas é como a nota do projeto virou ficção antes.

A ordem de ataque sai da tabela: peça que **custa** vem antes de peça que
**nunca foi medida**, que vem antes de peça que já **paga**.

## Como o formato foi escolhido (pesquisa, 27/08)

O artefato padrão para documentar um modelo é o **cartão de modelo** (Mitchell
et al., 2019), e a saída operacional para dizer quais componentes "merecem o
lugar que ocupam" é a **matriz de ablação**: remove-se um componente por vez e
compara-se com a linha de base, para raciocinar sobre a contribuição individual
de cada um. É exatamente isso abaixo.
Fontes: https://www.researchgate.net/publication/330268857_Model_Cards_for_Model_Reporting
e https://medium.com/@adnanmasood/ablation-studies-the-operating-system-for-trustworthy-ai-decisions-b99300d3bd32

## A régua da nota (para você poder conferir, e discordar)

A nota é de **evidência**, de 0 a 10, e sai de uma regra fixa — não do meu
julgamento:

| Nota | Quando |
|---|---|
| **10** | Medida em teste CEGO, com intervalo de confiança, e re-medida nos últimos 90 dias |
| **8** | Medida em teste cego com intervalo, mas a medição tem mais de 90 dias |
| **5** | Medida uma vez só, sem intervalo de confiança **ou** sem teste cego separado |
| **3** | Só existe indício indireto: a peça entra numa nota agregada, nunca foi isolada |
| **0** | **Nunca medida isoladamente.** Não se pode afirmar nada sobre ela |

E o **efeito** é o número medido de verdade, em logloss (menor é melhor), com a
barra de aceite da casa para comparação: a casa só aceita ganho **> 0,002 com
p < 0,05 e limite inferior do intervalo acima de zero** — as três coisas juntas.

---

## ACHADO QUE MUDA A ORDEM DE TUDO — **SUPERADO em 08/09/2026**

> **Este bloco continua aqui de propósito.** A prática de registro de decisão é
> log **append-only**: "não volte para editar registros aceitos; se uma decisão
> muda, escreva um novo registro que supersede o original e ligue os dois —
> isso preserva o histórico do seu raciocínio e deixa claro quando e por que a
> direção mudou". E: "evite esconder consequências, intencionalmente ou por
> acidente".
> https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record
> (conferida abrindo a página em 08/09/2026)
>
> Apagar a tabela abaixo tiraria a chance de alguém entender **por que** a fila
> apontava para o lado errado. Ela fica; a correção vem depois dela.

### A MEDIÇÃO NOVA (08/09/2026) — é esta que vale

A ablação de 27/08 mediu uma cadeia que **o app não roda**, sobre um modelo
**velho**. Duas causas, ambas já corrigidas:

- **dívida D8:** a cadeia do replay ligava o microssegmento da fusão e o Platt
  da fusão por default, e esses dois estágios **nunca são executados no app** —
  dependem de callbacks que o caminho servido não injeta.
- **dívida D9:** o cache do replay não vencia, e o modelo usado era de 26/08
  enquanto o robô atualizava todo dia.

Refeita contra o caminho **realmente servido**, em **6.002 jogos**:

| Variante | logloss | efeito |
|---|---|---|
| caminho completo (o que é servido hoje) | 0,58464 | — |
| sem o microssegmento **da fusão** | 0,58464 | **0,00000 — não roda** |
| sem o Platt **da fusão** | 0,58464 | **0,00000 — não roda** |
| sem o microssegmento do time | 0,58533 | piora 0,00069 (paga pouco) |
| **sem o Platt do time** | **0,58289** | **melhora 0,00175 (este CUSTA)** |
| sem a camada de jogadores | 0,59451 | piora 0,00987 (**esta paga muito**) |

**O que mudou, ponto a ponto:**

1. **Os dois estágios que a fila mandava remover valem ZERO EXATO** — porque
   não rodam. Não há o que tirar; o ganho já estava embolsado sem ninguém
   saber. A frente "tirar o que custa" **deixou de existir**.

2. **O Platt do time INVERTEU de sinal.** A tabela antiga dizia "piora 0,00204
   — **este paga**". Agora remover **melhora 0,00175**: ele passou a custar.
   **Ainda assim não é para mexer**: 0,00175 fica **abaixo da barra da casa**
   (ganho > 0,002). É o único candidato vivo da lista, e não passa. Confiança
   baixa — vale re-medir antes de agir.

3. **A camada de jogadores é o maior efeito medido** (+0,00987) e continua
   paga. Isso ganhou importância: a régua oficial **não a inclui** (dívida D5),
   então a nota que você lê subestima o modelo.

**Consequência para a fila:** a premissa de que "a primeira frente é tirar o que
custa" caiu. Não há remoção com ganho acima da barra. O que sobrou de maior
valor é **fazer a nota oficial medir o que a tela mostra** (D5), porque hoje ela
mede o Elo sozinho.

**Nota sobre o calibrador com grupo:** ele está ligado e, desde 08/09, é
**aplicado de verdade** na tela — até então vivia dentro de um ramo
(`use_lineup`) que vem desligado por padrão, e o ganho medido não chegava ao
usuário. Ver a frente 0 no `RETOMAR.md`.

---

### A medição antiga (27/08/2026) — SUPERADA, mantida para histórico


A ablação de 27/08, em **5.525 jogos de teste**, diz que **três estágios de
calibração do caminho servido estão CUSTANDO**, não pagando:

| Variante | logloss | efeito |
|---|---|---|
| caminho completo (o que é servido hoje) | 0,58577 | — |
| **sem o Platt da fusão** | **0,58142** | **melhora 0,00435** |
| sem o microssegmento do time | 0,58461 | melhora 0,00116 |
| sem o microssegmento da fusão | 0,58505 | melhora 0,00072 |
| sem o Platt do time | 0,58781 | piora 0,00204 (**este paga**) |
| sem a camada de jogadores | 0,59221 | piora 0,00644 (**esta paga muito**) |

O Platt da fusão sozinho custa **o dobro** do que a barra da casa exige para
aceitar qualquer coisa. E ele foi **aceito** um dia: o comentário em
`app_core/ml_settings_runtime_core.py` registra a decisão, medida em 2.827 jogos
de abril-maio, com ganho de +0,218pp e intervalo [+0,034, +0,381], p=0,008.

**Ou seja: uma medição menor e mais antiga aprovou algo que uma medição maior e
mais recente reprova.** Não é contradição de dado, é o efeito de janela — a
composição dos jogos muda ao longo do ano (BO1 de fase regular sai de 36,8% para
49,7% do volume). Isto é o mesmo mecanismo por trás do calibrador com grupo, que
mede **+0,02296** exatamente por substituir esse estágio.

~~**Consequência prática:** a primeira frente não é acrescentar nada. É *tirar*
o que custa e pôr no lugar o que já foi medido.~~
**(SUPERADA: os dois estágios que ela mandava tirar não rodam. Ver acima.)**

**RESSALVA, e ela importa.** Esta ablação roda sobre uma *reconstrução* do
caminho servido (`mlcore/replay_pre_jogo.py`), não sobre o app rodando. A própria
auditoria mede a distância entre os dois: **3,69 pontos percentuais de
divergência média** (logloss da reconstrução 0,58753 contra 0,58577 do servido).
A causa é que o caminho servido não é função pura.

Então o número está confiável o bastante para **decidir a ordem do trabalho**,
mas **não** o bastante para arrancar três estágios do que está no ar sem
confirmar. A confirmação é a sombra: rodar as duas versões em 100% do tráfego
real e comparar a distribuição de saída, antes de trocar o que você vê.
Se a sombra não reproduzir a ablação, o problema é a reconstrução — e aí a
frente vira essa, porque significa que nenhuma medição de pré-jogo vale.

---

## ONDE O MODELO MENTE (medido, 5.525 jogos)

O teste de Spiegelhalter por grupo, com correção para testes múltiplos, aponta
que a previsão está **sistematicamente errada** em fatias grandes:

| Grupo | n | previsto | aconteceu | erro |
|---|---|---|---|---|
| **formato BO1** | 2.783 | 54,15% | **59,94%** | −5,8 pp (z = −14,4) |
| **favorito 60–80%** | 1.691 | 68,78% | **75,69%** | −6,9 pp (z = −6,6) |
| **azarão 20–40%** | 994 | 31,86% | **24,85%** | +7,0 pp (z = −4,9) |
| fase regular | 4.448 | 54,19% | 55,17% | −1,0 pp |
| BO5 | 348 | 52,56% | 49,43% | +3,1 pp |

Leitura direta: **o modelo é subconfiante.** Quando ele diz "favorito de 69%",
o favorito ganha 76%. Isso vale dinheiro na direção óbvia, e é o que o
calibrador com grupo corrige.

---

## A TABELA — as peças

### A. Força de time (o núcleo)

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 1 | Rating do time (WHR) | `mlcore/whr_core.py`, `elo.py` | 3 | — | Só entra na nota agregada (9,08). Nunca isolado contra alternativa |
| 2 | Força de liga / SOS | `mlcore/league_sos.py` | 5 | validado, sem IC registrado | LIGADO |
| 3 | Transferência entre ligas | `mlcore/league_transfer_*.py` | 3 | — | LIGADO, nunca isolado |
| 4 | Forma recente | `mlcore/fit_form_core.py` | 3 | — | LIGADO, nunca isolado |
| 5 | Tiers de liga | `mlcore/tiers.py` | 0 | — | **Nunca medido** |
| 6 | Identidade de time | `mlcore/identity_registry_core.py` | 5 | 61 times perdiam histórico | Bug corrigido 24/07, sem medida do ganho |
| 7 | Continuidade de elenco | `mlcore/roster_signal_core.py` | 3 | — | LIGADO, nunca isolado |
| 8 | Snapshot de patch | `params_fitted.json` | 0 | — | **Nunca medido** |

### B. Jogadores

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 9 | **Camada de jogadores** | `mlcore/players_layer.py` | **10** | **paga 0,00644** (ablação 27/08) | LIGADA. A peça que mais paga |
| 10 | Contexto de jogadores | `mlcore/players_context_core.py` | 5 | — | **DESLIGADO à força** no runtime; os parâmetros existem ajustados |
| 11 | Pesos por rota | `params_fitted.json` | 0 | — | **Nunca medido** |
| 12 | Pesos por liga | `params_fitted.json` | 0 | — | **Nunca medido** |
| — | (nota do produto da fase Players) | `evidence/players_scorecard.json` | 8 | ganho 0,00892, cobertura 75,2% | Medida em 16/08 |

### C. Fusão e calibração ← **onde está o dinheiro**

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 13 | Fusão time+jogadores | `mlcore/fusion_core.py` | 3 | — | LIGADA, nunca isolada |
| 14 | **Platt do time** | `mlcore/calibration.py` | **10** | **paga 0,00204** | LIGADO, corretamente |
| 15 | **Microssegmento do time** | `app_core/postfusion_calibration_core.py` | **10** | **CUSTA 0,00116** | LIGADO — **tirar** |
| 16 | **Microssegmento da fusão** | idem | **10** | **CUSTA 0,00072** | LIGADO — **tirar** |
| 17 | **Platt da fusão** | idem | **10** | **CUSTA 0,00435** | LIGADO — **tirar. É o pior de todos** |
| 18 | Calibração hierárquica | `ml_microseg_hierarchical` | 3 | — | LIGADA, nunca isolada |
| 19 | **Calibrador com grupo (formato+fase)** | `tools/ajustar_calibrador_grupo.py` | **10** | **paga 0,02296**, IC [+0,01800, +0,02778]; z vai de −9,09 para −2,94 | **CONSTRUÍDO E DESLIGADO** — ninguém o chama |
| 20 | Calibração pós-fusão (o conjunto) | `ml_postfusion_cal_enabled` | 8 | +0,00218 em 2.827 jogos (abr-mai) | **Aceito por medida que a de 27/08 contradiz** |

### D. Governadores e guardas

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 21 | Governador de confiança | `ml_confidence_governor_*` | 0 | — | LIGADO por padrão, **nunca medido** |
| 22 | Incerteza | `ml_uncertainty_enabled` | 8 | **0 de 7 configurações** bateram a base (pior −0,38pp) | DESLIGADO, corretamente |
| 23 | Confiança marginal | `ml_marginal_trust_enabled` | 8 | **0 de 21 configurações** bateram a base (pior −3,34pp) | DESLIGADO, corretamente |
| 24 | Coerência de série | `ml_series_coherence_post_*` | 0 | — | LIGADO, **nunca medido** |
| 25 | Guardrail do resumo | `resumo_guardrail_*` | 0 | — | LIGADO, **nunca medido** |

### E. Série / melhor-de-N

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 26 | Gamma de série por liga/macro | `series_gamma_*` | 3 | — | LIGADO, nunca isolado |
| 27 | BO / DP-lite | `series_bo_dplite_tuning` | 3 | — | LIGADO, nunca isolado |

### F. Estilo e meta

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 28 | Estilo de confronto (B) | `mlcore/style_matchup_core.py` | 8 | −0,0004 de logloss | DESLIGADO, corretamente (era a causa da assimetria na troca de odd) |
| 29 | Meta blend (C) | `mlcore/meta_blend_core.py` | 8 | −0,0004 de logloss | DESLIGADO, corretamente |
| 30 | Draft | (código pronto, não ligado) | 8 | REJECT no gate, reconfirmado | Não entra. Lição: base fraca dá ACCEPT falso |

### G. Ao vivo

| # | Peça | Onde | Nota | Efeito medido | Estado |
|---|---|---|---|---|---|
| 31 | **Estado → vitória @10/15/20/25** | `live_models/` (LightGBM) | **8** | **+9,87 / +14,85 / +20,94 / +29,28 pp**, todos p=0,0000 | LIGADO. Maior salto do projeto |
| 32 | Calibrar os modelos ao vivo | — | 10 | **PIORA** (medido no Dota: 15 de 15) | Não fazer |

### H. Totais

| # | Peça | Onde | Nota | Efeito medido (sobre a taxa-base) | Estado |
|---|---|---|---|---|---|
| 33 | Kills | `mlcore/lines_engine.py` | 10 | **+0,0183** | Único mercado com sinal de verdade |
| 34 | Dragões | idem | 10 | +0,0050 | Fraco |
| 35 | Torres | idem | 10 | +0,0033 | Fraco |
| 36 | Tempo | idem | 10 | +0,0022 | Na barra |
| 37 | Barões | idem | 10 | +0,0007 | **Abaixo da barra** — a nota 6,69 vinha da linha torta |
| 38 | Inibidores | idem | 10 | **−0,0013** | **Pior que chutar a taxa-base** |

### I. Treino e manutenção

| # | Peça | Onde | Nota | Efeito | Estado |
|---|---|---|---|---|---|
| 39 | Treino offline | `mlcore/train_offline.py` | 0 | — | **Sem semente aleatória**: dois treinos podem não dar o mesmo resultado |
| 40 | Atualização incremental | `mlcore/update_incremental.py` | 3 | — | Nunca medida contra o treino cheio |
| 41 | Validação de camada | `mlcore/layer_validation.py` | 3 | — | Existe, nunca auditada |
| 42 | Walkforward | `mlcore/walkforward_report.py` | 5 | — | Roda, mas não em esteira |
| 43 | Fixtures de regressão | `mlcore/regression_fixtures.py` | 5 | — | Roda em `retreino.yml` |

---

## O PLACAR

| | quantas peças |
|---|---|
| Nota **10** (medida em teste cego, recente, com intervalo) | 13 |
| Nota **8** (medida com intervalo, mas velha) | 7 |
| Nota **5** (medida uma vez, sem rigor) | 5 |
| Nota **3** (só indício indireto) | 10 |
| Nota **0** (**nunca medida**) | 8 |

**De 43 peças, 18 (42%) nunca foram medidas isoladamente ou só aparecem numa
nota agregada.** Oito delas estão **ligadas por padrão** sem que ninguém saiba
se ajudam.

As notas agregadas que já existem, para contraste:

| Régua | Nota | Medida em |
|---|---|---|
| Fusão (vencedor do mapa) | 9,08 | 16/08 |
| Nota por liga (geral) | 8,48 | 27/08 |
| Produto (8 fases) | 8,69 (teto 9,03) | 16/08 |
| Ao vivo | 8,89 | 16/08 |
| Jogadores | 8,64 | 16/08 |
| Totais | 6,12 | 26/08 |
| **Régua das 28 (confiabilidade do sistema)** | **2,5** | 27/08 |

A nota geral de 8,48 esconde o espalhamento por liga: **LPLOL 4,95**, NACL 6,01,
LPL 6,38, LCKC 6,94 contra LJL, ROL e TCL em 10,0. A geral engana.

---

## A ORDEM DAS FRENTES, que sai da tabela

**F1 — Tirar o que custa e ligar o que paga (calibração do pré-jogo).**
Remover Platt da fusão + os dois microssegmentos (custam 0,00623 somados) e ligar
o calibrador com grupo (paga 0,02296). É a maior alavanca isolada do projeto e
está tudo medido. Sombra antes de servir; a inclinação global é 1,296, então os
números **vão** mudar.

**F2 — Medir as 8 peças que estão ligadas e nunca foram medidas.**
Governador de confiança, coerência de série, guardrail do resumo, tiers, snapshot
de patch, pesos por rota, pesos por liga, treino sem semente. Cada uma pode estar
custando como o Platt da fusão custava — e ninguém saberia.

**F3 — Tirar os totais que não pagam.** Inibidores é pior que a taxa-base;
barões está abaixo da barra. Servir número pior que chutar é pior que não servir.

**F4 — As ligas ruins.** LPLOL a 4,95 com 132 jogos. Ou melhora, ou a tela avisa
que ali o modelo não sabe.

**F5 — Isolar o núcleo.** WHR, fusão, forma, transferência entre ligas: nota 3,
nunca separadas. É o coração e é o que menos se sabe.

**F6 — Semente no treino.** Sem ela, nenhuma medição das anteriores é
reproduzível de verdade.

---

## A REGRA DE TRABALHO (a sua, escrita para não se perder)

Para **cada** frente, nesta ordem:

1. **Não sugerir ideia antes de procurar.** Ir à internet e ver se aquilo já
   existe, como se faz, e se já se sabe que é bom (copiar) ou ruim (nem começar).
2. Só então formar a minha ideia, misturando com o que a pesquisa trouxe.
3. Implementar.
4. **Procurar de novo** depois de implementado.
5. Dúvida no meio → **procurar**. "Eu acho que assim é melhor" → **procurar**.
6. **A fonte fica escrita no arquivo**, em bloco FONTES. Pesquisa que não ficou
   escrita conta como pesquisa que não aconteceu, porque ninguém pode conferir.
7. **Tudo testado.** Só passa o que for medidamente melhor, sem exceção. Teste
   cego separado, intervalo de confiança, e a barra da casa: ganho > 0,002,
   p < 0,05, limite inferior do intervalo acima de zero — as três juntas.
8. Não tem problema o modelo ficar quebrado por um tempo. Tem problema ele ficar
   bom por sorte.

**Fora do plano: CLV.** Consequência aceita: dá para provar que o modelo
**acerta**, nunca que **ganha dinheiro**. "Melhorou" só pode significar
"prevê melhor".

---

## Onde este arquivo mora, e onde estão os dados (corrigido em 08/09/2026)

Este documento foi escrito em 27/08 **dentro da pasta de backup**, e a seção
que ficava aqui descrevia aquele layout. Ele agora vive **no repositório**:

```
C:\Gabinetes\gabinetelolweb3.1\MODELO_LOL.md      <- este arquivo
C:\Gabinetes\GabineteDOTA\                        <- o Dota
```

Caminho **sem acento** de propósito: com o repositório em
`...\Área de Trabalho\...` o LightGBM não abre modelo ao vivo nenhum. Ver a
armadilha no `CLAUDE.md`.

**Os dados vêm no `git clone`** — `ml_artifact.json`, `params_fitted.json`,
`players_artifact.json`, `CSV_HISTORICO/`, `CSV_DIARIO/`, `live_models/` e
`evidence/` estão versionados. O passo a passo está no `SETUP.md`, que a partir
de 08/09 tem teste conferindo cada uma dessas afirmações.

**A exceção continua sendo `ops/baselines/`** (~68 MB): são os retratos para
onde `tools/rollback_baseline.py` volta, não estão no git, e sem eles acaba a
capacidade de reverter um modelo ruim. A cópia de 27/08 segue em
`GABINETE_BACKUP\LOL\opsaselines\`, no OneDrive.

**Consequência de os projetos terem saído do OneDrive:** baseline nova criada
daqui em diante **não tem cópia em lugar nenhum**. Decidir uma estratégia de
backup é assunto aberto — está registrado no `RETOMAR.md`.
