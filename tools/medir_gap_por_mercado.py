# -*- coding: utf-8 -*-
"""MEDIÇÃO v2: o gap REAL do WHR (mu) ajuda a prever cada mercado? — OOS, sem vazamento.

Diferença da v1: em vez do proxy (diff de ouro aos 15), usa o mu do WHR — a
força que o modelo de fato calcula. Para não vazar, o artefato do WHR é
construído SÓ com os jogos até o corte de treino (CSVs filtrados por data).

Mesma metodologia: treino fita o coeficiente do gap; teste (futuro) mede se
o erro cai. Totais -> RMSE; First X -> Brier.
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
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlcore.stats_teams import load_team_rows, build_team_games  # noqa: E402
from mlcore.state_team_artifact import build_team_state_artifact  # noqa: E402
from mlcore.team_artifact_normalize import _norm_team_key  # noqa: E402

CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]
TOTAIS = {
    "kills":      ("kills_for", "kills_against", "total_kills"),
    "torres":     ("towers_for", "towers_against", "total_towers"),
    "dragoes":    ("dragons_for", "dragons_against", "total_dragons"),
    "baroes":     ("barons_for", "barons_against", "total_nashors"),
    "inibidores": ("inhibitors_for", "inhibitors_against", "total_inhibitors"),
    "tempo":      (None, None, "game_time_min"),
}
FIRST_X = {"first_blood": "firstblood_for", "first_tower": "firsttower_for",
           "first_dragon": "firstdragon_for", "first_baron": "firstbaron_for"}


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _fit_logit_beta(base, y, gn, iters=250, lr=0.3):
    beta, lb = 0.0, _logit(np.clip(base, 1e-4, 1 - 1e-4))
    for _ in range(iters):
        beta -= lr * float(np.mean((_sig(lb + beta * gn) - y) * gn))
    return float(beta)


def _mu_from_train(cut_date, tmpdir) -> dict:
    """Constrói o WHR SÓ com jogos <= cut_date e devolve {team_key: mu}."""
    train_csvs = []
    for i, p in enumerate(CSVS):
        fp = ROOT / p
        if not fp.exists():
            continue
        df = pd.read_csv(fp, low_memory=False)
        d = pd.to_datetime(df["date"], errors="coerce")
        sub = df[d <= cut_date]
        if not len(sub):
            continue
        out = Path(tmpdir) / f"train_{i}.csv"
        sub.to_csv(out, index=False)
        train_csvs.append(str(out))
    print(f"  [whr] construindo artefato com {len(train_csvs)} CSVs de treino (pode levar ~2min)...", flush=True)
    art = build_team_state_artifact(train_csvs, include_players_for_roster=False)
    teams = art.get("teams") or {}
    mu = {}
    for k, d in teams.items():
        if isinstance(d, dict) and d.get("mu") is not None:
            mu[str(k)] = float(d["mu"])
    print(f"  [whr] mu de {len(mu)} times")
    return mu


def main():
    frames = []
    for p in CSVS:
        fp = ROOT / p
        if fp.exists():
            frames.append(build_team_games(load_team_rows(str(fp))))
    tg = pd.concat(frames, ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date", "team", "opponent"]).sort_values("date").reset_index(drop=True)
    cut = tg["date"].quantile(0.80)
    train = tg[tg["date"] <= cut].copy()
    test = tg[tg["date"] > cut].copy()
    print(f"jogos-linha: {len(tg)} | treino <= {cut.date()} ({len(train)}) | teste ({len(test)})")

    with tempfile.TemporaryDirectory() as td:
        mu_map = _mu_from_train(cut, td)
    mu_mean = float(np.mean(list(mu_map.values()))) if mu_map else 0.0

    def rt(team):
        v = mu_map.get(_norm_team_key(team))
        return float(v) if v is not None and np.isfinite(v) else mu_mean

    cover = float(np.mean([_norm_team_key(t) in mu_map for t in test["team"].unique()]))
    print(f"  [whr] cobertura de times do teste no artefato: {100*cover:.1f}%")

    gdef = {c: float(_num(train[c]).mean()) for c in
            ["kills_for", "kills_against", "towers_for", "towers_against",
             "dragons_for", "dragons_against", "barons_for", "barons_against",
             "inhibitors_for", "inhibitors_against"] if c in train.columns}
    prof = {}
    for team, d in train.groupby("team"):
        prof[str(team)] = {c: float(_num(d[c]).mean()) for c in gdef}
    prof_series = {c: {t: prof[t].get(c, gdef[c]) for t in prof} for c in gdef}
    tempo_mean = float(_num(train["game_time_min"]).mean())

    def col_of(df, tcol, col):
        return df[tcol].map(lambda t: prof_series[col].get(str(t), gdef[col])).astype(float)

    def gap_abs(df):
        return (df["team"].map(rt).astype(float) - df["opponent"].map(rt).astype(float)).abs()

    def gap_signed(df):
        return df["team"].map(rt).astype(float) - df["opponent"].map(rt).astype(float)

    def baseline_vec(df, mkt):
        cf, ca, _ = TOTAIS[mkt]
        if cf is None:
            return pd.Series(tempo_mean, index=df.index)
        a = 0.5 * (col_of(df, "team", cf) + col_of(df, "opponent", ca))
        b = 0.5 * (col_of(df, "opponent", cf) + col_of(df, "team", ca))
        return a + b

    tr_b = train[train["side"].astype(str).str.lower().eq("blue")]
    te_b = test[test["side"].astype(str).str.lower().eq("blue")]

    print("\n=== TOTAIS com gap REAL do WHR (|mu_A - mu_B|) — RMSE OOS ===")
    print(f"{'mercado':12} {'RMSE base':>10} {'RMSE +gap':>10} {'ganho%':>8} {'beta':>9}  veredito")
    for mkt in TOTAIS:
        def build(df):
            base = baseline_vec(df, mkt).astype(float)
            act = _num(df[TOTAIS[mkt][2]]).astype(float)
            gap = gap_abs(df).astype(float)
            m = base.notna() & act.notna() & gap.notna()
            return base[m].values, act[m].values, gap[m].values
        b_tr, a_tr, g_tr = build(tr_b)
        b_te, a_te, g_te = build(te_b)
        res = a_tr - b_tr
        beta = float(np.dot(g_tr, res) / max(1e-9, np.dot(g_tr, g_tr)))
        rb = float(np.sqrt(np.mean((a_te - b_te) ** 2)))
        rg = float(np.sqrt(np.mean((a_te - (b_te + beta * g_te)) ** 2)))
        ganho = 100.0 * (rb - rg) / rb
        v = "ACCEPT" if ganho > 0.3 else ("~neutro" if ganho > -0.3 else "REJECT")
        print(f"{mkt:12} {rb:10.3f} {rg:10.3f} {ganho:+7.2f}% {beta:+9.4f}  {v}")

    print("\n=== FIRST X com gap REAL do WHR (mu_A - mu_B) — Brier OOS ===")
    print(f"{'evento':12} {'Brier base':>11} {'Brier +gap':>11} {'ganho%':>8} {'beta':>9} {'gap_sd':>8}  veredito")
    calib = {}
    for ev, col in FIRST_X.items():
        fx = _num(train.assign(_v=_num(train[col])).groupby("team")["_v"].mean()).to_dict()

        def bf(df):
            base = df["team"].map(lambda t: fx.get(str(t), 0.5)).astype(float).fillna(0.5)
            act = _num(df[col]).astype(float)
            gap = gap_signed(df).astype(float)
            m = base.notna() & act.notna() & gap.notna()
            return base[m].values, act[m].values, gap[m].values
        b_tr, a_tr, g_tr = bf(train)
        b_te, a_te, g_te = bf(test)
        sd = float(np.std(g_tr)) + 1e-9
        beta = _fit_logit_beta(b_tr, a_tr, g_tr / sd)
        pb = np.clip(b_te, 1e-4, 1 - 1e-4)
        pg = _sig(_logit(pb) + beta * (g_te / sd))
        bb = float(np.mean((pb - a_te) ** 2))
        bg = float(np.mean((pg - a_te) ** 2))
        ganho = 100.0 * (bb - bg) / bb
        v = "ACCEPT" if ganho > 0.5 else ("~neutro" if ganho > -0.5 else "REJECT")
        print(f"{ev:12} {bb:11.4f} {bg:11.4f} {ganho:+7.2f}% {beta:+9.4f} {sd:8.4f}  {v}")
        calib[col.replace("_for", "")] = {
            "evento": ev, "beta": round(beta, 6), "gap_sd": round(sd, 6),
            "ganho_pct": round(ganho, 4), "veredito": v,
            "brier_base": round(bb, 6), "brier_gap": round(bg, 6),
        }

    import json as _json
    out = ROOT / "scratchpad" / "first_x_gap_calib.json"
    out.write_text(_json.dumps({"n_teste": int(len(te_b)), "corte": str(cut.date()),
                                "cobertura_mu": round(cover, 4), "eventos": calib},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[calib] salvo: {out}")


if __name__ == "__main__":
    main()
