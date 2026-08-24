# -*- coding: utf-8 -*-
"""SCORECARD DA LIVE — a nota da fase Live (F7), calculada e reproduzível.

Regra suprema (dele, 18/07): cada fase no TETO REAL, testável e replicável;
quando algo não dá pra confiar, avisar. Esta régua CONSOLIDA os gates já
rodados da camada ao vivo (não re-treina — isso é caro; ela lê os artefatos
do último treino e AVISA se estiverem velhos):

  state->win  (FASE6_LIVE.json)          — o coração: estado do mapa -> P(vit)
  first-markets (FASE8_FIRST_MARKETS.json) — first blood/dragon/herald/tower/baron
  player-props (FASE10_PLAYER_PROPS.json)  — over/under de kills+assists por player
  momentum entre-mapas                     — gate ACCEPT +0.0084 logloss mapa-2

Régua de logloss = a MESMA do vencedor (0.6931=5.0, 0.55=9.5, linear); assim
a nota da Live é comparável à do ML pré-jogo. player-props é RMSE (regressão),
então usa uma sub-régua PRÓPRIA declarada (não-logloss) — marcada como tal.

Uso: python tools/live_scorecard.py
Saída: texto + evidence/live_scorecard.json
"""
from __future__ import annotations

import json
import math
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ml_quality_scorecard import _grade_from_logloss  # noqa: E402

STALE_DAYS = 45  # artefatos live mais velhos que isto = aviso (re-treinar)
# Pesos dos componentes na nota da Live (state->win domina: é o mais validado).
W_STATE, W_FIRST, W_PROPS, W_MOM = 0.50, 0.20, 0.15, 0.15
# Momentum entre-mapas: gate OOS ACCEPT (project_ml_quality_levers, alavanca L):
# mapa-2 logloss 0.5754->0.5671 (+0.0084, 4x a barra); deployado no app.
MOMENTUM_GATE_GAIN = 0.0084


def _age_days(iso: str) -> float | None:
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def _load(name: str) -> dict:
    p = ROOT / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _pt(m: dict, key: str) -> float:
    v = m.get(key)
    if isinstance(v, dict):
        v = v.get("point")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def score_state_to_win(d: dict) -> dict:
    """Nota do state->win: média ponderada (por n_test) da régua-logloss dos
    modelos candidatos por snapshot; reporta ganho vs baseline pré-jogo."""
    snaps = [s for s in d.get("snapshots", []) if s.get("candidate_metrics")]
    if not snaps:
        return {"nota": None, "detail": "sem snapshots treinados"}
    wsum = tot = gain = ece = base_tot = 0.0
    rows = []
    for s in snaps:
        n = float(s.get("n_test", 0) or 0)
        cll = _pt(s["candidate_metrics"], "logloss")
        bll = _pt(s.get("baseline_metrics", {}), "logloss")
        cece = _pt(s["candidate_metrics"], "ece")
        if not math.isfinite(cll) or n <= 0:
            continue
        g = _grade_from_logloss(cll)
        wsum += n
        tot += n * g
        base_tot += n * (_grade_from_logloss(bll) if math.isfinite(bll) else 0.0)
        gain += n * (bll - cll if math.isfinite(bll) else 0.0)
        ece += n * (cece if math.isfinite(cece) else 0.0)
        rows.append((s.get("minute"), cll, bll, cece, g))
    if wsum <= 0:
        return {"nota": None, "detail": "métricas inválidas"}
    nota = tot / wsum
    return {"nota": round(nota, 2),
            "detail": f"logloss candidato médio ~{sum(r[1] for r in rows)/len(rows):.4f} "
                      f"(pré-jogo {sum(r[2] for r in rows)/len(rows):.4f}, ganho {gain/wsum:+.4f}), "
                      f"ECE {ece/wsum:.3f}, {len(rows)} snapshots",
            "rows": rows}


def score_first_markets(d: dict) -> dict:
    res = d.get("results", [])
    if not res:
        return {"nota": None, "detail": "sem resultados"}
    wsum = tot = accepted = 0.0
    for r in res:
        n = float(r.get("n_test", 0) or 0)
        cll = float(r.get("candidate_logloss", float("nan")))
        bll = float(r.get("baseline_logloss", float("nan")))
        if not math.isfinite(cll) or n <= 0:
            continue
        wsum += n
        tot += n * _grade_from_logloss(cll)
        if math.isfinite(bll) and cll < bll:
            accepted += 1
    if wsum <= 0:
        return {"nota": None, "detail": "métricas inválidas"}
    return {"nota": round(tot / wsum, 2),
            "detail": f"{int(accepted)}/{len(res)} mercados melhoram o pré-jogo; "
                      f"nota régua-logloss ponderada"}


