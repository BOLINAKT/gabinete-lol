"""Rerun the fixed 10-game top5 leagues shadow battery and compare with previous report.

Usage:
    python tools/shadow_top5leagues_recheck.py --timeout 360
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _odd_from_p(p: float) -> float | None:
    try:
        p = float(p)
    except Exception:
        return None
    if not math.isfinite(p):
        return None
    p = max(1e-6, min(1.0 - 1e-6, p))
    return float(1.0 / p)


def _bo3_from_map(p: float) -> float:
    p = max(1e-9, min(1.0 - 1e-9, float(p)))
    q = 1.0 - p
    return float(p * p + 2.0 * p * p * q)


def _bo5_from_map(p: float) -> float:
    p = max(1e-9, min(1.0 - 1e-9, float(p)))
    q = 1.0 - p
    return float(p**3 + 3.0 * p**3 * q + 6.0 * p**3 * (q**2))


def _classify(row: dict[str, Any]) -> tuple[str, list[str]]:
    dm = abs(float(row.get("diff_pp_map", 0.0) or 0.0))
    db = abs(float(row.get("diff_pp_bo5", 0.0) or 0.0))
    kind = str(row.get("kind", ""))
    p_old = float(row.get("p_map_old", 0.5) or 0.5)
    p_new = float(row.get("p_map_shadow", 0.5) or 0.5)
    reasons: list[str] = []
    suspect = False
    if kind == "close" and dm > 4.0:
        suspect = True
        reasons.append("close_move>4pp")
    if kind == "top_bottom" and dm > 10.0:
        suspect = True
        reasons.append("topbottom_move>10pp")
    if kind == "top_bottom" and p_old > 0.80 and p_new < 0.72:
        suspect = True
        reasons.append("favorite_collapse")
    if db > 16.0:
        suspect = True
        reasons.append("bo5_move>16pp")
    return ("suspeita" if suspect else "boa"), reasons


def _norm(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _pick_option(options: list[str], target: str) -> str | None:
    if not options:
        return None
    if target in options:
        return target
    nt = _norm(target)
    exact = next((x for x in options if _norm(x) == nt), None)
    if exact:
        return exact
    return None


def _ss_get(at: Any, key: str, default: Any = None) -> Any:
    try:
        return at.session_state[key]
    except Exception:
        return default


def _run(timeout: int = 360) -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        import os
        os.chdir(root)
    except Exception:
        pass
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    report_in = root / "shadow_top5leagues_10_report.json"
    if not report_in.exists():
        print(f"ERRO: arquivo ausente: {report_in}")
        return 2
    prev = json.loads(report_in.read_text(encoding="utf-8"))
    pairs = list(prev.get("selected_pairs") or [])
    if not pairs:
        print("ERRO: selected_pairs vazio no relatório base")
        return 2

    prev_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in list(prev.get("results") or []):
        k = (str(r.get("league")), str(r.get("teamA")), str(r.get("teamB")))
        prev_by_key[k] = r

    try:
        from streamlit.testing.v1 import AppTest  # type: ignore
    except Exception as exc:
        print(f"ERRO: streamlit.testing.v1 indisponível ({exc})")
        return 2

    out_results: list[dict[str, Any]] = []
    for i, pair in enumerate(pairs, 1):
        league = str(pair.get("league", ""))
        team_a_req = str(pair.get("teamA", ""))
        team_b_req = str(pair.get("teamB", ""))
        kind = str(pair.get("kind", ""))
        note = str(pair.get("note", ""))

        print(f"[{i}/{len(pairs)}] {league} | {team_a_req} vs {team_b_req} ...")
        at = AppTest.from_file(str(root / "plays_app.py"))
        at.run(timeout=timeout)
        if getattr(at, "exception", None):
            print("  FAIL bootstrap:", [str(e) for e in list(at.exception)[:2]])
            continue

        sels = {s.key: s for s in at.selectbox}
        if "teamA" not in sels or "teamB" not in sels:
            print("  FAIL selectors ausentes")
            continue
        opts_a = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
        opts_b = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
        team_a = _pick_option(opts_a, team_a_req)
        team_b = _pick_option(opts_b, team_b_req)
        if not team_a or not team_b:
            print("  FAIL pair não encontrado no selectbox", {"a": team_a_req, "b": team_b_req})
            continue
        if team_a == team_b:
            print("  FAIL teams iguais após mapping")
            continue

        at.session_state["teamA"] = team_a
        at.session_state["teamB"] = team_b
        at.session_state["bo"] = 5
        at.session_state["flow_stage"] = "results"
        at.session_state["_analysis_force_once"] = True
        at.run(timeout=max(timeout, 420))
        if getattr(at, "exception", None):
            print("  FAIL run:", [str(e) for e in list(at.exception)[:2]])
            continue

        p_map_old = float(_ss_get(at, "_p_map_used", float("nan")) or float("nan"))
        p_series_old = float(_ss_get(at, "_p_series_used", float("nan")) or float("nan"))
        tr = _ss_get(at, "_ml_trace_last", {}) or {}
        sh = (tr.get("shadow_vnext") if isinstance(tr, dict) else {}) or {}
        p_map_shadow = float(sh.get("p_map_new", float("nan")) or float("nan"))
        p_series_shadow = float(sh.get("p_series_new", float("nan")) or float("nan"))
        if not math.isfinite(p_map_old) or not math.isfinite(p_map_shadow):
            print("  FAIL shadow/old ausente", {"p_old": p_map_old, "p_shadow": p_map_shadow})
            continue
        if not math.isfinite(p_series_old):
            p_series_old = _bo5_from_map(p_map_old)
        if not math.isfinite(p_series_shadow):
            p_series_shadow = _bo5_from_map(p_map_shadow)

        row: dict[str, Any] = {
            "league": league,
            "kind": kind,
            "teamA": team_a_req,
            "teamB": team_b_req,
            "note": note,
            "p_map_old": p_map_old,
            "p_map_shadow": p_map_shadow,
            "diff_pp_map": float(100.0 * (p_map_shadow - p_map_old)),
            "p_bo5_old": p_series_old,
            "p_bo5_shadow": p_series_shadow,
            "diff_pp_bo5": float(100.0 * (p_series_shadow - p_series_old)),
            "odd_map_old_A": _odd_from_p(p_map_old),
            "odd_map_old_B": _odd_from_p(1.0 - p_map_old),
            "odd_map_shadow_A": _odd_from_p(p_map_shadow),
            "odd_map_shadow_B": _odd_from_p(1.0 - p_map_shadow),
            "odd_bo5_old_A": _odd_from_p(p_series_old),
            "odd_bo5_old_B": _odd_from_p(1.0 - p_series_old),
            "odd_bo5_shadow_A": _odd_from_p(p_series_shadow),
            "odd_bo5_shadow_B": _odd_from_p(1.0 - p_series_shadow),
            "shadow_method": sh.get("method"),
            "shadow_weights": sh.get("weights"),
            "shadow_inputs": sh.get("inputs"),
        }
        cls, reasons = _classify(row)
        row["classification"] = cls
        row["classification_reasons"] = reasons

        pk = (league, team_a_req, team_b_req)
        prev_row = prev_by_key.get(pk) or {}
        if prev_row:
            row["delta_vs_prev_shadow_pp_map"] = float(row["diff_pp_map"] - float(prev_row.get("diff_pp_map", 0.0) or 0.0))
            row["delta_vs_prev_shadow_pp_bo5"] = float(row["diff_pp_bo5"] - float(prev_row.get("diff_pp_bo5", 0.0) or 0.0))
        out_results.append(row)

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_report": report_in.name,
        "selected_pairs": pairs,
        "results": out_results,
        "summary": {},
    }
    # Summary
    by_league: dict[str, list[dict[str, Any]]] = {}
    for r in out_results:
        by_league.setdefault(str(r["league"]), []).append(r)
    out["summary"]["by_league_abs_diff_map_pp"] = {
        lg: round(sum(abs(float(x["diff_pp_map"])) for x in rows) / max(1, len(rows)), 2)
        for lg, rows in by_league.items()
    }
    out["summary"]["classification_counts"] = {
        "boa": sum(1 for r in out_results if r.get("classification") == "boa"),
        "suspeita": sum(1 for r in out_results if r.get("classification") == "suspeita"),
    }
    out["summary"]["avg_abs_diff_map_pp"] = round(sum(abs(float(r["diff_pp_map"])) for r in out_results) / max(1, len(out_results)), 2)
    out["summary"]["avg_abs_diff_bo5_pp"] = round(sum(abs(float(r["diff_pp_bo5"])) for r in out_results) / max(1, len(out_results)), 2)

    out_path = root / "shadow_top5leagues_10_report_round2.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: salvo {out_path.name} ({len(out_results)} jogos)")
    print("summary:", json.dumps(out["summary"], ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=360)
    args = ap.parse_args(argv)
    return _run(timeout=max(120, int(args.timeout)))


if __name__ == "__main__":
    raise SystemExit(main())
