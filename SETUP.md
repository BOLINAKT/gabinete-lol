# Setup — rodar idêntico em qualquer máquina

Guia pra deixar o app rodando numa máquina nova **exatamente** como na sua. O
código vai pelo git; o **modelo + os dados** vão por um zip separado (eles não
entram no git de propósito — são pesados e gerados).

## Requisitos
- **Python 3.13** (ver `.python-version`). Mínimo 3.11.
- git.

## Máquina nova — passo a passo
1. **Pegar o código** (clone do git ou a pasta do projeto).
2. **Ambiente virtual** (isola as libs):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1      # Windows
   ```
3. **Instalar as dependências** (versões pinadas = iguais às suas):
   ```powershell
   pip install -r requirements.txt
   ```
4. **Receber o modelo + dados.** Quem tem o projeto rodando gera o bundle com
   `\.tools\make_release.ps1` e te manda o `gabinete_data_<data>.zip`.
   **Descompacte na RAIZ do repositório** (de forma que `ml_artifact.json` fique
   na raiz e os CSVs em `CSV_HISTORICO/` e `CSV_DIARIO/`).
5. **Conferir que está tudo pronto** (diz exatamente o que falta, se faltar):
   ```powershell
   python tools/setup_check.py
   ```
6. **Rodar o app:**
   ```powershell
   streamlit run plays_app.py
   ```

## Comandos do dia a dia
- **Atualizar o modelo** (quando entrar CSV novo): `python tools/atualizar_modelo.py`
  (rebuild + nota + fixtures + testes, na ordem certa).
- **Diagnóstico de qualidade** (queda da nota + solução): `python tools/ml_quality_diagnose.py`
- **Nota atual (produto real, Elo+players):** `python tools/ml_fusion_scorecard.py`
- **Rodar os testes:** `python -m unittest discover -s mlcore/tests -p "test_*.py"`

## Enviar pra outra máquina (você → seu amigo)
1. **Código:** `git push` (ou mandar a pasta sem `.venv/`, `CSV_*`, `ops/`).
2. **Modelo + dados:** `\.tools\make_release.ps1` → manda o zip de `release/`.
3. Do outro lado: passos 1–6 acima.

## Por que os bugs aconteciam antes
`ml_artifact.json`, `players_artifact.json`, `params_fitted.json`, `CSV_HISTORICO/`,
`CSV_DIARIO/` e `ops/` estão no `.gitignore` (não vão no git). Mandando só o
código, a outra máquina ficava **sem o modelo e sem os dados** → o app subia sem
"cérebro" → bugs. O bundle de release (passo 4) resolve isso. O `setup_check.py`
detecta na hora se algo está faltando, em vez de o app quebrar com erro críptico.
