# -*- coding: utf-8 -*-
"""GATE v2: o DRAFT ajusta os totais? — com feature de TEMPO-DO-CAMPEÃO (data-driven).

Reconfirma, no MESMO protocolo da eval_draft_totals_adjust.py (baseline = motor
de linhas de produção matchup_expected_totals, fit 2025 / eval CEGO 2026, Brier
na linha padrão), mas troca o sinal:

  - ANTIGO: soma de macro_scores de arquétipo (dive/pick/side_pressure...) — feito
    na mão. Deu torres ACCEPT, kills/dragões NEUTRO.
  - NOVO (aqui): "total implícito pelo draft" = média, sobre os 10 campeões do
    jogo, do total médio HISTÓRICO daquele campeão no mercado — construído
    PREQUENCIALMENTE (só de jogos ANTERIORES à data do jogo, sem leakage).

Objetivo: ver se a feature data-driven bate a linha onde a de arquétipo não bateu
(medição 80/20 preliminar sugeriu que sim em kills/torres/drakes). Cospe as
constantes {a,b,sig_mu,sig_sd} p/ o mesmo mecanismo do DRAFT_TOWERS_ADJUST.
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_core.players_data_core import load_player_rows  # noqa: E402
from mlcore.fit_samples_core import _load_team_games_multi  # noqa: E402
from mlcore.lines_engine import MatchupTotals, build_profile, matchup_expected_totals, prob_over_from_total  # noqa: E402
from mlcore.stats_teams import Filters  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

FIT_YEAR, EVAL_YEAR = 2025, 2026
MIN_HIST, HALF_LIFE = 8, 180.0
# mercado -> (linha, coluna do total no team-games via for+against)
MARKETS = [("kills", 27.5, "kills_for", "kills_against"),
           ("towers", 11.5, "towers_for", "towers_against"),
           ("dragons", 4.5, "dragons_for", "dragons_against"),
           ("time", 32.5, "game_time_min", None)]


def _champs_por_jogo(csvs) -> dict[str, list[str]]:
    """gameid -> lista dos campeões do jogo (10)."""
    out: dict[str, list[str]] = defaultdict(list)
    for csv in csvs:
        pdf = load_player_rows(csv_path=str(csv))
        for r in pdf.itertuples(index=False):
            c = str(getattr(r, "champion", "") or "").strip()
            gid = str(getattr(r, "gameid", "") or "")
            if c and gid:
                out[gid].append(c)
    return out


def _prequential_signals(tg: pd.DataFrame, champs: dict, markets) -> dict:
    """gid -> {metric: sinal}, onde sinal = média (sobre os 10 champs) do total
    médio histórico do campeão no mercado, SÓ com jogos de dias ANTERIORES."""
    # gid -> total por mercado (game-level = for+against de qualquer linha do jogo)
    gid_total: dict[str, dict[str, float]] = {}
    gid_date: dict[str, pd.Timestamp] = {}
    for r in tg.itertuples(index=False):
        gid = str(r.gameid)
        if gid in gid_total:
            continue
        d = {}
        for metric, _line, cf, ca in markets:
            try:
                v = float(getattr(r, cf)) if ca is None else float(getattr(r, cf)) + float(getattr(r, ca))
                if math.isfinite(v):
                    d[metric] = v
            except (TypeError, ValueError, AttributeError):
                pass
        gid_total[gid] = d
        gid_date[gid] = pd.Timestamp(r.date).normalize()

    # ordena jogos por data; passa acumulando por DIA (flush após o dia p/ não vazar)
    order = sorted(gid_total.keys(), key=lambda g: gid_date[g])
    csum: dict[str, dict[str, float]] = {m[0]: defaultdict(float) for m in markets}
    ccnt: dict[str, dict[str, int]] = {m[0]: defaultdict(int) for m in markets}
    gsum: dict[str, float] = defaultdict(float)  # global por mercado
    gcnt: dict[str, int] = defaultdict(int)

    signals: dict[str, dict[str, float]] = {}
    buffer_day = None
    day_games: list[str] = []

    def _flush(games):
        for g in games:
            for metric, tot in gid_total[g].items():
                for c in champs.get(g, []):
                    csum[metric][c] += tot
                    ccnt[metric][c] += 1
                gsum[metric] += tot
                gcnt[metric] += 1

    for gid in order:
        day = gid_date[gid]
        if buffer_day is None:
            buffer_day = day
        if day != buffer_day:
            _flush(day_games)
            day_games = []
            buffer_day = day
        # sinal do jogo com a tabela ATUAL (só dias anteriores)
        sig = {}
        for metric, _line, _cf, _ca in markets:
            gmean = (gsum[metric] / gcnt[metric]) if gcnt[metric] else 0.0
            vals = []
            for c in champs.get(gid, []):
                if ccnt[metric][c] > 0:
                    vals.append(csum[metric][c] / ccnt[metric][c])
            sig[metric] = float(np.mean(vals)) if vals else gmean
        signals[gid] = sig
        day_games.append(gid)
    _flush(day_games)
    return signals


def main() -> int:
    csvs = [str(c) for c in default_csvs()]
    print("[champ_tempo] carregando picks...")
    champs = _champs_por_jogo(csvs)
    print(f"[champ_tempo] jogos com picks: {len(champs)}")

    tg = _load_team_games_multi(csvs).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    print("[champ_tempo] construindo sinais prequenciais (tempo do campeão)...")
    signals = _prequential_signals(tg, champs, MARKETS)

    rows: dict[str, dict[int, list]] = {m[0]: {FIT_YEAR: [], EVAL_YEAR: []} for m in MARKETS}
    flt = Filters()
    for season in (FIT_YEAR, EVAL_YEAR):
        g = tg[(tg["date"].dt.year == season) & (tg["team"].astype(str) < tg["opponent"].astype(str))].copy()
        g = g.sort_values("date").reset_index(drop=True)
        print(f"[champ_tempo] season {season}: {len(g)} mapas")
        cache: dict = {}
        last_cut, hist = None, None
        for idx, r in enumerate(g.itertuples(index=False)):
            cut = pd.Timestamp(r.date).normalize()
            if last_cut is None or cut != last_cut:
                hist = tg[tg["date"] < cut]
                cache.clear()
                last_cut = cut
            gid = str(r.gameid)
            sig = signals.get(gid)
            if sig is None or hist is None or hist.empty:
                continue

            def _prof(team: str):
                if team not in cache:
                    cache[team] = build_profile(hist, team=str(team), filters=flt, half_life_days=HALF_LIFE)
                return cache[team]

            pA, pB = _prof(str(r.team)), _prof(str(r.opponent))
            if int(getattr(pA, "n_games", 0)) < MIN_HIST or int(getattr(pB, "n_games", 0)) < MIN_HIST:
                continue
            totals = matchup_expected_totals(pA, pB)
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
                    (float(tot.mean), float(tot.sd), str(tot.dist), actual, float(sig[metric]), float(line)))
            if (idx + 1) % 1500 == 0:
                print(f"  {idx + 1}/{len(g)}", flush=True)

    print(f"\n{'mercado':9} {'n_fit':>6} {'b_sinal':>8} {'t':>6} | "
          f"{'n_2026':>6} {'brierV0':>8} {'brierADJ':>9} {'dif':>9} {'veredito':>9}")
    consts = {}
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
        zs = (sig - sig_mu) / sig_sd
        X = np.column_stack([np.ones_like(zs), zs])
        beta, *_ = np.linalg.lstsq(X, resid, rcond=None)
        pred = X @ beta
        s2 = float(((resid - pred) ** 2).sum() / (len(resid) - 2))
        cov = s2 * np.linalg.inv(X.T @ X)
        t_b = beta[1] / math.sqrt(cov[1, 1])

        v0_rows, adj_rows = [], []
        for mean_e, sd_e, dist_e, act_e, sig_e, line_e in ev:
            zs_e = (sig_e - sig_mu) / sig_sd
            delta = beta[0] + beta[1] * zs_e
            y = 1 if act_e > line_e else 0
            t0 = MatchupTotals(mean=mean_e, sd=sd_e, dist=dist_e)  # type: ignore[arg-type]
            ta = MatchupTotals(mean=max(mean_e + delta, 0.1), sd=sd_e, dist=dist_e)  # type: ignore[arg-type]
            p0, pa = prob_over_from_total(t0, line_e), prob_over_from_total(ta, line_e)
            if math.isfinite(p0) and math.isfinite(pa):
                v0_rows.append((p0, y)); adj_rows.append((pa, y))
        b0 = sum((p - y) ** 2 for p, y in v0_rows) / len(v0_rows)
        ba = sum((p - y) ** 2 for p, y in adj_rows) / len(adj_rows)
        dif = b0 - ba
        verdict = "ACCEPT" if dif > 0.0005 else ("neutro" if dif > -0.0005 else "REJECT")
        print(f"{metric:9} {len(fit):>6} {beta[1]:>+8.4f} {t_b:>+6.1f} | "
              f"{len(v0_rows):>6} {b0:>8.4f} {ba:>9.4f} {dif:>+9.5f} {verdict:>9}")
        print(f"{'':9} CONST {metric}: a={beta[0]:+.4f} b={beta[1]:+.4f} sig_mu={sig_mu:.4f} sig_sd={sig_sd:.4f}")
        consts[metric] = {"a": round(float(beta[0]), 4), "b": round(float(beta[1]), 4),
                          "sig_mu": round(sig_mu, 4), "sig_sd": round(sig_sd, 4),
                          "t": round(float(t_b), 2), "brier_dif": round(float(dif), 6), "veredito": verdict}

    import json
    out = ROOT / "scratchpad" / "draft_totals_champ_tempo.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(consts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[salvo] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
