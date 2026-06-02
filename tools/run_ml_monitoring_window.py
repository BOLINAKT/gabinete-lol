from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.ml_monitoring_core import build_monitor_snapshot, update_monitor_history


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_subprocess(cmd: list[str], *, timeout: int) -> Dict[str, Any]:
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
            timeout=int(timeout),
        )
        return {
            "ok": int(cp.returncode) == 0,
            "returncode": int(cp.returncode),
            "stdout_tail": str(cp.stdout or "")[-4000:],
            "stderr_tail": str(cp.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Append operational ML monitoring snapshot and rolling 7-day summary.")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--history", default="ops/monitoring/ml_monitor_history.json")
    ap.add_argument("--latest", default="ops/monitoring/ml_monitor_latest.json")
    ap.add_argument("--keep-entries", type=int, default=120)
    ap.add_argument("--run-regression", action="store_true")
    ap.add_argument("--run-anchor", action="store_true")
    ap.add_argument("--anchor-timeout", type=int, default=420)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    history_path = (ROOT / str(args.history)).resolve()
    latest_path = (ROOT / str(args.latest)).resolve()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.parent.mkdir(parents=True, exist_ok=True)

    prechecks: Dict[str, Any] = {}
    if bool(args.run_regression):
        prechecks["check_regression"] = _run_subprocess(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", "tools/check_regression.ps1"],
            timeout=int(args.timeout),
        )
    if bool(args.run_anchor):
        prechecks["anchor_regression"] = _run_subprocess(
            [
                sys.executable,
                "tools/anchor_regression_suite.py",
                "--mode",
                "app",
                "--out",
                "anchor_regression_report.monitoring.json",
                "--timeout",
                str(int(args.anchor_timeout)),
            ],
            timeout=max(int(args.timeout), int(args.anchor_timeout) + 120),
        )

    snapshot = build_monitor_snapshot(ROOT)
    if prechecks:
        snapshot["prechecks"] = prechecks
        blockers = list(((snapshot.get("health") or {}).get("blockers") or []))
        for name, row in prechecks.items():
            if not bool((row or {}).get("ok", False)):
                blockers.append(f"precheck:{name}=failed")
        snapshot["health"] = {
            "overall_ok": bool(not blockers),
            "blockers": blockers,
        }

    history_obj = _read_json(history_path)
    history_out = update_monitor_history(
        history_obj,
        snapshot,
        days=int(args.days),
        keep_entries=int(args.keep_entries),
    )

    latest_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    history_path.write_text(json.dumps(history_out, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = history_out.get("summary") if isinstance(history_out.get("summary"), dict) else {}
    print(
        "OK: ml monitoring snapshot -> "
        f"latest={latest_path.name} | history={history_path.name} | "
        f"healthy={int(summary.get('healthy_entries') or 0)}/{int(summary.get('entries') or 0)} | "
        f"streak={int(summary.get('consecutive_healthy_streak') or 0)}"
    )
    return 0 if bool(((snapshot.get("health") or {}).get("overall_ok"))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
