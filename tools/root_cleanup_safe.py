from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]

ACTIVE_ROOT_FILES = {
    ".gabinete_settings.json",
    "achievements.json",
    "anchor_regression_report.json",
    "backtest_pipeline_abc_by_league_report.json",
    "champion_knowledge_registry.json",
    "csv_bootstrap_last_report.json",
    "csv_bootstrap_maintenance_cache.json",
    "csv_bootstrap_maintenance_report.json",
    "csv_bootstrap_maintenance_state.json",
    "data_leakage_label_report.json",
    "identity_registry.json",
    "lacuna_guardrail_report.json",
    "league_transfer_features.json",
    "lv_last_report.json",
    "ml_artifact.json",
    "ml_confidence_baseline.json",
    "ml_trace_last.json",
    "odds_anchor_baseline.json",
    "params_fitted.json",
    "phase1_data_contract_report.json",
    "phase12_roster_continuity_report.json",
    "phase2_areal_report.json",
    "phase2b_areal_tuning_report.json",
    "phase3_breal_report.json",
    "phase4_ranksos_report.json",
    "phase4b_marginal_tuning_report.json",
    "phase5_hier_calibration_report.json",
    "phase5b_hier_oos_paired_report.json",
    "phase5c_hier_interleague_report.json",
    "phase5d_hier_sameleague_report.json",
    "phase6_series_bo_report.json",
    "phase7_layer_uncertainty_report.json",
    "phase8_operations_report.json",
    "phase9_players_report.json",
    "players_artifact.json",
    "plays_app.py",
    "prod_refresh_report.json",
    "RUN_PLAYS_WINDOWS.bat",
    "team_state_artifact.json",
    "user_games_agenda.json",
    "user_lines_store.json",
    "user_schedule_store.json",
    "user_team_aliases.json",
    "wf_last_report.json",
}

KEEP_DIRS = {
    ".venv",
    ".vscode",
    "app_core",
    "backups",
    "CSV_DIARIO",
    "CSV_HISTORICO",
    "docs",
    "evidence",
    "lixeira",
    "mlcore",
    "ops",
    "stabilization_snapshots",
    "tools",
}


def _latest_nonempty_archive(default: Path) -> Path:
    backups_dir = ROOT / "backups"
    candidates = sorted(backups_dir.glob("root_cleanup_*"), key=lambda p: p.name, reverse=True)
    for candidate in candidates:
        manifest = candidate / "manifest.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("moved"):
            return candidate
    return default


def _should_archive(path: Path) -> bool:
    if path.name in ACTIVE_ROOT_FILES:
        return False
    if path.name in {"pyrightconfig.json", "AGENTS.md"}:
        return False
    return True


def _move(src: Path, dst_root: Path, *, dry_run: bool) -> Dict[str, str]:
    rel = src.relative_to(ROOT)
    dst = dst_root / rel
    if dry_run:
        return {"src": str(src), "dst": str(dst), "action": "dry_run_move"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"src": str(src), "dst": str(dst), "action": "moved"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Safe root cleanup for gabinete LoL project.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = ROOT / "backups" / f"root_cleanup_{stamp}"
    docs_root = ROOT / "docs" / "root_archive"

    moved: List[Dict[str, str]] = []
    deleted: List[str] = []

    for path in ROOT.iterdir():
        if path.is_dir():
            if path.name == "__pycache__":
                if not args.dry_run:
                    shutil.rmtree(path, ignore_errors=True)
                deleted.append(str(path))
            elif path.name not in KEEP_DIRS:
                moved.append(_move(path, archive_root, dry_run=args.dry_run))
            continue

        if path.name == "_tmp_root_refs.txt":
            if not args.dry_run:
                path.unlink(missing_ok=True)
            deleted.append(str(path))
            continue

        if path.suffix.lower() == ".md":
            moved.append(_move(path, docs_root, dry_run=args.dry_run))
            continue

        if _should_archive(path):
            moved.append(_move(path, archive_root, dry_run=args.dry_run))

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(ROOT),
        "archive_root": str(archive_root),
        "docs_root": str(docs_root),
        "dry_run": bool(args.dry_run),
        "active_root_files": sorted(ACTIVE_ROOT_FILES),
        "moved": moved,
        "deleted": deleted,
    }
    target_root = archive_root if not args.dry_run else ROOT / "backups" / "_dry_run_root_cleanup"
    target_root.mkdir(parents=True, exist_ok=True)
    (target_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    docs_root.mkdir(parents=True, exist_ok=True)
    archive_ref = archive_root if moved else _latest_nonempty_archive(archive_root)
    (ROOT / "docs" / "ROOT_ORGANIZATION.md").write_text(
        "\n".join(
            [
                "# Root Organization",
                "",
                "Arquivos que permanecem no root por serem usados diretamente pelo app/runtime:",
                "",
            ]
            + [f"- `{name}`" for name in sorted(ACTIVE_ROOT_FILES)]
            + [
                "",
                "Arquivos historicos, variantes, backups e relatorios antigos foram movidos para:",
                f"- `{archive_ref}`",
                "",
                "Documentacao solta do root foi movida para:",
                f"- `{docs_root}`",
            ]
        ),
        encoding="utf-8",
    )

    print(json.dumps({"moved": len(moved), "deleted": len(deleted), "dry_run": bool(args.dry_run)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

