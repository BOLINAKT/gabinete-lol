from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.hier_calibration_core import apply_hier_calibration_live
from mlcore.artifact import MLArtifact
from mlcore.league_context import league_lookup_keys, league_macro_key
from mlcore.io_oracle import load_oracle_elixir_games
from mlcore.tiers import canonical_league, tier_for_league
from mlcore.utils import brier, clip_prob, logloss, safe_float as _f


_EVENT_LEAGUES = {
    "MSI",
    "WLDS",
    "WORLDS",
    "EWC",
    "FST",
    "EM",
    "HM",
    "IC",
    "ASI",
    "ASIA MASTER",
    "TSC",
    "DCUP",
    "NEXO",
    "KESPA",
}


def _safe_prob(p: Any, default: float = 0.5) -> float:
    try:
        v = float(p)
    except Exception:
        return float(default)
    if not math.isfinite(v):
        return float(default)
    return float(clip_prob(v))


def _canon_league(v: Any) -> str:
    return str(canonical_league(str(v or "")))


def _patch_tag(v: Any) -> str:
    s = str(v or "").strip().upper()
    if "REFIT" in s:
        return "refit"
    if "WARN" in s:
        return "warn"
    return "ok"


def _macro_group(league: str) -> str:
    return str(league_macro_key(_canon_league(league), unknown="OTHER"))


def _infer_league_class(league: str, node: Dict[str, Any]) -> str:
    macro = _macro_group(league)
    n_eff = max(_f(node.get("n_eff"), 0.0), _f(node.get("wf_n"), 0.0), _f(node.get("lv_n"), 0.0), _f(node.get("n_total"), 0.0))
    qb = str(node.get("quality_band") or "").strip().lower()
    strong_q = qb in {"strong", "good"}
    ok_q = qb in {"strong", "good", "ok"}
    if macro in {"KR", "CN"} and n_eff >= 500.0 and ok_q:
        return "major"
    if macro in {"EMEA", "NA", "BR", "APAC"} and n_eff >= 800.0 and strong_q:
        return "major"
    if n_eff >= 1300.0 and strong_q:
        return "major"
    return "minor"


def _league_class_map(baseline: Dict[str, Any]) -> Dict[str, str]:
    by_league = baseline.get("by_league") if isinstance(baseline.get("by_league"), dict) else {}
    out: Dict[str, str] = {}
    explicit = baseline.get("league_class") if isinstance(baseline.get("league_class"), dict) else {}
    for lg, cls in explicit.items():
        c = str(cls or "").strip().lower()
        if c in {"major", "minor"}:
            for key in league_lookup_keys(lg):
                out[str(key)] = c
    for lg, node in by_league.items():
        key = _canon_league(lg)
        if (not key) or key in out or not isinstance(node, dict):
            continue
        out[key] = _infer_league_class(key, node)
    return out


def _segment_class_inter(league_a: str, league_b: str, class_map: Dict[str, str]) -> str:
    cls_a = str(class_map.get(_canon_league(league_a), "minor")).strip().lower()
    cls_b = str(class_map.get(_canon_league(league_b), "minor")).strip().lower()
    if cls_a == "major" and cls_b == "major":
        return "inter_major_major"
    if cls_a == "minor" and cls_b == "minor":
        return "inter_minor_minor"
    return "inter_mixed"


def _baseline_pre_like(post_baseline: Dict[str, Any]) -> Dict[str, Any]:
    b = copy.deepcopy(post_baseline if isinstance(post_baseline, dict) else {})
    by_seg = b.get("by_segment") if isinstance(b.get("by_segment"), dict) else {}
    b["by_segment"] = {
        str(k): v
        for k, v in by_seg.items()
        if (not str(k).startswith("class:")) and ("|patch:" not in str(k))
    }
    b.pop("league_class", None)
    return b


def _default_csv_paths(root: Path) -> List[str]:
    paths: List[Path] = []
    hist = root / "CSV_HISTORICO"
    daily = root / "CSV_DIARIO"
    if hist.exists():
        paths.extend(sorted([p for p in hist.glob("*.csv") if p.is_file()]))
    if daily.exists():
        paths.extend(sorted([p for p in daily.glob("*.csv") if p.is_file()]))
    return [str(p) for p in paths]


