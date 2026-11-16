"""Run 10 shadow comparisons for each main league (LCK/LPL/LEC/CBLOL/LCP).

Builds pairs from ml_artifact ratings/team_meta and executes the app with AppTest.
Outputs `shadow_10_each_main_league_report.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from datetime import datetime
from pathlib import Path
from typing import Any


TARGET_LEAGUES = ["LCK", "LPL", "LEC", "CBLOL", "LCP"]


def _norm(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _odd_from_p(p: float) -> float | None:
    try:
        p = float(p)
    except Exception:
        return None
    if not math.isfinite(p):
        return None
    p = max(1e-6, min(1.0 - 1e-6, p))
    return float(1.0 / p)


def _bo5_from_map(p: float) -> float:
    p = max(1e-9, min(1.0 - 1e-9, float(p)))
    q = 1.0 - p
    return float(p**3 + 3.0 * p**3 * q + 6.0 * p**3 * (q**2))


def _ss_get(at: Any, key: str, default: Any = None) -> Any:
    try:
        return at.session_state[key]
    except Exception:
        return default


def _pick_option(options: list[str], target: str) -> str | None:
    if target in options:
        return target
    nt = _norm(target)
    for x in options:
        if _norm(x) == nt:
            return x
    return None


def _load_artifact_teams(root: Path) -> list[dict[str, Any]]:
    art = json.loads((root / "ml_artifact.json").read_text(encoding="utf-8"))
    ratings = ((art.get("model") or {}).get("ratings") or {})
    team_meta = ((art.get("model") or {}).get("team_meta") or {})
    out: list[dict[str, Any]] = []
    if not isinstance(ratings, dict) or not isinstance(team_meta, dict):
        return out
    for team, rating in ratings.items():
        meta = team_meta.get(team) or {}
        if not isinstance(meta, dict):
            continue
        lg = str(meta.get("league") or "")
        tier = str(meta.get("tier") or "")
        try:
            rt = float(rating)
        except Exception:
            continue
        out.append({"team": str(team), "league": lg, "tier": tier, "rating": rt})
    return out


def _build_pairs_for_league(rows: list[dict[str, Any]], league: str, n: int = 10) -> list[dict[str, Any]]:
    xs = [r for r in rows if str(r.get("league")) == league]
    xs.sort(key=lambda r: float(r["rating"]), reverse=True)
    if len(xs) < 4:
        return []
    m = len(xs)
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(a: str, b: str, kind: str, note: str) -> None:
        if not a or not b or a == b:
            return
        k = (a, b)
        if k in seen:
            return
        seen.add(k)
        pairs.append({"league": league, "kind": kind, "teamA": a, "teamB": b, "note": note})

    # Top vs bottom (3)
    for i in range(min(3, m // 2)):
        add(xs[i]["team"], xs[m - 1 - i]["team"], "top_bottom", f"rank#{i+1} vs rank#{m-i}")

    # Top cluster
    top_ids = list(range(min(4, m)))
    for i in range(len(top_ids)):
        for j in range(i + 1, len(top_ids)):
            add(xs[top_ids[i]]["team"], xs[top_ids[j]]["team"], "top_cluster", f"top{i+1}-top{j+1}")
            if len(pairs) >= n:
                return pairs[:n]

    # Close pairs by adjacent rating difference (prefer mid)
    adj = []
    for i in range(m - 1):
        d = abs(float(xs[i]["rating"]) - float(xs[i + 1]["rating"]))
        center_pen = abs((i + 0.5) - (m / 2.0))
        adj.append((d, center_pen, i))
    adj.sort(key=lambda t: (t[0], t[1]))
    for d, _, i in adj[: max(6, n)]:
        add(xs[i]["team"], xs[i + 1]["team"], "close", f"adj_diff={d:.2f}")
        if len(pairs) >= n:
            return pairs[:n]

    # Mid cluster
    mid = m // 2
    mids = [k for k in [mid - 2, mid - 1, mid, mid + 1, mid + 2] if 0 <= k < m]
    mids = list(dict.fromkeys(mids))
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            add(xs[mids[i]]["team"], xs[mids[j]]["team"], "mid_cluster", "mid-window")
            if len(pairs) >= n:
                return pairs[:n]

    # Fallback fill from all combinations by moderate distance
    cands = []
    for i in range(m):
        for j in range(i + 1, m):
            dist = j - i
            score = abs(dist - max(2, m // 3))
            cands.append((score, dist, i, j))
    cands.sort()
    for _, _, i, j in cands:
        add(xs[i]["team"], xs[j]["team"], "fill", "auto")
        if len(pairs) >= n:
            break
    return pairs[:n]


def _classify_result(row: dict[str, Any]) -> tuple[str, list[str]]:
    dm = abs(float(row.get("diff_pp_map", 0.0) or 0.0))
    db = abs(float(row.get("diff_pp_bo5", 0.0) or 0.0))
    kind = str(row.get("kind", ""))
    p_old = float(row.get("p_map_old", 0.5) or 0.5)
    p_new = float(row.get("p_map_shadow", 0.5) or 0.5)
    reasons: list[str] = []
    suspect = False
    if kind == "close" and dm > 4.0:
        suspect = True; reasons.append("close_move>4pp")
    if kind in {"top_bottom"} and dm > 10.0:
        suspect = True; reasons.append("topbottom_move>10pp")
    if kind in {"top_bottom"} and p_old > 0.80 and p_new < 0.72:
        suspect = True; reasons.append("favorite_collapse")
    if db > 16.0:
        suspect = True; reasons.append("bo5_move>16pp")
    return ("suspeita" if suspect else "boa"), reasons


def _run(timeout: int = 360, leagues_filter: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    teams = _load_artifact_teams(root)
    if not teams:
        print("ERRO: não consegui ler teams do ml_artifact.json")
        return 2

    # Bootstrap once to read selector options and ensure pair names exist in UI.
    try:
        from streamlit.testing.v1 import AppTest  # type: ignore
    except Exception as exc:
        print(f"ERRO: streamlit.testing.v1 indisponível ({exc})")
        return 2

    at0 = AppTest.from_file(str(root / "plays_app.py"))
    at0.run(timeout=timeout)
    if getattr(at0, "exception", None):
        print("ERRO bootstrap app:", [str(e) for e in list(at0.exception)[:2]])
        return 2
    sels0 = {s.key: s for s in at0.selectbox}
    optsA = [str(x) for x in list(getattr(sels0.get("teamA"), "options", []) or []) if str(x)]
    optsB = [str(x) for x in list(getattr(sels0.get("teamB"), "options", []) or []) if str(x)]
    optset = {_norm(x) for x in set(optsA + optsB)}

    # Filter artifact teams to those present in UI selectors.
    teams_ui = [t for t in teams if _norm(t["team"]) in optset]

    target_leagues = [str(x).upper().strip() for x in (leagues_filter or TARGET_LEAGUES) if str(x).strip()]
    selected_pairs: list[dict[str, Any]] = []
    for lg in target_leagues:
        pairs = _build_pairs_for_league(teams_ui, lg, n=10)
        selected_pairs.extend(pairs)
        print(f"{lg}: selected {len(pairs)} pairs")

    # Run all pairs
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, pair in enumerate(selected_pairs, 1):
        print(f"[{i}/{len(selected_pairs)}] {pair['league']} | {pair['teamA']} vs {pair['teamB']}")
        at = AppTest.from_file(str(root / "plays_app.py"))
        at.run(timeout=timeout)
        if getattr(at, "exception", None):
            skipped.append({"pair": pair, "reason": f"bootstrap_exception:{at.exception[0]}"})
            continue
        sels = {s.key: s for s in at.selectbox}
        if "teamA" not in sels or "teamB" not in sels:
            skipped.append({"pair": pair, "reason": "team_selectors_missing"})
            continue
        oa = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
        ob = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
        a = _pick_option(oa, str(pair["teamA"]))
        b = _pick_option(ob, str(pair["teamB"]))
        if not a or not b:
            skipped.append({"pair": pair, "reason": "pair_not_found_in_selectors"})
            continue
        at.session_state["teamA"] = a
        at.session_state["teamB"] = b
        at.session_state["bo"] = 5
        at.session_state["flow_stage"] = "results"
        at.session_state["_analysis_force_once"] = True
        at.run(timeout=max(timeout, 420))
        if getattr(at, "exception", None):
            skipped.append({"pair": pair, "reason": f"analysis_exception:{at.exception[0]}"})
            continue

        p_map_old = float(_ss_get(at, "_p_map_used", float("nan")) or float("nan"))
        p_bo5_old = float(_ss_get(at, "_p_series_used", float("nan")) or float("nan"))
        tr = _ss_get(at, "_ml_trace_last", {}) or {}
        sh = (tr.get("shadow_vnext") if isinstance(tr, dict) else {}) or {}
        p_map_shadow = float(sh.get("p_map_new", float("nan")) or float("nan"))
        p_bo5_shadow = float(sh.get("p_series_new", float("nan")) or float("nan"))
        if not math.isfinite(p_map_old) or not math.isfinite(p_map_shadow):
            skipped.append({"pair": pair, "reason": "missing_shadow_or_old_prob"})
            continue
        if not math.isfinite(p_bo5_old):
            p_bo5_old = _bo5_from_map(p_map_old)
        if not math.isfinite(p_bo5_shadow):
            p_bo5_shadow = _bo5_from_map(p_map_shadow)

        row: dict[str, Any] = {
            "league": str(pair["league"]),
            "kind": str(pair["kind"]),
            "teamA": str(pair["teamA"]),
            "teamB": str(pair["teamB"]),
            "note": str(pair.get("note", "")),
            "p_map_old": p_map_old,
            "p_map_shadow": p_map_shadow,
            "diff_pp_map": float(100.0 * (p_map_shadow - p_map_old)),
            "p_bo5_old": p_bo5_old,
            "p_bo5_shadow": p_bo5_shadow,
            "diff_pp_bo5": float(100.0 * (p_bo5_shadow - p_bo5_old)),
            "odd_map_old_A": _odd_from_p(p_map_old),
            "odd_map_old_B": _odd_from_p(1.0 - p_map_old),
            "odd_map_shadow_A": _odd_from_p(p_map_shadow),
            "odd_map_shadow_B": _odd_from_p(1.0 - p_map_shadow),
            "odd_bo5_old_A": _odd_from_p(p_bo5_old),
            "odd_bo5_old_B": _odd_from_p(1.0 - p_bo5_old),
            "odd_bo5_shadow_A": _odd_from_p(p_bo5_shadow),
            "odd_bo5_shadow_B": _odd_from_p(1.0 - p_bo5_shadow),
            "shadow_method": sh.get("method"),
            "shadow_weights": sh.get("weights"),
            "shadow_inputs": sh.get("inputs"),
        }
        cls, reasons = _classify_result(row)
        row["classification"] = cls
        row["classification_reasons"] = reasons
        results.append(row)

    # Summary
    by_league: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_league.setdefault(str(r["league"]), []).append(r)
    summary = {
        "requested": len(selected_pairs),
        "executed": len(results),
        "skipped": len(skipped),
        "classification_counts": {
            "boa": sum(1 for r in results if r.get("classification") == "boa"),
            "suspeita": sum(1 for r in results if r.get("classification") == "suspeita"),
        },
        "by_league_count": {lg: len(by_league.get(lg, [])) for lg in target_leagues},
        "by_league_abs_diff_map_pp": {
            lg: round(sum(abs(float(x["diff_pp_map"])) for x in by_league.get(lg, [])) / max(1, len(by_league.get(lg, []))), 2)
            for lg in target_leagues
        },
    }
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "selected_pairs": selected_pairs,
        "results": results,
        "skipped": skipped,
        "summary": summary,
    }
    out_path = root / "shadow_10_each_main_league_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: salvo {out_path.name}")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=360)
    ap.add_argument("--leagues", type=str, default="", help="Comma-separated subset, e.g. LPL or LCK,LPL")
    args = ap.parse_args(argv)
    leagues = [x.strip() for x in str(args.leagues or "").split(",") if x.strip()]
    return _run(timeout=max(120, int(args.timeout)), leagues_filter=leagues or None)


if __name__ == "__main__":
    raise SystemExit(main())
