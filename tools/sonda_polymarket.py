# -*- coding: utf-8 -*-
"""SONDA DA POLYMARKET: como ela organiza o LoL, e o que da para comparar? (23/10/2026)

Pedido dele: a Polymarket como segunda referencia ao lado da Pinnacle, na tela
de oportunidades. Antes de escrever coletor, MEDIR: os dominios da Polymarket
nao resolvem no Brasil (DNS, conferido em 23/10 no PC dele e na ferramenta de
leitura web), entao esta sonda roda no robo do GitHub (EUA) e grava o que viu
em evidence/sonda_polymarket.json. Nada aqui e decisao; e reconhecimento.

API usada: Gamma, publica, sem chave (https://gamma-api.polymarket.com). Os
nomes dos parametros vieram de clientes de terceiros (a documentacao oficial
tambem nao abre daqui) -- por isso a sonda tenta varios e registra o que
respondeu, em vez de confiar:
  /sports                     metadados por esporte (tag do LoL, se houver)
  /tags?limit=...             procurar slug com lol/league/esports
  /events?tag_slug=...|tag_id=...&closed=false   eventos abertos
  /markets?...                 mercados (precos em outcomePrices)

FONTES (pagina oficial NAO abriu daqui; o que foi lido):
  - busca de 23/10/2026 resumindo clientes da Gamma API: polyte-gamma (docs.rs),
    polyoxide-gamma (docs.rs), cliente OCaml (ocaml.org/p/polymarket) -- base
    gamma-api.polymarket.com, publica, /events, /tags, /markets, /sports, /teams.

Uso: python tools/sonda_polymarket.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://gamma-api.polymarket.com"
RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "evidence" / "sonda_polymarket.json"
PALAVRAS = ("league-of-legends", "league of legends", "lol", "esports", "lck", "lpl", "worlds")


def _get(caminho: str, **params):
    url = f"{BASE}/{caminho}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 gabinete-sonda", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf-8", "replace")
    except Exception as e:  # rede: registra e segue
        return 0, f"{type(e).__name__}: {e}"


def _casa(texto) -> bool:
    t = str(texto or "").lower()
    return any(p in t for p in PALAVRAS)


def _resumo_evento(ev: dict) -> dict:
    mercados = []
    for m in (ev.get("markets") or [])[:6]:
        mercados.append({k: m.get(k) for k in (
            "question", "slug", "outcomes", "outcomePrices", "bestBid", "bestAsk",
            "lastTradePrice", "volume", "liquidity", "gameStartTime", "sportsMarketType",
            "endDate", "active", "closed") if k in m})
    return {"title": ev.get("title"), "slug": ev.get("slug"), "startDate": ev.get("startDate"),
            "endDate": ev.get("endDate"), "seriesSlug": ev.get("seriesSlug"),
            "tags": [t.get("slug") for t in (ev.get("tags") or []) if isinstance(t, dict)],
            "n_markets": len(ev.get("markets") or []), "markets": mercados,
            "chaves_evento": sorted(ev.keys())[:60]}


def main() -> int:
    rel = {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base": BASE, "passos": {}}

    st, sports = _get("sports")
    rel["passos"]["sports"] = {"status": st, "casam": [s for s in (sports if isinstance(sports, list) else [])
                                                        if _casa(json.dumps(s))][:10]}

    st, tags = _get("tags", limit=1000)
    casam = [t for t in (tags if isinstance(tags, list) else []) if _casa(t.get("slug")) or _casa(t.get("label"))]
    rel["passos"]["tags"] = {"status": st, "total": len(tags) if isinstance(tags, list) else None,
                             "casam": [{k: t.get(k) for k in ("id", "slug", "label")} for t in casam][:40]}

    eventos, tentativas = {}, []
    alvos = [("tag_slug", t.get("slug")) for t in casam[:12]] + [("tag_id", t.get("id")) for t in casam[:12]]
    for s in rel["passos"]["sports"]["casam"]:
        for tid in str(s.get("tags") or "").split(","):
            if tid.strip():
                alvos.append(("tag_id", tid.strip()))
    for chave, valor in alvos:
        if not valor:
            continue
        st, evs = _get("events", **{chave: valor, "closed": "false", "limit": 100})
        n = len(evs) if isinstance(evs, list) else None
        tentativas.append({"param": f"{chave}={valor}", "status": st, "n": n})
        for ev in (evs if isinstance(evs, list) else []):
            eventos.setdefault(str(ev.get("id")), ev)
    rel["passos"]["events"] = {"tentativas": tentativas, "eventos_unicos": len(eventos)}
    rel["eventos"] = [_resumo_evento(e) for e in list(eventos.values())[:40]]

    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[sonda_polymarket] sports={rel['passos']['sports']['status']} tags={rel['passos']['tags']['status']} "
          f"(casam {len(casam)}), eventos LoL/esports abertos: {len(eventos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
