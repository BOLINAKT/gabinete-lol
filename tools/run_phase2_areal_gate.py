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

from mlcore.state_team_artifact import (
    build_team_state_artifact,
    load_team_state_artifact,
    save_team_state_artifact,
)


def _rank(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2}.get(str(dec or ""), 1)


def _norm_team_key(v: Any) -> str:
    s = str(v or "").strip()
    return " ".join(s.lower().split())


def _odd_from_p(p: Any) -> float | None:
    try:
        x = float(p)
    except Exception:
        return None
    if not math.isfinite(x):
        return None
    x = max(1e-6, min(1.0 - 1e-6, x))
    return float(1.0 / x)


def _default_csvs(root: Path) -> List[Path]:
    out: List[Path] = []
    d_daily = root / "CSV_DIARIO"
    d_hist = root / "CSV_HISTORICO"
    if d_hist.exists():
        out.extend(sorted([p for p in d_hist.glob("*.csv") if p.is_file()]))
    if d_daily.exists():
        out.extend(sorted([p for p in d_daily.glob("*.csv") if p.is_file()]))
    return out


def _latest_daily(root: Path) -> Path | None:
    d = root / "CSV_DIARIO"
    if not d.exists():
        return None
    files = sorted([p for p in d.glob("*.csv") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _read_games_for_pairs(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)
    cols = {str(c).lower(): str(c) for c in df.columns}
    if "league" not in cols:
        raise ValueError("missing_col:league")
    blue_col = cols.get("blue")
    red_col = cols.get("red")
    if not blue_col or not red_col:
        # Fallback for team-perspective files.
        blue_col = cols.get("team") or cols.get("teamname")
        red_col = cols.get("opponent")
    if not blue_col or not red_col:
        # Oracle Elixir canonical layout: team rows with side + teamname.
        if "teamname" in cols and "side" in cols and "gameid" in cols:
            date_col = cols.get("date")
            game_col = cols.get("game")
            base = pd.DataFrame(
                {
                    "league": df[cols["league"]].astype(str).fillna("").str.strip().str.upper(),
                    "teamname": df[cols["teamname"]].astype(str).fillna("").str.strip(),
                    "side": df[cols["side"]].astype(str).fillna("").str.strip().str.lower(),
                    "gameid": df[cols["gameid"]].astype(str).fillna(""),
                    "date": pd.to_datetime(df[date_col], errors="coerce") if date_col else pd.NaT,
                    "game": pd.to_numeric(df[game_col], errors="coerce") if game_col else 1,
                    "position": df[cols["position"]].astype(str).fillna("").str.strip().str.lower() if "position" in cols else "",
                }
            )
            if "position" in base.columns:
                b2 = base[base["position"].isin(["team", ""])].copy()
            else:
                b2 = base.copy()
            b2 = b2[(b2["teamname"] != "") & (b2["gameid"] != "")]
            by_gid = b2.groupby("gameid", dropna=False)
            rows: List[Dict[str, Any]] = []
            for gid, g in by_gid:
                gb = g[g["side"] == "blue"]
                gr = g[g["side"] == "red"]
                if gb.empty or gr.empty:
                    # Fallback: if side missing/dirty, take first two unique teams.
                    teams = [t for t in g["teamname"].dropna().astype(str).tolist() if str(t).strip()]
                    teams_u: List[str] = []
                    for t in teams:
                        if t not in teams_u:
                            teams_u.append(t)
                    if len(teams_u) < 2:
                        continue
                    blue_t, red_t = teams_u[0], teams_u[1]
                    league = str(g["league"].dropna().iloc[0]) if not g["league"].dropna().empty else ""
                    date_v = g["date"].dropna().iloc[0] if not g["date"].dropna().empty else pd.NaT
                    game_v = g["game"].dropna().iloc[0] if not g["game"].dropna().empty else 1
                else:
                    blue_t = str(gb["teamname"].dropna().iloc[0]).strip()
                    red_t = str(gr["teamname"].dropna().iloc[0]).strip()
                    league = str(gb["league"].dropna().iloc[0]) if not gb["league"].dropna().empty else (
                        str(gr["league"].dropna().iloc[0]) if not gr["league"].dropna().empty else ""
                    )
                    date_v = gb["date"].dropna().iloc[0] if not gb["date"].dropna().empty else (
                        gr["date"].dropna().iloc[0] if not gr["date"].dropna().empty else pd.NaT
                    )
                    game_v = gb["game"].dropna().iloc[0] if not gb["game"].dropna().empty else (
                        gr["game"].dropna().iloc[0] if not gr["game"].dropna().empty else 1
                    )
                if not blue_t or not red_t or blue_t == red_t:
                    continue
                rows.append(
                    {
                        "league": str(league).strip().upper(),
                        "blue": str(blue_t).strip(),
                        "red": str(red_t).strip(),
                        "date": date_v,
                        "gameid": str(gid),
                        "game": game_v,
                    }
                )
            out = pd.DataFrame(rows)
            if out.empty:
                raise ValueError("no_pairs_from_teamname_side_gameid")
            out = out[(out["blue"] != "") & (out["red"] != "") & (out["league"] != "")]
            return out
        raise ValueError("missing_cols:blue_red_or_team_opponent_or_teamname_side_gameid")
    date_col = cols.get("date")
    gid_col = cols.get("gameid")
    game_col = cols.get("game")
    out = pd.DataFrame(
        {
            "league": df[cols["league"]].astype(str).fillna("").str.strip().str.upper(),
            "blue": df[blue_col].astype(str).fillna("").str.strip(),
            "red": df[red_col].astype(str).fillna("").str.strip(),
            "date": pd.to_datetime(df[date_col], errors="coerce") if date_col else pd.NaT,
            "gameid": df[gid_col].astype(str).fillna("") if gid_col else "",
            "game": pd.to_numeric(df[game_col], errors="coerce") if game_col else 1,
        }
    )
    out = out[(out["blue"] != "") & (out["red"] != "")]
    out = out[(out["blue"] != out["red"])]
    out = out[out["league"] != ""]
    return out


def _pick_pairs(df: pd.DataFrame, leagues: List[str], per_league: int) -> List[Dict[str, str]]:
    pairs: List[Dict[str, str]] = []
    if df.empty:
        return pairs
    df = df.copy()
    if "date" in df.columns:
        df = df.sort_values(["date"], ascending=False)
    seen = set()
    for lg in leagues:
        dfl = df[df["league"] == str(lg).upper()].copy()
        if dfl.empty:
            continue
        cnt = 0
        for _, r in dfl.iterrows():
            a = str(r.get("blue", "")).strip()
            b = str(r.get("red", "")).strip()
            if not a or not b or a == b:
                continue
            key = (str(lg).upper(), tuple(sorted([_norm_team_key(a), _norm_team_key(b)])))
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"league": str(lg).upper(), "teamA": a, "teamB": b})
            cnt += 1
            if cnt >= int(per_league):
                break
    return pairs


