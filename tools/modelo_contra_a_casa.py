# -*- coding: utf-8 -*-
"""O modelo discorda da Pinnacle para melhor ou para pior?

POR QUE ESTA E A PERGUNTA CERTA AGORA (21/09/2026)

Depois de reprovar forma recente, confronto direto, descanso, experiencia e o
afrouxamento da trava de concordancia, ficou claro que o erro que sobra no
modelo de vencedor nao e alcancavel com sinal simples. Entao a pergunta deixa
de ser "como melhorar o modelo" e passa a ser "o modelo vale a aposta".

A Pinnacle e a referencia mais afiada que existe de graca. Se o modelo so
diverge dela para o lado errado, nao adianta refinar: adianta parar de apostar
vencedor e concentrar onde ha vantagem.

POR QUE COMPARAR PROBABILIDADE, E NAO ACERTO

Com poucas dezenas de partidas, contar vitoria e derrota e ruido pintado de
numero. Comparar o PRECO do modelo com o PRECO da casa usa muito mais
informacao de cada jogo, e ja mostra o que interessa primeiro: se o modelo e
mais extremo ou mais timido que o mercado, e para que lado ele erra.

O acerto contra o resultado tambem sai -- acompanhado de quantas partidas
faltam para ele significar alguma coisa.

O QUE E PONTO-NO-TEMPO AQUI
  - o preco da casa e a ULTIMA leitura antes do jogo;
  - a probabilidade do modelo vem da regua honesta (origem rolante), onde cada
    jogo foi pontuado por um modelo que nao o tinha visto.

A MARGEM SAI ANTES. Odd de casa embute a comissao: 1/odd dos dois lados soma
mais que 1. Comparar sem tirar isso faria o modelo parecer sistematicamente
mais timido que o mercado -- exatamente o tipo de conclusao errada que este
arquivo existe para nao produzir.

Uso: python tools/modelo_contra_a_casa.py

REFORCO SEMANAL (12 min, cobre os ultimos 30 dias):
    python tools/nota_honesta.py --marca base_agree_SEMANA --dobras 1         --cadencia diaria --com-hybrid --com-form
Esta regua junta sozinha todas as medicoes da familia.
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
# AS MEDICOES DA REGUA HONESTA, juntadas.
#
# POR QUE JUNTAR (22/09/2026). A nota honesta so pontua os jogos que existiam
# quando ela rodou. Descobri isso quando a regua do vencedor travou em 20
# partidas: 5 jogos novos estavam no CSV e apareciam como "sem nota do
# modelo". Ou seja, esta regua PARA DE CRESCER sem um reforco periodico.
#
# Refazer as 8 dobras leva 1h40. Uma dobra so cobre os ultimos 30 dias e leva
# ~12 minutos -- que e tudo de que o reforco precisa, porque os jogos antigos
# ja estao pontuados. Entao a regua le TODAS as medicoes da mesma variante e
# junta por jogo.
#
# Juntar e valido porque cada jogo foi pontuado por um modelo que nao o tinha
# visto, em qualquer das rodadas. Quando o mesmo jogo aparece em duas, fica o
# da primeira em ordem de nome, e a divergencia media e impressa -- se ela
# crescer, alguma rodada deixou de ser comparavel com as outras.
FAMILIA_REGUA = "nota_honesta_base_agree*_diaria_hybrid_form_platt.json"
PASTA_REGUA = ROOT / "scratchpad" / "nota_honesta"
MERCADO = "Vencedor - mapa 1"

# Abaixo disto, nenhuma conclusao sai, tenha a conta dado o que tiver.
#
# POR QUE O PISO EXISTE (21/09/2026): na primeira rodada, com 10 partidas, a
# ferramenta imprimiu "ja da para afirmar". Nao dava. A formula do intervalo
# supoe um monte de jogos parecidos; com 10, e UMA delas respondendo por
# metade da diferenca, ela mente com cara de estatistica. O numero continua
# saindo -- com o aviso na frente.
PARTIDAS_MINIMAS = 100


def _logit(p):
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


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


def precos_do_vencedor(mercado=MERCADO):
    """Ultima leitura de cada lado antes do jogo, ja sem a margem da casa.

    Devolve {id_da_partida: {casa, fora, margem_pct, odd_casa, odd_fora, lido_em}}
    com `casa`/`fora` somando 1.
    """
    ultimo = {}
    for x in _linhas(PRECOS):
        if str(x.get("mercado")) != mercado or x.get("alternativa"):
            continue
        lado = str(x.get("lado") or "")
        if lado not in ("home", "away"):
            continue
        try:
            odd = float(x.get("odd"))
        except (TypeError, ValueError):
            continue
        if not odd > 1.0:
            continue
        ch = (x.get("jogo"), lado)
        anterior = ultimo.get(ch)
        if anterior is None or str(x.get("lido_em")) > str(anterior.get("lido_em")):
            ultimo[ch] = x

    fora = {}
    for i in {k[0] for k in ultimo}:
        c, f = ultimo.get((i, "home")), ultimo.get((i, "away"))
        if not c or not f:
            continue          # com um lado so nao da para tirar a margem
        ic, iff = 1.0 / float(c["odd"]), 1.0 / float(f["odd"])
        soma = ic + iff
        if soma <= 0:
            continue
        fora[i] = {"casa": ic / soma, "fora": iff / soma,
                   "margem_pct": 100.0 * (soma - 1.0),
                   "odd_casa": float(c["odd"]), "odd_fora": float(f["odd"]),
                   "lido_em": max(str(c.get("lido_em")), str(f.get("lido_em")))}
    return fora


def _apelidos():
    """Os apelidos que ELE ensinou. SO LEITURA -- este arquivo nunca escreve.

    (Uma vez eu gravei um apelido adivinhado neste arquivo e tive de desfazer.
    Desde entao, ferramenta de medicao nao escreve aqui.)
    """
    arq = ROOT / "user_team_aliases.json"
    if not arq.exists():
        return {}
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def carregar_regua():
    """{gameid: (p do modelo, resultado)} de TODAS as medicoes da variante.

    Devolve tambem um resumo: quantos arquivos, quantos jogos, e o quanto as
    rodadas divergem quando pontuam o mesmo jogo.
    """
    arquivos = sorted(PASTA_REGUA.glob(FAMILIA_REGUA))
    modelo, repetidos = {}, []
    for arq in arquivos:
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for g, p, y in (d.get("por_jogo") or []):
            gid = str(g)
            if gid in modelo:
                repetidos.append(abs(float(p) - modelo[gid][0]))
                continue        # fica a primeira, para ser deterministico
            modelo[gid] = (float(p), int(y))
    resumo = {"arquivos": [a.name for a in arquivos], "jogos": len(modelo),
              "repetidos": len(repetidos),
              "divergencia_media": (sum(repetidos) / len(repetidos)) if repetidos else 0.0}
    return modelo, resumo


def juntar():
    """As partidas com preco da casa E nota do modelo, do ponto de vista do azul."""
    import pandas as pd

    from app_core.schedule_import_core import resolve_schedule_team
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import default_csvs

    nomes = {x["id"]: x for x in _linhas(PARTIDAS) if x.get("id") is not None}
    precos = precos_do_vencedor()
    modelo, _ = carregar_regua()

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])
    azul = tg[tg["side"].astype(str).str.lower() == "blue"]
    azul = azul[azul["map_number"].fillna(1).astype(int) == 1]

    # O MESMO resolvedor da aba Jogos. Ele NAO adivinha: casa nome exato ou
    # apelido ja ensinado, e devolve ok=False no resto. Isso e de proposito --
    # adivinhar aqui compararia o modelo de OUTRO time com o preco deste.
    ap = _apelidos()
    times = sorted({str(t) for t in tg["team"].dropna().unique()})

    def resolver(nome):
        try:
            achado, ok = resolve_schedule_team(str(nome or ""), times, ap)
        except (TypeError, ValueError):
            return ""
        return str(achado) if ok else ""

    indice = {}
    for r in azul.itertuples(index=False):
        par = tuple(sorted((str(r.team), str(r.opponent))))
        indice.setdefault((str(r.date)[:10], par), []).append(r)

    casos, sem_apelido, sem_jogo, sem_modelo = [], [], [], []
    for i, pr in precos.items():
        j = nomes.get(i)
        if not j or not j.get("inicio_utc"):
            continue
        dia = str(j["inicio_utc"])[:10]
        ca, fa = resolver(j.get("casa")), resolver(j.get("fora"))
        if not ca or not fa:
            sem_apelido.append({"dia": dia, "liga": j.get("liga"),
                                "casa": j.get("casa"), "fora": j.get("fora"),
                                "falta": [n for n, r in ((j.get("casa"), ca),
                                                         (j.get("fora"), fa)) if not r]})
            continue
        par = tuple(sorted((ca, fa)))
        achados = []
        for delta in (0, -1, 1):   # o fuso pode jogar a partida para o dia vizinho
            dd = (pd.Timestamp(dia) + pd.Timedelta(days=delta)).strftime("%Y-%m-%d")
            achados += indice.get((dd, par), [])
        if not achados:
            sem_jogo.append({"dia": dia, "liga": j.get("liga"),
                             "casa": j.get("casa"), "fora": j.get("fora")})
            continue
        r = achados[0]
        pmy = modelo.get(str(r.gameid))
        if pmy is None:
            sem_modelo.append({"dia": dia, "casa": j.get("casa"), "fora": j.get("fora")})
            continue
        # Tudo do ponto de vista do lado AZUL, que e de quem o modelo fala.
        azul_e_casa = str(r.team) == ca
        casos.append({"liga": j.get("liga"), "casa": j.get("casa"), "fora": j.get("fora"),
                      "dia": dia, "azul": r.team, "gameid": str(r.gameid),
                      "p_modelo": pmy[0], "y": pmy[1],
                      "p_mercado": float(pr["casa"] if azul_e_casa else pr["fora"]),
                      "margem": pr["margem_pct"]})
    casos.sort(key=lambda c: c["dia"])
    return {"casos": casos, "sem_apelido": sem_apelido, "sem_jogo": sem_jogo,
            "sem_modelo": sem_modelo, "n_nomes": len(nomes), "n_precos": len(precos)}


def main() -> int:
    import numpy as np

    if not PARTIDAS.exists():
        print("[casa] nao achei %s" % PARTIDAS)
        return 1
    _, resumo = carregar_regua()
    if not resumo["jogos"]:
        print("[casa] nao achei nenhuma medicao da regua honesta em %s" % PASTA_REGUA)
        print("[casa] rode: python tools/nota_honesta.py --marca base_agree "
              "--dobras 8 --cadencia diaria --com-hybrid --com-form")
        return 1
    print("[casa] regua honesta: %d jogos de %d medicao(oes)%s"
          % (resumo["jogos"], len(resumo["arquivos"]),
             ("; %d jogos repetidos, divergencia media %.4f"
              % (resumo["repetidos"], resumo["divergencia_media"]))
             if resumo["repetidos"] else ""))

    r = juntar()
    casos = r["casos"]
    print("[casa] %d partidas com nome | %d com preco de %r nos dois lados"
          % (r["n_nomes"], r["n_precos"], MERCADO))
    print("[casa] casaram: %d" % len(casos))
    if r["sem_apelido"]:
        print("       %d SEM APELIDO ENSINADO -- a casa escreve um nome, o CSV"
              % len(r["sem_apelido"]))
        print("       outro, e o resolvedor nao adivinha. Cada uma dessas e uma"
              " partida")
        print("       que some da medicao ate voce ensinar o apelido na aba Jogos:")
        faltando = {}
        for x in r["sem_apelido"]:
            for nome in x["falta"]:
                faltando[str(nome)] = faltando.get(str(nome), 0) + 1
        for nome, q in sorted(faltando.items(), key=lambda kv: -kv[1])[:12]:
            print("         %-34s (%d partida%s)" % (nome, q, "s" if q > 1 else ""))
    if r["sem_jogo"]:
        print("       %d com apelido OK mas sem o jogo no CSV -- esperado para"
              " partida de hoje" % len(r["sem_jogo"]))
    if r["sem_modelo"]:
        print("       %d no CSV mas sem nota do modelo (fora das dobras medidas)"
              % len(r["sem_modelo"]))
    if not casos:
        print("[casa] nenhuma partida com preco E nota do modelo ainda.")
        return 0

    pm = np.array([c["p_modelo"] for c in casos])
    pc = np.array([c["p_mercado"] for c in casos])
    y = np.array([c["y"] for c in casos], dtype=float)
    n = len(casos)

    print()
    print("=== O MODELO CONTRA A CASA (%d partidas, %s) ===" % (n, MERCADO))
    print("margem media da casa nestas linhas: %.2f%% (ja retirada da conta)"
          % float(np.mean([c["margem"] for c in casos])))
    print()
    print("distancia media entre os dois precos: %.1f pontos percentuais"
          % float(np.mean(np.abs(pm - pc)) * 100))
    print("maior distancia:                     %.1f pp"
          % float(np.max(np.abs(pm - pc)) * 100))

    lm = np.array([_logit(x) for x in pm])
    lc = np.array([_logit(x) for x in pc])
    if float(np.std(lc)) > 1e-9 and n >= 5:
        inclinacao = float(np.polyfit(lc, lm, 1)[0])
        print()
        print("inclinacao do modelo contra a casa: %.2f" % inclinacao)
        if inclinacao > 1.15:
            print("  -> o modelo e MAIS EXTREMO que o mercado (estica os favoritos)")
        elif inclinacao < 0.85:
            print("  -> o modelo e MAIS TIMIDO que o mercado (encolhe tudo para o meio)")
        else:
            print("  -> o modelo acompanha a escala do mercado")
        print("correlacao entre os dois: %.3f" % float(np.corrcoef(lm, lc)[0, 1]))

    def _perda(p):
        q = np.clip(p, 1e-9, 1 - 1e-9)
        return -(y * np.log(q) + (1 - y) * np.log(1 - q))

    perda_m, perda_c = _perda(pm), _perda(pc)
    llm, llc = float(np.mean(perda_m)), float(np.mean(perda_c))
    print()
    print("ACERTO CONTRA O RESULTADO")
    print("  logloss do modelo ... %.4f" % llm)
    print("  logloss da casa ..... %.4f" % llc)
    print("  diferenca ........... %+.4f  (%s)"
          % (llm - llc, "o modelo perde" if llm > llc else "o modelo ganha"))

    dif = perda_m - perda_c
    s = float(np.std(dif, ddof=1)) if n > 1 else float("nan")
    if math.isfinite(s) and s > 0:
        margem = 1.96 * s / math.sqrt(n)
        print("  margem de erro com %d partidas: +-%.4f" % (n, margem))
        # O quanto UMA partida sozinha responde pela diferenca. Com poucas
        # partidas, esse numero costuma ser o que decide tudo -- e mostrar
        # isso vale mais que qualquer intervalo.
        maior = float(np.max(np.abs(dif)))
        fatia = maior / max(abs(float(np.sum(dif))), 1e-9)
        print("  a partida mais influente sozinha responde por %.0f%% da diferenca"
              % (100 * fatia))
        if n < PARTIDAS_MINIMAS:
            print()
            print("  >> AMOSTRA PEQUENA DEMAIS (%d de %d). Nao ha conclusao aqui,"
                  % (n, PARTIDAS_MINIMAS))
            print("     nem a favor nem contra o modelo. A conta do intervalo")
            print("     supoe muitos jogos parecidos; com esta quantidade ela")
            print("     mente com cara de estatistica.")
        elif abs(llm - llc) > margem:
            print("  -> ja da para afirmar")
        else:
            print("  -> ainda NAO da para afirmar")
            if abs(llm - llc) > 1e-6:
                preciso = int(math.ceil((1.96 * s / abs(llm - llc)) ** 2))
                print("     para a diferenca DE HOJE virar afirmacao: ~%d partidas"
                      % preciso)

    print()
    print("ONDE ELES MAIS DISCORDAM")
    print("%-11s %-32s %8s %8s %7s %6s"
          % ("dia", "confronto", "modelo", "casa", "dif", "deu"))
    for c in sorted(casos, key=lambda c: -abs(c["p_modelo"] - c["p_mercado"]))[:10]:
        print("%-11s %-32s %7.1f%% %7.1f%% %+6.1f %6s" % (
            c["dia"], ("%s x %s" % (c["casa"], c["fora"]))[:32],
            100 * c["p_modelo"], 100 * c["p_mercado"],
            100 * (c["p_modelo"] - c["p_mercado"]),
            "azul" if c["y"] == 1 else "verm"))

    # O resumo para o app (25/09/2026): tools/regua_pinnacle_comum.py. Um
    # mapa por partida aqui, entao a partida e o proprio jogo.
    from tools.regua_pinnacle_comum import gravar, resumo
    gravar("vencedor", {"mercado": "Vencedor do mapa 1",
                        "so_kills": resumo([{"partida": c["gameid"], "p_modelo": c["p_modelo"],
                                              "p_casa": c["p_mercado"], "y": c["y"]}
                                             for c in casos], "p_modelo",
                                            minimo=PARTIDAS_MINIMAS)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
