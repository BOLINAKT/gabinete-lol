from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app_core.fusion_core import fuse_with_coherence_guard
from mlcore.artifact import MLArtifact
from mlcore.bo import prob_win_series
from mlcore.players_layer import PlayersArtifact, compute_delta_and_confidence, load_match_player_rows
from mlcore.regression_fixtures import upsert_players_fixture_snapshot
from mlcore.utils import clip_prob, logit, prob_to_decimal_odds, sigmoid


POS = ["Top", "Jungle", "Mid", "Bot", "Support"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _macro_key(league: str) -> str:
    z = str(league or "").strip().upper()
    if not z:
        return "OTHER"
    if z.startswith("LPL") or z in {"LDL", "LPL CL"}:
        return "CN"
    if z.startswith("LCK") or z in {"LCK CL"}:
        return "KR"
    if z.startswith(("LEC", "EMEA")) or z in {"LFL", "LVP SL", "PRIME LEAGUE", "NLC", "UL"}:
        return "EMEA"
    if z.startswith("LCS") or z in {"NACL", "LTA N", "LTA NORTH"}:
        return "NA"
    if z.startswith(("CBLOL", "LTA S", "LTA SOUTH")):
        return "BR"
    if z.startswith(("PCS", "VCS", "LJL", "LCO")):
        return "APAC"
    return "OTHER"


def _latest_lineup(rows: pd.DataFrame, team: str) -> Dict[str, str]:
    d = rows[rows["teamname"].astype(str) == str(team)].copy()
    if d.empty:
        return {}
    d = d.sort_values(["date"], ascending=False)
    for _, g in d.groupby("gameid", sort=False):
        m: Dict[str, str] = {}
        for _, r in g.iterrows():
            p = str(r.get("pos_can") or "")
            if p not in POS:
                continue
            pk = str(r.get("player_key") or "")
            if pk and p not in m:
                m[p] = pk
        if all(p in m for p in POS):
            return m
    out: Dict[str, str] = {}
    for p in POS:
        gp = d[d["pos_can"].astype(str) == p]
        if not gp.empty:
            out[p] = str(gp.iloc[0].get("player_key") or "")
    return out


def _load_settings(root: Path) -> Dict[str, Any]:
    p = root / ".gabinete_settings.json"
    if not p.exists():
        return {}
    try:
        return dict((json.loads(p.read_text(encoding="utf-8")) or {}).get("settings") or {})
    except Exception:
        return {}


def _load_fit_cfg(root: Path) -> Dict[str, Any]:
    p = root / "params_fitted.json"
    if not p.exists():
        return {}
    try:
        return dict(json.loads(p.read_text(encoding="utf-8")) or {})
    except Exception:
        return {}


def _fit_lane_weights_for_league(fit_cfg: Dict[str, Any], league: str) -> Tuple[Dict[str, float], str]:
    plw = dict((fit_cfg or {}).get("players_lane_weights") or {})
    if not plw:
        return {}, ""
    by_lg = plw.get("by_league") if isinstance(plw.get("by_league"), dict) else {}
    by_mk = plw.get("by_macro") if isinstance(plw.get("by_macro"), dict) else {}
    g = plw.get("global") if isinstance(plw.get("global"), dict) else {}
    if str(league) in by_lg and isinstance(by_lg.get(str(league)), dict):
        return dict(by_lg.get(str(league)) or {}), f"league:{league}"
    mk = _macro_key(str(league))
    if mk in by_mk and isinstance(by_mk.get(mk), dict):
        return dict(by_mk.get(mk) or {}), f"macro:{mk}"
    return dict(g), "global"


def _predict_row(
    *,
    art: MLArtifact,
    p_art: PlayersArtifact,
    rows: pd.DataFrame,
    fit_cfg: Dict[str, Any],
    settings: Dict[str, Any],
    team_a: str,
    team_b: str,
    league: str,
) -> Dict[str, Any]:
    p_raw_f = float(art.model.p_blue(team_a, team_b))
    p_raw_r = float(art.model.p_blue(team_b, team_a))
    p_raw = float(0.5 * (p_raw_f + (1.0 - p_raw_r)))
    p_map_team = float(0.5 * (float(art.calibrator.predict_proba(p_raw_f)) + (1.0 - float(art.calibrator.predict_proba(p_raw_r)))))

    lineup_a = _latest_lineup(rows, team_a)
    lineup_b = _latest_lineup(rows, team_b)

    lane_w = {
        "Top": float(settings.get("ml_players_lane_w_top", 1.0) or 1.0),
        "Jungle": float(settings.get("ml_players_lane_w_jungle", 1.0) or 1.0),
        "Mid": float(settings.get("ml_players_lane_w_mid", 1.0) or 1.0),
        "Bot": float(settings.get("ml_players_lane_w_adc", 1.0) or 1.0),
        "Support": float(settings.get("ml_players_lane_w_support", 1.0) or 1.0),
        "ADC": float(settings.get("ml_players_lane_w_adc", 1.0) or 1.0),
    }
    lane_fit, lane_fit_src = _fit_lane_weights_for_league(fit_cfg, league)
    if lane_fit:
        for k in ["Top", "Jungle", "Mid", "Bot", "Support"]:
            lane_w[k] = float(lane_w.get(k, 1.0) or 1.0) * float(lane_fit.get(k, 1.0) or 1.0)
        lane_w["ADC"] = float(lane_w.get("Bot", 1.0))

    league_w = {
        "LPL": float(settings.get("ml_players_lg_w_lpl", 1.0) or 1.0),
        "CN": float(settings.get("ml_players_lg_w_lpl", 1.0) or 1.0),
        "LCK": float(settings.get("ml_players_lg_w_lck", 1.0) or 1.0),
        "KR": float(settings.get("ml_players_lg_w_lck", 1.0) or 1.0),
        "EMEA": float(settings.get("ml_players_lg_w_emea", 1.0) or 1.0),
        "NA": float(settings.get("ml_players_lg_w_na", 1.0) or 1.0),
        "BR": float(settings.get("ml_players_lg_w_br", 1.0) or 1.0),
        "APAC": float(settings.get("ml_players_lg_w_apac", 1.0) or 1.0),
        "OTHER": float(settings.get("ml_players_lg_w_other", 1.0) or 1.0),
        "DEFAULT": 1.0,
    }
    info = compute_delta_and_confidence(
        p_art,
        blue_lineup=lineup_a,
        red_lineup=lineup_b,
        as_of=None,
        match_league=league,
        require_both_sides=False,
        lane_weights=lane_w,
        league_weights=league_w,
    )
    delta_raw = float(info.get("delta", 0.0) or 0.0)
    cap = float(settings.get("lineup_delta_cap", 1.2) or 1.2)
    slope = float(settings.get("lineup_delta_slope", 1.6) or 1.6)
    delta_eff = float(cap * math.tanh((slope * delta_raw) / max(0.05, abs(cap))))
    w_lineup = float(settings.get("ml_players_w_lineup", 0.75) or 0.75)
    if w_lineup > 5.0:
        w_lineup = w_lineup / 100.0
    p_raw_players = float(sigmoid(float(logit(float(clip_prob(p_raw))) + w_lineup * delta_eff)))
    p_map_players = float(clip_prob(float(art.calibrator.predict_proba(p_raw_players))))

    n_team = float(min(rows[rows["teamname"] == team_a]["gameid"].nunique(), rows[rows["teamname"] == team_b]["gameid"].nunique()))
    cov = float(info.get("coverage", 0.0) or 0.0)
    cov_tot = float(info.get("coverage_total", 5.0) or 5.0)
    cov_ratio = cov / max(1.0, cov_tot)
    fresh = float(info.get("freshness_avg", 0.0) or 0.0)
    avg_gp_min = float(info.get("avg_gp_min", 0.0) or 0.0)
    n_players = float(max(0.0, avg_gp_min * cov_ratio * fresh))

    team_scale = float((((fit_cfg.get("best") or {}).get("team_scale")) or 1.0))
    players_scale = float((((fit_cfg.get("best") or {}).get("players_scale")) or 1.0))
    p_fused = float(
        fuse_with_coherence_guard(
            p_team=float(p_map_team),
            p_players=float(p_map_players),
            n_team=float(max(0.0, n_team * team_scale)),
            n_players=float(max(0.0, n_players * players_scale)),
            coverage=float(cov_ratio),
            transfer_signal=0.0,
            season_phase="auto",
        ).get("p_fused", p_map_team)
    )

    def _bo_pack(p: float) -> Dict[str, float]:
        p1 = float(clip_prob(p))
        p3 = float(prob_win_series(p1, 3))
        p5 = float(prob_win_series(p1, 5))
        return {
            "p_map": p1,
            "odd_map_a": float(prob_to_decimal_odds(p1)),
            "odd_map_b": float(prob_to_decimal_odds(1.0 - p1)),
            "p_bo3": p3,
            "odd_bo3_a": float(prob_to_decimal_odds(p3)),
            "odd_bo3_b": float(prob_to_decimal_odds(1.0 - p3)),
            "p_bo5": p5,
            "odd_bo5_a": float(prob_to_decimal_odds(p5)),
            "odd_bo5_b": float(prob_to_decimal_odds(1.0 - p5)),
        }

    return {
        "team_a": team_a,
        "team_b": team_b,
        "league": league,
        "team_only": _bo_pack(float(p_map_team)),
        "players_fused": _bo_pack(float(p_fused)),
        "debug": {
            "p_raw": float(p_raw),
            "p_map_players": float(p_map_players),
            "delta_raw": float(delta_raw),
            "delta_eff": float(delta_eff),
            "w_lineup": float(w_lineup),
            "coverage_ratio": float(cov_ratio),
            "freshness": float(fresh),
            "n_team": float(n_team),
            "n_players_eff": float(n_players),
            "team_scale": float(team_scale),
            "players_scale": float(players_scale),
            "lane_fit_source": str(lane_fit_src),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Update players+fusion regression fixture from current local artifacts/settings.")
    ap.add_argument("--root", type=str, default=".")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    art_path = root / "ml_artifact.json"
    part_path = root / "players_artifact.json"
    # CSV diario mais recente, sem ano cravado (sobrevive a virada de season).
    _daily_candidates = sorted((root / "CSV_DIARIO").glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    csv_path = _daily_candidates[0] if _daily_candidates else (root / "CSV_DIARIO" / "_missing.csv")
    fixture = root / "mlcore" / "tests" / "fixtures" / "players_fusion_regression.json"
    if not art_path.exists() or not part_path.exists() or not csv_path.exists():
        raise FileNotFoundError("Missing ml_artifact.json / players_artifact.json / daily csv.")
    if not fixture.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture}")

    art = MLArtifact.load_json(str(art_path))
    p_art = PlayersArtifact.load_json(str(part_path))
    rows = load_match_player_rows([str(csv_path)])
    rows = rows.copy()
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce")
    rows = rows.dropna(subset=["date"]).copy()

    settings = _load_settings(root)
    fit_cfg = _load_fit_cfg(root)

    payload = json.loads(fixture.read_text(encoding="utf-8"))
    rows_tpl = payload.get("matchups")
    if not isinstance(rows_tpl, list) or len(rows_tpl) == 0:
        snaps = payload.get("snapshots") if isinstance(payload.get("snapshots"), dict) else {}
        latest_key = str(payload.get("latest_snapshot_key") or "").strip()
        row_src = snaps.get(latest_key) if latest_key and isinstance(snaps.get(latest_key), dict) else None
        if not isinstance(row_src, dict):
            for _v in snaps.values():
                if isinstance(_v, dict) and isinstance(_v.get("matchups"), list) and _v.get("matchups"):
                    row_src = _v
                    break
        rows_tpl = list((row_src or {}).get("matchups") or [])

    out_rows: List[Dict[str, Any]] = []
    for row in rows_tpl:
        out_rows.append(
            _predict_row(
                art=art,
                p_art=p_art,
                rows=rows,
                fit_cfg=fit_cfg,
                settings=settings,
                team_a=str(row.get("team_a")),
                team_b=str(row.get("team_b")),
                league=str(row.get("league") or ""),
            )
        )

    art_sha = _sha256(art_path)
    part_sha = _sha256(part_path)
    csv_sha = _sha256(csv_path)
    snapshot = {
        "artifact_sha256": art_sha,
        "players_artifact_sha256": part_sha,
        "csv_sha256": csv_sha,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "team_vs_players_fused_current_settings",
        "matchups": out_rows,
    }
    payload = upsert_players_fixture_snapshot(
        payload,
        artifact_sha256=art_sha,
        players_artifact_sha256=part_sha,
        csv_sha256=csv_sha,
        snapshot=snapshot,
    )
    fixture.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {fixture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