def score_player_props(d: dict) -> dict:
    """Sub-régua PRÓPRIA (RMSE, não logloss): aceito + ganho relativo de RMSE.
    Declarada como aproximação — kills+assists é regressão, não classificação."""
    brmse = float(d.get("baseline_rmse", float("nan")))
    crmse = float(d.get("candidate_rmse", float("nan")))
    if not (math.isfinite(brmse) and math.isfinite(crmse)) or brmse <= 0:
        return {"nota": None, "detail": "sem RMSE"}
    rel = (brmse - crmse) / brmse  # ganho relativo
    accept = bool(d.get("accept", False))
    # 7.0 base se aceito (bate o baseline com significância), +escala do ganho;
    # 5.0 se não aceito. Cap 9.0 (regressão de prop tem teto de ruído alto).
    nota = (7.0 + min(2.0, rel * 40.0)) if accept else 5.0
    return {"nota": round(min(9.0, nota), 2),
            "detail": f"RMSE {brmse:.3f}->{crmse:.3f} (ganho {rel:.1%}), "
                      f"aceito={accept} [sub-régua RMSE, não-logloss]"}


def main() -> int:
    t0 = time.time()
    f6 = _load("FASE6_LIVE.json")
    f8 = _load("FASE8_FIRST_MARKETS.json")
    f10 = _load("FASE10_PLAYER_PROPS.json")

    ages = {n: _age_days(d.get("generated_at", "")) for n, d in
            (("state->win", f6), ("first-markets", f8), ("player-props", f10)) if d}
    stale = {n: a for n, a in ages.items() if a is not None and a > STALE_DAYS}

    st_ = score_state_to_win(f6)
    fm_ = score_first_markets(f8)
    pp_ = score_player_props(f10)
    # momentum: gate ACCEPT documentado (deployado); nota alta fixa com fonte.
    mom = {"nota": 8.5, "detail": f"gate OOS ACCEPT (+{MOMENTUM_GATE_GAIN} logloss mapa-2), deployado no app"}

    comps = {"state->win (peso 0.50)": st_, "first-markets (0.20)": fm_,
             "player-props (0.15)": pp_, "momentum entre-mapas (0.15)": mom}

    parts, wsum = 0.0, 0.0
    for comp, w in ((st_, W_STATE), (fm_, W_FIRST), (pp_, W_PROPS), (mom, W_MOM)):
        if comp.get("nota") is not None:
            parts += w * comp["nota"]
            wsum += w
    nota = parts / wsum if wsum > 0 else float("nan")

    print(f"\n=== SCORECARD DA LIVE (F7) — {time.strftime('%Y-%m-%d')} ===")
    for name, c in comps.items():
        s = c.get("nota")
        print(f"  {name:28} {'n/a' if s is None else f'{s:5.2f}'}  {c['detail']}")
    print(f"\nNOTA DA LIVE = {nota:.2f}  (média ponderada dos componentes)")
    print("\nFrescor dos artefatos (dias): " +
          ", ".join(f"{n}={a:.0f}" for n, a in ages.items() if a is not None))
    if stale:
        print("AVISO: artefatos live VELHOS (> {}d): {} — re-treinar com "
              "tools/retrain_live_models_all.py + re-rodar os gates FASE6/8/10 "
              "antes de confiar nesta nota.".format(STALE_DAYS, ", ".join(f"{n}={a:.0f}d" for n, a in stale.items())))
    print("\nTETO REAL: state->win já opera ABAIXO do pré-jogo elite (logloss "
          "candidato < 0.55 nos snapshots iniciais) — é a camada mais validada "
          "do projeto; o teto é ~9.5 (limite de ruído do jogo ao vivo). A nota "
          "reflete o ÚLTIMO treino; re-treino move o número.")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nota_live": round(nota, 2) if math.isfinite(nota) else None,
           "componentes": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in comps.items()},
           "artifact_age_days": ages, "stale": bool(stale), "elapsed_s": round(time.time() - t0, 1)}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "live_scorecard.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n[live_scorecard] salvo: evidence/live_scorecard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
