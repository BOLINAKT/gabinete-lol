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

1. **Sombra antes de ligar.** Rodar o calibrador novo em 100% do tráfego sem
   servir o resultado, e comparar a distribuição de saída contra a base. A fonte
   é direta sobre este caso: se o candidato prevê sistematicamente diferente,
   "provavelmente é distorção de calibração ou numérica, mesmo que a métrica
   offline pareça boa". A inclinação global medida foi **1,296** (maior que 1 =
   afiando), então os números **vão** mudar de verdade.
   Fonte: https://resiliotech.com/blog/model-canary-releases-shadow-traffic-guide
2. **A janela de ajuste não pode ser chutada.** Eu tinha cravado "últimos 2.500
   jogos" sem medir. A literatura de deriva de calibração usa **janela
   adaptativa**: o detector escolhe qual é o pedaço recente estável e ele mesmo
   avisa quando reajustar. No mínimo, varrer a janela por validação cruzada em
   vez de afirmar 2.500.
   Fonte: Davis & Greevy, *Detection of calibration drift in clinical prediction
   models to inform model updating*, J. Biomed. Inform. 2020 —
   https://pubmed.ncbi.nlm.nih.gov/33157313/
3. **Deriva moderada pede recalibrar; deriva severa pede retreinar.** O gatilho
   tem que separar os dois, senão recalibra em cima de um modelo que já perdeu a
   ordenação. Fonte: https://smartdev.com/ai-model-drift-retraining-a-guide-for-ml-system-maintenance/

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

**D6. O `frescor.py` dá sinal verde com régua atrasada.** Achado em 04/09/2026.
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

**D7. A suíte do Dota retreina os modelos de produção.** Achado em 04/09/2026.
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
