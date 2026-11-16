# -*- coding: utf-8 -*-
"""Prova da alavanca WHR (Whole-History Rating, Coulom 2008) — candidato da
pesquisa de nota 2026-07-05.

WHR: em vez de update incremental (Elo), estima por MAP a TRAJETÓRIA inteira
de rating de cada time (random walk gaussiano entre dias de jogo, likelihood
Bradley-Terry), re-otimizando a história a cada jogo novo. No benchmark PGD
(Go pro) bateu Elo/Glicko/TrueSkill/decayed-history.

Protocolo honesto (mesmo do MOVDA):
- Âncora de liga: prior do 1º ponto de cada time = SOS points (mesma do Elo).
- w2 (drift Elo²/dia) tunado prequencialmente em < oos-year.
- EVAL prequencial no oos-year: pontua ANTES de adicionar o jogo.
- Baseline: Elo de produção (k=28/scale300/alpha60/tier.30/cap75/dynk ON/SOS)
  + MOVDA lam=0.5 (o que está deployado hoje).

Uso: python tools/eval_whr.py --oos-year 2026
"""
from __future__ import annotations

import argparse
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

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.elo import EloModel, EloParams  # noqa: E402
from tools.eval_interleague_levers import _tier, load_games, sos_points_from_train  # noqa: E402
from tools.eval_mov_elo import PROD_PARAMS, _mov_of, _dr_from_p, fit_expected_mov  # noqa: E402
from tools.ml_quality_scorecard import _grade_from_logloss, default_csvs  # noqa: E402

NAT = math.log(10.0) / 400.0  # Elo points -> unidades naturais do logit
SIGMA0_ELO = 350.0            # prior do 1º ponto (desvio em Elo)
MAX_STEP = 1.0                # clamp do passo de Newton (natural)


class WHR:
    """MAP do histórico completo; Newton tridiagonal por time (coordenada)."""

    def __init__(self, w2_elo_per_day: float, league_prior_elo: dict[str, float]):
        self.w2 = float(w2_elo_per_day) * NAT * NAT  # natural²/dia
        self.prior_mu = {k: float(v) * NAT for k, v in league_prior_elo.items()}
        self.days: dict[str, list[int]] = {}      # team -> dias (ordinal) com jogo
        self.r: dict[str, np.ndarray] = {}        # team -> ratings por dia (natural)
        self.mu0: dict[str, float] = {}           # team -> prior do 1º ponto
        self.games: dict[str, list[tuple[int, str, int, int]]] = {}
        # team -> [(day_idx_do_time, opp, day_idx_do_opp, y_do_time)]

    def _ensure_point(self, team: str, day: int, league: str) -> int:
        if team not in self.days:
            self.days[team] = [day]
            self.r[team] = np.array([self.prior_mu.get(league, 0.0)], dtype=float)
            self.mu0[team] = self.prior_mu.get(league, 0.0)
            self.games[team] = []
            return 0
        ds = self.days[team]
        if day > ds[-1]:
            ds.append(day)
            self.r[team] = np.append(self.r[team], self.r[team][-1])
            return len(ds) - 1
        # jogos chegam em ordem de data; mesmo dia = último ponto
        return len(ds) - 1

    def rating_last(self, team: str) -> float | None:
        arr = self.r.get(team)
        return float(arr[-1]) if arr is not None and len(arr) else None

    def p_win(self, a: str, b: str, la: str, lb: str) -> float:
        ra = self.rating_last(a)
        rb = self.rating_last(b)
        if ra is None:
            ra = self.prior_mu.get(la, 0.0)
        if rb is None:
            rb = self.prior_mu.get(lb, 0.0)
        return 1.0 / (1.0 + math.exp(-(ra - rb)))

    def add_game(self, a: str, b: str, y: int, day: int, la: str, lb: str) -> None:
        ia = self._ensure_point(a, day, la)
        ib = self._ensure_point(b, day, lb)
        self.games[a].append((ia, b, ib, int(y)))
        self.games[b].append((ib, a, ia, 1 - int(y)))

    def refresh_team(self, team: str, iters: int = 2) -> None:
        """Newton no timeline do time (opponents fixos). Hessiana tridiagonal."""
        ds = self.days.get(team)
        if not ds:
            return
        n = len(ds)
        r = self.r[team]
        s0 = (SIGMA0_ELO * NAT) ** 2
        for _ in range(int(iters)):
            grad = np.zeros(n)
            diag = np.zeros(n)
            off = np.zeros(max(n - 1, 0))
            # prior do primeiro ponto
            grad[0] += -(r[0] - self.mu0[team]) / s0
            diag[0] += -1.0 / s0
            # random walk entre pontos consecutivos
            for i in range(n - 1):
                var = self.w2 * max(ds[i + 1] - ds[i], 1)
                d = (r[i + 1] - r[i]) / var
                grad[i] += d
                grad[i + 1] -= d
                diag[i] -= 1.0 / var
                diag[i + 1] -= 1.0 / var
                off[i] += 1.0 / var
            # likelihood
            for (idx, opp, oidx, y) in self.games[team]:
                ro = self.r[opp][min(oidx, len(self.r[opp]) - 1)]
                p = 1.0 / (1.0 + math.exp(-(r[idx] - ro)))
                grad[idx] += (y - p)
                diag[idx] -= p * (1.0 - p)
            # resolve H dx = -grad (H tridiagonal, Thomas)
            dx = _solve_tridiag(diag.copy(), off.copy(), -grad)
            np.clip(dx, -MAX_STEP, MAX_STEP, out=dx)
            r += dx
        self.r[team] = r


