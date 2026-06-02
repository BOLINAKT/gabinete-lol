from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.identity_registry_audit_core import audit_identity_registry
from app_core.identity_registry_core import load_identity_registry
from app_core.runtime_canary_core import evaluate_runtime_canary
from mlcore.tiers import canonical_league, is_international_league


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Lightweight runtime canary for identity, matchup integrity and CSV gate.")
    ap.add_argument("--registry", default=str(ROOT / "identity_registry.json"))
    ap.add_argument("--identity-out", default=str(ROOT / "ops" / "monitoring" / "identity_registry_audit_report.json"))
    ap.add_argument("--matchup-report", default=str(ROOT / "ops" / "monitoring" / "matchup_integrity_audit_report.json"))
    ap.add_argument("--csv-gate-report", default=str(ROOT / "ops" / "csv_ingest" / "csv_ingest_gate_report.json"))
    ap.add_argument("--out", default=str(ROOT / "ops" / "monitoring" / "runtime_canary_report.json"))
    args = ap.parse_args()

    registry_path = Path(args.registry).expanduser().resolve()
    identity_out_path = Path(args.identity_out).expanduser().resolve()
    matchup_report_path = Path(args.matchup_report).expanduser().resolve()
    csv_gate_report_path = Path(args.csv_gate_report).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    registry = load_identity_registry(registry_path)
    identity_report = audit_identity_registry(
        registry,
        canonicalize_league_fn=canonical_league,
        is_international_league_fn=is_international_league,
    )
    identity_report_payload = {
        "version": "identity_registry_audit_v1",
        "generated_at": _utc_now(),
        "registry_path": str(registry_path),
        **identity_report,
    }
    _write_json(identity_out_path, identity_report_payload)

    matchup_report = _read_json(matchup_report_path)
    csv_gate_report = _read_json(csv_gate_report_path)
    decision_payload = evaluate_runtime_canary(
        matchup_report=matchup_report,
        identity_report=identity_report_payload,
        csv_gate_report=csv_gate_report,
    )
    payload = {
        "version": "runtime_canary_v1",
        "generated_at": _utc_now(),
        "decision": str(decision_payload.get("decision") or "shadow_only"),
        "reasons": list(decision_payload.get("reasons") or []),
        "components": decision_payload.get("components") or {},
        "inputs": {
            "registry_path": str(registry_path),
            "identity_report_path": str(identity_out_path),
            "matchup_report_path": str(matchup_report_path),
            "csv_gate_report_path": str(csv_gate_report_path),
        },
    }
    _write_json(out_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["decision"] == "promote" else (1 if payload["decision"] == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
