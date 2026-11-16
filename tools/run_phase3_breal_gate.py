from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUALITY_TERM_KEYS = [
    "quality_objective_control_edge",
    "quality_closeout_edge",
    "quality_resilience_edge",
    "quality_net_control_edge",
    "quality_conversion_edge",
    "quality_containment_edge",
]


def _rank(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2}.get(str(dec or ""), 1)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _default_daily_csv(root: Path) -> Path | None:
    d = root / "CSV_DIARIO"
    if not d.exists():
        return None
    files = sorted([p for p in d.glob("*.csv") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _read_pair_source(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)
    cols = {str(c).lower(): str(c) for c in df.columns}
    if "league" not in cols:
        raise ValueError("missing_col:league")
    if not {"teamname", "side", "gameid"}.issubset(set(cols.keys())):
        raise ValueError("missing_cols:teamname_side_gameid")
    date_col = cols.get("date")
    game_col = cols.get("game")
    pos_col = cols.get("position")
    base = pd.DataFrame(
        {
            "league": df[cols["league"]].astype(str).fillna("").str.strip().str.upper(),
            "teamname": df[cols["teamname"]].astype(str).fillna("").str.strip(),
            "side": df[cols["side"]].astype(str).fillna("").str.strip().str.lower(),
            "gameid": df[cols["gameid"]].astype(str).fillna(""),
            "date": pd.to_datetime(df[date_col], errors="coerce") if date_col else pd.NaT,
            "game": pd.to_numeric(df[game_col], errors="coerce") if game_col else 1,
            "position": df[pos_col].astype(str).fillna("").str.strip().str.lower() if pos_col else "",
        }
    )
    if "position" in base.columns:
        base = base[base["position"].isin(["team", ""])]
    base = base[(base["teamname"] != "") & (base["gameid"] != "") & (base["league"] != "")]
    rows: List[Dict[str, Any]] = []
    for gid, g in base.groupby("gameid", dropna=False):
        gb = g[g["side"] == "blue"]
        gr = g[g["side"] == "red"]
        if gb.empty or gr.empty:
            continue
        blue = str(gb["teamname"].dropna().iloc[0]).strip()
        red = str(gr["teamname"].dropna().iloc[0]).strip()
        if not blue or not red or _norm(blue) == _norm(red):
            continue
        lg = str(gb["league"].dropna().iloc[0]).strip().upper() if not gb["league"].dropna().empty else ""
        dt = gb["date"].dropna().iloc[0] if not gb["date"].dropna().empty else pd.NaT
        gm = gb["game"].dropna().iloc[0] if not gb["game"].dropna().empty else 1
        rows.append({"league": lg, "blue": blue, "red": red, "date": dt, "game": gm, "gameid": str(gid)})
    out = pd.DataFrame(rows)
    return out.sort_values(["date"], ascending=False) if not out.empty else out


def _pick_pairs(df: pd.DataFrame, leagues: List[str], per_league: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for lg in leagues:
        dfl = df[df["league"] == str(lg).upper()]
        c = 0
        for _, r in dfl.iterrows():
            a = str(r.get("blue", "")).strip()
            b = str(r.get("red", "")).strip()
            if not a or not b:
                continue
            k = (str(lg).upper(), tuple(sorted([_norm(a), _norm(b)])))
            if k in seen:
                continue
            seen.add(k)
            out.append({"league": str(lg).upper(), "teamA": a, "teamB": b})
            c += 1
            if c >= int(per_league):
                break
    return out


def _ss_get(st: Any, key: str, default: Any = None) -> Any:
    try:
        return st[key]
    except Exception:
        return default


def _pick_opt(opts: List[str], target: str) -> str | None:
    if target in opts:
        return target
    nt = _norm(target)
    for x in opts:
        if _norm(x) == nt:
            return x
    return None


def _run_case(root: Path, team_a: str, team_b: str, timeout: int) -> Dict[str, Any]:
    from streamlit.testing.v1 import AppTest  # type: ignore

    at = AppTest.from_file(str(root / "plays_app.py"))
    at.run(timeout=max(120, int(timeout)))
    if getattr(at, "exception", None):
        return {"ok": False, "error": f"bootstrap_exception:{at.exception[0]}"}

    sels = {s.key: s for s in at.selectbox}
    if ("teamA" not in sels or "teamB" not in sels):
        try:
            btn = next((b for b in at.button if str(getattr(b, "key", "") or "") == "csv_bootstrap_continue"), None)
            if btn is not None:
                btn.click()
                at.run(timeout=max(120, int(timeout)))
                if getattr(at, "exception", None):
                    return {"ok": False, "error": f"post_bootstrap_exception:{at.exception[0]}"}
                sels = {s.key: s for s in at.selectbox}
        except Exception as e:
            return {"ok": False, "error": f"csv_bootstrap_continue_failed:{e}"}

    if "teamA" not in sels or "teamB" not in sels:
        return {"ok": False, "error": "team_selectors_missing"}

    opts_a = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
    opts_b = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
    a = _pick_opt(opts_a, team_a)
    b = _pick_opt(opts_b, team_b)
    if not a or not b:
        return {"ok": False, "error": "pair_not_found_in_selectors"}

    at.session_state["teamA"] = a
    at.session_state["teamB"] = b
    at.session_state["bo"] = 5
    at.session_state["flow_stage"] = "results"
    at.session_state["_analysis_force_once"] = True
    at.run(timeout=max(180, int(timeout)))
    if getattr(at, "exception", None):
        return {"ok": False, "error": f"analysis_exception:{at.exception[0]}"}

    tr = _ss_get(at.session_state, "_ml_trace_last", {}) or {}
    sty = tr.get("style_b_lite_live") if isinstance(tr, dict) else {}
    if not isinstance(sty, dict):
        return {"ok": False, "error": "missing_style_trace"}

    sty_terms = (((sty.get("style") or {}).get("terms")) if isinstance(sty.get("style"), dict) else {}) or {}
    q_vals: List[float] = []
    for k in QUALITY_TERM_KEYS:
        try:
            vv = float(sty_terms.get(k))
        except Exception:
            continue
        if math.isfinite(vv):
            q_vals.append(abs(vv))
    quality_signal_abs_mean = float(sum(q_vals) / len(q_vals)) if q_vals else 0.0

    dpp = sty.get("diff_pp")
    try:
        dpp = float(dpp) if dpp is not None else None
    except Exception:
        dpp = None
    mm = sty.get("model_meta") if isinstance(sty.get("model_meta"), dict) else {}
    ctx = mm.get("context_blend") if isinstance(mm.get("context_blend"), dict) else {}
    qscale = mm.get("quality_term_scale") if isinstance(mm.get("quality_term_scale"), dict) else {}
    guard = mm.get("guard") if isinstance(mm.get("guard"), dict) else {}
    try:
        quality_scale_value = float(qscale.get("scale")) if qscale.get("scale") is not None else None
    except Exception:
        quality_scale_value = None
    quality_scale_applied = bool(
        quality_scale_value is not None and math.isfinite(float(quality_scale_value)) and abs(float(quality_scale_value) - 1.0) > 1e-9
    )
    try:
        imp_l = float(mm.get("improvement_vs_lite")) if mm.get("improvement_vs_lite") is not None else None
    except Exception:
        imp_l = None
    try:
        imp_a = float(mm.get("improvement_vs_anchor")) if mm.get("improvement_vs_anchor") is not None else None
    except Exception:
        imp_a = None
    guard_thr = guard.get("thresholds") if isinstance(guard.get("thresholds"), dict) else {}
    try:
        min_imp_l = float(guard_thr.get("min_improvement_vs_lite")) if guard_thr.get("min_improvement_vs_lite") is not None else -0.003
    except Exception:
        min_imp_l = -0.003
    try:
        min_imp_a = (
            float(guard_thr.get("min_improvement_vs_anchor"))
            if guard_thr.get("min_improvement_vs_anchor") is not None
            else -0.0015
        )
    except Exception:
        min_imp_a = -0.0015
    method_s = str(sty.get("method", "") or "")
    is_b_model = bool(method_s.startswith("style_matchup_b_model"))
    return {
        "ok": True,
        "teamA": a,
        "teamB": b,
        "applied": bool(sty.get("applied", False)),
        "reason": str(sty.get("reason", "") or ""),
        "method": method_s,
        "is_b_model": bool(is_b_model),
        "diff_pp": dpp,
        "model_version": str(mm.get("version", "") or ""),
        "trained_on_n": mm.get("trained_on_n"),
        "oos_logloss": mm.get("oos_logloss"),
        "improvement_vs_lite": imp_l,
        "improvement_vs_anchor": imp_a,
        "min_improvement_vs_lite": float(min_imp_l),
        "min_improvement_vs_anchor": float(min_imp_a),
        "context_key": str(mm.get("context_key", "") or ""),
        "context_used": bool(ctx.get("used", False)),
        "context_n": ctx.get("n_ctx"),
        "context_weight": ctx.get("w_ctx_blend"),
        "fallback_from_model": bool(sty.get("fallback_from_model", False)),
        "model_guard_blocked": bool(guard.get("blocked", False)),
        "quality_signal_abs_mean": float(quality_signal_abs_mean),
        "quality_scale_applied": bool(quality_scale_applied),
        "quality_scale_value": quality_scale_value,
        "quality_scale_key": str(qscale.get("selected_key") or ""),
        "quality_scale_source": str(qscale.get("source") or ""),
    }


def _decide(rows: List[Dict[str, Any]]) -> Tuple[str, List[str], Dict[str, Any], Dict[str, Any]]:
    reasons: List[str] = []
    dec = "promote"
    ok = [r for r in rows if bool(r.get("ok"))]
    if len(ok) < 8:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("few_samples")
    applied_rate = float(sum(1 for r in ok if bool(r.get("applied"))) / len(ok)) if ok else 0.0
    if applied_rate < 0.60:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_applied_rate")
    b_model_applied_rate = float(sum(1 for r in ok if bool(r.get("is_b_model", False))) / len(ok)) if ok else 0.0
    if b_model_applied_rate < 0.40:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_b_model_applied_rate")
    d = [abs(float(r.get("diff_pp"))) for r in ok if r.get("diff_pp") is not None and math.isfinite(float(r.get("diff_pp")))]
    avg_abs = float(sum(d) / len(d)) if d else float("nan")
    p95_abs = float(pd.Series(d).quantile(0.95)) if d else float("nan")
    max_abs = float(max(d)) if d else float("nan")
    if math.isfinite(max_abs) and max_abs > 16.0:
        dec = max([dec, "reject"], key=_rank)
        reasons.append("max_abs_diff_pp_gt_16")
    if math.isfinite(p95_abs) and p95_abs > 9.0:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("p95_abs_diff_pp_gt_9")
    if math.isfinite(avg_abs) and avg_abs > 5.5:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("avg_abs_diff_pp_gt_5_5")
    context_used_rate = float(sum(1 for r in ok if bool(r.get("context_used"))) / len(ok)) if ok else 0.0
    if context_used_rate < 0.25:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_context_usage_rate")
    fallback_rate = float(sum(1 for r in ok if bool(r.get("fallback_from_model"))) / len(ok)) if ok else 0.0
    if fallback_rate > 0.70:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("high_fallback_rate")
    guard_block_rate = float(sum(1 for r in ok if bool(r.get("model_guard_blocked"))) / len(ok)) if ok else 0.0
    if guard_block_rate > 0.50:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("high_model_guard_block_rate")
    underperf_rows = []
    for r in ok:
        try:
            imp_l = float(r.get("improvement_vs_lite"))
            imp_a = float(r.get("improvement_vs_anchor"))
            min_l = float(r.get("min_improvement_vs_lite") or -0.003)
            min_a = float(r.get("min_improvement_vs_anchor") or -0.0015)
        except Exception:
            continue
        if not (math.isfinite(imp_l) and math.isfinite(imp_a)):
            continue
        underperf_rows.append(1 if (imp_l < min_l and imp_a < min_a) else 0)
    underperf_rate = (
        float(sum(underperf_rows) / len(underperf_rows)) if len(underperf_rows) > 0 else 0.0
    )
    if len(underperf_rows) >= 6 and underperf_rate > 0.40:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("high_underperforming_model_rate")
    quality_signal_rate = float(sum(1 for r in ok if float(r.get("quality_signal_abs_mean") or 0.0) > 0.01) / len(ok)) if ok else 0.0
    quality_scale_apply_rate = float(sum(1 for r in ok if bool(r.get("quality_scale_applied"))) / len(ok)) if ok else 0.0
    if quality_signal_rate < 0.65:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_quality_signal_rate")
    # If quality signal is present and scale map exists for the sampled contexts,
    # require effective application to avoid silent fallback to scale=1.0.
    scale_expected_rows = [
        r
        for r in ok
        if float(r.get("quality_signal_abs_mean") or 0.0) > 0.01
        and str(r.get("quality_scale_key") or "").strip() != ""
    ]
    scale_expected_n = len(scale_expected_rows)
    scale_expected_apply_rate = (
        float(sum(1 for r in scale_expected_rows if bool(r.get("quality_scale_applied"))) / scale_expected_n)
        if scale_expected_n > 0
        else 0.0
    )
    if scale_expected_n >= 6 and scale_expected_apply_rate < 0.60:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_quality_scale_apply_rate")

    by_league: Dict[str, Dict[str, Any]] = {}
    for r in ok:
        lg = str(r.get("league") or "").strip().upper() or "UNK"
        d = by_league.setdefault(
            lg,
            {
                "n": 0,
                "applied": 0,
                "context_used": 0,
                "fallback": 0,
                "b_model_applied": 0,
                "guard_blocked": 0,
                "q_signal_pos": 0,
                "q_scale_applied": 0,
                "underperf_rows": 0,
                "underperf_pos": 0,
                "abs_diff_vals": [],
                "q_signal_vals": [],
            },
        )
        d["n"] += 1
        if bool(r.get("applied")):
            d["applied"] += 1
        if bool(r.get("context_used")):
            d["context_used"] += 1
        if bool(r.get("fallback_from_model")):
            d["fallback"] += 1
        if bool(r.get("is_b_model", False)):
            d["b_model_applied"] += 1
        if bool(r.get("model_guard_blocked", False)):
            d["guard_blocked"] += 1
        qv = float(r.get("quality_signal_abs_mean") or 0.0)
        d["q_signal_vals"].append(qv)
        if qv > 0.01:
            d["q_signal_pos"] += 1
        if bool(r.get("quality_scale_applied")):
            d["q_scale_applied"] += 1
        try:
            dv = float(r.get("diff_pp"))
            if math.isfinite(dv):
                d["abs_diff_vals"].append(abs(dv))
        except Exception:
            pass
        try:
            imp_l = float(r.get("improvement_vs_lite"))
            imp_a = float(r.get("improvement_vs_anchor"))
            min_l = float(r.get("min_improvement_vs_lite") or -0.003)
            min_a = float(r.get("min_improvement_vs_anchor") or -0.0015)
            if math.isfinite(imp_l) and math.isfinite(imp_a):
                d["underperf_rows"] += 1
                if imp_l < min_l and imp_a < min_a:
                    d["underperf_pos"] += 1
        except Exception:
            pass

    by_league_summary: Dict[str, Dict[str, Any]] = {}
    for lg, d in by_league.items():
        n = int(d.get("n", 0) or 0)
        abs_vals = list(d.get("abs_diff_vals") or [])
        q_vals = list(d.get("q_signal_vals") or [])
        lg_summary = {
            "n": int(n),
            "applied_rate": (float(d.get("applied", 0)) / n) if n > 0 else 0.0,
            "b_model_applied_rate": (float(d.get("b_model_applied", 0)) / n) if n > 0 else 0.0,
            "context_used_rate": (float(d.get("context_used", 0)) / n) if n > 0 else 0.0,
            "fallback_rate": (float(d.get("fallback", 0)) / n) if n > 0 else 0.0,
            "guard_block_rate": (float(d.get("guard_blocked", 0)) / n) if n > 0 else 0.0,
            "quality_signal_rate": (float(d.get("q_signal_pos", 0)) / n) if n > 0 else 0.0,
            "quality_scale_apply_rate": (float(d.get("q_scale_applied", 0)) / n) if n > 0 else 0.0,
            "underperforming_rate": (
                float(d.get("underperf_pos", 0)) / float(d.get("underperf_rows", 1))
                if int(d.get("underperf_rows", 0)) > 0
                else 0.0
            ),
            "avg_abs_diff_pp": (float(sum(abs_vals) / len(abs_vals)) if abs_vals else None),
            "avg_quality_signal_abs": (float(sum(q_vals) / len(q_vals)) if q_vals else 0.0),
        }
        by_league_summary[str(lg)] = lg_summary
        ctx_rate = float(lg_summary["context_used_rate"])
        has_ctx_signal = ctx_rate >= 0.34
        if n >= 3 and has_ctx_signal and float(lg_summary["fallback_rate"]) > 0.85:
            dec = max([dec, "shadow_only"], key=_rank)
            reasons.append(f"league_high_fallback:{lg}")
        if n >= 3 and has_ctx_signal and float(lg_summary["b_model_applied_rate"]) < 0.35:
            dec = max([dec, "shadow_only"], key=_rank)
            reasons.append(f"league_low_b_model_applied:{lg}")
        if n >= 3 and float(lg_summary["guard_block_rate"]) > 0.65:
            dec = max([dec, "shadow_only"], key=_rank)
            reasons.append(f"league_high_guard_block:{lg}")
        if n >= 3 and float(lg_summary["underperforming_rate"]) > 0.60:
            dec = max([dec, "shadow_only"], key=_rank)
            reasons.append(f"league_high_underperforming:{lg}")
        if n >= 3 and lg_summary["avg_abs_diff_pp"] is not None and float(lg_summary["avg_abs_diff_pp"]) > 12.0:
            dec = max([dec, "reject"], key=_rank)
            reasons.append(f"league_max_move_high:{lg}")
        if n >= 3 and float(lg_summary["quality_signal_rate"]) < 0.5:
            dec = max([dec, "shadow_only"], key=_rank)
            reasons.append(f"league_low_quality_signal:{lg}")
        if (
            n >= 3
            and has_ctx_signal
            and float(lg_summary["quality_signal_rate"]) >= 0.5
            and float(lg_summary["quality_scale_apply_rate"]) < 0.34
        ):
            dec = max([dec, "shadow_only"], key=_rank)
            reasons.append(f"league_low_quality_scale_apply:{lg}")

    metrics = {
        "samples_total": len(rows),
        "samples_ok": len(ok),
        "samples_fail": int(len(rows) - len(ok)),
        "applied_rate": float(applied_rate),
        "b_model_applied_rate": float(b_model_applied_rate),
        "context_used_rate": float(context_used_rate),
        "fallback_rate": float(fallback_rate),
        "guard_block_rate": float(guard_block_rate),
        "underperforming_model_rate": float(underperf_rate),
        "quality_signal_rate": float(quality_signal_rate),
        "quality_scale_apply_rate": float(quality_scale_apply_rate),
        "quality_scale_expected_samples": int(scale_expected_n),
        "quality_scale_expected_apply_rate": float(scale_expected_apply_rate),
        "avg_abs_diff_pp": (avg_abs if math.isfinite(avg_abs) else None),
        "p95_abs_diff_pp": (p95_abs if math.isfinite(p95_abs) else None),
        "max_abs_diff_pp": (max_abs if math.isfinite(max_abs) else None),
    }
    return dec, reasons, metrics, by_league_summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3 gate: B-real rolling style/matchup.")
    ap.add_argument("--out", default="phase3_breal_report.json")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--pairs-per-league", type=int, default=3)
    ap.add_argument("--leagues", default="LCK,LPL,LEC,CBLOL,LCP")
    args = ap.parse_args()

    os.chdir(ROOT)
    daily = _default_daily_csv(ROOT)
    if daily is None:
        rep = {
            "version": "phase3_breal_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "decision": "reject",
            "reasons": ["daily_csv_missing"],
        }
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK: phase3 breal -> {args.out} | decision=reject | reason=daily_csv_missing")
        return 2

    src = _read_pair_source(daily)
    leagues = [x.strip().upper() for x in str(args.leagues).split(",") if x.strip()]
    pairs = _pick_pairs(src, leagues=leagues, per_league=max(1, int(args.pairs_per_league)))
    rows: List[Dict[str, Any]] = []
    for p in pairs:
        r = _run_case(ROOT, p["teamA"], p["teamB"], timeout=max(180, int(args.timeout)))
        r["league"] = p.get("league")
        rows.append(r)

    dec, reasons, metrics, by_league_metrics = _decide(rows)
    report = {
        "version": "phase3_breal_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": dec,
        "reasons": reasons,
        "daily_csv": str(daily),
        "sample_pairs": pairs,
        "rows": rows,
        "metrics": metrics,
        "by_league_metrics": by_league_metrics,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "OK: phase3 breal -> {} | decision={} | ok={}/{} | applied_rate={:.1f}% | context_rate={:.1f}% | avg_abs={}".format(
            str(args.out),
            dec,
            int(metrics.get("samples_ok", 0)),
            int(metrics.get("samples_total", 0)),
            float(metrics.get("applied_rate", 0.0)) * 100.0,
            float(metrics.get("context_used_rate", 0.0)) * 100.0,
            metrics.get("avg_abs_diff_pp"),
        )
    )
    return 0 if dec == "promote" else (1 if dec == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