def _concat_non_empty_frames(parts: List[pd.DataFrame]) -> pd.DataFrame:
    clean: List[pd.DataFrame] = []
    for d in parts:
        if d is None or d.empty:
            continue
        dd = d.dropna(axis=1, how="all")
        if dd is None or dd.empty:
            continue
        clean.append(dd)
    if not clean:
        return pd.DataFrame()
    return pd.concat(clean, ignore_index=True, sort=False)


def _build_bo_map(games: pd.DataFrame) -> Dict[str, int]:
    if games is None or games.empty:
        return {}
    gtmp = games.copy()
    gtmp["date_day"] = pd.to_datetime(gtmp.get("date"), errors="coerce").dt.date.astype(str)
    gtmp["pair_key"] = gtmp.apply(
        lambda rr: "||".join(sorted([str(rr.get("blue") or ""), str(rr.get("red") or "")])),
        axis=1,
    )
    gtmp["gno"] = pd.to_numeric(gtmp.get("game"), errors="coerce").fillna(1).astype(int).clip(lower=1)
    grp = (
        gtmp.groupby(["date_day", "league", "split", "playoffs", "pair_key"], dropna=False)["gno"]
        .max()
        .reset_index()
        .rename(columns={"gno": "series_max"})
    )
    gtmp = gtmp.merge(grp, on=["date_day", "league", "split", "playoffs", "pair_key"], how="left")
    out: Dict[str, int] = {}
    for gid, mx in zip(gtmp.get("gameid", []), gtmp.get("series_max", [])):
        try:
            mxi = int(mx) if pd.notna(mx) else 1
        except Exception:
            mxi = 1
        out[str(gid)] = 5 if mxi >= 5 else (3 if mxi >= 3 else 1)
    return out


def _patch_status_sequence(games: pd.DataFrame) -> List[str]:
    out: List[str] = []
    state: Dict[str, Dict[str, Any]] = {}
    for _, g in games.iterrows():
        league = _canon_league(g.get("league"))
        patch_raw = str(g.get("patch") or "").strip()
        ps = state.get(league, {"patch": "", "count": 0})
        if patch_raw and str(ps.get("patch") or "") != patch_raw:
            status = "REFIT"
            ps = {"patch": patch_raw, "count": 0}
        else:
            cnt = int(ps.get("count", 0) or 0)
            status = "WARN" if cnt < 12 else "OK"
        ps["count"] = int(ps.get("count", 0) or 0) + 1
        state[league] = ps
        out.append(str(status))
    return out


def _infer_origin_league(
    hist: Deque[str],
    *,
    min_hist_games: int,
    min_share: float,
) -> Tuple[str, int, float]:
    vals = [_canon_league(x) for x in hist if _canon_league(x)]
    if len(vals) < int(min_hist_games):
        return "", len(vals), 0.0

    non_event = [x for x in vals if x not in _EVENT_LEAGUES]
    src = non_event if len(non_event) >= int(min_hist_games) else vals
    if len(src) < int(min_hist_games):
        return "", len(src), 0.0

    vc = Counter(src)
    if not vc:
        return "", len(src), 0.0
    top_lg, top_n = vc.most_common(1)[0]
    share = float(top_n) / float(max(1, len(src)))
    if share < float(min_share):
        return "", len(src), float(share)
    return _canon_league(top_lg), len(src), float(share)


def _sym_inter_probs(art: MLArtifact, blue_team: str, red_team: str, league_a: str, league_b: str) -> Tuple[float, float]:
    la = _canon_league(league_a)
    lb = _canon_league(league_b)
    ta = str(tier_for_league(la))
    tb = str(tier_for_league(lb))
    p_raw_f = float(
        art.model.p_blue(
            str(blue_team),
            str(red_team),
            blue_league=str(la),
            red_league=str(lb),
            blue_tier=ta,
            red_tier=tb,
        )
    )
    p_raw_r = float(
        art.model.p_blue(
            str(red_team),
            str(blue_team),
            blue_league=str(lb),
            red_league=str(la),
            blue_tier=tb,
            red_tier=ta,
        )
    )
    p_raw = 0.5 * (p_raw_f + (1.0 - p_raw_r))
    p_cal_f = float(art.calibrator.predict_proba(p_raw_f))
    p_cal_r = float(art.calibrator.predict_proba(p_raw_r))
    p_cal = 0.5 * (p_cal_f + (1.0 - p_cal_r))
    return float(clip_prob(p_raw)), float(clip_prob(p_cal))


