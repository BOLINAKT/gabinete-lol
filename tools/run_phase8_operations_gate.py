from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}
    return {}


def _norm_dec(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in {"promote", "shadow_only", "reject"} else "unknown"


def _rank_dec(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2, "unknown": 1}.get(dec, 1)


def _run(cmd: List[str], timeout: int = 900) -> Tuple[int, str]:
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=int(timeout),
        )
        out = (str(cp.stdout or "") + ("\n" + str(cp.stderr or "") if cp.stderr else "")).strip()
        return int(cp.returncode), (out or "-")
    except Exception as e:
        return 2, f"exception:{type(e).__name__}:{e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 8 operations gate (pre-op + monitoring + anchors).")
    ap.add_argument("--out", default="phase8_operations_report.json")
    ap.add_argument("--skip-runs", action="store_true", help="Only read existing reports.")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    logs: List[str] = []
    if not args.skip_runs:
        cmds = [
            [sys.executable, "tools/run_phase1_data_contract.py", "--timeout", "600"],
            [sys.executable, "tools/run_phase4b_marginal_tuning_gate.py", "--speed", "fast", "--max-cases", "14", "--write-params"],
            [sys.executable, "tools/run_phase6_series_bo_gate.py"],
            [sys.executable, "tools/run_phase7_layer_uncertainty_gate.py"],
            [sys.executable, "tools/anchor_regression_suite.py", "--mode", "app", "--out", "anchor_regression_report.json", "--timeout", "420"],
            [sys.executable, "tools/odds_delta_guardrail.py", "--mode", "app", "--out", "odd_delta_guardrail_report.json", "--timeout", "420"],
            [sys.executable, "tools/run_lacuna_guardrails.py", "--timeout", "600"],
        ]
        for cmd in cmds:
            rc, out = _run(cmd, timeout=args.timeout)
            logs.append(f"$ {' '.join(cmd)}\nrc={rc}\n{out}")

    p1 = _read_json(ROOT / "phase1_data_contract_report.json")
    p4b = _read_json(ROOT / "phase4b_marginal_tuning_report.json")
    p6 = _read_json(ROOT / "phase6_series_bo_report.json")
    p7 = _read_json(ROOT / "phase7_layer_uncertainty_report.json")
    lg = _read_json(ROOT / "lacuna_guardrail_report.json")
    ar = _read_json(ROOT / "anchor_regression_report.json")
    od = _read_json(ROOT / "odd_delta_guardrail_report.json")
    bt = _read_json(ROOT / "backtest_pipeline_abc_by_league_report.json")

    checks: List[Dict[str, Any]] = []

    d_p1 = _norm_dec(p1.get("decision"))
    checks.append({"check": "phase1_data_contract", "decision": d_p1, "ok": d_p1 == "promote"})

    d_p4b = _norm_dec(p4b.get("decision"))
    checks.append({"check": "phase4b_marginal_tuning", "decision": d_p4b, "ok": d_p4b == "promote"})

    d_p6 = _norm_dec(p6.get("decision"))
    checks.append({"check": "phase6_series_bo", "decision": d_p6, "ok": d_p6 == "promote"})

    d_p7 = _norm_dec(p7.get("decision"))
    checks.append({"check": "phase7_layer_uncertainty", "decision": d_p7, "ok": d_p7 == "promote"})

    d_lg = _norm_dec(lg.get("decision"))
    checks.append({"check": "lacuna_guardrail", "decision": d_lg, "ok": d_lg == "promote"})

    d_ar = _norm_dec(ar.get("decision"))
    _ar_sum = ar.get("summary") if isinstance(ar.get("summary"), dict) else {}
    _ar_fail = int(_ar_sum.get("fail") or 0)
    checks.append(
        {
            "check": "anchor_semantic_regression",
            "decision": d_ar,
            "ok": (d_ar == "promote" and _ar_fail == 0),
            "detail": {"fail": _ar_fail, "ok": int(_ar_sum.get("ok") or 0), "total": int(_ar_sum.get("total") or 0)},
        }
    )

    d_od = _norm_dec(od.get("decision"))
    _od_sum = od.get("summary") if isinstance(od.get("summary"), dict) else {}
    _od_fail = int(_od_sum.get("fail") or 0)
    _od_total = int(_od_sum.get("total") or 0)
    _od_allow = max(1, int(_od_total * 0.34)) if _od_total > 0 else 1
    _od_alert = bool(_od_total <= 0 or _od_fail > _od_allow)
    checks.append(
        {
            "check": "anchor_delta_regression",
            # Informative only: never blocks promotion decision.
            "decision": "promote",
            "ok": True,
            "non_blocking": True,
            "detail": {
                "observed_decision": d_od,
                "fail": _od_fail,
                "ok": int(_od_sum.get("ok") or 0),
                "total": _od_total,
                "allowed_fail": _od_allow,
                "alert": _od_alert,
            },
        }
    )

    _bt_mon = bt.get("monitoring") if isinstance(bt.get("monitoring"), dict) else {}
    _bt_gl = _bt_mon.get("global") if isinstance(_bt_mon.get("global"), dict) else {}
    _bands_node = _bt_gl.get("favorite_odd_bands_final")
    _bands_count = 0
    if isinstance(_bands_node, list):
        _bands_count = len(_bands_node)
    elif isinstance(_bands_node, dict):
        _bands_map = _bands_node.get("bands") if isinstance(_bands_node.get("bands"), dict) else {}
        _bands_count = len(_bands_map)
    _bands_ok = _bands_count >= 3
    checks.append(
        {
            "check": "monitoring_global_odd_bands",
            "decision": ("promote" if _bands_ok else "shadow_only"),
            "ok": _bands_ok,
            "detail": f"bands={_bands_count}",
        }
    )

    _by_lg = _bt_mon.get("by_league") if isinstance(_bt_mon.get("by_league"), dict) else {}
    _need = {"LCK", "LPL", "LEC", "CBLOL", "LCP"}
    _present = {str(k).strip().upper() for k in _by_lg.keys()}
    _have = sorted(list(_need & _present))
    _lg_cov_ok = len(_have) >= 4
    checks.append(
        {
            "check": "monitoring_by_league_coverage",
            "decision": ("promote" if _lg_cov_ok else "shadow_only"),
            "ok": _lg_cov_ok,
            "detail": {"required": sorted(list(_need)), "present": _have},
        }
    )

    part_decisions = [str(c.get("decision") or "unknown") for c in checks]
    final = max(part_decisions, key=_rank_dec) if part_decisions else "unknown"
    reasons = [str(c.get("check")) for c in checks if not bool(c.get("ok"))]

    rep = {
        "version": "phase8_operations_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": final,
        "reasons": reasons,
        "summary": {
            "ok": int(sum(1 for c in checks if bool(c.get("ok")))),
            "total": len(checks),
            "anchors_fail": int(_ar_fail),
            "anchors_delta_fail": int(_od_fail),
            "anchors_delta_alert": bool(_od_alert),
            "monitoring_bands": int(_bands_count),
            "monitoring_major_present": _have,
        },
        "checks": checks,
        "sources": {
            "phase1": "phase1_data_contract_report.json",
            "phase4b": "phase4b_marginal_tuning_report.json",
            "phase6": "phase6_series_bo_report.json",
            "phase7": "phase7_layer_uncertainty_report.json",
            "lacuna": "lacuna_guardrail_report.json",
            "anchors": "anchor_regression_report.json",
            "anchors_delta": "odd_delta_guardrail_report.json",
            "backtest": "backtest_pipeline_abc_by_league_report.json",
        },
        "run_log": "\n\n".join(logs),
    }

    out_path = ROOT / str(args.out)
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase8 operations gate -> {out_path.name} | "
        f"decision={final} | ok={rep['summary']['ok']}/{rep['summary']['total']}"
    )
    return 0 if final == "promote" else (1 if final == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
