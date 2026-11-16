"""Validacao OOS da calibracao POR SEGMENTO vs Platt global (gate antes de produto).

Pergunta: trocar o calibrador global (a,b) por calibradores por segmento
(mesma/inter-liga x major/minor x regular/playoffs), com shrinkage para o global
quando o segmento tem pouca amostra, melhora logloss/ECE FORA da amostra sem
piorar as faixas de odd que o usuario aposta (1.30-1.50) nem o inicio de season?

Protocolo (tudo season atual, predicoes p_raw do Elo core como o produto ve):
  SPLIT PRINCIPAL: fit jan-abr -> eval mai+   (calibrador olha o passado)
  SPLIT REVERSO:   fit mar+    -> eval jan-fev (robustez de inicio de season)
Comparamos no MESMO eval: global-Platt(fit) vs segmentado(fit) vs calibrador do artefato.

  python tools/eval_segment_calibration.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.artifact import MLArtifact
from mlcore.calibration import PlattCalibrator, fit_platt_from_raw_probs
from mlcore.io_oracle import load_oracle_elixir_games
from mlcore.tiers import tier_for_league
from mlcore.train_offline import (
    _infer_team_domestic_league_by_year,
    _infer_team_meta_latest,
    _resolve_home_league,
)
from tools.ml_quality_scorecard import _grade_from_logloss, _metrics, default_csvs

ROOT = Path(__file__).resolve().parents[1]
SHRINK_K = 200.0  # peso do segmento = n/(n+K); n pequeno -> cola no global


def _seg_key(inter: bool, major: bool, po: bool) -> str:
    return f"{'inter' if inter else 'same'}|{'major' if major else 'minor'}|{'po' if po else 'reg'}"


def _fit_segmented(rows: list[dict]) -> tuple[PlattCalibrator, dict[str, dict]]:
    glob = fit_platt_from_raw_probs([r["y"] for r in rows], [r["p_raw"] for r in rows])
    segs: dict[str, dict] = {}
    by_seg: dict[str, list[dict]] = {}
    for r in rows:
        by_seg.setdefault(r["seg"], []).append(r)
    for seg, rr in by_seg.items():
        cal = fit_platt_from_raw_probs([r["y"] for r in rr], [r["p_raw"] for r in rr])
        n = float(len(rr))
        w = n / (n + SHRINK_K)
        segs[seg] = {
            "n": int(n),
            "w": w,
            "a": w * cal.a + (1.0 - w) * glob.a,
            "b": w * cal.b + (1.0 - w) * glob.b,
            "a_pure": cal.a,
            "b_pure": cal.b,
        }
    return glob, segs


def _apply_seg(p_raw: float, seg: str, glob: PlattCalibrator, segs: dict[str, dict]) -> float:
    node = segs.get(seg)
    if not node:
        return glob.predict_proba(p_raw)
    cal = PlattCalibrator(a=float(node["a"]), b=float(node["b"]))
    return cal.predict_proba(p_raw)


def _fav_band_gaps(rows: list[tuple[float, int]]) -> list[dict]:
    """Gap de calibracao |media(p_fav) - winrate_fav| por banda de odd do favorito."""
    bands = [(1.30, 1.50), (1.50, 1.75), (1.75, 2.10)]
    out = []
    for lo, hi in bands:
        sel = []
        for p, y in rows:
            p_fav = max(p, 1.0 - p)
            y_fav = y if p >= 0.5 else (1 - y)
            odd = 1.0 / p_fav
            if lo <= odd < hi:
                sel.append((p_fav, y_fav))
        if sel:
            gap = abs(sum(p for p, _ in sel) / len(sel) - sum(y for _, y in sel) / len(sel)) * 100.0
        else:
            gap = float("nan")
        out.append({"band": f"{lo:.2f}-{hi:.2f}", "n": len(sel), "gap_pp": gap})
    return out


def _eval_block(name: str, rows_eval: list[dict], glob: PlattCalibrator,
                segs: dict[str, dict], art_cal: PlattCalibrator) -> dict:
    variants = {
        "artefato(global atual)": [(art_cal.predict_proba(r["p_raw"]), r["y"]) for r in rows_eval],
        "global(fit split)": [(glob.predict_proba(r["p_raw"]), r["y"]) for r in rows_eval],
        "SEGMENTADO(fit split)": [(_apply_seg(r["p_raw"], r["seg"], glob, segs), r["y"]) for r in rows_eval],
    }
    print(f"\n--- {name} (n={len(rows_eval)}) ---")
    print(f"{'variante':26} {'logloss':>9} {'ece':>8} {'nota':>6}   bandas-fav gap_pp (1.30-1.50 | 1.50-1.75 | 1.75-2.10)")
    res = {}
    for vn, rows in variants.items():
        m = _metrics(rows)
        gaps = _fav_band_gaps(rows)
        gtxt = " | ".join(f"{g['gap_pp']:.2f}(n={g['n']})" if g["gap_pp"] == g["gap_pp"] else "-" for g in gaps)
        print(f"{vn:26} {m['logloss']:>9.4f} {m['ece']:>8.4f} {_grade_from_logloss(m['logloss']):>6.2f}   {gtxt}")
        res[vn] = {"logloss": m["logloss"], "ece": m["ece"], "gaps": gaps}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Eval OOS: calibracao por segmento vs global.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--season", type=int, default=None)
    args = ap.parse_args()

    csvs = default_csvs()
    frames = []
    for p in csvs:
        try:
            df = load_oracle_elixir_games(p, keep_playoffs=None)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"skip {p}: {e}")
    games = pd.concat(frames, ignore_index=True, join="inner")
    games["gameid"] = games["gameid"].astype(str)
    games["date"] = pd.to_datetime(games["date"], errors="coerce")
    games = games.dropna(subset=["date"]).drop_duplicates(subset=["gameid"], keep="last")
    games = games.sort_values(["date", "gameid"]).reset_index(drop=True)

    season = int(args.season) if args.season is not None else int(pd.to_numeric(games["year"], errors="coerce").max())
    domestic_by_year = _infer_team_domestic_league_by_year(games)
    team_meta = _infer_team_meta_latest(domestic_by_year)

    art = MLArtifact.load_json(str(args.artifact))
    model = art.model
    art_cal = art.calibrator

    rows: list[dict] = []
    for r in games.itertuples(index=False):
        try:
            if int(getattr(r, "year", 0)) != season:
                continue
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        lg_match = str(getattr(r, "league", "") or "OTHER")
        bl = _resolve_home_league(team=str(r.blue), year=season, match_league=lg_match,
                                  domestic_by_year=domestic_by_year, team_meta_latest=team_meta)
        rl = _resolve_home_league(team=str(r.red), year=season, match_league=lg_match,
                                  domestic_by_year=domestic_by_year, team_meta_latest=team_meta)
        p_raw = float(model.p_blue(str(r.blue), str(r.red), blue_league=bl, red_league=rl,
                                   blue_tier=str(tier_for_league(bl)), red_tier=str(tier_for_league(rl))))
        inter = bl != rl
        major = (str(tier_for_league(bl)) == "T1") and (str(tier_for_league(rl)) == "T1")
        try:
            po = bool(int(float(getattr(r, "playoffs", 0) or 0)))
        except (TypeError, ValueError):
            po = False
        rows.append({"p_raw": p_raw, "y": y, "seg": _seg_key(inter, major, po),
                     "month": int(pd.to_datetime(r.date).month)})

    print(f"=== EVAL CALIBRACAO POR SEGMENTO - season={season} - n={len(rows)} ===")
    seg_counts: dict[str, int] = {}
    for r in rows:
        seg_counts[r["seg"]] = seg_counts.get(r["seg"], 0) + 1
    for seg, n in sorted(seg_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {seg:22} n={n}")

    # SPLIT PRINCIPAL: fit jan-abr -> eval mai+
    fit_rows = [r for r in rows if r["month"] <= 4]
    ev_rows = [r for r in rows if r["month"] >= 5]
    glob, segs = _fit_segmented(fit_rows)
    print(f"\n[fit jan-abr n={len(fit_rows)}] global a={glob.a:.3f} b={glob.b:.3f}")
    for seg, node in sorted(segs.items()):
        print(f"  {seg:22} n={node['n']:>5} w={node['w']:.2f} a={node['a']:.3f} b={node['b']:+.3f} (puro a={node['a_pure']:.3f})")
    res_main = _eval_block("EVAL PRINCIPAL: mai+ (fit jan-abr)", ev_rows, glob, segs, art_cal)

    # SPLIT REVERSO: fit mar+ -> eval jan-fev (robustez inicio de season)
    fit2 = [r for r in rows if r["month"] >= 3]
    ev2 = [r for r in rows if r["month"] <= 2]
    glob2, segs2 = _fit_segmented(fit2)
    res_rev = _eval_block("EVAL REVERSO: jan-fev (fit mar+)", ev2, glob2, segs2, art_cal)

    # GATE
    def _ll(res, k):
        return float(res[k]["logloss"])
    main_gain = _ll(res_main, "global(fit split)") - _ll(res_main, "SEGMENTADO(fit split)")
    rev_gain = _ll(res_rev, "global(fit split)") - _ll(res_rev, "SEGMENTADO(fit split)")
    band0_glob = res_main["global(fit split)"]["gaps"][0]["gap_pp"]
    band0_seg = res_main["SEGMENTADO(fit split)"]["gaps"][0]["gap_pp"]
    print("\n=== GATE ===")
    print(f"ganho logloss eval principal (seg vs global): {main_gain:+.5f}")
    print(f"ganho logloss eval jan-fev   (seg vs global): {rev_gain:+.5f}")
    print(f"banda 1.30-1.50 gap_pp: global={band0_glob:.2f} seg={band0_seg:.2f}")
    ok = (main_gain > 0.0005) and (rev_gain > -0.0010) and (band0_seg <= band0_glob + 0.5)
    print(f"DECISAO: {'ACCEPT' if ok else 'REJECT'} (criterio: ganho>0.0005 no principal, "
          f"sem piora >0.001 no jan-fev, banda 1.30-1.50 nao piora >0.5pp)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
