from __future__ import annotations

import argparse
import json
import sys
import math
import os
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.streamlit_apptest_core import (
    quiet_streamlit_bare_mode_warnings as core_quiet_streamlit_bare_mode_warnings,
    new_apptest_for_file as core_new_apptest_for_file,
    run_apptest_quiet as core_run_apptest_quiet,
)
from mlcore.artifact import MLArtifact
from tools.validate_key_matchups import _odd_for_case


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _decide(ok_count: int, fail_count: int, total: int) -> str:
    if total <= 0:
        return "shadow_only"
    if fail_count == 0:
        return "promote"
    if fail_count <= max(1, int(total * 0.2)):
        return "shadow_only"
    return "reject"


def _norm(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _pick_option(options: List[str], target: str) -> str | None:
    if target in options:
        return target
    nt = _norm(target)
    for x in options:
        if _norm(x) == nt:
            return x
    return None


def _odd_from_p(p: float) -> float:
    p = float(p)
    p = max(1e-6, min(1.0 - 1e-6, p))
    return float(1.0 / p)


def _odd_for_case_app(
    root: Path,
    team_a: str,
    team_b: str,
    market: str,
    side: str,
    timeout: int,
    *,
    csv_override: str | None = None,
    artifact_override: str | None = None,
) -> float:
    core_quiet_streamlit_bare_mode_warnings(disable_global_logging=True)

    def _ss_get(atx: Any, key: str, default: Any = None) -> Any:
        try:
            return atx.session_state[key]
        except Exception:
            return default

    try:
        pass  # type: ignore
    except Exception as e:
        raise RuntimeError(f"streamlit.testing.v1 indisponivel: {e}") from e

    at = core_new_apptest_for_file(root / "plays_app.py")

    def _run_quiet(timeout_s: int) -> None:
        core_run_apptest_quiet(at, int(timeout_s))

    csv_override_s = str(csv_override or "").strip()
    artifact_override_s = str(artifact_override or "").strip()
    if csv_override_s:
        at.session_state["cfg_auto_paths"] = False
        at.session_state["cfg_csv_override"] = csv_override_s
    if artifact_override_s:
        at.session_state["cfg_auto_paths"] = False
        at.session_state["cfg_artifact_override"] = artifact_override_s
    # Probe mode: bypass CSV bootstrap gate to keep AppTest deterministic.
    try:
        at.session_state["_probe_skip_csv_bootstrap_gate"] = True
        at.session_state["_csv_bootstrap_hold_screen"] = False
        at.session_state["_csv_bootstrap_done_fp"] = "__probe__"
    except Exception:
        pass
    _run_quiet(max(120, int(timeout)))
    if getattr(at, "exception", None):
        raise RuntimeError(f"bootstrap_exception: {at.exception[0]}")

    sels = {s.key: s for s in at.selectbox}
    # Fallback: if app is still on CSV bootstrap screen, press Continue once.
    if ("teamA" not in sels or "teamB" not in sels):
        try:
            _btn = next((b for b in at.button if str(getattr(b, "key", "") or "") == "csv_bootstrap_continue"), None)
            if _btn is not None:
                _btn.click()
                _run_quiet(max(120, int(timeout)))
                if getattr(at, "exception", None):
                    raise RuntimeError(f"post_bootstrap_exception: {at.exception[0]}")
                sels = {s.key: s for s in at.selectbox}
        except Exception as e:
            raise RuntimeError(f"csv_bootstrap_continue_failed: {e}") from e

    if "teamA" not in sels or "teamB" not in sels:
        raise RuntimeError("team_selectors_missing")
    opts_a = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
    opts_b = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
    a = _pick_option(opts_a, team_a)
    b = _pick_option(opts_b, team_b)
    if not a or not b:
        raise RuntimeError("pair_not_found_in_selectors")

    bo = 1
    mk = str(market or "").strip().lower()
    if mk == "bo3":
        bo = 3
    elif mk == "bo5":
        bo = 5

    at.session_state["teamA"] = a
    at.session_state["teamB"] = b
    at.session_state["bo"] = int(bo)
    at.session_state["flow_stage"] = "results"
    at.session_state["_analysis_force_once"] = True
    _run_quiet(max(180, int(timeout)))
    if getattr(at, "exception", None):
        raise RuntimeError(f"analysis_exception: {at.exception[0]}")

    p_map = _ss_get(at, "_p_map_used", float("nan"))
    p_series = _ss_get(at, "_p_series_used", float("nan"))
    try:
        p_map = float(p_map)
    except Exception:
        p_map = float("nan")
    try:
        p_series = float(p_series)
    except Exception:
        p_series = float("nan")

    if mk in ("map", "bo1"):
        p_a = p_map
    else:
        p_a = p_series
    if not math.isfinite(float(p_a)):
        raise RuntimeError("missing_probability_from_app")

    side_norm = str(side).strip().lower()
    if side_norm in ("a", "team_a"):
        return _odd_from_p(float(p_a))
    if side_norm in ("b", "team_b"):
        return _odd_from_p(1.0 - float(p_a))
    raise ValueError(f"side invalido: {side}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated anchor regression suite (semantic odds ranges).")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--out", default="anchor_regression_report.json")
    ap.add_argument("--mode", choices=["app", "artifact"], default="app", help="app: odds finais do pipeline do app; artifact: odds do ml_artifact cru.")
    ap.add_argument("--timeout", type=int, default=300, help="Timeout por caso quando --mode=app.")
    ap.add_argument(
        "--epsilon-odd",
        type=float,
        default=0.02,
        help="Margem absoluta de tolerancia na borda das faixas para reduzir falso negativo por jitter.",
    )
    args = ap.parse_args()

    use_artifact = str(args.mode) == "artifact"
    art = MLArtifact.load_json(str(args.artifact)) if use_artifact else None
    exp_path = Path(args.expectations)
    root = Path(__file__).resolve().parents[1]
    try:
        os.chdir(root)
    except Exception:
        pass
    data = _load_json(exp_path)
    cases_in = list(data.get("cases", []))

    rows: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    for c in cases_in:
        name = str(c.get("name", "")).strip() or f"{c.get('team_a')} vs {c.get('team_b')}"
        try:
            team_a = str(c["team_a"])
            team_b = str(c["team_b"])
            market = str(c.get("market", "bo5"))
            side = str(c.get("side", "a"))
            if use_artifact:
                odd_value = float(_odd_for_case(art, team_a, team_b, market, side))
            else:
                odd_value = float(_odd_for_case_app(root, team_a, team_b, market, side, int(args.timeout)))
            min_odd = float(c["min_odd"])
            max_odd = float(c["max_odd"])
            eps = max(0.0, float(args.epsilon_odd))
            ok = bool((min_odd - eps) <= odd_value <= (max_odd + eps))
            err = ""
        except Exception as e:
            odd_value = float("nan")
            min_odd = float(c.get("min_odd", 0.0) or 0.0)
            max_odd = float(c.get("max_odd", 0.0) or 0.0)
            ok = False
            err = str(e)
        ok_count += int(ok)
        fail_count += int(not ok)
        rows.append(
            {
                "name": name,
                "team_a": str(c.get("team_a", "")),
                "team_b": str(c.get("team_b", "")),
                "market": str(c.get("market", "")),
                "side": str(c.get("side", "")),
                "odd_value": odd_value,
                "min_odd": min_odd,
                "max_odd": max_odd,
                "ok": ok,
                "error": err,
            }
        )

    total = len(rows)
    report = {
        "version": "anchor_regression_v1",
        "artifact": str(args.artifact),
        "expectations": str(args.expectations),
        "mode": str(args.mode),
        "summary": {
            "total": total,
            "ok": ok_count,
            "fail": fail_count,
            "pass_rate": (float(ok_count) / float(total)) if total else 0.0,
        },
        "decision": _decide(ok_count, fail_count, total),
        "cases": rows,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: anchor regression saved -> {args.out} | ok={ok_count}/{total} fail={fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
