"""GATE do momentum de séries: o termo medido melhora logloss FORA da amostra?

Modelo candidato (1 parâmetro, honesto):
  p_mapa_k = sigmoid(logit(p) + d * s)   com s=+1 se ganhou o mapa anterior, -1 se perdeu
  decider EMPATADO fica p puro (medido ~0 de momentum em decider).

Protocolo: d é FITADO em 2025 (MLE em grid) e avaliado às cegas em 2026:
  (A) nível mapa-2: logloss/Brier de prever o mapa 2 (V0 independente vs V1 momentum)
  (B) nível série bo3: P(vencer a série) analítica com momentum vs binomial independente

  python tools/eval_series_momentum_gate.py
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.artifact import MLArtifact
from tools.eval_interleague_levers import load_games
from tools.ml_quality_scorecard import default_csvs


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _ll(rows: list[tuple[int, float]]) -> float:
    n = len(rows)
    return sum(-(y * math.log(min(max(p, 1e-6), 1 - 1e-6)) + (1 - y) * math.log(1 - min(max(p, 1e-6), 1 - 1e-6))) for y, p in rows) / max(n, 1)


def _brier(rows: list[tuple[int, float]]) -> float:
    return sum((p - y) ** 2 for y, p in rows) / max(len(rows), 1)


def collect_series(g, art) -> list[dict]:
    """[{p, wins:[...], yr}] — p simetrizado (fwd/rev) por série, orientação team<opp."""
    out: list[dict] = []
    g = g.copy()
    g["day"] = g["date"].dt.date
    for (_day, team, opp), grp in g.groupby(["day", "team", "opponent"], sort=False):
        maps = grp.sort_values("date")
        if len(maps) < 2:
            continue
        bl, rl = str(maps.iloc[0]["dl"]), str(maps.iloc[0]["ol"])
        if not bl or not rl:
            continue
        p_fwd = float(art.model.p_blue(str(team), str(opp), blue_league=bl, red_league=rl))
        p_rev = float(art.model.p_blue(str(opp), str(team), blue_league=rl, red_league=bl))
        if art.calibrator is not None:
            p_fwd = float(art.calibrator.predict_proba(p_fwd))
            p_rev = float(art.calibrator.predict_proba(p_rev))
        p = 0.5 * (p_fwd + (1.0 - p_rev))
        if not (0.01 < p < 0.99):
            continue
        out.append({"p": p, "wins": [int(w) for w in maps["win"].tolist()],
                    "yr": int(maps.iloc[0]["yr"])})
    return out


def map2_rows(series: list[dict], d: float) -> list[tuple[int, float]]:
    rows = []
    for s in series:
        w = s["wins"]
        sgn = 1.0 if w[0] == 1 else -1.0
        p2 = _sig(_logit(s["p"]) + d * sgn)
        rows.append((w[1], p2))
    return rows


def p_series_bo3(p: float, d: float) -> float:
    """P(ref vence bo3) com momentum d no mapa seguido de vitória/derrota; decider puro."""
    p2w = _sig(_logit(p) + d)   # ref venceu m1 → m2 com boost
    p2l = _sig(_logit(p) - d)   # ref perdeu m1 → m2 com malus
    # 2-0 | 1-1(via WV..) decider p | 0-1 depois vence m2 e decider
    return p * p2w + p * (1 - p2w) * p + (1 - p) * p2l * p


def bo3_rows(series: list[dict], d: float) -> list[tuple[int, float]]:
    rows = []
    for s in series:
        w = s["wins"]
        # série bo3 completa: alguém fechou 2 em <=3 mapas
        ref, opp = sum(w), len(w) - sum(w)
        if len(w) > 3 or max(ref, opp) != 2 or min(ref, opp) > 1:
            continue
        y = 1 if ref == 2 else 0
        rows.append((y, p_series_bo3(s["p"], d)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate OOS do momentum de séries.")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--train-year", type=int, default=2025)
    ap.add_argument("--eval-year", type=int, default=2026)
    args = ap.parse_args()

    g = load_games(default_csvs())
    g = g[g["yr"].isin({args.train_year, args.eval_year})]
    art = MLArtifact.load_json(str(args.artifact))
    series = collect_series(g, art)
    tr = [s for s in series if s["yr"] == args.train_year]
    ev = [s for s in series if s["yr"] == args.eval_year]
    print(f"[gate] séries: treino({args.train_year})={len(tr)} | eval({args.eval_year})={len(ev)}")

    # Fit d por MLE (grid) no MAPA 2 do treino
    best_d, best_ll = 0.0, float("inf")
    for i in range(0, 41):
        d = i * 0.01
        ll = _ll(map2_rows(tr, d))
        if ll < best_ll:
            best_d, best_ll = d, ll
    print(f"[fit] d*={best_d:.2f} (logloss treino mapa-2 {best_ll:.4f} vs d=0 {_ll(map2_rows(tr, 0.0)):.4f})")

    print(f"\n=== EVAL OOS {args.eval_year} ===")
    r0 = map2_rows(ev, 0.0)
    r1 = map2_rows(ev, best_d)
    print(f"(A) MAPA 2       n={len(r0)}")
    print(f"    V0 indep     logloss {_ll(r0):.4f} | brier {_brier(r0):.4f}")
    print(f"    V1 momentum  logloss {_ll(r1):.4f} | brier {_brier(r1):.4f}")
    print(f"    ganho        logloss {_ll(r0) - _ll(r1):+.4f} | brier {_brier(r0) - _brier(r1):+.4f}")

    b0 = bo3_rows(ev, 0.0)
    b1 = bo3_rows(ev, best_d)
    print(f"(B) SÉRIE bo3    n={len(b0)}")
    print(f"    V0 indep     logloss {_ll(b0):.4f} | brier {_brier(b0):.4f}")
    print(f"    V1 momentum  logloss {_ll(b1):.4f} | brier {_brier(b1):.4f}")
    print(f"    ganho        logloss {_ll(b0) - _ll(b1):+.4f} | brier {_brier(b0) - _brier(b1):+.4f}")

    ok_a = (_ll(r0) - _ll(r1)) > 0.002
    ok_b = (_ll(b0) - _ll(b1)) > -0.001
    print(f"\nDECISÃO: {'ACCEPT' if (ok_a and ok_b) else 'REJECT'} "
          f"(critério: mapa-2 ganha >0.002 de logloss OOS e série não piora >0.001)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
