"""SCORECARD DE TOTAIS — a "nota" do motor de linhas (não existia até 2026-07-03).

Replay prequencial da season: para cada mapa, constrói os perfis dos dois times
usando SÓ jogos anteriores (mesma matemática do produto: build_profile +
matchup_expected_totals) e mede P(over linha-padrão) contra o resultado real.

Compara duas variantes de distribuição:
  V0 (atual):       dragões/barões/inibs = Poisson (sd=sqrt(média)); resto normal.
  V1 (sd empírico): mesmas médias, mas os mercados Poisson usam Normal com o sd
                    COMBINADO empírico dos perfis (a mesma receita do kills).
Motivação (alavanca K): medido em 2026-07-03, os totais desses mercados são
SUBDISPERSOS (var/média 0.27-0.49) → o sd Poisson é ~2x largo → P(over) achatada.

  python tools/totals_scorecard.py            # season mais recente, linhas padrão
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.fit_samples_core import _load_team_games_multi
from mlcore.lines_engine import (
    MatchupTotals,
    _combine_sd,
    _norm_cdf,
    apply_dc_blend,
    apply_time_sd_calibration,
    build_profile,
    matchup_expected_totals,
    prob_over_from_total,
)
from mlcore.stats_teams import Filters
from tools.ml_quality_scorecard import default_csvs

# (métrica do engine, linha padrão, colunas for/against no team_games)
MARKETS = [
    ("kills", 27.5, "kills_for", "kills_against"),
    ("towers", 11.5, "towers_for", "towers_against"),
    ("dragons", 4.5, "dragons_for", "dragons_against"),
    ("barons", 1.5, "barons_for", "barons_against"),
    ("inhibitors", 1.5, "inhibitors_for", "inhibitors_against"),
    ("time", 32.5, "game_time_min", None),
]
POISSON_METRICS = {"dragons", "barons", "inhibitors"}
SD_FLOOR = 0.35  # V1: floor pro sd empírico dos mercados discretos


def _metrics(rows: list[tuple[float, int]]) -> dict:
    if not rows:
        return {"n": 0, "brier": float("nan"), "logloss": float("nan"), "ece": float("nan"), "sharp": float("nan")}
    n = len(rows)
    ll = sum(-(y * math.log(min(max(p, 1e-6), 1 - 1e-6)) + (1 - y) * math.log(1 - min(max(p, 1e-6), 1 - 1e-6))) for p, y in rows) / n
    brier = sum((p - y) ** 2 for p, y in rows) / n
    bins: dict[int, list] = {}
    for p, y in rows:
        bins.setdefault(min(9, int(p * 10)), []).append((p, y))
    ece = sum((len(v) / n) * abs(sum(pp for pp, _ in v) / len(v) - sum(yy for _, yy in v) / len(v)) for v in bins.values())
    sharp = sum(abs(p - 0.5) for p, _ in rows) / n
    return {"n": n, "brier": brier, "logloss": ll, "ece": ece, "sharp": sharp}


def _v1_prob_over(metric: str, tot: MatchupTotals, pA, pB, line: float) -> float:
    """V1: mesma média; mercados Poisson viram Normal com sd empírico combinado."""
    if metric not in POISSON_METRICS:
        return prob_over_from_total(tot, line)
    fa = f"{'inhib' if metric == 'inhibitors' else metric}_for_sd"
    ga = f"{'inhib' if metric == 'inhibitors' else metric}_against_sd"
    try:
        sd = math.sqrt(
            _combine_sd(getattr(pA, fa), getattr(pB, ga)) ** 2
            + _combine_sd(getattr(pB, fa), getattr(pA, ga)) ** 2
        )
    except (TypeError, ValueError):
        sd = float("nan")
    if not math.isfinite(sd):
        return prob_over_from_total(tot, line)
    return float(1.0 - _norm_cdf(float(line), float(tot.mean), max(float(sd), SD_FLOOR)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Scorecard de totais (prequencial, V0 Poisson vs V1 sd empírico vs V2 dispersão global).")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--half-life-days", type=float, default=180.0)
    ap.add_argument("--min-hist-games", type=int, default=8, help="Mínimo de jogos no perfil de cada time.")
    args = ap.parse_args()

    tg = _load_team_games_multi(default_csvs())
    tg = tg.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    season = int(args.season) if args.season is not None else int(tg["date"].dt.year.max())

    # V2: fator de dispersão global var/média por mercado, medido SÓ nos anos de
    # TREINO (< season avaliada) — codifica a subdispersão sem o ruído dos perfis.
    train = tg[(tg["date"].dt.year < season) & (tg["team"].astype(str) < tg["opponent"].astype(str))]
    disp_ratio: dict[str, float] = {}
    for metric, _line, col_for, col_against in MARKETS:
        if metric not in POISSON_METRICS:
            continue
        try:
            tot_s = pd.to_numeric(train[col_for], errors="coerce") + pd.to_numeric(train[col_against], errors="coerce")
            tot_s = tot_s.dropna()
            m, v = float(tot_s.mean()), float(tot_s.var())
            disp_ratio[metric] = max(v / m, 0.05) if m > 0 else 1.0
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            disp_ratio[metric] = 1.0
    print(f"[totals_scorecard] fatores de dispersão (treino <{season}): " +
          ", ".join(f"{k}={v:.2f}" for k, v in disp_ratio.items()))

    # Um registro por mapa (lado do team < opponent), season alvo.
    g = tg[(tg["date"].dt.year == season) & (tg["team"].astype(str) < tg["opponent"].astype(str))].copy()
    g = g.sort_values("date").reset_index(drop=True)
    print(f"[totals_scorecard] season={season} | mapas={len(g)} | half_life={args.half_life_days}")

    flt = Filters()
    results: dict[str, dict[str, list]] = {m[0]: {"v0": [], "v1": [], "v2": [], "prod": []} for m in MARKETS}
    profile_cache: dict[tuple[str, str], object] = {}

    last_cut = None
    hist = None
    for idx, r in enumerate(g.itertuples(index=False)):
        cut = pd.Timestamp(r.date).normalize()
        if last_cut is None or cut != last_cut:
            hist = tg[tg["date"] < cut]
            profile_cache.clear()
            last_cut = cut
        if hist is None or hist.empty:
            continue

        def _prof(team: str):
            key = (str(team), str(cut))
            if key not in profile_cache:
                profile_cache[key] = build_profile(
                    hist, team=str(team), filters=flt,
                    half_life_days=float(args.half_life_days),
                )
            return profile_cache[key]

        pA = _prof(r.team)
        pB = _prof(r.opponent)
        if int(getattr(pA, "n_games", 0)) < int(args.min_hist_games) or int(getattr(pB, "n_games", 0)) < int(args.min_hist_games):
            continue
        totals = matchup_expected_totals(pA, pB)
        # "prod" = caminho DEPLOYADO no app (plays_app._expected_totals_dc):
        # blend Dixon-Coles (ACCEPT 07-06) + calibração do sd do tempo
        # (ACCEPT 07-17), prequencial com o hist do dia.
        totals_prod = apply_time_sd_calibration(
            apply_dc_blend(hist, str(r.team), str(r.opponent), totals)
        )

        for metric, line, col_for, col_against in MARKETS:
            tot = totals.get(metric)
            if tot is None or not math.isfinite(float(tot.mean)):
                continue
            try:
                if col_against is None:
                    actual = float(getattr(r, col_for))
                else:
                    actual = float(getattr(r, col_for)) + float(getattr(r, col_against))
            except (TypeError, ValueError, AttributeError):
                continue
            if not math.isfinite(actual):
                continue
            y = 1 if actual > float(line) else 0
            p0 = prob_over_from_total(tot, float(line))
            p1 = _v1_prob_over(metric, tot, pA, pB, float(line))
            if metric in POISSON_METRICS:
                _sd2 = max(math.sqrt(max(float(tot.mean), 1e-6) * disp_ratio.get(metric, 1.0)), SD_FLOOR)
                p2 = float(1.0 - _norm_cdf(float(line), float(tot.mean), _sd2))
            else:
                p2 = p0
            if math.isfinite(p0):
                results[metric]["v0"].append((float(p0), y))
            if math.isfinite(p1):
                results[metric]["v1"].append((float(p1), y))
            if math.isfinite(p2):
                results[metric]["v2"].append((float(p2), y))
            tot_p = totals_prod.get(metric)
            if tot_p is not None and math.isfinite(float(tot_p.mean)):
                pp = prob_over_from_total(tot_p, float(line))
                if math.isfinite(pp):
                    results[metric]["prod"].append((float(pp), y))

        if (idx + 1) % 1000 == 0:
            print(f"[totals_scorecard] {idx + 1}/{len(g)}", flush=True)

    print(f"\n{'mercado':12} {'var':>4} {'n':>5} {'brier':>8} {'logloss':>9} {'ece':>7} {'sharp':>7}")
    for metric, line, _, _ in MARKETS:
        for tag in ("v0", "v1", "v2", "prod"):
            m = _metrics(results[metric][tag])
            label = f"{metric} O{line:g}" if tag == "v0" else ""
            print(f"{label:12} {tag:>4} {m['n']:>5} {m['brier']:>8.4f} {m['logloss']:>9.4f} {m['ece']:>7.4f} {m['sharp']:>7.3f}")
        m0 = _metrics(results[metric]["v0"])
        for tag in ("v1", "v2", "prod"):
            mx = _metrics(results[metric][tag])
            if m0["n"] and mx["n"] and math.isfinite(m0["brier"]) and math.isfinite(mx["brier"]):
                gain = m0["brier"] - mx["brier"]
                dlab = "dP" if tag == "prod" else ("d" + tag[-1])
                print(f"{'':12} {dlab:>4} {'':>5} {gain:>+8.4f}  ({tag} melhor se >0)")

    # NOTA CONSOLIDADA (régua formalizada 18/07): nota = 8.0 - 68*(brier-0.2067),
    # variante PROD (caminho deployado), por mercado; nota dos totais = média.
    def _grade(brier: float) -> float:
        return max(0.0, min(10.0, 8.0 - 68.0 * (brier - 0.2067)))
    per_market = {}
    for metric, _line, _, _ in MARKETS:
        mp = _metrics(results[metric]["prod"])
        if mp["n"] and math.isfinite(mp["brier"]):
            per_market[metric] = round(_grade(mp["brier"]), 2)
    nota_totais = sum(per_market.values()) / len(per_market) if per_market else float("nan")
    print(f"\nNOTA DOS TOTAIS (prod, régua 8.0-68*(brier-0.2067)): {nota_totais:.2f}")
    print("  por mercado: " + ", ".join(f"{k}={v}" for k, v in per_market.items()))
    try:
        import json as _json
        import time as _time
        from pathlib import Path as _Path
        _ev = _Path(__file__).resolve().parents[1] / "evidence"
        _ev.mkdir(exist_ok=True)
        (_ev / "totals_scorecard.json").write_text(_json.dumps({
            "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "nota_totais": round(float(nota_totais), 2) if math.isfinite(nota_totais) else None,
            "por_mercado": per_market, "season": int(season),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
