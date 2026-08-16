# -*- coding: utf-8 -*-
"""NOTA POR LIGA — onde o modelo merece confiança (pedido dele 24/07).

Motivo: a nota geral (9.15) é uma média que mistura ligas onde ele aposta com
ligas pequenas que nem olha. Medido em 24/07: LPL/LCK/LEC/LCS estão BEM
calibradas (ECE 0.019-0.056) enquanto LRS/VCS/HM/CBLOL estão em 0.09-0.12 — o
segmento "mesma-liga 8.5" é puxado pelas pequenas, não pelas grandes.

Aqui a nota sai POR LIGA, com a MESMA fórmula do scorecard oficial
(_grade_from_logloss: aleatório 0.6931 -> 5.0, elite 0.55 -> 9.5), mais
acurácia, ECE e amostra. Serve para saber onde confiar antes de apostar.

Saída: tabela no terminal + evidence/nota_por_liga.json

Uso: python tools/nota_por_liga.py [--min-n 80] [--season 2026]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact  # noqa: E402
from mlcore.io_oracle import load_oracle_elixir_games  # noqa: E402
from mlcore.tiers import tier_for_league  # noqa: E402
from tools.ml_quality_scorecard import _grade_from_logloss, default_csvs  # noqa: E402


def _ece(d: pd.DataFrame) -> float:
    """Erro de calibração: |previsto - real| médio, ponderado por faixa."""
    bins = [0, .3, .4, .45, .55, .6, .7, 1]
    d = d.copy()
    d["_b"] = pd.cut(d["p"], bins)
    tot = 0.0
    for _, dd in d.groupby("_b", observed=True):
        if len(dd) == 0:
            continue
        tot += (len(dd) / len(d)) * abs(dd["p"].mean() - dd["y"].mean())
    return float(tot)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=80, help="amostra mínima por liga")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--csv", action="append", default=None,
                    help="CSV no schema OracleElixir-like (repetível). Sem isso, usa os do LoL. "
                         "Serve para medir OUTRO modelo — ex.: o do Dota, que é clone do mesmo mlcore.")
    ap.add_argument("--out", default=None, help="caminho do JSON de saída")
    args = ap.parse_args()

    art_path = Path(args.artifact)
    art = MLArtifact.load_json(str(art_path if art_path.is_absolute() else ROOT / art_path))
    model = art.model

    frames = []
    for c in (args.csv or default_csvs()):
        try:
            d = load_oracle_elixir_games(str(c), keep_playoffs=None)
            if not d.empty:
                frames.append(d)
        except Exception as e:
            print(f"skip {c}: {e}")
    g = pd.concat(frames, ignore_index=True, join="inner")
    g["date"] = pd.to_datetime(g["date"], errors="coerce")
    g = g.dropna(subset=["date"]).drop_duplicates("gameid", keep="last")
    season = int(args.season) if args.season else int(pd.to_numeric(g["year"], errors="coerce").max())
    g = g[pd.to_numeric(g["year"], errors="coerce") == season]

    rows = []
    for r in g.itertuples(index=False):
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        lg = str(getattr(r, "league", "") or "OTHER")
        t = str(tier_for_league(lg))
        p = float(model.p_blue(str(r.blue), str(r.red), blue_league=lg, red_league=lg,
                               blue_tier=t, red_tier=t))
        rows.append({"league": lg, "tier": t, "p": p, "y": y})
    df = pd.DataFrame(rows)
    if df.empty:
        print("sem jogos na season")
        return 1
    pc = df["p"].clip(1e-9, 1 - 1e-9)
    df["ll"] = -(df["y"] * np.log(pc) + (1 - df["y"]) * np.log(1 - pc))

    out = []
    for lg, d in df.groupby("league"):
        if len(d) < int(args.min_n):
            continue
        ll = float(d["ll"].mean())
        out.append({
            "liga": lg, "tier": d["tier"].iloc[0], "n": int(len(d)),
            "nota": round(float(_grade_from_logloss(ll)), 2),
            "logloss": round(ll, 4),
            "acuracia": round(float(((d["p"] >= 0.5) == (d["y"] >= 0.5)).mean()), 3),
            "ece": round(_ece(d), 3),
        })
    o = pd.DataFrame(out).sort_values("nota", ascending=False)

    geral_ll = float(df["ll"].mean())
    print(f"=== NOTA POR LIGA — season {season} (min {args.min_n} jogos) ===")
    print(f"nota GERAL (todas as ligas juntas): {_grade_from_logloss(geral_ll):.2f}  "
          f"[logloss {geral_ll:.4f}, n={len(df)}]\n")
    print(o.to_string(index=False))
    print("\nleitura: nota usa a formula oficial (aleatorio=5.0, elite=9.5).")
    print("         ece = erro de calibracao; <0.06 e bom, >0.10 e desconfiar.")

    out_path = Path(args.out) if args.out else (ROOT / "evidence" / "nota_por_liga.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"season": season, "nota_geral": round(float(_grade_from_logloss(geral_ll)), 2),
                    "min_n": int(args.min_n), "ligas": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n[salvo] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
