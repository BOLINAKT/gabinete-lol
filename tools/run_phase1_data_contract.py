from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _run_cmd(args: List[str], timeout: int = 300) -> Tuple[int, str]:
    try:
        cp = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=int(timeout),
        )
        out = (str(cp.stdout or "") + ("\n" + str(cp.stderr or "") if cp.stderr else "")).strip()
        return int(cp.returncode), (out or "-")
    except Exception as e:
        return 2, f"exception:{type(e).__name__}:{e}"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}
    return {}


def _default_csvs(root: Path) -> List[Path]:
    out: List[Path] = []
    for sub in ("CSV_DIARIO", "CSV_HISTORICO"):
        d = root / sub
        if d.exists():
            out.extend(sorted([p for p in d.glob("*.csv") if p.is_file()]))
    return out


def _coverage(csv_paths: List[Path]) -> Dict[str, Any]:
    leagues: Dict[str, int] = {}
    rows = 0
    files_ok = 0
    team_blank = 0
    team_rows = 0
    errors: List[str] = []

    for p in csv_paths:
        try:
            df = pd.read_csv(p, low_memory=False)
        except Exception as e:
            errors.append(f"{p.name}:read_error:{e}")
            continue
        files_ok += 1
        rows += len(df)
        cols = {str(c).lower(): str(c) for c in df.columns}
        lg_col = cols.get("league")
        if lg_col:
            vc = df[lg_col].fillna("").astype(str).str.strip().str.upper().value_counts()
            for k, v in vc.to_dict().items():
                if k:
                    leagues[k] = int(leagues.get(k, 0) + int(v))

        if "blue" in cols and "red" in cols:
            b = df[cols["blue"]].fillna("").astype(str).str.strip()
            r = df[cols["red"]].fillna("").astype(str).str.strip()
            team_rows += int(2 * len(df))
            team_blank += int((b == "").sum() + (r == "").sum())
        elif "team" in cols and "opponent" in cols:
            a = df[cols["team"]].fillna("").astype(str).str.strip()
            b = df[cols["opponent"]].fillna("").astype(str).str.strip()
            team_rows += int(2 * len(df))
            team_blank += int((a == "").sum() + (b == "").sum())
        elif "teamname" in cols:
            a = df[cols["teamname"]].fillna("").astype(str).str.strip()
            team_rows += len(df)
            team_blank += int((a == "").sum())

    blank_rate = (float(team_blank) / float(team_rows)) if team_rows > 0 else 0.0
    low_sample_leagues = int(sum(1 for _k, v in leagues.items() if int(v) < 30))
    league_count = len(leagues)

    decision = "promote"
    reasons: List[str] = []
    if errors:
        decision = "shadow_only"
        reasons.append("csv_read_errors")
    if league_count < 10:
        decision = "shadow_only"
        reasons.append("league_count_low")
    if blank_rate > 0.001:
        decision = "reject"
        reasons.append("blank_team_rate_high")
    elif low_sample_leagues > 10 and decision == "promote":
        decision = "shadow_only"
        reasons.append("many_low_sample_leagues")

    return {
        "decision": decision,
        "reasons": reasons,
        "summary": {
            "files_ok": int(files_ok),
            "files_total": len(csv_paths),
            "rows_total": int(rows),
            "league_count": int(league_count),
            "low_sample_leagues_lt30": int(low_sample_leagues),
            "team_rows": int(team_rows),
            "blank_team_rows": int(team_blank),
            "blank_team_rate": float(blank_rate),
        },
        "top_leagues": sorted(
            [{"league": k, "rows": int(v)} for k, v in leagues.items()],
            key=lambda x: int(x["rows"]),
            reverse=True,
        )[:25],
        "errors": errors[:20],
    }


def _rank(v: str) -> int:
    return {"promote": 0, "shadow_only": 1, "reject": 2}.get(str(v or ""), 1)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase-1 data contract gate (leakage + label + coverage).")
    ap.add_argument("--out", default="phase1_data_contract_report.json")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--skip-leakage-run", action="store_true")
    args = ap.parse_args()

    logs: List[str] = []
    if not bool(args.skip_leakage_run):
        rc, out = _run_cmd([sys.executable, "tools/check_data_leakage_and_labels.py"], timeout=int(args.timeout))
        logs.append(f"$ check_data_leakage_and_labels rc={rc}\n{out}")

    leak = _read_json(ROOT / "data_leakage_label_report.json")
    cov = _coverage(_default_csvs(ROOT))

    leak_dec = str(leak.get("decision") or "shadow_only")
    cov_dec = str(cov.get("decision") or "shadow_only")
    final = max([leak_dec, cov_dec], key=_rank)
    reasons: List[str] = []
    if leak_dec != "promote":
        reasons.append(f"leakage_labels:{leak_dec}")
    if cov_dec != "promote":
        reasons.append(f"coverage:{cov_dec}")

    rep = {
        "version": "phase1_data_contract_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": final,
        "reasons": reasons,
        "parts": {
            "leakage_labels": leak_dec,
            "coverage": cov_dec,
        },
        "leakage_labels_report": leak,
        "coverage_report": cov,
        "run_log": "\n\n".join(logs),
    }
    out_path = ROOT / str(args.out)
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"OK: phase1 data contract -> {out_path.name} | decision={final} | "
        f"leak={leak_dec} cov={cov_dec}"
    )
    return 0 if final == "promote" else (1 if final == "shadow_only" else 2)


if __name__ == "__main__":
    raise SystemExit(main())

