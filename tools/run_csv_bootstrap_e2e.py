from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # AppTest executa no processo atual; garantir ROOT evita ModuleNotFoundError (mlcore).
    sys.path.insert(0, str(ROOT))

from app_core.streamlit_apptest_core import (
    quiet_streamlit_bare_mode_warnings as core_quiet_streamlit_bare_mode_warnings,
    new_apptest_for_file as core_new_apptest_for_file,
    run_apptest_quiet as core_run_apptest_quiet,
)

_BENIGN_STREAMLIT_WARNINGS = ("missing ScriptRunContext! This warning can be ignored when running in bare mode.",)


def _quiet_streamlit_logs() -> None:
    core_quiet_streamlit_bare_mode_warnings(disable_global_logging=True)


def _new_apptest():
    return core_new_apptest_for_file(ROOT / "plays_app.py")


def _run_apptest_quiet(at: Any, timeout: int) -> None:
    core_run_apptest_quiet(at, max(120, int(timeout)))


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


def _run_cmd(cmd: List[str], timeout: int = 900) -> Tuple[int, str]:
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=max(30, int(timeout)),
        )
        out_raw = (str(cp.stdout or "") + ("\n" + str(cp.stderr or "") if cp.stderr else "")).strip()
        out_lines: List[str] = []
        for line in str(out_raw or "").splitlines():
            line_s = str(line or "").strip()
            if not line_s:
                continue
            if any(pat in line_s for pat in _BENIGN_STREAMLIT_WARNINGS):
                continue
            out_lines.append(line)
        out = "\n".join(out_lines).strip()
        return int(cp.returncode), (out or "-")
    except Exception as exc:
        return 2, f"exception:{type(exc).__name__}:{exc}"


def _seed_fast_probe_session(at: Any) -> None:
    """Configura sessão para probes rápidos e determinísticos de bootstrap."""
    try:
        at.session_state["_probe_skip_csv_bootstrap_gate"] = False
        at.session_state["auto_maint_fast_mode"] = True
        at.session_state["auto_maint_run_layer_validation"] = False
        at.session_state["auto_maint_cmd_timeout_s"] = 45
        at.session_state["auto_maint_fast_new_games_max"] = 30
        at.session_state["auto_maint_force_fast"] = True
        at.session_state["auto_maint_force_full"] = False
        at.session_state["auto_maint_lock_poll_max"] = 0
        at.session_state["auto_maint_lock_poll_sleep_s"] = 0.2
        # Evita WF/LV pesados no probe quando não há pendência real.
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        at.session_state["wf_last_report_at"] = now_iso
        at.session_state["lv_last_report_at"] = now_iso
    except Exception:
        pass


def _probe_force_bootstrap_maintenance(timeout: int) -> Dict[str, Any]:
    _quiet_streamlit_logs()
    try:
        pass  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"streamlit.testing.v1 indisponivel: {exc}"}

    at = _new_apptest()
    _seed_fast_probe_session(at)
    at.session_state["_csv_bootstrap_done_fp"] = ""
    at.session_state["_csv_bootstrap_hold_screen"] = True
    at.session_state["_csv_bootstrap_force_once"] = True
    # Keep probe lightweight: this check validates bootstrap UI stability
    # and report generation, not heavy maintenance runtime.
    at.session_state["_csv_bootstrap_force_maint"] = False
    try:
        _run_apptest_quiet(at, timeout=int(timeout))
    except Exception as e:
        return {"ok": False, "error": f"bootstrap_timeout_or_error:{type(e).__name__}:{e}"}
    excs = [str(e) for e in list(getattr(at, "exception", []))]
    return {
        "ok": len(excs) == 0,
        "exceptions": excs[:5],
    }


