from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "phase5_hier_calibration_report.json"
BASELINE = ROOT / "ml_confidence_baseline.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.hier_calibration_core import apply_hier_calibration_live


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return {}


def _pick_segment_key(seg: Dict[str, Any]) -> str:
    for k in seg.keys():
        if str(k).startswith("league:") and "|bo:" in str(k):
            return str(k)
    return ""


def _parse_key(k: str) -> Dict[str, Any]:
    out = {"league": "", "bo": 1, "po": 0, "inter": 0}
    parts = [p for p in str(k).split("|") if p]
    for p in parts:
        if p.startswith("league:"):
            out["league"] = p.split(":", 1)[1].strip().upper()
        elif p.startswith("bo:"):
            try:
                out["bo"] = int(float(p.split(":", 1)[1]))
            except Exception:
                pass
        elif p.startswith("po:"):
            try:
                out["po"] = int(float(p.split(":", 1)[1]))
            except Exception:
                pass
        elif p.startswith("inter:"):
            try:
                out["inter"] = int(float(p.split(":", 1)[1]))
            except Exception:
                pass
    return out


def main() -> int:
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    decision = "promote"

    base = _read_json(BASELINE)
    ok_exists = bool(base)
    checks.append({"check": "baseline_exists", "ok": ok_exists, "detail": str(BASELINE)})
    if not ok_exists:
        decision = "reject"
        reasons.append("baseline_missing_or_invalid")

    by_seg = base.get("by_segment") if isinstance(base.get("by_segment"), dict) else {}
    by_lg = base.get("by_league") if isinstance(base.get("by_league"), dict) else {}
    by_lg_class = base.get("league_class") if isinstance(base.get("league_class"), dict) else {}
    by_inter = base.get("interleague_pairs") if isinstance(base.get("interleague_pairs"), dict) else {}
    th = base.get("thresholds") if isinstance(base.get("thresholds"), dict) else {}

    ok_seg = bool(len(by_seg) > 0)
    checks.append({"check": "baseline_by_segment_non_empty", "ok": ok_seg, "detail": f"by_segment={len(by_seg)}"})
    if not ok_seg and decision != "reject":
        decision = "shadow_only"
        reasons.append("by_segment_empty")

    ok_lg = bool(len(by_lg) > 0)
    checks.append({"check": "baseline_by_league_non_empty", "ok": ok_lg, "detail": f"by_league={len(by_lg)}"})
    if not ok_lg and decision != "reject":
        decision = "shadow_only"
        reasons.append("by_league_empty")

    ok_lg_class = bool(len(by_lg_class) > 0)
    checks.append({"check": "baseline_league_class_non_empty", "ok": ok_lg_class, "detail": f"league_class={len(by_lg_class)}"})
    if not ok_lg_class and decision != "reject":
        decision = "shadow_only"
        reasons.append("league_class_empty")

    ok_inter_tbl = bool(len(by_inter) > 0)
    checks.append({"check": "baseline_interleague_pairs_non_empty", "ok": ok_inter_tbl, "detail": f"interleague_pairs={len(by_inter)}"})
    if not ok_inter_tbl and decision != "reject":
        decision = "shadow_only"
        reasons.append("interleague_pairs_empty")

    ok_th = bool(
        {
            "seg_shrink_k",
            "league_shrink_k",
            "global_shrink_k",
            "hier_decay",
            "inter_shrink_k",
            "fine_z_hi",
            "fine_z_xhi",
            "fine_shrink_hi",
            "fine_shrink_xhi",
            "fine_profiles",
            "fine_profile_by_league_same",
            "fine_profile_by_league_inter",
        }.issubset(set(th.keys()))
    )
    checks.append({"check": "threshold_keys_present", "ok": ok_th, "detail": f"keys={sorted(list(th.keys()))}"})
    if not ok_th and decision != "reject":
        decision = "shadow_only"
        reasons.append("threshold_keys_missing")

    by_inter_src = {
        str(v.get("source") or "")
        for v in by_inter.values()
        if isinstance(v, dict)
    }
    ok_inter_source = (
        any("agg_v2" in s for s in by_inter_src)
        or any("repair_" in s for s in by_inter_src)
        or any("meta_v2" in s for s in by_inter_src)
        or any("meta_v3" in s for s in by_inter_src)
        or any("interleague_pair_meta" in s for s in by_inter_src)
    )
    checks.append(
        {
            "check": "interleague_pairs_have_aggregated_or_repair_source",
            "ok": bool(ok_inter_source),
            "detail": {"sources": sorted(list(by_inter_src))[:12]},
        }
    )
    if not ok_inter_source and decision != "reject":
        decision = "shadow_only"
        reasons.append("interleague_source_not_agg")

    seg_class_keys = [k for k in by_seg.keys() if str(k).startswith("class:")]
    seg_patch_keys = [k for k in by_seg.keys() if "|patch:" in str(k)]
    ok_seg_class_patch = bool(len(seg_class_keys) >= 3 and len(seg_patch_keys) > 0)
    checks.append(
        {
            "check": "baseline_segments_have_class_and_patch_coverage",
            "ok": ok_seg_class_patch,
            "detail": {"class_keys": len(seg_class_keys), "patch_keys": len(seg_patch_keys)},
        }
    )
    if not ok_seg_class_patch and decision != "reject":
        decision = "shadow_only"
        reasons.append("segments_class_patch_missing")

    sample_key = _pick_segment_key(by_seg)
    parsed = _parse_key(sample_key)
    sample_out = apply_hier_calibration_live(
        p_map_in=0.58,
        league=parsed.get("league"),
        league_a=parsed.get("league"),
        league_b=parsed.get("league"),
        bo=parsed.get("bo", 1),
        playoffs=bool(int(parsed.get("po", 0))),
        interregional=bool(int(parsed.get("inter", 0))),
        n_team_eff=45,
        n_players_eff=25,
        patch_status="ok",
        baseline_payload=base,
    )
    ok_runtime = (
        bool(sample_out.get("enabled", False))
        and str(sample_out.get("method") or "") == "hier_calibration_v3"
        and str(sample_out.get("scope_used") or "").startswith("league:")
    )
    checks.append(
        {
            "check": "runtime_scope_resolves_segment_or_league",
            "ok": ok_runtime,
            "detail": {
                "sample_key": sample_key,
                "method": sample_out.get("method"),
                "scope_used": sample_out.get("scope_used"),
                "reason": sample_out.get("reason"),
                "applied": sample_out.get("applied"),
            },
        }
    )
    if not ok_runtime and decision != "reject":
        decision = "shadow_only"
        reasons.append("runtime_scope_not_resolved")

    # Interregional sanity: must populate interleague metadata and stay conservative.
    _lg_keys = [str(k).strip().upper() for k in by_lg.keys() if str(k).strip()]
    lg_a = _lg_keys[0] if _lg_keys else "LCK"
    lg_b = _lg_keys[1] if len(_lg_keys) > 1 else ("LPL" if lg_a != "LPL" else "LEC")
    inter_out = apply_hier_calibration_live(
        p_map_in=0.66,
        league="INTER",
        league_a=lg_a,
        league_b=lg_b,
        bo=3,
        playoffs=False,
        interregional=True,
        n_team_eff=28,
        n_players_eff=12,
        patch_status="warn",
        baseline_payload=base,
    )
    inter_meta = inter_out.get("interleague") if isinstance(inter_out.get("interleague"), dict) else {}
    diff_inter = float(inter_out.get("diff_pp", 0.0) or 0.0)
    ok_inter_runtime = bool(inter_meta) and (str(inter_meta.get("macro_a") or "") != "") and (abs(diff_inter) <= 3.2)
    checks.append(
        {
            "check": "runtime_interregional_has_meta_and_conservative_move",
            "ok": ok_inter_runtime,
            "detail": {
                "league_a": lg_a,
                "league_b": lg_b,
                "reason": inter_out.get("reason"),
                "interleague": inter_meta,
                "diff_pp": diff_inter,
            },
        }
    )
    if not ok_inter_runtime and decision != "reject":
        decision = "shadow_only"
        reasons.append("runtime_interregional_invalid")

    fine_out = apply_hier_calibration_live(
        p_map_in=0.93,
        league=lg_a,
        league_a=lg_a,
        league_b=lg_a,
        bo=1,
        playoffs=False,
        interregional=False,
        n_team_eff=2,
        n_players_eff=0,
        patch_status="warn",
        baseline_payload=base,
    )
    fine_node = fine_out.get("runtime_fine") if isinstance(fine_out.get("runtime_fine"), dict) else {}
    ok_runtime_fine = str(fine_node.get("band") or "") in {"high", "extreme"} and float(fine_node.get("fine_shrink", 0.0) or 0.0) > 0.0
    checks.append(
        {
            "check": "runtime_fine_band_active_on_extreme_prob",
            "ok": ok_runtime_fine,
            "detail": {"runtime_fine": fine_node, "reason": fine_out.get("reason")},
        }
    )
    if not ok_runtime_fine and decision != "reject":
        decision = "shadow_only"
        reasons.append("runtime_fine_not_active")

    rep = {
        "version": "phase5_hier_calibration_gate_v3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "reasons": reasons,
        "summary": {
            "ok": int(sum(1 for c in checks if bool(c.get("ok")))),
            "total": len(checks),
            "sample_key": sample_key,
            "scope_used": sample_out.get("scope_used"),
            "by_segment": len(by_seg),
            "by_league": len(by_lg),
            "league_class": len(by_lg_class),
            "interleague_pairs": len(by_inter),
            "segment_class_keys": len(seg_class_keys),
            "segment_patch_keys": len(seg_patch_keys),
        },
        "checks": checks,
    }
    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase5 gate -> {OUT.name} | decision={decision} | "
        f"ok={rep['summary']['ok']}/{rep['summary']['total']} | by_segment={len(by_seg)}"
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
