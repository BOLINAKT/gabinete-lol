from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]

SNAPSHOT_TO_TARGET = {
    "ml_artifact.json": "ml_artifact.json",
    "players_artifact.json": "players_artifact.json",
    "params_fitted.json": "params_fitted.json",
    "odds_regression.json": "mlcore/tests/fixtures/odds_regression.json",
    "odds_regression_40.json": "mlcore/tests/fixtures/odds_regression_40.json",
    "interleague_matchups_regression.json": "mlcore/tests/fixtures/interleague_matchups_regression.json",
}


def _pick_baseline_dir(root: Path, baseline_dir_arg: str) -> Path:
    if baseline_dir_arg:
        p = Path(baseline_dir_arg).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        return p
    base = root / "ops" / "baselines"
    cands = [p for p in base.glob("*") if p.is_dir()]
    if not cands:
        raise FileNotFoundError("Nenhum baseline encontrado em ops/baselines.")
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def _read_manifest(base_dir: Path) -> Dict[str, Any]:
    m = base_dir / "manifest.json"
    if not m.exists():
        return {}
    try:
        obj = json.loads(m.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _safe_backup(path: Path) -> Path | None:
    try:
        if path.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            bak = path.with_name(f"{path.name}.pre_rollback_{ts}.bak")
            shutil.copy2(path, bak)
            return bak
    except Exception:
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Rollback artifacts/fixtures from a baseline snapshot.")
    ap.add_argument("--baseline-dir", default="", help="Baseline folder path. If empty, uses latest from ops/baselines.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base_dir = _pick_baseline_dir(ROOT, str(args.baseline_dir or ""))
    manifest = _read_manifest(base_dir)

    steps: List[Dict[str, Any]] = []
    ok = True
    for snap_name, target_rel in SNAPSHOT_TO_TARGET.items():
        src = base_dir / snap_name
        dst = ROOT / target_rel
        step: Dict[str, Any] = {
            "snapshot": str(src),
            "target": str(dst),
            "exists_snapshot": src.exists(),
            "applied": False,
            "backup": None,
            "error": "",
        }
        if not src.exists():
            step["error"] = "snapshot_missing"
            steps.append(step)
            continue
        try:
            if not bool(args.dry_run):
                dst.parent.mkdir(parents=True, exist_ok=True)
                bak = _safe_backup(dst)
                if bak is not None:
                    step["backup"] = str(bak)
                shutil.copy2(src, dst)
            step["applied"] = True
        except Exception as e:
            ok = False
            step["error"] = str(e)
        steps.append(step)

    report = {
        "rolled_back_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_dir": str(base_dir),
        "manifest_found": bool(manifest),
        "dry_run": bool(args.dry_run),
        "ok": bool(ok),
        "steps": steps,
    }
    out = ROOT / "rollback_baseline_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: rollback report -> {out.name} | baseline={base_dir.name} | ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
