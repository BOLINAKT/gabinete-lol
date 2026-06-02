from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.ml_monitoring_core import build_monitor_snapshot, update_monitor_history


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}
    return {}


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _norm_dec(v: Any) -> str:
    s = str(v or "").strip().lower()
    return s if s in {"promote", "shadow_only", "reject"} else "unknown"


def _rank(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2, "unknown": 1}.get(str(dec or ""), 1)


@dataclass
class Step:
    name: str
    cmd: List[str]
    report_path: Path | None = None
    report_decision_key: str = "decision"
    timeout: int = 1800


def _run_step(step: Step) -> Dict[str, Any]:
    started = _utc_now()
    try:
        cp = subprocess.run(
            step.cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=int(step.timeout),
        )
        rc = int(cp.returncode)
        out = str(cp.stdout or "")
        err = str(cp.stderr or "")
    except Exception as e:
        rc = 2
        out = ""
        err = f"exception:{type(e).__name__}:{e}"
    finished = _utc_now()

    rep_dec = "unknown"
    rep_payload: Dict[str, Any] = {}
    if step.report_path is not None:
        rep_payload = _read_json(step.report_path)
        if isinstance(rep_payload, dict):
            node: Any = rep_payload
            for k in str(step.report_decision_key or "decision").split("."):
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(k)
            rep_dec = _norm_dec(node)

    # rc semantics in these gates:
    # 0=promote, 1=shadow_only, 2=reject/error.
    # We rely primarily on report decision when available.
    status = "ok"
    if step.report_path is not None:
        # Gates may return rc=2 for decision=reject; this is a valid decision, not execution failure.
        if rep_dec == "unknown":
            status = "error"
    else:
        if rc >= 2:
            status = "error"

    return {
        "name": step.name,
        "cmd": step.cmd,
        "started_at": started,
        "finished_at": finished,
        "returncode": rc,
        "status": status,
        "report_path": (str(step.report_path) if step.report_path else ""),
        "decision": rep_dec,
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-4000:],
    }


def _anchor_report_status(path: Path) -> Dict[str, Any]:
    rep = _read_json(path)
    dec = _norm_dec(rep.get("decision") if isinstance(rep, dict) else "")
    sm = rep.get("summary") if isinstance(rep.get("summary"), dict) else {}
    fail = int(sm.get("fail") or 0)
    total = int(sm.get("total") or 0)
    ok = bool(dec == "promote" and fail == 0 and total > 0)
    return {"ok": ok, "decision": dec, "fail": fail, "total": total}


