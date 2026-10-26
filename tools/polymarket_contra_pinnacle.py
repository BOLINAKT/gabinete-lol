# -*- coding: utf-8 -*-
"""POLYMARKET x PINNACLE: qual das duas acerta mais? (26/10/2026)

Combinado com ele em 23/10/2026: a tela "Modelo x Mercado" usa a Pinnacle como
regua porque "a Pinnacle vai ser quase sempre melhor regulada" -- suposicao.
Esta medicao troca a suposicao por numero: as duas casas, nos MESMOS jogos,
contra o que aconteceu.

A CONTA E A DAS OUTRAS REGUAS (tools/regua_pinnacle_comum.resumo): logloss das
duas contra o resultado, a margem de erro, e "conclusivo" so com o minimo de
partidas E a diferenca maior que a margem. Aqui "modelo" = Polymarket e
"casa" = Pinnacle: diferenca < 0 quer dizer Polymarket melhor.

O QUE ENTRA (versao 1): jogos BO1, onde o vencedor do jogo e o do MAPA 1 --
a Pinnacle pelo mesmo preco que a regua do vencedor usa (mapa 1, sem a margem,
ultima leitura antes do jogo; tools/modelo_contra_a_casa.precos_do_vencedor);
a Polymarket pela ultima leitura antes do inicio (o coletor so guarda
pre-jogo); o resultado pelo CSV (mapa 1 entre os dois times, mesmo dia +-1).
Series BO3/BO5 ficam para depois (precisam do placar da serie).

MINIMO: 200 partidas -- o combinado. Antes disso o veredito e "ainda nao da".
Roda toda semana no robo das reguas (reguas_pinnacle.yml).
"""
from __future__ import annotations

import json
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HISTORICO_POLY = ROOT / "polymarket_lol_historico.jsonl"
MINIMO = 200


def ultima_poly_por_jogo() -> dict:
    """{evento: ultima leitura pre-jogo} (o coletor so grava antes do inicio)."""
    fora = {}
    try:
        linhas = HISTORICO_POLY.read_text(encoding="utf-8").splitlines()
    except OSError:
        return fora
    for t in linhas:
        try:
            x = json.loads(t)
        except ValueError:
            continue
        ev = x.get("evento")
        if ev and (ev not in fora or str(x.get("coletado_em")) > str(fora[ev].get("coletado_em"))):
            fora[ev] = x
    return fora


def casos() -> dict:
    import pandas as pd

    from app_core.schedule_import_core import resolve_schedule_team
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.modelo_contra_a_casa import PARTIDAS, _apelidos, _linhas, precos_do_vencedor
    from tools.nota_honesta import default_csvs

    poly = ultima_poly_por_jogo()
    precos = precos_do_vencedor()
    nomes = {x["id"]: x for x in _linhas(PARTIDAS) if x.get("id") is not None}
    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()], ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    m1 = tg[tg["map_number"].fillna(1).astype(int) == 1]
    ap = _apelidos()
    times = sorted({str(t) for t in tg["team"].dropna().unique()})

    def resolver(nome):
        try:
            achado, ok = resolve_schedule_team(str(nome or ""), times, ap)
        except (TypeError, ValueError):
            return ""
        return str(achado) if ok else ""

    resultado = {}
    for r in m1.itertuples(index=False):
        resultado.setdefault((str(r.date)[:10], str(r.team), str(r.opponent)), int(r.win == 1))
    pin_por_par = {}
    for i, pr in precos.items():
        j = nomes.get(i)
        if not j or not j.get("inicio_utc"):
            continue
        ca, fa = resolver(j.get("casa")), resolver(j.get("fora"))
        if ca and fa:
            pin_por_par[(str(j["inicio_utc"])[:10], ca, fa)] = pr["casa"]
            pin_por_par[(str(j["inicio_utc"])[:10], fa, ca)] = pr["fora"]

    def _vizinhos(dia):
        d0 = pd.Timestamp(dia)
        return [(d0 + pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in (0, -1, 1)]

    fora, motivos = [], {"nao_bo1": 0, "sem_nome": 0, "sem_pinnacle": 0, "sem_resultado": 0}
    for ev, x in poly.items():
        if int(x.get("bo") or 0) != 1:
            motivos["nao_bo1"] += 1
            continue
        a, b = resolver(x.get("time_a")), resolver(x.get("time_b"))
        if not (a and b):
            motivos["sem_nome"] += 1
            continue
        dia = str(x.get("inicio_utc") or "")[:10]
        p_pin = next((pin_por_par[(d, a, b)] for d in _vizinhos(dia) if (d, a, b) in pin_por_par), None)
        if p_pin is None:
            motivos["sem_pinnacle"] += 1
            continue
        y = next((resultado[(d, a, b)] for d in _vizinhos(dia) if (d, a, b) in resultado), None)
        if y is None:
            motivos["sem_resultado"] += 1     # jogo ainda nao no CSV (o normal nos ultimos dias)
            continue
        fora.append({"partida": ev, "p_poly": float(x["p_a"]), "p_casa": float(p_pin), "y": int(y),
                     "spread": x.get("spread"), "liquidez": x.get("liquidez")})
    return {"casos": fora, "motivos": motivos, "jogos_polymarket": len(poly)}


def main() -> int:
    from tools.regua_pinnacle_comum import gravar, resumo
    c = casos()
    r = resumo(c["casos"], "p_poly", minimo=MINIMO)
    dados = {"mercado": "Polymarket x Pinnacle (vencedor, BO1)",
             "nota": "diferenca < 0 = Polymarket acerta mais; 'modelo' aqui e a Polymarket",
             "jogos_polymarket": c["jogos_polymarket"], "fora_e_por_que": c["motivos"],
             "polymarket_x_pinnacle": r}
    alvo = gravar("polymarket", dados)
    if r is None:
        print(f"[polymarket x pinnacle] nenhum jogo ainda com as duas casas e o resultado "
              f"(motivos: {c['motivos']}).")
    else:
        veredito = ("ainda nao da para concluir" if not r["conclusivo"] else
                    ("Polymarket acerta mais" if r["diferenca"] < 0 else "Pinnacle acerta mais"))
        print(f"[polymarket x pinnacle] {r['partidas']} de {MINIMO} partidas · logloss Polymarket "
              f"{r['logloss_modelo']:.4f} x Pinnacle {r['logloss_casa']:.4f} · {veredito}")
    print("gravado em", alvo.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