def _probe_lock_warning(timeout: int) -> Dict[str, Any]:
    _quiet_streamlit_logs()
    try:
        pass  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"streamlit.testing.v1 indisponivel: {exc}"}

    lock_path = ROOT / "csv_bootstrap_maintenance.lock.json"
    payload = {
        "fp_key": "__probe_other_fp__",
        "pid": 999999,
        "ts": float(time.time()),
        "acquired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        at = _new_apptest()
        _seed_fast_probe_session(at)
        at.session_state["_csv_bootstrap_done_fp"] = ""
        at.session_state["_csv_bootstrap_hold_screen"] = True
        at.session_state["_csv_bootstrap_force_once"] = True
        at.session_state["_csv_bootstrap_force_maint"] = True
        _run_apptest_quiet(at, timeout=int(timeout))
        excs = [str(e) for e in list(getattr(at, "exception", []))]
        warns = [str(getattr(w, "value", "") or "") for w in list(getattr(at, "warning", []))]
        found = any("Manutenção automática já está em execução em outra sessão/processo" in w for w in warns)
        return {
            "ok": (len(excs) == 0) and bool(found),
            "exceptions": excs[:5],
            "warning_found": bool(found),
            "warnings_count": len(warns),
        }
    finally:
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass


def _probe_no_go_blocks_enter(timeout: int) -> Dict[str, Any]:
    _quiet_streamlit_logs()
    try:
        pass  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"streamlit.testing.v1 indisponivel: {exc}"}

    # Usa override inválido apenas no teste para forçar estado crítico (NO-GO).
    daily_dir = ROOT / "CSV_DIARIO"
    csv_candidates = sorted([p for p in daily_dir.glob("*.csv") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not csv_candidates:
        return {"ok": False, "error": "sem_csv_diario"}
    csv_path = str(csv_candidates[0].resolve())

    lock_path = ROOT / "csv_bootstrap_maintenance.lock.json"
    payload = {
        "fp_key": "__probe_other_fp_no_go__",
        "pid": 999999,
        "ts": float(time.time()),
        "acquired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        at = _new_apptest()
        _seed_fast_probe_session(at)
        at.session_state["cfg_auto_paths"] = False
        at.session_state["cfg_csv_override"] = csv_path
        at.session_state["cfg_artifact_override"] = "Z:/__gabinete_probe__/ml_artifact.json"
        at.session_state["_csv_bootstrap_done_fp"] = ""
        at.session_state["_csv_bootstrap_hold_screen"] = True
        at.session_state["_csv_bootstrap_force_once"] = True
        at.session_state["_csv_bootstrap_force_maint"] = True
        at.session_state["auto_maint_cmd_timeout_s"] = 30
        try:
            _run_apptest_quiet(at, timeout=int(timeout))
        except Exception as e:
            return {
                "ok": False,
                "error": f"no_go_probe_timeout_or_error:{type(e).__name__}:{e}",
                "button_found": False,
                "button_disabled": None,
                "decision": "",
            }

        excs = [str(e) for e in list(getattr(at, "exception", []))]
        btn = next((b for b in at.button if str(getattr(b, "key", "")) == "csv_bootstrap_continue"), None)
        disabled = (None if btn is None else bool(getattr(btn, "disabled", False)))
        rep = _read_json(ROOT / "csv_bootstrap_last_report.json")
        go_no_go = rep.get("go_no_go") if isinstance(rep.get("go_no_go"), dict) else {}
        decision = str(go_no_go.get("decision", "") or "")

        return {
            "ok": (len(excs) == 0) and (btn is not None) and bool(disabled) and (decision == "NO-GO"),
            "exceptions": excs[:5],
            "button_found": bool(btn is not None),
            "button_disabled": disabled,
            "decision": decision,
        }
    finally:
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass


def _restore_normal_bootstrap_state(timeout: int) -> Dict[str, Any]:
    _quiet_streamlit_logs()
    try:
        pass  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"streamlit.testing.v1 indisponivel: {exc}"}

    at = _new_apptest()
    _seed_fast_probe_session(at)
    at.session_state["cfg_auto_paths"] = True
    at.session_state["_csv_bootstrap_done_fp"] = ""
    at.session_state["_csv_bootstrap_hold_screen"] = True
    at.session_state["_csv_bootstrap_force_once"] = True
    _run_apptest_quiet(at, timeout=int(timeout))
    excs = [str(e) for e in list(getattr(at, "exception", []))]
    rep = _read_json(ROOT / "csv_bootstrap_last_report.json")
    go_no_go = rep.get("go_no_go") if isinstance(rep.get("go_no_go"), dict) else {}
    return {
        "ok": len(excs) == 0,
        "exceptions": excs[:5],
        "go_no_go": go_no_go,
    }


def _validate_reports() -> Dict[str, Any]:
    rep_last = _read_json(ROOT / "csv_bootstrap_last_report.json")
    rep_maint = _read_json(ROOT / "csv_bootstrap_maintenance_report.json")
    auto = rep_maint.get("auto_report") if isinstance(rep_maint.get("auto_report"), dict) else {}
    go_no_go = rep_last.get("go_no_go") if isinstance(rep_last.get("go_no_go"), dict) else {}
    status_after = rep_last.get("maintenance_status_after") if isinstance(rep_last.get("maintenance_status_after"), dict) else {}

    checks = {
        "has_go_no_go": bool(go_no_go),
        "has_status_after": bool(status_after),
        "has_policy_profile": bool(str(auto.get("policy_profile", "")).strip()),
        "has_policy_reason": bool(str(auto.get("policy_reason", "")).strip()),
        "has_steps": isinstance(auto.get("steps"), list) and len(auto.get("steps") or []) > 0,
        "has_policy_step": any(
            isinstance(s, dict) and str(s.get("step", "")) == "policy_fast_full"
            for s in (auto.get("steps") or [])
        ),
    }
    return {
        "ok": all(bool(v) for v in checks.values()),
        "checks": checks,
        "go_no_go": go_no_go,
        "status_after": status_after,
        "policy_profile": auto.get("policy_profile"),
        "policy_reason": auto.get("policy_reason"),
    }


def _decision_from_checks(checks: List[Dict[str, Any]]) -> str:
    if not checks:
        return "reject"
    if all(bool(c.get("ok")) for c in checks):
        return "promote"
    return "reject"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CSV bootstrap E2E gate (UI + maintenance + GO/NO-GO + lock).")
    ap.add_argument("--out", default="csv_bootstrap_e2e_report.json")
    ap.add_argument("--timeout", type=int, default=300, help="Timeout (s) for each AppTest run.")
    ap.add_argument("--skip-heavy", action="store_true", help="Skip unittest suite and run only probes/reports.")
    args = ap.parse_args(argv)

    os.chdir(ROOT)
    logs: List[str] = []
    checks: List[Dict[str, Any]] = []

    rc, out = _run_cmd([sys.executable, "-m", "py_compile", "plays_app.py"], timeout=120)
    logs.append(f"$ python -m py_compile plays_app.py\nrc={rc}\n{out}")
    checks.append({"check": "py_compile", "ok": rc == 0, "detail": f"rc={rc}"})

    rc, out = _run_cmd([sys.executable, "tools/ui_break_probe.py", "--timeout", str(int(args.timeout))], timeout=max(300, int(args.timeout) * 3))
    logs.append(f"$ python tools/ui_break_probe.py --timeout {int(args.timeout)}\nrc={rc}\n{out}")
    checks.append({"check": "ui_break_probe", "ok": rc == 0, "detail": f"rc={rc}"})

    if not bool(args.skip_heavy):
        for mod in [
            "mlcore.tests.test_ui_smoke",
            "mlcore.tests.test_e2e_smoke_flow",
            "mlcore.tests.test_state_team_artifact",
        ]:
            rc, out = _run_cmd([sys.executable, "-m", "unittest", mod, "-v"], timeout=max(300, int(args.timeout) * 3))
            logs.append(f"$ python -m unittest {mod} -v\nrc={rc}\n{out}")
            checks.append({"check": f"unittest:{mod}", "ok": rc == 0, "detail": f"rc={rc}"})

    p_force = _probe_force_bootstrap_maintenance(timeout=int(args.timeout))
    checks.append({"check": "probe_force_bootstrap_maintenance", "ok": bool(p_force.get("ok")), "detail": p_force})

    rep_check = _validate_reports()
    checks.append({"check": "validate_reports", "ok": bool(rep_check.get("ok")), "detail": rep_check})

    p_lock = _probe_lock_warning(timeout=int(args.timeout))
    checks.append({"check": "probe_lock_warning", "ok": bool(p_lock.get("ok")), "detail": p_lock})

    p_nogo = _probe_no_go_blocks_enter(timeout=int(args.timeout))
    checks.append({"check": "probe_no_go_blocks_enter", "ok": bool(p_nogo.get("ok")), "detail": p_nogo})

    p_restore = _restore_normal_bootstrap_state(timeout=int(args.timeout))
    checks.append({"check": "restore_normal_bootstrap_state", "ok": bool(p_restore.get("ok")), "detail": p_restore})

    final = _decision_from_checks(checks)
    reasons = [str(c.get("check")) for c in checks if not bool(c.get("ok"))]

    rep: Dict[str, Any] = {
        "version": "csv_bootstrap_e2e_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": final,
        "summary": {
            "ok": int(sum(1 for c in checks if bool(c.get("ok")))),
            "total": len(checks),
            "fail": int(sum(1 for c in checks if not bool(c.get("ok")))),
        },
        "reasons": reasons,
        "checks": checks,
        "artifacts": {
            "csv_bootstrap_last_report": str((ROOT / "csv_bootstrap_last_report.json").resolve()),
            "csv_bootstrap_maintenance_report": str((ROOT / "csv_bootstrap_maintenance_report.json").resolve()),
        },
        "run_log": "\n\n".join(logs),
    }

    out_path = ROOT / str(args.out)
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"OK: csv bootstrap e2e gate -> {out_path.name} | "
        f"decision={final} | ok={rep['summary']['ok']}/{rep['summary']['total']}"
    )
    return 0 if final == "promote" else 2


if __name__ == "__main__":
    raise SystemExit(main())

