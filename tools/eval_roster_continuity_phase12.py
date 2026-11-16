from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

THIS_DIR = Path(__file__).resolve().parent
ROOT_DIR = THIS_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app_core.roster_continuity_core import apply_roster_continuity_live
from mlcore.players_layer import PlayersArtifact
from mlcore.artifact import MLArtifact
from mlcore.utils import brier, clip_prob, logloss, safe_float as _f
from tools.backtest_pipeline_abc_by_league import (
    ROOT,
    _default_csv_paths,
    _iter_replay_rows,
    _load_params,
)


def _summary(rows: List[Dict[str, Any]], p_key: str) -> Dict[str, Any]:
    ys: List[int] = []
    ps: List[float] = []
    for r in rows:
        try:
            y = int(r.get("y"))
            p = float(r.get(p_key))
        except Exception:
            continue
        if y not in (0, 1):
            continue
        if not math.isfinite(p):
            continue
        ys.append(y)
        ps.append(float(clip_prob(p)))
    if not ys:
        return {"n": 0, "logloss": None, "brier": None}
    return {
        "n": len(ys),
        "logloss": float(logloss(ys, ps)),
        "brier": float(brier(ys, ps)),
    }


def _proxy_signals(r: Dict[str, Any]) -> Dict[str, float]:
    n_team = max(0.0, _f(r.get("n_team"), 0.0))
    n_players = max(0.0, _f(r.get("n_players"), 0.0))
    recent_ev = max(0.0, min(1.0, _f(r.get("recent_ev"), 0.0)))
    roster_changed = bool(r.get("roster_changed", False))

    # Proxies for backtest (pre-jogo only, no leakage):
    # coverage grows with players evidence; continuity decreases when roster_changed.
    coverage_eff = max(0.0, min(1.0, n_players / (n_players + 7.0)))
    freshness_avg = max(0.0, min(1.0, 0.55 * recent_ev + 0.45 * coverage_eff))
    lineup_cont = max(0.0, min(1.0, coverage_eff * (0.85 if not roster_changed else 0.45)))
    transfer_signal = max(0.0, min(1.0, 1.0 - lineup_cont)) if roster_changed else 0.0

    return {
        "n_team_eff": float(n_team),
        "n_players_eff": float(n_players),
        "coverage_eff": float(coverage_eff),
        "freshness_avg": float(freshness_avg),
        "lineup_continuity": float(lineup_cont),
        "transfer_signal": float(transfer_signal),
    }