def _ece(y_true: Iterable[int], probs: Iterable[float], bins: int = 10) -> float:
    ys = [(1 if int(y) == 1 else 0) for y in y_true]
    ps = [_safe_prob(p) for p in probs]
    n = len(ys)
    if n <= 0:
        return float("nan")
    b = max(2, int(bins))
    cnt = [0] * b
    sum_p = [0.0] * b
    sum_y = [0.0] * b
    for y, p in zip(ys, ps):
        idx = int(min(b - 1, max(0, math.floor(p * b))))
        cnt[idx] += 1
        sum_p[idx] += float(p)
        sum_y[idx] += float(y)
    e = 0.0
    for i in range(b):
        if cnt[i] <= 0:
            continue
        avg_p = sum_p[i] / float(cnt[i])
        avg_y = sum_y[i] / float(cnt[i])
        e += (float(cnt[i]) / float(n)) * abs(avg_y - avg_p)
    return float(e)


def _metrics(rows: List[Dict[str, Any]], key: str, bins: int = 10) -> Dict[str, Any]:
    ys: List[int] = []
    ps: List[float] = []
    for r in rows:
        if key not in r:
            continue
        ys.append(int(r.get("y", 0)))
        ps.append(_safe_prob(r.get(key), 0.5))
    if not ys:
        return {"n": 0, "logloss": None, "brier": None, "ece": None}
    return {
        "n": len(ys),
        "logloss": float(logloss(ys, ps)),
        "brier": float(brier(ys, ps)),
        "ece": float(_ece(ys, ps, bins=int(bins))),
    }


def _gain(pre: Dict[str, Any], post: Dict[str, Any]) -> Dict[str, Any]:
    ll_pre = _f(pre.get("logloss"))
    ll_post = _f(post.get("logloss"))
    br_pre = _f(pre.get("brier"))
    br_post = _f(post.get("brier"))
    ec_pre = _f(pre.get("ece"))
    ec_post = _f(post.get("ece"))
    return {
        "n": int(post.get("n") or pre.get("n") or 0),
        "pre": pre,
        "post": post,
        "gain_logloss": (float(ll_pre - ll_post) if math.isfinite(ll_pre) and math.isfinite(ll_post) else None),
        "gain_brier": (float(br_pre - br_post) if math.isfinite(br_pre) and math.isfinite(br_post) else None),
        "gain_ece": (float(ec_pre - ec_post) if math.isfinite(ec_pre) and math.isfinite(ec_post) else None),
    }


