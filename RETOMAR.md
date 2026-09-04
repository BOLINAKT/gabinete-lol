# RETOMAR — como voltar depois de formatar o PC

Escrito em 27/08/2026, antes de o Bruno formatar a máquina. Este arquivo existe
porque **a memória da sessão do assistente mora em `C:\Users\<voce>\.claude\` e
morre com o formato.** O que não estiver aqui e empurrado para o GitHub some.

Vale para os DOIS repositórios: `gabinetelolweb3.1` (LoL, remoto
`BOLINAKT/gabinete-lol`, branch `master`) e `GabineteDOTA` (Dota, remoto
`BOLINCRVG/gabinete-dota`, branch `main`).

---

## A MUDANÇA JÁ ACONTECEU — 04/09/2026

A máquina nova está de pé e os dois projetos rodam. **Onde as pastas moram
agora:**

```
C:\Gabinetes\gabinetelolweb3.1                  <- LoL
C:\Gabinetes\GabineteDOTA                       <- Dota
C:\Gabinetes\_backup_dota_pre_move_20260904\    <- cópia do live_models do Dota
C:\Users\...\OneDrive\...\Gabinetes\GABINETE_BACKUP\   <- o backup de 27/08
```

**Elas saíram da Área de Trabalho de propósito, e isso não é arrumação.** Ler a
armadilha do acento no `CLAUDE.md`: com o repo em `...\Área de Trabalho\...` o
LightGBM não abria nenhum modelo ao vivo, e a suíte do LoL dava 14 falhas que
pareciam bug de modelo. No caminho sem acento, a suíte passa inteira. **Não
mova os projetos de volta para dentro de uma pasta com acento.**

Consequência de ter saído do OneDrive: **`ops/baselines/` não tem mais cópia na
nuvem.** A de 27/08 continua em `GABINETE_BACKUP\LOL\ops\baselines\`, então
reverter um modelo ruim ainda funciona. Mas baseline nova criada daqui em diante
está só no disco — decidir uma estratégia de backup é assunto aberto.

O que foi conferido no dia, e vale como o carimbo desta migração:

| | LoL | Dota |
|---|---|---|
| suíte | **OK, 0 falhas em 4.697** | 15 falhas + 30 erros (o conhecido) |
| régua das 28 | 2,5 (segura: MONITORAMENTO) | 2,0 (segura: INFRA + MONITORAMENTO) |
| Python | 3.13.15, venv recriado | 3.13.15, do sistema |

Duas coisas que a migração revelou e ainda estão abertas — ver dívidas D6 e D7
no fim deste arquivo.

---

## 0. ANTES DE FORMATAR — a lista curta do que copiar

Quase tudo já está no git. **Foi conferido arquivo por arquivo em 27/08**, e o
`SETUP.md` estava desatualizado dizendo o contrário (ver dívida D3 abaixo).

Está no git e volta sozinho com o `git clone`: `ml_artifact.json`,
`params_fitted.json`, `players_artifact.json`, `CSV_HISTORICO/`, `CSV_DIARIO/`,
`live_models/`, `user_team_aliases.json`, `evidence/` (as notas), e no Dota
`data.csv`, `CSV_DOTA/`, `ml_artifact.json`, `team_api_cache.json`.

**Copiar à mão, porque NÃO está no git:**

| O quê | Tamanho | Por que importa |
|---|---|---|
| `ops/baselines/` | ~68 MB | São os retratos para onde `tools/rollback_baseline.py` volta. Sem eles, **acaba a capacidade de reverter um modelo ruim.** |
| `ops/BASELINE_PROD.md` | 4 KB | Explica a estrutura das baselines. |

Não precisa copiar: `ops/full_fit_runs/` (2,0 GB) e `ops/tmp/` são saída de
treinos passados e se regeneram. `ops/backups/` (41 MB) é cópia velha do código,
que o git já guarda melhor.

**Confira antes de desligar:** `git status` limpo e `git log origin/master..HEAD`
vazio nos dois repositórios. Se aparecer commit ali, ele ainda não subiu.

---

## 1. Reconstruir o ambiente no PC novo

Python **3.13**. A 3.13.7 era a de 27/08; em 04/09/2026 subiu com a **3.13.15**
sem quebrar nenhum pacote do `requirements.txt`. Não passar para 3.14: os pinos
são de 3.13.

**Clonar em pasta SEM ACENTO no caminho** (`C:\Gabinetes\`, não a Área de
Trabalho) — ver a armadilha no `CLAUDE.md`, senão o modelo ao vivo não abre.

```
git clone https://github.com/BOLINAKT/gabinete-lol.git C:\Gabinetes\gabinetelolweb3.1
cd C:\Gabinetes\gabinetelolweb3.1
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Restaure `ops/baselines/` da cópia. Depois, os três comandos que provam que
voltou inteiro:

```
.venv\Scripts\python -m unittest discover -s mlcore\tests -p "test_*.py"
.venv\Scripts\python tools\regua_28.py
.venv\Scripts\python tools\frescor.py
```

O primeiro leva **~3,7 min** (5700X) e roda 4.697 testes. O esperado é
**`OK (skipped=3)`, sem nenhuma falha** — qualquer falha é problema novo.
A régua tem que dar **2,5**.

**Se você mover o repositório de pasta, recrie o `.venv`.** Os `.exe` do
`.venv\Scripts\` (o `streamlit.exe`, entre outros) têm o caminho antigo gravado
dentro deles e ficam mudos depois da mudança — o `python.exe` continua
funcionando, o que faz o problema passar despercebido.

No Dota é a mesma receita, trocando o remoto, e **sem `.venv` própria** (lá o
`python` do sistema é usado direto). Mas leia antes o `CLAUDE.md` de lá: a suíte
do Dota **retreina os modelos de produção**, e o número esperado (15 falhas) só
aparece com `GABINETE_VIEWER=0`.

---

## 2. Onde o projeto está — o número que importa

**A nota do modelo não mudou nada nesta rodada.** O que foi mexido foi
instrumentação: réguas que medem o projeto, não previsões.

- **Régua das 28** (ML Test Score do Google, nota = MÍNIMO das quatro áreas):
  LoL **2,5** e Dota **2,0**. Quem segura os dois é MONITORAMENTO.
- Correção importante de honestidade: até 27/08 eu reportava a nota do Dota
  como 0,5 / média 3,1. **Estava errado** — a régua resolvia a raiz do repositório
  por `parents[1]`, e como no Dota ela mora na raiz, isso apontava para a Área
  de Trabalho. Ela varria o Desktop inteiro e enxergava as ferramentas do LoL
  como se fossem do Dota. O mesmo bug existia em `livro_caixa.py` e `frescor.py`;
  os três agora usam `git rev-parse --show-toplevel`.

---

## 3. A PRÓXIMA AÇÃO, exata

**Ligar o calibrador com grupo do pré-jogo.** É a única coisa medida que muda o
número que aparece na tela, e ela está pronta e **desligada**.

- Ganho medido: **+0,02296 de logloss**, IC [+0,01800, +0,02778], replicado em
  4 de 5 cortes; o desvio de calibração (Spiegelhalter Z) vai de −9,09 para −2,94.
- Causa: o calibrador final de hoje é ajustado em temporada velha, e a
  composição dos jogos muda ao longo do ano (BO1 de fase regular sai de 36,8%
  para 49,7% do volume entre a janela de calibração e o período seguinte).
- O que existe: `tools/gate_calibrador_final.py` (mediu e escolheu),
  `tools/ajustar_calibrador_grupo.py` (produz os coeficientes),
  `app_core/postfusion_calibration_core.py::_calibrador_com_grupo` (aplica), e
  `mlcore/tests/test_postfusion_grupo.py` (4 testes, travando a paridade entre
  quem ajusta e quem aplica).
- **O que falta, e é só isto:** ninguém passa `grupo_coef` para
  `apply_postfusion_calibration`, e o bloco `postfusion_group_calibration`
  ainda **não foi gravado** em `params_fitted.json` (conferido em 27/08:
  `ajustar_calibrador_grupo.py` só rodou em modo seco). O caminho a rastrear
  é `fused_post_calibration` em `app_core/fit_runtime_core.py`.

**A pesquisa desta frente já foi feita (27/08) e mudou o plano em três pontos** —
não repita do zero, comece daqui:

1. **Sombra antes de ligar. FEITO em 04/09/2026** —
   `tools/sombra_calibrador_grupo.py`, nota em
   `evidence/sombra_calibrador_grupo.json`. Em 5.525 jogos: diferença absoluta
   média de **7,15 pp**, 64% dos jogos mexem mais de 5 pp, e **8,43% trocam de
   favorito** (466 jogos cruzam os 50%). Os jogos fora da faixa 20–80% saem de
   9,6% para 23,5% — a inclinação de 1,296 afiando, como previsto.

   **CORREÇÃO DE FONTE (04/09/2026).** A frase que estava aqui — "se o candidato
   prevê sistematicamente diferente, provavelmente é distorção de calibração ou
   numérica, mesmo que a métrica offline pareça boa" — era atribuída a
   https://resiliotech.com/blog/model-canary-releases-shadow-traffic-guide.
   A página foi aberta e **não diz isso**; o único trecho sobre sombra ali é
   "Compare the shadow outputs against the production baseline using statistical
   A/B testing methods". A afirmação forte fica **sem fonte** e não decidiu nada.
   O apoio real para o desenho da sombra está em
   https://arize.com/glossary/shadow-deployment/ e
   https://atlan.com/know/shadow-deployment-for-ml-models/ — comparar
   distribuição de saída, taxa de concordância e os casos de discordância.
2. **A janela de ajuste não pode ser chutada. FECHADO em 04/09/2026, com
   resultado NEGATIVO — o 2.500 fica.**
   Foi medido: `tools/varrer_janela_calibrador.py` varreu a janela por validação
   de origem rolante dentro da calibração, e recomendou **900 com L2=3**.
   Levado ao teste cego **uma vez**, o 900 **perdeu**:

   | | ganho | IC 95% | Z |
   |---|---|---|---|
   | calibração inteira (~2.400) | **+0,02368** | [+0,01847, +0,02866] | −2,94 |
   | janela 900 | +0,01256 | [+0,00460, +0,02006] | **+6,88** |

   O 900 troca subconfiança por superconfiança. **Causa do erro:** a varredura
   avaliava blocos de 200–400 jogos (horizonte de dias) e a produção serve cinco
   meses à frente — janela curta ajuda o horizonte próximo e não o longo. Isso é
   conhecido: Zanotti M., *On the retraining frequency of global models in retail
   demand forecasting*, arXiv:2505.00356 — https://arxiv.org/pdf/2505.00356
   (domínio diferente; é analogia com apoio, e quem prova aqui é o teste cego).

   **Correção de leitura minha:** eu disse que o "2.500" não era janela, e sim
   "usar tudo", porque a calibração tem 2.427 jogos. A mecânica está certa, a
   conclusão não: ele produz um pedaço do mesmo tamanho que o teste cego acabou
   de validar. Foi escolhido sem medir, mas o valor está certo. **Não trocar.**

   **Não varrer janela contra o teste cego** para procurar uma melhor — é o viés
   de seleção de Cawley & Talbot (JMLR 11:2079–2107, 2010,
   https://jmlr.org/papers/v11/cawley10a.html), o erro que o gate já registra
   ter cometido uma vez.

   Sobre a fonte original deste ponto: Davis SE, Greevy RA Jr, Lasko TA, Walsh CG,
   Matheny ME, *Detection of calibration drift in clinical prediction models to
   inform model updating*, J. Biomed. Inform. 112:103611 (2020) — conferida em
   04/09. Ela usa janela deslizante adaptativa para **DETECTAR** miscalibração,
   não para escolher o tamanho da janela de **AJUSTE**. Usá-la para a segunda
   coisa era extrapolação, e está marcada como tal nas ferramentas.
3. ~~**Deriva moderada pede recalibrar; deriva severa pede retreinar.**~~
   **REFORMULADO em 04/09/2026 — a fonte não sustenta, e a evidência é contra.**

   A fonte citada (https://smartdev.com/ai-model-drift-retraining-a-guide-for-ml-system-maintenance/)
   foi aberta em 04/09 e **não mapeia severidade para recalibrar vs. retreinar**.
   Ela tem uma matriz de severidade por % de degradação (verde/amarelo/laranja/
   vermelho), mas as respostas são cinco caminhos paralelos — monitorar,
   investigar, retreinar, redesenhar, reverter — escolhidos por análise de
   causa-raiz, não por severidade. E é guia prescritivo, sem experimento.

   **O que fica de pé, verificado:** recalibrar só opera sobre a ordenação que o
   modelo já produz. Um modelo que sempre chuta a taxa-base é perfeitamente
   calibrado e inútil. Então ordenação estragada não se conserta recalibrando —
   só se maquia.

   **O que a evidência diz sobre o gatilho:** ele foi testado e não venceu.
   Schnellinger EM, Yang W, Kimmel SE, *Comparison of dynamic updating strategies
   for clinical prediction models*, Diagn Progn Res 2021;5:20,
   doi:10.1186/s41512-021-00110-w — https://pmc.ncbi.nlm.nih.gov/articles/PMC8647501/
   comparou cinco estratégias, entre elas o *closed testing procedure* (o
   gatilho) e "sempre recalibrar". Conclusão lida no artigo: *"Recalibration
   strategies led to more consistent improvements and less variability over time
   compared to the other updating strategies."* Refazer o modelo só compensou
   quando as covariáveis mudam bastante, e atualizar com mais frequência foi
   melhor **independentemente** da estratégia.
   (O *closed testing* original é Vergouwe et al., Stat Med 2017;36:4529–4539 —
   **não foi aberto**: PubMed bloqueou por cookie e a Wiley devolveu 403. É
   citação de segunda mão, pela descrição do Schnellinger.)

   **Consequência para o plano:** não construir gatilho de severidade. Em vez
   dele, (a) recalibração periódica com cadência declarada — o que conversa com
   a dívida D4 — e (b) um vigia que acompanha **ordenação** e **calibração** em
   trilhas separadas, porque só uma delas o recalibrador sabe curar. O alarme
   que importa é o da ordenação: se ela cair, recalibrar é o remédio errado.
   Acompanhar AUROC ao longo do tempo é o sinal padrão, e agregado esconde
   deriva por segmento — medir por fatia.
   https://mlflow.org/articles/why-monitor-model-drift-production/

**Reverter, se der errado:** apagar a chave `postfusion_group_calibration` de
`params_fitted.json`. Sem ela, o código volta ao comportamento de hoje — isso
está travado por teste (`test_postfusion_grupo.py`).

---

## 4. As frentes, em ordem

Regra de trabalho combinada: **uma frente por vez, terminada por completo antes
de abrir a próxima**, e **pesquisar a frente antes de começar** — e pesquisar de
novo a cada problema e a cada dúvida no meio dela, com a fonte escrita no
arquivo.

| # | Frente | Estado |
|---|---|---|
| 0 | **Ligar o calibrador do pré-jogo** | **PRÓXIMA** — ver seção 3 |
| 1 | Calibração ao vivo | Dota medido: calibrar PIORA (15 de 15). Falta o LoL |
| 2 | Livro-caixa do silêncio | FEITO (`tools/livro_caixa.py`) |
| 3 | Interruptor de homem morto | FEITO (`tools/frescor.py`) |
| 4 | Régua das 28 | FEITO nos dois repos |
| 5 | Deflação por número de tentativas | não começada |
| 6 | Draft e jogadores do Dota | bloqueada por dado (60 de ~2.000 partidas com draft) |
| 7 | Testar os testes (mutation testing) | não começada |
| 8 | As outras 4 colunas do dado (volume, schema, distribuição, linhagem) | não começada |
| 9 | Anti-padrões do Sculley | não começada — o mais caro é limiar fixo: as linhas de 27,5 kills e 32,5 min nunca foram reconferidas |
| 10 | Prever a duração da partida | não começada — objetivos correlacionam 0,80–0,87 com duração e o motor prevê 0,21 |

**FORA DO PLANO: CLV.** Decisão dele, por falta de tempo. Consequência aceita:
dá para provar que o modelo **acerta**, nunca que **ganha dinheiro**. "Melhorou"
só pode significar "prevê melhor".

---

## 5. Dívidas abertas — honestas, não escondidas

**D1. Uma falha na suíte, 1 em 4.697 — NÃO REPRODUZ desde 04/09/2026.**
`test_e2e_smoke` acusava "E2E MUTOU artifacts do modelo — a suíte tem que ser
só-leitura". Sozinho ele **passa**; só falhava na suíte inteira, ou seja, algum
outro teste deixava estado que fazia o app escrever em `ml_artifact.json` /
`params_fitted.json` / `players_artifact.json` / `user_schedule_store.json`.
Nunca foi identificado qual.

Em 04/09, no caminho sem acento, a suíte rodou duas vezes e **passou inteira, e
nada foi gravado em disco** (`git status` conferido antes e depois: só os JSON
das próprias réguas mudaram). A dívida fica aberta porque **a causa continua
desconhecida** — o que se sabe é que ela não aparece hoje, não que foi
consertada.

Hipótese não confirmada, escrita para quem investigar não começar do zero: as
escritas podiam vir de um caminho de erro aberto pelo bug do acento — código
que, ao falhar em carregar um modelo, tentava regravá-lo. Combina com o Dota,
onde a suíte dispara retreino de verdade (D7). **Isto é hipótese, não medição.**

Importa para a frente 0, que grava exatamente em `params_fitted.json` — e essa
frente ficou mais segura de tocar do que estava em 27/08.

**D2. Fontes faltando em 15 arquivos.** A regra é que tudo carregue a fonte no
arquivo. Do que foi construído desde 26/08, **5 arquivos têm bloco FONTES e 15
não têm**. Em vários deles a pesquisa aconteceu de verdade (`mlcore/calibration.py`
é construído sobre Platt 1999, Kull 2017 e Guo 2017), mas não ficou escrita — o
que, pela regra, é igual a não ter pesquisado, porque ninguém consegue conferir.
Sem fonte: `app_core/nota_liga_core.py`, `app_core/postfusion_calibration_core.py`,
`app_core/statscamps_tab_core.py`, `app_core/streamlit_apptest_core.py`,
`app_core/viewer_mode_core.py`, `mlcore/calibration.py`, `mlcore/replay_pre_jogo.py`,
`mlcore/tests/test_calibradores_aninhados.py`, `mlcore/tests/test_e2e_smoke.py`,
`mlcore/tests/test_postfusion_grupo.py`, `mlcore/tests/test_viewer_mode_core.py`,
`tools/auditoria_pre_jogo.py`, `tools/find_code_errors.py`, `tools/nota_por_liga.py`,
`tools/run_phase6_live_gate.py`.
Preencher junto com a frente que tocar cada arquivo, não numa mutirão separado.

**D3. `SETUP.md` está desatualizado.** Ele afirma que `ml_artifact.json`,
`params_fitted.json`, `CSV_HISTORICO/` e `CSV_DIARIO/` estão no `.gitignore`.
**Não estão mais** — foram versionados. Quem seguir o SETUP.md no PC novo vai
procurar arquivo que já veio no clone.

**D4. `frescor.py` usa uma tabela de cadência compartilhada pelos dois repos.**
Ela diz 7 dias para `livro_caixa.json` e `frescor.json`, mas a esteira do Dota
roda 2x por dia — lá o prazo está tolerante demais (avisaria com 14 dias em vez
de 2). É a mesma doença curada na régua das 28 (afirmação sobre um repositório
morando em código compartilhado), e a cura é a mesma: cadência vira dado do repo.

**D5. A nota oficial mede um caminho que não é o servido.** Divergência média de
3,36 pontos percentuais, em 69,2% dos jogos ≥ 2 pp. A causa é que o caminho
servido não é função pura. `mlcore/replay_pre_jogo.py` foi criado para atacar
isso e ainda não fechou a frente.

**D8. A CALIBRAÇÃO PÓS-FUSÃO NÃO FAZ NADA EM PRODUÇÃO — e isto trava a frente 0.**
Achado em 04/09/2026, e é o motivo de a frente 0 estar PARADA esperando decisão.

A bandeira `ml_postfusion_cal_enabled` tem default **True**, e o docstring de
`app_core/postfusion_calibration_core.py` afirmava que "a etapa ESTÁ ativa em
produção". Ela não está. O estágio recebe três coisas por injeção
(`apply_microseg_fn`, `apply_fused_postcal_fn`, `postfusion_microseg_table`) e
**nenhuma delas existe no caminho servido**:

- o contrato de entrada `MlPreEngineInput` (`app_core/ml_pre_pipeline_models.py`)
  não tem esses campos;
- `build_pre_engine_input` (`app_core/visao_geral_ml_pipeline_core.py:63`) não
  os produz;
- `visao_tab_core.py:491–602` monta o dicionário uma vez e o passa sem mexer.

Conferido rodando com os argumentos exatos do caminho servido:
`p_out == p_in`, `applied == False`. A bandeira está ligada e o estágio é
inerte.

**Por que isto importa para a frente 0.** O gate mediu o calibrador com grupo
**substituindo** o Platt da fusão. Em produção não há Platt da fusão para
substituir. Então ligar o bloco não faz o que a medição descreve: faz uma coisa
diferente, e possivelmente maior, porque o grupo passaria a ser o único estágio
ativo ali. **A medição de +0,02368 continua válida para o caminho medido, e
não se pode afirmar que vale para o servido.**

Isto é a dívida D5 aparecendo com nome e endereço: a nota mede um caminho que
não é o servido. Aqui está uma causa concreta, localizada.

**Também explica o achado da ablação** em `MODELO_LOL.md` ("sem o Platt da fusão
melhora 0,00435"): essa ablação corre na cadeia de replay, onde o Platt existe.
No app, ele não roda. Não é contradição de dado — são dois caminhos.

**O que NÃO fiz, de propósito:** não liguei os callbacks. Injetar
`apply_fused_post_calibration` (que existe, em `app_core/fit_runtime_core.py:299`)
ligaria de uma vez um estágio que está morto há tempo indeterminado, mudando o
número na tela sem medição do efeito dessa mudança isolada. É decisão do Bruno,
e provavelmente uma frente própria antes da 0.

**Perguntas em aberto, para quem retomar:** desde quando está inerte? A ablação
de 27/08 e a nota oficial mediram com ou sem ele? Se o Platt da fusão nunca
rodou no app, o número servido hoje é o de qual cadeia exatamente?

---

**D6. RESOLVIDA em 04/09/2026** — o `frescor.py` dava sinal verde com régua
atrasada. Conserto: o resumo agora emite a faixa de aviso (`AVISO: N régua(s)
ATRASADA(s)`), separada do nível de erro. Rodando hoje, o LoL passou a dizer
"AVISO: 8 régua(s) ATRASADA(s)" onde antes dizia "todas dentro do prazo".

Junto vieram três coisas que o conserto sozinho não resolveria:

- **O CI tinha o mesmo ponto cego.** `nota_semanal.yml` decidia o alerta com
  `grep -qE "regua\(s\) VELHA|regua\(s\) SEM CARIMBO"` — a faixa de aviso era
  invisível lá também. Entrou um ramo novo, por último na cadeia de `elif`,
  porque é o nível mais baixo. É a armadilha do `CLAUDE.md` ("casar string em
  YAML não prova que o passo roda") aparecendo de novo.
- **Não havia UM teste** cobrindo o arquivo. Agora há `mlcore/tests/test_frescor.py`,
  com 5 testes, idêntico nos dois repositórios. Ele foi verificado contra o bug:
  revertendo o conserto, o teste falha com a mensagem da D6; com o conserto,
  passa. Não é teste vazio.
- **O CI do Dota não olha o frescor de jeito nenhum** — `dados_diarios_dota.yml`
  roda `python frescor.py` sem capturar nem examinar a saída. Lá o vigia roda e
  o resultado é jogado fora. **Fica em aberto**, é conserto de esteira, não do
  arquivo compartilhado.

Fonte do desenho (conferida em 04/09): a prática de monitoramento de frescor
configura os testes com nível de **aviso e de erro**, emitindo sinal em ambos —
ter duas faixas e reportar só a de erro desperdiça a faixa que existe para agir
a tempo. https://dqops.com/docs/categories-of-data-quality-checks/how-to-detect-timeliness-and-freshness-issues/

Registro do que era: achado em 04/09/2026.
O interruptor de homem morto tem três estados — `atrasada` (passou de 2x a
cadência), `VELHA` (3x) e `SEM CARIMBO`. A linha de resumo em
`tools/frescor.py:188` é `if not (velhas or sem)`, e **o balde `atrasada` fica
de fora**. Resultado real do dia: a tabela listou 8 réguas `atrasada` (18,8 dias
para uma cadência de 7) e logo abaixo imprimiu "todas as reguas declaradas estao
dentro do prazo".

Ou seja, o vigia que existe para avisar que a nota envelheceu **avisa que está
tudo bem**. É o mesmo arquivo compartilhado da D4, então as duas saem juntas —
e, pela regra 5, junto com a frente que tocar nele, não em mutirão. Vale nos
dois repositórios.

**D7. RESOLVIDA em 04/09/2026** — a suíte do Dota retreinava os modelos de
produção. Culpado: `mlcore/tests/test_retrain_pre_voo.py`, que chamava
`launch_retrain_background(project_root=".")` — a raiz real e o `live_models/`
real. Conserto: raiz temporária.

O teste era pior do que parecia: a chamada estava **antes** da checagem de
existência, então ele lançava o retreino e só depois via que o script existe
neste repo e dava `skipTest`. **Pagava o efeito colateral e não verificava
nada.** Com a raiz temporária o guarda de pré-voo passa a ser exercitado de
verdade, e a suíte não toca em produção.

Verificado rodando a suíte inteira: os 4 `lgb_model.txt` ficam **byte a byte
idênticos** (md5 conferido antes e depois), `FASE6_LIVE_DOTA.json` não é
reescrito e `live_models/retrain.log` não é tocado. Baseline mantido: 15 falhas
e 30 erros, agora em 4.681 testes.

Fonte (conferida em 04/09): teste hermético — só o conteúdo do próprio teste
decide se ele passa, sem depender do sistema de arquivos real e sem efeito
colateral, e injeção de dependência é o meio de trocar o que é do ambiente por
algo controlado pelo teste. https://testrigor.com/blog/hermetic-testing/

**PERDA QUE EU CAUSEI, e que não dá para desfazer:** o retreino acidental de
04/09 sobrescreveu `live_models/last_auto_retrain.txt` com
`2026-09-04T10:20:41`. O valor que estava lá antes **está perdido** — a cópia de
segurança foi feita depois do acidente. O git tem `2026-08-26T07:56:01` no HEAD,
que é o último commitado, não o que estava em uso. Não inventei carimbo no
lugar. Consequência prática: o agendador do auto-retreino acha que retreinou
hoje e vai esperar mais um ciclo, enquanto os modelos são de 27/08. **Se quiser
forçar um retreino, é decisão sua** — apagar ou recuar esse carimbo faz o app
retreinar no próximo ciclo.

**FICA EM ABERTO, menor:** vários outros testes leem o `live_models/` real por
`Path(__file__).parents[2]` — `test_live_assessment_integration`,
`test_live_state_runtime_core`, `test_live_markets_runtime_core`,
`test_live_first_markets`, `test_player_props`, `test_live_state_panel_ui`.
Ler não destrói, mas torna o teste dependente do estado do disco: foi por isso
que 14 deles falharam no caminho com acento parecendo bug de modelo. Consertar
é refatoração maior, e não foi feita.

Registro do que era: achado em 04/09/2026.
Um teste chama `launch_retrain_background` contra o `live_models/` real em vez
de uma pasta temporária: rodar a suíte sobrescreve os 12 arquivos dos 4 minutos.
Não há chave de ambiente para desligar. Enquanto o repo morou em caminho com
acento isso ficou escondido, porque o acento é que impedia a escrita — o erro
aparecia como `Model file ... is not available for writes`, que parece
permissão e não é.

É o mesmo defeito de fundo da D1 (suíte que não é só-leitura), mas aqui é
**medido e localizado**, não hipótese. O conserto é o teste usar `tmp_path`.
Até lá: copiar `live_models/` antes de rodar a suíte do Dota. A cópia de 04/09
está em `C:\Gabinetes\_backup_dota_pre_move_20260904\`.

Cuidado ao restaurar: `git checkout` **não** devolve o arquivo original. O Dota
tem `core.autocrlf = true` e nenhum `.gitattributes`, então o checkout reescreve
`lgb_model.txt` com CRLF e engorda o arquivo em ~2.200 bytes. Restaure de cópia
física e confira por md5.

Efeito colateral já visível: os 4 `lgb_model.txt` do Dota agora aparecem como
modificados no `git status`. **Os arquivos em disco são os originais** (md5
conferido). O que mudou foi o relato do git: eles sempre diferiram do commitado
por 2 bytes — as duas últimas linhas terminam em CRLF e o resto em LF — e o git
não mostrava porque o cache de `stat` dele nunca comparou o conteúdo. Mexer nos
arquivos derrubou o cache. Não commitar por reflexo; decidir junto com a frente
que tocar em `live_models`.