def _evaluate(rows: List[Dict[str, Any]], cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out_rows: List[Dict[str, Any]] = []
    applied_count = 0
    dpp_abs_sum = 0.0

    for r in rows:
        p_in = _f(r.get("p_after_b"), float("nan"))
        if not math.isfinite(p_in):
            continue
        p_team = _f(r.get("p_cal_team"), p_in)
        p_players = _f(r.get("p_base"), float("nan"))
        bo = int(_f(r.get("bo"), 1.0) or 1)
        phase = str(r.get("phase") or "")
        roster_changed = bool(r.get("roster_changed", False))
        sig = _proxy_signals(r)

        rc = apply_roster_continuity_live(
            p_map_in=float(p_in),
            p_players=(float(p_players) if math.isfinite(p_players) else None),
            p_team=(float(p_team) if math.isfinite(p_team) else None),
            lineup_continuity=float(sig["lineup_continuity"]),
            freshness_avg=float(sig["freshness_avg"]),
            coverage_eff=float(sig["coverage_eff"]),
            roster_changed=bool(roster_changed),
            season_phase=phase,
            bo=int(bo),
            n_team_eff=float(sig["n_team_eff"]),
            n_players_eff=float(sig["n_players_eff"]),
            transfer_signal=float(sig["transfer_signal"]),
            cfg=(cfg or {}),
        )
        p_rc = float(rc.get("p_after")) if bool(rc.get("applied", False)) and math.isfinite(_f(rc.get("p_after"), float("nan"))) else float(p_in)
        if bool(rc.get("applied", False)):
            applied_count += 1
            dpp_abs_sum += abs(100.0 * (p_rc - float(p_in)))

        o = dict(r)
        o["p_roster_off"] = float(p_in)
        o["p_roster_on"] = float(p_rc)
        o["roster_layer_applied"] = bool(rc.get("applied", False))
        o["roster_layer_diff_pp"] = float(100.0 * (p_rc - float(p_in)))
        o["roster_layer_reason"] = str(rc.get("reason") or "")
        out_rows.append(o)

    g_off = _summary(out_rows, "p_roster_off")
    g_on = _summary(out_rows, "p_roster_on")
    gain_ll = (float(g_off["logloss"]) - float(g_on["logloss"])) if g_off.get("logloss") is not None and g_on.get("logloss") is not None else None
    gain_br = (float(g_off["brier"]) - float(g_on["brier"])) if g_off.get("brier") is not None and g_on.get("brier") is not None else None

    by_league_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in out_rows:
        by_league_rows[str(r.get("league") or "")].append(r)

    by_league: Dict[str, Any] = {}
    for lg, rr in sorted(by_league_rows.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        off = _summary(rr, "p_roster_off")
        on = _summary(rr, "p_roster_on")
        gain_lg = (float(off["logloss"]) - float(on["logloss"])) if off.get("logloss") is not None and on.get("logloss") is not None else None
        by_league[lg] = {
            "rows": len(rr),
            "off": off,
            "on": on,
            "gain_logloss": gain_lg,
        }

    major = ["LCK", "LPL", "LEC", "CBLOL", "LCP", "PRM", "TCL", "LTA N", "LTA S"]
    major_drawdowns: List[Dict[str, Any]] = []
    for lg in major:
        x = by_league.get(lg)
        if not isinstance(x, dict):
            continue
        if int(x.get("rows") or 0) < 60:
            continue
        g = x.get("gain_logloss")
        if g is None:
            continue
        if float(g) < -0.008:
            major_drawdowns.append({"league": lg, "rows": int(x.get("rows") or 0), "gain_logloss": float(g)})

    reasons: List[str] = []
    decision = "shadow_only"
    # Neutral zones to avoid false shadow/reject on evaluation noise.
    # tight zone: near-zero variation; almost-neutral zone: tiny degradation
    # accepted only with high coverage and no major drawdowns.
    neutral_ll_eps = 0.00020
    neutral_br_eps = 0.00008
    near_neutral_ll_eps = 0.00050
    near_neutral_br_eps = 0.00020
    if g_on.get("n", 0) < 1500:
        reasons.append("rows_insuficientes_para_promocao")
    if gain_ll is None:
        reasons.append("gain_logloss_indisponivel")
    else:
        if float(gain_ll) >= 0.0010 and float(gain_br or 0.0) >= 0.0001 and not major_drawdowns:
            decision = "promote"
        elif (
            abs(float(gain_ll)) <= float(neutral_ll_eps)
            and abs(float(gain_br or 0.0)) <= float(neutral_br_eps)
            and not major_drawdowns
            and int(g_on.get("n", 0) or 0) >= 2500
        ):
            decision = "promote"
            reasons.append("promovido_por_zona_neutra_sem_drawdown")
        elif (
            float(gain_ll) >= -float(near_neutral_ll_eps)
            and float(gain_br or 0.0) >= -float(near_neutral_br_eps)
            and not major_drawdowns
            and int(g_on.get("n", 0) or 0) >= 3000
            and float(applied_count / max(1, len(out_rows))) >= 0.90
        ):
            decision = "promote"
            reasons.append("promovido_por_zona_quase_neutra_com_cobertura_alta")
        elif major_drawdowns:
            decision = "reject"
            reasons.append("drawdown_liga_principal")
        else:
            decision = "shadow_only"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cfg_used": dict(cfg or {}),
        "rows_total": len(out_rows),
        "applied_rows": int(applied_count),
        "applied_rate": float(applied_count / max(1, len(out_rows))),
        "mean_abs_diff_pp_when_applied": (float(dpp_abs_sum / max(1, applied_count)) if applied_count > 0 else 0.0),
        "global": {
            "off": g_off,
            "on": g_on,
            "gain_logloss": gain_ll,
            "gain_brier": gain_br,
        },
        "by_league": by_league,
        "major_drawdowns": major_drawdowns,
        "neutral_zone": {
            "gain_logloss_eps": float(neutral_ll_eps),
            "gain_brier_eps": float(neutral_br_eps),
            "near_gain_logloss_eps": float(near_neutral_ll_eps),
            "near_gain_brier_eps": float(near_neutral_br_eps),
        },
        "decision": str(decision),
        "reasons": reasons,
    }


def _fit_cfg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    strengths = [0.25, 0.35, 0.50, 0.70, 1.00]
    team_shrinks = [0.35, 0.50, 0.70, 1.00]
    players_alpha = [0.60, 0.80, 1.00]
    min_covs = [0.20, 0.25, 0.30]
    w_caps = [0.12, 0.16, 0.20]

    best: Optional[Dict[str, Any]] = None
    all_trials: List[Dict[str, Any]] = []
    for s in strengths:
        for ts in team_shrinks:
            for pa in players_alpha:
                for mc in min_covs:
                    for wc in w_caps:
                        cfg = {
                            "strength": float(s),
                            "team_shrink_mult": float(ts),
                            "players_alpha_mult": float(pa),
                            "min_coverage": float(mc),
                            "weight_cap": float(wc),
                        }
                        rep = _evaluate(rows, cfg=cfg)
                        g = rep.get("global") or {}
                        gain_ll = g.get("gain_logloss")
                        gain_br = g.get("gain_brier")
                        dec = str(rep.get("decision") or "unknown")
                        applied_rate = float(rep.get("applied_rate") or 0.0)
                        trial = {
                            "cfg": cfg,
                            "decision": dec,
                            "gain_logloss": gain_ll,
                            "gain_brier": gain_br,
                            "applied_rate": applied_rate,
                        }
                        all_trials.append(trial)
                        # ranking objective:
                        # 1) avoid reject
                        # 2) maximize logloss gain
                        # 3) maximize brier gain
                        # 4) keep moderate applied_rate (prefer <= 0.75)
                        if gain_ll is None:
                            continue
                        score = float(gain_ll) + 0.35 * float(gain_br or 0.0)
                        if applied_rate > 0.75:
                            score -= 0.0006 * (applied_rate - 0.75) * 100.0
                        if dec == "reject":
                            score -= 1.0
                        elif dec == "shadow_only":
                            score -= 0.05
                        cand = {"score": score, "trial": trial}
                        if best is None or float(cand["score"]) > float(best["score"]):
                            best = cand

    top = sorted(
        [x for x in all_trials if x.get("gain_logloss") is not None],
        key=lambda x: float(x.get("gain_logloss") or -999.0),
        reverse=True,
    )[:12]
    return {
        "best": ((best or {}).get("trial") or {}),
        "top_trials": top,
        "n_trials": len(all_trials),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1.2 A/B: roster_continuity_v2 (off vs on).")
    ap.add_argument("--artifact", default=str(ROOT / "ml_artifact.json"))
    ap.add_argument("--players-artifact", default=str(ROOT / "players_artifact.json"))
    ap.add_argument("--params", default=str(ROOT / "params_fitted.json"))
    ap.add_argument("--csv", dest="csvs", action="append", default=None)
    ap.add_argument("--speed", default="fast", choices=["fast", "full"])
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "phase12_roster_continuity_report.json"))
    ap.add_argument("--fit", action="store_true", help="Run grid-search fit and evaluate best cfg.")
    ap.add_argument("--write-params", action="store_true", help="Persist best cfg into params_fitted.json.")
    args = ap.parse_args()

    csv_paths = list(args.csvs or []) or _default_csv_paths(ROOT)
    csv_paths = [str(Path(p)) for p in csv_paths if str(p).lower().endswith(".csv")]
    if not csv_paths:
        print("ERRO: nenhum CSV encontrado.")
        return 2

    art_path = Path(args.artifact)
    p_art_path = Path(args.players_artifact)
    params_path = Path(args.params)
    if not art_path.exists() or not p_art_path.exists() or not params_path.exists():
        print("ERRO: artifact/players_artifact/params ausente.")
        return 2

    art = MLArtifact.load_json(str(art_path))
    p_art = PlayersArtifact.load_json(str(p_art_path))
    params = _load_params(params_path)

    rows = _iter_replay_rows(
        art=art,
        p_art=p_art,
        params=params,
        csv_paths=csv_paths,
        max_rows=int(args.max_rows or 0),
        speed_profile=str(args.speed or "fast"),
    )
    fit_info: Dict[str, Any] = {}
    best_cfg: Dict[str, Any] = {}
    if bool(args.fit):
        fit_info = _fit_cfg(rows)
        best_cfg = dict((fit_info.get("best") or {}).get("cfg") or {})
    rep = _evaluate(rows, cfg=best_cfg)
    if fit_info:
        rep["fit"] = fit_info
    rep["inputs"] = {
        "artifact": str(art_path),
        "players_artifact": str(p_art_path),
        "params": str(params_path),
        "csvs": [str(p) for p in csv_paths],
        "speed": str(args.speed or "fast"),
        "max_rows": int(args.max_rows or 0),
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.write_params) and best_cfg:
        try:
            params_live = _load_params(params_path)
            if not isinstance(params_live, dict):
                params_live = {}
            params_live["roster_continuity_v2"] = dict(best_cfg)
            params_live["generated_at"] = datetime.now().isoformat(timespec="seconds")
            params_path.write_text(json.dumps(params_live, ensure_ascii=False, indent=2), encoding="utf-8")
            rep["params_updated"] = str(params_path)
            out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e_up:
            rep["params_update_error"] = str(e_up)
            out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "OK: phase1.2 roster continuity report -> {} | decision={} | rows={} | applied_rate={:.1f}% | gain_ll={}".format(
            out_path.name,
            rep.get("decision"),
            int(rep.get("rows_total") or 0),
            100.0 * float(rep.get("applied_rate") or 0.0),
            ("{:.6f}".format(float((rep.get("global") or {}).get("gain_logloss"))) if (rep.get("global") or {}).get("gain_logloss") is not None else "None"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
