# -*- coding: utf-8 -*-
"""GATE: calibrar o modelo POR LIGA melhora a previsão? (pedido dele 24/07)

Contexto (medido em tools/nota_por_liga.py, season 2026): a calibração varia
MUITO por liga. LPL ECE 0.019, LCS 0.031, LEC 0.045, LCK 0.056 — nessas o % do
modelo é honesto. Mas VCS 0.117, HM 0.116, CBLOL 0.114 — ali o % mente, e o EV
que ele calcula em cima disso não é real.

Pergunta: dá pra corrigir, ou é ruído de liga pequena (n=100-280)?

Método (walk-forward, sem vazamento): para cada jogo, o calibrador da liga é
ajustado SÓ com os jogos anteriores daquela liga, e encolhido para a identidade
(sem ajuste) com força k — a receita hierárquica padrão para grupo com amostra
pequena. Duas variantes:
  viés   -> só desloca (corrige "diz 50.8%, acontece 58.3%"); 1 parâmetro
  Platt  -> desloca E ajusta a inclinação (corrige excesso de confiança); 2 par.

Nota conservadora: o p base vem de um artifact treinado nesta mesma season, ou
seja, o baseline está favorecido. Um ACCEPT aqui é confiável; um REJECT pode
estar sendo puxado por isso.

Uso: python tools/medir_calibrador_por_liga.py
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.artifact import MLArtifact  # noqa: E402
from mlcore.io_oracle import load_oracle_elixir_games  # noqa: E402
from mlcore.tiers import tier_for_league  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

# Força do prior "não ajusta nada". A 1ª rodada (24/07) mostrou ganho ainda
# SUBINDO em k=400, então a grade vai até 6400 para achar o pico de verdade —
# como o ganho tende a 0 quando k→∞, o máximo está em algum ponto no meio.
SHRINK_K = [25.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0]
MIN_N = 30           # liga só é ajustada com histórico mínimo
REFIT_EVERY = 20     # reajusta o calibrador a cada N jogos novos da liga
GATE = 0.002         # ganho de logloss que vira ACCEPT


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


def _fit_platt(zs: list[float], ys: list[int], *, slope: bool) -> tuple[float, float]:
    """IRLS/Newton para y ~ sigmoid(a*z + b). slope=False fixa a=1 (só viés).

    Sem sklearn no projeto — são 2 parâmetros, Newton converge em ~10 passos.
    Retorna (a, b); em caso de separação/singularidade devolve a identidade.
    """
    a, b = 1.0, 0.0
    n = len(zs)
    if n == 0:
        return 1.0, 0.0
    for _ in range(25):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for z, y in zip(zs, ys):
            p = _sig(a * z + b)
            r = p - y
            w = max(p * (1 - p), 1e-9)
            g_a += r * z
            g_b += r
            h_aa += w * z * z
            h_ab += w * z
            h_bb += w
        if not slope:
            if h_bb <= 1e-12:
                break
            step = g_b / h_bb
            b -= step
            if abs(step) < 1e-8:
                break
            continue
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        da = (h_bb * g_a - h_ab * g_b) / det
        db = (h_aa * g_b - h_ab * g_a) / det
        a -= da
        b -= db
        if max(abs(da), abs(db)) < 1e-8:
            break
    if not (math.isfinite(a) and math.isfinite(b)):
        return 1.0, 0.0
    # trava contra ajuste absurdo vindo de liga pequena
    return float(min(max(a, 0.2), 3.0)), float(min(max(b, -2.0), 2.0))


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
    season = int(pd.to_numeric(g["year"], errors="coerce").max())
    print(f"jogos: {len(g)} | avaliando a season {season}")

    hist_z: dict[str, list[float]] = defaultdict(list)   # logits passados da liga
    hist_y: dict[str, list[int]] = defaultdict(list)
    fitted: dict[tuple[str, bool], tuple[float, float, int]] = {}  # (a,b,n_no_fit)

    base_ps: list[float] = []
    ys: list[int] = []
    lgs: list[str] = []
    # ajuste bruto (sem shrink) guardado por variante; o shrink entra depois
    raw_adj: dict[bool, list[tuple[float, float, int]]] = {True: [], False: []}

    for r in g.itertuples(index=False):
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        lg = str(getattr(r, "league", "") or "OTHER")
        z = None
        if pd.to_numeric(getattr(r, "year", None), errors="coerce") == season:
            t = str(tier_for_league(lg))
            p0 = float(model.p_blue(str(r.blue), str(r.red), blue_league=lg, red_league=lg,
                                    blue_tier=t, red_tier=t))
            z = _logit(p0)
            base_ps.append(p0)
            ys.append(y)
            lgs.append(lg)
            n_lg = len(hist_y[lg])
            for slope in (False, True):
                if n_lg < MIN_N:
                    raw_adj[slope].append((1.0, 0.0, n_lg))
                    continue
                key = (lg, slope)
                cached = fitted.get(key)
                if cached is None or n_lg - cached[2] >= REFIT_EVERY:
                    a, b = _fit_platt(hist_z[lg], hist_y[lg], slope=slope)
                    fitted[key] = (a, b, n_lg)
                    cached = fitted[key]
                raw_adj[slope].append((cached[0], cached[1], n_lg))

        # walk-forward: só acumula DEPOIS de usar
        if z is None:
            t = str(tier_for_league(lg))
            p0 = float(model.p_blue(str(r.blue), str(r.red), blue_league=lg, red_league=lg,
                                    blue_tier=t, red_tier=t))
            z = _logit(p0)
        hist_z[lg].append(z)
        hist_y[lg].append(y)

    print(f"avaliação: {len(ys)} jogos\n")
    ll0 = _ll(base_ps, ys)
    print(f"{'variante':>10} {'k':>6} {'logloss':>9} {'vs sem ajuste':>15}")
    print(f"{'sem ajuste':>10} {'-':>6} {ll0:>9.5f} {0.0:>+15.5f}")

    best = (None, None, ll0)
    for slope in (False, True):
        nome = "Platt" if slope else "viés"
        for k in SHRINK_K:
            ps = []
            for p0, (a, b, n) in zip(base_ps, raw_adj[slope]):
                w = n / (n + k)                      # shrink para a identidade
                a_e = 1.0 + w * (a - 1.0)
                b_e = w * b
                ps.append(_sig(a_e * _logit(p0) + b_e))
            ll = _ll(ps, ys)
            if ll < best[2]:
                best = (nome, k, ll)
            print(f"{nome:>10} {k:>6.0f} {ll:>9.5f} {ll0 - ll:>+15.5f}")

    print()
    if best[0] is None:
        print("VEREDITO: REJECT — nenhuma variante/k melhora; o desvio por liga é ruído.")
        return 0
    ganho = ll0 - best[2]
    v = "ACCEPT" if ganho > GATE else "~neutro"
    print(f"melhor: {best[0]} k={best[1]:.0f} | ganho {ganho:+.5f} -> {v}")

    # onde o ganho aparece? (as ligas mal calibradas deveriam ser as beneficiadas)
    slope = best[0] == "Platt"
    k = float(best[1])
    per = defaultdict(lambda: [0.0, 0.0, 0])
    for p0, y, lg, (a, b, n) in zip(base_ps, ys, lgs, raw_adj[slope]):
        w = n / (n + k)
        p1 = _sig((1.0 + w * (a - 1.0)) * _logit(p0) + w * b)
        e = per[lg]
        e[0] += _ll([p0], [y])
        e[1] += _ll([p1], [y])
        e[2] += 1
    rows = [(lg, c, (s0 - s1) / c) for lg, (s0, s1, c) in per.items() if c >= 80]
    rows.sort(key=lambda t: t[2], reverse=True)
    print(f"\nganho por liga ({best[0]}, k={best[1]:.0f}) — top 6 e bottom 3:")
    for lg, c, d in rows[:6] + rows[-3:]:
        print(f"  {lg:>6} n={c:<5} {d:+.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
