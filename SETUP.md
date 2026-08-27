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
4. **Modelo + dados: já vêm no `git clone`.** Conferido em 27/08/2026 —
   `ml_artifact.json`, `params_fitted.json`, `players_artifact.json`,
   `CSV_HISTORICO/`, `CSV_DIARIO/`, `live_models/` e `evidence/` **estão
   versionados**. Não é mais preciso bundle nenhum para começar a trabalhar.
   O bundle (`\.tools\make_release.ps1`) segue existindo para mandar a alguém
   que não tenha acesso ao repositório privado.
   **O que o clone NÃO traz:** `ops/baselines/` (~68 MB), que são os retratos
   para onde `tools/rollback_baseline.py` volta. Sem eles não dá para reverter
   um modelo ruim — copiar à mão ao trocar de máquina.
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
**(história — corrigido desde então.)** `ml_artifact.json`,
`players_artifact.json`, `params_fitted.json`, `CSV_HISTORICO/` e `CSV_DIARIO/`
ficavam no `.gitignore`. Mandando só o código, a outra máquina ficava **sem o
modelo e sem os dados** → o app subia sem "cérebro" → bugs. O mesmo mordeu na
Streamlit Cloud, com `live_models/` ignorado: na nuvem o arquivo simplesmente
não existia. Hoje todos esses estão versionados; só `ops/` continua de fora. O bundle de release (passo 4) resolve isso. O `setup_check.py`
detecta na hora se algo está faltando, em vez de o app quebrar com erro críptico.
