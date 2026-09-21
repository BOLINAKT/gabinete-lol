# -*- coding: utf-8 -*-
"""Sobrou sinal na mesa? A pergunta que vem ANTES de inventar feature nova.

O CONTEXTO (21/09/2026). O diagnostico de `tools/onde_o_vencedor_erra.py`
mostrou que o erro do modelo de vencedor e de ORDEM, nao de escala:

    logloss hoje ......................... 0,64642
    com a melhor recalibracao possivel ... 0,63043
    erro de ESCALA (recalibravel) ........ 0,016
    erro de ORDEM (o que sobra) .......... 0,080   <- cinco vezes maior

E ele mandou atacar. So que "erro de ordem" nao diz O QUE FAZER -- diz apenas
que recalibrar nao salva. O passo honesto antes de construir sinal novo e
PROVAR QUE EXISTE sinal sobrando, e em qual direcao.

O TESTE
Para cada jogo ja pontuado FORA DA AMOSTRA, monta-se um punhado de sinais
simples a partir do CSV, usando SO os jogos ANTERIORES aquele (ponto-no-tempo
de verdade -- olhar o futuro aqui faria qualquer sinal parecer genial). Depois
pergunta-se: esse sinal prediz o resultado DEPOIS de ja saber o que o modelo
disse?

A conta e uma regressao logistica de y sobre [logit(p_modelo), sinal]. Se o
coeficiente do sinal for indistinguivel de zero, nao ha nada ali. Se for
grande e estavel, ha -- e o tamanho do ganho de logloss diz quanto vale.

POR QUE ISSO E O CAMINHO CURTO
Construir um sinal dentro do modelo custa retreino, gate e dias. Testar aqui
custa minutos, e reprova as ideias ruins antes de elas virarem trabalho.

O QUE SERIA ARMADILHA, e esta evitado:
  - ajustar e medir no mesmo dado infla tudo. Aqui ha divisao temporal: o
    coeficiente e ajustado na primeira metade (por data) e medido na segunda;
  - sinal que usa o proprio jogo (placar, duracao) preveria o passado. So
    entram jogos ANTERIORES;
  - "significativo" com 7 mil jogos e facil. Por isso sai tambem o GANHO DE
    LOGLOSS, que e o que decide se vale mexer no modelo.

O QUE SAIU (21/09/2026, contra a medicao com FORMATO DE PRODUCAO -- hybrid +
form + Platt, 7.296 jogos fora da amostra).

ATENCAO: a PRIMEIRA leitura destes numeros estava errada, e por vazamento do
futuro meu. Os dois conjuntos, lado a lado:

  sinal          com vazamento     CORRIGIDO
  forma            +0,0183          +0,0044 [+0,0021, +0,0073]
  h2h              +0,0094          +0,0005 [-0,0003, +0,0013]  nada
  descanso         -0,0001          -0,0005                     nada
  experiencia      +0,0028          +0,0025                     nada

O vazamento: cada jogo ocupa DUAS linhas no CSV (uma por time) com a mesma
data, e o laco percorria linha a linha. A linha do adversario podia ser
processada antes -- medido, em 46,6% dos jogos --, e ai a "forma recente do
adversario" ja continha o resultado DESTE jogo. Corrigido percorrendo JOGO a
jogo. O teste `test_a_forma_do_ADVERSARIO_nao_contem_o_jogo_atual` pega isso
num caso montado a mao, com resposta exata.

E a separacao que decide se o que sobrou SERVE:

  mapa 1 (jogo que nao comecou) .. +0,0009 [-0,0020, +0,0037]   NADA
  mapa 2+ (serie em curso) ....... +0,0076

Ou seja: para precificar uma partida que ainda nao comecou -- que e o que a
aba de Oportunidades faz -- forma recente NAO acrescenta nada ao modelo. O que
sobra vive nos mapas seguintes de uma serie ja em andamento, e ali o sinal
direto nao e "forma": e o PLACAR DA SERIE. Isso esta medido em
tools/empurrao_de_forma.py.

Uso: python tools/sobrou_sinal.py [arquivo_de_previsoes.json]
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

# QUAL arquivo de previsoes. Importa mais do que parece: a primeira rodada
# deste teste usou `nota_honesta_prod_diaria.json`, que foi gerado com
# com_hybrid=False e com_form=False -- ou seja, SEM as duas camadas de forma
# que a producao aplica. Ele "descobriu" que forma ajuda um modelo que nao
# tinha forma. Verdade inutil. O padrao agora e a medicao com FORMATO DE
# PRODUCAO (hybrid + form + Platt), que e contra quem a pergunta faz sentido.
PADRAO = "nota_honesta_prod_diaria_hybrid_form_platt.json"
PREVISOES = ROOT / "scratchpad" / "nota_honesta" / (
    sys.argv[1] if len(sys.argv) > 1 else PADRAO)
CSV = ROOT / "CSV_DIARIO" / "2026_LoL_esports_match_data_from_OraclesElixir.csv"

# Quantos mapas recentes contam como "forma". Curto de proposito: se forma
# ajuda, tem de ajudar no curto prazo -- no longo ela vira o proprio rating,
# que o modelo ja tem.
JANELA_FORMA = 10


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1.0 - p))


def _sig(z: float) -> float:
    if z < -700:
        return 1e-300
    return 1.0 / (1.0 + math.exp(-z))


def _logloss(ps, ys) -> float:
    t = 0.0
    for p, y in zip(ps, ys):
        q = min(max(float(p), 1e-9), 1 - 1e-9)
        t += -(math.log(q) if int(y) == 1 else math.log(1.0 - q))
    return t / max(len(ys), 1)


def _ajustar(xs, ys, passos: int = 60):
    """Regressao logistica por IRLS (Newton) -- converge de verdade.

    A PRIMEIRA versao disto usava gradiente com passo fixo, e ela MENTIU: o
    sinal "descanso" apareceu com ganho de -0,023, grande demais para ser
    acaso. A causa nao era o sinal, era o ajuste -- a diferenca de descanso
    vale +-100 dias, e com passo fixo uma coluna nessa escala nem chega perto
    do minimo em 400 passos. Numero que sai de ajuste nao convergido nao
    mede o sinal, mede o otimizador.

    IRLS resolve o sistema inteiro a cada passo, entao a escala da coluna
    deixa de importar, e 60 passos sobram.
    """
    import numpy as np

    X = np.asarray(xs, dtype=float)
    X = np.hstack([X, np.ones((X.shape[0], 1))])      # intercepto
    y = np.asarray(ys, dtype=float)
    w = np.zeros(X.shape[1])
    for _ in range(passos):
        z = X @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        s = np.clip(p * (1 - p), 1e-9, None)
        g = X.T @ (y - p)
        H = (X * s[:, None]).T @ X
        H[np.diag_indices_from(H)] += 1e-6            # so para nao singular
        try:
            passo = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w = w + passo
        if float(np.max(np.abs(passo))) < 1e-9:
            break
    return list(w[:-1]), float(w[-1])


def _prever(xs, w, b):
    return [_sig(b + sum(wi * xi for wi, xi in zip(w, x))) for x in xs]


def montar_dados(previsoes=None):
    previsoes = previsoes or PREVISOES

    import pandas as pd

    from mlcore.stats_teams import build_team_games, load_team_rows

    d = json.loads(previsoes.read_text(encoding="utf-8"))
    prev = {}
    for item in (d.get("por_jogo") or []):
        try:
            prev[str(item[0])] = (float(item[1]), int(item[2]))
        except (TypeError, ValueError, IndexError):
            continue

    tg = build_team_games(load_team_rows(str(CSV)))
    tg["gameid"] = tg["gameid"].astype(str)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"]).sort_values("date")

    return montar_linhas(tg, prev)


def montar_linhas(tg, prev):
    """Os sinais de cada jogo, com o historico que existia ANTES dele.

    Recebe o quadro e as previsoes em vez de le-los do disco: e o que permite
    a um teste alimentar um caso onde o vazamento seria gritante.
    """
    import math

    # --- historico PONTO-NO-TEMPO: so o que aconteceu ANTES de cada jogo ---
    #
    # A PRIMEIRA VERSAO DISTO VAZOU O FUTURO, e vale registrar como.
    #
    # Cada jogo ocupa DUAS linhas no CSV (uma por time). Eu percorria linha a
    # linha, montava os sinais na linha AZUL e so depois punha aquela linha no
    # historico. Parece certo -- e e, para o time azul. Mas a linha VERMELHA do
    # MESMO jogo podia ter sido processada antes: as duas tem a mesma data, e a
    # ordenacao do pandas nao garante desempate. MEDIDO: a vermelha vinha
    # primeiro em 46,6% dos jogos. Nesses, a "forma recente do adversario" ja
    # continha o resultado DESTE jogo.
    #
    # Numa janela de 10 mapas, um deles ser o proprio jogo e sinal quase
    # perfeito -- e foi isso que apareceu como "sobrou sinal".
    #
    # O conserto: percorrer JOGO a jogo, nunca linha a linha. O jogo vira
    # numero primeiro; so depois os DOIS times aprendem com ele.
    historico = {}          # time -> lista de (data, venceu)
    confrontos = {}         # (a,b) ordenado -> lista de (data, venceu_a)
    descanso = {}           # time -> data do ultimo jogo

    def _forma(time, janela=JANELA_FORMA):
        h = historico.get(time) or []
        if len(h) < 3:
            return None
        ult = h[-janela:]
        return sum(1 for _, v in ult if v) / len(ult)

    # Uma linha por JOGO: a do lado azul ja traz time, adversario e o
    # resultado do azul. O desempate por gameid deixa a ordem deterministica.
    jogos = tg[tg["side"].astype(str).str.lower() == "blue"].copy()
    jogos = jogos.sort_values(["date", "gameid"], kind="mergesort")

    dados = []
    for r in jogos.itertuples(index=False):
        gid = str(r.gameid)
        blue, red, venceu, quando = str(r.team), str(r.opponent), bool(r.win), r.date

        if gid in prev:
            p, y = prev[gid]
            f_a, f_b = _forma(blue), _forma(red)
            ch = tuple(sorted((blue, red)))
            h2h = confrontos.get(ch) or []
            n_h2h = len(h2h)
            if n_h2h >= 3:
                venc = sum(1 for _, v in h2h if (v if ch[0] == blue else not v))
                taxa_h2h = venc / n_h2h
            else:
                taxa_h2h = None
            d_a = (quando - descanso[blue]).days if blue in descanso else None
            d_b = (quando - descanso[red]).days if red in descanso else None
            dados.append({
                "p": p, "y": y, "date": quando, "liga": str(r.league),
                "mapa": int(getattr(r, "map_number", 1) or 1),
                "forma": (f_a - f_b) if (f_a is not None and f_b is not None) else None,
                "h2h": (taxa_h2h - 0.5) if taxa_h2h is not None else None,
                "n_h2h": n_h2h,
                "descanso": ((d_a - d_b) if (d_a is not None and d_b is not None) else None),
                "experiencia": (math.log1p(len(historico.get(blue) or []))
                                - math.log1p(len(historico.get(red) or []))),
            })

        # SO ENTAO os DOIS times aprendem com este jogo.
        historico.setdefault(blue, []).append((quando, venceu))
        historico.setdefault(red, []).append((quando, not venceu))
        descanso[blue] = quando
        descanso[red] = quando
        ch = tuple(sorted((blue, red)))
        confrontos.setdefault(ch, []).append(
            (quando, venceu if ch[0] == blue else (not venceu)))

    dados.sort(key=lambda x: x["date"])
    return dados



def main() -> int:
    if not PREVISOES.exists():
        print("[sinal] nao achei %s" % PREVISOES)
        return 1
    dados = montar_dados()
    if not dados:
        print("[sinal] nenhum jogo casou entre as previsoes e o CSV.")
        return 1
    print("[sinal] %d jogos com previsao fora da amostra e historico montado" % len(dados))
    corte = len(dados) // 2
    print("[sinal] ajuste nos %d primeiros (ate %s), medicao nos %d ultimos" % (
        corte, str(dados[corte]["date"])[:10], len(dados) - corte))
    print()

    base_tr = [[_logit(x["p"])] for x in dados[:corte]]
    base_te = [[_logit(x["p"])] for x in dados[corte:]]
    y_tr = [x["y"] for x in dados[:corte]]
    y_te = [x["y"] for x in dados[corte:]]
    w0, b0 = _ajustar(base_tr, y_tr)
    ll_base = _logloss(_prever(base_te, w0, b0), y_te)
    print("logloss so com o modelo (recalibrado) ..... %.5f" % ll_base)
    print()
    print("%-14s %7s %9s %20s" % ("sinal", "n", "peso", "ganho (IC 95%)"))

    def _ganho(nome_ou_lista):
        nomes = ([nome_ou_lista] if isinstance(nome_ou_lista, str)
                 else list(nome_ou_lista))
        tr = [x for x in dados[:corte] if all(x[n] is not None for n in nomes)]
        te = [x for x in dados[corte:] if all(x[n] is not None for n in nomes)]
        if len(tr) < 200 or len(te) < 200:
            return None
        v = lambda x: [_logit(x["p"])] + [float(x[n]) for n in nomes]
        w, b = _ajustar([v(x) for x in tr], [x["y"] for x in tr])
        p_com = _prever([v(x) for x in te], w, b)
        # a base MEDIDA NO MESMO recorte, senao a comparacao nao vale
        wb, bb = _ajustar([[_logit(x["p"])] for x in tr], [x["y"] for x in tr])
        p_sem = _prever([[_logit(x["p"])] for x in te], wb, bb)
        ys = [x["y"] for x in te]
        return {"n": len(te), "peso": w[1:], "com": p_com, "sem": p_sem, "y": ys,
                "ganho": _logloss(p_sem, ys) - _logloss(p_com, ys)}

    def _ic(r, repeticoes=600):
        """IC por reamostragem dos MESMOS jogos -- os modelos ficam fixos.

        E o que a pergunta pede: "esse ganho aguenta outra amostra de jogos?",
        nao "aguenta outro ajuste?".
        """
        import numpy as np
        rng = np.random.default_rng(20260921)
        y = np.asarray(r["y"], float)
        c = np.clip(np.asarray(r["com"], float), 1e-9, 1 - 1e-9)
        m = np.clip(np.asarray(r["sem"], float), 1e-9, 1 - 1e-9)
        dif = -(y * np.log(m) + (1 - y) * np.log(1 - m))               + (y * np.log(c) + (1 - y) * np.log(1 - c))
        amostras = dif[rng.integers(0, len(dif), size=(repeticoes, len(dif)))].mean(axis=1)
        return float(np.percentile(amostras, 2.5)), float(np.percentile(amostras, 97.5))

    resultados = {}
    for nome in ("forma", "h2h", "descanso", "experiencia"):
        r = _ganho(nome)
        if r is None:
            print("%-14s  (poucos jogos para julgar)" % nome)
            continue
        resultados[nome] = r
        lo, hi = _ic(r)
        veredito = "SOBROU SINAL" if lo > 0 else "nao da para afirmar"
        print("%-14s %7d %9.3f   %+.5f [%+.5f,%+.5f]  %s" % (
            nome, r["n"], r["peso"][0], r["ganho"], lo, hi, veredito))

    juntos = [n for n in ("forma", "h2h") if n in resultados]
    if len(juntos) > 1:
        r = _ganho(juntos)
        if r is not None:
            lo, hi = _ic(r)
            print()
            print("%-14s %7d %9s   %+.5f [%+.5f,%+.5f]" % (
                "+".join(juntos), r["n"], "-", r["ganho"], lo, hi))
            print("(os dois juntos -- se somar bem menos que a soma, eles dizem "
                  "a mesma coisa)")

    # ---------------------------------------------------------------
    # O ganho aguenta OUTROS periodos? Um corte so pode ser sorte de epoca:
    # meta muda, times somem, ligas comecam. Aqui o ajuste anda para frente --
    # treina no passado, mede no bloco seguinte, cinco vezes.
    # ---------------------------------------------------------------
    # ---------------------------------------------------------------
    # MAPA 1 x MAPA 2+ -- a separacao que decide se isto vale para APOSTAR.
    #
    # Num BO3, o mapa 2 sabe quem ganhou o mapa 1, e isso entra na "forma"
    # legitimamente (aconteceu antes). So que a aba de Oportunidades precifica
    # partida que ainda NAO comecou. Se o ganho todo estiver nos mapas 2+, ele
    # e verdadeiro e inutil para o uso que ele tem.
    # ---------------------------------------------------------------
    print()
    print("O ganho vale para jogo que AINDA NAO COMECOU?")
    print("%-22s %7s %12s" % ("recorte", "n", "ganho forma"))
    for rotulo, filtro in (("mapa 1 (serie nova)", lambda x: x["mapa"] <= 1),
                           ("mapa 2+ (serie em curso)", lambda x: x["mapa"] >= 2)):
        tr = [x for x in dados[:corte] if x["forma"] is not None and filtro(x)]
        te = [x for x in dados[corte:] if x["forma"] is not None and filtro(x)]
        if len(tr) < 150 or len(te) < 150:
            print("%-22s %7d  (poucos jogos)" % (rotulo, len(tr) + len(te)))
            continue
        v = lambda x: [_logit(x["p"]), float(x["forma"])]
        w, b = _ajustar([v(x) for x in tr], [x["y"] for x in tr])
        wb, bb = _ajustar([[_logit(x["p"])] for x in tr], [x["y"] for x in tr])
        ys = [x["y"] for x in te]
        g = (_logloss(_prever([[_logit(x["p"])] for x in te], wb, bb), ys)
             - _logloss(_prever([v(x) for x in te], w, b), ys))
        print("%-22s %7d %12s" % (rotulo, len(te), "%+.5f" % g))

    print()
    print("O MESMO TESTE, andando no tempo (treina no passado, mede no bloco seguinte)")
    print("%-12s %-12s %7s %10s %10s" % ("ate", "mede ate", "n", "forma", "forma+h2h"))
    blocos = 6
    tam = len(dados) // blocos
    for k in range(1, blocos):
        tr_all, te_all = dados[:k * tam], dados[k * tam:(k + 1) * tam]

        def _g(nomes):
            tr = [x for x in tr_all if all(x[n] is not None for n in nomes)]
            te = [x for x in te_all if all(x[n] is not None for n in nomes)]
            if len(tr) < 150 or len(te) < 150:
                return None
            v = lambda x: [_logit(x["p"])] + [float(x[n]) for n in nomes]
            w, b = _ajustar([v(x) for x in tr], [x["y"] for x in tr])
            wb, bb = _ajustar([[_logit(x["p"])] for x in tr], [x["y"] for x in tr])
            ys = [x["y"] for x in te]
            return (_logloss(_prever([[_logit(x["p"])] for x in te], wb, bb), ys)
                    - _logloss(_prever([v(x) for x in te], w, b), ys))

        g1, g2 = _g(["forma"]), _g(["forma", "h2h"])
        print("%-12s %-12s %7d %10s %10s" % (
            str(tr_all[-1]["date"])[:10], str(te_all[-1]["date"])[:10], len(te_all),
            ("%+.5f" % g1) if g1 is not None else "  -",
            ("%+.5f" % g2) if g2 is not None else "  -"))

    print()
    print("peso = quanto o sinal empurra a probabilidade, depois do modelo.")
    print("ganho = logloss que ele tira, medido em jogos que o ajuste NAO viu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