def _ss_get(at: Any, key: str, default: Any = None) -> Any:
    try:
        return at.session_state[key]
    except Exception:
        return default


def _pick_option(options: List[str], target: str) -> str | None:
    if target in options:
        return target
    nt = _norm_team_key(target)
    for x in options:
        if _norm_team_key(x) == nt:
            return x
    return None


def _run_shadow_pair(root: Path, team_a: str, team_b: str, timeout: int = 360) -> Dict[str, Any]:
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
    a = _pick_option(opts_a, team_a)
    b = _pick_option(opts_b, team_b)
    if not a or not b:
        return {"ok": False, "error": "pair_not_found_in_selectors"}
    if _norm_team_key(a) == _norm_team_key(b):
        return {"ok": False, "error": "same_team_after_mapping"}

    at.session_state["teamA"] = a
    at.session_state["teamB"] = b
    at.session_state["bo"] = 5
    at.session_state["flow_stage"] = "results"
    at.session_state["_analysis_force_once"] = True
    at.run(timeout=max(180, int(timeout)))
    if getattr(at, "exception", None):
        return {"ok": False, "error": f"analysis_exception:{at.exception[0]}"}

    p_old = float(_ss_get(at, "_p_map_used", float("nan")) or float("nan"))
    p_old_s = float(_ss_get(at, "_p_series_used", float("nan")) or float("nan"))
    tr = _ss_get(at, "_ml_trace_last", {}) or {}
    # A-real shadow trace lives at top-level key in current pipeline.
    sa = tr.get("shadow_state_areal") if isinstance(tr, dict) else {}
    if not isinstance(sa, dict):
        sa = {}
    p_new = float(sa.get("p_map_new", float("nan")) or float("nan"))
    p_new_s = float(sa.get("p_series_new", float("nan")) or float("nan"))
    if not math.isfinite(p_old) or not math.isfinite(p_new):
        return {"ok": False, "error": "missing_probabilities"}
    dpp = float(100.0 * (p_new - p_old))
    dpp_s = float(100.0 * (p_new_s - p_old_s)) if math.isfinite(p_new_s) and math.isfinite(p_old_s) else None
    return {
        "ok": True,
        "teamA": a,
        "teamB": b,
        "p_map_old": p_old,
        "p_map_new": p_new,
        "diff_pp_map": dpp,
        "p_series_old": p_old_s if math.isfinite(p_old_s) else None,
        "p_series_new": p_new_s if math.isfinite(p_new_s) else None,
        "diff_pp_series": dpp_s,
        "odd_old_A": _odd_from_p(p_old),
        "odd_new_A": _odd_from_p(p_new),
        "applied": bool(sa.get("applied", False)),
        "reason": str(sa.get("reason", "") or ""),
        "method": str(sa.get("method", "") or ""),
    }