def _group_report(rows: List[Dict[str, Any]], group_key: str, bins: int) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        g = str(r.get(group_key) or "")
        if not g:
            continue
        groups[g].append(r)
    out: Dict[str, Any] = {}
    for g, rr in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out[g] = _gain(_metrics(rr, "p_pre", bins=bins), _metrics(rr, "p_post", bins=bins))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare hier calibration pre/post on inferred interleague matches.")
    ap.add_argument("--artifact", default=str(ROOT / "ml_artifact.json"))
    ap.add_argument("--baseline-post", default=str(ROOT / "ml_confidence_baseline.json"))
    ap.add_argument("--csv", dest="csvs", action="append", default=None, help="CSV path (repeatable).")
    ap.add_argument("--speed", default="fast", choices=["fast", "full"])
    ap.add_argument("--max-games", type=int, default=0, help="Cap processed games after load (0 disables).")
    ap.add_argument("--ece-bins", type=int, default=10)
    ap.add_argument("--min-hist-games", type=int, default=8)
    ap.add_argument("--min-share", type=float, default=0.55)
    ap.add_argument("--max-team-history", type=int, default=120)
    ap.add_argument("--out", default=str(ROOT / "hier_calibration_interleague_pre_post_compare.json"))
    args = ap.parse_args()

    art_path = Path(str(args.artifact))
    base_post_path = Path(str(args.baseline_post))
    if not art_path.exists():
        print(f"ERRO: artifact ausente: {art_path}")
        return 2
    if not base_post_path.exists():
        print(f"ERRO: baseline pos ausente: {base_post_path}")
        return 2

    csv_paths = list(args.csvs or []) or _default_csv_paths(ROOT)
    csv_paths = [str(Path(p)) for p in csv_paths if str(p).lower().endswith(".csv")]
    if not csv_paths:
        print("ERRO: nenhum CSV valido.")
        return 2

    art = MLArtifact.load_json(str(art_path))
    baseline_post = json.loads(base_post_path.read_text(encoding="utf-8"))
    if not isinstance(baseline_post, dict):
        print("ERRO: baseline pos invalido.")
        return 2
    baseline_pre = _baseline_pre_like(baseline_post)
    class_map = _league_class_map(baseline_post)

    g_parts: List[pd.DataFrame] = []
    for p in csv_paths:
        d = load_oracle_elixir_games(p, keep_playoffs=None)
        if d is not None and not d.empty:
            g_parts.append(d)
    if not g_parts:
        print("ERRO: sem jogos apos carga dos CSVs.")
        return 2
    games = _concat_non_empty_frames(g_parts)
    if games.empty:
        print("ERRO: sem jogos validos apos concat.")
        return 2
    games["date"] = pd.to_datetime(games["date"], errors="coerce")
    games = games.dropna(subset=["date"]).copy()
    games = games.sort_values(["date", "gameid"]).drop_duplicates(subset=["gameid"], keep="last").reset_index(drop=True)
    speed = str(args.speed or "fast").strip().lower()
    if speed == "fast" and len(games) > 24000:
        games = games.tail(24000).reset_index(drop=True)

    max_games = int(max(0, int(args.max_games or 0)))
    if max_games > 0 and len(games) > max_games:
        games = games.tail(max_games).reset_index(drop=True)

    bo_map = _build_bo_map(games)
    patch_seq = _patch_status_sequence(games)
    if len(patch_seq) != len(games):
        patch_seq = ["OK"] * len(games)

    team_hist: Dict[str, Deque[str]] = {}
    max_hist = max(20, int(args.max_team_history or 120))
    min_hist_games = max(3, int(args.min_hist_games or 8))
    min_share = max(0.40, min(0.95, float(args.min_share or 0.55)))
    rows_out: List[Dict[str, Any]] = []
    scope_pre = Counter()
    scope_post = Counter()
    skip_reason = Counter()
    infer_counts = Counter()

    for idx, g in enumerate(games.itertuples(index=False)):
        gameid = str(getattr(g, "gameid", ""))
        blue_team = str(getattr(g, "blue", "")).strip()
        red_team = str(getattr(g, "red", "")).strip()
        match_league = _canon_league(getattr(g, "league", ""))
        if (not blue_team) or (not red_team):
            skip_reason["missing_team_name"] += 1
            continue

        hist_b = team_hist.get(blue_team)
        if hist_b is None:
            hist_b = deque(maxlen=max_hist)
            team_hist[blue_team] = hist_b
        hist_r = team_hist.get(red_team)
        if hist_r is None:
            hist_r = deque(maxlen=max_hist)
            team_hist[red_team] = hist_r

        league_a, n_a, sh_a = _infer_origin_league(hist_b, min_hist_games=min_hist_games, min_share=min_share)
        league_b, n_b, sh_b = _infer_origin_league(hist_r, min_hist_games=min_hist_games, min_share=min_share)

        if not league_a:
            skip_reason["blue_origin_unknown"] += 1
        if not league_b:
            skip_reason["red_origin_unknown"] += 1
        if league_a and league_b and league_a == league_b:
            skip_reason["same_origin_league"] += 1

        if league_a and league_b and league_a != league_b:
            infer_counts["interleague"] += 1
            try:
                _, p_in = _sym_inter_probs(art, blue_team, red_team, league_a, league_b)
            except Exception:
                skip_reason["sym_inter_probs_error"] += 1
                p_in = float("nan")
            if not math.isfinite(_f(p_in)):
                skip_reason["invalid_p_in"] += 1
            else:
                y = int(getattr(g, "blue_win", 0))
                bo = int(bo_map.get(gameid, 1))
                po = bool(getattr(g, "playoffs", False))
                patch_status = str(patch_seq[idx])
                nte = float(min(len(hist_b), len(hist_r)))
                common_kwargs = {
                    "p_map_in": float(_safe_prob(p_in)),
                    "league": str(match_league or "INTER"),
                    "league_a": str(league_a),
                    "league_b": str(league_b),
                    "bo": int(bo),
                    "playoffs": bool(po),
                    "interregional": True,
                    "n_team_eff": float(max(0.0, nte)),
                    "n_players_eff": 0.0,
                    "patch_status": str(patch_status),
                }
                out_pre = apply_hier_calibration_live(baseline_payload=baseline_pre, **common_kwargs)
                out_post = apply_hier_calibration_live(baseline_payload=baseline_post, **common_kwargs)
                p_pre = _safe_prob(out_pre.get("p_after"), p_in) if bool(out_pre.get("applied", False)) else float(_safe_prob(p_in))
                p_post = _safe_prob(out_post.get("p_after"), p_in) if bool(out_post.get("applied", False)) else float(_safe_prob(p_in))
                scope_pre[str(out_pre.get("scope_used") or "")] += 1
                scope_post[str(out_post.get("scope_used") or "")] += 1

                seg_class = _segment_class_inter(league_a, league_b, class_map)
                seg_patch = f"{seg_class}|patch:{_patch_tag(patch_status)}"
                pair_und = "|".join(sorted([str(league_a), str(league_b)]))
                rows_out.append(
                    {
                        "y": int(y),
                        "p_pre": float(p_pre),
                        "p_post": float(p_post),
                        "segment_class": str(seg_class),
                        "segment_class_patch": str(seg_patch),
                        "league_pair": str(pair_und),
                        "league_dir": f"{league_a}->{league_b}",
                        "match_league": str(match_league),
                        "patch_tag": str(_patch_tag(patch_status)),
                        "blue_hist_n": int(n_a),
                        "red_hist_n": int(n_b),
                        "blue_hist_share": float(sh_a),
                        "red_hist_share": float(sh_b),
                    }
                )

        if match_league:
            hist_b.append(match_league)
            hist_r.append(match_league)

    global_pre = _metrics(rows_out, "p_pre", bins=int(args.ece_bins))
    global_post = _metrics(rows_out, "p_post", bins=int(args.ece_bins))
    by_class = _group_report(rows_out, "segment_class", bins=int(args.ece_bins))
    by_class_patch = _group_report(rows_out, "segment_class_patch", bins=int(args.ece_bins))
    by_pair = _group_report(rows_out, "league_pair", bins=int(args.ece_bins))

    rep = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "hier_calibration_interleague_pre_post_compare_v1",
        "inputs": {
            "artifact": str(art_path),
            "baseline_post": str(base_post_path),
            "csvs": [str(p) for p in csv_paths],
            "speed": str(speed),
            "max_games": int(max_games),
            "ece_bins": int(max(2, int(args.ece_bins or 10))),
            "min_hist_games": int(min_hist_games),
            "min_share": float(min_share),
            "max_team_history": int(max_hist),
        },
        "games_processed": len(games),
        "rows_total": len(rows_out),
        "global": _gain(global_pre, global_post),
        "by_segment_class": by_class,
        "by_segment_class_patch": by_class_patch,
        "by_league_pair": by_pair,
        "selection": {
            "interleague_detected": int(infer_counts.get("interleague", 0)),
            "skip_reasons": dict(sorted(skip_reason.items())),
        },
        "scope_usage": {
            "pre_top20": scope_pre.most_common(20),
            "post_top20": scope_post.most_common(20),
            "pre_unique": len(scope_pre),
            "post_unique": len(scope_post),
        },
    }
    out_path = Path(str(args.out))
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    g = rep.get("global") or {}
    print("OK: comparativo hier interleague pre/post concluido")
    print(f"- games_processed: {rep.get('games_processed')}")
    print(f"- rows_total: {rep.get('rows_total')}")
    print(
        "- gain global: logloss={:.6f} | brier={:.6f} | ece={:.6f}".format(
            float(g.get("gain_logloss") or 0.0),
            float(g.get("gain_brier") or 0.0),
            float(g.get("gain_ece") or 0.0),
        )
    )
    print(f"- report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
