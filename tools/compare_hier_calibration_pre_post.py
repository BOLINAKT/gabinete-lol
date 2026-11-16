from __future__ import annotations

import argparse
import copy
import json
import math
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.hier_calibration_core import apply_hier_calibration_live
from mlcore.artifact import MLArtifact
from mlcore.league_context import league_macro_key
from mlcore.players_layer import PlayersArtifact
from mlcore.utils import brier, clip_prob, logloss, safe_float as _f
from tools.backtest_pipeline_abc_by_league import _default_csv_paths, _iter_replay_rows, _load_params


def _i(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def _safe_prob(p: Any, default: float = 0.5) -> float:
    try:
        v = float(p)
    except Exception:
        return float(default)
    if not math.isfinite(v):
        return float(default)
    return float(clip_prob(v))


def _patch_tag(v: Any) -> str:
    s = str(v or "").strip().upper()
    if "REFIT" in s:
        return "refit"
    if "WARN" in s:
        return "warn"
    return "ok"


def _macro_group(league: str) -> str:
    return str(league_macro_key(str(league or ""), unknown="OTHER"))


def _infer_league_class(league: str, node: Dict[str, Any]) -> str:
    macro = _macro_group(league)
    n_eff = max(_i(node.get("n_eff")), _i(node.get("wf_n")), _i(node.get("lv_n")), _i(node.get("n_total")))
    qb = str(node.get("quality_band") or "").strip().lower()
    strong_q = qb in {"strong", "good"}
    ok_q = qb in {"strong", "good", "ok"}
    if macro in {"KR", "CN"} and n_eff >= 500 and ok_q:
        return "major"
    if macro in {"EMEA", "NA", "BR", "APAC"} and n_eff >= 800 and strong_q:
        return "major"
    if n_eff >= 1300 and strong_q:
        return "major"
    return "minor"


def _league_class_map(baseline: Dict[str, Any]) -> Dict[str, str]:
    by_league = baseline.get("by_league") if isinstance(baseline.get("by_league"), dict) else {}
    out: Dict[str, str] = {}
    explicit = baseline.get("league_class") if isinstance(baseline.get("league_class"), dict) else {}
    for lg, cls in explicit.items():
        c = str(cls or "").strip().lower()
        if c in {"major", "minor"}:
            out[str(lg).strip().upper()] = c
    for lg, node in by_league.items():
        key = str(lg or "").strip().upper()
        if (not key) or key in out or not isinstance(node, dict):
            continue
        out[key] = _infer_league_class(key, node)
    return out


def _baseline_pre_like(post_baseline: Dict[str, Any]) -> Dict[str, Any]:
    b = copy.deepcopy(post_baseline if isinstance(post_baseline, dict) else {})
    by_seg = b.get("by_segment") if isinstance(b.get("by_segment"), dict) else {}
    by_seg_pre = {
        str(k): v
        for k, v in by_seg.items()
        if (not str(k).startswith("class:")) and ("|patch:" not in str(k))
    }
    b["by_segment"] = by_seg_pre
    b.pop("league_class", None)
    return b


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
    ece = 0.0
    for i in range(b):
        if cnt[i] <= 0:
            continue
        avg_p = sum_p[i] / float(cnt[i])
        avg_y = sum_y[i] / float(cnt[i])
        ece += (float(cnt[i]) / float(n)) * abs(avg_y - avg_p)
    return float(ece)


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
    out: Dict[str, Any] = {
        "n": int(post.get("n") or pre.get("n") or 0),
        "pre": pre,
        "post": post,
        "gain_logloss": (float(ll_pre - ll_post) if math.isfinite(ll_pre) and math.isfinite(ll_post) else None),
        "gain_brier": (float(br_pre - br_post) if math.isfinite(br_pre) and math.isfinite(br_post) else None),
        "gain_ece": (float(ec_pre - ec_post) if math.isfinite(ec_pre) and math.isfinite(ec_post) else None),
    }
    return out


def _group_report(rows: List[Dict[str, Any]], group_key: str, bins: int) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        g = str(r.get(group_key) or "")
        if not g:
            continue
        groups[g].append(r)
    out: Dict[str, Any] = {}
    for g, rr in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        pre_m = _metrics(rr, "p_pre", bins=bins)
        post_m = _metrics(rr, "p_post", bins=bins)
        out[g] = _gain(pre_m, post_m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare pre/post hier calibration by segment on replay rows.")
    ap.add_argument("--artifact", default=str(ROOT / "ml_artifact.json"))
    ap.add_argument("--players-artifact", default=str(ROOT / "players_artifact.json"))
    ap.add_argument("--params", default=str(ROOT / "params_fitted.json"))
    ap.add_argument("--baseline-post", default=str(ROOT / "ml_confidence_baseline.json"))
    ap.add_argument("--csv", dest="csvs", action="append", default=None, help="CSV path (repeatable).")
    ap.add_argument("--speed", default="fast", choices=["fast", "full"])
    ap.add_argument("--max-rows", type=int, default=15000)
    ap.add_argument("--ece-bins", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "hier_calibration_pre_post_compare.json"))
    args = ap.parse_args()

    art_path = Path(str(args.artifact))
    p_art_path = Path(str(args.players_artifact))
    params_path = Path(str(args.params))
    base_post_path = Path(str(args.baseline_post))
    if not art_path.exists():
        print(f"ERRO: artifact ausente: {art_path}")
        return 2
    if not p_art_path.exists():
        print(f"ERRO: players_artifact ausente: {p_art_path}")
        return 2
    if not params_path.exists():
        print(f"ERRO: params_fitted ausente: {params_path}")
        return 2
    if not base_post_path.exists():
        print(f"ERRO: baseline pos ausente: {base_post_path}")
        return 2

    csv_paths = list(args.csvs or []) or _default_csv_paths(ROOT)
    csv_paths = [str(Path(p)) for p in csv_paths if str(p).lower().endswith(".csv")]
    if not csv_paths:
        print("ERRO: nenhum CSV válido.")
        return 2

    art = MLArtifact.load_json(str(art_path))
    p_art = PlayersArtifact.load_json(str(p_art_path))
    params = _load_params(params_path)
    baseline_post = json.loads(base_post_path.read_text(encoding="utf-8"))
    if not isinstance(baseline_post, dict):
        print("ERRO: baseline pós inválido.")
        return 2
    baseline_pre = _baseline_pre_like(baseline_post)
    class_map = _league_class_map(baseline_post)

    rows_in = _iter_replay_rows(
        art=art,
        p_art=p_art,
        params=params,
        csv_paths=csv_paths,
        max_rows=int(max(0, int(args.max_rows or 0))),
        speed_profile=str(args.speed or "fast"),
    )
    rows_out: List[Dict[str, Any]] = []
    scope_pre = Counter()
    scope_post = Counter()
    for r in rows_in:
        p_in = _safe_prob(r.get("p_final"), 0.5)
        y = int(r.get("y", 0))
        lg = str(r.get("league") or "").strip().upper()
        bo = _i(r.get("bo"), 1)
        po = (str(r.get("phase") or "").strip().lower() == "playoffs")
        patch = str(r.get("patch_status") or "")
        n_team = _f(r.get("n_team"), 0.0)
        n_players = _f(r.get("n_players"), 0.0)
        common_kwargs = {
            "p_map_in": float(p_in),
            "league": str(lg),
            "league_a": str(lg),
            "league_b": str(lg),
            "bo": int(bo),
            "playoffs": bool(po),
            "interregional": False,
            "n_team_eff": float(max(0.0, n_team)),
            "n_players_eff": float(max(0.0, n_players)),
            "patch_status": str(patch),
        }
        out_pre = apply_hier_calibration_live(baseline_payload=baseline_pre, **common_kwargs)
        out_post = apply_hier_calibration_live(baseline_payload=baseline_post, **common_kwargs)
        p_pre = _safe_prob(out_pre.get("p_after"), p_in) if bool(out_pre.get("applied", False)) else float(p_in)
        p_post = _safe_prob(out_post.get("p_after"), p_in) if bool(out_post.get("applied", False)) else float(p_in)
        scope_pre[str(out_pre.get("scope_used") or "")] += 1
        scope_post[str(out_post.get("scope_used") or "")] += 1

        cls = str(class_map.get(lg, "minor"))
        seg_class = f"same_{'major' if cls == 'major' else 'minor'}"
        seg_patch = f"{seg_class}|patch:{_patch_tag(patch)}"
        rows_out.append(
            {
                "y": int(y),
                "p_pre": float(p_pre),
                "p_post": float(p_post),
                "segment_class": str(seg_class),
                "segment_class_patch": str(seg_patch),
                "league": str(lg),
                "patch_tag": str(_patch_tag(patch)),
            }
        )

    global_pre = _metrics(rows_out, "p_pre", bins=int(args.ece_bins))
    global_post = _metrics(rows_out, "p_post", bins=int(args.ece_bins))
    by_class = _group_report(rows_out, "segment_class", bins=int(args.ece_bins))
    by_class_patch = _group_report(rows_out, "segment_class_patch", bins=int(args.ece_bins))

    rep = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "hier_calibration_pre_post_compare_v1",
        "inputs": {
            "artifact": str(art_path),
            "players_artifact": str(p_art_path),
            "params": str(params_path),
            "baseline_post": str(base_post_path),
            "csvs": [str(p) for p in csv_paths],
            "speed": str(args.speed or "fast"),
            "max_rows": int(max(0, int(args.max_rows or 0))),
            "ece_bins": int(max(2, int(args.ece_bins or 10))),
        },
        "rows_total": len(rows_out),
        "global": _gain(global_pre, global_post),
        "by_segment_class": by_class,
        "by_segment_class_patch": by_class_patch,
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
    print("OK: comparativo hier pre/post concluído")
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
