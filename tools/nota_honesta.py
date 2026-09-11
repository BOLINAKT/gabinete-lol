# -*- coding: utf-8 -*-
"""A NOTA, medida so em jogos que o modelo NUNCA viu (origem rolante).

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ O PROBLEMA (medido em 09/09/2026): tools/ml_fusion_scorecard.py percorre a  ║
║ temporada chamando model.p_blue() com o artefato JA TREINADO e nunca        ║
║ atualiza nada — nao ha uma linha de model.update() no laco. Como o treino   ║
║ come 2026 quase inteiro, a nota pontua 8.452 jogos dos quais 7.175 (84,9%)  ║
║ ESTAVAM NO TREINO. So 15,1% e previsao de verdade.                          ║
║                                                                             ║
║ 1. POR QUE ISSO INFLA A NOTA — a fonte canonica de avaliacao de series      ║
║    temporais diz literalmente: "as medidas de acuracia dos residuos sao     ║
║    MENORES, porque as 'previsoes' correspondentes vem de um modelo ajustado ║
║    ao conjunto de dados INTEIRO, em vez de serem previsoes de verdade".     ║
║    E a regra que a nota viola: o treino de cada ponto testado deve conter   ║
║    "apenas observacoes ANTERIORES a observacao que forma o teste".          ║
║    Hyndman & Athanasopoulos, Forecasting: Principles and Practice (3a ed.), ║
║    5.10 Time series cross-validation.                                       ║
║    https://otexts.com/fpp3/tscv.html  (aberta em 09/09/2026)                ║
║                                                                             ║
║ 2. POR QUE ORIGEM ROLANTE E NAO UM HOLDOUT SO — "no arranjo de origem fixa, ║
║    uma serie da apenas UMA previsao por passo", e os erros podem refletir   ║
║    "padroes observaveis apenas naquela regiao especifica". A recomendacao e ║
║    ter "previsoes suficientes em cada passo". Por isso aqui sao N dobras,   ║
║    nao um corte.                                                            ║
║    Hewamalage, Ackermann & Bergmeir, "Forecast Evaluation for Data          ║
║    Scientists: Common Pitfalls and Best Practices".                         ║
║    https://arxiv.org/abs/2203.10716  (texto aberto via ar5iv em 09/09/2026) ║
║                                                                             ║
║ 3. POR QUE JANELA EXPANSIVA (o treino cresce) e nao deslizante: a mesma     ║
║    fonte — expansiva e "boa para bases pequenas", deslizante serve a        ║
║    modelos puramente autorregressivos. Nossa base tem 3 anos; jogar fora o  ║
║    passado seria perder o pouco que ha.                                     ║
║                                                                             ║
║ 4. POR QUE NAO EMBARALHAR AS DATAS (k-fold comum): a mesma fonte lista 4    ║
║    problemas, entre eles "inverte a logica temporal (futuro no treino,      ║
║    passado no teste)" e "transforma previsao em imputacao de faltante".     ║
║                                                                             ║
║ 5. POR QUE MOSTRAR DOBRA A DOBRA e nao so o total: a mesma fonte manda usar ║
║    "varios operadores de resumo sobre os mesmos erros", porque medidas      ║
║    isoladas escondem problemas. Uma nota media boa com uma dobra pessima e  ║
║    um alerta, nao um sucesso.                                               ║
╚═════════════════════════════════════════════════════════════════════════════╝

COMO FUNCIONA, sem mexer no treino: `--holdout-days D` ja faz o train_offline
enxergar SO os dados anteriores a (data_max - D). Entao a dobra D treina com
corte em (data_max - D) e e pontuada apenas na janela [corte, corte + passo) —
jogos estritamente posteriores ao que ela viu.

  python tools/nota_honesta.py                      # producao de hoje
  python tools/nota_honesta.py --marca margem \
      --extra "--whr-mov gd15 --whr-mov-lambda 0.35 --whr-mov-folga 0.15"
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import subprocess
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

from mlcore.artifact import MLArtifact  # noqa: E402
from mlcore.utils import clip_prob  # noqa: E402
from mlcore.io_oracle import load_oracle_elixir_games  # noqa: E402
from mlcore.players_layer import (  # noqa: E402
    PlayersArtifact, load_match_player_rows, lineup_for_game,
    compute_delta_and_confidence, logit as _logit, sigmoid as _sigmoid,
)
from mlcore.tiers import tier_for_league  # noqa: E402
from mlcore.train_offline import (  # noqa: E402
    _infer_team_domestic_league_by_year, _infer_team_meta_latest, _resolve_home_league,
)
from tools.ml_quality_scorecard import _grade_from_logloss, _metrics, default_csvs  # noqa: E402

PY = sys.executable


def _escalas_de_fusao() -> tuple[float, float]:
    """Le os pesos de evidencia da fusao do MESMO params_fitted.json que o app.

    O app os pega em params_fitted["best"]["team_scale"] / ["players_scale"]
    (app_core/fit_runtime_core.py, linhas 30-31) e cai em 1.0 se faltarem.
    Cravar o numero aqui seria reimplementar producao — Principio V.
    """
    try:
        _pf = json.loads((ROOT / "params_fitted.json").read_text(encoding="utf-8"))
        _b = _pf.get("best") or {}
        return (max(0.0, float(_b.get("team_scale") or 1.0)),
                max(0.0, float(_b.get("players_scale") or 1.0)))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return (1.0, 1.0)


FUS_TEAM_SCALE, FUS_PLAYERS_SCALE = _escalas_de_fusao()


def treinar_dobra(dias: int, marca: str, extra: list[str], csvs: list[str],
                  pasta: Path) -> tuple[Path, Path]:
    """Treina um artefato que so enxerga dados anteriores a (data_max - dias)."""
    art = pasta / f"{marca}_h{dias}_artifact.json"
    ply = pasta / f"{marca}_h{dias}_players.json"
    if art.exists() and ply.exists():
        print(f"  [dobra {dias:>3}d] reaproveitando artefato ja treinado", flush=True)
        return art, ply
    cmd = [PY, "-m", "mlcore.train_offline", "--out", str(art), "--players-out", str(ply),
           "--holdout-days", str(int(dias))]
    for c in csvs:
        cmd += ["--csv", str(c)]
    cmd += list(extra)
    print(f"  [dobra {dias:>3}d] treinando...", flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit(f"treino da dobra {dias} falhou (rc={r.returncode})")
    return art, ply


def pontuar_janela(art_path: Path, ply_path: Path, jogos: pd.DataFrame,
                   ini, fim, player_rows, domestic_by_year, team_meta) -> dict:
    """Pontua [ini, fim) pelo caminho FUNDIDO — o mesmo que o app serve.

    Repete a matematica de ml_fusion_scorecard de proposito: se a nota honesta
    usasse outro caminho, ela mediria outro produto, e a comparacao com a nota
    de hoje perderia o sentido.
    """
    art = MLArtifact.load_json(str(art_path))
    p_art = PlayersArtifact.load_json(str(ply_path))
    w_lineup = float(((art.meta or {}).get("players_layer") or {}).get("w_lineup", 0.0) or 0.0)

    janela = jogos[(jogos["date"] >= ini) & (jogos["date"] < fim)]
    inter, same = [], []
    n_delta = 0
    for r in janela.itertuples(index=False):
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        blue, red = str(r.blue), str(r.red)
        lg = str(getattr(r, "league", "") or "OTHER")
        yy = None
        try:
            yy = int(r.year)
        except (TypeError, ValueError):
            yy = None
        bl = _resolve_home_league(team=blue, year=yy, match_league=lg,
                                  domestic_by_year=domestic_by_year, team_meta_latest=team_meta)
        rl = _resolve_home_league(team=red, year=yy, match_league=lg,
                                  domestic_by_year=domestic_by_year, team_meta_latest=team_meta)
        p0 = float(art.model.p_blue(blue, red, blue_league=bl, red_league=rl,
                                    blue_tier=str(tier_for_league(bl)),
                                    red_tier=str(tier_for_league(rl))))
        b_lin, r_lin = lineup_for_game(player_rows, str(r.gameid))
        res = compute_delta_and_confidence(
            p_art, blue_lineup=b_lin, red_lineup=r_lin,
            as_of=pd.to_datetime(r.date).date(), match_league=lg)
        d = float(res.get("delta", 0.0) or 0.0)
        cov_tot = float(res.get("coverage_total", 5) or 5.0)
        cov = float(res.get("coverage", 0) or 0.0) / (cov_tot if cov_tot else 5.0)
        d_eff = d * cov
        if abs(d_eff) > 1e-9:
            n_delta += 1
        fundido = float(_sigmoid(_logit(p0) + w_lineup * d_eff))
        (inter if bl != rl else same).append((fundido, y))
    return {"inter": inter, "same": same, "n_delta": n_delta, "w_lineup": w_lineup}


class NotaDeJogador:
    """Nota de jogador por DESEMPENHO (nao por resultado), point-in-time.

    ╔══ FONTES ══════════════════════════════════════════════════════════════╗
    ║ POR QUE POR DESEMPENHO: a camada de jogadores de producao avalia por    ║
    ║ RESULTADO, e o ajuste dela mediu peso -0,115 (negativo) — foi zerada    ║
    ║ pelo piso. Motivo provavel: "quem ganhou" e a MESMA informacao que o    ║
    ║ rating do time ja consumiu; sobra ruido.                                ║
    ║ O caminho da literatura, em artigo especifico de LoL (37.400 partidas): ║
    ║ "as notas de habilidade sao atualizadas SOMENTE com base nas notas de   ║
    ║ desempenho, e nao nos resultados das partidas, destacando as            ║
    ║ contribuicoes individuais". As variaveis que eles usam sao do mesmo     ║
    ║ tipo destas: participacao em ouro e dano, KDA, metricas por minuto.     ║
    ║ https://arxiv.org/html/2501.10049  (aberta em 10/09/2026)               ║
    ║                                                                         ║
    ║ POR QUE ENCOLHER POR JOGOS: "regularizacao encolhe as estimativas em    ║
    ║ funcao do tempo jogado — quem jogou pouco e puxado agressivamente para  ║
    ║ a media", e "encolhimento via modelagem hierarquica e uma das           ║
    ║ ferramentas mais importantes" contra ruido de jogador.                   ║
    ║ https://www.roycewebb.com/p/adjusted-plus-minus-explained (10/09/2026)  ║
    ║                                                                         ║
    ║ POR QUE Z-SCORE DENTRO DA ROTA: comparar suporte com atirador por ouro  ║
    ║ nao faz sentido; a rota e o grupo de comparacao natural.                ║
    ╚═════════════════════════════════════════════════════════════════════════╝
    """

    BETA = 10.0   # jogos-equivalentes de prior na media da rota

    def __init__(self, csvs: list[str]):
        import numpy as np
        cols = ["gameid", "date", "participantid", "position", "playername",
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
        df = df.dropna(subset=["date", "playername", "position"])
        df = df.sort_values("date").reset_index(drop=True)
        df["lado"] = np.where(df["participantid"] <= 5, "blue", "red")

        def _z(v):
            g = v.groupby(df["position"], sort=False)
            m = g.transform(lambda x: x.expanding().mean().shift(1))
            sd = g.transform(lambda x: x.expanding().std().shift(1))
            return ((v - m) / sd.replace(0.0, np.nan)).fillna(0.0)

        partes = []
        for c in ("earnedgoldshare", "damageshare", "golddiffat15"):
            if c in df.columns:
                partes.append(_z(pd.to_numeric(df[c], errors="coerce")))
        if "kills" in df.columns and "deaths" in df.columns:
            kda = ((pd.to_numeric(df["kills"], errors="coerce").fillna(0)
                    + pd.to_numeric(df.get("assists", 0), errors="coerce").fillna(0))
                   / (pd.to_numeric(df["deaths"], errors="coerce").fillna(0) + 1.0))
            partes.append(_z(kda))
        df["pscore"] = sum(partes) / len(partes)

        # media das partidas ANTERIORES do jogador
        df = df.sort_values(["playername", "date"])
        g = df.groupby("playername", sort=False)
        soma_ant = g["pscore"].cumsum() - df["pscore"]
        n_ant = g.cumcount()
        df["nota"] = soma_ant / (n_ant + self.BETA)

        agg = df.groupby(["gameid", "lado"], sort=False)["nota"].sum().unstack("lado")
        agg = agg.dropna()
        self._dif = {str(k): float(v) for k, v in (agg["blue"] - agg["red"]).items()}


    def _usar_escalacao_anterior(self, df):
        """Troca a nota dos 5 que jogaram pela dos 5 do jogo ANTERIOR do time.

        E o que o app consegue saber antes da partida: quem jogou da ultima vez.
        Medir com a escalacao real superestima, porque supoe adivinhar
        substituicao.
        """
        if "teamname" not in df.columns:
            print("[jogadores] CSV sem teamname — nao da para usar escalacao anterior")
            return None
        d = df[["gameid", "date", "teamname", "lado", "nota"]].copy()
        d = d.sort_values(["teamname", "date", "gameid"])
        # soma das notas dos 5 daquele time naquele jogo
        soma = d.groupby(["teamname", "gameid", "lado", "date"], sort=False)["nota"].sum()
        soma = soma.reset_index().sort_values(["teamname", "date", "gameid"])
        # a do jogo ANTERIOR do mesmo time
        soma["nota_ant"] = soma.groupby("teamname", sort=False)["nota"].shift(1)
        soma = soma.dropna(subset=["nota_ant"])
        piv = soma.pivot_table(index="gameid", columns="lado", values="nota_ant")
        piv = piv.dropna()
        if "blue" not in piv.columns or "red" not in piv.columns:
            return None
        return {str(k): float(v) for k, v in (piv["blue"] - piv["red"]).items()}

    def dif(self, gameid) -> float:
        """Soma das notas dos 5 do blue menos a dos 5 do red. 0 = sem dado."""
        return self._dif.get(str(gameid), 0.0)


class NotaDeJogadorAprendida(NotaDeJogador):
    """Nota de jogador com os pesos APRENDIDOS por rota, nao media simples.

    ╔══ FONTES ══════════════════════════════════════════════════════════════╗
    ║ A versao anterior fazia media SIMPLES de quatro z-scores — tratando     ║
    ║ participacao em ouro e visao como igualmente importantes, o que nao ha  ║
    ║ razao para ser verdade.                                                 ║
    ║                                                                         ║
    ║ O caminho da literatura, em artigo especifico de LoL (37.400 partidas): ║
    ║ "para cada rota, treinamos um modelo que preve a probabilidade de o     ║
    ║ jogador vencer a partir de suas estatisticas de fim de jogo".           ║
    ║ https://arxiv.org/html/2501.10049  (aberta em 10/09/2026)               ║
    ║                                                                         ║
    ║ AVALIAR POR ROTA: isto e INFERENCIA MINHA, nao citacao.                 ║
    ║ Ate 11/09/2026 havia aqui uma frase entre aspas atribuida ao trabalho   ║
    ║ do SAGE 10.1177/17479541251381652. REBAIXADA no mesmo dia: tentei       ║
    ║ reabrir a pagina e o SAGE, o ResearchGate e o IEEE (documento 11153635) ║
    ║ devolveram 403 / conteudo fechado. Nao consigo conferir a frase, entao  ║
    ║ ela sai das aspas. A divida D2 do RETOMAR.md diz por que: bloco de      ║
    ║ fontes que nao da para conferir e pior que bloco nenhum.                ║
    ║                                                                         ║
    ║ O que sustenta a escolha por rota, e QUE DA para conferir, e o          ║
    ║ PandaSkill acima: "for each role, we train a machine learning model".   ║
    ║                                                                         ║
    ║ SUSPEITA REGISTRADA, tambem minha e tambem nao confirmada: o resumo     ║
    ║ daquele trabalho relata acuracia de 0,8686. Previsao pre-jogo de LoL    ║
    ║ nao chega perto disso — o proprio PandaSkill fica em 0,6498. Numero     ║
    ║ desse tamanho e tipico de quem preve a partida usando estatistica DA    ║
    ║ PROPRIA partida, o que seria pos-fato e nao serviria para nos. Nao      ║
    ║ afirmo que seja o caso; nao li o artigo.                                ║
    ║                                                                         ║
    ║ SEM VAZAMENTO: os pesos sao aprendidos SO com jogos anteriores a 2026,  ║
    ║ e todas as dobras avaliadas sao de 2026. A padronizacao usa media e     ║
    ║ desvio do mesmo recorte anterior.                                        ║
    ║                                                                         ║
    ║ SEM DECAIMENTO, de proposito: testado em 11/09/2026 com meia-vida de    ║
    ║ 180 dias (a que o projeto ja usa) e a nota PIOROU, 7,41 -> 7,31. Bate   ║
    ║ com a ressalva da fonte: "decaimento mais rapido capta mudancas rapido, ║
    ║ mas e mais suscetivel a ruido de amostra pequena".                       ║
    ╚═════════════════════════════════════════════════════════════════════════╝
    """

    ANO_CORTE = 2026
    COLS = ["kills", "deaths", "assists", "teamkills", "dpm", "damageshare",
            "earnedgoldshare", "cspm", "visionscore", "golddiffat15"]

    def __init__(self, csvs):
        base = ["gameid", "date", "participantid", "position", "playername",
                "result", "teamname"]
        quadros = []
        for c in csvs:
            pv = pd.read_csv(c, nrows=1, low_memory=False)
            uso = [x for x in base + self.COLS if x in pv.columns]
            quadros.append(pd.read_csv(c, low_memory=False, usecols=uso))
        df = pd.concat(quadros, ignore_index=True)
        df = df[(df["participantid"] >= 1) & (df["participantid"] <= 10)].copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "playername", "position", "result"])
        df = df.sort_values("date").reset_index(drop=True)
        df["lado"] = np.where(df["participantid"] <= 5, "blue", "red")
        df["ano"] = df["date"].dt.year

        # participacao em kills normaliza por quao sangrento foi o jogo —
        # melhor que KDA cru, que premia jogo cheio de luta.
        if set(["kills", "assists", "teamkills"]).issubset(df.columns):
            tk = pd.to_numeric(df["teamkills"], errors="coerce")
            df["kp"] = ((pd.to_numeric(df["kills"], errors="coerce").fillna(0)
                         + pd.to_numeric(df["assists"], errors="coerce").fillna(0))
                        / tk.replace(0, np.nan)).fillna(0.0)

        feats = [c for c in ("kp", "deaths", "dpm", "damageshare", "earnedgoldshare",
                             "cspm", "visionscore", "golddiffat15") if c in df.columns]
        treino_mask = (df["ano"] < self.ANO_CORTE).to_numpy()
        if int(treino_mask.sum()) < 2000:
            raise SystemExit("poucos jogos antes do corte para aprender os pesos")

        y_all = pd.to_numeric(df["result"], errors="coerce").fillna(0).to_numpy(float)
        X_all = np.zeros((len(df), len(feats)), dtype=float)
        self._w = {}
        for rota, idx in df.groupby("position", sort=False).indices.items():
            tr = [i for i in idx if treino_mask[i]]
            if len(tr) < 300:
                continue
            for j, f in enumerate(feats):
                v = pd.to_numeric(df[f], errors="coerce").fillna(0.0).to_numpy(float)
                m = float(v[tr].mean())
                sd = float(v[tr].std()) or 1.0
                X_all[idx, j] = (v[idx] - m) / sd
            Xtr = np.column_stack([X_all[tr], np.ones(len(tr))])
            w = np.zeros(Xtr.shape[1])
            for _ in range(60):
                pr = 1.0 / (1.0 + np.exp(-np.clip(Xtr @ w, -30, 30)))
                g = Xtr.T @ (y_all[tr] - pr)
                H = -(Xtr.T * (pr * (1 - pr))) @ Xtr - 1e-6 * np.eye(Xtr.shape[1])
                try:
                    passo = np.linalg.solve(H, -g)
                except np.linalg.LinAlgError:
                    break
                w = w + passo
                if np.max(np.abs(passo)) < 1e-9:
                    break
            self._w[rota] = w

        ps = np.zeros(len(df), dtype=float)
        for rota, idx in df.groupby("position", sort=False).indices.items():
            w = self._w.get(rota)
            if w is None:
                continue
            ps[idx] = np.column_stack([X_all[idx], np.ones(len(idx))]) @ w
        df["pscore"] = ps

        df = df.sort_values(["playername", "date"])
        g = df.groupby("playername", sort=False)
        df["nota"] = (g["pscore"].cumsum() - df["pscore"]) / (g.cumcount() + self.BETA)

        agg = df.groupby(["gameid", "lado"], sort=False)["nota"].sum().unstack("lado").dropna()
        self._dif = {str(k): float(v) for k, v in (agg["blue"] - agg["red"]).items()}
        print("[jogadores] pesos aprendidos em {} rotas, {} estatisticas, "
              "so com jogos < {}".format(len(self._w), len(feats), self.ANO_CORTE))
        if os.environ.get("ESCALACAO_ANTERIOR") == "1":
            alt = self._usar_escalacao_anterior(df)
            if alt:
                self._dif = alt
                print("[jogadores] usando a ESCALACAO ANTERIOR de cada time "
                      "({} jogos) — e o que o app sabe antes da partida".format(len(alt)))


class HistoricoPorTime:
    """Historico de cada time, para consulta ESTRITAMENTE ANTERIOR a uma data.

    POR QUE ESTA CLASSE EXISTE, e nao "peguei o df do app" (09/09/2026):
    os colaboradores do app carregam o artefato e os params de HOJE. Colher a
    fiacao viva e reusa-la para pontuar marco seria look-ahead classico.

    FONTES (abertas em 09/09/2026):
      - "point-in-time correctness": o exemplo so pode ver o que existia no
        momento dele; juncoes fora do ponto no tempo "inflam a AUC offline em
        5 a 20%".
        https://www.systemoverflow.com/learn/ml-feature-stores/feature-store-architecture/point-in-time-correctness-and-time-travel
      - regra do backtest: "em cada passo, as decisoes sao tomadas usando
        apenas a informacao disponivel naquele momento".
        https://analystprep.com/study-notes/cfa-level-2/problems-in-backtesting/
    """

    def __init__(self, team_games):
        import numpy as np
        self._np = np
        d = team_games.copy()
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["date", "team"]).sort_values("date")
        self._por_time = {}
        for t, g in d.groupby("team", sort=False):
            g = g.reset_index(drop=True)
            self._por_time[str(t)] = (g, g["date"].to_numpy())

    def antes_de(self, time, quando):
        par = self._por_time.get(str(time))
        if par is None:
            return pd.DataFrame()
        g, datas = par
        # side="left" => ESTRITAMENTE antes. "right" incluiria o jogo do proprio
        # dia, que e exatamente o vazamento que se quer evitar.
        i = int(self._np.searchsorted(
            datas, self._np.datetime64(pd.Timestamp(quando)), side="left"))
        return g.iloc[:i]


def pontuar_janela_prequencial(art_path: Path, ply_path: Path, jogos: pd.DataFrame,
                               ini, fim, player_rows, domestic_by_year, team_meta_infer,
                               historico=None, ss_app=None, cfg_form=None,
                               usar_hybrid=True, usar_platt=True,
                               jogadores=None, w_jog=0.0,
                               fusao_servida=False) -> dict:
    """Como pontuar_janela, mas com a CADENCIA DE PRODUCAO.

    POR QUE ISTO EXISTE (09/09/2026): a dobra congelada treina no corte e preve
    30 dias com o rating parado. PRODUCAO NAO FAZ ISSO — o robo roda o
    update_incremental 3x por dia (.github/workflows/retreino.yml). Medido: o
    mesmo motor nos mesmos 6.446 jogos da logloss 0.6823 congelado e 0.6200
    atualizando (scratchpad/congelar.py). Julgar producao pela dobra congelada
    a condena por uma velhice que ela nao tem.

    Aqui cada jogo e pontuado ANTES de entrar no modelo, e entra logo depois —
    que e exatamente o efeito de atualizar varias vezes ao dia.

    FIDELIDADE: o laco reproduz mlcore/update_incremental.py (linhas 366-428):
    mesma resolucao de liga/tier (`_home`), mesmo reset por promocao e o MESMO
    `model.update` de producao. A matematica nao e reescrita; o que foi copiado
    e a ORDEM e o `_home`, porque vivem dentro de um `main()` e nao dao para
    importar. Isso e divida: precisa de um teste de paridade contra o
    update_incremental de verdade antes de virar a regua oficial.
    """
    from mlcore.tiers import canonical_league, is_international_league, tier_for_league
    from mlcore.update_incremental import _apply_promotion_reset

    art = MLArtifact.load_json(str(art_path))
    p_art = PlayersArtifact.load_json(str(ply_path))
    w_lineup = float(((art.meta or {}).get("players_layer") or {}).get("w_lineup", 0.0) or 0.0)
    meta_times: dict = dict((art.meta or {}).get("team_meta") or {})

    def _home(team: str, liga_do_jogo: str):
        m = meta_times.get(team) or {}
        guardada = str(canonical_league(m.get("league") or "") or "").strip()
        fb = str(canonical_league(liga_do_jogo or "") or "").strip()
        lg = fb if (fb and not is_international_league(fb)) else (guardada or fb or "OTHER")
        return lg, str(tier_for_league(lg))

    janela = jogos[(jogos["date"] >= ini) & (jogos["date"] < fim)].sort_values(["date", "gameid"])
    inter, same = [], []
    # Guardado por gameid para o teste PAREADO entre variantes: comparar medias
    # de amostras diferentes jogaria fora a informacao de que sao OS MESMOS
    # jogos, e alargaria o intervalo sem necessidade.
    por_jogo = []
    para_ajuste = []   # (logito, sinal, y) para ajustar o peso das PROXIMAS dobras
    for r in janela.itertuples(index=False):
        try:
            y = int(r.blue_win)
        except (TypeError, ValueError):
            continue
        blue, red = str(r.blue), str(r.red)
        lg = str(canonical_league(getattr(r, "league", "") or "OTHER") or "OTHER")
        bl, bt = _home(blue, lg)
        rl, rt = _home(red, lg)

        # ---- PONTUA ANTES de o modelo ver o jogo ----
        p0 = float(art.model.p_blue(blue, red, blue_league=bl, red_league=rl,
                                    blue_tier=bt, red_tier=rt))
        # CALIBRADOR PLATT — DEFEITO CORRIGIDO EM 10/09/2026.
        # A regua nascia copiando a matematica da nota oficial, que pontua a
        # probabilidade CRUA. Mas o caminho servido calibra ANTES de tudo
        # (app_core/ml_artifact_pricing_core.py: p_raw -> calibrator -> motor).
        # Sem isto, a regua media um modelo que ninguem serve, e os numeros
        # absolutos estavam todos deslocados.
        # Point-in-time: o calibrador vem do artefato DA DOBRA, ajustado so com
        # dados anteriores ao corte dela.
        p_raw_pre = float(p0)
        if usar_platt:
            try:
                p0 = float(clip_prob(art.calibrator.predict_proba(p0)))
            except Exception:
                pass
        b_lin, r_lin = lineup_for_game(player_rows, str(r.gameid))
        res = compute_delta_and_confidence(
            p_art, blue_lineup=b_lin, red_lineup=r_lin,
            as_of=pd.to_datetime(r.date).date(), match_league=lg)
        d = float(res.get("delta", 0.0) or 0.0)
        cov_tot = float(res.get("coverage_total", 5) or 5.0)
        cov = float(res.get("coverage", 0) or 0.0) / (cov_tot if cov_tot else 5.0)
        fundido = float(_sigmoid(_logit(p0) + w_lineup * (d * cov)))

        # ---- FUSAO POR PRECISAO: o estagio que faltava na regua ----
        #
        # POR QUE ISTO EXISTE (11/09/2026). Ate hoje a regua parava no
        # deslocamento do logito acima, e eu afirmei que "o app nao desloca o
        # logito, ele funde por precisao". ERRADO, conferido lendo o codigo:
        # o app faz AS DUAS coisas, nesta ordem
        # (app_core/ml_pre_engine_core.py, linhas ~565-595):
        #
        #   logit_used = logit(p_RAW) + w_lineup * delta
        #   p_players  = calibrar(sigmoide(logit_used))
        #   p_final    = fundir_por_precisao(p_team=p_map, p_players=p_players)
        #
        # Duas diferencas contra o caminho acima, e as duas importam:
        #   1) o deslocamento entra no logito CRU, e a calibracao vem DEPOIS.
        #      Por isso este ramo recomeca de p_raw_pre.
        #   2) existe uma etapa de fusao que ENCOLHE o deslocamento de volta
        #      na direcao da probabilidade so-de-time, por variancia inversa.
        #
        # Consequencia: todo ganho de jogadores medido SEM esta etapa e um
        # TETO, nao a entrega.
        #
        # PRINCIPIO V: fuse_with_coherence_guard e IMPORTADA de
        # mlcore/fusion_core.py — a mesma funcao que o app chama. Nada aqui
        # reimplementa producao.
        if fusao_servida:
            from mlcore.fusion_core import fuse_with_coherence_guard
            _pp = float(_sigmoid(_logit(p_raw_pre) + w_lineup * (d * cov)))
            if usar_platt:
                try:
                    _pp = float(clip_prob(art.calibrator.predict_proba(_pp)))
                except Exception:
                    pass
            _gp = getattr(art.model, "games_played", {}) or {}
            _n_team = min(float(_gp.get(blue, 0.0) or 0.0),
                          float(_gp.get(red, 0.0) or 0.0))
            _n_play = max(0.0, float(res.get("avg_gp_min", 0.0) or 0.0)
                          * float(cov)
                          * float(res.get("freshness_avg", 1.0) or 1.0))
            try:
                _fus = fuse_with_coherence_guard(
                    p_team=float(p0), p_players=float(_pp),
                    n_team=float(_n_team), n_players=float(_n_play),
                    team_scale=float(FUS_TEAM_SCALE),
                    players_scale=float(FUS_PLAYERS_SCALE),
                    coverage=float(cov), season_phase="auto",
                )
                fundido = float(_fus.get("p_fused", fundido))
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        # ---- camada de jogadores por DESEMPENHO ----
        # Deslocamento no logito, que e a forma que a camada atual ja usa
        # (sigmoid(logit(p) + w * delta)). O peso `w_jog` vem de FORA, ajustado
        # so em dobras ANTERIORES a esta — nunca nesta janela.
        if jogadores is not None and w_jog:
            _dj = jogadores.dif(r.gameid)
            if _dj:
                fundido = float(_sigmoid(_logit(fundido) + float(w_jog) * float(_dj)))

        # ---- season_form_blend: vem ANTES do hybrid (ordem lida do traco do app) ----
        # Config vinda do params_fitted (best_form). ESTE e o estagio sob suspeita
        # de vazamento: os parametros foram escolhidos em 18/07 usando dados que
        # incluem as dobras antigas. O teste e comparar o ganho nas dobras
        # LIMPAS (pos-18/07) contra as CONTAMINADAS.
        if historico is not None and cfg_form:
            from mlcore.fusion_core import season_form_blend
            _ano = pd.Timestamp(r.date).year
            _ha = historico.antes_de(blue, r.date)
            _hb = historico.antes_de(red, r.date)
            # "season" form: so os jogos da MESMA temporada, como o nome diz.
            if not _ha.empty:
                _ha = _ha[_ha["date"].dt.year == _ano]
            if not _hb.empty:
                _hb = _hb[_hb["date"].dt.year == _ano]
            _fm = season_form_blend(
                p_model=float(fundido), df_team_a=_ha, df_team_b=_hb,
                enabled=bool(cfg_form.get("enabled", True)),
                max_weight=float(cfg_form.get("max_weight", 0.75)),
                knee_games=float(cfg_form.get("knee_games", 6.0)),
                beta_prior=float(cfg_form.get("beta_prior", 2.0)),
                signal_power=float(cfg_form.get("signal_power", 1.0)),
                elite_same_league_parity_strength=float(
                    cfg_form.get("elite_same_league_parity_strength", 0.35)),
            )
            _pf = _fm.get("p_blended") if isinstance(_fm, dict) else None
            if _fm.get("applied") and _pf is not None and math.isfinite(float(_pf)):
                fundido = float(_pf)

        # ---- hybrid_blend: o MAIOR movedor da odd servida (ate +-7pp) ----
        # Usa a funcao de PRODUCAO (mlcore.fusion_core.hybrid_momentum_blend) e
        # historicos point-in-time. E o unico dos tres estagios ativos que nao
        # depende do params_fitted.json (de 18/07), entao e o unico que da para
        # medir sem look-ahead nas dobras antigas.
        if historico is not None and usar_hybrid:
            from mlcore.fusion_core import hybrid_momentum_blend
            _ss = ss_app or {}
            _w = float(_ss.get("ml_hybrid_blend_max_weight", 0.70) or 0.70)
            _k = float(_ss.get("ml_hybrid_blend_knee_games", 12.0) or 12.0)
            if bl != rl:   # mesmo amortecimento interregional do app
                _w *= max(0.0, min(1.0, float(_ss.get("ml_interregional_hybrid_max_weight_mult", 0.18) or 0.18)))
                _k *= max(1.0, float(_ss.get("ml_interregional_hybrid_knee_mult", 1.8) or 1.8))
            _hy = hybrid_momentum_blend(
                p_model=float(fundido),
                df_team_a=historico.antes_de(blue, r.date),
                df_team_b=historico.antes_de(red, r.date),
                enabled=True, max_weight=_w, knee_games=_k,
                momentum_games=int(_ss.get("ml_hybrid_momentum_games", 10) or 10),
                beta_prior=float(_ss.get("ml_hybrid_beta", 2.0) or 2.0),
            )
            _pb = _hy.get("p_blended") if isinstance(_hy, dict) else None
            if _hy.get("applied") and _pb is not None and math.isfinite(float(_pb)):
                fundido = float(_pb)

        (inter if bl != rl else same).append((fundido, y))
        por_jogo.append((str(r.gameid), float(fundido), int(y)))
        if jogadores is not None:
            para_ajuste.append((float(_logit(fundido)), float(jogadores.dif(r.gameid)),
                                float(y)))

        # ---- e SO ENTAO o modelo aprende com ele ----
        _apply_promotion_reset(art.model, team=blue,
                               prev_tier=str((meta_times.get(blue) or {}).get("tier") or ""), new_tier=bt)
        _apply_promotion_reset(art.model, team=red,
                               prev_tier=str((meta_times.get(red) or {}).get("tier") or ""), new_tier=rt)
        for t, l, tr in ((blue, bl, bt), (red, rl, rt)):
            ant = meta_times.get(t) or {}
            meta_times[t] = {"league": l,
                             "tier": max([tr, str(ant.get("tier") or tr)], key=lambda x: str(x))}
        art.model.update(blue, red, y, blue_league=bl, red_league=rl,
                         blue_tier=bt, red_tier=rt)

    return {"inter": inter, "same": same, "n_delta": 0, "w_lineup": w_lineup,
            "por_jogo": por_jogo, "para_ajuste": para_ajuste}


def nota_de(inter: list, same: list) -> float:
    """A MESMA mistura 45/55 da nota oficial — trocar isso inventaria outra nota."""
    if not inter or not same:
        return float("nan")
    return (0.45 * _grade_from_logloss(_metrics(inter)["logloss"])
            + 0.55 * _grade_from_logloss(_metrics(same)["logloss"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Nota medida fora da amostra (origem rolante).")
    ap.add_argument("--marca", default="prod", help="Nome desta variante (separa os artefatos).")
    ap.add_argument("--extra", default="", help="Argumentos extras para o train_offline.")
    ap.add_argument("--passo", type=int, default=30, help="Tamanho da janela de teste, em dias.")
    ap.add_argument("--dobras", type=int, default=8, help="Quantas janelas para tras.")
    ap.add_argument("--pasta", default="scratchpad/nota_honesta")
    ap.add_argument("--jogadores-aprendido", action="store_true",
                    help="Pesos APRENDIDOS por rota em vez de media simples.")
    ap.add_argument("--com-jogadores", action="store_true",
                    help="Camada de jogadores por DESEMPENHO. O peso e ajustado so "
                         "em dobras ANTERIORES a cada janela (prequencial).")
    ap.add_argument("--fusao-servida", action="store_true",
                    help="Aplica a FUSAO POR PRECISAO depois do deslocamento da "
                         "camada de jogadores, que e o que o app faz de verdade. "
                         "Sem isto o ganho de jogadores e um TETO, nao a entrega.")
    ap.add_argument("--sem-platt", action="store_true",
                    help="Mede SEM o calibrador Platt (o que a regua fazia por engano "
                         "ate 10/09/2026). So para comparar com as medicoes antigas.")
    ap.add_argument("--com-form", action="store_true",
                    help="Aplica o season_form_blend com a config ajustada (best_form). "
                         "Serve para MEDIR se o vazamento de 18/07 infla o ganho.")
    ap.add_argument("--com-hybrid", action="store_true",
                    help="Aplica o hybrid_blend de producao (o maior movedor da odd) "
                         "com historicos point-in-time. So faz sentido com --cadencia diaria.")
    ap.add_argument("--cadencia", choices=["congelada", "diaria"], default="congelada",
                    help="congelada = modelo parado na dobra inteira (o que a nota antiga "
                         "supunha). diaria = jogo entra no modelo logo apos ser pontuado, "
                         "que e a cadencia real do robo (3x/dia).")
    args = ap.parse_args()

    extra = shlex.split(args.extra)
    pasta = (ROOT / args.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    csvs = [str(c) for c in default_csvs()]

    jogos = pd.concat([load_oracle_elixir_games(c) for c in csvs], ignore_index=True)
    jogos["date"] = pd.to_datetime(jogos["date"], errors="coerce")
    jogos = jogos.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    data_max = jogos["date"].max()

    domestic_by_year = _infer_team_domestic_league_by_year(jogos)
    team_meta = _infer_team_meta_latest(domestic_by_year)
    player_rows = load_match_player_rows(csvs)

    historico = None
    ss_app = None
    cfg_form = None
    jogadores = None
    if args.com_jogadores:
        jogadores = (NotaDeJogadorAprendida(csvs) if args.jogadores_aprendido
                     else NotaDeJogador(csvs))
        print(f"[jogadores] nota por desempenho montada para {len(jogadores._dif)} jogos")
    if args.com_form:
        _pf = json.loads((ROOT / "params_fitted.json").read_text(encoding="utf-8"))
        cfg_form = dict(_pf.get("best_form") or {})
        print(f"[form] config ajustada em 18/07: max_weight={cfg_form.get('max_weight')} "
              f"knee={cfg_form.get('knee_games')} ganho declarado="
              f"{cfg_form.get('improvement_logloss_vs_no_form')}")
    if args.com_hybrid or args.com_form:
        # build_team_games da exatamente as colunas que o hybrid_blend le
        # (win, firstblood/firsttower/firstdragon, dragons_*, barons_*).
        from mlcore.stats_teams import build_team_games, load_team_rows
        from tools.cadeia_servida import estado_do_app
        quadros = [build_team_games(load_team_rows(c)) for c in csvs]
        historico = HistoricoPorTime(pd.concat(quadros, ignore_index=True))
        ss_app = estado_do_app()
        print("[hybrid] historico point-in-time montado; usando as configuracoes do app")

    print(f"dados ate {data_max.date()} | {args.dobras} dobras de {args.passo} dias "
          f"| variante '{args.marca}' {' '.join(extra) if extra else '(producao)'}\n")

    todos_inter, todos_same, linhas = [], [], []
    todos_por_jogo = []
    acumulado = []        # (logito, sinal, y) das dobras JA pontuadas (mais antigas)
    w_jog = 0.0

    def _ajusta_peso(dados):
        """Peso da camada por maxima verossimilhanca, so nas dobras anteriores."""
        import numpy as np
        if len(dados) < 500:
            return 0.0
        z = np.array([d[0] for d in dados]); x = np.array([d[1] for d in dados])
        y = np.array([d[2] for d in dados])
        if x.std() <= 0:
            return 0.0
        # Newton para MAXIMIZAR a verossimilhanca: w <- w - g/h, com h < 0.
        # BUG CORRIGIDO EM 10/09/2026: a primeira versao fazia w <- w + g/h
        # (sinal trocado), entao cada passo andava para o lado errado e dobrava.
        # Resultado: peso -6e14 e nota 0,00 em todas as dobras. O erro so ficou
        # visivel porque a saida ficou absurda — por isso a trava abaixo.
        w = 0.0
        for _ in range(50):
            pr = 1.0 / (1.0 + np.exp(-np.clip(z + w * x, -30, 30)))
            g = float(np.dot(x, y - pr))
            h = float(-np.dot(x * x, pr * (1 - pr)))
            if abs(h) < 1e-12:
                break
            passo = g / h
            w = w - passo
            if abs(passo) < 1e-10:
                break
        # Trava: peso absurdo e sintoma de ajuste que nao convergiu. Devolver 0
        # (camada desligada) e melhor que servir um numero quebrado calado.
        if not math.isfinite(w) or abs(w) > 10.0:
            print(f"           AVISO: ajuste do peso divergiu (w={w:.3g}); "
                  "camada DESLIGADA nesta dobra")
            return 0.0
        return float(w)

    # ORDEM DAS DOBRAS: da mais ANTIGA para a mais recente. Assim o peso de cada
    # janela sai so do que veio antes dela no tempo — nunca do proprio futuro.
    for i in range(args.dobras, 0, -1):
        dias = i * args.passo
        ini = data_max - pd.Timedelta(days=dias)
        fim = ini + pd.Timedelta(days=args.passo)
        art, ply = treinar_dobra(dias, args.marca, extra, csvs, pasta)
        f_pontuar = (pontuar_janela_prequencial if args.cadencia == "diaria"
                     else pontuar_janela)
        if args.cadencia == "diaria":
            res = f_pontuar(art, ply, jogos, ini, fim, player_rows,
                            domestic_by_year, team_meta,
                            historico=historico, ss_app=ss_app,
                            cfg_form=cfg_form, usar_hybrid=bool(args.com_hybrid),
                            usar_platt=not args.sem_platt,
                            jogadores=jogadores, w_jog=w_jog,
                            fusao_servida=bool(args.fusao_servida))
        else:
            res = f_pontuar(art, ply, jogos, ini, fim, player_rows,
                            domestic_by_year, team_meta)
        n = len(res["inter"]) + len(res["same"])
        if n < 50:
            print(f"  [dobra {dias:>3}d] so {n} jogos na janela — ignorada")
            continue
        nt = nota_de(res["inter"], res["same"])
        if jogadores is not None:
            acumulado += list(res.get("para_ajuste") or [])
            w_novo = _ajusta_peso(acumulado)
            print(f"           peso da camada p/ a proxima dobra: {w_novo:+.4f} "
                  f"(de {len(acumulado)} jogos anteriores)", flush=True)
            w_jog = w_novo
        todos_por_jogo += list(res.get("por_jogo") or [])
        todos_inter += res["inter"]
        todos_same += res["same"]
        linhas.append((f"{ini.date()}..{fim.date()}", n, nt))
        print(f"  [dobra {dias:>3}d] {ini.date()} a {fim.date()} | n={n:>5} | nota {nt:.2f}",
              flush=True)

    print(f"\n{'janela testada':<26}{'n':>7}{'nota':>8}")
    for jan, n, nt in linhas:
        print(f"{jan:<26}{n:>7}{nt:>8.2f}")

    geral = nota_de(todos_inter, todos_same)
    n_tot = len(todos_inter) + len(todos_same)
    notas = [nt for _, _, nt in linhas]
    print(f"\nNOTA HONESTA ({args.marca}): {geral:.2f} / 10   "
          f"(n={n_tot}, {len(linhas)} dobras, TODOS fora da amostra)")
    # A nota de uma dobra e indefinida quando a janela nao tem jogo ENTRE
    # REGIOES — a mistura 45/55 nao existe com um dos lados vazio. Acontece de
    # verdade: em janeiro nao ha evento internacional. Antes de 11/09/2026 esse
    # nan escorria pelo min()/max() e o resumo saia "pior nan | melhor nan",
    # escondendo tanto o resumo quanto o motivo.
    # PRINCIPIO IV: ausencia nao vira numero — ela e CONTADA e DITA.
    validas = [x for x in notas if x == x]
    vazias = len(notas) - len(validas)
    if validas:
        # Varios operadores de resumo, como a fonte 5 recomenda: a media esconde
        # dobra ruim, o pior caso nao.
        print(f"  por dobra -> pior {min(validas):.2f} | mediana "
              f"{sorted(validas)[len(validas)//2]:.2f} | melhor {max(validas):.2f}")
    if vazias:
        print(f"  {vazias} dobra(s) sem nota propria: a janela nao teve jogo "
              f"entre regioes, e a mistura 45/55 precisa dos dois lados. "
              f"Os jogos delas CONTAM na nota geral, que soma tudo.")

    saida = pasta / (f"nota_honesta_{args.marca}_{args.cadencia}"
                             f"{'_hybrid' if args.com_hybrid else ''}"
                             f"{'_form' if args.com_form else ''}"
                             f"{'_semplatt' if args.sem_platt else '_platt'}"
                             f"{('_jogA' if args.jogadores_aprendido else '_jog') if args.com_jogadores else ''}"
                             # Sem este sufixo a variante servida sobrescreveria a
                             # base, que foi o erro de 10/09 (comparacao com n
                             # diferente porque um arquivo comeu o outro).
                             f"{'_fus' if args.fusao_servida else ''}.json")
    saida.write_text(json.dumps({
        "marca": args.marca, "extra": extra, "cadencia": args.cadencia, "com_hybrid": bool(args.com_hybrid), "com_form": bool(args.com_form), "nota_honesta": geral, "n": n_tot,
        "dobras": [{"janela": j, "n": n, "nota": nt} for j, n, nt in linhas],
        "inter": _metrics(todos_inter), "same": _metrics(todos_same),
        "por_jogo": todos_por_jogo,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  gravado em {saida.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
