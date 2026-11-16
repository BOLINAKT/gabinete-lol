from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCANNER_TARGETS: list[str] = [
    "plays_app.py",
    "app_core",
    "mlcore",
    "tools",
]

QUICK_COMPILE_TARGETS: list[str] = [
    "plays_app.py",
    "tools/find_code_errors.py",
    "app_core/consistency_core.py",
    "app_core/consistency_ui_core.py",
    "app_core/maintenance_policy_core.py",
    "app_core/maintenance_runtime_core.py",
    "app_core/maintenance_status_core.py",
    "app_core/pre_delivery_checks_core.py",
    "app_core/quick_selector_ui_core.py",
    "tools/check_streamlit_key_index_defaults.py",
    "tools/check_streamlit_key_value_defaults.py",
    "tools/run_csv_bootstrap_e2e.py",
    "tools/ui_break_probe.py",
]

QUICK_UNITTEST_MODULES: list[str] = [
    "mlcore.tests.test_bootstrap_maintenance_state_core",
    "mlcore.tests.test_consistency_core",
    "mlcore.tests.test_csv_bootstrap_runtime_core",
    "mlcore.tests.test_daily_pipeline_runtime_core",
    "mlcore.tests.test_find_code_errors",
    "mlcore.tests.test_fit_ml_params",
    "mlcore.tests.test_maintenance_policy_core",
    "mlcore.tests.test_maintenance_runtime_core",
    "mlcore.tests.test_maintenance_status_core",
    "mlcore.tests.test_pre_delivery_checks_core",
    "mlcore.tests.test_pre_delivery_runtime_core",
    "mlcore.tests.test_quick_maintenance_ui_core",
    "mlcore.tests.test_quick_selector_ui_core",
    "mlcore.tests.test_run_stabilization_gate",
    "mlcore.tests.test_walkforward_report",
]

FULL_EXTRA_UNITTEST_MODULES: list[str] = [
    "mlcore.tests.test_e2e_smoke_flow",
    "mlcore.tests.test_state_team_artifact",
    "mlcore.tests.test_ui_smoke",
]


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    root_s = str(ROOT)
    cur_pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
    if cur_pythonpath:
        if root_s not in cur_pythonpath.split(os.pathsep):
            env["PYTHONPATH"] = root_s + os.pathsep + cur_pythonpath
    else:
        env["PYTHONPATH"] = root_s
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_cmd(
    cmd: Sequence[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> Dict[str, Any]:
    try:
        cp = subprocess.run(
            [str(x) for x in cmd],
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30, int(timeout)),
            env=_subprocess_env(),
        )
        output = ((cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")).strip()
        return {
            "ok": int(cp.returncode) == 0,
            "returncode": int(cp.returncode),
            "output": output,
            "cmd": [str(x) for x in cmd],
        }
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else "")).strip()
        return {
            "ok": False,
            "returncode": 124,
            "output": output,
            "cmd": [str(x) for x in cmd],
            "error": f"timeout>{int(timeout)}s",
        }
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "returncode": None,
            "output": "",
            "cmd": [str(x) for x in cmd],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _run_check(
    checks: list[Dict[str, Any]],
    *,
    name: str,
    cmd: Sequence[str],
    timeout: int,
    cwd: Path | None = None,
) -> Dict[str, Any]:
    res = _run_cmd(cmd, timeout=timeout, cwd=cwd)
    row = {
        "check": str(name),
        "ok": bool(res.get("ok")),
        "returncode": res.get("returncode"),
        "cmd": list(res.get("cmd") or []),
        "error": str(res.get("error") or ""),
        "output_tail": str(res.get("output") or "")[-6000:],
    }
    checks.append(row)
    status = "OK" if row["ok"] else "FAIL"
    print(f"[{status}] {name}")
    return row


def _default_out_path(profile: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "evidence" / f"stabilization_gate_{profile}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "report.json"


def _report_summary(checks: list[Dict[str, Any]]) -> Dict[str, int]:
    ok_n = int(sum(1 for row in checks if bool(row.get("ok"))))
    total = len(checks)
    return {
        "ok": ok_n,
        "fail": int(total - ok_n),
        "total": total,
    }


def _scanner_cmd(profile: str) -> list[str]:
    cmd = [sys.executable, "tools/find_code_errors.py", "--profile", str(profile)]
    for target in SCANNER_TARGETS:
        cmd.extend(["--path", str(target)])
    return cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the curated stabilization gate for the most fragile app flows.")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--timeout", type=int, default=180, help="Base timeout in seconds for UI/bootstrap probes.")
    ap.add_argument("--out", default="", help="Optional JSON report path.")
    args = ap.parse_args(argv)

    os.chdir(ROOT)
    profile = str(args.profile)
    base_timeout = max(60, int(args.timeout or 180))
    out_path = Path(str(args.out)).expanduser() if str(args.out or "").strip() else _default_out_path(profile)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    checks: list[Dict[str, Any]] = []
    ui_probe_timeout = min(60, base_timeout) if profile == "quick" else base_timeout
    ui_probe_budget = max(600, ui_probe_timeout * 10) if profile == "quick" else max(300, base_timeout * 4)

    _run_check(
        checks,
        name="py_compile:critical_targets",
        cmd=[sys.executable, "-m", "py_compile", *QUICK_COMPILE_TARGETS],
        timeout=180,
    )
    _run_check(
        checks,
        name="streamlit_key_value_defaults_guard",
        cmd=[sys.executable, "tools/check_streamlit_key_value_defaults.py"],
        timeout=120,
    )
    _run_check(
        checks,
        name="streamlit_key_index_defaults_guard",
        cmd=[sys.executable, "tools/check_streamlit_key_index_defaults.py"],
        timeout=120,
    )
    _run_check(
        checks,
        name=f"code_error_scan:{profile}",
        cmd=_scanner_cmd(profile),
        timeout=max(180, base_timeout * 4),
    )
    _run_check(
        checks,
        name="unittest:critical_core",
        cmd=[sys.executable, "-m", "unittest", *QUICK_UNITTEST_MODULES],
        timeout=max(300, base_timeout * 4),
    )
    _run_check(
        checks,
        name="ui_break_probe",
        cmd=[sys.executable, "tools/ui_break_probe.py", "--timeout", str(ui_probe_timeout)],
        timeout=ui_probe_budget,
    )

    if profile == "full":
        _run_check(
            checks,
            name="csv_bootstrap_e2e:full",
            cmd=[sys.executable, "tools/run_csv_bootstrap_e2e.py", "--timeout", str(base_timeout)],
            timeout=max(300, base_timeout * 5),
        )
        _run_check(
            checks,
            name="unittest:ui_and_state_full",
            cmd=[sys.executable, "-m", "unittest", *FULL_EXTRA_UNITTEST_MODULES],
            timeout=max(300, base_timeout * 5),
        )

    summary = _report_summary(checks)
    report = {
        "version": "stabilization_gate_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile,
        "timeout_s": int(base_timeout),
        "summary": summary,
        "decision": ("pass" if summary["fail"] == 0 else "fail"),
        "failed_checks": [str(row.get("check")) for row in checks if not bool(row.get("ok"))],
        "checks": checks,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"stabilization_gate profile={profile} decision={report['decision']} "
        f"ok={summary['ok']}/{summary['total']} out={out_path}"
    )
    return 0 if summary["fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
