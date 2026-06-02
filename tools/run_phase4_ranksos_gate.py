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


def _rank(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2}.get(str(dec or ""), 1)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _ss_get(st: Any, key: str, default: Any = None) -> Any:
    try:
        return st[key]
    except Exception:
        return default


def _latest_daily_csv(root: Path) -> Path | None:
    d = root / "CSV_DIARIO"
    if not d.exists():
        return None
    files = sorted([p for p in d.glob("*.csv") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _read_pair_source(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)
    cols = {str(c).lower(): str(c) for c in df.columns}
    if "league" not in cols or "teamname" not in cols or "side" not in cols or "gameid" not in cols:
        raise ValueError("missing required columns league/teamname/side/gameid")
    pos_col = cols.get("position")
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
            "position": df[pos_col].astype(str).fillna("").str.strip().str.lower() if pos_col else "",
        }
    )
    if "position" in base.columns:
        base = base[base["position"].isin(["team", ""])]
    base = base[(base["league"] != "") & (base["teamname"] != "") & (base["gameid"] != "")]
    rows: List[Dict[str, Any]] = []
    for gid, g in base.groupby("gameid", dropna=False):
        gb = g[g["side"] == "blue"]
        gr = g[g["side"] == "red"]
        if gb.empty or gr.empty:
            continue
        blue = str(gb["teamname"].iloc[0]).strip()
        red = str(gr["teamname"].iloc[0]).strip()
        if not blue or not red or _norm(blue) == _norm(red):
            continue
        lg = str(gb["league"].iloc[0]).strip().upper()
        dt = gb["date"].iloc[0] if "date" in gb.columns else pd.NaT
        gm = gb["game"].iloc[0] if "game" in gb.columns else 1
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


def _pick_opt(opts: List[str], target: str) -> str | None:
    if target in opts:
        return target
    nt = _norm(target)
    for x in opts:
        if _norm(x) == nt:
            return x
    return None


def _run_case(root: Path, team_a: str, team_b: str, timeout: int = 420) -> Dict[str, Any]:
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
    rs = tr.get("league_rank_sos_live") if isinstance(tr, dict) else {}
    if not isinstance(rs, dict):
        rs = {}
    p_map = _ss_get(at.session_state, "_p_map_used", float("nan"))
    try:
        p_map = float(p_map)
    except Exception:
        p_map = float("nan")
    return {
        "ok": True,
        "teamA": a,
        "teamB": b,
        "p_map_used": (p_map if math.isfinite(p_map) else None),
        "applied": bool(rs.get("applied", False)),
        "reason": str(rs.get("reason", "") or ""),
        "method": str(rs.get("method", "") or ""),
        "same_league": bool(rs.get("same_league", False)),
        "team_a_found": bool(rs.get("team_a_found", False)),
        "team_b_found": bool(rs.get("team_b_found", False)),
        "n_games_league": rs.get("n_games_league"),
        "n_teams_league": rs.get("n_teams_league"),
        "weight": rs.get("weight"),
        "diff_pp": rs.get("diff_pp"),
        "p_before": rs.get("p_before"),
        "p_after": rs.get("p_after"),
        "p_rank": rs.get("p_rank"),
    }


def _trio_check(root: Path, timeout: int = 420) -> Dict[str, Any]:
    teams = ["S2G Esports", "Bushido Wildcats", "Misa Esports"]
    pairs = [(teams[0], teams[1]), (teams[0], teams[2]), (teams[1], teams[2])]
    rows: List[Dict[str, Any]] = []
    for a, b in pairs:
        r = _run_case(root, a, b, timeout=timeout)
        r["pair_req"] = f"{a} vs {b}"
        rows.append(r)
    ok_rows = [r for r in rows if bool(r.get("ok")) and r.get("p_map_used") is not None]
    if len(ok_rows) < 3:
        return {"available": False, "reason": "trio_unavailable_in_selector", "rows": rows}

    # Strong preference graph with threshold 55%.
    edge = []
    for r in ok_rows:
        p = float(r["p_map_used"])
        a = str(r.get("teamA", ""))
        b = str(r.get("teamB", ""))
        if p >= 0.55:
            edge.append((a, b))
        elif p <= 0.45:
            edge.append((b, a))
    # detect simple 3-cycle
    names = set()
    for u, v in edge:
        names.add(u)
        names.add(v)
    cyc = False
    e = set(edge)
    for x in names:
        for y in names:
            for z in names:
                if x != y and y != z and x != z and (x, y) in e and (y, z) in e and (z, x) in e:
                    cyc = True
    return {
        "available": True,
        "rows": ok_rows,
        "strong_edges": edge,
        "has_strong_cycle": bool(cyc),
    }


