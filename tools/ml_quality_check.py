"""Alarme de qualidade pos-retrain — compara a nota ATUAL vs baseline e grita se caiu.

Nasceu do incidente de 2026-06-06/10: a Manutencao completa retreinou com holdout 180,
os ratings congelaram 6 meses atras e a nota despencou de 7.74 p/ 4.97 SEM nenhum aviso
por 4 dias. O guard de artefato (test_live_artifact_complete) verifica se o artefato esta
COMPLETO, nao se esta BOM. Este check fecha esse buraco: roda apos qualquer retrain.

Comportamento:
  - Mede o snapshot da season atual (mesma matematica do ml_quality_diagnose).
  - Sem baseline -> fixa o atual como baseline e retorna ok.
  - Atual MELHOR que baseline (logloss -0.002 ou mais) -> re-fixa baseline (regua sobe).
  - Atual pior ate +0.010 logloss -> ok (ruido).
  - Pior entre +0.010 e +0.020 -> verdict=warn (exit 0, mas registrado).
  - Pior alem de +0.020 (~ -0.6 de nota) -> verdict=fail (exit 3) = ALARME.

Sempre grava ops/monitoring/ml_quality_last_check.json (a UI le esse arquivo).

  python tools/ml_quality_check.py
  python tools/ml_quality_check.py --artifact ml_artifact.json --set-baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ml_quality_diagnose import snapshot
from tools.ml_quality_scorecard import _grade_from_logloss

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "ops" / "monitoring" / "ml_quality_baseline.json"
LAST_CHECK_PATH = ROOT / "ops" / "monitoring" / "ml_quality_last_check.json"

# Limiares sobre o logloss GERAL calibrado vs baseline.
WARN_DELTA = 0.010   # ~ -0.3 de nota
FAIL_DELTA = 0.020   # ~ -0.6 de nota (o incidente foi +0.09)
REPIN_DELTA = 0.002  # melhora minima p/ re-fixar baseline


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def compare_to_baseline(cur: dict, base: dict | None) -> dict:
    """Verdito puro (testavel): ok / ok_improved / warn / fail / no_baseline."""
    cur_ll = _f((cur.get("geral_cal") or {}).get("logloss"))
    if not (cur_ll == cur_ll):  # NaN
        return {"verdict": "error", "reason": "snapshot sem logloss geral_cal"}
    if not isinstance(base, dict) or not isinstance(base.get("geral_cal"), dict):
        return {"verdict": "no_baseline", "reason": "baseline inexistente; fixando o atual", "delta_logloss": None}
    base_ll = _f((base.get("geral_cal") or {}).get("logloss"))
    if not (base_ll == base_ll):
        return {"verdict": "no_baseline", "reason": "baseline sem logloss; refixando", "delta_logloss": None}
    delta = float(cur_ll - base_ll)
    out = {
        "delta_logloss": delta,
        "current_logloss": float(cur_ll),
        "baseline_logloss": float(base_ll),
        "current_nota": _grade_from_logloss(float(cur_ll)),
        "baseline_nota": _grade_from_logloss(float(base_ll)),
    }
    if delta <= -REPIN_DELTA:
        out.update({"verdict": "ok_improved", "reason": f"melhorou {-delta:.4f} de logloss; baseline re-fixado"})
    elif delta >= FAIL_DELTA:
        out.update({"verdict": "fail", "reason": (
            f"NOTA CAIU: logloss {cur_ll:.4f} vs baseline {base_ll:.4f} (+{delta:.4f}; "
            f"nota {out['current_nota']:.1f} vs {out['baseline_nota']:.1f}). "
            "Modelo possivelmente degradado — verificar retrain (holdout? csvs? cutoff)."
        )})
    elif delta >= WARN_DELTA:
        out.update({"verdict": "warn", "reason": f"logloss +{delta:.4f} vs baseline (acima do ruido, abaixo do alarme)"})
    else:
        out.update({"verdict": "ok", "reason": f"dentro do ruido ({delta:+.4f} logloss)"})
    return out


def run_check(artifact: str = "ml_artifact.json", *, set_baseline: bool = False) -> dict:
    cur = snapshot(artifact, None, 45)
    if cur.get("error"):
        result = {"verdict": "error", "reason": str(cur.get("error"))}
    else:
        base = None
        if BASELINE_PATH.exists():
            try:
                base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
            except Exception:
                base = None
        if set_baseline:
            result = {"verdict": "baseline_set", "reason": "baseline fixado manualmente",
                      "current_logloss": _f((cur.get("geral_cal") or {}).get("logloss"))}
            base = None  # forca gravacao abaixo
        else:
            result = compare_to_baseline(cur, base)
        if result.get("verdict") in ("no_baseline", "ok_improved", "baseline_set"):
            BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
            BASELINE_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "artifact": str(artifact),
        "season": cur.get("season"),
        "result": result,
        "current_geral_cal": cur.get("geral_cal"),
        "baseline_path": str(BASELINE_PATH),
    }
    LAST_CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_CHECK_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Checagem de qualidade do ML vs baseline (alarme pos-retrain).")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--set-baseline", action="store_true", help="Fixa o estado atual como baseline e sai.")
    args = ap.parse_args()

    payload = run_check(args.artifact, set_baseline=bool(args.set_baseline))
    result = payload.get("result") or {}
    verdict = str(result.get("verdict") or "error")
    print(f"[ml_quality_check] verdict={verdict} | {result.get('reason', '')}")
    cur_ll = result.get("current_logloss")
    if isinstance(cur_ll, float):
        print(f"[ml_quality_check] logloss atual={cur_ll:.4f} (nota {_grade_from_logloss(cur_ll):.2f})")
    if verdict == "fail":
        return 3
    if verdict == "error":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
