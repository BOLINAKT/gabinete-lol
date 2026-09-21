# -*- coding: utf-8 -*-
"""O modelo de handicap de abates contra o preco da Pinnacle.

A PERGUNTA. `tools/handicap_de_abates.py` mostrou que o modelo esta bem
calibrado (erro medio de 0,31 ponto percentual, fora da amostra, em 10.994
jogos). Calibrado NAO e lucrativo: a casa tambem e calibrada e cobra margem.
Vantagem exige acertar MAIS que ela. E isso que se mede aqui.

POR QUE NESTE MERCADO, E NAO NO VENCEDOR. No vencedor, uma partida da UMA
aposta -- ha 20 medidas e sao precisas ~100. No handicap, uma partida da
varias linhas e varios mapas: ha 301 apostas de linha PRINCIPAL em 29
partidas. A resposta chega antes aqui.

SO A LINHA PRINCIPAL. As alternativas sao 3.182 das 3.700 leituras, mas
cobram 8,49% contra 6,98% da principal. Medir nelas responderia sobre uma
aposta que ele nao deveria fazer.

O QUE NAO PODE SER FEITO COM 301 APOSTAS, e por isso esta travado no codigo:
trata-las como 301 observacoes independentes. Elas nao sao -- quando um time
atropela, TODAS as linhas daquele mapa acertam juntas. A incerteza sai
agrupada por partida, que e a unidade que de fato varia.

Uso: python tools/handicap_contra_a_casa.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PARTIDAS = ROOT / "odds_pinnacle_partidas.jsonl"
PRECOS = ROOT / "odds_pinnacle_historico.jsonl"

# Abaixo disto nenhuma conclusao sai, tenha a conta dado o que tiver. A
# unidade e a PARTIDA, nao a aposta -- ver o cabecalho.
PARTIDAS_MINIMAS = 60


def _linhas(arq):
    if not arq.exists():
        return []
    fora = []
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            fora.append(json.loads(linha))
        except ValueError:
            continue
    return fora


def apostas_principais():
    """As linhas PRINCIPAIS de handicap de abates, sem a margem da casa.

    Devolve [{jogo, mapa, pontos_casa, p_casa, p_fora, margem_pct, ...}], com
    `p_casa + p_fora == 1`. Cada par (casa com -X, fora com +X) e uma aposta.
    """
    import re
    ultimo = {}
    for x in _linhas(PRECOS):
        m = re.match(r"^Handicap - Kills - mapa (\d+)$", str(x.get("mercado") or ""))
        if not m or x.get("alternativa"):
            continue
        lado = str(x.get("lado") or "")
        if lado not in ("home", "away"):
            continue
        try:
            odd = float(x.get("odd"))
            pontos = float(x.get("pontos"))
        except (TypeError, ValueError):
            continue
        if not odd > 1.0:
            continue
        ch = (x.get("jogo"), int(m.group(1)), abs(pontos), lado)
        ant = ultimo.get(ch)
        if ant is None or str(x.get("lido_em")) > str(ant.get("lido_em")):
            ultimo[ch] = dict(x, _mapa=int(m.group(1)), _abs=abs(pontos))

    fora = []
    chaves = {(j, mp, ab) for (j, mp, ab, _l) in ultimo}
    for j, mp, ab in chaves:
        c, f = ultimo.get((j, mp, ab, "home")), ultimo.get((j, mp, ab, "away"))
        if not c or not f:
            continue      # sem os dois lados nao da para tirar a margem
        ic, iff = 1.0 / float(c["odd"]), 1.0 / float(f["odd"])
        soma = ic + iff
        if soma <= 0:
            continue
        fora.append({"jogo": j, "mapa": mp,
                     "pontos_casa": float(c["pontos"]),
                     "p_casa": ic / soma, "p_fora": iff / soma,
                     "margem_pct": 100.0 * (soma - 1.0),
                     "limite": c.get("limite"),
                     "odd_casa": float(c["odd"]), "odd_fora": float(f["odd"])})
    return fora


def main() -> int:
    import numpy as np
    import pandas as pd

    from app_core.schedule_import_core import resolve_schedule_team
    from mlcore.lines_engine import DC_BLEND_HL_DAYS as HL, DC_BLEND_MIN_EFF as MIN_EFF, _dc_decayed
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.handicap_de_abates import calibrador, forma_empirica, prob_acima
    from tools.modelo_contra_a_casa import _apelidos
    from tools.nota_honesta import default_csvs

    nomes = {x["id"]: x for x in _linhas(PARTIDAS) if x.get("id") is not None}
    apostas = apostas_principais()
    print("[hcasa] %d apostas de linha principal em %d partidas"
          % (len(apostas), len({a["jogo"] for a in apostas})))
    if not apostas:
        return 1

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    jogos = tg[tg["side"].astype(str).str.lower() == "blue"].copy()
    jogos = jogos.sort_values(["date", "gameid"], kind="mergesort")
    jogos["ka"] = pd.to_numeric(jogos["kills_for"], errors="coerce")
    jogos["kc"] = pd.to_numeric(jogos["kills_against"], errors="coerce")
    jogos = jogos.dropna(subset=["ka", "kc"])

    # --- estado PONTO-NO-TEMPO, jogo a jogo, ate o dia de cada partida ---
    soma = peso = 0.0
    ultima = None
    hist = {}
    passado = []          # (media prevista, total previsto, diferenca real)
    estado = {}           # gameid -> tudo o que se sabia ANTES daquele jogo
    for r in jogos.itertuples(index=False):
        azul, verm, quando = str(r.team), str(r.opponent), r.date
        if ultima is not None:
            _f = 0.5 ** (max((quando - ultima).total_seconds() / 86400.0, 0.0) / HL)
            soma *= _f
            peso *= _f
        ultima = quando
        nivel = (soma / peso) if peso > 1e-9 else float("nan")
        ha, hb = hist.get(azul), hist.get(verm)
        if ha is not None and hb is not None and nivel == nivel and nivel > 0:
            aa, n1 = _dc_decayed(ha["d"], ha["f"], quando, HL)
            da, n2 = _dc_decayed(ha["d"], ha["g"], quando, HL)
            ab, n3 = _dc_decayed(hb["d"], hb["f"], quando, HL)
            db, n4 = _dc_decayed(hb["d"], hb["g"], quando, HL)
            if (min(n1, n2, n3, n4) >= MIN_EFF
                    and all(x == x for x in (aa, da, ab, db))):
                ea, eb = aa * db / nivel, ab * da / nivel
                estado[str(r.gameid)] = {"media": ea - eb, "total": ea + eb,
                                         "azul": azul, "passado": len(passado)}
                passado.append({"media": ea - eb, "total": ea + eb,
                                "dif": float(r.ka) - float(r.kc)})
        for t, f_, g_ in ((azul, float(r.ka), float(r.kc)),
                          (verm, float(r.kc), float(r.ka))):
            d = hist.get(t)
            nova = pd.DataFrame({"d": [quando], "f": [f_], "g": [g_]})
            hist[t] = nova if d is None else pd.concat([d, nova], ignore_index=True)
        soma += float(r.ka) + float(r.kc)
        peso += 2.0

    # --- o modelo, ajustado UMA VEZ com tudo que veio antes da coleta ---
    # A coleta comecou em 15/09/2026; todo jogo medido aqui e posterior ao
    # ajuste, entao nenhum deles entra no proprio ajuste.
    from tools.handicap_de_abates import LINHAS_TIPICAS
    JANELA = 3000
    base = passado[-JANELA:] if len(passado) > JANELA else passado
    vies = float(np.mean([t["dif"] - t["media"] for t in base]))
    resto = np.array([t["dif"] - t["media"] - vies for t in base], dtype=float)
    tot = np.array([t["total"] for t in base], dtype=float)
    qs = np.quantile(tot, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    pontos = []
    for i in range(len(qs) - 1):
        m = (tot >= qs[i]) & (tot <= qs[i + 1] if i == len(qs) - 2 else tot < qs[i + 1])
        if int(m.sum()) >= 100:
            pontos.append((float(np.mean(tot[m])), float(np.std(resto[m]))))
    inc, bas = (np.polyfit([x for x, _ in pontos], [y for _, y in pontos], 1)
                if len(pontos) >= 2 else (0.0, float(np.std(resto))))
    largura = lambda x: max(1.0, inc * float(x) + bas)
    forma = forma_empirica([t["dif"] - t["media"] - vies for t in base],
                           [largura(t["total"]) for t in base])
    cru = []
    for t in base:
        for L in LINHAS_TIPICAS:
            pp = prob_acima(L, t["media"] + vies, largura(t["total"]), forma)
            if pp is not None:
                cru.append((pp, 1.0 if t["dif"] > L else 0.0))
    cal = calibrador(cru)
    print("[hcasa] modelo ajustado em %d jogos anteriores a coleta" % len(base))

    # --- casar cada aposta com o jogo do CSV ---
    ap = _apelidos()
    times = sorted({str(t) for t in tg["team"].dropna().unique()})

    def resolver(n):
        try:
            achado, ok = resolve_schedule_team(str(n or ""), times, ap)
        except (TypeError, ValueError):
            return ""
        return str(achado) if ok else ""

    indice = {}
    for r in jogos.itertuples(index=False):
        par = tuple(sorted((str(r.team), str(r.opponent))))
        mp = int(getattr(r, "map_number", 1) or 1)
        indice.setdefault((str(r.date)[:10], par, mp), []).append(r)

    casos, sem = [], 0
    for a in apostas:
        j = nomes.get(a["jogo"])
        if not j or not j.get("inicio_utc"):
            sem += 1
            continue
        ca, fa = resolver(j.get("casa")), resolver(j.get("fora"))
        if not ca or not fa:
            sem += 1
            continue
        par = tuple(sorted((ca, fa)))
        dia = str(j["inicio_utc"])[:10]
        achados = []
        for delta in (0, -1, 1):
            dd = (pd.Timestamp(dia) + pd.Timedelta(days=delta)).strftime("%Y-%m-%d")
            achados += indice.get((dd, par, a["mapa"]), [])
        if not achados:
            sem += 1
            continue
        r = achados[0]
        est = estado.get(str(r.gameid))
        if est is None:
            sem += 1
            continue
        # Tudo do ponto de vista do lado AZUL do CSV.
        azul_e_casa = str(r.team) == ca
        # O handicap da casa: "casa com pontos_casa". Do lado azul isso vira:
        linha_azul = a["pontos_casa"] if azul_e_casa else -a["pontos_casa"]
        p_modelo = prob_acima(-linha_azul, est["media"] + vies,
                              largura(est["total"]), forma)
        if p_modelo is None:
            sem += 1
            continue
        p_modelo = cal(p_modelo)
        p_casa = a["p_casa"] if azul_e_casa else a["p_fora"]
        dif = float(r.ka) - float(r.kc)
        casos.append({"partida": a["jogo"], "gameid": str(r.gameid),
                      "mapa": a["mapa"], "linha_azul": linha_azul,
                      "p_modelo": float(p_modelo), "p_casa": float(p_casa),
                      "y": 1.0 if dif + linha_azul > 0 else 0.0,
                      "margem": a["margem_pct"], "limite": a.get("limite"),
                      "liga": j.get("liga"), "confronto": "%s x %s" % (j.get("casa"), j.get("fora"))})

    n_part = len({c["partida"] for c in casos})
    print("[hcasa] casaram: %d apostas em %d partidas | fora: %d"
          % (len(casos), n_part, sem))
    if not casos:
        print("[hcasa] nada para medir ainda.")
        return 0

    pm = np.array([c["p_modelo"] for c in casos])
    pc = np.array([c["p_casa"] for c in casos])
    y = np.array([c["y"] for c in casos])

    def _perda(p):
        q = np.clip(p, 1e-9, 1 - 1e-9)
        return -(y * np.log(q) + (1 - y) * np.log(1 - q))

    lm, lc = float(np.mean(_perda(pm))), float(np.mean(_perda(pc)))
    print()
    print("=== O MODELO CONTRA A CASA (handicap de abates, linha principal) ===")
    print("margem media da casa: %.2f%% (ja retirada)"
          % float(np.mean([c["margem"] for c in casos])))
    print("distancia media entre os dois precos: %.1f pp"
          % float(np.mean(np.abs(pm - pc)) * 100))
    print()
    print("  logloss do modelo ... %.4f" % lm)
    print("  logloss da casa ..... %.4f" % lc)
    print("  diferenca ........... %+.4f  (%s)"
          % (lm - lc, "o modelo perde" if lm > lc else "o modelo ganha"))

    # INCERTEZA AGRUPADA POR PARTIDA. Tratar 301 apostas como independentes
    # daria uma certeza que nao existe: no mesmo mapa, todas as linhas
    # acertam ou erram juntas.
    dif = _perda(pm) - _perda(pc)
    por_partida = {}
    for c, d in zip(casos, dif):
        por_partida.setdefault(c["partida"], []).append(float(d))
    medias = np.array([float(np.mean(v)) for v in por_partida.values()])
    print()
    print("INCERTEZA, contando PARTIDA e nao aposta (%d partidas)" % len(medias))
    if len(medias) > 1:
        erro = 1.96 * float(np.std(medias, ddof=1)) / math.sqrt(len(medias))
        print("  margem de erro: +-%.4f" % erro)
        print("  partidas em que o modelo bateu a casa: %d de %d"
              % (int((medias < 0).sum()), len(medias)))
    if len(medias) < PARTIDAS_MINIMAS:
        print()
        print("  >> AMOSTRA PEQUENA DEMAIS (%d partidas de %d). Nenhuma"
              % (len(medias), PARTIDAS_MINIMAS))
        print("     conclusao sai daqui, nem a favor nem contra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
