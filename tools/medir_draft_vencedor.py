# -*- coding: utf-8 -*-
"""MEDIÇÃO: o DRAFT sozinho prevê o vencedor do mapa? — acurácia OOS (teto ~57%?).

Pedido dele (24/07): ver com o dado ATUAL se o teto de ~56-57% do draft-puro
(loldraftai/literatura) mudou. Modelo TRANSPARENTE (não é rede neural):
  - WR histórico de cada campeão (shrinkado pra 0.5), SÓ de jogos ANTERIORES.
  - Sinal do jogo = média(WR dos 5 champs blue) − média(WR dos 5 red).
  - Logística fit no treino (o intercepto captura a vantagem do lado azul).
  - Acurácia + logloss OOS. Compara com o piso (só o lado azul).

Sem identidade de time, sem força de time — SÓ os campeões. É o teto honesto do
draft-puro; uma rede neural (synergies/counters) espremeria talvez +1pp.
"""
from __future__ import annotations

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
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]
WR_K = 30.0  # shrinkage do WR do campeão pra 0.5


def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def _load_games() -> pd.DataFrame:
    """Um registro por jogo: date, champs_blue[5], champs_red[5], blue_win."""
    frames = []
    for p in CSVS:
        fp = ROOT / p
        if not fp.exists():
            continue
        df = pd.read_csv(fp, low_memory=False,
                         usecols=["gameid", "date", "side", "champion", "result", "participantid"])
        pid = pd.to_numeric(df["participantid"], errors="coerce")
        pr = df[pid.between(1, 10) & df["champion"].notna()].copy()
        pr["side"] = pr["side"].astype(str).str.strip().str.lower()
        frames.append(pr[["gameid", "date", "side", "champion", "result"]])
    allp = pd.concat(frames, ignore_index=True)
    allp["date"] = pd.to_datetime(allp["date"], errors="coerce")
    rows = []
    for gid, g in allp.groupby("gameid", sort=False):
        blue = g[g["side"] == "blue"]
        red = g[g["side"] == "red"]
        if len(blue) < 5 or len(red) < 5:
            continue
        try:
            bw = int(float(blue["result"].iloc[0]))
        except (ValueError, TypeError):
            continue
        rows.append({
            "gameid": str(gid), "date": g["date"].dropna().iloc[0] if g["date"].notna().any() else pd.NaT,
            "blue": list(blue["champion"].astype(str))[:5],
            "red": list(red["champion"].astype(str))[:5],
            "blue_win": bw,
        })
    out = pd.DataFrame(rows).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return out


def _champ_wr(train: pd.DataFrame) -> dict:
    """WR shrinkado por campeão, contado no TREINO (ambos os lados)."""
    wins: dict[str, float] = {}
    games: dict[str, float] = {}
    for r in train.itertuples(index=False):
        for c in r.blue:
            games[c] = games.get(c, 0) + 1
            wins[c] = wins.get(c, 0) + r.blue_win
        for c in r.red:
            games[c] = games.get(c, 0) + 1
            wins[c] = wins.get(c, 0) + (1 - r.blue_win)
    return {c: (wins.get(c, 0) + WR_K * 0.5) / (games[c] + WR_K) for c in games}


def _signal(df: pd.DataFrame, wr: dict, glob: float) -> np.ndarray:
    def team_wr(champs):
        vals = [wr.get(c, glob) for c in champs]
        return float(np.mean(vals)) if vals else glob
    return np.array([team_wr(r.blue) - team_wr(r.red) for r in df.itertuples(index=False)])


def main():
    g = _load_games()
    cut = g["date"].quantile(0.80)
    train = g[g["date"] <= cut].reset_index(drop=True)
    test = g[g["date"] > cut].reset_index(drop=True)
    print(f"jogos: {len(g)} | treino <= {cut.date()} ({len(train)}) | teste ({len(test)})")

    wr = _champ_wr(train)
    glob = float(np.mean(list(wr.values()))) if wr else 0.5
    s_tr = _signal(train, wr, glob)
    s_te = _signal(test, wr, glob)
    y_tr = train["blue_win"].to_numpy(dtype=float)
    y_te = test["blue_win"].to_numpy(dtype=float)

    # logística fit no treino (a = vantagem do lado azul; b = peso do sinal de draft)
    a, b = 0.0, 0.0
    sd = float(np.std(s_tr)) + 1e-9
    z_tr, z_te = s_tr / sd, s_te / sd
    for _ in range(600):
        p = _sig(a + b * z_tr)
        a -= 0.1 * float(np.mean(p - y_tr))
        b -= 0.1 * float(np.mean((p - y_tr) * z_tr))

    p_te = _sig(a + b * z_te)
    acc_draft = float(np.mean((p_te >= 0.5) == (y_te >= 0.5)))
    ll_draft = float(-np.mean(y_te * np.log(np.clip(p_te, 1e-9, 1)) + (1 - y_te) * np.log(np.clip(1 - p_te, 1e-9, 1))))

    # pisos de referência
    base_rate_blue = float(np.mean(y_te))
    acc_side = max(base_rate_blue, 1 - base_rate_blue)  # sempre chutar o lado majoritário
    ll_side = float(-np.mean(y_te * np.log(base_rate_blue) + (1 - y_te) * np.log(1 - base_rate_blue)))

    print("\n=== DRAFT SOZINHO prevê o vencedor? (OOS) ===")
    print(f"  acurácia DRAFT (champ-WR agregado): {100*acc_draft:.2f}%   logloss {ll_draft:.4f}")
    print(f"  piso — só o LADO azul (majoritário): {100*acc_side:.2f}%   logloss {ll_side:.4f}")
    print(f"  ganho do draft sobre o lado:         {100*(acc_draft-acc_side):+.2f} pp")
    print(f"  (blue win rate no teste: {100*base_rate_blue:.1f}% · vantagem de lado real)")
    print(f"  peso do sinal de draft (b): {b:+.3f}  ·  intercepto lado (a): {a:+.3f}")
    print("\nReferência: loldraftai (rede neural, milhões de ranked) = 56,7% no draft-puro.")


if __name__ == "__main__":
    main()
