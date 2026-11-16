from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _run(cmd: List[str], *, timeout: int) -> Dict[str, Any]:
    started = _utc_now()
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=int(timeout),
        )
        rc = int(cp.returncode)
        out = str(cp.stdout or "")
        err = str(cp.stderr or "")
    except Exception as exc:
        rc = 2
        out = ""
        err = f"{type(exc).__name__}: {exc}"
    finished = _utc_now()
    return {
        "cmd": list(cmd),
        "started_at": started,
        "finished_at": finished,
        "returncode": rc,
        "ok": bool(rc == 0),
        "stdout_tail": out[-4000:],
        "stderr_tail": err[-4000:],
    }


def _write_report(path: Path, payload: Dict[str, Any], aliases: List[Path] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for alias in list(aliases or []):
        try:
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _parse_iso_to_epoch(text: Any) -> float | None:
    try:
        s = str(text or "").strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return float(datetime.fromisoformat(s).timestamp())
    except Exception:
        return None


def _path_mtime(path: Path) -> float | None:
    try:
        if path.exists():
            return float(path.stat().st_mtime)
    except Exception:
        return None
    return None


def _latest_tree_mtime(path: Path) -> float | None:
    try:
        if not path.exists():
            return None
        if path.is_file():
            return _path_mtime(path)
        latest = 0.0
        found = False
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    latest = max(latest, float(p.stat().st_mtime))
                    found = True
            except Exception:
                pass
        return latest if found else None
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _read_process_cpu_seconds(pid: int) -> float | None:
    if int(pid or 0) <= 0:
        return None
    try:
        if os.name == "nt":
            cp = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; if ($p) {{ [Console]::Write($p.CPU) }}",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=5,
            )
            out = str(cp.stdout or "").strip()
            if not out:
                return None
            return float(out.replace(",", "."))
        cp = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "etimes="],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = str(cp.stdout or "").strip()
        if not out:
            return None
        return float(out)
    except Exception:
        return None


