from __future__ import annotations

import ast
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REQUIRED_CORE_COLS = ["gameid", "league", "date"]
TEAM_CANDIDATES = ["teamname", "team_name", "team", "teamid"]
SIDE_CANDIDATES = ["side", "team_side", "map_side"]
BO_CANDIDATES = ["best_of", "bo", "series_best_of"]
PLAYOFF_CANDIDATES = ["playoffs", "is_playoffs"]
PATCH_CANDIDATES = ["patch"]
POSITION_CANDIDATES = ["position", "role", "participant_position"]
RESULT_CANDIDATES = ["result", "game_won", "winner", "win", "blue_win"]
HIGH_RISK_RAW_OUTCOME_COLS = [
    "result",
    "game_won",
    "winner",
    "kills",
    "deaths",
    "assists",
    "gamelength",
    "game_length",
    "dragons",
    "barons",
    "towers",
]


def _default_csvs(root: Path) -> List[str]:
    out: List[str] = []
    for sub in ("CSV_HISTORICO", "CSV_DIARIO"):
        d = root / sub
        if d.exists():
            out.extend([str(p) for p in sorted(d.glob("*.csv")) if p.is_file()])
    return out


def _pick_col(cols: List[str], candidates: List[str]) -> str:
    lower = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return ""


def _oracle_team_rows_view(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Prefer team-level rows for label quality checks when OracleElixir player rows are present."""
    cols = [str(c) for c in df.columns]
    pos_col = _pick_col(cols, POSITION_CANDIDATES)
    if not pos_col:
        return df, "all_rows_no_position_col"
    try:
        pos = df[pos_col].astype(str).str.strip().str.lower()
    except Exception:
        return df, "all_rows_position_parse_error"
    if (pos == "team").any():
        return df.loc[pos == "team"].copy(), "team_rows_only"
    return df, "all_rows_no_team_position"


def _feature_schema_static_check(root: Path) -> Dict[str, Any]:
    files = [
        root / "app_core" / "style_matchup_core.py",
        root / "app_core" / "meta_blend_core.py",
        root / "app_core" / "state_strength_areal_core.py",
    ]
    text = "\n".join([p.read_text(encoding="utf-8", errors="ignore") for p in files if p.exists()])
    keyword_hits = []
    for k in HIGH_RISK_RAW_OUTCOME_COLS:
        if f'"{k}"' in text or f"'{k}'" in text:
            keyword_hits.append(k)

    feature_fn_tokens = ("feature", "build_", "make_")
    critical_hits: List[Dict[str, Any]] = []

    def _slice_str(node: ast.AST) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return str(node.value)
        if isinstance(node, ast.Index):  # py<3.9 compat
            val = getattr(node, "value", None)
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                return str(val.value)
        return ""

    class _Visitor(ast.NodeVisitor):
        def __init__(self, file_path: str) -> None:
            self.file_path = file_path
            self.fn_stack: List[str] = []

        def _in_feature_fn(self) -> bool:
            if not self.fn_stack:
                return False
            nm = str(self.fn_stack[-1]).lower()
            return any(tok in nm for tok in feature_fn_tokens)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self.fn_stack.append(str(node.name))
            self.generic_visit(node)
            self.fn_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            self.fn_stack.append(str(node.name))
            self.generic_visit(node)
            self.fn_stack.pop()

        def visit_Subscript(self, node: ast.Subscript) -> Any:
            if self._in_feature_fn():
                key = _slice_str(getattr(node, "slice", None))
                if key and str(key).lower() in {x.lower() for x in HIGH_RISK_RAW_OUTCOME_COLS}:
                    critical_hits.append(
                        {
                            "file": self.file_path,
                            "function": self.fn_stack[-1],
                            "line": int(getattr(node, "lineno", 0) or 0),
                            "kind": "subscript",
                            "column": key,
                        }
                    )
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> Any:
            if self._in_feature_fn():
                # Detect patterns like df.get("kills")
                fn = getattr(node, "func", None)
                if isinstance(fn, ast.Attribute) and str(fn.attr) == "get" and node.args:
                    a0 = node.args[0]
                    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                        key = str(a0.value)
                        if key.lower() in {x.lower() for x in HIGH_RISK_RAW_OUTCOME_COLS}:
                            critical_hits.append(
                                {
                                    "file": self.file_path,
                                    "function": self.fn_stack[-1],
                                    "line": int(getattr(node, "lineno", 0) or 0),
                                    "kind": "get",
                                    "column": key,
                                }
                            )
            self.generic_visit(node)

    for p in files:
        if not p.exists():
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(p))
            _Visitor(str(p)).visit(tree)
        except Exception:
            # non-fatal: static parsing issues should not silently reject
            pass

    return {
        "scanned_files": [str(p) for p in files if p.exists()],
        "keyword_hits": sorted(set(keyword_hits)),
        "critical_hits": critical_hits,
        "critical_hits_count": len(critical_hits),
        "note": "critical_hits only consider outcome-column accesses inside feature-builder-like functions.",
    }


def _check_team_game_consistency(
    *,
    df_labels: pd.DataFrame,
    team_col: str,
    side_col: str,
    result_col: str,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "checked": False,
        "games_checked": 0,
        "bad_side_games": 0,
        "bad_result_games": 0,
    }
    if ("gameid" not in df_labels.columns) or (not team_col):
        return out
    try:
        g = df_labels.copy()
        g["__gameid"] = g["gameid"].astype(str)
        g["__team"] = g[team_col].astype(str).fillna("").str.strip()
        g = g[g["__team"] != ""].copy()
        if g.empty:
            return out

        out["checked"] = True
        by_game = g.groupby("__gameid", dropna=False)
        out["games_checked"] = int(by_game.ngroups)

        if side_col:
            gs = g.copy()
            gs["__side"] = gs[side_col].astype(str).str.strip().str.lower()
            bad_side_games = 0
            for _gid, gg in gs.groupby("__gameid", dropna=False):
                sides = set([s for s in gg["__side"].tolist() if s in {"blue", "red", "b", "r"}])
                # team-level view should have both sides in most complete games
                if len(gg) >= 2 and len(sides) < 2:
                    bad_side_games += 1
            out["bad_side_games"] = int(bad_side_games)

        if result_col:
            gr = g.copy()
            rv = pd.to_numeric(gr[result_col], errors="coerce")
            gr["__r"] = rv
            bad_result_games = 0
            for _gid, gg in gr.groupby("__gameid", dropna=False):
                rr = gg["__r"].dropna()
                if len(rr) >= 2:
                    s = float(rr.sum())
                    # for team-level rows with binary result, sum should be close to 1
                    if not (0.5 <= s <= 1.5):
                        bad_result_games += 1
            out["bad_result_games"] = int(bad_result_games)
    except Exception:
        return out
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Leakage/label quality checks for Oracle CSVs.")
    ap.add_argument("--csv", action="append", default=[])
    ap.add_argument("--out", default="data_leakage_label_report.json")
    args = ap.parse_args()

    csvs = [str(Path(x)) for x in (args.csv or []) if str(x).strip()]
    if not csvs:
        csvs = _default_csvs(ROOT)

    rows_total = 0
    files_ok = 0
    files_fail = 0
    file_reports: List[Dict[str, Any]] = []
    all_cols: set[str] = set()
    label_issues_total = 0
    critical_issues_total = 0

    for p_s in csvs:
        p = Path(p_s)
        rep: Dict[str, Any] = {"path": str(p), "ok": False, "errors": [], "warnings": []}
        if not p.exists():
            rep["errors"].append("missing_file")
            files_fail += 1
            file_reports.append(rep)
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception as e:
            rep["errors"].append(f"read_error:{e}")
            files_fail += 1
            file_reports.append(rep)
            continue
        cols = [str(c) for c in df.columns]
        all_cols.update(cols)
        rep["rows"] = len(df)
        rows_total += len(df)
        rep["columns"] = len(cols)
        df_labels, label_view_mode = _oracle_team_rows_view(df)
        rep["label_view_mode"] = label_view_mode
        rep["label_rows"] = len(df_labels)

        missing_core = [c for c in REQUIRED_CORE_COLS if c.lower() not in {x.lower() for x in cols}]
        if missing_core:
            rep["errors"].append(f"missing_core_cols:{','.join(missing_core)}")
            critical_issues_total += 1

        team_col = _pick_col(cols, TEAM_CANDIDATES)
        side_col = _pick_col(cols, SIDE_CANDIDATES)
        bo_col = _pick_col(cols, BO_CANDIDATES)
        playoffs_col = _pick_col(cols, PLAYOFF_CANDIDATES)
        patch_col = _pick_col(cols, PATCH_CANDIDATES)
        result_col = _pick_col(cols, RESULT_CANDIDATES)
        rep["label_cols"] = {
            "team": team_col or None,
            "side": side_col or None,
            "bo": bo_col or None,
            "playoffs": playoffs_col or None,
            "patch": patch_col or None,
            "result": result_col or None,
        }

        if team_col:
            s = df_labels[team_col].astype(str).fillna("").str.strip()
            empty_team = int((s == "").sum())
            rep["empty_team_rows"] = empty_team
            if empty_team > 0:
                rep["warnings"].append(f"empty_team_rows:{empty_team}")
                label_issues_total += 1
        else:
            rep["warnings"].append("missing_team_col")
            label_issues_total += 1

        if side_col:
            vals = df_labels[side_col].astype(str).str.strip().str.lower()
            counts = vals.value_counts(dropna=False).to_dict()
            rep["side_counts"] = {str(k): int(v) for k, v in counts.items()}
            known = {"blue", "red", "b", "r"}
            unknown = int((~vals.isin(list(known)) & (vals != "")).sum())
            if unknown > 0:
                rep["warnings"].append(f"unknown_side_rows:{unknown}")
                label_issues_total += 1
        else:
            rep["warnings"].append("missing_side_col")
            label_issues_total += 1

        if bo_col:
            bo_vals = pd.to_numeric(df_labels[bo_col], errors="coerce")
            bo_counts = bo_vals.value_counts(dropna=False).to_dict()
            rep["bo_counts"] = {("nan" if pd.isna(k) else str(int(k))): int(v) for k, v in bo_counts.items()}
            invalid_bo = int((~bo_vals.isin([1, 3, 5]) & bo_vals.notna()).sum())
            if invalid_bo > 0:
                rep["warnings"].append(f"invalid_bo_rows:{invalid_bo}")
                label_issues_total += 1
        else:
            rep["warnings"].append("missing_bo_col")
            # OracleElixir exports often omit explicit BO and require inference outside the CSV.
            rep["bo_missing_informational"] = True
            # Informational only: do not count as label issue by default.

        if playoffs_col:
            pv = df_labels[playoffs_col].astype(str).str.strip().str.lower()
            rep["playoffs_counts"] = {str(k): int(v) for k, v in pv.value_counts(dropna=False).to_dict().items()}

        if "gameid" in df_labels.columns:
            dup_gameid_rows = int(df_labels.duplicated(subset=["gameid"]).sum())
            rep["duplicate_gameid_rows"] = dup_gameid_rows
            # Oracle can legitimately have multiple rows per game; only warn if very high without team column
            if dup_gameid_rows > 0 and not team_col:
                rep["warnings"].append(f"duplicate_gameid_rows_no_team_col:{dup_gameid_rows}")
                label_issues_total += 1

        if team_col and "gameid" in df_labels.columns:
            dup_game_team = int(df_labels.duplicated(subset=["gameid", team_col]).sum())
            rep["duplicate_gameid_team_rows"] = dup_game_team
            if dup_game_team > 0:
                rep["warnings"].append(f"duplicate_gameid_team_rows:{dup_game_team}")
                label_issues_total += 1

        _cons = _check_team_game_consistency(
            df_labels=df_labels,
            team_col=team_col,
            side_col=side_col,
            result_col=result_col,
        )
        rep["game_consistency"] = _cons
        bad_side_games = int(_cons.get("bad_side_games") or 0)
        bad_result_games = int(_cons.get("bad_result_games") or 0)
        games_checked = int(_cons.get("games_checked") or 0)
        bad_side_rate = (float(bad_side_games) / float(games_checked)) if games_checked > 0 else 0.0
        bad_result_rate = (float(bad_result_games) / float(games_checked)) if games_checked > 0 else 0.0
        rep["game_consistency_rates"] = {
            "bad_side_rate": float(bad_side_rate),
            "bad_result_rate": float(bad_result_rate),
        }
        # Tolerate tiny noise in historical labels; escalate only above threshold.
        if bad_side_rate > 0.002:
            rep["warnings"].append(f"bad_side_games:{bad_side_games}")
            label_issues_total += 1
        if bad_result_rate > 0.002:
            rep["warnings"].append(f"bad_result_games:{bad_result_games}")
            label_issues_total += 1

        rep["ok"] = len(rep["errors"]) == 0
        files_ok += int(rep["ok"])
        files_fail += int(not rep["ok"])
        file_reports.append(rep)

    cols_lower = {c.lower() for c in all_cols}
    risk_cols_present = sorted([c for c in HIGH_RISK_RAW_OUTCOME_COLS if c.lower() in cols_lower])
    static_schema = _feature_schema_static_check(ROOT)

    decision = "promote"
    reasons: List[str] = []
    if critical_issues_total > 0 or files_fail > 0:
        decision = "reject"
        reasons.append("critical_file_or_schema_issue")
    elif int(static_schema.get("critical_hits_count") or 0) > 0:
        decision = "reject"
        reasons.append("feature_schema_leakage_risk")
    elif label_issues_total > 0:
        decision = "shadow_only"
        reasons.append("label_quality_warnings_present")

    report = {
        "version": "data_leakage_label_v2",
        "summary": {
            "csv_files": len(csvs),
            "files_ok": files_ok,
            "files_fail": files_fail,
            "rows_total": rows_total,
            "label_issues_total": label_issues_total,
            "critical_issues_total": critical_issues_total,
        },
        "decision": decision,
        "reasons": reasons,
        "leakage_risk": {
            "high_risk_raw_columns_present": risk_cols_present,
            "feature_schema_static_check": static_schema,
            "note": "Presenca em CSV nao implica leakage. O risco critico e usar esses campos como feature pre-jogo.",
        },
        "files": file_reports,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: leakage/label report saved -> {args.out} | decision={decision} | "
        f"files_ok={files_ok}/{len(csvs)} rows={rows_total}"
    )
    return 0 if decision == "promote" else (1 if decision == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
