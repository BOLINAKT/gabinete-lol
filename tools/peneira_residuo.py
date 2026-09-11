# -*- coding: utf-8 -*-
"""PENEIRA: um sinal candidato explica onde o modelo ERRA? (teste pre-construcao)

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ POR QUE ESTE ARQUIVO EXISTE: antes de investir semanas construindo draft,   ║
║ camada de jogador ou margem mais funda, medir se cada um tem o que          ║
║ acrescentar. A pergunta NAO e "o sinal preve?" — e "o sinal preve algo que  ║
║ o modelo AINDA NAO SABE?".                                                  ║
║                                                                             ║
║ 1. O PERIGO QUE ISTO EVITA, em uma frase da fonte: "significancia           ║
║    estatistica de novas variaveis preditoras NAO se traduz necessariamente  ║
║    em aumento estatisticamente significativo da AUC". Um sinal pode ser     ║
║    comprovadamente ligado ao resultado e AINDA ASSIM nao acrescentar nada.  ║
║    https://onlinelibrary.wiley.com/doi/10.1002/bimj.201300260               ║
║    (resumo lido em 10/09/2026)                                              ║
║    MEDIDO NESTE PROJETO: hybrid_blend e season_form_blend preveem os DOIS,  ║
║    e juntos rendem menos da metade da soma (interacao -0,0043). Sobreposicao║
║    e a regra, nao a excecao.                                                ║
║                                                                             ║
║ 2. O METODO: residualizacao. "Primeiro deixe um modelo baseline explicar a  ║
║    parte do resultado que voce ja sabe explicar. Depois, testar se as       ║
║    variaveis adicionais correlacionam com os RESIDUOS diz se elas fornecem  ║
║    informacao genuinamente nova, ajudando a decidir se o custo de inclui-las║
║    se justifica."                                                           ║
║    https://medium.com/data-science-collective/residualisation-in-ai-estimating-what-a-feature-adds-after-the-baseline-96598ce50e6d
║    (resumo lido em 10/09/2026)                                              ║
║                                                                             ║
║ 3. POR QUE RESIDUALIZAR OS DOIS LADOS (Frisch-Waugh-Lovell): "para obter o  ║
║    coeficiente de uma variavel nova controlando pelas variaveis da baseline,║
║    voce residualiza TANTO o alvo QUANTO a variavel nova contra a baseline". ║
║    Isso resolve de graca o confundimento do draft: forca de campeao medida  ║
║    por taxa de vitoria crua embute forca de TIME ("campeoes mais escolhidos ║
║    tem taxa real maior que a empirica"). Residualizar tira a parte que era  ║
║    time e deixa a parte que e campeao.                                      ║
║    https://www.itero.gg/articles/how-useful-is-a-champions-win-rate         ║
║    (resumo lido em 10/09/2026)                                              ║
║                                                                             ║
║ 4. REGRA INVIOLAVEL: so entra informacao anterior a partida. Testar o       ║
║    residuo contra estatisticas do PROPRIO jogo faria tudo correlacionar —   ║
║    e seria o vazamento que a Fase 0 inteira existiu para eliminar. Forca de ║
║    campeao e calculada SO com jogos anteriores a data da partida.           ║
║                                                                             ║
║ 5. ERRO-PADRAO DIADICO (Cameron/Gelbach/Miller), igual ao resto da Fase 2:  ║
║    cada jogo pertence a dois times, entao V = V_a + V_b - V_par.            ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
  python tools/peneira_residuo.py --sinal draft
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.comparar_variantes import _var_agrupada  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

# A melhor configuracao medida (WHR + ouro aos 15 + hybrid + forma) = nota 7,25.
# A peneira tem que rodar contra o MELHOR modelo: um sinal que so explica o erro
# de um modelo pior nao acrescenta nada ao que vamos usar.
# ATUALIZADO EM 10/09/2026: a baseline passou a ser a versao COM calibrador
# Platt. A anterior media um modelo sem calibrar — ver EMENDA 3 do protocolo.
# Peneirar contra baseline errada mediria o sinal contra um erro que nao e o
# erro real do produto.
BASELINE = (ROOT / "scratchpad" / "nota_honesta"
            / "nota_honesta_margem_diaria_hybrid_form_platt.json")


def _logito(p: float) -> float:
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def carregar_baseline() -> pd.DataFrame:
    d = json.loads(BASELINE.read_text(encoding="utf-8"))
    df = pd.DataFrame(d["por_jogo"], columns=["gameid", "p", "y"])
    df["logito"] = df["p"].apply(_logito)
    df["residuo"] = df["y"] - df["p"]
    return df


def forca_de_campeao_pit(csvs: list[str]) -> pd.DataFrame:
    """Para cada (gameid, lado), a soma da forca dos 5 campeoes — POINT-IN-TIME.

    Forca de um campeao na data D = taxa de vitoria nos jogos ANTERIORES a D,
    encolhida para 50% por poucos jogos (shrink bayesiano simples). Sem o
    encolhimento, um campeao com 2 jogos e 2 vitorias viraria "100% forte".
    """
    cols = ["gameid", "date", "participantid", "champion", "result", "side", "patch"]
    quadros = []
    for c in csvs:
        pv = pd.read_csv(c, nrows=1, low_memory=False)
        uso = [x for x in cols if x in pv.columns]
        d = pd.read_csv(c, low_memory=False, usecols=uso)
        quadros.append(d)
    df = pd.concat(quadros, ignore_index=True)
    df = df[(df["participantid"] >= 1) & (df["participantid"] <= 10)].copy()  # so jogadores
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "champion", "result"]).sort_values("date")
    df["result"] = pd.to_numeric(df["result"], errors="coerce")
    df = df.dropna(subset=["result"])
    df["lado"] = np.where(df["participantid"] <= 5, "blue", "red")

    # Acumulado ANTERIOR por campeao (expanding shift): vitorias e jogos ate o
    # jogo anterior. groupby.cumsum + shift faz isso sem olhar o presente.
    df = df.sort_values(["champion", "date"])
    g = df.groupby("champion", sort=False)
    df["v_ant"] = g["result"].cumsum() - df["result"]
    df["n_ant"] = g.cumcount()
    BETA = 30.0   # encolhimento: 30 jogos-equivalentes de prior em 50%
    df["forca"] = (df["v_ant"] + 0.5 * BETA) / (df["n_ant"] + BETA)

    agg = (df.groupby(["gameid", "lado"], sort=False)["forca"].sum().unstack("lado"))
    agg = agg.dropna()
    agg["draft_dif"] = agg["blue"] - agg["red"]
    return agg.reset_index()[["gameid", "draft_dif"]]


def desempenho_de_jogador_pit(csvs: list[str]) -> pd.DataFrame:
    """Diferenca de DESEMPENHO PASSADO dos 5 jogadores de cada lado.

    O caminho que a literatura aponta (PandaSkill, LoL, 37.400 partidas): avaliar
    o jogador pelo COMO ele jogou, nao por ter ganhado. Taxa de vitoria de
    jogador e a mesma informacao que o rating do time ja usou.

    Versao de peneira: para cada jogo-jogador, um z-score DENTRO DA ROTA de
    algumas estatisticas de desempenho; a nota do jogador e a media das
    anteriores. Point-in-time por construcao (cumsum deslocado).
    """
    cols = ["gameid", "date", "participantid", "position", "playername", "result",
            "kills", "deaths", "assists", "earnedgoldshare", "damageshare",
            "golddiffat15"]
    quadros = []
    for c in csvs:
        pv = pd.read_csv(c, nrows=1, low_memory=False)
        uso = [x for x in cols if x in pv.columns]
        quadros.append(pd.read_csv(c, low_memory=False, usecols=uso))
    df = pd.concat(quadros, ignore_index=True)
    df = df[(df["participantid"] >= 1) & (df["participantid"] <= 10)].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "playername", "position"]).sort_values("date")
    df["lado"] = np.where(df["participantid"] <= 5, "blue", "red")
    df = df.sort_values("date").reset_index(drop=True)

    # z-score DENTRO DA ROTA: comparar suporte com atirador por ouro nao faz
    # sentido; a rota e o grupo de comparacao natural.
    # z-score DENTRO DA ROTA, com media e desvio EXPANSIVOS (so o passado).
    # DEFEITO CORRIGIDO EM 10/09/2026: a primeira versao usava media e desvio da
    # base INTEIRA, incluindo jogos futuros. Look-ahead na constante de
    # normalizacao — pequeno, mas e exatamente o erro que a Fase 0 inteira
    # existiu para eliminar, e "pequeno" nao e medicao.
    def _z_expansivo(v: pd.Series) -> pd.Series:
        g = v.groupby(df["position"], sort=False)
        m = g.transform(lambda x: x.expanding().mean().shift(1))
        sd = g.transform(lambda x: x.expanding().std().shift(1))
        return ((v - m) / sd.replace(0.0, np.nan)).fillna(0.0)

    partes = []
    for col in ("earnedgoldshare", "damageshare", "golddiffat15"):
        if col not in df.columns:
            continue
        partes.append(_z_expansivo(pd.to_numeric(df[col], errors="coerce")))
    if "kills" in df.columns and "deaths" in df.columns:
        kda = ((pd.to_numeric(df["kills"], errors="coerce").fillna(0)
                + pd.to_numeric(df.get("assists", 0), errors="coerce").fillna(0))
               / (pd.to_numeric(df["deaths"], errors="coerce").fillna(0) + 1.0))
        partes.append(_z_expansivo(kda))
    if not partes:
        raise SystemExit("nenhuma estatistica de desempenho disponivel no CSV")
    df["pscore"] = sum(partes) / len(partes)

    # media das partidas ANTERIORES daquele jogador
    df = df.sort_values(["playername", "date"])
    g = df.groupby("playername", sort=False)
    soma_ant = g["pscore"].cumsum() - df["pscore"]
    n_ant = g.cumcount()
    BETA = 10.0   # encolhe para 0 (media da rota) quem tem poucos jogos
    df["nota_jogador"] = soma_ant / (n_ant + BETA)

    agg = df.groupby(["gameid", "lado"], sort=False)["nota_jogador"].sum().unstack("lado")
    agg = agg.dropna()
    agg["jogadores_dif"] = agg["blue"] - agg["red"]
    return agg.reset_index()[["gameid", "jogadores_dif"]]


def margem_funda_pit(csvs: list[str]) -> pd.DataFrame:
    """Perfil de margem PASSADO dos times, ALEM do ouro aos 15.

    O modelo ja usa gd15 dentro do rating. A pergunta aqui e se as OUTRAS
    medidas de inicio de jogo (ouro aos 10 e 20, XP, farm) carregam algo que o
    gd15 nao carrega. Tudo com media das partidas ANTERIORES.
    """
    from mlcore.stats_teams import build_team_games, load_team_rows
    df = pd.concat([build_team_games(load_team_rows(c)) for c in csvs],
                   ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "team", "gameid"]).sort_values("date")

    alvos = [c for c in ("golddiffat10_for", "golddiffat20_for", "xpdiffat15_for",
                         "csdiffat15_for") if c in df.columns]
    if not alvos:
        raise SystemExit("nenhuma coluna de margem funda no CSV")
    print(f"  colunas usadas: {', '.join(alvos)}")

    # media das partidas ANTERIORES daquele time, por coluna
    df = df.sort_values(["team", "date"])
    g = df.groupby("team", sort=False)
    comps = []
    for c in alvos:
        v = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        soma = v.groupby(df["team"], sort=False).cumsum() - v
        n = g.cumcount()
        media = soma / (n + 10.0)          # encolhe quem tem poucos jogos
        comps.append(media / (media.std() or 1.0))
    df["perfil"] = sum(comps) / len(comps)

    # a linha do CSV e por TIME; o gameid tem duas. Diferenca = time - oponente.
    piv = df.pivot_table(index="gameid", columns=None, values="perfil",
                         aggfunc=list)
    linhas = []
    for gid, vals in piv["perfil"].items():
        if isinstance(vals, list) and len(vals) == 2:
            linhas.append((gid, float(vals[0]) - float(vals[1])))
    return pd.DataFrame(linhas, columns=["gameid", "margem_funda_dif"])


def peneirar(base: pd.DataFrame, sinal: pd.DataFrame, nome: str,
             times: dict) -> None:
    """Frisch-Waugh-Lovell: residualiza ALVO e SINAL contra a baseline, e mede
    o que sobra de associacao entre eles."""
    d = base.merge(sinal, on="gameid", how="inner")
    if len(d) < 300:
        print(f"[{nome}] so {len(d)} jogos em comum — amostra insuficiente")
        return

    x = d[sinal.columns[1]].to_numpy(dtype=float)
    r = d["residuo"].to_numpy(dtype=float)
    z = d["logito"].to_numpy(dtype=float)

    # residualiza o SINAL contra o que a baseline ja sabe (o logito dela)
    A = np.column_stack([z, np.ones_like(z)])
    coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    x_res = x - A @ coef

    # a associacao que sobra
    sx = x_res.std()
    if sx <= 0:
        print(f"[{nome}] sinal constante apos residualizar")
        return
    xn = x_res / sx
    b = float(np.dot(xn, r) / np.dot(xn, xn))     # inclinacao: residuo ~ sinal

    # erro-padrao diadico da inclinacao
    infl = xn * (r - b * xn) / np.dot(xn, xn)     # funcao de influencia
    ta = [times.get(g, ("?", "?"))[0] for g in d["gameid"]]
    tb = [times.get(g, ("?", "?"))[1] for g in d["gameid"]]
    par = [tuple(sorted(t)) for t in zip(ta, tb)]
    n = len(infl)
    v = (_var_agrupada(infl * n, ta) + _var_agrupada(infl * n, tb)
         - _var_agrupada(infl * n, par))
    se = math.sqrt(v) if v > 0 else float("nan")
    p = (2 * (1 - 0.5 * (1 + math.erf(abs(b / se) / math.sqrt(2))))
         if se and math.isfinite(se) and se > 0 else float("nan"))

    # quanto do erro o sinal explicaria, em logloss
    corr = float(np.corrcoef(xn, r)[0, 1])
    print(f"\n[{nome}]  n={len(d)}")
    print(f"  inclinacao (residuo por desvio-padrao do sinal): {b:+.5f}")
    print(f"  IC95 diadico: [{b - 1.96 * se:+.5f}, {b + 1.96 * se:+.5f}]   p={p:.5f}")
    print(f"  correlacao com o erro: {corr:+.4f}")
    if math.isfinite(p) and p < 0.05 and abs(b) > 0.005:
        print("  VEREDITO: tem sinal — vale investigar construir")
    else:
        print("  VEREDITO: NAO explica o erro — construir isto nao deve render")


def quanto_vale(base: pd.DataFrame, sinal: pd.DataFrame, nome: str) -> None:
    """Converte "tem sinal" em "vale X de logloss" — FORA DA AMOSTRA.

    Ajusta o coeficiente na PRIMEIRA metade cronologica e mede na SEGUNDA.
    Ajustar e medir no mesmo lugar daria um numero inflado, que e exatamente o
    defeito que a Fase 0 desta sessao existiu para corrigir.
    """
    d = base.merge(sinal, on="gameid", how="inner").reset_index(drop=True)
    col = sinal.columns[1]
    # ordem cronologica pela ordem do proprio replay (o por_jogo ja vem em ordem)
    corte = len(d) // 2
    tr, te = d.iloc[:corte], d.iloc[corte:]

    # logistica simples: y ~ logito_do_modelo + sinal  (Newton, 2 parametros
    # alem do intercepto; sem biblioteca externa para nao mudar o ambiente)
    def ajusta(df):
        X = np.column_stack([df["logito"].to_numpy(float),
                             df[col].to_numpy(float),
                             np.ones(len(df))])
        y = df["y"].to_numpy(float)
        w = np.zeros(3)
        for _ in range(60):
            z = X @ w
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            g = X.T @ (y - p)
            H = -(X.T * (p * (1 - p))) @ X
            try:
                passo = np.linalg.solve(H, -g)
            except np.linalg.LinAlgError:
                break
            w = w + passo
            if np.max(np.abs(passo)) < 1e-9:
                break
        return w

    def ll(y, p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())

    # DEFEITO CORRIGIDO EM 10/09/2026: a primeira versao comparava o modelo COM
    # sinal contra o modelo CRU. Mas a logistica tambem reajusta a inclinacao do
    # logito (saiu 1.11, 1.09, 0.88 nos tres sinais) — entao parte do "ganho"
    # era so RECALIBRAR, e nao o sinal novo. Toda comparacao agora tem uma
    # baseline que TAMBEM recalibra; a diferenca entre as duas isola o sinal.
    def ajusta_sem_sinal(df):
        X = np.column_stack([df["logito"].to_numpy(float), np.ones(len(df))])
        y = df["y"].to_numpy(float)
        w = np.zeros(2)
        for _ in range(60):
            z = X @ w
            pr = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            g = X.T @ (y - pr)
            H = -(X.T * (pr * (1 - pr))) @ X
            try:
                passo = np.linalg.solve(H, -g)
            except np.linalg.LinAlgError:
                break
            w = w + passo
            if np.max(np.abs(passo)) < 1e-9:
                break
        return w

    w = ajusta(tr)
    w0 = ajusta_sem_sinal(tr)
    yte = te["y"].to_numpy(float)
    Xte = np.column_stack([te["logito"].to_numpy(float),
                           te[col].to_numpy(float), np.ones(len(te))])
    X0 = np.column_stack([te["logito"].to_numpy(float), np.ones(len(te))])
    p_novo = 1.0 / (1.0 + np.exp(-np.clip(Xte @ w, -30, 30)))
    p_recal = 1.0 / (1.0 + np.exp(-np.clip(X0 @ w0, -30, 30)))
    p_base = te["p"].to_numpy(float)
    ll_base, ll_recal, ll_novo = ll(yte, p_base), ll(yte, p_recal), ll(yte, p_novo)
    ganho = ll_recal - ll_novo          # <- SO o sinal
    ganho_recal = ll_base - ll_recal    # <- so a recalibracao

    def nota(x):
        return max(0.0, min(10.0, 5.0 + (0.6931 - x) / (0.6931 - 0.55) * 4.5))

    print(f"\n[{nome}] QUANTO VALE (ajustado em {len(tr)} jogos, medido em {len(te)}):")
    print(f"  coeficiente do sinal: {w[1]:+.4f}   (do logito do modelo: {w[0]:+.3f})")
    print(f"  logloss cru      {ll_base:.5f}")
    print(f"  so RECALIBRANDO  {ll_recal:.5f}   (ganho {ganho_recal:+.5f} — nao e o sinal)")
    print(f"  com o SINAL      {ll_novo:.5f}")
    print(f"  GANHO DO SINAL   {ganho:+.5f}      nota {nota(ll_recal):.2f} -> {nota(ll_novo):.2f}")
    print(f"  barra da casa (>0.002): {'PASSA' if ganho > 0.002 else 'NAO PASSA'}")
    print("  AVISO: teto ESTIMADO com a forma mais crua do sinal. O coeficiente")
    print("  foi ajustado em metade dos MESMOS jogos da Fase 2 — separado no")
    print("  tempo, mas nao e amostra independente.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sinal", default="draft", choices=["draft", "jogadores", "margem"])
    args = ap.parse_args()

    from tools.comparar_variantes import _times_por_jogo
    base = carregar_baseline()
    print(f"baseline: {len(base)} jogos | erro medio absoluto "
          f"{base['residuo'].abs().mean():.4f}")
    times = _times_por_jogo()
    csvs = [str(c) for c in default_csvs()]

    if args.sinal == "draft":
        s = forca_de_campeao_pit(csvs)
        print(f"forca de campeao (point-in-time) montada para {len(s)} jogos")
        peneirar(base, s, "DRAFT (soma da forca dos campeoes)", times)
        quanto_vale(base, s, "DRAFT")
    elif args.sinal == "jogadores":
        s = desempenho_de_jogador_pit(csvs)
        print(f"desempenho de jogador (point-in-time) montado para {len(s)} jogos")
        peneirar(base, s, "JOGADORES (desempenho passado, por rota)", times)
        quanto_vale(base, s, "JOGADORES")
    elif args.sinal == "margem":
        s = margem_funda_pit(csvs)
        print(f"perfil de margem funda montado para {len(s)} jogos")
        peneirar(base, s, "MARGEM FUNDA (gd10/gd20/xp/cs passados)", times)
        quanto_vale(base, s, "MARGEM FUNDA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
