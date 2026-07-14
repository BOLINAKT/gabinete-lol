"""Validacao barata da alavanca I: Elo com margin-of-victory (MOVDA, arXiv 2506.00348).

Ideia do paper: alem do update W/L, somar lambda * (MOV_real - MOV_esperado), onde
MOV_esperado = alpha_m * tanh(beta_m * dR) + gamma_m (sem termo de casa no LoL pre-jogo).
No LoL usamos MOV = diferenca de kills (kills_for - kills_against).

Protocolo (mesmo padrao honesto do eval_dynamic_k_both_segments):
  1) FIT: replay dos anos de treino (< oos-year), coletando (dR_previsto, MOV) e
     ajustando alpha_m/beta_m/gamma_m por minimos quadrados (grid em beta_m).
  2) EVAL prequencial: para cada lambda, replay completo em ordem de data; jogos do
     oos-year sao pontuados ANTES do update (nunca ve o jogo antes de prever).
     lambda=0 == baseline de producao (k=28, scale=300, alpha=60, tier 0.30,
     cap 75, SOS, dynamic_k ON).

  python tools/eval_mov_elo.py --oos-year 2026
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.elo import EloModel, EloParams
from tools.eval_interleague_levers import _tier, load_games, sos_points_from_train
from tools.ml_quality_scorecard import _grade_from_logloss, default_csvs

PROD_PARAMS = dict(
    k=28.0, scale_points=300.0, alpha=60.0,
    tier_prior_weight=0.30, league_strength_cap_abs=75.0,
    dynamic_k_enabled=True,
)


def _mov_of(row) -> float | None:
    try:
        kf = float(getattr(row, "kills_for"))
        ka = float(getattr(row, "kills_against"))
    except (TypeError, ValueError, AttributeError):
        return None
    if not (math.isfinite(kf) and math.isfinite(ka)):
        return None
    return kf - ka


def _dr_from_p(p: float, scale: float) -> float:
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return float(scale) * math.log10(p / (1.0 - p))


def fit_expected_mov(g, *, oos_year: int, league_points: dict) -> dict:
    """Replay dos anos de treino coletando (dR, MOV) e ajustando a tanh."""
    elo = EloModel(EloParams(**PROD_PARAMS))
    elo.league_base_points_map = dict(league_points)
    xs: list[float] = []
    ys: list[float] = []
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        if r.yr >= oos_year:
            break  # g esta ordenado por data; nada de treino depois do corte
        mov = _mov_of(r)
        if bl and rl and mov is not None:
            p = float(elo.p_blue(r.team, r.opponent, blue_league=bl, red_league=rl,
                                 blue_tier=_tier(bl), red_tier=_tier(rl)))
            xs.append(_dr_from_p(p, PROD_PARAMS["scale_points"]))
            ys.append(mov)
        elo.update(str(r.team), str(r.opponent), int(r.win),
                   blue_league=bl or None, red_league=rl or None,
                   blue_tier=_tier(bl) if bl else None, red_tier=_tier(rl) if rl else None)
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    best = None
    for beta in (0.001, 0.002, 0.003, 0.005, 0.008, 0.012, 0.020, 0.030):
        t = np.tanh(beta * x)
        A = np.column_stack([t, np.ones_like(t)])
        coef, res, _, _ = np.linalg.lstsq(A, y, rcond=None)
        sse = float(res[0]) if len(res) else float(((A @ coef - y) ** 2).sum())
        if best is None or sse < best["sse"]:
            best = {"alpha_m": float(coef[0]), "gamma_m": float(coef[1]),
                    "beta_m": float(beta), "sse": sse}
    resid = y - (best["alpha_m"] * np.tanh(best["beta_m"] * x) + best["gamma_m"])
    best["resid_std"] = float(np.std(resid))
    best["n_fit"] = int(len(x))
    return best


def eval_lambda(g, *, oos_year: int, league_points: dict, fit: dict, lam: float) -> dict:
    """Prequencial: pontua jogos do oos-year antes do update; MOV ajusta apos cada update."""
    elo = EloModel(EloParams(**PROD_PARAMS))
    elo.league_base_points_map = dict(league_points)
    acc = {"inter": [0.0, 0], "same": [0.0, 0]}
    am, bm, gm = fit["alpha_m"], fit["beta_m"], fit["gamma_m"]
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        dr_pred = None
        if bl and rl:
            p = float(elo.p_blue(r.team, r.opponent, blue_league=bl, red_league=rl,
                                 blue_tier=_tier(bl), red_tier=_tier(rl)))
            dr_pred = _dr_from_p(p, PROD_PARAMS["scale_points"])
            if r.yr == oos_year:
                pc = min(max(p, 1e-6), 1 - 1e-6)
                y = int(r.win)
                seg = "inter" if bl != rl else "same"
                acc[seg][0] += -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
                acc[seg][1] += 1
        elo.update(str(r.team), str(r.opponent), int(r.win),
                   blue_league=bl or None, red_league=rl or None,
                   blue_tier=_tier(bl) if bl else None, red_tier=_tier(rl) if rl else None)
        if lam > 0 and dr_pred is not None:
            mov = _mov_of(r)
            if mov is not None:
                dmov = mov - (am * math.tanh(bm * dr_pred) + gm)
                adj = float(lam) * float(dmov)
                elo.ratings[str(r.team)] = elo.rating_raw(str(r.team)) + adj
                elo.ratings[str(r.opponent)] = elo.rating_raw(str(r.opponent)) - adj
    out = {}
    for k, (s, n) in acc.items():
        out[k] = (s / max(1, n), n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Eval prequencial: Elo + margin-of-victory (MOVDA).")
    ap.add_argument("--csv", action="append", default=None)
    ap.add_argument("--oos-year", type=int, default=2026)
    ap.add_argument("--sos-scale", type=float, default=400.0)
    args = ap.parse_args()

    csvs = args.csv or default_csvs()
    g = load_games(csvs)
    league_points = sos_points_from_train(g, args.oos_year, args.sos_scale)

    fit = fit_expected_mov(g, oos_year=args.oos_year, league_points=league_points)
    print(f"[fit E_MOV] n={fit['n_fit']} | alpha_m={fit['alpha_m']:.3f} "
          f"beta_m={fit['beta_m']:.4f} gamma_m={fit['gamma_m']:+.3f} | resid_std={fit['resid_std']:.2f} kills")

    print(f"\n{'lambda':>7} {'inter_ll':>9} {'same_ll':>9} {'nota(45/55)':>12} {'n_inter':>7} {'n_same':>7}")
    base_nota = None
    for lam in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0):
        res = eval_lambda(g, oos_year=args.oos_year, league_points=league_points, fit=fit, lam=lam)
        ll_i, n_i = res["inter"]
        ll_s, n_s = res["same"]
        nota = 0.45 * _grade_from_logloss(ll_i) + 0.55 * _grade_from_logloss(ll_s)
        if lam == 0.0:
            base_nota = nota
        delta = f" ({nota - base_nota:+.2f})" if base_nota is not None and lam > 0 else ""
        print(f"{lam:>7.2f} {ll_i:>9.4f} {ll_s:>9.4f} {nota:>12.2f}{delta} {n_i:>7} {n_s:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
