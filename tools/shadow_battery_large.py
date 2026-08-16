"""Large shadow battery runner (20+ games) using AppTest.

Builds a reproducible battery by combining:
- shadow_battery_report.json (16 cases)
- shadow_top5leagues_10_report_round2.json (10 cases; mostly overlaps)
- extra curated pairs (main leagues + interregional)

Outputs:
- shadow_battery_large_report.json
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
    if kind in {"top_bottom", "intra_top_bottom"} and dm > 10.0:
        suspect = True
        reasons.append("topbottom_move>10pp")
    if kind in {"top_bottom", "intra_top_bottom"} and p_old > 0.80 and p_new < 0.72:
        suspect = True
        reasons.append("favorite_collapse")
    if db > 16.0:
        suspect = True
        reasons.append("bo5_move>16pp")
    return ("suspeita" if suspect else "boa"), reasons


def _pick_option(options: list[str], target: str) -> str | None:
    if target in options:
        return target
    nt = _norm(target)
    for x in options:
        if _norm(x) == nt:
            return x
    return None


def _ss_get(at: Any, key: str, default: Any = None) -> Any:
    try:
        return at.session_state[key]
    except Exception:
        return default


def _load_pairs(root: Path) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    p16 = root / "shadow_battery_report.json"
    if p16.exists():
        d16 = json.loads(p16.read_text(encoding="utf-8"))
        for p in list(d16.get("pairs") or []):
            pairs.append(
                {
                    "source": "battery16",
                    "kind": str(p.get("category", "")),
                    "league": None,
                    "teamA": str(p.get("teamA", "")),
                    "teamB": str(p.get("teamB", "")),
                    "note": str(p.get("note", "")),
                }
            )
    p10 = root / "shadow_top5leagues_10_report_round2.json"
    if p10.exists():
        d10 = json.loads(p10.read_text(encoding="utf-8"))
        for p in list(d10.get("selected_pairs") or []):
            pairs.append(
                {
                    "source": "top5_10",
                    "kind": str(p.get("kind", "")),
                    "league": str(p.get("league", "")),
                    "teamA": str(p.get("teamA", "")),
                    "teamB": str(p.get("teamB", "")),
                    "note": str(p.get("note", "")),
                }
            )

    # Extra curated pool (main leagues + interregional). Missing pairs are skipped safely.
    extras = [
        ("LCK", "extra_curated", "T1", "Dplus Kia", "LCK marquee"),
        ("LCK", "extra_curated", "Hanwha Life Esports", "KT Rolster", "LCK upper-mid"),
        ("LCK", "extra_curated", "T1", "DN SOOPers", "LCK top-bottom alt"),
        ("LPL", "extra_curated", "Bilibili Gaming", "JD Gaming", "LPL elite"),
        ("LPL", "extra_curated", "Anyone's Legend", "Top Esports", "LPL close/top"),
        ("LPL", "extra_curated", "Weibo Gaming", "FunPlus Phoenix", "LPL mid"),
        ("LPL", "extra_curated", "LNG Esports", "Invictus Gaming", "LPL style clash"),
        ("LEC", "extra_curated", "G2 Esports", "Fnatic", "LEC classic"),
        ("LEC", "extra_curated", "Movistar KOI", "Karmine Corp", "LEC mid-high"),
        ("LEC", "extra_curated", "MAD Lions KOI", "SK Gaming", "LEC mid"),
        ("CBLOL", "extra_curated", "paiN Gaming", "FURIA", "CBLOL top"),
        ("CBLOL", "extra_curated", "Vivo Keyd Stars", "Fluxo W7M", "CBLOL close"),
        ("CBLOL", "extra_curated", "LOUD", "FURIA", "CBLOL legacy"),
        ("LCP", "extra_curated", "CTBC Flying Oyster", "GAM Esports", "LCP/APAC top"),
        ("LCP", "extra_curated", "DetonatioN FocusMe", "Team Secret Whales", "LCP upper"),
        ("LCP", "extra_curated", "GAM Esports", "Ground Zero Gaming", "LCP/APAC cross strength"),
        ("INTL", "interregional_extra", "Gen.G", "Bilibili Gaming", "KR vs CN elite"),
        ("INTL", "interregional_extra", "T1", "Top Esports", "KR vs CN top"),
        ("INTL", "interregional_extra", "G2 Esports", "paiN Gaming", "EMEA vs BR"),
        ("INTL", "interregional_extra", "FlyQuest", "CTBC Flying Oyster", "NA vs APAC"),
    ]
    for lg, kind, a, b, note in extras:
        pairs.append({"source": "curated_extra", "league": lg, "kind": kind, "teamA": a, "teamB": b, "note": note})

    # Deduplicate by ordered pair.
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for p in pairs:
        k = (_norm(p.get("teamA")), _norm(p.get("teamB")))
        if not k[0] or not k[1] or k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _run(timeout: int = 360) -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    pairs = _load_pairs(root)
    print(f"pairs_loaded={len(pairs)}")
    if len(pairs) < 20:
        print("ERRO: bateria <20 pares após dedupe")
        return 2

    try:
        from streamlit.testing.v1 import AppTest  # type: ignore
    except Exception as exc:
        print(f"ERRO: streamlit.testing.v1 indisponível ({exc})")
        return 2

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, pair in enumerate(pairs, 1):
        league = pair.get("league")
        kind = str(pair.get("kind", ""))
        a_req = str(pair.get("teamA", ""))
        b_req = str(pair.get("teamB", ""))
        print(f"[{i}/{len(pairs)}] {a_req} vs {b_req}")
        at = AppTest.from_file(str(root / "plays_app.py"))
        at.run(timeout=timeout)
        if getattr(at, "exception", None):
            skipped.append({"pair": pair, "reason": f"bootstrap_exception:{at.exception[0]}"})
            continue
        sels = {s.key: s for s in at.selectbox}
        if "teamA" not in sels or "teamB" not in sels:
            skipped.append({"pair": pair, "reason": "team_selectors_missing"})
            continue
        opts_a = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
        opts_b = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
        a = _pick_option(opts_a, a_req)
        b = _pick_option(opts_b, b_req)
        if not a or not b or a == b:
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
            "source": pair.get("source"),
            "league_hint": league,
            "kind": kind,
            "teamA": a_req,
            "teamB": b_req,
            "note": pair.get("note"),
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
        # Resolve actual league labels from shadow trace if available
        si = row.get("shadow_inputs") or {}
        row["league_a"] = si.get("league_a")
        row["league_b"] = si.get("league_b")
        cls, reasons = _classify(row)
        row["classification"] = cls
        row["classification_reasons"] = reasons
        results.append(row)

    by_kind: dict[str, list[dict[str, Any]]] = {}
    by_league: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_kind.setdefault(str(r.get("kind", "")), []).append(r)
        lg_key = str(r.get("league_a") or r.get("league_hint") or "UNK")
        by_league.setdefault(lg_key, []).append(r)

    summary = {
        "requested_pairs": len(pairs),
        "executed_pairs": len(results),
        "skipped_pairs": len(skipped),
        "classification_counts": {
            "boa": sum(1 for r in results if r.get("classification") == "boa"),
            "suspeita": sum(1 for r in results if r.get("classification") == "suspeita"),
        },
        "avg_abs_diff_map_pp": round(sum(abs(float(r["diff_pp_map"])) for r in results) / max(1, len(results)), 2),
        "avg_abs_diff_bo5_pp": round(sum(abs(float(r["diff_pp_bo5"])) for r in results) / max(1, len(results)), 2),
        "by_kind_abs_diff_map_pp": {
            k: round(sum(abs(float(x["diff_pp_map"])) for x in v) / max(1, len(v)), 2) for k, v in by_kind.items()
        },
        "by_league_abs_diff_map_pp": {
            k: round(sum(abs(float(x["diff_pp_map"])) for x in v) / max(1, len(v)), 2) for k, v in by_league.items()
        },
    }
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pairs": pairs,
        "results": results,
        "skipped": skipped,
        "summary": summary,
    }
    out_path = root / "shadow_battery_large_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {out_path.name} salvo")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=360)
    args = ap.parse_args(argv)
    return _run(timeout=max(120, int(args.timeout)))


if __name__ == "__main__":
    raise SystemExit(main())

