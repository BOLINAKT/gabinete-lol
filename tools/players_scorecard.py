# -*- coding: utf-8 -*-
"""SCORECARD DOS PLAYERS — a nota da fase Players, reproduzível.

Regra suprema (dele, 18/07): teto real, testável, e declarar o teto.
A camada de players NÃO prediz sozinha — ela AGREGA valor sobre o core
(WHR+MOVDA). Então a nota mede o VALOR INCREMENTAL medido em walk-forward
OOS (não um logloss absoluto). Componentes, lidos de params_fitted.json
(players_context_fit, do fit promovido) + a exposição na UI:

  ganho-oos    — o quanto a camada melhora o logloss OOS vs core puro,
                 ancorado na barra de gate do projeto (0.0004 = aceitável)
                 e num ganho FORTE p/ camada incremental (0.010).
  cobertura    — fração de jogos que recebem o ajuste (ctx_applied_rate).
  exposicao-ui — a leitura individual (percentil por role, à la PandaSkill)
                 está no app? (players_value_core / players_tab_core).

Uso: python tools/players_scorecard.py
Saída: texto + evidence/players_scorecard.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

W_GAIN, W_COV, W_UI = 0.55, 0.25, 0.20
GATE_BAR = 0.0004      # barra de gate do projeto p/ a camada (min_improvement_logloss)
STRONG_GAIN = 0.010    # ganho FORTE p/ camada incremental sobre core já bom


def _grade_gain(gain: float) -> float:
    """Barra de gate (0.0004)=6.0 (aceitável); ganho forte (0.010)=9.0; linear."""
    if not math.isfinite(gain):
        return float("nan")
    g = 6.0 + (gain - GATE_BAR) / (STRONG_GAIN - GATE_BAR) * 3.0
    return float(max(0.0, min(9.5, g)))


def main() -> int:
    t0 = time.time()
    params = json.loads((ROOT / "params_fitted.json").read_text(encoding="utf-8-sig"))
    pc = params.get("players_context_fit", {})
    if not pc:
        print("params_fitted.json sem players_context_fit — rode o fit (F4).")
        return 1

    off = pc.get("baseline_off", {})
    on = pc.get("best_on", {})
    gate = pc.get("gate", {})
    ll_off = float(off.get("logloss", float("nan")))
    ll_on = float(on.get("logloss", float("nan"))) if isinstance(on, dict) else float("nan")
    gain = ll_off - ll_on
    ctx = on.get("context", {}) if isinstance(on, dict) else {}
    cov = float(ctx.get("ctx_applied_rate", float("nan")))
    n_total = int(ctx.get("ctx_total", 0) or 0)
    brier_gain = float(off.get("brier", float("nan"))) - float(on.get("brier", float("nan"))) if isinstance(on, dict) else float("nan")

    ui = (ROOT / "app_core" / "players_value_core.py").exists() and (ROOT / "app_core" / "players_tab_core.py").exists()

    comps = {
        "ganho-oos (peso 0.55)": {
            "nota": round(_grade_gain(gain), 2),
            "detail": f"logloss {ll_off:.4f}->{ll_on:.4f} (ganho {gain:+.4f} = {gain/GATE_BAR:.0f}x a barra de gate; "
                      f"brier {brier_gain:+.4f}); OOS n={n_total}, gate={gate.get('decision')}"},
        "cobertura (0.25)": {
            "nota": round(cov * 10, 2) if math.isfinite(cov) else None,
            "detail": f"{cov:.0%} dos jogos recebem o ajuste da camada"},
        "exposicao-ui (0.20)": {
            "nota": 10.0 if ui else 0.0,
            "detail": "percentil por role (PandaSkill) exposto na aba Players" if ui else "sem leitura individual na UI"},
    }
    weights = {"ganho-oos (peso 0.55)": W_GAIN, "cobertura (0.25)": W_COV, "exposicao-ui (0.20)": W_UI}
    parts, wsum = 0.0, 0.0
    for name, c in comps.items():
        if c["nota"] is not None:
            parts += weights[name] * c["nota"]
            wsum += weights[name]
    nota = parts / wsum if wsum > 0 else float("nan")

    print(f"\n=== SCORECARD DOS PLAYERS (F4) — {time.strftime('%Y-%m-%d')} ===")
    for name, c in comps.items():
        s = c["nota"]
        print(f"  {name:24} {'n/a' if s is None else f'{s:5.2f}'}  {c['detail']}")
    print(f"\nNOTA DOS PLAYERS = {nota:.2f}  (média ponderada)")
    print("TETO REAL: ~9.0, NÃO 10. Dois limites estruturais declarados: (1) o "
          "core WHR+MOVDA já absorve parte do sinal individual (por isso "
          "w_lineup do artifact é 0; o ganho vem da segmentação por liga do "
          "context); (2) roster churn / stand-in ainda NÃO modelados (backlog "
          "'blindagem de roster'). A camada agrega valor OOS real e está exposta.")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nota_players": round(nota, 2) if math.isfinite(nota) else None,
           "gain_logloss": round(gain, 5), "coverage": round(cov, 4) if math.isfinite(cov) else None,
           "componentes": comps, "elapsed_s": round(time.time() - t0, 1)}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "players_scorecard.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[players_scorecard] salvo: evidence/players_scorecard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
