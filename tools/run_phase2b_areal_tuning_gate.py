from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlcore.state_team_artifact import build_team_state_artifact


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rank(d: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2}.get(str(d or ""), 1)


def _default_csvs(root: Path) -> List[Path]:
    out: List[Path] = []
    d_hist = root / "CSV_HISTORICO"
    d_daily = root / "CSV_DIARIO"
    if d_hist.exists():
        out.extend(sorted([p for p in d_hist.glob("*.csv") if p.is_file()]))
    if d_daily.exists():
        out.extend(sorted([p for p in d_daily.glob("*.csv") if p.is_file()]))
    return out


def _select_csvs_for_speed(csvs: List[Path], speed: str) -> List[Path]:
    if str(speed) != "fast":
        return list(csvs)
    daily = [p for p in csvs if "CSV_DIARIO" in str(p).upper()]
    try:
        daily = sorted(daily, key=lambda x: x.stat().st_mtime, reverse=True)
    except Exception:
        daily = list(daily)
    if daily:
        return [daily[0]]
    if not csvs:
        return []
    try:
        return [sorted(csvs, key=lambda x: x.stat().st_mtime, reverse=True)[0]]
    except Exception:
        return [csvs[-1]]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_f(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else float(default)
    except Exception:
        return float(default)


def _pick_best(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {}
    return min(results, key=lambda r: (_safe_f(r.get("logloss"), 9.0), _safe_f(r.get("brier"), 9.0)))


def _impr(base: float, best: float) -> float:
    if not (math.isfinite(base) and math.isfinite(best)):
        return float("nan")
    return float(base - best)


def _coerce_maps_from_candidates(
    *,
    all_results: List[Dict[str, Any]],
    global_best: Dict[str, Any],
    min_n_league: int,
    min_n_patch: int,
    min_gain: float,
    min_gain_patch: float,
    patch_top_k: int,
) -> Dict[str, Any]:
    by_league: Dict[str, Dict[str, Any]] = {}
    by_patch: Dict[str, Dict[str, Any]] = {}
    for r in all_results:
        lg = r.get("by_league") if isinstance(r.get("by_league"), dict) else {}
        pt = r.get("by_patch") if isinstance(r.get("by_patch"), dict) else {}
        for lk, lv in lg.items():
            if not isinstance(lv, dict):
                continue
            n = int(_safe_f(lv.get("n"), 0.0))
            if n <= 0:
                continue
            ll = _safe_f(lv.get("logloss"))
            br = _safe_f(lv.get("brier"))
            if not (math.isfinite(ll) and math.isfinite(br)):
                continue
            lst = by_league.setdefault(str(lk).upper(), [])
            lst.append(
                {
                    "n": n,
                    "logloss": ll,
                    "brier": br,
                    "bayes_info_scale": float(r.get("bayes_info_scale")),
                    "quality_k_boost": float(r.get("quality_k_boost")),
                    "qwl_surplus_mix": float(r.get("qwl_surplus_mix")),
                    "qwl_throw_weight": float(r.get("qwl_throw_weight")),
                    "qwl_comeback_weight": float(r.get("qwl_comeback_weight")),
                    "qwl_phase_dynamic_strength": float(r.get("qwl_phase_dynamic_strength")),
                    "qwl_opponent_context_mix": float(r.get("qwl_opponent_context_mix")),
                }
            )
        for pk, pv in pt.items():
            if not isinstance(pv, dict):
                continue
            n = int(_safe_f(pv.get("n"), 0.0))
            if n <= 0:
                continue
            ll = _safe_f(pv.get("logloss"))
            br = _safe_f(pv.get("brier"))
            if not (math.isfinite(ll) and math.isfinite(br)):
                continue
            lst = by_patch.setdefault(str(pk).upper(), [])
            lst.append(
                {
                    "n": n,
                    "logloss": ll,
                    "brier": br,
                    "bayes_info_scale": float(r.get("bayes_info_scale")),
                    "quality_k_boost": float(r.get("quality_k_boost")),
                    "qwl_surplus_mix": float(r.get("qwl_surplus_mix")),
                    "qwl_throw_weight": float(r.get("qwl_throw_weight")),
                    "qwl_comeback_weight": float(r.get("qwl_comeback_weight")),
                    "qwl_phase_dynamic_strength": float(r.get("qwl_phase_dynamic_strength")),
                    "qwl_opponent_context_mix": float(r.get("qwl_opponent_context_mix")),
                }
            )

    out_bayes: Dict[str, float] = {}
    out_quality: Dict[str, float] = {}
    out_qwl: Dict[str, float] = {}
    out_qwl_throw: Dict[str, float] = {}
    out_qwl_comeback: Dict[str, float] = {}
    out_qwl_phase_dyn: Dict[str, float] = {}
    out_qwl_opp_ctx: Dict[str, float] = {}
    out_bayes_patch: Dict[str, float] = {}
    out_quality_patch: Dict[str, float] = {}
    out_qwl_patch: Dict[str, float] = {}
    out_qwl_throw_patch: Dict[str, float] = {}
    out_qwl_comeback_patch: Dict[str, float] = {}
    out_qwl_phase_dyn_patch: Dict[str, float] = {}
    out_qwl_opp_ctx_patch: Dict[str, float] = {}
    diag_league: Dict[str, Dict[str, Any]] = {}
    diag_patch: Dict[str, Dict[str, Any]] = {}
    g_b = float(global_best.get("bayes_info_scale", 1.0))
    g_q = float(global_best.get("quality_k_boost", 0.22))
    g_qwl = float(global_best.get("qwl_surplus_mix", 0.70))
    g_qwl_throw = float(global_best.get("qwl_throw_weight", 1.20))
    g_qwl_comeback = float(global_best.get("qwl_comeback_weight", 0.65))
    g_qwl_phase_dyn = float(global_best.get("qwl_phase_dynamic_strength", 0.35))
    g_qwl_opp_ctx = float(global_best.get("qwl_opponent_context_mix", 0.30))
    for lk, rows in by_league.items():
        if not rows:
            continue
        n_tot = int(sum(int(x.get("n", 0)) for x in rows))
        if n_tot < int(min_n_league):
            diag_league[lk] = {
                "n_total": int(n_tot),
                "candidate_points": len(rows),
                "selected": False,
                "reason": "low_n",
                "global": {
                    "bayes_info_scale": float(g_b),
                    "quality_k_boost": float(g_q),
                    "qwl_surplus_mix": float(g_qwl),
                    "qwl_throw_weight": float(g_qwl_throw),
                    "qwl_comeback_weight": float(g_qwl_comeback),
                    "qwl_phase_dynamic_strength": float(g_qwl_phase_dyn),
                    "qwl_opponent_context_mix": float(g_qwl_opp_ctx),
                },
            }
            continue
        # choose best for this league
        best = min(rows, key=lambda x: (float(x.get("logloss", 9.0)), float(x.get("brier", 9.0))))
        # baseline at global point for this league (nearest by params)
        base_rows = [
            x
            for x in rows
            if abs(float(x.get("bayes_info_scale", g_b)) - g_b) < 1e-9
            and abs(float(x.get("quality_k_boost", g_q)) - g_q) < 1e-9
            and abs(float(x.get("qwl_surplus_mix", g_qwl)) - g_qwl) < 1e-9
            and abs(float(x.get("qwl_throw_weight", g_qwl_throw)) - g_qwl_throw) < 1e-9
            and abs(float(x.get("qwl_comeback_weight", g_qwl_comeback)) - g_qwl_comeback) < 1e-9
            and abs(float(x.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn)) - g_qwl_phase_dyn) < 1e-9
            and abs(float(x.get("qwl_opponent_context_mix", g_qwl_opp_ctx)) - g_qwl_opp_ctx) < 1e-9
        ]
        if not base_rows:
            diag_league[lk] = {
                "n_total": int(n_tot),
                "candidate_points": len(rows),
                "selected": False,
                "reason": "missing_global_baseline",
                "best": {
                    "bayes_info_scale": float(best.get("bayes_info_scale", g_b)),
                    "quality_k_boost": float(best.get("quality_k_boost", g_q)),
                    "qwl_surplus_mix": float(best.get("qwl_surplus_mix", g_qwl)),
                    "qwl_throw_weight": float(best.get("qwl_throw_weight", g_qwl_throw)),
                    "qwl_comeback_weight": float(best.get("qwl_comeback_weight", g_qwl_comeback)),
                    "qwl_phase_dynamic_strength": float(best.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn)),
                    "qwl_opponent_context_mix": float(best.get("qwl_opponent_context_mix", g_qwl_opp_ctx)),
                },
                "global": {
                    "bayes_info_scale": float(g_b),
                    "quality_k_boost": float(g_q),
                    "qwl_surplus_mix": float(g_qwl),
                    "qwl_throw_weight": float(g_qwl_throw),
                    "qwl_comeback_weight": float(g_qwl_comeback),
                    "qwl_phase_dynamic_strength": float(g_qwl_phase_dyn),
                    "qwl_opponent_context_mix": float(g_qwl_opp_ctx),
                },
            }
            continue
        base = base_rows[0]
        gain = _impr(float(base.get("logloss", float("nan"))), float(best.get("logloss", float("nan"))))
        selected = bool(math.isfinite(gain) and gain >= float(min_gain))
        diag_league[lk] = {
            "n_total": int(n_tot),
            "candidate_points": len(rows),
            "gain_logloss_best_vs_global": (float(gain) if math.isfinite(gain) else None),
            "selected": bool(selected),
            "reason": ("ok" if selected else "low_gain"),
            "best": {
                "bayes_info_scale": float(best.get("bayes_info_scale", g_b)),
                "quality_k_boost": float(best.get("quality_k_boost", g_q)),
                "qwl_surplus_mix": float(best.get("qwl_surplus_mix", g_qwl)),
                "qwl_throw_weight": float(best.get("qwl_throw_weight", g_qwl_throw)),
                "qwl_comeback_weight": float(best.get("qwl_comeback_weight", g_qwl_comeback)),
                "qwl_phase_dynamic_strength": float(best.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn)),
                "qwl_opponent_context_mix": float(best.get("qwl_opponent_context_mix", g_qwl_opp_ctx)),
            },
            "global": {
                "bayes_info_scale": float(g_b),
                "quality_k_boost": float(g_q),
                "qwl_surplus_mix": float(g_qwl),
                "qwl_throw_weight": float(g_qwl_throw),
                "qwl_comeback_weight": float(g_qwl_comeback),
                "qwl_phase_dynamic_strength": float(g_qwl_phase_dyn),
                "qwl_opponent_context_mix": float(g_qwl_opp_ctx),
            },
        }
        if not selected:
            continue
        out_bayes[lk] = float(best.get("bayes_info_scale", g_b))
        out_quality[lk] = float(best.get("quality_k_boost", g_q))
        out_qwl[lk] = float(best.get("qwl_surplus_mix", g_qwl))
        out_qwl_throw[lk] = float(best.get("qwl_throw_weight", g_qwl_throw))
        out_qwl_comeback[lk] = float(best.get("qwl_comeback_weight", g_qwl_comeback))
        out_qwl_phase_dyn[lk] = float(best.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn))
        out_qwl_opp_ctx[lk] = float(best.get("qwl_opponent_context_mix", g_qwl_opp_ctx))

    patch_candidates: List[Tuple[str, Dict[str, Any], float]] = []
    for pk, rows in by_patch.items():
        if not rows:
            continue
        n_tot = int(sum(int(x.get("n", 0)) for x in rows))
        if n_tot < int(min_n_patch):
            diag_patch[pk] = {
                "n_total": int(n_tot),
                "candidate_points": len(rows),
                "selected": False,
                "reason": "low_n",
                "global": {
                    "bayes_info_scale": float(g_b),
                    "quality_k_boost": float(g_q),
                    "qwl_surplus_mix": float(g_qwl),
                    "qwl_throw_weight": float(g_qwl_throw),
                    "qwl_comeback_weight": float(g_qwl_comeback),
                    "qwl_phase_dynamic_strength": float(g_qwl_phase_dyn),
                    "qwl_opponent_context_mix": float(g_qwl_opp_ctx),
                },
            }
            continue
        best = min(rows, key=lambda x: (float(x.get("logloss", 9.0)), float(x.get("brier", 9.0))))
        base_rows = [
            x
            for x in rows
            if abs(float(x.get("bayes_info_scale", g_b)) - g_b) < 1e-9
            and abs(float(x.get("quality_k_boost", g_q)) - g_q) < 1e-9
            and abs(float(x.get("qwl_surplus_mix", g_qwl)) - g_qwl) < 1e-9
            and abs(float(x.get("qwl_throw_weight", g_qwl_throw)) - g_qwl_throw) < 1e-9
            and abs(float(x.get("qwl_comeback_weight", g_qwl_comeback)) - g_qwl_comeback) < 1e-9
            and abs(float(x.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn)) - g_qwl_phase_dyn) < 1e-9
            and abs(float(x.get("qwl_opponent_context_mix", g_qwl_opp_ctx)) - g_qwl_opp_ctx) < 1e-9
        ]
        if not base_rows:
            diag_patch[pk] = {
                "n_total": int(n_tot),
                "candidate_points": len(rows),
                "selected": False,
                "reason": "missing_global_baseline",
                "best": {
                    "bayes_info_scale": float(best.get("bayes_info_scale", g_b)),
                    "quality_k_boost": float(best.get("quality_k_boost", g_q)),
                    "qwl_surplus_mix": float(best.get("qwl_surplus_mix", g_qwl)),
                    "qwl_throw_weight": float(best.get("qwl_throw_weight", g_qwl_throw)),
                    "qwl_comeback_weight": float(best.get("qwl_comeback_weight", g_qwl_comeback)),
                    "qwl_phase_dynamic_strength": float(best.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn)),
                    "qwl_opponent_context_mix": float(best.get("qwl_opponent_context_mix", g_qwl_opp_ctx)),
                },
                "global": {
                    "bayes_info_scale": float(g_b),
                    "quality_k_boost": float(g_q),
                    "qwl_surplus_mix": float(g_qwl),
                    "qwl_throw_weight": float(g_qwl_throw),
                    "qwl_comeback_weight": float(g_qwl_comeback),
                    "qwl_phase_dynamic_strength": float(g_qwl_phase_dyn),
                    "qwl_opponent_context_mix": float(g_qwl_opp_ctx),
                },
            }
            continue
        base = base_rows[0]
        gain = _impr(float(base.get("logloss", float("nan"))), float(best.get("logloss", float("nan"))))
        score = (float(gain) if math.isfinite(gain) else -9.0) * math.log1p(float(max(1, n_tot)))
        selected_pre = bool(math.isfinite(gain) and gain >= float(min_gain_patch))
        diag_patch[pk] = {
            "n_total": int(n_tot),
            "candidate_points": len(rows),
            "gain_logloss_best_vs_global": (float(gain) if math.isfinite(gain) else None),
            "selected_pre_topk": bool(selected_pre),
            "reason": ("ok_pre_topk" if selected_pre else "low_gain"),
            "score_for_topk": (float(score) if math.isfinite(score) else None),
            "best": {
                "bayes_info_scale": float(best.get("bayes_info_scale", g_b)),
                "quality_k_boost": float(best.get("quality_k_boost", g_q)),
                "qwl_surplus_mix": float(best.get("qwl_surplus_mix", g_qwl)),
                "qwl_throw_weight": float(best.get("qwl_throw_weight", g_qwl_throw)),
                "qwl_comeback_weight": float(best.get("qwl_comeback_weight", g_qwl_comeback)),
                "qwl_phase_dynamic_strength": float(best.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn)),
                "qwl_opponent_context_mix": float(best.get("qwl_opponent_context_mix", g_qwl_opp_ctx)),
            },
            "global": {
                "bayes_info_scale": float(g_b),
                "quality_k_boost": float(g_q),
                "qwl_surplus_mix": float(g_qwl),
                "qwl_throw_weight": float(g_qwl_throw),
                "qwl_comeback_weight": float(g_qwl_comeback),
                "qwl_phase_dynamic_strength": float(g_qwl_phase_dyn),
                "qwl_opponent_context_mix": float(g_qwl_opp_ctx),
            },
        }
        if not selected_pre:
            continue
        patch_candidates.append((str(pk), dict(best), float(score)))

    patch_candidates = sorted(patch_candidates, key=lambda t: float(t[2]), reverse=True)
    if int(patch_top_k) > 0:
        patch_candidates = patch_candidates[: int(patch_top_k)]
    for rank_idx, (pk, best, _score) in enumerate(patch_candidates, start=1):
        out_bayes_patch[pk] = float(best.get("bayes_info_scale", g_b))
        out_quality_patch[pk] = float(best.get("quality_k_boost", g_q))
        out_qwl_patch[pk] = float(best.get("qwl_surplus_mix", g_qwl))
        out_qwl_throw_patch[pk] = float(best.get("qwl_throw_weight", g_qwl_throw))
        out_qwl_comeback_patch[pk] = float(best.get("qwl_comeback_weight", g_qwl_comeback))
        out_qwl_phase_dyn_patch[pk] = float(best.get("qwl_phase_dynamic_strength", g_qwl_phase_dyn))
        out_qwl_opp_ctx_patch[pk] = float(best.get("qwl_opponent_context_mix", g_qwl_opp_ctx))
        dpk = diag_patch.setdefault(pk, {})
        dpk["selected"] = True
        dpk["selected_rank"] = int(rank_idx)
    for _pk, dpk in list(diag_patch.items()):
        if not bool(dpk.get("selected", False)):
            dpk["selected"] = False

    return {
        "bayes_info_scale_by_league": out_bayes,
        "quality_k_boost_by_league": out_quality,
        "qwl_surplus_mix_by_league": out_qwl,
        "qwl_throw_weight_by_league": out_qwl_throw,
        "qwl_comeback_weight_by_league": out_qwl_comeback,
        "qwl_phase_dynamic_strength_by_league": out_qwl_phase_dyn,
        "qwl_opponent_context_mix_by_league": out_qwl_opp_ctx,
        "bayes_info_scale_by_patch": out_bayes_patch,
        "quality_k_boost_by_patch": out_quality_patch,
        "qwl_surplus_mix_by_patch": out_qwl_patch,
        "qwl_throw_weight_by_patch": out_qwl_throw_patch,
        "qwl_comeback_weight_by_patch": out_qwl_comeback_patch,
        "qwl_phase_dynamic_strength_by_patch": out_qwl_phase_dyn_patch,
        "qwl_opponent_context_mix_by_patch": out_qwl_opp_ctx_patch,
        "diag_by_league": diag_league,
        "diag_by_patch": diag_patch,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 2B gate: auto-tune A-real probabilistic params (league/patch aware).")
    ap.add_argument("--out", default="phase2b_areal_tuning_report.json")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--speed", choices=["fast", "full"], default="fast")
    ap.add_argument("--write-params", action="store_true")
    ap.add_argument("--min-n-league", type=int, default=400)
    ap.add_argument("--min-n-patch", type=int, default=180)
    ap.add_argument("--min-gain", type=float, default=0.0005)
    ap.add_argument("--min-gain-patch", type=float, default=0.00005)
    ap.add_argument("--patch-top-k", type=int, default=8)
    args = ap.parse_args()

    csvs = _default_csvs(ROOT)
    if not csvs:
        rep = {"version": "phase2b_areal_tuning_v1", "generated_at": _utc_now(), "decision": "reject", "reasons": ["no_csvs_found"]}
        _write_json(ROOT / args.out, rep)
        print(f"OK: phase2b areal tuning -> {args.out} | decision=reject | reason=no_csvs_found")
        return 0

    if str(args.speed) == "fast":
        # Operational profile for in-app maintenance: bounded runtime.
        # Uses a compact grid (real tuning) to preserve throughput in daily flow.
        max_games_eval = 420
        grid_bayes = [1.00, 1.20]
        grid_quality = [0.22]
        grid_qwl = [0.55, 0.70]
        grid_mu_q = [0.85, 1.00]
        # Curated shortlist to keep runtime stable in app maintenance.
        candidates: List[Tuple[float, float, float, float, float, float, float, float]] = [
            (1.00, 0.22, 0.70, 1.00, 1.20, 0.65, 0.35, 0.30),  # baseline
            (1.20, 0.22, 0.70, 1.00, 1.00, 0.65, 0.35, 0.30),  # info_scale only
            (1.00, 0.22, 0.55, 1.00, 1.00, 0.65, 0.35, 0.30),  # qwl mix only
            (1.00, 0.22, 0.70, 0.85, 1.00, 0.65, 0.35, 0.30),  # mu_q only
            (1.20, 0.22, 0.70, 1.00, 1.20, 0.65, 0.35, 0.30),  # throw emphasis
            (1.20, 0.22, 0.55, 0.85, 1.20, 0.75, 0.45, 0.40),  # strong context/phase
        ]
        grid_bayes = sorted({c[0] for c in candidates})
        grid_quality = sorted({c[1] for c in candidates})
        grid_qwl = sorted({c[2] for c in candidates})
        grid_mu_q = sorted({c[3] for c in candidates})
        grid_qwl_throw = sorted({c[4] for c in candidates})
        grid_qwl_comeback = sorted({c[5] for c in candidates})
        grid_qwl_phase_dyn = sorted({c[6] for c in candidates})
        grid_qwl_opp_ctx = sorted({c[7] for c in candidates})
    else:
        max_games_eval = None
        grid_bayes = [0.60, 0.80, 1.00, 1.20, 1.50]
        grid_quality = [0.00, 0.10, 0.22, 0.32, 0.45]
        grid_qwl = [0.20, 0.40, 0.55, 0.70, 0.85]
        grid_mu_q = [0.75, 1.00, 1.25]
        qwl_profiles = [
            (0.90, 0.55, 0.20, 0.15),
            (1.00, 0.65, 0.35, 0.30),
            (1.20, 0.85, 0.50, 0.45),
        ]
        candidates = [
            (b, q, qw, mq, tw, cw, pd, oc)
            for b in grid_bayes
            for q in grid_quality
            for qw in grid_qwl
            for mq in grid_mu_q
            for (tw, cw, pd, oc) in qwl_profiles
        ]
        grid_qwl_throw = sorted({profile[0] for profile in qwl_profiles})
        grid_qwl_comeback = sorted({profile[1] for profile in qwl_profiles})
        grid_qwl_phase_dyn = sorted({profile[2] for profile in qwl_profiles})
        grid_qwl_opp_ctx = sorted({profile[3] for profile in qwl_profiles})

    csvs_eval = _select_csvs_for_speed(csvs, str(args.speed))
    results: List[Dict[str, Any]] = []
    for b, q, qwl, muq, qwl_throw, qwl_comeback, qwl_phase_dyn, qwl_opp_ctx in candidates:
        rep = build_team_state_artifact(
            [str(p) for p in csvs_eval],
            include_players_for_roster=False,
            incremental=False,
            store_processed_gameids=False,
            mu_update_mode="bayes_joint_v1",
            sigma_update_mode="bayes_logit_v1",
            bayes_info_scale=float(b),
            bayes_mu_q_strength=float(muq),
            quality_k_boost=float(q),
            qwl_surplus_mix=float(qwl),
            qwl_throw_weight=float(qwl_throw),
            qwl_comeback_weight=float(qwl_comeback),
            qwl_phase_dynamic_strength=float(qwl_phase_dyn),
            qwl_opponent_context_mix=float(qwl_opp_ctx),
            eval_track_metrics=True,
            max_games_eval=max_games_eval,
        )
        meta = (rep.get("meta") or {}) if isinstance(rep, dict) else {}
        ev = (meta.get("eval_metrics") or {}) if isinstance(meta.get("eval_metrics"), dict) else {}
        results.append(
            {
                "bayes_info_scale": float(b),
                "bayes_mu_q_strength": float(muq),
                "quality_k_boost": float(q),
                "qwl_surplus_mix": float(qwl),
                "qwl_throw_weight": float(qwl_throw),
                "qwl_comeback_weight": float(qwl_comeback),
                "qwl_phase_dynamic_strength": float(qwl_phase_dyn),
                "qwl_opponent_context_mix": float(qwl_opp_ctx),
                "n": int(_safe_f(ev.get("n"), 0.0)),
                "logloss": _safe_f(ev.get("logloss")),
                "brier": _safe_f(ev.get("brier")),
                "by_league": (ev.get("by_league") if isinstance(ev.get("by_league"), dict) else {}),
                "by_patch": (ev.get("by_patch") if isinstance(ev.get("by_patch"), dict) else {}),
            }
        )

    best_global = _pick_best(results)
    if not best_global:
        rep_out = {"version": "phase2b_areal_tuning_v1", "generated_at": _utc_now(), "decision": "reject", "reasons": ["no_results"]}
        _write_json(ROOT / args.out, rep_out)
        print(f"OK: phase2b areal tuning -> {args.out} | decision=reject | reason=no_results")
        return 0

    baseline = next(
        (
            r
            for r in results
            if abs(float(r.get("bayes_info_scale", 0.0)) - 1.0) < 1e-9
            and abs(float(r.get("bayes_mu_q_strength", 0.0)) - 1.0) < 1e-9
            and abs(float(r.get("quality_k_boost", 0.0)) - 0.22) < 1e-9
            and abs(float(r.get("qwl_surplus_mix", 0.0)) - 0.70) < 1e-9
            and abs(float(r.get("qwl_throw_weight", 0.0)) - 1.20) < 1e-9
            and abs(float(r.get("qwl_comeback_weight", 0.0)) - 0.65) < 1e-9
            and abs(float(r.get("qwl_phase_dynamic_strength", 0.0)) - 0.35) < 1e-9
            and abs(float(r.get("qwl_opponent_context_mix", 0.0)) - 0.30) < 1e-9
        ),
        {},
    )
    gain = _impr(_safe_f(baseline.get("logloss")), _safe_f(best_global.get("logloss")))
    league_maps = _coerce_maps_from_candidates(
        all_results=results,
        global_best=best_global,
        min_n_league=int(args.min_n_league),
        min_n_patch=int(args.min_n_patch),
        min_gain=float(args.min_gain),
        min_gain_patch=float(args.min_gain_patch),
        patch_top_k=int(args.patch_top_k),
    )

    decision = "promote"
    reasons: List[str] = []
    if not math.isfinite(gain) or gain < float(args.min_gain):
        decision = "shadow_only"
        reasons.append("insufficient_global_gain")

    tuning_cfg = {
        "version": "areal_prob_tuning_v1",
        "generated_at": _utc_now(),
        "speed": str(args.speed),
        "max_games_eval": (int(max_games_eval) if isinstance(max_games_eval, int) else None),
        "mu_update_mode": "bayes_joint_v1",
        "sigma_update_mode": "bayes_logit_v1",
        "global": {
            "bayes_info_scale": float(best_global.get("bayes_info_scale", 1.0)),
            "bayes_mu_q_strength": float(best_global.get("bayes_mu_q_strength", 1.0)),
            "quality_k_boost": float(best_global.get("quality_k_boost", 0.22)),
            "qwl_surplus_mix": float(best_global.get("qwl_surplus_mix", 0.70)),
            "qwl_throw_weight": float(best_global.get("qwl_throw_weight", 1.20)),
            "qwl_comeback_weight": float(best_global.get("qwl_comeback_weight", 0.65)),
            "qwl_phase_dynamic_strength": float(best_global.get("qwl_phase_dynamic_strength", 0.35)),
            "qwl_opponent_context_mix": float(best_global.get("qwl_opponent_context_mix", 0.30)),
        },
        "by_league": {
            "bayes_info_scale": dict(league_maps.get("bayes_info_scale_by_league") or {}),
            "quality_k_boost": dict(league_maps.get("quality_k_boost_by_league") or {}),
            "qwl_surplus_mix": dict(league_maps.get("qwl_surplus_mix_by_league") or {}),
            "qwl_throw_weight": dict(league_maps.get("qwl_throw_weight_by_league") or {}),
            "qwl_comeback_weight": dict(league_maps.get("qwl_comeback_weight_by_league") or {}),
            "qwl_phase_dynamic_strength": dict(league_maps.get("qwl_phase_dynamic_strength_by_league") or {}),
            "qwl_opponent_context_mix": dict(league_maps.get("qwl_opponent_context_mix_by_league") or {}),
        },
        "by_patch": {
            "bayes_info_scale": dict(league_maps.get("bayes_info_scale_by_patch") or {}),
            "quality_k_boost": dict(league_maps.get("quality_k_boost_by_patch") or {}),
            "qwl_surplus_mix": dict(league_maps.get("qwl_surplus_mix_by_patch") or {}),
            "qwl_throw_weight": dict(league_maps.get("qwl_throw_weight_by_patch") or {}),
            "qwl_comeback_weight": dict(league_maps.get("qwl_comeback_weight_by_patch") or {}),
            "qwl_phase_dynamic_strength": dict(league_maps.get("qwl_phase_dynamic_strength_by_patch") or {}),
            "qwl_opponent_context_mix": dict(league_maps.get("qwl_opponent_context_mix_by_patch") or {}),
        },
        "thresholds": {
            "min_n_league": int(args.min_n_league),
            "min_n_patch": int(args.min_n_patch),
            "min_gain": float(args.min_gain),
            "min_gain_patch": float(args.min_gain_patch),
            "patch_top_k": int(args.patch_top_k),
        },
    }

    params_path = ROOT / str(args.params)
    if bool(args.write_params) and decision == "promote":
        params = _read_json(params_path)
        params["areal_prob_tuning"] = tuning_cfg
        params["generated_at"] = _utc_now()
        _write_json(params_path, params)

    rep_out = {
        "version": "phase2b_areal_tuning_v1",
        "generated_at": _utc_now(),
        "decision": decision,
        "reasons": reasons,
        "csvs": [str(p) for p in csvs],
        "csvs_eval": [str(p) for p in csvs_eval],
        "grid": {
            "bayes_info_scale": grid_bayes,
            "bayes_mu_q_strength": grid_mu_q,
            "quality_k_boost": grid_quality,
            "qwl_surplus_mix": grid_qwl,
            "qwl_throw_weight": grid_qwl_throw,
            "qwl_comeback_weight": grid_qwl_comeback,
            "qwl_phase_dynamic_strength": grid_qwl_phase_dyn,
            "qwl_opponent_context_mix": grid_qwl_opp_ctx,
        },
        "baseline": baseline,
        "best_global": best_global,
        "gain_logloss_vs_baseline": (float(gain) if math.isfinite(gain) else None),
        "tuning_cfg": tuning_cfg,
        "results_count": len(results),
        "tuning_diagnostics": {
            "by_league": dict(league_maps.get("diag_by_league") or {}),
            "by_patch": dict(league_maps.get("diag_by_patch") or {}),
            "selected_by_league": len((league_maps.get("bayes_info_scale_by_league") or {})),
            "selected_by_patch": len((league_maps.get("bayes_info_scale_by_patch") or {})),
            "seen_by_patch": len({str(k).upper() for r in results for k in ((r.get("by_patch") or {}).keys() if isinstance(r.get("by_patch"), dict) else [])}),
        },
    }
    _write_json(ROOT / args.out, rep_out)
    print(
        "OK: phase2b areal tuning -> {} | decision={} | gain_ll={} | best(b={},q={})".format(
            args.out,
            decision,
            f"{gain:.6f}" if math.isfinite(gain) else "nan",
            float(best_global.get("bayes_info_scale", 1.0)),
            float(best_global.get("quality_k_boost", 0.22))
        )
    )
    print(
        "OK: phase2b areal tuning mu_q={}".format(
            float(best_global.get("bayes_mu_q_strength", 1.0)),
        )
    )
    print(
        "OK: phase2b areal tuning qwl_mix={}".format(
            float(best_global.get("qwl_surplus_mix", 0.70)),
        )
    )
    print(
        "OK: phase2b areal tuning qwl_extra(throw={},comeback={},phase_dyn={},opp_ctx={})".format(
            float(best_global.get("qwl_throw_weight", 1.20)),
            float(best_global.get("qwl_comeback_weight", 0.65)),
            float(best_global.get("qwl_phase_dynamic_strength", 0.35)),
            float(best_global.get("qwl_opponent_context_mix", 0.30)),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
