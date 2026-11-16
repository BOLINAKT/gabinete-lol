# Setup — rodar idêntico em qualquer máquina

Guia pra deixar o app rodando numa máquina nova **exatamente** como na sua.

**O código E os dados vão pelo git.** Modelo, CSVs, modelos ao vivo e as notas
estão todos versionados — um `git clone` traz tudo o que é preciso para
começar. As exceções estão no passo 4.

> Cada afirmação de fato deste arquivo é conferida por
> `mlcore/tests/test_setup_md.py`, que roda na suíte. Se você mudar o que está
> versionado, ou renomear uma ferramenta, e esquecer de atualizar aqui, o teste
> fica vermelho. Foi assim que este documento parou de apodrecer — ver o fim.

## Requisitos
- **Python 3.13** (ver `.python-version`). Mínimo 3.11.
- git.
- **Pasta SEM ACENTO no caminho.** Não é frescura: com o repositório em
  `...\Área de Trabalho\...`, o LightGBM não abre nenhum modelo ao vivo e a
  suíte dá 14 falhas que parecem bug de modelo. Ver a armadilha no `CLAUDE.md`.

## Máquina nova — passo a passo
1. **Pegar o código** (clone do git ou a pasta do projeto), em caminho sem acento.
2. **Ambiente virtual** (isola as libs):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1      # Windows
   ```
3. **Instalar as dependências** (versões pinadas = iguais às suas):
   ```powershell
   pip install -r requirements.txt
   ```
4. **Modelo + dados: já vêm no `git clone`.** `ml_artifact.json`,
   `params_fitted.json`, `players_artifact.json`, `CSV_HISTORICO/`,
   `CSV_DIARIO/`, `live_models/` e `evidence/` **estão versionados**. Não é
   preciso bundle nenhum para começar a trabalhar.

   **O que o clone NÃO traz:** `ops/baselines/` (~68 MB), que são os retratos
   para onde `tools/rollback_baseline.py` volta. Sem eles não dá para reverter
   um modelo ruim — **copiar à mão ao trocar de máquina.**

   Também não vem `.streamlit/secrets.toml` (está no `.gitignore`, e é onde
   moram as chaves de API). Guarde-o à parte.
5. **Conferir que está tudo pronto** (diz exatamente o que falta, se faltar):
   ```powershell
   python tools/setup_check.py
   ```
6. **Rodar o app:**
   ```powershell
   streamlit run plays_app.py
   ```

**Se você MOVER o repositório de pasta, recrie o `.venv`.** Os `.exe` de
`.venv\Scripts\` têm o caminho antigo gravado dentro e ficam mudos depois da
mudança — o `python.exe` continua funcionando, o que faz o problema passar
despercebido.

## Comandos do dia a dia
- **Atualizar o modelo** (quando entrar CSV novo): `python tools/atualizar_modelo.py`
  (rebuild + nota + fixtures + testes, na ordem certa).
- **Diagnóstico de qualidade** (queda da nota + solução): `python tools/ml_quality_diagnose.py`
- **Nota atual (produto real, Elo+players):** `python tools/ml_fusion_scorecard.py`
- **Rodar os testes:** `python -m unittest discover -s mlcore/tests -p "test_*.py"`
  (~3,5 min; o esperado é `OK`, sem nenhuma falha)

## Enviar pra outra máquina (você → seu amigo)
1. **Código e dados:** `git push` — o clone do outro lado traz tudo.
2. **Só se ele NÃO tiver acesso ao repositório privado:**
   `tools\make_release.ps1` → manda o zip de `release/`.
3. Do outro lado: passos 1–6 acima, mais o `ops/baselines/` à mão.

## Por que os bugs aconteciam antes
**(história — corrigido desde então.)** `ml_artifact.json`,
`players_artifact.json`, `params_fitted.json`, `CSV_HISTORICO/` e `CSV_DIARIO/`
ficavam no `.gitignore`. Mandando só o código, a outra máquina ficava **sem o
modelo e sem os dados** → o app subia sem "cérebro" → bugs. O mesmo mordeu na
Streamlit Cloud, com `live_models/` ignorado: na nuvem o arquivo simplesmente
não existia.

Hoje todos esses estão versionados; só `ops/` continua de fora. O
`setup_check.py` detecta na hora se algo está faltando, em vez de o app quebrar
com erro críptico.

## Por que este arquivo tem teste (dívida D3, fechada em 06/09/2026)

Ele apodreceu, e do jeito mais traiçoeiro: alguém corrigiu o **meio** e
esqueceu as **pontas**. O passo 4 foi atualizado em 27/08 para dizer que o
modelo vem no clone, mas o cabeçalho continuou dizendo o contrário — "vão por
um zip separado, eles não entram no git de propósito" — e o fim ainda mandava
o bundle resolver um problema que já não existia. Quem lesse de cima para baixo
recebia duas instruções opostas. O caminho do `make_release.ps1` também estava
errado: `.tools\` em vez de `tools\`.

Documento de instalação erra assim porque **mudança de código passa por
revisão, CI e merge, e mudança de documento não passa por nada** — e o erro só
aparece meses depois, com alguém seguindo instrução que não corresponde mais à
realidade.

A cura é transformar as afirmações em teste: cada instrução carrega alegações
sobre o produto, e essas alegações viram ações executáveis; quando o teste
falha, ou o documento envelheceu, ou o produto quebrou um caminho que
funcionava. É o que `mlcore/tests/test_setup_md.py` faz.

Fontes, conferidas abrindo as páginas em 06/09/2026:
- https://www.cherryleaf.com/2026/08/docs-as-tests/
- https://understandingdata.com/posts/doc-drift-detection-ci/

**O que o teste NÃO cobre, e vale saber:** ele confere fatos verificáveis —
quais arquivos estão versionados, quais ferramentas existem, se os caminhos
citados batem. Ele não roda o passo a passo de ponta a ponta numa máquina
limpa, então instrução que esteja *certa mas incompleta* continua passando.
