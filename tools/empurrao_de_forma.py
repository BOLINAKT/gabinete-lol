# -*- coding: utf-8 -*-
"""Nao dar MAIS PESO ao blend -- dar um EMPURRAO pequeno e ajustado.

O QUE JA FOI MEDIDO, nesta ordem:

  1. Sobra sinal de forma depois do modelo: +0,013 de logloss no mapa 1
     (tools/sobrou_sinal.py), positivo em 5 janelas de 5.
  2. Ele esta concentrado onde a forma DISCORDA do modelo: +0,037 contra
     +0,004 onde concorda.
  3. Dai eu conclui que bastava afrouxar a trava de concordancia do
     hybrid_blend. ERRADO: piorou a nota em 8 blocos de 8
     (tools/varrer_agree.py), de forma monotona -- quanto mais afrouxava,
     pior.

POR QUE O 3 FALHOU, embora 1 e 2 estejam certos. Afrouxar a trava faz o preco
andar em direcao a `p_hibrido`, que e uma estimativa GROSSA (razao de taxas de
vitoria). Mais peso numa estimativa grossa estraga o preco, mesmo quando a
DIRECAO em que ela discorda carrega informacao. Sao coisas diferentes:

    "a forma aponta para o outro lado"  -> informacao util, pequena
    "entao va 40% do caminho ate ela"   -> destroi um preco que estava bom

O que a regressao de (1) encontrou nao foi um peso grande: foi um coeficiente
ajustado empurrando o LOGITO alguns centesimos. E isso que esta ferramenta
mede -- e com o peso ajustado SO no passado de cada bloco, nunca no bloco
medido.

    logito(p) <- logito(p) + w * (forma_a - forma_b)

Se isto tambem nao aparecer na nota, entao o ganho de logloss nao sobrevive a
mistura 45/55 da nota e ao tamanho real do efeito, e o caminho morre aqui --
o que e uma resposta, nao um fracasso.

Uso: python tools/empurrao_de_forma.py
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

FONTE = "nota_honesta_base_agree_diaria_hybrid_form_platt.json"
JANELA_FORMA = 10
BLOCOS = 8


def _logit(p):
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1.0 - p))


def _sig(z):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, float(z)))))


def main() -> int:
    import numpy as np
    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import default_csvs, nota_de

    alvo = ROOT / "scratchpad" / "nota_honesta" / FONTE
    if not alvo.exists():
        print("[empurrao] nao achei %s" % alvo)
        return 1
    d = json.loads(alvo.read_text(encoding="utf-8"))
    final = {str(g): (float(p), int(y)) for g, p, y in (d.get("por_jogo") or [])}
    # `antes_hybrid` e quem sabe se o jogo e entre regioes -- a nota precisa disso.
    meta = {str(x["gameid"]): x for x in (d.get("antes_hybrid") or [])}
    if not final or not meta:
        print("[empurrao] o arquivo nao tem por_jogo/antes_hybrid.")
        return 1

    csvs = [str(c) for c in default_csvs()]
    tg = pd.concat([build_team_games(load_team_rows(c)) for c in csvs], ignore_index=True)
    tg["gameid"] = tg["gameid"].astype(str)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"]).sort_values("date")

    # --- forma PONTO-NO-TEMPO: so jogos anteriores ao proprio jogo ---
    #
    # PERCORRE JOGO A JOGO, nunca linha a linha. Cada jogo ocupa duas linhas no
    # CSV (uma por time) com a MESMA data, e a ordenacao do pandas nao garante
    # desempate: medido, a linha do time vermelho vinha primeiro em 46,6% dos
    # jogos. Percorrendo linha a linha, a "forma do adversario" ja continha o
    # resultado DESTE jogo em quase metade da amostra -- e um resultado proprio
    # dentro de uma janela de 10 mapas e sinal quase perfeito.
    #
    # Foi assim que este mesmo arquivo chegou a marcar +1,57 de nota no placar
    # da serie. Era o vazamento, nao o sinal.
    historico = {}
    serie = {}          # (dia, par de times) -> vitorias do time par[0]
    linhas = []

    def _forma(t):
        h = historico.get(t) or []
        if len(h) < 3:
            return None
        u = h[-JANELA_FORMA:]
        return sum(1 for v in u if v) / len(u)

    jogos = tg[tg["side"].astype(str).str.lower() == "blue"].copy()
    jogos = jogos.sort_values(["date", "gameid"], kind="mergesort")

    for r in jogos.itertuples(index=False):
        gid = str(r.gameid)
        blue, red, venceu = str(r.team), str(r.opponent), bool(r.win)
        par = tuple(sorted((blue, red)))
        ch_serie = (str(r.date)[:10], par)
        if gid in final:
            fa, fb = _forma(blue), _forma(red)
            p, y = final[gid]
            m = meta.get(gid) or {}
            feitos = serie.get(ch_serie) or []
            placar = sum((1 if (v if par[0] == blue else not v) else -1) for v in feitos)
            linhas.append({"p": p, "y": y, "date": r.date,
                           "forma": (fa - fb) if (fa is not None and fb is not None) else 0.0,
                           "tem": fa is not None and fb is not None,
                           "serie": float(placar), "n_serie": len(feitos),
                           "inter": bool(m.get("inter", False)),
                           "mapa": int(getattr(r, "map_number", 1) or 1)})
        # SO ENTAO os dois times, e a serie, aprendem com este jogo.
        historico.setdefault(blue, []).append(venceu)
        historico.setdefault(red, []).append(not venceu)
        serie.setdefault(ch_serie, []).append(venceu if par[0] == blue else (not venceu))

    linhas.sort(key=lambda x: x["date"])
    print("[empurrao] %d jogos, %d com forma dos dois lados" % (
        len(linhas), sum(1 for x in linhas if x["tem"])))

    def _nota(pegar_p):
        inter, same = [], []
        for x in linhas:
            (inter if x["inter"] else same).append((pegar_p(x), x["y"]))
        return nota_de(inter, same)

    base = _nota(lambda x: x["p"])
    print("[empurrao] nota de hoje: %.3f" % base)
    print()

    def _ajustar_w(amostra, col="forma"):
        """O empurrao que minimiza o logloss NAQUELE passado. Busca direta:
        uma linha so de parametro, e assim da para ver a curva inteira."""
        # A FAIXA precisa ser larga. A primeira versao ia so ate +0,60 e o
        # ajuste bateu no limite nos 7 blocos -- peso encostado na borda da
        # busca nao e o otimo, e o numero que sai dele nao vale nada.
        melhor, melhor_ll = 0.0, None
        for w in np.arange(-3.00, 3.01, 0.02):
            ll = 0.0
            for x in amostra:
                q = _sig(_logit(x["p"]) + w * x[col])
                q = min(max(q, 1e-9), 1 - 1e-9)
                ll += -(math.log(q) if x["y"] == 1 else math.log(1 - q))
            ll /= max(len(amostra), 1)
            if melhor_ll is None or ll < melhor_ll:
                melhor, melhor_ll = float(w), ll
        return melhor

    recortes = (
        ("todos os mapas", lambda x: True, "forma"),
        ("so o mapa 1 (serie nova)", lambda x: x["mapa"] <= 1, "forma"),
        ("so mapas 2+ (serie em curso)", lambda x: x["mapa"] >= 2, "forma"),
        ("mapas 2+, pelo PLACAR da serie", lambda x: x["mapa"] >= 2, "serie"),
    )
    for rotulo, filtro, col in recortes:
        print("--- %s  [sinal: %s] ---" % (rotulo, col))
        tam = len(linhas) // BLOCOS
        empurrado = {}
        pesos = []
        for k in range(1, BLOCOS):
            passado = [x for x in linhas[:k * tam] if x["tem"] and filtro(x)]
            bloco = linhas[k * tam:(k + 1) * tam] if k < BLOCOS - 1 else linhas[k * tam:]
            if len(passado) < 300:
                continue
            w = _ajustar_w(passado, col)
            pesos.append(w)
            for i, x in enumerate(bloco):
                idx = k * tam + i
                if x["tem"] and filtro(x):
                    empurrado[idx] = _sig(_logit(x["p"]) + w * x[col])
        if not empurrado:
            print("  (nao deu para ajustar)\n")
            continue
        # MACA COM MACA: a nota sai SO dos jogos deste recorte, nos dois
        # lados. Medir o empurrao do mapa 1 sobre o conjunto inteiro diluiria
        # o efeito em 8.526 jogos e devolveria quase zero por construcao.
        i_com, i_sem, s_com, s_sem = [], [], [], []
        for i, x in enumerate(linhas):
            if not (x["tem"] and filtro(x)):
                continue
            if x["inter"]:
                i_com.append((empurrado.get(i, x["p"]), x["y"]))
                i_sem.append((x["p"], x["y"]))
            else:
                s_com.append((empurrado.get(i, x["p"]), x["y"]))
                s_sem.append((x["p"], x["y"]))
        n = nota_de(i_com, s_com)
        n0 = nota_de(i_sem, s_sem)
        na_borda = sum(1 for w in pesos if abs(abs(w) - 3.00) < 1e-9)
        if na_borda:
            print("  AVISO: %d peso(s) na borda da busca -- alargue a faixa." % na_borda)
        print("  pesos ajustados por bloco: %s" % ", ".join("%+.2f" % w for w in pesos))
        print("  jogos deste recorte: %d (dos quais %d entre regioes)" % (
            len(i_com) + len(s_com), len(i_com)))
        print("  nota HOJE neste recorte ....... %.3f" % n0)
        print("  nota COM o empurrao ........... %.3f   (%+.3f)" % (n, n - n0))
        # OS DOIS LADOS SEPARADOS. A nota pesa 45% o inter-regional, que aqui
        # tem poucos jogos -- um ganho que so aparecesse ali seria fragil, e a
        # media esconderia isso.
        from tools.ml_quality_scorecard import _grade_from_logloss, _metrics
        def _g(lado):
            return _grade_from_logloss(_metrics(lado)["logloss"]) if lado else float("nan")
        print("    entre regioes (n=%4d): %.3f -> %.3f  (%+.3f)" % (
            len(i_com), _g(i_sem), _g(i_com), _g(i_com) - _g(i_sem)))
        print("    mesma regiao  (n=%4d): %.3f -> %.3f  (%+.3f)" % (
            len(s_com), _g(s_sem), _g(s_com), _g(s_com) - _g(s_sem)))
        # E BLOCO A BLOCO, porque media boa pode esconder epoca.
        tam_b = max(1, (len(i_com) + len(s_com)) // 6)
        seq = [(i, x) for i, x in enumerate(linhas) if x["tem"] and filtro(x)]
        ganhos = []
        for kb in range(6):
            pedaco = seq[kb * tam_b:(kb + 1) * tam_b] if kb < 5 else seq[kb * tam_b:]
            if len(pedaco) < 80:
                continue
            com = [(empurrado.get(i, x["p"]), x["y"]) for i, x in pedaco]
            sem = [(x["p"], x["y"]) for _, x in pedaco]
            ganhos.append(_g(com) - _g(sem))
        print("    por bloco: %s" % "  ".join("%+.2f" % g for g in ganhos))
        print("    blocos com ganho: %d de %d" % (sum(1 for g in ganhos if g > 0), len(ganhos)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
