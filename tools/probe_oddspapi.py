"""Probe do OddsPapi — decide se a alavanca J (Elo+odds) e o CLV destravam.

Responde com dados reais:
  1) COBERTURA: quantas partidas de LoL com odds existem por janela/liga?
  2) PROFUNDIDADE: até quando volta o histórico (2024? 2025?)?
  3) QUALIDADE: as odds históricas têm timestamps (dá pra pegar CLOSING line?)
     e casas decentes (Pinnacle etc.)?

  python tools/probe_oddspapi.py --api-key SUA_CHAVE
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.oddspapi.io/v4"
SPORT_ID_LOL = 18


def _get(path: str, **params) -> dict | list | None:
    qs = urllib.parse.urlencode(params)
    url = f"{BASE}/{path}?{qs}"
    # Cloudflare (error 1010) bloqueia o UA padrão do urllib; UA de navegador resolve.
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read()[:300]
        print(f"  [HTTP {e.code}] {path}: {body!r}")
        return None
    except Exception as e:
        print(f"  [erro] {path}: {type(e).__name__}: {e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe OddsPapi (LoL odds históricas).")
    ap.add_argument("--api-key", required=True)
    args = ap.parse_args()
    key = str(args.api_key).strip()

    # Janelas de teste: recente, 6 meses atrás, 1 ano, 2 anos.
    windows = [
        ("recente (jun/2026)", "2026-06-06", "2026-06-14"),
        ("6 meses (jan/2026)", "2026-01-14", "2026-01-22"),
        ("1 ano (jun/2025)", "2025-06-06", "2025-06-14"),
        ("2 anos (jun/2024)", "2024-06-06", "2024-06-14"),
    ]
    sample_fixture = None
    for label, d0, d1 in windows:
        data = _get("fixtures", apiKey=key, sportId=SPORT_ID_LOL, hasOdds="true", **{"from": d0, "to": d1})
        n = len(data) if isinstance(data, list) else (len(data.get("fixtures", data or [])) if isinstance(data, dict) else 0)
        rows = data if isinstance(data, list) else (data.get("fixtures") if isinstance(data, dict) else []) or []
        leagues: dict[str, int] = {}
        for f in rows:
            lg = str((f or {}).get("league", (f or {}).get("tournament", "?")))[:30]
            leagues[lg] = leagues.get(lg, 0) + 1
            if sample_fixture is None:
                sample_fixture = f
        top = ", ".join(f"{k}({v})" for k, v in sorted(leagues.items(), key=lambda kv: -kv[1])[:6])
        print(f"[{label}] partidas com odds: {n} | ligas: {top or '-'}")
        time.sleep(2)

    if isinstance(sample_fixture, dict):
        fid = sample_fixture.get("fixtureId") or sample_fixture.get("id")
        print(f"\n[amostra] fixture={fid} | {json.dumps(sample_fixture, ensure_ascii=False)[:400]}")
        if fid:
            time.sleep(2)
            hist = _get("historical-odds", apiKey=key, fixtureId=fid)
            if hist is not None:
                s = json.dumps(hist, ensure_ascii=False)
                print(f"\n[historico da amostra] {s[:900]}")
                for marker in ("pinnacle", "Pinnacle", "timestamp", "updatedAt", "time"):
                    print(f"  contem '{marker}': {marker in s}")
    print("\nProbe concluido. Critério: >=2 janelas antigas com partidas + timestamps no histórico = alavanca J destravada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
