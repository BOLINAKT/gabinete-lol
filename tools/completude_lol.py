# -*- coding: utf-8 -*-
"""COMPLETUDE DA BASE DO LOL (24/11/2026): toda serie que a lolesports diz que TERMINOU nos ultimos 21
dias esta na base? As que nao estao vao para evidence/completude_lol.json, com o motivo, e a faixa do topo
do app mostra (app_core/confianca_base_core.py).

Achado que motivou: a base do LoL parou em 04/11 (o CSV do Oracle's Elixir nao foi atualizado) e as
quartas, semis e a FINAL do Mundial (05 a 14/11) ficaram fora -- com a faixa dizendo "ok", porque o robo
rodava certo. Regra dele: jogo nunca falta calado.
Fonte: API publica da lolesports (getSchedule, a mesma chave publica do site). Uso: python tools/completude_lol.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
SAIDA = RAIZ / "evidence" / "completude_lol.json"
JANELA_DIAS = 21
CSV = RAIZ / "CSV_DIARIO" / "2026_LoL_esports_match_data_from_OraclesElixir.csv"


def series_terminadas(agora: datetime, get=None) -> list:
    """[{inicio, a, b, liga, placar}] das series 'completed' da janela (paginando para tras)."""
    from app_core import super_live_core as SL
    h = {"x-api-key": SL.LOL_CHAVE_PUBLICA, "User-Agent": "Gabinete/0.1"}

    def _get(url):
        if get:
            return get(url)
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read())
    out, token, desde = [], None, agora - timedelta(days=JANELA_DIAS)
    for _ in range(8):
        url = SL.LOL_API + "/getSchedule?hl=en-US" + (f"&pageToken={urllib.parse.quote(token)}" if token else "")
        s = (_get(url).get("data") or {}).get("schedule") or {}
        evs = s.get("events") or []
        for e in evs:
            ini = datetime.fromisoformat(str(e.get("startTime")).replace("Z", "+00:00"))
            if e.get("type") != "match" or e.get("state") != "completed" or not (desde <= ini <= agora):
                continue
            ts = (e.get("match") or {}).get("teams") or []
            if len(ts) != 2:
                continue
            out.append({"inicio": ini.isoformat(), "a": ts[0].get("name"), "b": ts[1].get("name"),
                        "liga": (e.get("league") or {}).get("name"),
                        "placar": "-".join(str((t.get("result") or {}).get("gameWins")) for t in ts)})
        token = (s.get("pages") or {}).get("older")
        if not token or not evs or min(e.get("startTime", "") for e in evs) < desde.isoformat()[:19]:
            break
    return out


def conferir(series: list, base: pd.DataFrame, resolver) -> list:
    """Pura: as series sem jogo na base (mesmos dois times, de 1 dia antes a 2 dias depois)."""
    t = base[base["position"] == "team"].copy()
    t["dt"] = pd.to_datetime(t["date"], errors="coerce", utc=True)
    jogos = {}
    for gid, g in t.groupby("gameid"):
        jogos[gid] = (g["dt"].min(), frozenset(str(x) for x in g["teamname"]))
    faltam = []
    for s in series:
        a, b = resolver(s["a"]) or "", resolver(s["b"]) or ""
        if not a or not b:
            nao = [x for x, r in ((s["a"], a), (s["b"], b)) if not r]
            faltam.append({**s, "motivo": "time não reconhecido na base: " + ", ".join(nao)})
            continue
        ini = pd.Timestamp(s["inicio"])
        ok = any(par == {a, b} and ini - pd.Timedelta(days=1) <= dt <= ini + pd.Timedelta(days=2)
                 for dt, par in jogos.values())
        if not ok:
            faltam.append({**s, "motivo": "não está na base (o CSV do Oracle's Elixir ainda não tem)"})
    return faltam


def main() -> int:
    agora = datetime.now(timezone.utc)
    try:
        series = series_terminadas(agora)
    except Exception as e:  # noqa: BLE001
        print(f"[completude_lol] lolesports nao respondeu ({type(e).__name__}); fica o arquivo anterior")
        return 0
    base = pd.read_csv(CSV, usecols=["gameid", "date", "teamname", "position"], low_memory=False)
    times = sorted(set(base.loc[base["position"] == "team", "teamname"].astype(str)))
    from app_core.gaveta_jogos_core import resolver_padrao
    faltam = conferir(series, base, resolver_padrao(times, RAIZ))
    doc = {"quando": agora.isoformat(timespec="seconds"), "fonte": "lolesports getSchedule",
           "janela_dias": JANELA_DIAS, "series_conferidas": len(series), "faltando": faltam}
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[completude_lol] {len(series)} series terminadas em {JANELA_DIAS} dias; faltam {len(faltam)} na base")
    for f in faltam[:10]:
        print("  -", f["inicio"][:10], f["a"], "x", f["b"], f"({f['liga']}, {f['placar']}):", f["motivo"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
