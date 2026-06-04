"""Diagnóstico de qualidade do ML — identifica a QUEDA da nota e prescreve a SOLUÇÃO.

A nota sozinha diz "caiu"; este comando diz "caiu ONDE, POR QUÊ e O QUE FAZER".
Tira um retrato decomposto da qualidade do modelo ao vivo (Elo + calibrador Platt)
e compara com um baseline salvo. Para cada dimensão que regrediu além do limiar,
emite um diagnóstico + a ação recomendada.

Dimensões (cada uma aponta uma causa diferente):
  - segmento: inter-liga vs mesma-liga (cross-região defasado vs forma recente);
  - métrica: logloss (discriminação) e ECE (calibração) — separa "o modelo erra"
    de "as probabilidades não batem";
  - cru vs calibrado: isola se o problema é o Elo ou o calibrador Platt;
  - janela recente (últimos N dias) vs temporada: pega DRIFT (patch/meta/rosters);
  - saúde dos dados: nº de jogos, span de datas, times com poucos jogos (cold-start).

Uso:
  python tools/ml_quality_diagnose.py                 # diagnostica vs baseline
  python tools/ml_quality_diagnose.py --set-baseline  # salva o estado atual como baseline
  python tools/ml_quality_diagnose.py --recent-days 45
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mlcore.artifact import MLArtifact
from mlcore.stats_teams import build_team_games, load_team_rows

ROOT = Path(__file__).resolve().parents[1]
INTL = {"EWC", "MSI", "WORLDS", "FST", "IEM", "FIRST STAND"}
DEFAULT_CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]
BASELINE_PATH = ROOT / "ops" / "monitoring" / "ml_quality_baseline.json"

# Limiares de regressão (quanto pior que o baseline para acender alerta).
THRESH = {"logloss": 0.010, "ece": 0.010, "acc": -0.010}  # acc: queda de 1pp


def _metrics(rows: list[tuple[float, int]]) -> dict:
    if not rows:
        return {"n": 0, "logloss": float("nan"), "ece": float("nan"), "acc": float("nan")}
    n = len(rows)
    ll = sum(-(y * math.log(min(max(p, 1e-6), 1 - 1e-6)) + (1 - y) * math.log(1 - min(max(p, 1e-6), 1 - 1e-6))) for p, y in rows) / n
    acc = sum(1 for p, y in rows if (p >= 0.5) == (y == 1)) / n
    bins: dict[int, list] = {}
    for p, y in rows:
        bins.setdefault(min(9, int(p * 10)), []).append((p, y))
    ece = sum((len(v) / n) * abs(sum(pp for pp, _ in v) / len(v) - sum(yy for _, yy in v) / len(v)) for v in bins.values())
    return {"n": n, "logloss": ll, "ece": ece, "acc": acc}


def _load_games(csvs: list[str]) -> pd.DataFrame:
    frames = []
    for p in csvs:
        fp = p if Path(p).is_absolute() else str(ROOT / p)
        try:
            frames.append(build_team_games(load_team_rows(fp)))
        except Exception as e:
            print(f"skip {p}: {e}")
    df = pd.concat(frames, ignore_index=True)
    dom = df[~df["league"].astype(str).str.upper().isin(INTL)]
    tl = dom.groupby("team")["league"].agg(lambda s: s.astype(str).value_counts().index[0] if len(s) else "")
    df["dl"] = df["team"].map(tl)
    df["ol"] = df["opponent"].map(tl)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["win"] = pd.to_numeric(df["win"], errors="coerce")
    df = df.dropna(subset=["win", "date"])
    g = df[df["team"].astype(str) < df["opponent"].astype(str)].copy()
    return g[g["dl"].ne("") & g["ol"].ne("")].sort_values("date")


def snapshot(artifact: str, season: int, recent_days: int) -> dict:
    art = MLArtifact.load_json(str(artifact if Path(artifact).is_absolute() else ROOT / artifact))
    g = _load_games(DEFAULT_CSVS)
    g = g[g["date"].dt.year == int(season)]
    if g.empty:
        return {"error": f"sem jogos {season}"}
    cutoff = g["date"].max() - pd.Timedelta(days=int(recent_days))

    inter_cal, same_cal, raw_all, recent_cal = [], [], [], []
    for r in g.itertuples(index=False):
        praw = float(art.model.p_blue(str(r.team), str(r.opponent), blue_league=r.dl, red_league=r.ol))
        pcal = float(art.calibrator.predict_proba(praw)) if art.calibrator is not None else praw
        y = int(r.win)
        raw_all.append((praw, y))
        (inter_cal if r.dl != r.ol else same_cal).append((pcal, y))
        if r.date >= cutoff:
            recent_cal.append((pcal, y))

    mi, ms = _metrics(inter_cal), _metrics(same_cal)
    geral_cal = _metrics(inter_cal + same_cal)
    mraw = _metrics(raw_all)
    mrec = _metrics(recent_cal)

    teams = pd.concat([g["team"], g["opponent"]])
    vc = teams.value_counts()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact": str(artifact),
        "season": int(season),
        "recent_days": int(recent_days),
        "inter": mi, "same": ms, "geral_cal": geral_cal, "geral_raw": mraw, "recent": mrec,
        "data": {
            "n_games": len(g),
            "date_min": str(g["date"].min().date()),
            "date_max": str(g["date"].max().date()),
            "n_teams": int(vc.shape[0]),
            "n_cold_teams": int((vc < 5).sum()),
        },
    }


def _diagnose(cur: dict, base: dict) -> list[dict]:
    """Compara cur vs base e devolve [{severidade, sintoma, causa, solucao}]."""
    out: list[dict] = []

    def worse(metric: str, c: dict, b: dict) -> float | None:
        cv, bv = c.get(metric), b.get(metric)
        if not (isinstance(cv, (int, float)) and isinstance(bv, (int, float))):
            return None
        if not (math.isfinite(cv) and math.isfinite(bv)):
            return None
        return cv - bv  # logloss/ece: positivo = pior; acc: negativo = pior

    # Calibração (ECE) vs discriminação (logloss), por segmento.
    for seg, label in (("inter", "inter-liga (cross-região)"), ("same", "mesma-liga")):
        d_ll = worse("logloss", cur[seg], base[seg])
        d_ece = worse("ece", cur[seg], base[seg])
        if d_ece is not None and d_ece > THRESH["ece"]:
            out.append({
                "sev": "ALERTA", "sintoma": f"ECE {label} subiu {d_ece:+.4f}",
                "causa": "Calibração defasada (probabilidades não batem com a realidade).",
                "solucao": "Rebuild (re-fita o Platt) via `atualizar_modelo`. Se persistir, calibração por segmento / isotônica.",
            })
        if d_ll is not None and d_ll > THRESH["logloss"]:
            if seg == "inter":
                out.append({
                    "sev": "ALERTA", "sintoma": f"logloss inter-liga subiu {d_ll:+.4f}",
                    "causa": "Força-de-liga (SOS) defasada ou faltam jogos cross-região recentes.",
                    "solucao": "Rebuild via `atualizar_modelo` (re-fita SOS). Cross-região melhora com mais MSI/Worlds/EWC — checar ingestão.",
                })
            else:
                out.append({
                    "sev": "ALERTA", "sintoma": f"logloss mesma-liga subiu {d_ll:+.4f}",
                    "causa": "Forma recente defasada (ratings velhos para o split atual).",
                    "solucao": "Rebuild via `atualizar_modelo` (holdout 30 capta recência via k/alpha).",
                })

    # Cru vs calibrado: isola Elo vs calibrador.
    d_raw = worse("logloss", cur["geral_raw"], base["geral_raw"])
    d_cal = worse("logloss", cur["geral_cal"], base["geral_cal"])
    if d_raw is not None and d_cal is not None:
        if d_raw > THRESH["logloss"] and d_cal <= THRESH["logloss"]:
            out.append({"sev": "INFO", "sintoma": "Elo cru piorou mas calibrado segura",
                        "causa": "Elo degradou; o Platt está compensando.", "solucao": "Rebuild preventivo via `atualizar_modelo`."})
        elif d_cal > THRESH["logloss"] and d_raw <= THRESH["logloss"]:
            out.append({"sev": "ALERTA", "sintoma": "Calibrado piorou mas Elo cru ok",
                        "causa": "Calibrador Platt defasado.", "solucao": "Rebuild via `atualizar_modelo` (re-fita o calibrador)."})

    # Drift recente: janela recente pior que a temporada inteira (no estado atual).
    rec_vs_full = (cur["recent"].get("logloss", float("nan")) - cur["geral_cal"].get("logloss", float("nan")))
    if isinstance(rec_vs_full, float) and math.isfinite(rec_vs_full) and rec_vs_full > 0.03:
        out.append({"sev": "ALERTA", "sintoma": f"janela recente {rec_vs_full:+.4f} pior que a temporada",
                    "causa": "DRIFT recente: patch/meta novo, trocas de roster, ou modelo defasado.",
                    "solucao": "Ingerir CSV novo + rebuild (`atualizar_modelo`). Se for patch grande, considerar re-fit do fit de fusão."})

    # Saúde dos dados.
    if base.get("data"):
        cold_up = cur["data"]["n_cold_teams"] - base["data"]["n_cold_teams"]
        if cold_up >= 3:
            out.append({"sev": "INFO", "sintoma": f"+{cold_up} times com <5 jogos (cold-start)",
                        "causa": "Times/rosters novos sem amostra — previsão imatura para eles.",
                        "solucao": "Esperar acumular jogos; a camada de players ajuda no curto prazo."})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico de qualidade do ML (queda + solução).")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--recent-days", type=int, default=45)
    ap.add_argument("--set-baseline", action="store_true", help="Salva o estado atual como baseline e sai.")
    args = ap.parse_args()

    cur = snapshot(args.artifact, args.season, args.recent_days)
    if cur.get("error"):
        print("ERRO:", cur["error"]); return 2

    print(f"\n=== DIAGNÓSTICO ML — {args.artifact} season={args.season} ===")
    print(f"{'dimensão':22} {'logloss':>9} {'ece':>8} {'acc':>7} {'n':>6}")
    for key, lab in (("inter", "inter-liga"), ("same", "mesma-liga"), ("geral_cal", "GERAL (calibrado)"),
                     ("geral_raw", "GERAL (cru)"), ("recent", f"recente {args.recent_days}d")):
        m = cur[key]
        print(f"{lab:22} {m['logloss']:>9.4f} {m['ece']:>8.4f} {m['acc']:>7.3f} {m['n']:>6}")
    d = cur["data"]
    print(f"dados: {d['n_games']} jogos | {d['date_min']}..{d['date_max']} | {d['n_teams']} times | {d['n_cold_teams']} cold-start")

    if args.set_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nBASELINE salvo em {BASELINE_PATH.relative_to(ROOT)} (estado atual = referência).")
        return 0

    if not BASELINE_PATH.exists():
        print("\n(sem baseline ainda — rode com --set-baseline para fixar a referência.)")
        return 0

    base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    print(f"\nComparando com baseline de {base.get('generated_at', '?')[:19]}:")
    issues = _diagnose(cur, base)
    if not issues:
        print("  ✅ Sem queda relevante de qualidade. Modelo saudável.")
    else:
        for it in issues:
            print(f"  [{it['sev']}] {it['sintoma']}")
            print(f"        causa:   {it['causa']}")
            print(f"        solução: {it['solucao']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
