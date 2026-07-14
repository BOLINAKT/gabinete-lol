# -*- coding: utf-8 -*-
"""GATE: o DRAFT ajusta as linhas de totais? (pedido do usuário 2026-07-05)

Intuição dele: "se for draftado fiora, gnar, trundle — bonecos com muita força
na side — o valor das torres tende a subir... mas tem time que quase
independente do draft não vai bater em torre."

Método (dois testes):
1. EFEITO PRINCIPAL: resíduo do total (real − média V0 prequencial do motor)
   ~ sinal de draft do mercado (somas dos macro_scores das duas comps, fórmulas
   do comp_archetype_core/comp_compare). Fit em 2025, avaliação CEGA em 2026:
   Brier nas linhas padrão com a média deslocada vs V0.
2. INTERAÇÃO time×draft (a ressalva dele): sinal × tendência do matchup
   (média V0 padronizada) — o draft de side só sobe torre de quem já bate torre?

Se o Brier 2026 não melhorar, o ajuste NÃO entra no produto.

Uso: python tools/eval_draft_totals_adjust.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_core.champion_knowledge_core import load_champion_knowledge_registry  # noqa: E402
from app_core.comp_archetype_core import build_comp_profile  # noqa: E402
from app_core.players_data_core import load_player_rows  # noqa: E402
from app_core.radar_confronto_core import ROLE_ORDER, norm_position  # noqa: E402
from mlcore.fit_samples_core import _load_team_games_multi  # noqa: E402
from mlcore.lines_engine import MatchupTotals, build_profile, matchup_expected_totals, prob_over_from_total  # noqa: E402
from mlcore.stats_teams import Filters  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

FIT_YEAR, EVAL_YEAR = 2025, 2026
MIN_HIST, HALF_LIFE = 8, 180.0
MARKETS = [("kills", 27.5, "kills_for", "kills_against"),
           ("towers", 11.5, "towers_for", "towers_against"),
           ("dragons", 4.5, "dragons_for", "dragons_against"),
           ("time", 32.5, "game_time_min", None)]


def _game_macros(csvs: list[str]) -> dict[tuple[str, str], dict]:
    """(gameid, teamname) -> macro_scores da comp (cache por tupla de picks)."""
    reg = load_champion_knowledge_registry()
    prof_cache: dict[tuple, dict] = {}
    out: dict[tuple[str, str], dict] = {}
    for csv in csvs:
        pdf = load_player_rows(csv_path=str(csv))
        for (gid, team), grp in pdf.groupby(["gameid", "teamname"]):
            pos = {}
            for r in grp.itertuples(index=False):
                p = norm_position(getattr(r, "position", ""))
                c = str(getattr(r, "champion", "") or "").strip()
                if p and c and p not in pos:
                    pos[p] = c
            if len(pos) < 5:
                continue
            picks = tuple(pos[r] for r in ROLE_ORDER)
            if picks not in prof_cache:
                prof_cache[picks] = build_comp_profile(
                    registry=reg, picks=list(picks), role_order=list(ROLE_ORDER),
                )["macro_scores"]
            out[(str(gid), str(team))] = prof_cache[picks]
    return out


def _signals(ma: dict, mb: dict) -> dict[str, float]:
    def s(k: str) -> float:
        return float(ma.get(k, 0) or 0) + float(mb.get(k, 0) or 0)
    return {
        "towers": 1.45 * s("side_pressure") + 0.25 * s("siege_pressure") + 0.15 * s("objective_setup"),
        "dragons": 0.60 * s("objective_setup") + 0.30 * s("fight_reliability") + 0.18 * s("tempo_pressure"),
        "kills": 0.65 * s("dive_threat") + 0.50 * s("pick_threat") + 0.35 * s("tempo_pressure") - 0.25 * s("anti_dive"),
        "time": s("carry_scaling") + 0.45 * s("fight_reliability") - 0.55 * s("tempo_pressure") - 0.35 * s("dive_threat"),
    }


def main() -> int:
    csvs = default_csvs()
    print("[draft_totals] carregando picks/macros...")
    macros = _game_macros([str(c) for c in csvs])
    print(f"[draft_totals] comps com macro: {len(macros)}")

    tg = _load_team_games_multi(csvs).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    rows: dict[str, dict[int, list]] = {m[0]: {FIT_YEAR: [], EVAL_YEAR: []} for m in MARKETS}
    flt = Filters()

    for season in (FIT_YEAR, EVAL_YEAR):
        g = tg[(tg["date"].dt.year == season) & (tg["team"].astype(str) < tg["opponent"].astype(str))].copy()
        g = g.sort_values("date").reset_index(drop=True)
        print(f"[draft_totals] season {season}: {len(g)} mapas")
        cache: dict = {}
        last_cut, hist = None, None
        for idx, r in enumerate(g.itertuples(index=False)):
            cut = pd.Timestamp(r.date).normalize()
            if last_cut is None or cut != last_cut:
                hist = tg[tg["date"] < cut]
                cache.clear()
                last_cut = cut
            gid = str(r.gameid)
            ma, mb = macros.get((gid, str(r.team))), macros.get((gid, str(r.opponent)))
            if ma is None or mb is None or hist is None or hist.empty:
                continue

            def _prof(team: str):
                if team not in cache:
                    cache[team] = build_profile(hist, team=str(team), filters=flt, half_life_days=HALF_LIFE)
                return cache[team]

            pA, pB = _prof(str(r.team)), _prof(str(r.opponent))
            if int(getattr(pA, "n_games", 0)) < MIN_HIST or int(getattr(pB, "n_games", 0)) < MIN_HIST:
                continue
            totals = matchup_expected_totals(pA, pB)
            sigs = _signals(ma, mb)
            for metric, line, col_for, col_against in MARKETS:
                tot = totals.get(metric)
                if tot is None or not math.isfinite(float(tot.mean)):
                    continue
                try:
                    actual = float(getattr(r, col_for)) if col_against is None else \
                        float(getattr(r, col_for)) + float(getattr(r, col_against))
                except (TypeError, ValueError, AttributeError):
                    continue
                if not math.isfinite(actual):
                    continue
                rows[metric][season].append(
                    (float(tot.mean), float(tot.sd), str(tot.dist), actual, float(sigs[metric]), float(line)))
            if (idx + 1) % 1500 == 0:
                print(f"  {idx + 1}/{len(g)}", flush=True)

    print(f"\n{'mercado':9} {'n_fit':>6} {'b_sinal':>8} {'t':>6} {'b_inter':>8} {'t':>6} | "
          f"{'n_2026':>6} {'brierV0':>8} {'brierADJ':>9} {'dif':>8} {'veredito':>9}")
    for metric, line, _cf, _ca in MARKETS:
        fit = rows[metric][FIT_YEAR]
        ev = rows[metric][EVAL_YEAR]
        if len(fit) < 500 or len(ev) < 500:
            print(f"{metric:9} amostra insuficiente ({len(fit)}/{len(ev)})")
            continue
        mean0 = np.array([x[0] for x in fit]); act = np.array([x[3] for x in fit])
        sig = np.array([x[4] for x in fit])
        resid = act - mean0
        sig_mu, sig_sd = float(sig.mean()), float(sig.std() or 1.0)
        m_mu, m_sd = float(mean0.mean()), float(mean0.std() or 1.0)
        zs = (sig - sig_mu) / sig_sd
        zm = (mean0 - m_mu) / m_sd
        # OLS com intercepto: resid ~ a + b*zs + c*(zs*zm)
        X = np.column_stack([np.ones_like(zs), zs, zs * zm])
        beta, *_ = np.linalg.lstsq(X, resid, rcond=None)
        pred = X @ beta
        s2 = float(((resid - pred) ** 2).sum() / (len(resid) - 3))
        cov = s2 * np.linalg.inv(X.T @ X)
        t_b = beta[1] / math.sqrt(cov[1, 1]); t_c = beta[2] / math.sqrt(cov[2, 2])

        # avaliação cega 2026: média deslocada por a + b*zs (+ c*zs*zm se |t|>=2)
        use_inter = abs(t_c) >= 2.0
        v0_rows, adj_rows = [], []
        for mean_e, sd_e, dist_e, act_e, sig_e, line_e in ev:
            zs_e = (sig_e - sig_mu) / sig_sd
            zm_e = (mean_e - m_mu) / m_sd
            delta = beta[0] + beta[1] * zs_e + (beta[2] * zs_e * zm_e if use_inter else 0.0)
            y = 1 if act_e > line_e else 0
            t0 = MatchupTotals(mean=mean_e, sd=sd_e, dist=dist_e)  # type: ignore[arg-type]
            ta = MatchupTotals(mean=max(mean_e + delta, 0.1), sd=sd_e, dist=dist_e)  # type: ignore[arg-type]
            p0, pa = prob_over_from_total(t0, line_e), prob_over_from_total(ta, line_e)
            if math.isfinite(p0) and math.isfinite(pa):
                v0_rows.append((p0, y)); adj_rows.append((pa, y))
        b0 = sum((p - y) ** 2 for p, y in v0_rows) / len(v0_rows)
        ba = sum((p - y) ** 2 for p, y in adj_rows) / len(adj_rows)
        verdict = "ACCEPT" if (b0 - ba) > 0.0005 else ("neutro" if (b0 - ba) > -0.0005 else "REJECT")
        print(f"{metric:9} {len(fit):>6} {beta[1]:>+8.3f} {t_b:>+6.1f} {beta[2]:>+8.3f} {t_c:>+6.1f} | "
              f"{len(v0_rows):>6} {b0:>8.4f} {ba:>9.4f} {b0 - ba:>+8.4f} {verdict:>9}"
              + ("  [c/ interação]" if use_inter else ""))
        # Constantes de deploy (delta = a + b*(sig − mu)/sd):
        print(f"{'':9} CONST {metric}: a={beta[0]:+.4f} b={beta[1]:+.4f} sig_mu={sig_mu:.4f} sig_sd={sig_sd:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
