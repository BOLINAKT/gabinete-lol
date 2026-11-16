# -*- coding: utf-8 -*-
"""Validação FIEL do WHR (etapa 2 da alavanca N; o probe barato deu ACCEPT).

Lição das cicatrizes (SOS/alpha): ganho no harness cru precisa sobreviver ao
CAMINHO DO PRODUTO — calibração Platt (a mesma classe do artefato). A fusão de
players hoje tem w_lineup=0 (fusão == core), então o caminho fiel é
Elo/WHR + Platt.

Protocolo (controle-vs-tratamento, tudo idêntico exceto o rating):
- Duas frentes prequenciais: BASELINE = Elo produção (k28/scale300/alpha60/
  tier.30/cap75/dynk ON/SOS + MOVDA lam=0.5, o deploy atual) vs WHR (w2=60,
  tunado no probe SÓ em 2025; prior de liga = mesmos pontos SOS).
- Cada frente coleta (ano, segmento, p_raw, y) prequencialmente (pontua ANTES
  de ver o jogo).
- Platt GLOBAL fitado nas predições de 2025 de CADA frente (mesma receita) e
  aplicado CEGO em 2026.
- Métricas 2026 calibradas: logloss/ECE/acc por segmento + NOTA na régua do
  scorecard (45% inter + 55% mesma) — comparável à nota 8.31 do produto.

Uso: python tools/eval_whr_faithful.py
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.calibration import fit_platt_from_raw_probs  # noqa: E402
from mlcore.elo import EloModel, EloParams  # noqa: E402
from tools.eval_interleague_levers import _tier, load_games, sos_points_from_train  # noqa: E402
from tools.eval_mov_elo import PROD_PARAMS, _dr_from_p, _mov_of, fit_expected_mov  # noqa: E402
from tools.eval_whr import WHR  # noqa: E402
from tools.ml_quality_scorecard import _grade_from_logloss, default_csvs  # noqa: E402

FIT_YEAR, EVAL_YEAR = 2025, 2026
W2_STAR = 60.0  # tunado no probe (eval_whr.py) prequencialmente em 2025
MOV_LAMBDA = 0.5


def replay_baseline(g, league_points: dict, mov_fit: dict) -> list[tuple[int, str, float, int]]:
    elo = EloModel(EloParams(**PROD_PARAMS))
    elo.league_base_points_map = dict(league_points)
    am, bm, gm = mov_fit["alpha_m"], mov_fit["beta_m"], mov_fit["gamma_m"]
    preds: list[tuple[int, str, float, int]] = []
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        if r.yr > EVAL_YEAR:
            break
        dr_pred = None
        if bl and rl:
            p = float(elo.p_blue(r.team, r.opponent, blue_league=bl, red_league=rl,
                                 blue_tier=_tier(bl), red_tier=_tier(rl)))
            dr_pred = _dr_from_p(p, PROD_PARAMS["scale_points"])
            if r.yr in (FIT_YEAR, EVAL_YEAR):
                preds.append((int(r.yr), "inter" if bl != rl else "same", p, int(r.win)))
        elo.update(str(r.team), str(r.opponent), int(r.win),
                   blue_league=bl or None, red_league=rl or None,
                   blue_tier=_tier(bl) if bl else None, red_tier=_tier(rl) if rl else None)
        if MOV_LAMBDA > 0 and dr_pred is not None:
            mov = _mov_of(r)
            if mov is not None:
                adj = MOV_LAMBDA * (mov - (am * math.tanh(bm * dr_pred) + gm))
                elo.ratings[str(r.team)] = elo.rating_raw(str(r.team)) + adj
                elo.ratings[str(r.opponent)] = elo.rating_raw(str(r.opponent)) - adj
    return preds


def replay_whr(g, league_points: dict) -> list[tuple[int, str, float, int]]:
    whr = WHR(W2_STAR, league_points)
    preds: list[tuple[int, str, float, int]] = []
    count = 0
    for r in g.itertuples(index=False):
        bl, rl = r.dl, r.ol
        if r.yr > EVAL_YEAR:
            break
        if bl and rl and r.yr in (FIT_YEAR, EVAL_YEAR):
            p = whr.p_win(str(r.team), str(r.opponent), bl, rl)
            preds.append((int(r.yr), "inter" if bl != rl else "same", p, int(r.win)))
        day = int(r.date.toordinal())
        whr.add_game(str(r.team), str(r.opponent), int(r.win), day, bl or "", rl or "")
        whr.refresh_team(str(r.team), iters=2)
        whr.refresh_team(str(r.opponent), iters=2)
        count += 1
        if count % 400 == 0:
            for t in whr.days:
                whr.refresh_team(t, iters=1)
    return preds


def _metrics(rows: list[tuple[float, int]]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "logloss": float("nan"), "ece": float("nan"), "acc": float("nan")}
    ll = sum(-(y * math.log(min(max(p, 1e-6), 1 - 1e-6))
               + (1 - y) * math.log(1 - min(max(p, 1e-6), 1 - 1e-6))) for p, y in rows) / n
    acc = sum(1 for p, y in rows if (p >= 0.5) == (y == 1)) / n
    bins: dict[int, list] = {}
    for p, y in rows:
        bins.setdefault(min(9, int(p * 10)), []).append((p, y))
    ece = sum((len(v) / n) * abs(sum(pp for pp, _ in v) / len(v) - sum(yy for _, yy in v) / len(v))
              for v in bins.values())
    return {"n": n, "logloss": ll, "ece": ece, "acc": acc}


def evaluate(name: str, preds: list[tuple[int, str, float, int]]) -> dict:
    fit_rows = [(p, y) for yr, _s, p, y in preds if yr == FIT_YEAR]
    platt = fit_platt_from_raw_probs([y for _, y in fit_rows], [p for p, _ in fit_rows])
    out: dict[str, dict] = {}
    for seg in ("same", "inter"):
        rows = [(float(platt.predict_proba(p)), y) for yr, s, p, y in preds
                if yr == EVAL_YEAR and s == seg]
        out[seg] = _metrics(rows)
    nota = 0.45 * _grade_from_logloss(out["inter"]["logloss"]) + \
        0.55 * _grade_from_logloss(out["same"]["logloss"])
    out["nota"] = nota
    print(f"\n[{name}] Platt(a={platt.a:+.3f}, b={platt.b:+.3f}) fitado em {len(fit_rows)} preds de {FIT_YEAR}")
    for seg in ("same", "inter"):
        m = out[seg]
        print(f"  {seg:6s} n={m['n']:>5} logloss={m['logloss']:.4f} ece={m['ece']:.4f} acc={100 * m['acc']:.1f}%")
    print(f"  NOTA (45% inter + 55% mesma): {nota:.2f}")
    return out


def main() -> int:
    g = load_games(default_csvs())
    print(f"[faithful] jogos: {len(g)} | fit={FIT_YEAR} | eval cego={EVAL_YEAR}")
    league_points = sos_points_from_train(g, EVAL_YEAR, 400.0)
    mov_fit = fit_expected_mov(g, oos_year=EVAL_YEAR, league_points=league_points)

    print("[faithful] replay BASELINE (Elo produção + MOVDA)...")
    base_preds = replay_baseline(g, league_points, mov_fit)
    print("[faithful] replay WHR (w2=60)...")
    whr_preds = replay_whr(g, league_points)

    base = evaluate("BASELINE Elo+Platt", base_preds)
    whr = evaluate("WHR+Platt", whr_preds)

    d_nota = whr["nota"] - base["nota"]
    d_same = base["same"]["logloss"] - whr["same"]["logloss"]
    d_inter = base["inter"]["logloss"] - whr["inter"]["logloss"]
    print(f"\nDIF (WHR - baseline): nota {d_nota:+.2f} | logloss same {d_same:+.4f} | inter {d_inter:+.4f}")
    if d_nota >= 0.05 and min(d_same, d_inter) > -0.002:
        print("VEREDITO: ACCEPT — ganho sobrevive ao calibrador; planejar deploy (troca do core).")
    elif d_nota > -0.05:
        print("VEREDITO: NEUTRO — ganho não sobrevive claramente; não trocar o core por isso.")
    else:
        print("VEREDITO: REJECT — Elo de produção segue melhor no caminho fiel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
