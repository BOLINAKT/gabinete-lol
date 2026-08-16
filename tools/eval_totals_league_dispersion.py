# -*- coding: utf-8 -*-
"""GATE: dispersão CONDICIONAL por liga melhora os totais normais vs V0?

Candidato F5 da campanha (2026-07-17). A alavanca K provou que mexer na
dispersão GLOBAL piora (a folga do V0 absorve erro de estimação da média).
Tese aqui é outra: ligas diferentes têm volatilidade diferente EM TORNO da
média prevista (resíduo condicional) — LCK estável, ligas menores caóticas.
Se a razão de dispersão por liga (rho) for estável, sd' = sd × rho afia onde
o jogo é previsível e alarga onde não é.

Só mercados NORMAIS (kills/torres/tempo): prob_over_from_total ignora sd nos
Poisson (dragões/barões/inibs) — dispersão por liga lá exigiria outra família
de distribuição (fora deste gate).

Protocolo (mesma régua do eval_totals_dixon_coles):
- replay prequencial por season (2024, 2025, 2026), V0 fiel (build_profile
  hl=180, MIN_HIST=8), coletando por jogo: liga, z=(real−média)/sd, (mean,sd,y);
- rho por liga×mercado é STREAMING (só passado, com shrinkage n/(n+K) p/ 1.0
  e cap), estado atravessa as seasons em ordem cronológica = prequencial puro;
- K (shrinkage) tunado SÓ em 2025 (estado aquecido por 2024); avaliação CEGA
  em 2026 (Brier nas linhas padrão) V0 vs disp. ACCEPT se ganho > 0.0005.

Uso: python tools/eval_totals_league_dispersion.py
"""
from __future__ import annotations

import math
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.fit_samples_core import _load_team_games_multi  # noqa: E402
from mlcore.lines_engine import MatchupTotals, build_profile, matchup_expected_totals, prob_over_from_total  # noqa: E402
from mlcore.stats_teams import Filters  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

RECORD_YEARS = (2024, 2025, 2026)
TUNE_YEAR, EVAL_YEAR = 2025, 2026
MIN_HIST, HALF_LIFE_V0 = 8, 180.0
K_GRID = (30.0, 60.0, 120.0, 240.0)
RHO_MIN, RHO_MAX = 0.75, 1.35
MARKETS = [("kills", 27.5, "kills_for", "kills_against"),
           ("towers", 11.5, "towers_for", "towers_against"),
           ("time", 32.5, "game_time_min", None)]


def collect_season(tg: pd.DataFrame, season: int) -> list[dict]:
    """Replay prequencial da season; um registro por jogo×mercado com o V0 fiel."""
    g = tg[(tg["date"].dt.year == season) & (tg["team"].astype(str) < tg["opponent"].astype(str))]
    g = g.sort_values("date").reset_index(drop=True)
    flt = Filters()
    out: list[dict] = []
    cache: dict = {}
    last_cut, hist = None, None
    for idx, r in enumerate(g.itertuples(index=False)):
        cut = pd.Timestamp(r.date).normalize()
        if last_cut is None or cut != last_cut:
            hist = tg[tg["date"] < cut]
            cache.clear()
            last_cut = cut
        if hist is None or hist.empty:
            continue

        def _prof(team: str):
            if team not in cache:
                cache[team] = build_profile(hist, team=str(team), filters=flt, half_life_days=HALF_LIFE_V0)
            return cache[team]

        pA, pB = _prof(str(r.team)), _prof(str(r.opponent))
        if int(getattr(pA, "n_games", 0)) < MIN_HIST or int(getattr(pB, "n_games", 0)) < MIN_HIST:
            continue
        totals = matchup_expected_totals(pA, pB)
        day = int(r.date.toordinal())
        league = str(getattr(r, "league", "") or "").strip() or "?"
        for metric, line, cf, ca in MARKETS:
            tot = totals.get(metric)
            if tot is None or not math.isfinite(float(tot.mean)) or not math.isfinite(float(tot.sd)) or float(tot.sd) <= 1e-6:
                continue
            try:
                actual = float(getattr(r, cf)) if ca is None else \
                    float(getattr(r, cf)) + float(getattr(r, ca))
            except (TypeError, ValueError, AttributeError):
                continue
            if not math.isfinite(actual):
                continue
            out.append({
                "year": season, "day": day, "league": league, "metric": metric,
                "mean": float(tot.mean), "sd": float(tot.sd), "line": float(line),
                "y": 1 if actual > line else 0,
                "z": (actual - float(tot.mean)) / float(tot.sd),
            })
        if (idx + 1) % 1500 == 0:
            print(f"  {season}: {idx + 1}/{len(g)}", flush=True)
    return out


def _brier(rows: list[tuple[float, int]]) -> float:
    return sum((p - y) ** 2 for p, y in rows) / len(rows) if rows else float("nan")


