# -*- coding: utf-8 -*-
"""Baixa os ícones dos campeões (Data Dragon, Riot) para champ_icons/<id>.png.

Rodar uma vez (e de novo quando sair campeão novo). O grid de draft do Radar
usa esses arquivos; sem eles, cai graciosamente em botões só com o nome.

Uso: python tools/fetch_champion_icons.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "champ_icons"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    versions = json.loads(_get("https://ddragon.leagueoflegends.com/api/versions.json"))
    ver = str(versions[0])
    print(f"Data Dragon {ver}")
    reg = json.loads((ROOT / "champion_knowledge_registry.json").read_text(encoding="utf-8"))
    champs = reg.get("champions") or {}
    ok = skip = fail = 0
    for key, entry in sorted(champs.items()):
        cid = str(entry.get("id") or "").strip()
        if not cid:
            print(f"  sem id: {key}")
            fail += 1
            continue
        dest = OUT / f"{cid}.png"
        if dest.exists() and dest.stat().st_size > 500:
            skip += 1
            continue
        url = f"https://ddragon.leagueoflegends.com/cdn/{ver}/img/champion/{cid}.png"
        try:
            dest.write_bytes(_get(url))
            ok += 1
        except Exception as exc:
            print(f"  FALHOU {cid}: {exc}")
            fail += 1
    print(f"baixados {ok} | já existiam {skip} | falhas {fail} | total {len(champs)}")


if __name__ == "__main__":
    sys.exit(main())
