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

## 3-A. FRENTE 0 — LIGADA em 06/09/2026

O calibrador com grupo está **em produção**. O bloco
`postfusion_group_calibration` foi gravado em `params_fitted.json`.

**Para DESLIGAR:** apagar essa chave do arquivo, ou
`git checkout -- params_fitted.json`. Sem ela o app volta ao comportamento
anterior, e isso está travado por teste.

**O número que decide** (teste cego, 5.525 jogos, contra o caminho REALMENTE
servido — ver dívida D8): ganho **+0,02007**, IC [+0,01560, +0,02446].
Z de Spiegelhalter de −6,64 para −2,94.

**O QUE MAIS IMPORTA SABER, e a média escondia.** O efeito **muda de sinal**
por formato:

| grupo | inclinação na tela | efeito | % dos jogos |
|---|---|---|---|
| BO1 regular | 1,506 | afia | 47,3% |
| **BO3 regular** | **0,602** | **achata** | **31,6%** |
| BO3 playoffs | 1,797 | afia | 11,7% |
| BO5 playoffs | 0,513 | achata | 4,7% |
| BO1 playoffs | 1,434 | afia | 3,1% |
| BO5 regular | 0,501 | achata | 1,6% |

Ou seja: o modelo era **subconfiante em BO1** e **superconfiante em série
longa**. Em BO3 de fase regular — quase um terço dos jogos — os números agora
vêm bem mais perto de 50%: um 80% de antes sai por volta de 63%. Se a leitura
parecer "o modelo ficou covarde nas BO3", é isto, e é de propósito.

Impacto medido na tela: 6,22 pp de diferença média, e **6,53% dos jogos trocam
de favorito** (361 de 5.525).

**Como reajustar** (a composição de formato/fase muda ao longo do ano e o
calibrador envelhece com ela): `python tools/ajustar_calibrador_grupo.py`
para ver, `--escrever` para gravar. Cadência ainda **não declarada** — está na
lista de artefatos sem prazo do `frescor.py`, e declarar é dívida aberta.

**O que ficou de fora, e é decisão sua:** o estágio pós-fusão continua com
microssegmento da fusão e Platt da fusão desligados, porque foi medido que
custam. O código deles segue lá com bandeira ligada, parecendo ativo — ou se
remove, ou se documenta como desligado de propósito.

---

## 3. A PRÓXIMA AÇÃO, exata (histórico — a frente 0 foi concluída)

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
   Acompanhar AUROC ao longo do tempo é o sinal padrão. Sobre "agregado
   esconde deriva por segmento": eu citava aqui um artigo do MLflow, e ao
   abrir a página em 06/09/2026 ela **não diz isso** — trata de limiares por
   feature, não por coorte. A afirmação fica **sem fonte externa**, e não
   precisa de uma: a sombra do calibrador mediu o agregado dizendo "afia"
   enquanto 38% dos jogos eram achatados. A evidência é nossa.

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
| 0 | **Ligar o calibrador do pré-jogo** | **FEITA em 06/09/2026** — ver abaixo |
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

**D2. REENQUADRADA em 06/09/2026 — o problema não era o que eu pensava.**

A dívida dizia "15 arquivos sem bloco FONTES". Hoje são **14** (o
`postfusion_calibration_core.py` saiu junto com a frente 0, como a regra 5
manda). Mas ao trabalhar nela apareceu coisa pior.

**A regra 5 proíbe fazer o resto agora.** "Cada um sai junto com a frente que
tocar nele — não em mutirão separado." Das frentes desta semana, só duas
tocaram arquivos da lista: `mlcore/replay_pre_jogo.py` (D9) e
`tools/nota_por_liga.py` (temporada). Os outros 12 esperam.

**O ACHADO QUE IMPORTA: bloco FONTES que não pode ser conferido é pior que
bloco nenhum.** Auditei as **28 URLs** que entraram nos arquivos desta semana.
**15 tinham sido citadas a partir do RESUMO da busca, sem eu abrir a página.**
Abri as que carregavam peso, e o resultado:

