# -*- coding: utf-8 -*-
"""GATE: estimador Dixon-Coles (ataque/defesa multiplicativo com decaimento
temporal) melhora a MÉDIA dos totais vs o motor atual (V0)?

Último candidato da pesquisa de nota (2026-07-05). O clássico do futebol:
  E[kills que A faz vs B] = média_liga × ataque_A × defesa_B
com forma recente pesando mais (decaimento exponencial). A alavanca K provou
que a VARIÂNCIA do V0 está certa; isto ataca a MÉDIA (o erro de estimação do
matchup com amostra pequena — o pool da liga inteira estabiliza).

Protocolo: prequencial; half-life do decaimento tunado SÓ em 2025; avaliação
CEGA em 2026 (Brier nas linhas padrão) para V0, DC puro e BLEND 50/50.
Fallback honesto: sem histórico mínimo (8 jogos efetivos), DC cai no V0.

Uso: python tools/eval_totals_dixon_coles.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.fit_samples_core import _load_team_games_multi  # noqa: E402
from mlcore.lines_engine import MatchupTotals, build_profile, matchup_expected_totals, prob_over_from_total  # noqa: E402
from mlcore.stats_teams import Filters  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

FIT_YEAR, EVAL_YEAR = 2025, 2026
MIN_HIST, HALF_LIFE_V0 = 8, 180.0
MIN_EFF_GAMES_DC = 8.0
HL_GRID = (60.0, 120.0, 240.0, 480.0)
MARKETS = [("kills", 27.5, "kills_for", "kills_against"),
           ("towers", 11.5, "towers_for", "towers_against"),
           ("dragons", 4.5, "dragons_for", "dragons_against"),
           ("barons", 1.5, "barons_for", "barons_against"),
           ("inhibitors", 1.5, "inhibitors_for", "inhibitors_against"),
           ("time", 32.5, "game_time_min", None)]


class DecayedMean:
    """Média com decaimento exponencial (half-life em dias), atualização lazy."""

    __slots__ = ("w", "wx", "day", "hl")

    def __init__(self, hl: float):
        self.w = 0.0
        self.wx = 0.0
        self.day = None
        self.hl = float(hl)

    def _decay_to(self, day: int) -> None:
        if self.day is not None and day > self.day:
            f = 0.5 ** ((day - self.day) / self.hl)
            self.w *= f
            self.wx *= f
        self.day = day if self.day is None else max(self.day, day)

    def add(self, day: int, x: float) -> None:
        self._decay_to(day)
        self.w += 1.0
        self.wx += float(x)

    def mean(self, day: int) -> float:
        self._decay_to(day)
        return self.wx / self.w if self.w > 1e-9 else float("nan")

    def eff_n(self, day: int) -> float:
        self._decay_to(day)
        return self.w


class DCState:
    """Por métrica: liga (média global) + ataque/defesa por time."""

    def __init__(self, hl: float):
        self.hl = float(hl)
        self.league = DecayedMean(hl)
        self.att: dict[str, DecayedMean] = {}
        self.deff: dict[str, DecayedMean] = {}

    def _get(self, d: dict, team: str) -> DecayedMean:
        if team not in d:
            d[team] = DecayedMean(self.hl)
        return d[team]

    def update(self, day: int, team: str, opp: str, x_for: float, x_against: float) -> None:
        self.league.add(day, x_for)
        self.league.add(day, x_against)
        self._get(self.att, team).add(day, x_for)
        self._get(self.deff, team).add(day, x_against)
        self._get(self.att, opp).add(day, x_against)
        self._get(self.deff, opp).add(day, x_for)

    def total_mean(self, day: int, a: str, b: str) -> float:
        lm = self.league.mean(day)
        if not math.isfinite(lm) or lm <= 1e-9:
            return float("nan")
        for d, t in ((self.att, a), (self.deff, a), (self.att, b), (self.deff, b)):
            if self._get(d, t).eff_n(day) < MIN_EFF_GAMES_DC:
                return float("nan")
        att_a = self.att[a].mean(day) / lm
        def_a = self.deff[a].mean(day) / lm
        att_b = self.att[b].mean(day) / lm
        def_b = self.deff[b].mean(day) / lm
        return lm * (att_a * def_b) + lm * (att_b * def_a)


def _brier(rows: list[tuple[float, int]]) -> float:
    return sum((p - y) ** 2 for p, y in rows) / len(rows) if rows else float("nan")


def run_season(tg: pd.DataFrame, season: int, hl_dc: float) -> dict[str, dict[str, list]]:
    """Replay prequencial da season: coleta (p, y) para V0, DC e blend."""
    dc: dict[str, DCState] = {m[0]: DCState(hl_dc) for m in MARKETS}
    # aquece o DC com TODO o histórico anterior à season (prequencial de verdade)
    hist_all = tg[tg["date"].dt.year < season].sort_values("date")
    for r in hist_all.itertuples(index=False):
        if str(r.team) >= str(r.opponent):
            continue
        day = int(r.date.toordinal())
        for metric, _l, cf, ca in MARKETS:
            try:
                xf = float(getattr(r, cf))
                xa = float(getattr(r, ca)) if ca else float("nan")
            except (TypeError, ValueError, AttributeError):
                continue
            if ca is None:
                if math.isfinite(xf):
                    dc[metric].league.add(day, xf)
                    dc[metric]._get(dc[metric].att, str(r.team)).add(day, xf)
                    dc[metric]._get(dc[metric].att, str(r.opponent)).add(day, xf)
                continue
            if math.isfinite(xf) and math.isfinite(xa):
                dc[metric].update(day, str(r.team), str(r.opponent), xf, xa)

    g = tg[(tg["date"].dt.year == season) & (tg["team"].astype(str) < tg["opponent"].astype(str))]
    g = g.sort_values("date").reset_index(drop=True)
    flt = Filters()
    out: dict[str, dict[str, list]] = {m[0]: {"v0": [], "dc": [], "blend": []} for m in MARKETS}
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
        day = int(r.date.toordinal())
        if int(getattr(pA, "n_games", 0)) >= MIN_HIST and int(getattr(pB, "n_games", 0)) >= MIN_HIST:
            totals = matchup_expected_totals(pA, pB)
            for metric, line, cf, ca in MARKETS:
                tot = totals.get(metric)
                if tot is None or not math.isfinite(float(tot.mean)):
                    continue
                try:
                    actual = float(getattr(r, cf)) if ca is None else \
                        float(getattr(r, cf)) + float(getattr(r, ca))
                except (TypeError, ValueError, AttributeError):
                    continue
                if not math.isfinite(actual):
                    continue
                y = 1 if actual > line else 0
                m_dc = dc[metric].total_mean(day, str(r.team), str(r.opponent)) if ca else \
                    (dc[metric].att[str(r.team)].mean(day) + dc[metric].att[str(r.opponent)].mean(day)) / 2.0 \
                    if (str(r.team) in dc[metric].att and str(r.opponent) in dc[metric].att) else float("nan")
                p0 = prob_over_from_total(tot, line)
                if math.isfinite(p0):
                    out[metric]["v0"].append((p0, y))
                for tag, mean_x in (("dc", m_dc), ("blend", 0.5 * float(tot.mean) + 0.5 * m_dc
                                                  if math.isfinite(m_dc) else float("nan"))):
                    mean_use = mean_x if math.isfinite(mean_x) else float(tot.mean)
                    tx = MatchupTotals(mean=max(mean_use, 0.1), sd=tot.sd, dist=tot.dist)
                    px = prob_over_from_total(tx, line)
                    if math.isfinite(px):
                        out[metric][tag].append((px, y))

        # update DC com o jogo de hoje (após prever)
        for metric, _l, cf, ca in MARKETS:
            try:
                xf = float(getattr(r, cf))
                xa = float(getattr(r, ca)) if ca else float("nan")
            except (TypeError, ValueError, AttributeError):
                continue
            if ca is None:
                if math.isfinite(xf):
                    dc[metric].league.add(day, xf)
                    dc[metric]._get(dc[metric].att, str(r.team)).add(day, xf)
                    dc[metric]._get(dc[metric].att, str(r.opponent)).add(day, xf)
            elif math.isfinite(xf) and math.isfinite(xa):
                dc[metric].update(day, str(r.team), str(r.opponent), xf, xa)
        if (idx + 1) % 1500 == 0:
            print(f"  {idx + 1}/{len(g)}", flush=True)
    return out


def main() -> int:
    tg = _load_team_games_multi(default_csvs()).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    tg["game_time_min"] = pd.to_numeric(tg["gamelength"], errors="coerce") / 60.0
    print(f"[dc] mapas: {len(tg)} | fit hl em {FIT_YEAR} | eval cego {EVAL_YEAR}")

    print(f"[dc] tune do half-life em {FIT_YEAR} (Brier médio dos 6 mercados, variante blend):")
    best_hl, best_score = None, float("inf")
    for hl in HL_GRID:
        res = run_season(tg, FIT_YEAR, hl)
        score = sum(_brier(res[m[0]]["blend"]) for m in MARKETS) / len(MARKETS)
        print(f"  hl={hl:>5.0f}d -> brier medio {score:.4f}", flush=True)
        if score < best_score:
            best_score, best_hl = score, hl
    print(f"[dc] hl* = {best_hl}")

    print(f"\n[dc] EVAL {EVAL_YEAR} (cego):")
    res = run_season(tg, EVAL_YEAR, float(best_hl))
    print(f"\n{'mercado':11} {'n':>5} {'brierV0':>8} {'brierDC':>8} {'brierBL':>8} {'difDC':>8} {'difBL':>8} {'veredito':>9}")
    for metric, line, _cf, _ca in MARKETS:
        b0 = _brier(res[metric]["v0"])
        bd = _brier(res[metric]["dc"])
        bb = _brier(res[metric]["blend"])
        n = len(res[metric]["v0"])
        best_gain = max(b0 - bd, b0 - bb)
        verdict = "ACCEPT" if best_gain > 0.0005 else ("neutro" if best_gain > -0.0005 else "REJECT")
        print(f"{metric:11} {n:>5} {b0:>8.4f} {bd:>8.4f} {bb:>8.4f} {b0 - bd:>+8.4f} {b0 - bb:>+8.4f} {verdict:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
