# -*- coding: utf-8 -*-
"""REVALIDA os params sem trocar nenhum numero (27/10/2026).

Quando o teste honesto mostra que os params ATUAIS continuam tao bons quanto um
reajuste novo, o certo e mante-los -- mas o aviso "Patch/Liga em REFIT" continua
gritando, porque compara a foto de patches e a data guardadas no
params_fitted.json com o CSV de hoje. Este script atualiza SO a foto de patches
(patch_snapshot, do CSV atual) e o carimbo de data, guardando a data do ajuste
original e a evidencia do teste em "revalidacao". Os parametros nao mudam.

Uso: python tools/revalidar_params.py --csv CSV_DIARIO/2026_...csv --evidencia "texto"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.calibration_schedule import build_patch_snapshot  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--params", default=str(ROOT / "params_fitted.json"))
    ap.add_argument("--evidencia", required=True)
    a = ap.parse_args()
    p = Path(a.params)
    d = json.loads(p.read_text(encoding="utf-8"))
    dfp = pd.read_csv(a.csv, usecols=["gameid", "league", "patch", "date", "participantid"], low_memory=False)
    dfp = dfp[pd.to_numeric(dfp["participantid"], errors="coerce").isin([100, 200])].copy()
    dfp["date"] = pd.to_datetime(dfp["date"], errors="coerce")
    dfp = dfp.dropna(subset=["date"]).sort_values(["date", "gameid"]).drop_duplicates(subset=["gameid"], keep="last")
    antes = dict(d.get("patch_snapshot") or {})
    d["patch_snapshot"] = {**antes, **build_patch_snapshot(dfp)}   # ligas antigas que sumiram ficam
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rev = dict(d.get("revalidacao") or {})
    rev.setdefault("ajustado_em_original", d.get("generated_at"))
    rev["historico"] = list(rev.get("historico") or []) + [{"em": agora, "evidencia": a.evidencia}]
    d["revalidacao"] = rev
    d["generated_at"] = agora
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    mud = [lg for lg, r in d["patch_snapshot"].items() if (antes.get(lg) or {}).get("latest_patch") != r.get("latest_patch")]
    print(f"[revalidar] patch_snapshot atualizado ({len(mud)} ligas mudaram de patch); params intactos; carimbo {agora}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