| fonte | o que aconteceu |
|---|---|
| thicket.sh (ausência de dado) | **confere**, textual |
| blog.engflow.com (chave por entrada) | **confere**, textual |
| feast.dev (uma definição só) | **confere**, e mais forte que meu resumo |
| dqops.com (aviso + erro no frescor) | **confere**: "We advise configuring the check for warning and error severity levels" |
| cherryleaf.com (docs as tests) | **confere** |
| PMC8647501 (Schnellinger) | **confere** |
| arXiv 2505.00356 (Zanotti) | **confere** |
| mlflow.org/docs (assinatura do modelo) | **confere em parte** — não diz "evita cravar suposições"; isso é meu |
| resiliotech (sombra) | **NÃO diz** o que se afirmava |
| smartdev (deriva moderada × severa) | **NÃO diz** o que se afirmava |
| mlflow.org/articles (agregado × segmento) | **NÃO diz** o que se afirmava |
| giskard + Google (teste cego não revela) | dão a definição e a Regra de Ouro, **não** a minha lição |
| apxml (tolerância da paridade) | **403, não pude abrir** |
| bazel.build/remote/caching | não descreve a chave — descartada antes de citar |
| systemoverflow | não continha a frase — descartada antes de citar |

**Quatro afirmações minhas estavam vestidas de citação.** Todas corrigidas no
lugar onde estavam, marcadas como inferência minha ou como sem fonte. Nenhuma
conclusão técnica mudou — o que mudou foi o que cada afirmação pode sustentar.

**A lição, que vale mais que a dívida original:** resumo de busca não é fonte.
Ele confirma o que você já queria ouvir. Das cinco páginas que abri procurando
confirmação, **três não confirmavam**. Regra nova, a cumprir: *nenhuma URL
entra em bloco FONTES sem ter sido aberta, e o bloco diz a data em que foi.*

**O que os 12 restantes precisam, quando a frente chegar neles:** não é um
link. Um registro de decisão captura a decisão, a razão, **e as consequências
— boas e ruins**. Os blocos bons deste repositório já fazem isso (o do
`gate_calibrador_final.py` registra até um erro do autor); os ruins são lista
de link. https://adr.github.io/ (conferida em 06/09/2026)

