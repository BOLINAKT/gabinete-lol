# -*- coding: utf-8 -*-
"""Baixa logos dos times da season atual (Leaguepedia) para logos/<norm>.png,
no formato que team_logos_core resolve (nome minúsculo, só [a-z0-9]).

Tenta os padrões de arquivo da Leaguepedia ("<Time>logo square.png" e
"<Time>logo std.png") via API MediaWiki. Times sem logo continuam no badge
de iniciais — nada quebra. Rodar de novo é idempotente (pula os que existem).

Uso: python tools/fetch_team_logos.py [--year 2026]
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
API = "https://lol.fandom.com/api.php"


def _norm(team: str) -> str:
    s = str(team or "").strip().lower()
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", s)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _file_url(filename: str) -> str | None:
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "imageinfo",
        "iiprop": "url", "titles": f"File:{filename}",
    })
    try:
        data = json.loads(_get(f"{API}?{params}"))
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = page.get("imageinfo") or []
            if info and info[0].get("url"):
                return str(info[0]["url"])
    except Exception:
        return None
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()

    import pandas as pd
    csvs = sorted((ROOT / "CSV_DIARIO").glob(f"{args.year}_*OraclesElixir*.csv")) or \
        sorted((ROOT / "CSV_HISTORICO").glob(f"{args.year}_*OraclesElixir*.csv"))
    if not csvs:
        print(f"sem CSV {args.year}")
        return
    df = pd.read_csv(csvs[0], usecols=["teamname"], low_memory=False)
    teams = sorted({str(t).strip() for t in df["teamname"].dropna() if str(t).strip() and str(t) != "unknown team"})
    print(f"{len(teams)} times na season {args.year}")

    out_dir = ROOT / "logos"
    out_dir.mkdir(exist_ok=True)
    ok = skip = miss = 0
    misses: list[str] = []
    for team in teams:
        key = _norm(team)
        if not key:
            continue
        dest = out_dir / f"{key}.png"
        if dest.exists() and dest.stat().st_size > 500:
            skip += 1
            continue
        url = None
        for pattern in (f"{team}logo square.png", f"{team}logo std.png", f"{team}logo profile.png"):
            url = _file_url(pattern)
            if url:
                break
        if not url:
            miss += 1
            misses.append(team)
            continue
        try:
            dest.write_bytes(_get(url))
            ok += 1
            print(f"  ok  {team} -> {dest.name}")
        except Exception as exc:
            miss += 1
            misses.append(f"{team} ({exc})")
    print(f"\nbaixadas {ok} | já existiam {skip} | sem logo {miss}")
    if misses:
        print("faltaram (nome não bate com a Leaguepedia — dá pra salvar manual em logos/):")
        for m in misses:
            print("  -", str(m).encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    sys.exit(main())