def _sha256_file(path: Path) -> str | None:
    try:
        if not path.exists():
            return None
        import hashlib

        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _detect_live_input_drift(source_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    inputs = source_manifest.get("inputs") if isinstance(source_manifest.get("inputs"), dict) else {}
    issues: List[Dict[str, Any]] = []

    def _check_item(item: Dict[str, Any], role: str) -> None:
        if not isinstance(item, dict):
            return
        source_path = Path(str(item.get("source_path") or "")).expanduser()
        expected_sha = str(item.get("sha256") or "").strip().lower()
        observed_sha = _sha256_file(source_path)
        if not expected_sha:
            return
        if observed_sha != expected_sha:
            issues.append(
                {
                    "role": role,
                    "source_path": str(source_path),
                    "expected_sha256": expected_sha,
                    "observed_sha256": observed_sha,
                }
            )

    _check_item(inputs.get("artifact") if isinstance(inputs.get("artifact"), dict) else {}, "artifact")
    _check_item(inputs.get("players_artifact") if isinstance(inputs.get("players_artifact"), dict) else {}, "players_artifact")
    for idx, item in enumerate(list(inputs.get("csvs") or []), 1):
        _check_item(item if isinstance(item, dict) else {}, f"csv[{idx}]")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="Wait for a full fit artifact and finalize validation/promotion automatically.")
    ap.add_argument("--fit-out", default="params_fitted.full.tmp.json")
    ap.add_argument("--target", default="params_fitted.json")
    ap.add_argument("--report", default="ops/monitoring/full_fit_finalize_report.json")
    ap.add_argument("--progress", default="ops/monitoring/fit_ml_params_progress.json")
    ap.add_argument("--checkpoint-dir", default="")
    ap.add_argument("--fit-stdout-log", default="")
    ap.add_argument("--fit-pid", type=int, default=0)
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--players-artifact", default="players_artifact.json")
    ap.add_argument("--source-manifest", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--latest-report-alias", default="ops/monitoring/full_fit_finalize_report.json")
    ap.add_argument("--poll-seconds", type=int, default=60)
    ap.add_argument("--timeout-seconds", type=int, default=21600)
    ap.add_argument("--stale-seconds", type=int, default=1800)
    ap.add_argument("--cpu-idle-threshold", type=float, default=0.05)
    ap.add_argument("--cpu-sample-seconds", type=int, default=3)
    ap.add_argument("--tag-prefix", default="fullfit_watch")
    args = ap.parse_args()

    fit_out = (ROOT / str(args.fit_out)).resolve()
    target = (ROOT / str(args.target)).resolve()
    report_path = (ROOT / str(args.report)).resolve()
    progress_path = (ROOT / str(args.progress)).resolve()
    checkpoint_dir = (ROOT / str(args.checkpoint_dir)).resolve() if str(args.checkpoint_dir or "").strip() else None
    fit_stdout_log = (ROOT / str(args.fit_stdout_log)).resolve() if str(args.fit_stdout_log or "").strip() else None
    artifact_path = (ROOT / str(args.artifact)).resolve()
    players_artifact_path = (ROOT / str(args.players_artifact)).resolve()
    source_manifest_path = (ROOT / str(args.source_manifest)).resolve() if str(args.source_manifest or "").strip() else None
    report_aliases = []
    if str(args.latest_report_alias or "").strip():
        report_aliases.append((ROOT / str(args.latest_report_alias)).resolve())
    backup_dir = (ROOT / "ops" / "backups").resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    source_manifest = _read_json(source_manifest_path) if source_manifest_path is not None else {}

    started_at = _utc_now()
    report: Dict[str, Any] = {
        "version": "full_fit_finalize_v1",
        "started_at": started_at,
        "run_id": str(args.run_id or "").strip(),
        "fit_out": str(fit_out),
        "target": str(target),
        "progress_path": str(progress_path),
        "checkpoint_dir": (str(checkpoint_dir) if checkpoint_dir is not None else ""),
        "fit_stdout_log": (str(fit_stdout_log) if fit_stdout_log is not None else ""),
        "artifact_path": str(artifact_path),
        "players_artifact_path": str(players_artifact_path),
        "source_manifest_path": (str(source_manifest_path) if source_manifest_path is not None else ""),
        "steps": [],
        "status": "waiting",
    }
    if source_manifest:
        report["source_manifest"] = source_manifest
    _write_report(report_path, report, aliases=report_aliases)

    deadline = time.time() + int(max(60, args.timeout_seconds))
    fit_obj: Dict[str, Any] = {}
    stale_seconds = int(max(60, args.stale_seconds))
    while time.time() < deadline:
        now_ts = time.time()
        fit_obj = _read_json(fit_out)
        progress_obj = _read_json(progress_path)
        fit_pid = int(max(0, int(args.fit_pid or 0)))
        if progress_obj:
            fit_pid = max(fit_pid, _safe_int(((progress_obj.get("process") or {}).get("pid")), 0))
        launch_manifest = _read_json(ROOT / "ops" / "monitoring" / "full_fit_launch_latest.json")
        if fit_pid <= 0 and isinstance(launch_manifest, dict):
            fit_pid = max(fit_pid, _safe_int(launch_manifest.get("fit_pid"), 0))
        if checkpoint_dir is None and isinstance(launch_manifest, dict) and str(launch_manifest.get("checkpoint_dir") or "").strip():
            checkpoint_dir = (ROOT / str(launch_manifest.get("checkpoint_dir"))).resolve()
        if fit_stdout_log is None and isinstance(launch_manifest, dict) and str(launch_manifest.get("fit_stdout_log") or "").strip():
            fit_stdout_log = Path(str(launch_manifest.get("fit_stdout_log"))).resolve()
        if progress_obj:
            report["fit_progress"] = progress_obj
        progress_updated_epoch = _parse_iso_to_epoch((progress_obj or {}).get("updated_at"))
        progress_age_s = (float(max(0.0, now_ts - progress_updated_epoch)) if progress_updated_epoch is not None else None)
        activity_marks = [x for x in [_path_mtime(progress_path), _path_mtime(fit_out), _latest_tree_mtime(checkpoint_dir) if checkpoint_dir is not None else None, _path_mtime(fit_stdout_log) if fit_stdout_log is not None else None] if x is not None]
        latest_activity_ts = max(activity_marks) if activity_marks else None
        activity_age_s = (float(max(0.0, now_ts - latest_activity_ts)) if latest_activity_ts is not None else None)
        watchdog: Dict[str, Any] = {
            "stale_seconds": int(stale_seconds),
            "fit_pid": int(fit_pid),
            "progress_age_s": progress_age_s,
            "activity_age_s": activity_age_s,
        }
        if progress_age_s is not None and progress_age_s > float(stale_seconds):
            cpu_before = _read_process_cpu_seconds(int(fit_pid))
            time.sleep(int(max(1, args.cpu_sample_seconds)))
            cpu_after = _read_process_cpu_seconds(int(fit_pid))
            cpu_delta = (
                float(max(0.0, cpu_after - cpu_before))
                if cpu_before is not None and cpu_after is not None
                else None
            )
            watchdog["cpu_before_s"] = cpu_before
            watchdog["cpu_after_s"] = cpu_after
            watchdog["cpu_delta_s"] = cpu_delta
            if cpu_before is None and cpu_after is None:
                report["status"] = "stalled_fit_process_dead"
                report["watchdog"] = watchdog
                report["finished_at"] = _utc_now()
                _write_report(report_path, report, aliases=report_aliases)
                return 3
            if (cpu_delta is not None) and (cpu_delta <= float(max(0.0, args.cpu_idle_threshold))) and (
                activity_age_s is None or activity_age_s > float(stale_seconds)
            ):
                report["status"] = "stalled_fit_no_heartbeat"
                report["watchdog"] = watchdog
                report["finished_at"] = _utc_now()
                _write_report(report_path, report, aliases=report_aliases)
                return 4
            watchdog["state"] = "stale_but_busy"
        else:
            watchdog["state"] = "healthy"
        report["watchdog"] = watchdog
        _write_report(report_path, report, aliases=report_aliases)
        if fit_obj:
            break
        time.sleep(int(max(5, args.poll_seconds)))

    if not fit_obj:
        report["status"] = "timeout_waiting_fit"
        report["finished_at"] = _utc_now()
        _write_report(report_path, report, aliases=report_aliases)
        return 1

    if str(fit_obj.get("speed_profile") or "").strip().lower() != "full":
        report["status"] = "invalid_fit_artifact"
        report["fit_summary"] = {
            "speed_profile": fit_obj.get("speed_profile"),
            "generated_at": fit_obj.get("generated_at"),
        }
        report["finished_at"] = _utc_now()
        _write_report(report_path, report, aliases=report_aliases)
        return 2

    live_input_drift = _detect_live_input_drift(source_manifest) if source_manifest else []
    if live_input_drift:
        report["status"] = "source_drift_detected_no_promotion"
        report["finished_at"] = _utc_now()
        report["live_input_drift"] = live_input_drift
        report["fit_summary"] = {
            "generated_at": fit_obj.get("generated_at"),
            "speed_profile": fit_obj.get("speed_profile"),
            "samples_total": fit_obj.get("samples_total"),
            "min_train_games": fit_obj.get("min_train_games"),
        }
        _write_report(report_path, report, aliases=report_aliases)
        return 5

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tag = f"{args.tag_prefix}_{ts}"
    backup_path = backup_dir / f"params_fitted.before_{tag}.json"
    if target.exists():
        shutil.copyfile(target, backup_path)
        report["backup_path"] = str(backup_path)
    shutil.copyfile(fit_out, target)
    report["status"] = "copied_fit_to_target"
    report["fit_summary"] = {
        "generated_at": fit_obj.get("generated_at"),
        "speed_profile": fit_obj.get("speed_profile"),
        "samples_total": fit_obj.get("samples_total"),
        "min_train_games": fit_obj.get("min_train_games"),
    }
    _write_report(report_path, report, aliases=report_aliases)

    steps: List[Dict[str, Any]] = []
    commands = [
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "mlcore/tests",
        ],
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "tools/check_regression.ps1",
        ],
        [
            sys.executable,
            "tools/run_ml_v3_phase0_baseline.py",
            "--mode",
            "full",
            "--artifact",
            str(artifact_path),
            "--players-artifact",
            str(players_artifact_path),
            "--params-fitted",
            str(target),
            "--out",
            f"phase0_ml_v3_baseline_report.full.{tag}.json",
            "--min-train-games",
            "1500",
            "--k",
            "26",
            "--scale",
            "400",
            "--bins",
            "10",
            "--min-league-games",
            "120",
            "--cal-use-microseg-fitted",
        ],
        [
            sys.executable,
            "tools/promote_baseline.py",
            "--tag",
            tag,
            "--key-gate-mode",
            "app",
        ],
        [
            sys.executable,
            "tools/run_ml_monitoring_window.py",
            "--days",
            "7",
        ],
    ]
    timeouts = [7200, 2400, 7200, 2400, 900]

    failed = False
    for cmd, timeout in zip(commands, timeouts):
        step = _run(cmd, timeout=timeout)
        steps.append(step)
        report["steps"] = steps
        _write_report(report_path, report, aliases=report_aliases)
        if not bool(step.get("ok")):
            failed = True
            break

    if failed:
        if backup_path.exists():
            shutil.copyfile(backup_path, target)
            report["rollback"] = {"applied": True, "source": str(backup_path)}
        else:
            report["rollback"] = {"applied": False, "source": ""}
        report["status"] = "failed_rolled_back"
        report["finished_at"] = _utc_now()
        _write_report(report_path, report, aliases=report_aliases)
        return 2

    report["status"] = "promoted"
    report["finished_at"] = _utc_now()
    report["promotion_report"] = str((ROOT / "ops" / "baselines" / tag / "promotion_report.json").resolve())
    _write_report(report_path, report, aliases=report_aliases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