**D3. RESOLVIDA em 06/09/2026.** O `SETUP.md` apodreceu do jeito mais
traiçoeiro: alguém corrigiu o **meio** e esqueceu as **pontas**. O passo 4 foi
atualizado em 27/08 para dizer (certo) que o modelo vem no clone, mas o
cabeçalho continuou dizendo o contrário — "vão por um zip separado, eles não
entram no git de propósito" — e o fim ainda mandava o bundle resolver um
problema que já não existia. Quem lesse de cima para baixo recebia duas
instruções opostas. O caminho do `make_release.ps1` também estava errado
(`.tools\` em vez de `tools\`).

Conferi cada afirmação de fato contra o repositório antes de reescrever: os
sete caminhos que ele promete no clone **estão** versionados, o
`ops/baselines/` **não** está (confere), e das seis ferramentas citadas só o
caminho do `make_release.ps1` estava errado.

**E ele passou a ter teste** — `mlcore/tests/test_setup_md.py`, 6 testes.
Documento de instalação apodrece porque mudança de código passa por revisão,
CI e merge, e mudança de documento não passa por nada
(https://understandingdata.com/posts/doc-drift-detection-ci/). A cura é "docs
as tests": as alegações do guia viram ações executáveis, e um teste vermelho
revela ou guia velho, ou produto que quebrou um caminho que funcionava
(https://www.cherryleaf.com/2026/08/docs-as-tests/). As duas conferidas
abrindo as páginas.

O teste foi verificado contra o bug: repondo a frase do cabeçalho, ele falha
com "o cabecalho voltou a dizer que modelo/dados nao vem no git".

**Um teste meu nasceu errado e foi apagado, não remendado:** eu tinha posto uma
varredura por regex atrás de todo token terminado em `.py`/`.ps1`. Ela produzia
lixo — fragmentos como `.py` e `Activate.ps1`, tirados de coisas como
`-p "test_*.py"` — e ficava vermelha com o documento correto. Teste que chora
sem motivo ensina a ignorar teste. O motivo está escrito no lugar onde ele
estava.

**Limite honesto:** o teste confere fatos verificáveis — o que está versionado,
se as ferramentas existem, se os caminhos batem. Ele **não** roda o passo a
passo numa máquina limpa, então instrução certa porém incompleta continua
passando.

Aproveitei para acrescentar ao guia o que esta semana ensinou e não estava lá:
o aviso de **caminho sem acento**, o **recriar o `.venv` ao mover a pasta**, e
que o `.streamlit/secrets.toml` também não vem no clone.

**D4. `frescor.py` usa uma tabela de cadência compartilhada pelos dois repos.**
Ela diz 7 dias para `livro_caixa.json` e `frescor.json`, mas a esteira do Dota
roda 2x por dia — lá o prazo está tolerante demais (avisaria com 14 dias em vez
de 2). É a mesma doença curada na régua das 28 (afirmação sobre um repositório
morando em código compartilhado), e a cura é a mesma: cadência vira dado do repo.

**D11. O PADRÃO POR TRÁS DE QUATRO DÍVIDAS — atacado em 08/09/2026.**

Esta semana quatro coisas quebraram do mesmo jeito: **ausência de dado virando
um número plausível, calado.** A D8 (estágio inerte com bandeira ligada), a D9
(cache que nunca vencia), a nota oficial virando `nan`, e a D5
(`getattr` com default 0.0 de um campo que não existe). Em três das quatro, a
régua que deveria avisar estava ela própria quebrada.

**Já existia ferramenta, e eu reusei em vez de construir:**
`tools/find_silent_failures.py`, de 16/08. Ela tinha quatro famílias — e o
docstring dela dizia **duas**, porque também tinha apodrecido. Corrigido.

**O que a varredura reporta hoje:**

| família | achados |
|---|---|
| 1. imprime não-ASCII sem ajustar encoding | 2 arquivos |
| 2. subprocesso com resultado ignorado | 0 |
| 3. **exceção engolida (`except: pass`)** | **301 em 173** |
| 4. coerce + fillna (dado ruim vira número) | 97 em 28 |
| 5. **`getattr` com default lendo outra camada** (nova) | **65 em 31** |

**A família 5 é a da D5**, e foi desenhada para pegar exatamente aquele caso:
`getattr(x, "nome", 0.0)` de um objeto que não tem o campo. Só conta default
**plausível** — com `None` o idioma é correto, porque obriga quem chama a
tratar. Essa distinção tirou 14 falsos positivos, entre eles o `elo.py`, que
faz `getattr(row, "tier", None)` seguido de `if tg is not None`.

**Um defeito meu, no relatório, que vale registrar:** a primeira versão
mostrava os 12 maiores **por contagem** — e o caso que originou a família
inteira, com uma ocorrência só, ficava de fora. **A ferramenta achou e
escondeu.** Agora ordena por risco: `mlcore` e `tools` primeiro, porque
contagem alta em arquivo de tela é ruído e uma ocorrência no núcleo de medição
apaga uma nota. Há teste travando que o caso da D5 apareça.

Fonte (conferida abrindo a página em 08/09/2026): "Errors should never pass
silently"; `except: pass` é o pior anti-padrão; e "é melhor falhar rápido do
que esconder um erro que causa bug lá na frente".
https://pybit.es/articles/python-errors-should-not-pass-silently/

**O QUE FICA EM ABERTO, e é grande:** as **301 exceções engoladas**. A própria
ferramenta avisa que nem todo caso é bug — às vezes engolir é a decisão certa,
e por isso ela reporta com linha e tipo em vez de proibir. Triar 301 é frente
própria, e a ordem sensata é começar pelas que estão em caminho de medição.

Testes: `mlcore/tests/test_find_silent_failures.py`, 11.

---

**D5. DIAGNOSTICADA em 08/09/2026 — e o número que ela citava nunca foi
confiável.** Ela dizia: divergência média de 3,36 pp entre a régua oficial e o
caminho servido, em 69,2% dos jogos ≥ 2 pp. Medindo de novo, com a D8 e a D9
já consertadas, apareceu o seguinte.

**1) A ferramenta que mede a D5 tinha a D8 dentro.**
`tools/auditoria_pre_jogo.py:156` fazia `servido = variante(treino, teste,
tabela=tabela)` — defaults, com o microssegmento e o Platt da fusão que o app
não roda. Terceira ocorrência da mesma armadilha.

**Consertado na raiz, não no chamador:** os defaults de `cadeia()` e
`variante()` passaram a ser **os de produção**. Quem quiser as etapas mortas
agora **pede**. O docstring dizia "roda o caminho servido" e não era verdade;
agora é. O gate reproduz o mesmo número de antes, com a base velha pedida
explicitamente.

**2) A ablação, refeita, confirma a D8 de forma limpa:**

| variante | Δ logloss |
|---|---|
| sem microssegmento da fusão | **+0,00000** |
| sem Platt da fusão | **+0,00000** |
| sem microssegmento do time | +0,00069 |
| sem Platt do time | **−0,00175** (remover MELHORA) |
| sem a camada de jogadores | +0,00987 (paga muito) |

Zero exato nas duas primeiras porque elas não rodam. Isso **substitui** a
tabela do `MODELO_LOL.md`, que foi medida com elas ligadas.

**3) O ACHADO QUE INVALIDA O NÚMERO DA DÍVIDA.** `Amostra.delta_eff` chega
**zero em 100% dos jogos**. A causa: o replay monta o campo com
`getattr(s, "delta_players_eff", 0.0)` e a classe `Sample`
(`mlcore/fit_samples_core.py`) **não tem campo de delta nenhum** — o delta é
calculado durante a montagem e descartado. O `getattr` com default devolve
0,0 calado, para sempre.

Com delta = 0, `p_regua` devolve **o Elo sozinho** — conferido, bate com
`p_team` em 1,11e-16. Então a "divergência régua × servido" comparava o Elo
puro contra a cadeia completa. Mede alguma coisa, mas **não o que a dívida
afirma**.

**O que fica medido e vale:** a régua oficial dá logloss **0,59109** e o
caminho servido **0,58464** — a nota oficial **subestima** o modelo, porque
não tem a camada de jogadores, que vale +0,00987.

**Conserto feito hoje:** `p_regua` **avisa em voz alta** quando o delta é zero
em todos os jogos, em vez de mentir calada. `mlcore/tests/test_regua_vs_servido.py`
(6 testes) trava o aviso, e trava que ele **não** apareça quando o dado estiver
certo — aviso que vira ruído é aviso ignorado.

**O QUE FALTA, e é frente própria:** levar o delta até a `Sample`. Isso mexe
num arquivo que o TREINO usa, então não entra de carona. Só depois disso dá
para medir a divergência de verdade.

**Fonte da regra aplicada** (conferida abrindo a página em 04/09/2026):
ausência de dado não pode virar um número — "as métricas devolvem nulo quando
nada foi medido... e imprimem um aviso explícito", e "falhe alto na fronteira".
https://thicket.sh/blog/when-your-metric-is-broken-not-your-business

**D9. RESOLVIDA em 06/09/2026.** O cache passa a carregar a **assinatura das
entradas** que o geraram — `ml_artifact.json`, `players_artifact.json`,
`params_fitted.json`, os CSVs (nome, tamanho, mtime) e o `val_cutoff`, mais um
`CACHE_VERSAO` para invalidar tudo de uma vez se a forma do que se guarda
mudar. Assinatura diferente → recalcula, **avisando alto**.

Fonte (conferida abrindo a página): num sistema de build, "o `digestKey` é um
hash das entradas e saídas da ação", e como a chave incorpora o hash das
próprias entradas, qualquer modificação nelas produz chave diferente,
"tornando o resultado antigo inacessível sob a chave nova e portanto
impossível de ser reusado por engano" —
https://blog.engflow.com/2024/05/13/the-many-caches-of-bazel/
Não existe "esquecer de invalidar".

Vale registrar que **abrir as páginas mudou o resultado**: das quatro
consultadas, três não serviram. A da Bazel não descreve a composição da chave;
a do systemoverflow **não continha** a frase que o resumo da busca lhe
atribuía; a da ACM devolveu 403.

Conferido rodando: cache sem assinatura **vence** e recalcula (224 s); cache
válido é usado em **0,2 s**; tocar o `ml_artifact.json` **vence**.

**O recálculo revelou dado escondido além de modelo escondido:** o teste cego
passou de 5.525 para **5.917 jogos**. Os CSVs novos do robô nunca tinham
entrado nas medições.

**ESCOLHA COM PREÇO ACEITO:** tamanho+mtime em vez de hash do conteúdo — é o
mesmo critério do `_file_sig` que o app já usa, e ler ~300 MB de CSV a cada
chamada só para decidir se pode usar o cache anularia o cache. O preço:
arquivo reescrito com mesmo tamanho **e** mesmo mtime passa despercebido. Para
forçar, apagar o arquivo de cache.

Testes: `mlcore/tests/test_cache_replay.py`, 10. Suíte: 4.739, OK.

Registro do que era: achado em 06/09/2026.

`mlcore/replay_pre_jogo.carregar()` devolve `evidence/_cache_pre_jogo.json` se
o arquivo existir, **sem conferir nada**. O cache era de **26/08 23:34** e o
`ml_artifact.json` foi atualizado pelo robô **todo dia até 06/09**.

Sintoma que denunciou: depois de integrar o modelo novo, o gate deu números
**idênticos** aos de antes, até a quinta casa. Modelo diferente, nota igual.

**Consequência:** tudo o que foi medido em 04 e 05/09 — o gate, a sombra, a
varredura da janela, a comparação de base da D8 — usou o modelo de 26/08.
Os números foram refeitos em 06/09 contra o modelo corrente, e estão marcados
como tal onde aparecem.

É a terceira variante da mesma doença numa semana (D5, D8, D9): **a medição
descolada do que roda**. E é o item MONITORAMENTO 3 da régua das 28 outra vez.

**Conserto que NÃO foi feito:** o cache precisa carregar a assinatura das
entradas que o geraram (`ml_artifact.json`, `players_artifact.json`, os CSV) e
se invalidar sozinho quando elas mudam. Hoje o jeito de forçar é apagar o
arquivo à mão — e ninguém sabe que precisa.

---

**D10. RESOLVIDA em 06/09/2026.** O aplicador cravava a chave do grupo como
`f"{bo}|{phase}"`, então dos quatro agrupamentos que a validação cruzada pode
escolher só um era representável — e o reajuste ficava bloqueado.

**Conserto:** `mlcore/agrupamentos.py` (novo) é a **fonte única** da chave, e
tanto quem ajusta (gate e `ajustar_calibrador_grupo.py`) quanto quem serve
(`postfusion_calibration_core`) passam a importar dali. O bloco em
`params_fitted.json` já gravava `agrupamento`; agora o aplicador **lê esse
campo** em vez de adivinhar. Bloco antigo, sem o campo, cai no legado
("formato + fase") — que era o único que podia estar em produção.

Junto veio um segundo defeito, que sozinho manteria o bloqueio: o
`ajustar_calibrador_grupo.py` só escrevia `agrupamento` no bloco **depois** da
conferência de paridade, então a conferência usava o legado e divergia em todo
agrupamento que não fosse "formato + fase". O campo passou para antes.

Prova: reajustando contra o modelo de hoje, a validação cruzada escolhe
**"formato BO"** e a paridade dá **1,11e-16** — antes dava 2,8e-01 e abortava.

Fontes (conferidas em 06/09): o artefato tem que se **descrever**, para o
código de serviço não cravar suposições sobre o que o modelo espera
(https://mlflow.org/docs/latest/ml/model/signatures/); e a transformação
precisa de **uma definição só**, porque reimplementada de um lado ela "começa
idêntica e deriva" (https://feast.dev/blog/what-is-a-feature-store/).

Testes: `mlcore/tests/test_agrupamentos.py` (7) e três casos novos em
`test_paridade_grupo_servido.py`, cobrindo os quatro agrupamentos, o
agrupamento desconhecido (que **desliga** em vez de servir o global calado) e
o bloco legado. Suíte: 4.729 testes, OK. O gate reproduz o mesmo número de
antes do refactor (+0,01698), então nada regrediu.

**E o reajuste, agora que dá? NÃO é preciso.** Medidos contra o modelo
corrente, no teste cego:

| | logloss | ECE | Z | ganho |
|---|---|---|---|---|
| app sem calibrador | 0,58300 | 0,033 | −6,59 | — |
| bloco em produção (26/08) | 0,56017 | 0,033 | −4,26 | +0,02284 |
| bloco novo (modelo de hoje) | 0,56560 | 0,033 | −4,97 | +0,01740 |

O reajuste não mostra melhora. **Cuidado com a leitura:** escolher entre os
dois pelo teste cego seria o viés de seleção da fonte 3 do gate. O que se pode
afirmar é o bastante para decidir — não há motivo para trocar o bloco. Fica
como está, e o mecanismo de reajuste agora existe para quando for preciso.

Registro do que era: achado em 06/09/2026.

`app_core/postfusion_calibration_core._calibrador_com_grupo` monta a chave do
grupo fixa como `f"{bo}|{phase}"`. Mas `tools/gate_calibrador_final.AGRUPAMENTOS`
oferece quatro opções ("nenhum", "formato BO", "fase", "formato + fase"), e a
validação cruzada escolhe entre elas. **Só uma das quatro é representável no
app.**

Apareceu assim: reajustando contra o modelo de 06/09, a validação cruzada
escolheu **"formato BO"**, e a paridade acusou divergência de 2,8e-01. O
`ajustar_calibrador_grupo.py` **abortou sozinho e não gravou** — o guarda
funcionou exatamente como devia.

**Efeito prático:** o bloco que está servindo continua sendo o ajustado sobre o
modelo de 26/08, e **não dá para reajustar** enquanto a validação cruzada
preferir um agrupamento que o aplicador não representa.

**Medido em 06/09**, o bloco que está de fato ligado, contra o modelo corrente
e no teste cego: ganho **+0,02068**, IC [+0,01584, +0,02516] — **passa**.
Mas o ECE **piora** (0,033 → 0,041) e o Z quase não anda (−6,59 → −5,95),
enquanto um ajuste fresco daria ECE 0,030 e Z −3,70. Ou seja: pela barra da
casa ele passa, e ainda assim deixa mais distorção sistemática do que deixaria
um bloco novo. **Isso é motivo para consertar, não para desligar.**

**O conserto:** o bloco gravado passa a carregar qual é o agrupamento, e o
aplicador monta a chave a partir disso em vez de assumir `bo|phase`. Enquanto
não for feito, todo reajuste depende de a validação cruzada escolher
"formato + fase" por sorte.

---

**D8. RESOLVIDA em 05/09/2026, e o diagnóstico mudou de figura.** Ela NÃO trava
mais a frente 0 — o que ela fez foi corrigir a régua.

**O que era.** Achei em 04/09 que "a calibração pós-fusão não faz nada em
produção" e que isso invalidava a medição da frente. Metade estava certa.

**O que é, depois da arqueologia de 05/09.** Existem DUAS camadas com nomes
parecidos, e só uma está morta:

- **VIVA:** `plays_app.py:2261` injeta `apply_microseg_fn` e
  `apply_fused_postcal_fn` em `compute_ml_core_prediction`
  (`app_core/ml_prediction_core.py`). Isso roda **antes da fusão**, sobre a
  probabilidade do time. O Platt do time e o microssegmento do time estão de pé.
- **MORTA:** o estágio pós-fusão de `ml_pre_engine_core.py`, que chama
  `postfusion_calibration_core.apply_postfusion_calibration`. Os callbacks dele
  nunca são injetados (o contrato `MlPreEngineInput` nem tem os campos).
  Conferido rodando: `p_out == p_in`, `applied == False`.

Ou seja: o **microssegmento da fusão** e o **Platt da fusão** não rodam no app.

**O erro que isso causava, e é o mais grave.** `mlcore/replay_pre_jogo.cadeia()`
tem no docstring "roda o caminho servido", e os defaults dela ligam essas duas
etapas mortas. O gate usava `variante(tr, te, tabela=tab)` com os defaults como
"hoje". **Estava medindo contra uma base pior que a realidade** — a armadilha
"base fraca dá ACCEPT falso" do próprio `CLAUDE.md`, cometida pelo instrumento
que decide.

Medido no teste cego (5.525 jogos):

| | logloss | ECE | Z |
|---|---|---|---|
| base velha do gate (com as duas etapas mortas) | 0,58577 | 0,047 | −8,97 |
| **o que o app realmente roda** | **0,58109** | 0,036 | −6,64 |
| calibrador com grupo | 0,56209 | 0,031 | −2,94 |

A base velha é pior que a realidade em **+0,00469, IC [+0,00339, +0,00587]** —
acima da barra da casa. Isso bate com a ablação do `MODELO_LOL.md`, que já dizia
"sem o Platt da fusão melhora 0,00435"; a diferença é que **não há o que
remover: o app já não roda essa etapa.** O ganho estava contabilizado como
pendente e já tinha sido embolsado.

**Consequência para a frente 0 — ela SOBREVIVE.** O calibrador com grupo,
medido contra a base correta:

- antes reportado (base errada): +0,02368, IC [+0,01847, +0,02866]
- **o que decide: +0,01899, IC [+0,01443, +0,02340] — PASSA**

O ganho estava inflado em ~20%, e ainda assim é dez vezes a barra da casa.
O Z melhora de −6,64 para −2,94.

**A sombra também estava contra a base errada.** Refeita: a tela muda
**6,22 pp** em média (não 7,15) e troca o favorito em **6,53%** dos jogos —
361 de 5.525, não 466.

**Consertado:** `tools/gate_calibrador_final.py` passa a comparar contra o
caminho servido e imprime a base velha só como contraste histórico;
`tools/sombra_calibrador_grupo.py` idem. A evidência grava as duas.

**O QUE FICA EM ABERTO, e é uma decisão sua:** o estágio pós-fusão continua
morto. A medição diz que isso é BOM (as duas etapas custavam), então a
recomendação é **não** ligar os callbacks — mas o código continua lá, com
bandeira ligada, dando a impressão de ativo. Ou se remove, ou se documenta como
desligado de propósito. E `cadeia()` ainda afirma no docstring que roda "o
caminho servido", o que não é verdade com os defaults — quem usar sem passar
`usar_ms2=False, usar_platt_fusao=False` mede outra coisa.

Registro do que era: achado em 04/09/2026, resolvido em 05/09/2026.

---

*(diagnóstico original, mantido para quem for auditar)*
Achado em 04/09/2026.

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