def _solve_tridiag(diag: np.ndarray, off: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    n = len(diag)
    if n == 1:
        return rhs / diag
    # forward
    for i in range(1, n):
        m = off[i - 1] / diag[i - 1]
        diag[i] -= m * off[i - 1]
        rhs[i] -= m * rhs[i - 1]
    x = np.zeros(n)
    x[-1] = rhs[-1] / diag[-1]
    for i in range(n - 2, -1, -1):
        x[i] = (rhs[i] - off[i] * x[i + 1]) / diag[i]
    return x


def run_whr(g, *, oos_year: int, league_points: dict, w2: float,
            score_year: int, full_every: int = 400) -> dict:
    """Replay prequencial; pontua jogos de score_year antes de adicioná-los."""
    whr = WHR(w2, league_points)
    acc = {"inter": [0.0, 0, 0, 0], "same": [0.0, 0, 0, 0]}  # ll_sum, n, hits, _
    count = 0
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        if r.yr > score_year:
            break
        if bl and rl and r.yr == score_year:
            p = whr.p_win(str(r.team), str(r.opponent), bl, rl)
            pc = min(max(p, 1e-6), 1 - 1e-6)
            y = int(r.win)
            seg = "inter" if bl != rl else "same"
            acc[seg][0] += -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
            acc[seg][1] += 1
            acc[seg][2] += 1 if ((p >= 0.5) == (y == 1)) else 0
        day = int(r.date.toordinal()) if hasattr(r.date, "toordinal") else int(r.dayord)
        whr.add_game(str(r.team), str(r.opponent), int(r.win), day, bl or "", rl or "")
        whr.refresh_team(str(r.team), iters=2)
        whr.refresh_team(str(r.opponent), iters=2)
        count += 1
        if count % int(full_every) == 0:
            for t in whr.days:
                whr.refresh_team(t, iters=1)
    out = {}
    for seg, (ll, n, hits, _x) in acc.items():
        out[seg] = {"logloss": ll / n if n else float("nan"), "n": n,
                    "acc": hits / n if n else float("nan")}
    return out


def run_baseline(g, *, score_year: int, league_points: dict, mov_fit: dict, lam: float = 0.5) -> dict:
    """Elo de produção (PROD_PARAMS + SOS) + MOVDA lam (deploy atual)."""
    elo = EloModel(EloParams(**PROD_PARAMS))
    elo.league_base_points_map = dict(league_points)
    am, bm, gm = mov_fit["alpha_m"], mov_fit["beta_m"], mov_fit["gamma_m"]
    acc = {"inter": [0.0, 0, 0], "same": [0.0, 0, 0]}
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        if r.yr > score_year:
            break
        dr_pred = None
        if bl and rl:
            p = float(elo.p_blue(r.team, r.opponent, blue_league=bl, red_league=rl,
                                 blue_tier=_tier(bl), red_tier=_tier(rl)))
            dr_pred = _dr_from_p(p, PROD_PARAMS["scale_points"])
            if r.yr == score_year:
                pc = min(max(p, 1e-6), 1 - 1e-6)
                y = int(r.win)
                seg = "inter" if bl != rl else "same"
                acc[seg][0] += -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
                acc[seg][1] += 1
                acc[seg][2] += 1 if ((p >= 0.5) == (y == 1)) else 0
        elo.update(str(r.team), str(r.opponent), int(r.win),
                   blue_league=bl or None, red_league=rl or None,
                   blue_tier=_tier(bl) if bl else None, red_tier=_tier(rl) if rl else None)
        if lam > 0 and dr_pred is not None:
            mov = _mov_of(r)
            if mov is not None:
                adj = float(lam) * (mov - (am * math.tanh(bm * dr_pred) + gm))
                elo.ratings[str(r.team)] = elo.rating_raw(str(r.team)) + adj
                elo.ratings[str(r.opponent)] = elo.rating_raw(str(r.opponent)) - adj
    out = {}
    for seg, (ll, n, hits) in acc.items():
        out[seg] = {"logloss": ll / n if n else float("nan"), "n": n,
                    "acc": hits / n if n else float("nan")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos-year", type=int, default=2026)
    args = ap.parse_args()
    oos = int(args.oos_year)

    g = load_games(default_csvs())
    league_points = sos_points_from_train(g, oos, 400.0)  # scale 400 = default de produção
    print(f"[whr] jogos: {len(g)} | oos={oos}")

    print("[whr] fit MOVDA p/ baseline (anos de treino)...")
    mov_fit = fit_expected_mov(g, oos_year=oos, league_points=league_points)

    tune_year = oos - 1
    lp_tune = sos_points_from_train(g, tune_year, 400.0)
    print(f"[whr] tune de w2 em {tune_year} (prequencial, sem tocar {oos}):")
    best_w2, best_ll = None, float("inf")
    for w2 in (5.0, 20.0, 60.0, 150.0):
        res = run_whr(g, oos_year=oos, league_points=lp_tune, w2=w2, score_year=tune_year)
        ll = (res["same"]["logloss"] * res["same"]["n"] + res["inter"]["logloss"] * res["inter"]["n"]) / \
             (res["same"]["n"] + res["inter"]["n"])
        print(f"  w2={w2:>6.0f} Elo2/dia -> geral {ll:.4f} | same {res['same']['logloss']:.4f} "
              f"| inter {res['inter']['logloss']:.4f}", flush=True)
        if ll < best_ll:
            best_ll, best_w2 = ll, w2
    print(f"[whr] w2* = {best_w2}")

    print(f"\n[whr] EVAL {oos} (cego):")
    whr_res = run_whr(g, oos_year=oos, league_points=league_points, w2=float(best_w2), score_year=oos)
    base_res = run_baseline(g, score_year=oos, league_points=league_points, mov_fit=mov_fit, lam=0.5)

    print(f"\n{'seg':6} {'n':>5} | {'BASE ll':>8} {'acc':>6} | {'WHR ll':>8} {'acc':>6} | {'dif ll':>8}")
    tot_b = tot_w = tot_n = 0.0
    for seg in ("same", "inter"):
        b, w = base_res[seg], whr_res[seg]
        print(f"{seg:6} {b['n']:>5} | {b['logloss']:>8.4f} {100 * b['acc']:>5.1f}% | "
              f"{w['logloss']:>8.4f} {100 * w['acc']:>5.1f}% | {b['logloss'] - w['logloss']:>+8.4f}")
        tot_b += b["logloss"] * b["n"]
        tot_w += w["logloss"] * w["n"]
        tot_n += b["n"]
    llb, llw = tot_b / tot_n, tot_w / tot_n
    print(f"{'GERAL':6} {int(tot_n):>5} | {llb:>8.4f} {'':>6} | {llw:>8.4f} {'':>6} | {llb - llw:>+8.4f}")
    print(f"nota baseline {_grade_from_logloss(llb):.2f} vs WHR {_grade_from_logloss(llw):.2f}")
    print("VEREDITO:", "ACCEPT (investigar deploy)" if (llb - llw) > 0.003 else
          ("neutro/marginal" if (llb - llw) > -0.003 else "REJECT — Elo de produção segue melhor"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