def main() -> int:
    ap = argparse.ArgumentParser(description="Production refresh: run all ML gates and promote baseline only on strict promote.")
    ap.add_argument("--mode", choices=["quick", "full"], default="quick", help="quick=skip extra reruns inside lacuna gate; full=run full lacuna internals.")
    ap.add_argument("--phase12-speed", choices=["fast", "full"], default="fast")
    ap.add_argument("--phase12-fit", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--promote-on-pass", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--auto-rollback-on-reject", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--tag-prefix", default="prod_refresh")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--out", default="prod_refresh_report.json")
    ap.add_argument("--run-monitoring", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--monitoring-days", type=int, default=7)
    ap.add_argument("--monitoring-history", default="ops/monitoring/ml_monitor_history.json")
    ap.add_argument("--monitoring-latest", default="ops/monitoring/ml_monitor_latest.json")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tag = f"{args.tag_prefix}_{ts}"

    steps: List[Step] = []
    steps.append(
        Step(
            name="phase1_data_contract",
            cmd=[sys.executable, "tools/run_phase1_data_contract.py", "--timeout", "600"],
            report_path=ROOT / "phase1_data_contract_report.json",
            timeout=min(1800, int(args.timeout)),
        )
    )

    cmd_p12 = [sys.executable, "tools/eval_roster_continuity_phase12.py", "--speed", str(args.phase12_speed)]
    if bool(args.phase12_fit):
        cmd_p12.extend(["--fit", "--write-params"])
    steps.append(
        Step(
            name="phase12_roster_continuity",
            cmd=cmd_p12,
            report_path=ROOT / "phase12_roster_continuity_report.json",
            timeout=min(3600, int(args.timeout)),
        )
    )

    steps.extend(
        [
            Step(
                name="phase2_areal_gate",
                cmd=[sys.executable, "tools/run_phase2_areal_gate.py"],
                report_path=ROOT / "phase2_areal_report.json",
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="phase2b_areal_tuning_gate",
                cmd=[sys.executable, "tools/run_phase2b_areal_tuning_gate.py", "--speed", "fast", "--write-params"],
                report_path=ROOT / "phase2b_areal_tuning_report.json",
                timeout=min(1800, int(args.timeout)),
            ),
            Step(
                name="phase3_breal_gate",
                cmd=[sys.executable, "tools/run_phase3_breal_gate.py"],
                report_path=ROOT / "phase3_breal_report.json",
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="phase4_ranksos_gate",
                cmd=[sys.executable, "tools/run_phase4_ranksos_gate.py"],
                report_path=ROOT / "phase4_ranksos_report.json",
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="phase4b_marginal_tuning_gate",
                cmd=[
                    sys.executable,
                    "tools/run_phase4b_marginal_tuning_gate.py",
                    "--speed",
                    "fast",
                    "--max-cases",
                    "14",
                    "--write-params",
                ],
                report_path=ROOT / "phase4b_marginal_tuning_report.json",
                timeout=min(1800, int(args.timeout)),
            ),
            Step(
                name="phase5_hier_calibration_gate",
                cmd=[sys.executable, "tools/run_phase5_hier_calibration_gate.py"],
                report_path=ROOT / "phase5_hier_calibration_report.json",
                timeout=min(2400, int(args.timeout)),
            ),
            Step(
                name="phase5_compare_hier_pre_post",
                cmd=[
                    sys.executable,
                    "tools/compare_hier_calibration_pre_post.py",
                    "--speed",
                    "fast",
                    "--max-rows",
                    "15000",
                    "--out",
                    "hier_calibration_pre_post_compare.json",
                ],
                report_path=None,
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="phase5b_hier_oos_paired_gate",
                cmd=[
                    sys.executable,
                    "tools/run_phase5b_hier_oos_paired_gate.py",
                    "--compare",
                    "hier_calibration_pre_post_compare.json",
                    "--baseline",
                    "ml_confidence_baseline.json",
                    "--out",
                    "phase5b_hier_oos_paired_report.json",
                ],
                report_path=ROOT / "phase5b_hier_oos_paired_report.json",
                timeout=min(1800, int(args.timeout)),
            ),
            Step(
                name="phase5_compare_hier_interleague_pre_post",
                cmd=[
                    sys.executable,
                    "tools/compare_hier_calibration_interleague.py",
                    "--speed",
                    "fast",
                    "--out",
                    "hier_calibration_interleague_pre_post_compare.json",
                ],
                report_path=None,
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="phase5c_hier_interleague_gate",
                cmd=[
                    sys.executable,
                    "tools/run_phase5c_hier_interleague_gate.py",
                    "--compare",
                    "hier_calibration_interleague_pre_post_compare.json",
                    "--baseline",
                    "ml_confidence_baseline.json",
                    "--out",
                    "phase5c_hier_interleague_report.json",
                ],
                report_path=ROOT / "phase5c_hier_interleague_report.json",
                timeout=min(1800, int(args.timeout)),
            ),
            Step(
                name="phase5_compare_hier_sameleague_pre_post",
                cmd=[
                    sys.executable,
                    "tools/compare_hier_calibration_sameleague.py",
                    "--speed",
                    "fast",
                    "--out",
                    "hier_calibration_sameleague_pre_post_compare.json",
                ],
                report_path=None,
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="phase5d_hier_sameleague_gate",
                cmd=[
                    sys.executable,
                    "tools/run_phase5d_hier_sameleague_gate.py",
                    "--compare",
                    "hier_calibration_sameleague_pre_post_compare.json",
                    "--baseline",
                    "ml_confidence_baseline.json",
                    "--out",
                    "phase5d_hier_sameleague_report.json",
                ],
                report_path=ROOT / "phase5d_hier_sameleague_report.json",
                timeout=min(1800, int(args.timeout)),
            ),
            Step(
                name="phase6_series_bo_gate",
                cmd=[sys.executable, "tools/run_phase6_series_bo_gate.py"],
                report_path=ROOT / "phase6_series_bo_report.json",
                timeout=min(2400, int(args.timeout)),
            ),
            Step(
                name="phase7_layer_uncertainty_gate",
                cmd=[sys.executable, "tools/run_phase7_layer_uncertainty_gate.py"],
                report_path=ROOT / "phase7_layer_uncertainty_report.json",
                timeout=min(2400, int(args.timeout)),
            ),
            Step(
                name="phase9_players_gate",
                cmd=[sys.executable, "tools/run_phase9_players_gate.py"],
                report_path=ROOT / "phase9_players_report.json",
                timeout=min(3600, int(args.timeout)),
            ),
            Step(
                name="anchor_regression_pre_promotion",
                cmd=[
                    sys.executable,
                    "tools/anchor_regression_suite.py",
                    "--mode",
                    "app",
                    "--out",
                    "anchor_regression_report.json",
                    "--timeout",
                    "420",
                ],
                report_path=ROOT / "anchor_regression_report.json",
                timeout=min(2400, int(args.timeout)),
            ),
            Step(
                name="lacuna_guardrail_strict",
                cmd=(
                    [sys.executable, "tools/run_lacuna_guardrails.py", "--strict-phase-coverage", "--skip-runs"]
                    if str(args.mode) == "quick"
                    else [sys.executable, "tools/run_lacuna_guardrails.py", "--strict-phase-coverage"]
                ),
                report_path=ROOT / "lacuna_guardrail_report.json",
                timeout=min(2400, int(args.timeout)),
            ),
            Step(
                name="phase8_operations_gate",
                cmd=[sys.executable, "tools/run_phase8_operations_gate.py", "--skip-runs"],
                report_path=ROOT / "phase8_operations_report.json",
                timeout=min(1200, int(args.timeout)),
            ),
        ]
    )

    run_results: List[Dict[str, Any]] = []
    for st in steps:
        rr = _run_step(st)
        run_results.append(rr)
        if rr.get("status") == "error":
            break

    final_dec = "unknown"
    lac = _read_json(ROOT / "lacuna_guardrail_report.json")
    if isinstance(lac, dict):
        final_dec = _norm_dec(lac.get("decision"))
    # Always respect the worst gate decision among executed steps.
    step_decs = [
        str(x.get("decision") or "").strip().lower()
        for x in run_results
        if str(x.get("decision") or "").strip().lower() in {"promote", "shadow_only", "reject"}
    ]
    if step_decs:
        worst_step_dec = max(step_decs, key=_rank)
        if final_dec == "unknown":
            final_dec = worst_step_dec
        elif _rank(worst_step_dec) > _rank(final_dec):
            final_dec = worst_step_dec

    action = "none"
    action_detail: Dict[str, Any] = {}
    actions: List[Dict[str, Any]] = []
    action_ok = True
    if bool(args.promote_on_pass) and final_dec == "promote":
        cp = subprocess.run(
            [sys.executable, "tools/promote_baseline.py", "--tag", tag],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
        )
        action = "promote_baseline"
        action_detail = {
            "returncode": int(cp.returncode),
            "stdout_tail": str(cp.stdout or "")[-3000:],
            "stderr_tail": str(cp.stderr or "")[-3000:],
            "tag": tag,
        }
        actions.append({"name": "promote_baseline", **action_detail})
        action_ok = int(cp.returncode) == 0
        if not action_ok:
            # Promotion gate failed; cannot keep final decision as promote.
            final_dec = "reject"
        else:
            cp_anchor = subprocess.run(
                [
                    sys.executable,
                    "tools/anchor_regression_suite.py",
                    "--mode",
                    "app",
                    "--out",
                    "anchor_regression_report.post_promotion.json",
                    "--timeout",
                    "420",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_subprocess_env(),
            )
            anchor_post = _anchor_report_status(ROOT / "anchor_regression_report.post_promotion.json")
            anchor_step = {
                "name": "anchor_regression_post_promotion",
                "returncode": int(cp_anchor.returncode),
                "stdout_tail": str(cp_anchor.stdout or "")[-3000:],
                "stderr_tail": str(cp_anchor.stderr or "")[-3000:],
                "report": anchor_post,
            }
            actions.append(anchor_step)
            if int(cp_anchor.returncode) != 0 or not bool(anchor_post.get("ok")):
                # Promotion succeeded but semantic anchors regressed in final app pipeline.
                final_dec = "reject"
                action_ok = False
                action = "promote_baseline+anchor_post_failed"
                action_detail = anchor_step
    elif bool(args.auto_rollback_on_reject) and final_dec == "reject":
        cp = subprocess.run(
            [sys.executable, "tools/rollback_baseline.py"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
        )
        action = "rollback_baseline"
        action_detail = {
            "returncode": int(cp.returncode),
            "stdout_tail": str(cp.stdout or "")[-3000:],
            "stderr_tail": str(cp.stderr or "")[-3000:],
        }
        actions.append({"name": "rollback_baseline", **action_detail})
        action_ok = int(cp.returncode) == 0

    if bool(args.auto_rollback_on_reject) and final_dec == "reject":
        has_rollback = any(str(a.get("name")) == "rollback_baseline" for a in actions)
        if not has_rollback:
            cp = subprocess.run(
                [sys.executable, "tools/rollback_baseline.py"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_subprocess_env(),
            )
            rb_detail = {
                "name": "rollback_baseline",
                "returncode": int(cp.returncode),
                "stdout_tail": str(cp.stdout or "")[-3000:],
                "stderr_tail": str(cp.stderr or "")[-3000:],
            }
            actions.append(rb_detail)
            action_ok = action_ok and (int(cp.returncode) == 0)
            if int(cp.returncode) == 0:
                action = "rollback_baseline"
                action_detail = dict(rb_detail)

    rep = {
        "version": "prod_refresh_v1",
        "generated_at": _utc_now(),
        "mode": str(args.mode),
        "phase12_speed": str(args.phase12_speed),
        "phase12_fit": bool(args.phase12_fit),
        "promote_on_pass": bool(args.promote_on_pass),
        "auto_rollback_on_reject": bool(args.auto_rollback_on_reject),
        "steps": run_results,
        "final_decision": final_dec,
        "action": action,
        "action_ok": bool(action_ok),
        "action_detail": action_detail,
        "actions": actions,
        "anchor_pre": _anchor_report_status(ROOT / "anchor_regression_report.json"),
        "anchor_post": _anchor_report_status(ROOT / "anchor_regression_report.post_promotion.json"),
    }
    out_path = ROOT / str(args.out)
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.run_monitoring):
        latest_path = (ROOT / str(args.monitoring_latest)).resolve()
        history_path = (ROOT / str(args.monitoring_history)).resolve()
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.parent.mkdir(parents=True, exist_ok=True)

        snapshot = build_monitor_snapshot(ROOT)
        snapshot["source"] = "prod_refresh"
        snapshot["prod_refresh_report_path"] = str(out_path.resolve())

        history_in = _read_json(history_path)
        history_out = update_monitor_history(
            history_in,
            snapshot,
            days=int(args.monitoring_days),
            keep_entries=120,
        )
        latest_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        history_path.write_text(json.dumps(history_out, ensure_ascii=False, indent=2), encoding="utf-8")

        rep["monitoring"] = {
            "latest_path": str(latest_path),
            "history_path": str(history_path),
            "latest_overall_ok": bool(((snapshot.get("health") or {}).get("overall_ok"))),
            "window_entries": int(((history_out.get("summary") or {}).get("entries")) or 0),
        }
        out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = final_dec == "promote"
    print(
        f"OK: prod refresh -> {out_path.name} | decision={final_dec} | "
        f"steps={len(run_results)}/{len(steps)} | action={action}"
    )
    return 0 if ok else (1 if final_dec == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
