from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.interleague_baseline_core import (
    build_interleague_pairs_table,
    infer_league_class_from_node,
)
from mlcore.league_context import league_macro_key
from mlcore.tiers import canonical_league

BASELINE = ROOT / "ml_confidence_baseline.json"
THRESH_DEFAULTS = {
    "low_sample_min_n": 300,
    "bias_clip_abs": 15.0,
    "seg_shrink_k": 160.0,
    "league_shrink_k": 260.0,
    "global_shrink_k": 400.0,
    "hier_decay": 0.78,
    "inter_shrink_k": 320.0,
    "fine_z_hi": 1.20,
    "fine_z_xhi": 1.85,
    "fine_shrink_hi": 0.05,
    "fine_shrink_xhi": 0.09,
    "fine_profiles": {
        "default": {"fine_z_hi": 1.20, "fine_z_xhi": 1.85, "fine_shrink_hi": 0.05, "fine_shrink_xhi": 0.09},
        "same_league": {"fine_z_hi": 1.25, "fine_z_xhi": 1.95, "fine_shrink_hi": 0.045, "fine_shrink_xhi": 0.08},
        "interregional": {"fine_z_hi": 1.10, "fine_z_xhi": 1.70, "fine_shrink_hi": 0.07, "fine_shrink_xhi": 0.12},
        "strict_low_sample": {"fine_z_hi": 1.00, "fine_z_xhi": 1.55, "fine_shrink_hi": 0.085, "fine_shrink_xhi": 0.145},
        "major_stable": {"fine_z_hi": 1.35, "fine_z_xhi": 2.05, "fine_shrink_hi": 0.035, "fine_shrink_xhi": 0.065},
    },
    "fine_profile_by_league": {},
    "fine_profile_by_league_same": {},
    "fine_profile_by_league_inter": {},
}


def _build_fallback_segments(payload: Dict[str, Any]) -> Dict[str, Any]:
    by_league = payload.get("by_league") if isinstance(payload.get("by_league"), dict) else {}
    out: Dict[str, Any] = {}
    for lg, node in by_league.items():
        if not isinstance(node, dict):
            continue
        lg_key = str(canonical_league(str(lg or "")))
        if not lg_key:
            continue
        try:
            sb = float(node.get("score_bias"))
        except Exception:
            continue
        wf_n = int(node.get("wf_n") or 0)
        lv_n = int(node.get("lv_n") or 0)
        n = int(max(0, wf_n, lv_n))
        qb = str(node.get("quality_band") or ("ok" if n >= 300 else "low_sample"))
        for bo in (1, 3, 5):
            for po in (0, 1):
                key = f"league:{lg_key}|bo:{bo}|po:{po}|inter:0"
                out[key] = {
                    "score_bias": float(sb),
                    "wf_n": int(n),
                    "quality_band": qb,
                    "source": "fallback_by_league_copy",
                }
    return out


def _macro_group(league: Any) -> str:
    return str(league_macro_key(str(league or ""), unknown="OTHER"))


def _build_fallback_interleague_pairs(payload: Dict[str, Any]) -> Dict[str, Any]:
    by_league = payload.get("by_league") if isinstance(payload.get("by_league"), dict) else {}
    league_class = payload.get("league_class") if isinstance(payload.get("league_class"), dict) else {}
    return build_interleague_pairs_table(by_league, league_class_out=league_class)


def _rebuild_league_class(payload: Dict[str, Any]) -> Dict[str, str]:
    by_league = payload.get("by_league") if isinstance(payload.get("by_league"), dict) else {}
    out: Dict[str, str] = {}
    for lg, node in by_league.items():
        if not isinstance(node, dict):
            continue
        lg_key = str(canonical_league(str(lg or "")))
        if not lg_key:
            continue
        out[lg_key] = str(infer_league_class_from_node(lg_key, node))
    return out


def main() -> int:
    if not BASELINE.exists():
        print("ERROR: ml_confidence_baseline.json nao encontrado.")
        return 2
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: baseline invalido: {e}")
        return 2
    if not isinstance(payload, dict):
        print("ERROR: baseline nao e dict.")
        return 2

    by_segment = payload.get("by_segment") if isinstance(payload.get("by_segment"), dict) else {}
    by_inter = payload.get("interleague_pairs") if isinstance(payload.get("interleague_pairs"), dict) else {}
    thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {}
    league_class = payload.get("league_class") if isinstance(payload.get("league_class"), dict) else {}
    changed = False
    changed_reasons = []

    changed_thresholds = False
    for k, v in THRESH_DEFAULTS.items():
        if k not in thresholds:
            thresholds[k] = v
            changed_thresholds = True
    payload["thresholds"] = thresholds
    if changed_thresholds:
        changed = True
        changed_reasons.append("threshold_keys_completed")

    if len(by_segment) == 0:
        repaired = _build_fallback_segments(payload)
        payload["by_segment"] = repaired
        by_segment = repaired
        changed = True
        changed_reasons.append("by_segment_empty_fallback_from_by_league")

    rebuilt_class = _rebuild_league_class(payload)
    league_class_changed = bool(rebuilt_class and rebuilt_class != league_class)
    if league_class_changed:
        payload["league_class"] = rebuilt_class
        league_class = rebuilt_class
        changed = True
        changed_reasons.append("league_class_rebuilt_from_by_league")

    _inter_src = {
        str(v.get("source") or "")
        for v in by_inter.values()
        if isinstance(v, dict)
    }
    _has_tier_pair = any(str(k).startswith("tier_pair:") for k in by_inter.keys())
    _inter_needs_repair = league_class_changed or (len(by_inter) == 0) or (
        (not _has_tier_pair)
        or
        not any(
            ("agg_v2" in s)
            or ("repair_" in s)
            or ("interleague_pair_meta_v" in s)
            or ("interleague_tier_pair_meta_v" in s)
            or ("interleague_league_pair_meta_v" in s)
            for s in _inter_src
        )
    )
    if _inter_needs_repair:
        repaired_inter = _build_fallback_interleague_pairs(payload)
        payload["interleague_pairs"] = repaired_inter
        by_inter = repaired_inter
        changed = True
        changed_reasons.append("interleague_pairs_repaired_from_by_league")

    _v = str(payload.get("version") or "").strip()
    if _v in {"", "ml_confidence_baseline_v1", "ml_confidence_baseline_v2", "ml_confidence_baseline_v3"}:
        payload["version"] = "ml_confidence_baseline_v4"
        changed = True
        changed_reasons.append("version_upgraded_v4")

    if not changed:
        print(f"OK: baseline ja consistente | by_segment={len(by_segment)} | interleague_pairs={len(by_inter)}")
        return 0

    payload["repaired_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["repaired_reason"] = ",".join(changed_reasons)
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "OK: baseline reparado"
        f" | by_segment={len(by_segment)}"
        f" | interleague_pairs={len(by_inter)}"
        f" | reasons={payload.get('repaired_reason')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
