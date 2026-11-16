"""Estudo de momentum em séries (bo3/bo5): ganhar o mapa anterior muda o próximo?

O produto assume INDEPENDÊNCIA entre mapas (prob_win_series = binomial de p_map;
series_gamma é só um expoente global por liga, não dependência). Este estudo mede,
nos nossos dados, se existe dependência REAL além da força dos times:

  lift(k) = média(y_k) − média(p_modelo)  condicionado ao resultado do mapa k-1

onde p_modelo = prob calibrada do artefato (constante na série — ratings não
atualizam no meio). Se lift(ganhou anterior) >> lift(perdeu anterior), existe
momentum não-modelado e as odds de MD3/MD5 deixam dinheiro na mesa.

  python tools/eval_series_momentum.py
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


def _binom_z(k: int, n: int, p_bar: float) -> float:
    """z-score de k sucessos em n tentativas contra probabilidade média p_bar."""
    if n <= 0 or not (0.0 < p_bar < 1.0):
        return float("nan")
    sd = math.sqrt(n * p_bar * (1.0 - p_bar))
    return (k - n * p_bar) / sd if sd > 0 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description="Momentum em séries bo3/bo5 (dados próprios).")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--seasons", default="2025,2026", help="Anos avaliados (CSV).")
    args = ap.parse_args()

    seasons = {int(s) for s in str(args.seasons).split(",") if s.strip()}
    g = load_games(default_csvs())
    art = MLArtifact.load_json(str(args.artifact))

    # Séries: mesmos dois times no mesmo dia, orientação fixa (team < opponent).
    g = g[g["yr"].isin(seasons)].copy()
    g["day"] = g["date"].dt.date
    g = g.sort_values("date").reset_index(drop=True)

    # (lift dado resultado anterior) por posição do mapa e por placar
    buckets: dict[str, list[tuple[int, float]]] = {}

    def _add(key: str, y: int, p: float) -> None:
        buckets.setdefault(key, []).append((int(y), float(p)))

    n_series = 0
    for (_day, team, opp), grp in g.groupby(["day", "team", "opponent"], sort=False):
        maps = grp.sort_values("date")
        if len(maps) < 2:
            continue
        bl, rl = str(maps.iloc[0]["dl"]), str(maps.iloc[0]["ol"])
        if not bl or not rl:
            continue
        # SIMETRIZADO como o produto: calibrador tem intercepto de lado azul
        # (b>0 => +5.6pp pro 1º slot); uma direção só contamina o estudo com
        # ~5pp de viés de orientação (detectado na 1ª rodada deste estudo).
        p_fwd = float(art.model.p_blue(str(team), str(opp), blue_league=bl, red_league=rl))
        p_rev = float(art.model.p_blue(str(opp), str(team), blue_league=rl, red_league=bl))
        if art.calibrator is not None:
            p_fwd = float(art.calibrator.predict_proba(p_fwd))
            p_rev = float(art.calibrator.predict_proba(p_rev))
        p = 0.5 * (p_fwd + (1.0 - p_rev))
        if not (0.01 < p < 0.99):
            continue
        n_series += 1
        wins = [int(w) for w in maps["win"].tolist()]
        score_a = 0
        for k, y in enumerate(wins):
            if k >= 1:
                prev = wins[k - 1]
                _add(f"mapa{k + 1}|{'ganhou' if prev else 'perdeu'} anterior", y, p)
                _add(f"todos_k>=2|{'ganhou' if prev else 'perdeu'} anterior", y, p)
                score_b = k - score_a
                estado = ("empate" if score_a == score_b
                          else "lider" if score_a > score_b else "atras")
                if estado == "empate":
                    _add("decider/empate", y, p)
                elif estado == "lider":
                    _add("lider joga", y, p)
                else:
                    _add("atras joga", y, p)
                # CRUZAMENTO placar x mapa anterior (08/09/2026) — o teste que
                # separa MOMENTO de FORCA REVELADA. Se o efeito for informacao
                # sobre a forca do time, com a serie EMPATADA a evidencia se
                # cancela e o mapa anterior nao deve prever nada. Se for
                # momento (psicologico), ele deve prever mesmo empatado.
                _add(f"[{estado}] {'ganhou' if prev else 'perdeu'} anterior", y, p)
            score_a += wins[k]

    print(f"[series_momentum] seasons={sorted(seasons)} | séries com 2+ mapas: {n_series}\n")
    print(f"{'condição':32} {'n':>6} {'real%':>7} {'modelo%':>8} {'lift pp':>8} {'z':>6}")
    order = sorted(buckets.keys(), key=lambda k: ("todos" not in k, k))
    for key in order:
        rows = buckets[key]
        n = len(rows)
        wins_k = sum(y for y, _ in rows)
        real = wins_k / n
        pbar = sum(p for _, p in rows) / n
        lift = 100.0 * (real - pbar)
        z = _binom_z(wins_k, n, pbar)
        flag = " <-- SINAL" if (isinstance(z, float) and math.isfinite(z) and abs(z) >= 2.5) else ""
        print(f"{key:32} {n:>6} {100 * real:>6.1f}% {100 * pbar:>7.1f}% {lift:>+8.2f} {z:>6.2f}{flag}")
    print("\nLeitura: lift = quanto o resultado real desvia do modelo NAQUELA condição.")
    print("Momentum real = lift positivo em 'ganhou anterior' E negativo em 'perdeu anterior' com |z|>=2.5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
