from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rank(dec: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2}.get(str(dec or ""), 1)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _safe_float(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else float(default)
    except Exception:
        return float(default)


def _clip_prob(v: float, eps: float = 1e-9) -> float:
    x = _safe_float(v, 0.5)
    return float(max(float(eps), min(1.0 - float(eps), x)))


def _safe_logit(p: float) -> float:
    x = _clip_prob(p)
    return float(math.log(x / (1.0 - x)))


def _safe_sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return float(1.0 / (1.0 + ez))
    ez = math.exp(z)
    return float(ez / (1.0 + ez))


def _logloss(y: int, p: float) -> float:
    pp = _clip_prob(p)
    yy = 1 if int(y) == 1 else 0
    return float(-(yy * math.log(pp) + (1 - yy) * math.log(1.0 - pp)))


def _default_profiles() -> Dict[str, Dict[str, float]]:
    return {
        "top": {
            "strength_scale": 0.35,
            "prior_scale": 0.70,
            "max_shrink_scale": 0.55,
            "cap_shift": +0.06,
            "soft_shift": +10.0,
            "hard_shift": +8.0,
            "gate_score": 80.0,
            "gate_n_eff": 30.0,
        },
        "core": {
            "strength_scale": 0.75,
            "prior_scale": 0.95,
            "max_shrink_scale": 0.85,
            "cap_shift": +0.02,
            "soft_shift": +3.0,
            "hard_shift": +2.0,
            "gate_score": 84.0,
            "gate_n_eff": 42.0,
        },
        "edge": {
            "strength_scale": 1.15,
            "prior_scale": 1.20,
            "max_shrink_scale": 1.05,
            "cap_shift": -0.04,
            "soft_shift": -6.0,
            "hard_shift": -4.0,
            "gate_score": 88.0,
            "gate_n_eff": 55.0,
        },
    }


def _sanitize_profiles(raw: Any) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    base = _default_profiles()
    if not isinstance(raw, dict):
        return out
    for b in ("top", "core", "edge"):
        rv = raw.get(b)
        if not isinstance(rv, dict):
            continue
        row: Dict[str, float] = {}
        for k in base[b].keys():
            if k not in rv:
                continue
            fv = _safe_float(rv.get(k))
            if math.isfinite(fv):
                row[k] = float(fv)
        if row:
            out[b] = row
    return out


def _merge_profiles(overrides: Dict[str, Dict[str, float]] | None) -> Dict[str, Dict[str, float]]:
    base = _default_profiles()
    ov = _sanitize_profiles(overrides or {})
    out: Dict[str, Dict[str, float]] = {}
    for b in ("top", "core", "edge"):
        row = dict(base[b])
        if b in ov:
            row.update(dict(ov[b]))
        out[b] = row
    return out


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}
    return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_daily_csv(root: Path) -> Path | None:
    d = root / "CSV_DIARIO"
    if not d.exists():
        return None
    files = sorted([p for p in d.glob("*.csv") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _read_pair_source(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)
    cols = {str(c).lower(): str(c) for c in df.columns}
    required = {"league", "teamname", "side", "gameid"}
    if not required.issubset(set(cols.keys())):
        miss = ",".join(sorted(list(required - set(cols.keys()))))
        raise ValueError(f"missing required cols: {miss}")
    result_col = cols.get("result")
    winner_col = cols.get("winner")
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
            "result": pd.to_numeric(df[result_col], errors="coerce") if result_col else float("nan"),
            "winner": df[winner_col].astype(str).fillna("").str.strip() if winner_col else "",
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

        blue_win: int | None = None
        if "result" in gb.columns:
            rb = _safe_float(gb["result"].iloc[0])
            if math.isfinite(rb):
                blue_win = 1 if rb >= 0.5 else 0
        if blue_win is None and "winner" in gb.columns:
            wb = str(gb["winner"].iloc[0]).strip().lower()
            if wb in {"blue", "b"}:
                blue_win = 1
            elif wb in {"red", "r"}:
                blue_win = 0
        if blue_win is None:
            continue

        rows.append(
            {
                "league": lg,
                "blue": blue,
                "red": red,
                "date": dt,
                "game": gm,
                "gameid": str(gid),
                "blue_win": int(blue_win),
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values(["date"], ascending=False) if not out.empty else out


def _pick_cases(
    df: pd.DataFrame,
    leagues: List[str],
    per_league: int,
    *,
    seen_gameids: set[str] | None = None,
    max_total: int = 0,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    seen_gid = set(seen_gameids or set())
    for lg in leagues:
        dfl = df[df["league"] == str(lg).upper()]
        c = 0
        for _, r in dfl.iterrows():
            a = str(r.get("blue", "")).strip()
            b = str(r.get("red", "")).strip()
            if not a or not b:
                continue
            gid = str(r.get("gameid", ""))
            if gid and gid in seen_gid:
                continue
            key = (str(lg).upper(), gid)
            if key in seen:
                continue
            seen.add(key)
            if gid:
                seen_gid.add(gid)
            out.append(
                {
                    "league": str(lg).upper(),
                    "teamA": a,
                    "teamB": b,
                    "gameid": gid,
                    "blue_win": int(r.get("blue_win") or 0),
                }
            )
            if int(max_total or 0) > 0 and len(out) >= int(max_total):
                return out
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


def _session_get(session_state: Any, key: str, default: Any = None) -> Any:
    try:
        if key in session_state:
            return session_state[key]
    except Exception:
        pass
    try:
        return session_state[key]
    except Exception:
        return default


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
    at.session_state["bo"] = 1
    at.session_state["flow_stage"] = "results"
    at.session_state["_analysis_force_once"] = True
    at.session_state["ml_marginal_trust_enabled"] = True
    at.session_state["ml_marginal_trust_band_tuning"] = True
    at.session_state["ml_marginal_trust_exclude_leagues"] = ""
    at.run(timeout=max(180, int(timeout)))
    if getattr(at, "exception", None):
        return {"ok": False, "error": f"analysis_exception:{at.exception[0]}"}

    tr = _session_get(at.session_state, "_ml_trace_last", {}) or {}
    mt = tr.get("marginal_trust_guard") if isinstance(tr, dict) else {}
    if not isinstance(mt, dict):
        return {"ok": False, "error": "missing_marginal_trace"}

    p_in = _safe_float(mt.get("p_in"))
    p_out = _safe_float(mt.get("p_out"))
    if not math.isfinite(p_in):
        return {"ok": False, "error": "missing_p_in"}
    if not math.isfinite(p_out):
        p_out = p_in

    return {
        "ok": True,
        "teamA": a,
        "teamB": b,
        "p_in": float(_clip_prob(p_in)),
        "p_out_live": float(_clip_prob(p_out)),
        "band": str(mt.get("band", "") or "edge").strip().lower() or "edge",
        "league": str(mt.get("league", "") or ""),
        "tier": str(mt.get("tier", "") or ""),
        "confidence_score": _safe_float(mt.get("confidence_score"), 50.0),
        "n_eff": max(0.0, _safe_float(mt.get("n_eff"), 0.0)),
        "reason": str(mt.get("reason", "") or ""),
        "applied_live": bool(mt.get("applied", False)),
        "gate_score": _safe_float(mt.get("gate_score"), float("nan")),
        "gate_n_eff": _safe_float(mt.get("gate_n_eff"), float("nan")),
    }


def _global_params_from_file(path: Path) -> Dict[str, Any]:
    d = _read_json(path)
    return {
        "enabled": bool(d.get("ml_marginal_trust_enabled", True)),
        "strength": float(_safe_float(d.get("ml_marginal_trust_strength"), 0.70)),
        "prior_games": float(max(1.0, _safe_float(d.get("ml_marginal_trust_prior_games"), 28.0))),
        "max_shrink": float(max(0.0, min(0.95, _safe_float(d.get("ml_marginal_trust_max_shrink"), 0.72)))),
        "cap_prob": float(max(0.55, min(0.95, _safe_float(d.get("ml_marginal_trust_cap_prob"), 0.84)))),
        "score_soft": float(max(1.0, min(100.0, _safe_float(d.get("ml_marginal_trust_score_soft"), 68.0)))),
        "score_hard": float(max(0.0, min(99.0, _safe_float(d.get("ml_marginal_trust_score_hard"), 46.0)))),
        "band_tuning": bool(d.get("ml_marginal_trust_band_tuning", True)),
        "band_coeffs": _sanitize_profiles(d.get("ml_marginal_trust_band_coeffs", {})),
    }


def _apply_profile_to_sample(sample: Dict[str, Any], params: Dict[str, Any], profiles: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    p0 = _clip_prob(_safe_float(sample.get("p_in"), 0.5))
    n_eff = max(0.0, _safe_float(sample.get("n_eff"), 0.0))
    cs = max(0.0, min(100.0, _safe_float(sample.get("confidence_score"), 50.0)))
    band = str(sample.get("band", "edge") or "edge").strip().lower()
    if band not in {"top", "core", "edge"}:
        band = "edge"
    prof = dict((profiles or {}).get(band) or _default_profiles().get(band) or _default_profiles()["edge"])

    pg = float(max(1.0, _safe_float(params.get("prior_games"), 28.0)))
    s = float(max(0.0, min(1.0, _safe_float(params.get("strength"), 0.70))))
    cap_shrink = float(max(0.0, min(0.95, _safe_float(params.get("max_shrink"), 0.72))))
    cap_hi_in = float(max(0.55, min(0.95, _safe_float(params.get("cap_prob"), 0.84))))
    sc_soft = float(max(1.0, min(100.0, _safe_float(params.get("score_soft"), 68.0))))
    sc_hard = float(max(0.0, min(99.0, _safe_float(params.get("score_hard"), 46.0))))

    gate_score = _safe_float(prof.get("gate_score"), 85.0)
    gate_n_eff = _safe_float(prof.get("gate_n_eff"), 40.0)
    if bool(params.get("band_tuning", True)):
        s = float(max(0.0, min(1.0, s * _safe_float(prof.get("strength_scale"), 1.0))))
        pg = float(max(1.0, pg * _safe_float(prof.get("prior_scale"), 1.0)))
        cap_shrink = float(max(0.0, min(0.95, cap_shrink * _safe_float(prof.get("max_shrink_scale"), 1.0))))
        cap_hi_in = float(max(0.55, min(0.95, cap_hi_in + _safe_float(prof.get("cap_shift"), 0.0))))
        sc_soft = float(max(1.0, min(100.0, sc_soft + _safe_float(prof.get("soft_shift"), 0.0))))
        sc_hard = float(max(0.0, min(99.0, sc_hard + _safe_float(prof.get("hard_shift"), 0.0))))

    if sc_soft <= (sc_hard + 1.0):
        sc_soft = float(min(100.0, sc_hard + 1.0))

    if (band in {"top", "core"}) and (cs >= gate_score) and (n_eff >= gate_n_eff):
        return {
            "p": float(p0),
            "gate": 1.0,
            "shrink": 0.0,
            "weak": 0.0,
            "cap_hi": cap_hi_in,
            "band": band,
        }

    conf_weak = float((sc_soft - cs) / max(1e-9, (sc_soft - sc_hard)))
    conf_weak = float(max(0.0, min(1.0, conf_weak)))
    evidence_weak = float(pg / (n_eff + pg))
    evidence_weak = float(max(0.0, min(1.0, evidence_weak)))
    weak = float(max(0.0, min(1.0, 0.60 * conf_weak + 0.40 * evidence_weak)))

    shrink = float(min(cap_shrink, s * weak))
    w_keep = float(max(0.0, min(1.0, 1.0 - shrink)))
    z0 = float(_safe_logit(p0))
    z1 = float(w_keep * z0)
    p1 = float(_clip_prob(_safe_sigmoid(z1)))

    cap_hi_dyn = float(cap_hi_in - (0.12 * weak))
    cap_hi = float(max(0.55, min(cap_hi_in, cap_hi_dyn)))
    cap_lo = float(1.0 - cap_hi)
    p2 = float(max(cap_lo, min(cap_hi, p1)))
    return {
        "p": float(_clip_prob(p2)),
        "gate": 0.0,
        "shrink": float(shrink),
        "weak": float(weak),
        "cap_hi": float(cap_hi),
        "band": band,
    }


def _evaluate_profiles(
    samples: List[Dict[str, Any]],
    params: Dict[str, Any],
    profiles: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    band_w = {"edge": 1.00, "core": 0.70, "top": 0.35}
    sum_w = 0.0
    sum_ll = 0.0
    by_band: Dict[str, Dict[str, Any]] = {
        "top": {"n": 0, "ll": 0.0, "w": 0.0, "sum_abs_shift_pp": 0.0},
        "core": {"n": 0, "ll": 0.0, "w": 0.0, "sum_abs_shift_pp": 0.0},
        "edge": {"n": 0, "ll": 0.0, "w": 0.0, "sum_abs_shift_pp": 0.0},
    }
    rows_eval = 0
    for s in samples:
        y = int(s.get("y", 0))
        p_in = float(_clip_prob(_safe_float(s.get("p_in"), 0.5)))
        ap = _apply_profile_to_sample(s, params, profiles)
        p = float(_clip_prob(ap.get("p", 0.5)))
        b = str(ap.get("band", "edge"))
        if b not in by_band:
            b = "edge"
        w = float(band_w.get(b, 1.0))
        ll = float(_logloss(y, p))
        sum_ll += (w * ll)
        sum_w += w
        rows_eval += 1
        by_band[b]["n"] = int(by_band[b]["n"] + 1)
        by_band[b]["ll"] = float(by_band[b]["ll"] + ll)
        by_band[b]["w"] = float(by_band[b]["w"] + w)
        by_band[b]["sum_abs_shift_pp"] = float(by_band[b]["sum_abs_shift_pp"] + abs(p - p_in) * 100.0)
    out_bands: Dict[str, Dict[str, Any]] = {}
    for b, d in by_band.items():
        n = int(d.get("n", 0))
        out_bands[b] = {
            "n": n,
            "logloss_mean": (float(d.get("ll", 0.0)) / n) if n > 0 else None,
            "avg_abs_shift_pp": (float(d.get("sum_abs_shift_pp", 0.0)) / n) if n > 0 else None,
        }
    return {
        "rows_eval": int(rows_eval),
        "weighted_logloss": (float(sum_ll / sum_w) if sum_w > 0 else None),
        "by_band": out_bands,
    }


def _candidate_profiles(speed: str, base: Dict[str, Dict[str, float]]) -> List[Dict[str, Dict[str, float]]]:
    prof0 = _merge_profiles(base)
    if str(speed) == "fast":
        top_strength = [0.85, 1.00, 1.15]
        core_strength = [0.90, 1.00, 1.10]
        edge_strength = [0.90, 1.00, 1.10, 1.20]
        edge_prior = [0.90, 1.00, 1.10]
        top_cap_delta = [-0.01, 0.0, +0.01]
        core_cap_delta = [-0.02, 0.0, +0.02]
        edge_cap_delta = [-0.02, 0.0, +0.02]
    else:
        top_strength = [0.75, 0.90, 1.00, 1.10, 1.25]
        core_strength = [0.80, 0.90, 1.00, 1.10, 1.20]
        edge_strength = [0.80, 0.95, 1.00, 1.10, 1.20, 1.30]
        edge_prior = [0.80, 0.90, 1.00, 1.10, 1.20]
        top_cap_delta = [-0.02, -0.01, 0.0, +0.01, +0.02]
        core_cap_delta = [-0.03, -0.02, 0.0, +0.02, +0.03]
        edge_cap_delta = [-0.04, -0.02, 0.0, +0.02, +0.04]

    out: List[Dict[str, Dict[str, float]]] = []
    seen: set[str] = set()
    for ts in top_strength:
        for cs in core_strength:
            for es in edge_strength:
                for ep in edge_prior:
                    for tc in top_cap_delta:
                        for cc in core_cap_delta:
                            for ec in edge_cap_delta:
                                cand = _merge_profiles(prof0)
                                cand["top"]["strength_scale"] = float(prof0["top"]["strength_scale"] * ts)
                                cand["core"]["strength_scale"] = float(prof0["core"]["strength_scale"] * cs)
                                cand["edge"]["strength_scale"] = float(prof0["edge"]["strength_scale"] * es)
                                cand["edge"]["prior_scale"] = float(prof0["edge"]["prior_scale"] * ep)
                                cand["top"]["cap_shift"] = float(prof0["top"]["cap_shift"] + tc)
                                cand["core"]["cap_shift"] = float(prof0["core"]["cap_shift"] + cc)
                                cand["edge"]["cap_shift"] = float(prof0["edge"]["cap_shift"] + ec)
                                key = json.dumps(cand, ensure_ascii=False, sort_keys=True)
                                if key in seen:
                                    continue
                                seen.add(key)
                                out.append(cand)
    # guarantee baseline included
    k0 = json.dumps(prof0, ensure_ascii=False, sort_keys=True)
    if k0 not in seen:
        out.insert(0, prof0)
    return out


def _profile_distance(a: Dict[str, Dict[str, float]], b: Dict[str, Dict[str, float]]) -> float:
    da = _merge_profiles(a)
    db = _merge_profiles(b)
    dist = 0.0
    for band in ("top", "core", "edge"):
        for k in ("strength_scale", "prior_scale", "max_shrink_scale", "cap_shift", "soft_shift", "hard_shift", "gate_score", "gate_n_eff"):
            va = _safe_float(da.get(band, {}).get(k), 0.0)
            vb = _safe_float(db.get(band, {}).get(k), 0.0)
            dist += abs(va - vb)
    return float(dist)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 4B gate: auto-tune marginal trust band coefficients.")
    ap.add_argument("--out", default="phase4b_marginal_tuning_report.json")
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--speed", choices=["fast", "full"], default="fast")
    ap.add_argument("--write-params", action="store_true")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--pairs-per-league", type=int, default=0, help="0=auto by speed")
    ap.add_argument("--leagues", default="LCK,LPL,LEC,CBLOL,LCP,TCL,PRM,LIT,UL")
    ap.add_argument("--max-cases", type=int, default=0, help="0=auto by speed (fast=14, full=40)")
    ap.add_argument("--min-samples", type=int, default=10)
    ap.add_argument("--min-marginal-samples", type=int, default=5)
    ap.add_argument("--min-gain", type=float, default=0.00015)
    ap.add_argument("--max-top-shift-pp", type=float, default=2.0)
    ap.add_argument("--max-core-shift-pp", type=float, default=4.5)
    args = ap.parse_args()

    daily = _latest_daily_csv(ROOT)
    if daily is None:
        rep = {
            "version": "phase4b_marginal_tuning_v1",
            "generated_at": _utc_now(),
            "decision": "reject",
            "reasons": ["daily_csv_missing"],
        }
        _write_json(ROOT / str(args.out), rep)
        print(f"OK: phase4b marginal tuning -> {args.out} | decision=reject | reason=daily_csv_missing")
        return 2

    try:
        src = _read_pair_source(daily)
    except Exception as e:
        rep = {
            "version": "phase4b_marginal_tuning_v1",
            "generated_at": _utc_now(),
            "decision": "reject",
            "reasons": [f"pair_source_error:{type(e).__name__}"],
            "error": str(e),
        }
        _write_json(ROOT / str(args.out), rep)
        print(f"OK: phase4b marginal tuning -> {args.out} | decision=reject | reason=pair_source_error")
        return 2

    ppl = int(args.pairs_per_league)
    if ppl <= 0:
        ppl = 1 if str(args.speed) == "fast" else 2
    leagues = [x.strip().upper() for x in str(args.leagues).split(",") if x.strip()]
    max_cases = int(args.max_cases)
    if max_cases <= 0:
        max_cases = 14 if str(args.speed) == "fast" else 40
    pairs = _pick_cases(src, leagues=leagues, per_league=max(1, ppl), max_total=max_cases)

    # Coverage fallback: if preferred leagues are insufficient, expand to all leagues in CSV.
    # This improves gate stability without loosening thresholds.
    target_pairs = max(int(args.min_samples), int(args.min_marginal_samples))
    if len(pairs) < target_pairs:
        pref = [str(x).upper() for x in leagues]
        lc = src["league"].astype(str).str.upper().value_counts()
        remaining = [str(lg).upper() for lg in lc.index.tolist() if str(lg).upper() not in set(pref)]
        all_order = pref + remaining
        extra = _pick_cases(
            src,
            leagues=all_order,
            per_league=max(1, ppl),
            seen_gameids={str(p.get("gameid", "")) for p in pairs if str(p.get("gameid", ""))},
            max_total=max(0, int(max_cases - len(pairs))),
        )
        if extra:
            pairs.extend(extra)

    rows: List[Dict[str, Any]] = []
    for p in pairs:
        r = _run_case(ROOT, str(p.get("teamA", "")), str(p.get("teamB", "")), timeout=max(180, int(args.timeout)))
        r["league_req"] = str(p.get("league", ""))
        r["gameid"] = str(p.get("gameid", ""))
        r["y"] = int(p.get("blue_win", 0))
        rows.append(r)

    ok_rows = [r for r in rows if bool(r.get("ok")) and math.isfinite(_safe_float(r.get("p_in")))]
    samples = []
    for r in ok_rows:
        band = str(r.get("band", "edge") or "edge").strip().lower()
        if band not in {"top", "core", "edge"}:
            band = "edge"
        samples.append(
            {
                "y": int(r.get("y", 0)),
                "p_in": float(_clip_prob(_safe_float(r.get("p_in"), 0.5))),
                "confidence_score": float(max(0.0, min(100.0, _safe_float(r.get("confidence_score"), 50.0)))),
                "n_eff": float(max(0.0, _safe_float(r.get("n_eff"), 0.0))),
                "band": band,
            }
        )

    params_path = ROOT / str(args.params)
    global_params = _global_params_from_file(params_path)
    base_overrides = _sanitize_profiles(global_params.get("band_coeffs", {}))
    baseline_profiles = _merge_profiles(base_overrides)

    baseline_eval = _evaluate_profiles(samples, global_params, baseline_profiles)
    baseline_ll = _safe_float(baseline_eval.get("weighted_logloss"))
    candidates = _candidate_profiles(str(args.speed), baseline_profiles)

    scored: List[Dict[str, Any]] = []
    for cand in candidates:
        ev = _evaluate_profiles(samples, global_params, cand)
        ll = _safe_float(ev.get("weighted_logloss"))
        if not math.isfinite(ll):
            continue
        by_band = ev.get("by_band") if isinstance(ev.get("by_band"), dict) else {}
        top_shift = _safe_float((by_band.get("top") or {}).get("avg_abs_shift_pp"), 0.0)
        core_shift = _safe_float((by_band.get("core") or {}).get("avg_abs_shift_pp"), 0.0)
        hard_ok = bool(top_shift <= float(args.max_top_shift_pp) and core_shift <= float(args.max_core_shift_pp))
        dist = _profile_distance(cand, baseline_profiles)
        scored.append(
            {
                "profiles": cand,
                "eval": ev,
                "ll": float(ll),
                "top_shift_pp": float(top_shift),
                "core_shift_pp": float(core_shift),
                "hard_ok": bool(hard_ok),
                "distance_from_baseline": float(dist),
            }
        )

    scored_ok = [x for x in scored if bool(x.get("hard_ok", False))]
    if not scored_ok:
        scored_ok = list(scored)
    best = min(scored_ok, key=lambda x: (float(x.get("ll", 9.0)), float(x.get("distance_from_baseline", 9e9)))) if scored_ok else {}
    best_ll = _safe_float(best.get("ll"))
    gain_ll = float(baseline_ll - best_ll) if (math.isfinite(baseline_ll) and math.isfinite(best_ll)) else float("nan")

    n_samples = len(samples)
    n_marginal = int(sum(1 for s in samples if str(s.get("band", "")) in {"core", "edge"}))
    decision = "promote"
    reasons: List[str] = []
    if n_samples < int(args.min_samples):
        decision = max([decision, "shadow_only"], key=_rank)
        reasons.append("few_samples")
    if n_marginal < int(args.min_marginal_samples):
        decision = max([decision, "shadow_only"], key=_rank)
        reasons.append("few_marginal_samples")
    if (not math.isfinite(gain_ll)) or (float(gain_ll) < float(args.min_gain)):
        decision = max([decision, "shadow_only"], key=_rank)
        reasons.append("insufficient_gain")

    tuning_cfg = {
        "version": "ml_marginal_band_tuning_v1",
        "generated_at": _utc_now(),
        "speed": str(args.speed),
        "global_params_snapshot": {
            "strength": float(global_params.get("strength", 0.70)),
            "prior_games": float(global_params.get("prior_games", 28.0)),
            "max_shrink": float(global_params.get("max_shrink", 0.72)),
            "cap_prob": float(global_params.get("cap_prob", 0.84)),
            "score_soft": float(global_params.get("score_soft", 68.0)),
            "score_hard": float(global_params.get("score_hard", 46.0)),
            "band_tuning": bool(global_params.get("band_tuning", True)),
        },
        "band_coeffs": _sanitize_profiles((best.get("profiles") or {}) if isinstance(best, dict) else {}),
        "thresholds": {
            "min_samples": int(args.min_samples),
            "min_marginal_samples": int(args.min_marginal_samples),
            "min_gain": float(args.min_gain),
            "max_top_shift_pp": float(args.max_top_shift_pp),
            "max_core_shift_pp": float(args.max_core_shift_pp),
        },
    }

    if bool(args.write_params) and decision == "promote":
        params_cur = _read_json(params_path)
        params_cur["ml_marginal_trust_band_coeffs"] = dict(tuning_cfg.get("band_coeffs") or {})
        params_cur["ml_marginal_trust_band_coeffs_meta"] = {
            "version": str(tuning_cfg.get("version") or ""),
            "generated_at": str(tuning_cfg.get("generated_at") or ""),
            "source": "phase4b_marginal_tuning_report.json",
            "decision": str(decision),
            "gain_logloss_vs_baseline": (float(gain_ll) if math.isfinite(gain_ll) else None),
            "samples": int(n_samples),
        }
        params_cur["ml_marginal_trust_band_tuning"] = True
        params_cur["generated_at"] = _utc_now()
        _write_json(params_path, params_cur)

    rep = {
        "version": "phase4b_marginal_tuning_v1",
        "generated_at": _utc_now(),
        "decision": decision,
        "reasons": reasons,
        "reason": (reasons[0] if reasons else ""),
        "daily_csv": str(daily),
        "params_path": str(params_path),
        "sample_pairs": pairs,
        "rows": rows,
        "samples_used": int(n_samples),
        "samples_n": int(n_samples),
        "samples_marginal": int(n_marginal),
        "samples_marginal_n": int(n_marginal),
        "baseline_eval": baseline_eval,
        "best_eval": (best.get("eval") if isinstance(best, dict) else {}),
        "baseline_band_coeffs": _sanitize_profiles(base_overrides),
        "best_band_coeffs": _sanitize_profiles((best.get("profiles") or {}) if isinstance(best, dict) else {}),
        "best_candidate": (best if isinstance(best, dict) else {}),
        "constraints_ok": bool(best.get("hard_ok", False)) if isinstance(best, dict) else False,
        "gain_logloss_vs_baseline": (float(gain_ll) if math.isfinite(gain_ll) else None),
        "grid_size": len(candidates),
        "valid_candidates": len(scored_ok),
        "tuning_cfg": tuning_cfg,
    }
    _write_json(ROOT / str(args.out), rep)
    print(
        "OK: phase4b marginal tuning -> {} | decision={} | samples={} | gain_ll={}".format(
            str(args.out),
            decision,
            int(n_samples),
            (f"{gain_ll:.6f}" if math.isfinite(gain_ll) else "nan"),
        )
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
