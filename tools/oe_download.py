# -*- coding: utf-8 -*-
"""Baixa o CSV diário do Oracle's Elixir (pasta pública do Google Drive) e
substitui o de CSV_DIARIO de forma ATÔMICA e À PROVA DE REGRESSÃO.

Usado pelo robô (GitHub Actions, diário) e utilizável à mão em qualquer PC:
    python tools/oe_download.py

Garantias (aprendidas a ferro no projeto):
- NUNCA substitui por arquivo menor/mais velho: o novo precisa ter >= jogos
  únicos e data máxima >= atual (quota do Drive devolve HTML de erro; um
  arquivo truncado jamais pode virar o oficial).
- Escrita atômica (tmp + os.replace) — nada de leitor pegando arquivo pela
  metade (corrida de escrita já quebrou o app duas vezes em 2026-07).
- Quota do Drive é INTERMITENTE ("Too many users..."): sai com rc=75 (EX_TEMPFAIL)
  para o workflow tratar como "tenta na próxima janela", não como erro.
- Virada de ano: tenta o ano corrente; se o OE ainda não criou o arquivo
  (janeiro), segue no ano anterior. Zero manutenção anual.
"""
from __future__ import annotations

import os
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
import tempfile
from datetime import datetime
from pathlib import Path

FOLDER_URL = "https://drive.google.com/drive/folders/1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = REPO_ROOT / "CSV_DIARIO"
SUFFIX = "_LoL_esports_match_data_from_OraclesElixir.csv"

RC_OK = 0
RC_TEMPFAIL = 75  # quota/indisponibilidade transitória: robô tenta depois
RC_FAIL = 1


def _log(msg: str) -> None:
    print(f"[oe_download] {msg}", flush=True)


def _summary(csv_path: Path) -> tuple[int, str]:
    """(jogos únicos, data máxima) do CSV — régua anti-regressão."""
    import pandas as pd

    df = pd.read_csv(csv_path, usecols=["gameid", "date"], low_memory=False)
    n = int(df["gameid"].nunique())
    dmax = str(df["date"].max())
    return n, dmax


def main() -> int:
    try:
        import gdown
        from gdown.exceptions import FileURLRetrievalError
    except ImportError:
        _log("gdown ausente: pip install gdown")
        return RC_FAIL

    try:
        files = gdown.download_folder(url=FOLDER_URL, skip_download=True, quiet=True)
    except Exception as exc:  # rede/Drive fora: transitório
        _log(f"listagem da pasta falhou ({type(exc).__name__}: {exc}) — transitório")
        return RC_TEMPFAIL
    by_name = {f.path: f for f in (files or [])}

    year = datetime.now().year
    entry = by_name.get(f"{year}{SUFFIX}")
    if entry is None:
        entry = by_name.get(f"{year - 1}{SUFFIX}")  # virada de ano
        if entry is None:
            _log(f"nenhum CSV de {year}/{year-1} na pasta do OE — layout mudou?")
            return RC_FAIL
    target = CSV_DIR / entry.path
    _log(f"alvo: {entry.path}")

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".csv", dir=str(CSV_DIR))
    os.close(tmp_fd)
    try:
        try:
            out = gdown.download(id=entry.id, output=tmp_name, quiet=True)
        except FileURLRetrievalError as exc:
            _log(f"Drive bloqueou o download (quota) — transitório: {exc}")
            return RC_TEMPFAIL
        if not out:
            _log("gdown não baixou (sem exceção) — transitório")
            return RC_TEMPFAIL

        try:
            new_n, new_dmax = _summary(Path(tmp_name))
        except Exception as exc:
            _log(f"arquivo baixado não parseia como CSV do OE ({exc}) — descartado")
            return RC_TEMPFAIL

        if target.exists():
            cur_n, cur_dmax = _summary(target)
            if new_n < cur_n or new_dmax < cur_dmax:
                _log(
                    f"REGRESSÃO detectada (novo {new_n} jogos/max {new_dmax} < "
                    f"atual {cur_n}/{cur_dmax}) — mantendo o atual"
                )
                return RC_FAIL
            if new_n == cur_n and new_dmax == cur_dmax:
                _log(f"sem novidade ({cur_n} jogos, max {cur_dmax}) — nada a fazer")
                return RC_OK
        os.replace(tmp_name, target)
        _log(f"ATUALIZADO: {target.name} ({new_n} jogos, max {new_dmax})")
        return RC_OK
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