def apply_variant(records: list[dict], k: float, score_year: int, freeze_year: int | None = None):
    """rho por liga×mercado só do passado; devolve (p,y) por variante.

    freeze_year: se dado, o estado PARA de aprender após esse ano (variante
    "mapa congelado" = o que um deploy com constantes regeneradas no retreino
    veria). None = streaming puro."""
    state: dict[tuple[str, str], list[float]] = {}
    out = {m[0]: {"v0": [], "disp": []} for m in MARKETS}
    for rec in records:
        key = (rec["metric"], rec["league"])
        n, sz2 = state.get(key, (0.0, 0.0))
        rho = math.sqrt((sz2 + k) / (n + k)) if (n + k) > 0 else 1.0
        rho = min(max(rho, RHO_MIN), RHO_MAX)
        if rec["year"] == score_year:
            t0 = MatchupTotals(mean=rec["mean"], sd=rec["sd"], dist="normal")
            td = MatchupTotals(mean=rec["mean"], sd=rec["sd"] * rho, dist="normal")
            p0 = prob_over_from_total(t0, rec["line"])
            pdx = prob_over_from_total(td, rec["line"])
            if math.isfinite(p0) and math.isfinite(pdx):
                out[rec["metric"]]["v0"].append((p0, rec["y"]))
                out[rec["metric"]]["disp"].append((pdx, rec["y"]))
        if freeze_year is None or rec["year"] <= freeze_year:
            state[key] = [n + 1.0, sz2 + rec["z"] ** 2]
    return out, state


def main() -> int:
    tg = _load_team_games_multi(default_csvs()).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    tg["game_time_min"] = pd.to_numeric(tg["gamelength"], errors="coerce") / 60.0
    print(f"[disp] mapas: {len(tg)} | tune K em {TUNE_YEAR} | eval cego {EVAL_YEAR}")

    cache_path = ROOT / "evidence" / "eval_totals_league_dispersion_records.parquet"
    if cache_path.exists():
        records = pd.read_parquet(cache_path).to_dict("records")
        print(f"[disp] registros do cache: {len(records)} ({cache_path.name})")
    else:
        records = []
        for season in RECORD_YEARS:
            print(f"[disp] replay {season}...", flush=True)
            records.extend(collect_season(tg, season))
        records.sort(key=lambda r: r["day"])
        pd.DataFrame(records).to_parquet(cache_path, index=False)
        print(f"[disp] registros: {len(records)} (cache salvo)")

    tune = [r for r in records if r["year"] <= TUNE_YEAR]
    print(f"\n[disp] tune de K em {TUNE_YEAR} (Brier médio dos {len(MARKETS)} mercados):")
    best_k, best_score = None, float("inf")
    for k in K_GRID:
        res, _ = apply_variant(tune, k, TUNE_YEAR)
        score = sum(_brier(res[m[0]]["disp"]) for m in MARKETS) / len(MARKETS)
        print(f"  K={k:>5.0f} -> brier medio {score:.5f}", flush=True)
        if score < best_score:
            best_score, best_k = score, k
    print(f"[disp] K* = {best_k}")

    print(f"\n[disp] EVAL {EVAL_YEAR} (cego) — streaming E mapa congelado (deploy fiel):")
    res, state = apply_variant(records, float(best_k), EVAL_YEAR)
    res_frozen, _ = apply_variant(records, float(best_k), EVAL_YEAR, freeze_year=TUNE_YEAR)
    print(f"\n{'mercado':9} {'n':>5} {'brierV0':>9} {'STREAM':>9} {'difS':>9} {'FROZEN':>9} {'difF':>9} {'veredito':>9}")
    for metric, _line, _cf, _ca in MARKETS:
        b0 = _brier(res[metric]["v0"])
        bd = _brier(res[metric]["disp"])
        bf = _brier(res_frozen[metric]["disp"])
        n = len(res[metric]["v0"])
        gain_s, gain_f = b0 - bd, b0 - bf
        best_gain = max(gain_s, gain_f)
        verdict = "ACCEPT" if best_gain > 0.0005 else ("neutro" if best_gain > -0.0005 else "REJECT")
        print(f"{metric:9} {n:>5} {b0:>9.5f} {bd:>9.5f} {gain_s:>+9.5f} {bf:>9.5f} {gain_f:>+9.5f} {verdict:>9}")

    print("\n[disp] rho final por liga (top-12 por n, K*):")
    rows = []
    for (metric, league), (n, sz2) in state.items():
        rho = min(max(math.sqrt((sz2 + best_k) / (n + best_k)), RHO_MIN), RHO_MAX)
        rows.append((metric, league, int(n), rho))
    rows.sort(key=lambda x: -x[2])
    for metric, league, n, rho in rows[:12]:
        print(f"  {metric:8} {league:12} n={n:>5} rho={rho:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