def _decide(rows: List[Dict[str, Any]], trio: Dict[str, Any]) -> Tuple[str, List[str], Dict[str, Any]]:
    dec = "promote"
    reasons: List[str] = []

    ok = [r for r in rows if bool(r.get("ok"))]
    if len(ok) < 8:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("few_samples")

    eligible = [
        r
        for r in ok
        if bool(r.get("same_league", False))
        and bool(r.get("team_a_found", False))
        and bool(r.get("team_b_found", False))
        and float(r.get("n_games_league") or 0.0) >= 40.0
    ]
    if len(eligible) < 5:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("few_eligible_samples")

    applied_rate = float(sum(1 for r in eligible if bool(r.get("applied"))) / len(eligible)) if eligible else 0.0
    if applied_rate < 0.35:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("low_applied_rate")

    d = []
    for r in eligible:
        try:
            dv = float(r.get("diff_pp"))
        except Exception:
            continue
        if math.isfinite(dv):
            d.append(abs(dv))
    avg_abs = float(sum(d) / len(d)) if d else float("nan")
    p95_abs = float(pd.Series(d).quantile(0.95)) if d else float("nan")
    max_abs = float(max(d)) if d else float("nan")

    if math.isfinite(max_abs) and max_abs > 14.0:
        dec = max([dec, "reject"], key=_rank)
        reasons.append("max_abs_diff_pp_gt_14")
    if math.isfinite(p95_abs) and p95_abs > 7.0:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("p95_abs_diff_pp_gt_7")
    if math.isfinite(avg_abs) and avg_abs > 4.5:
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("avg_abs_diff_pp_gt_4_5")

    if bool(trio.get("available")) and bool(trio.get("has_strong_cycle")):
        dec = max([dec, "shadow_only"], key=_rank)
        reasons.append("tcl_trio_strong_cycle")

    reason_counts: Dict[str, int] = {}
    for r in ok:
        rs = str(r.get("reason", "") or "")
        reason_counts[rs] = int(reason_counts.get(rs, 0) + 1)

    metrics = {
        "samples_total": len(rows),
        "samples_ok": len(ok),
        "eligible_samples": len(eligible),
        "applied_rate_eligible": float(applied_rate),
        "avg_abs_diff_pp": (avg_abs if math.isfinite(avg_abs) else None),
        "p95_abs_diff_pp": (p95_abs if math.isfinite(p95_abs) else None),
        "max_abs_diff_pp": (max_abs if math.isfinite(max_abs) else None),
        "reason_counts": reason_counts,
        "trio_available": bool(trio.get("available", False)),
        "trio_has_strong_cycle": bool(trio.get("has_strong_cycle", False)),
    }
    return dec, reasons, metrics


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 4 gate: Rank-SOS intra-league.")
    ap.add_argument("--out", default="phase4_ranksos_report.json")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--pairs-per-league", type=int, default=2)
    ap.add_argument("--leagues", default="LCK,LPL,LEC,CBLOL,LCP,TCL")
    args = ap.parse_args()

    os.chdir(ROOT)
    daily = _latest_daily_csv(ROOT)
    if daily is None:
        rep = {
            "version": "phase4_ranksos_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "decision": "reject",
            "reasons": ["daily_csv_missing"],
        }
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK: phase4 ranksos -> {args.out} | decision=reject | reason=daily_csv_missing")
        return 2

    src = _read_pair_source(daily)
    leagues = [x.strip().upper() for x in str(args.leagues).split(",") if x.strip()]
    pairs = _pick_pairs(src, leagues=leagues, per_league=max(1, int(args.pairs_per_league)))
    rows: List[Dict[str, Any]] = []
    for p in pairs:
        r = _run_case(ROOT, p["teamA"], p["teamB"], timeout=max(180, int(args.timeout)))
        r["league"] = p.get("league")
        rows.append(r)

    trio = _trio_check(ROOT, timeout=max(180, int(args.timeout)))
    dec, reasons, metrics = _decide(rows, trio)
    report = {
        "version": "phase4_ranksos_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": dec,
        "reasons": reasons,
        "daily_csv": str(daily),
        "sample_pairs": pairs,
        "rows": rows,
        "trio_tcl_check": trio,
        "metrics": metrics,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "OK: phase4 ranksos -> {} | decision={} | ok={}/{} | eligible={} | applied_rate={:.1f}% | avg_abs={}".format(
            str(args.out),
            dec,
            int(metrics.get("samples_ok", 0)),
            int(metrics.get("samples_total", 0)),
            int(metrics.get("eligible_samples", 0)),
            float(metrics.get("applied_rate_eligible", 0.0)) * 100.0,
            metrics.get("avg_abs_diff_pp"),
        )
    )
    return 0 if dec == "promote" else (1 if dec == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())

