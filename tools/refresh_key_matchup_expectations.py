from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.anchor_regression_suite import _odd_for_case_app  # uses app-final pipeline


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return {}


def _round(x: float, nd: int = 3) -> float:
    return float(round(float(x), int(nd)))


def main() -> int:
    ap = argparse.ArgumentParser(description='Refresh key matchup expectation ranges from current app pipeline odds.')
    ap.add_argument('--expectations', default='ops/key_matchup_expectations.json')
    ap.add_argument('--out', default='')
    ap.add_argument('--timeout', type=int, default=300)
    ap.add_argument('--default-tolerance-pct', type=float, default=0.12)
    ap.add_argument('--min-odd-floor', type=float, default=1.01)
    ap.add_argument('--round-ndigits', type=int, default=3)
    args = ap.parse_args()

    exp_path = Path(args.expectations)
    data = _load_json(exp_path)
    cases: List[Dict[str, Any]] = list(data.get('cases', []) if isinstance(data, dict) else [])

    updated: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for c in cases:
        row = dict(c)
        try:
            team_a = str(row.get('team_a') or '')
            team_b = str(row.get('team_b') or '')
            market = str(row.get('market') or 'bo5')
            side = str(row.get('side') or 'a')
            tol = float(row.get('tolerance_pct') if row.get('tolerance_pct') is not None else args.default_tolerance_pct)
            tol = max(0.01, min(0.50, tol))
            odd = float(_odd_for_case_app(ROOT, team_a, team_b, market, side, int(args.timeout)))
            lo = max(float(args.min_odd_floor), odd * (1.0 - tol))
            hi = odd * (1.0 + tol)
            row['baseline_odd'] = _round(odd, args.round_ndigits)
            row['tolerance_pct'] = _round(tol, 4)
            row['min_odd'] = _round(lo, args.round_ndigits)
            row['max_odd'] = _round(hi, args.round_ndigits)
            row['refreshed_from'] = 'app_pipeline'
            row['refresh_ok'] = True
        except Exception as e:
            row['refresh_ok'] = False
            row['refresh_error'] = str(e)
            errors.append({'name': str(row.get('name') or ''), 'error': str(e)})
        updated.append(row)

    out_data = {'cases': updated}
    out_path = Path(args.out) if str(args.out).strip() else exp_path
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({
        'ok': len(errors) == 0,
        'updated_cases': len(updated),
        'errors': len(errors),
        'out': str(out_path),
    }, ensure_ascii=False))
    if errors:
        for e in errors:
            print(f"[refresh_error] {e['name']}: {e['error']}")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