def _build_state_artifact(root: Path, csvs: List[Path]) -> Tuple[Dict[str, Any], Path]:
    out_path = root / "team_state_artifact.json"
    seed = None
    try:
        if out_path.exists():
            seed = load_team_state_artifact(out_path)
    except Exception:
        seed = None
    rep = build_team_state_artifact(
        [str(p) for p in csvs],
        include_players_for_roster=True,
        seed_artifact=(seed if isinstance(seed, dict) and seed else None),
        incremental=True,
    )
    if isinstance(rep, dict) and not rep.get("error"):
        save_team_state_artifact(out_path, rep)
    return rep if isinstance(rep, dict) else {}, out_path


def _decision(rep_state: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[str, List[str], Dict[str, Any]]:
    reasons: List[str] = []
    dec = "promote"
    if not isinstance(rep_state, dict) or rep_state.get("error"):
        return "reject", ["state_artifact_error"], {}

    meta = rep_state.get("meta") if isinstance(rep_state.get("meta"), dict) else {}
    upd = str(meta.get("update_mode") or "")
    if not upd:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("missing_update_mode")

    ok_rows = [r for r in rows if bool(r.get("ok"))]
    if len(ok_rows) < 6:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("few_shadow_samples")

    abs_d = [abs(float(r.get("diff_pp_map", 0.0) or 0.0)) for r in ok_rows]
    applied_rate = (
        float(sum(1 for r in ok_rows if bool(r.get("applied")))) / float(len(ok_rows))
        if ok_rows
        else 0.0
    )
    avg_abs = float(sum(abs_d) / len(abs_d)) if abs_d else float("nan")
    p95_abs = float(pd.Series(abs_d).quantile(0.95)) if abs_d else float("nan")
    max_abs = float(max(abs_d)) if abs_d else float("nan")

    if math.isfinite(max_abs) and max_abs > 18.0:
        dec = max([dec, "reject"], key=_rank)
        reasons.append("max_abs_diff_pp_gt_18")
    if math.isfinite(p95_abs) and p95_abs > 10.0:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("p95_abs_diff_pp_gt_10")
    if math.isfinite(avg_abs) and avg_abs > 6.0:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("avg_abs_diff_pp_gt_6")
    if applied_rate < 0.60:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_areal_applied_rate")
    q_signal_n = int(meta.get("quality_signal_used_games") or 0)
    q_adj_n = int(meta.get("quality_adjust_used_games") or 0)
    q_throw_n = int(meta.get("quality_throw_used_games") or 0)
    q_comeback_n = int(meta.get("quality_comeback_used_games") or 0)
    try:
        q_adj_avg = float(meta.get("quality_adjust_avg"))
    except Exception:
        q_adj_avg = float("nan")
    try:
        q_early_avg = float(meta.get("quality_early_avg"))
    except Exception:
        q_early_avg = float("nan")
    try:
        q_obj_avg = float(meta.get("quality_objective_avg"))
    except Exception:
        q_obj_avg = float("nan")
    try:
        q_kill_avg = float(meta.get("quality_kill_avg"))
    except Exception:
        q_kill_avg = float("nan")
    if q_signal_n >= 8 and q_adj_n <= 0:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("missing_qwl_adjust_usage")
    if q_signal_n >= 8 and (not math.isfinite(q_early_avg) or not math.isfinite(q_obj_avg) or not math.isfinite(q_kill_avg)):
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("missing_qwl_causal_breakdown")

    metrics = {
        "samples_total": len(rows),
        "samples_ok": len(ok_rows),
        "samples_fail": int(len(rows) - len(ok_rows)),
        "applied_rate": float(applied_rate),
        "avg_abs_diff_pp_map": (avg_abs if math.isfinite(avg_abs) else None),
        "p95_abs_diff_pp_map": (p95_abs if math.isfinite(p95_abs) else None),
        "max_abs_diff_pp_map": (max_abs if math.isfinite(max_abs) else None),
        "update_mode": upd,
        "backfill_detected": bool(meta.get("backfill_detected", False)),
        "incremental_fastpath": bool(meta.get("incremental_fastpath", False)),
        "patch_mu_recenter_events": int(meta.get("patch_mu_recenter_events") or 0),
        "roster_mu_recenter_events": int(meta.get("roster_mu_recenter_events") or 0),
        "league_switch_recenter_events": int(meta.get("league_switch_recenter_events") or 0),
        "roster_hard_reset_events": int(meta.get("roster_hard_reset_events") or 0),
        "quality_signal_used_games": int(q_signal_n),
        "quality_adjust_used_games": int(q_adj_n),
        "quality_adjust_surplus_games": int(meta.get("quality_adjust_surplus_games") or 0),
        "quality_adjust_avg": (q_adj_avg if math.isfinite(q_adj_avg) else None),
        "quality_throw_used_games": int(q_throw_n),
        "quality_comeback_used_games": int(q_comeback_n),
        "quality_early_avg": (q_early_avg if math.isfinite(q_early_avg) else None),
        "quality_objective_avg": (q_obj_avg if math.isfinite(q_obj_avg) else None),
        "quality_kill_avg": (q_kill_avg if math.isfinite(q_kill_avg) else None),
    }
    return dec, reasons, metrics


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 2 gate: A-real incremental + shadow stability.")
    ap.add_argument("--out", default="phase2_areal_report.json")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--pairs-per-league", type=int, default=2)
    ap.add_argument(
        "--leagues",
        default="LCK,LPL,LEC,CBLOL,LCP",
        help="Comma-separated major leagues for phase2 stability sample.",
    )
    args = ap.parse_args()

    os.chdir(ROOT)
    csvs = _default_csvs(ROOT)
    if not csvs:
        rep = {
            "version": "phase2_areal_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "decision": "reject",
            "reasons": ["no_csvs_found"],
        }
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK: phase2 areal -> {args.out} | decision=reject | reason=no_csvs_found")
        return 2

    rep_state, out_state_path = _build_state_artifact(ROOT, csvs)
    daily = _latest_daily(ROOT)
    pair_rows: List[Dict[str, Any]] = []
    sample_pairs: List[Dict[str, str]] = []
    if daily is not None:
        try:
            gdf = _read_games_for_pairs(daily)
            leagues = [x.strip().upper() for x in str(args.leagues).split(",") if x.strip()]
            sample_pairs = _pick_pairs(gdf, leagues=leagues, per_league=max(1, int(args.pairs_per_league)))
            for p in sample_pairs:
                row = _run_shadow_pair(ROOT, p["teamA"], p["teamB"], timeout=max(180, int(args.timeout)))
                row["league"] = p.get("league")
                pair_rows.append(row)
        except Exception as e:
            pair_rows.append({"ok": False, "error": f"pair_sampling_exception:{type(e).__name__}:{e}"})

    dec, reasons, metrics = _decision(rep_state, pair_rows)

    report = {
        "version": "phase2_areal_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": dec,
        "reasons": reasons,
        "state_artifact_path": str(out_state_path),
        "state_artifact_report": rep_state,
        "daily_csv": (str(daily) if daily else None),
        "sample_pairs": sample_pairs,
        "shadow_rows": pair_rows,
        "metrics": metrics,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "OK: phase2 areal -> {} | decision={} | ok={}/{} | applied_rate={:.1f}% | avg_abs={}".format(
            str(args.out),
            dec,
            int(metrics.get("samples_ok", 0)),
            int(metrics.get("samples_total", 0)),
            float(metrics.get("applied_rate", 0.0)) * 100.0,
            metrics.get("avg_abs_diff_pp_map"),
        )
    )
    return 0 if dec == "promote" else (1 if dec == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
