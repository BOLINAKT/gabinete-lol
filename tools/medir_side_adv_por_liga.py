# -*- coding: utf-8 -*-
"""GATE: vantagem de lado POR LIGA melhora a previsão? (achado 24/07, com ele)

Contexto: `side_adv_points = 0.0` no artifact — o modelo não modela vantagem de
lado; o calibrador global absorve a média (azul 53.5% em 2026). Mas a vantagem
varia MUITO por liga: PRM 60.3%, CBLOL 58.3% ... EBL 44.9%, VCS 46.0%.
Consequência medida: no CBLOL o modelo prevê 50.8% e o real é 58.3% (ECE 0.114),
enquanto LPL/LCK/LEC/LCS estão bem calibradas (ECE 0.019-0.056).

Pergunta: um ajuste de lado por liga (estimado SÓ no passado) melhora o futuro,
ou é ruído amostral de liga pequena (n=100-280)?

Método (walk-forward, sem vazamento): para cada jogo, o ajuste da liga vem
apenas dos jogos ANTERIORES daquela liga, com shrink bayesiano para a média
global (k = força do prior). Compara logloss com e sem o ajuste.

Uso: python tools/medir_side_adv_por_liga.py
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

from mlcore.artifact import MLArtifact  # noqa: E402
from mlcore.io_oracle import load_oracle_elixir_games  # noqa: E402
from mlcore.tiers import tier_for_league  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

SHRINK_K = [20.0, 50.0, 100.0, 200.0]   # força do prior (jogos equivalentes)
MIN_N = 15                               # só ajusta liga com histórico mínimo


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))


def _ll(ps, ys) -> float:
    tot = 0.0
    for p, y in zip(ps, ys):
        p = min(max(p, 1e-9), 1 - 1e-9)
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return tot / max(1, len(ps))


def main() -> int:
    art = MLArtifact.load_json(str(ROOT / "ml_artifact.json"))
    model = art.model

    frames = []
    for c in default_csvs():
        try:
            d = load_oracle_elixir_games(str(c), keep_playoffs=None)
            if not d.empty:
                frames.append(d)
        except Exception as e:
            print(f"skip {c}: {e}")
    g = pd.concat(frames, ignore_index=True, join="inner")
    g["date"] = pd.to_datetime(g["date"], errors="coerce")
    g = g.dropna(subset=["date"]).drop_duplicates("gameid", keep="last")
    g = g.sort_values("date").reset_index(drop=True)
    print(f"jogos totais: {len(g)} | de {str(g.date.min())[:10]} a {str(g.date.max())[:10]}")

    # avaliação na season mais recente; histórico do lado vem de TUDO que veio antes
    season = int(pd.to_numeric(g["year"], errors="coerce").max())

    base_ps: list[float] = []
    ys: list[int] = []
    adj_logit: dict[float, list[float]] = {k: [] for k in SHRINK_K}

    wins = defaultdict(float)   # por liga, só do passado
    cnt = defaultdict(float)
    glob_w = 0.0
    glob_n = 0.0

    for r in g.itertuples(index=False):
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        lg = str(getattr(r, "league", "") or "OTHER")
        yy = pd.to_numeric(getattr(r, "year", None), errors="coerce")

        if yy == season:
            t = str(tier_for_league(lg))
            p0 = float(model.p_blue(str(r.blue), str(r.red), blue_league=lg, red_league=lg,
                                    blue_tier=t, red_tier=t))
            base_ps.append(p0)
            ys.append(y)
            p_glob = (glob_w / glob_n) if glob_n > 0 else 0.5
            n_lg = cnt[lg]
            for k in SHRINK_K:
                if n_lg >= MIN_N:
                    p_lg = (wins[lg] + k * p_glob) / (n_lg + k)
                else:
                    p_lg = p_glob
                # ajuste em logits: quanto a liga desvia do global
                bump = _logit(p_lg) - _logit(p_glob) if 0 < p_glob < 1 else 0.0
                adj_logit[k].append(bump)

        # depois de usar, acumula (walk-forward: nunca vê o próprio jogo)
        wins[lg] += y
        cnt[lg] += 1.0
        glob_w += y
        glob_n += 1.0

    print(f"avaliação: {len(ys)} jogos da season {season}")
    ll0 = _ll(base_ps, ys)
    print(f"\n{'k (prior)':>10} {'logloss':>9} {'vs sem ajuste':>15}")
    print(f"{'sem ajuste':>10} {ll0:>9.5f} {0.0:>+15.5f}")
    best = (None, ll0)
    for k in SHRINK_K:
        ps = [_sig(_logit(p) + b) for p, b in zip(base_ps, adj_logit[k])]
        ll = _ll(ps, ys)
        if ll < best[1]:
            best = (k, ll)
        print(f"{k:>10.0f} {ll:>9.5f} {ll0 - ll:>+15.5f}")

    print()
    if best[0] is None:
        print("VEREDITO: REJECT — nenhum k melhora; o viés por liga é ruído amostral.")
    else:
        ganho = ll0 - best[1]
        v = "ACCEPT" if ganho > 0.002 else "~neutro"
        print(f"melhor k={best[0]:.0f} com ganho {ganho:+.5f} -> {v}")
        if v == "ACCEPT":
            print("  (ganho real: vale modelar vantagem de lado por liga)")
        else:
            print("  (ganho pequeno demais: manter simples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
