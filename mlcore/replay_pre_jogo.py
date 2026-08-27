# -*- coding: utf-8 -*-
"""REPLAY DO PRÉ-JOGO — uma fonte só para medir o número que a tela serve.

Motivo (26/08/2026): existem TRÊS implementações da probabilidade pré-jogo,
com contagem de etapas diferente, e a nota oficial mede a mais simples. A
causa raiz é que o caminho servido não é chamável fora da interface
(`run_ml_pre_engine_layers` recebe `st`, formatadores e callbacks), então quem
precisa medir REIMPLEMENTA — e cada um para num ponto diferente.

Este módulo existe para a medição parar de reescrever o caminho. Não altera
nada em produção: é leitura.

DUAS DECISÕES DE DESENHO QUE IMPORTAM:

1) O CACHE GUARDA O DADO CRU, não as probabilidades.
   Montar as amostras leva ~20 min (lineup cache sobre 28 mil jogos); montar
   as probabilidades a partir delas leva segundos. Guardando o cru, dá para
   testar QUALQUER variante do caminho sem repagar a carga.

2) CADA VARIANTE REAJUSTA OS PRÓPRIOS CALIBRADORES.
   Sem isso a ablação seria fraudada a favor do status quo: remover uma etapa
   e manter um Platt que foi ajustado COM ela presente compara a etapa contra
   uma versão sabotada de si mesma.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifact import MLArtifact
from .calibration import fit_platt_from_raw_probs
from .calibration_diagnostics import _apply_microseg_calibration, _read_json_file_safe
from .fit_ml_params import _build_lineup_cache, _fuse_probs_by_precision, _make_samples
from .players_layer import PlayersArtifact, load_match_player_rows
from .utils import clip_prob, logit, sigmoid

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "evidence" / "_cache_pre_jogo.json"


@dataclass
class Amostra:
    """O dado CRU de um jogo — tudo que o caminho servido consome."""
    gameid: str
    league: str
    split: str
    side: str
    bo: str
    phase: str
    month: str
    y: int
    p_team: float
    p_players: float
    n_team: float
    n_players: float
    delta_eff: float


def _ms(p: float, a: Amostra, tabela: dict) -> float:
    """Microssegmento. Os argumentos sao NOMEADOS na funcao original — passar a
    amostra posicionalmente levanta TypeError, que um `except` largo engoliria,
    fazendo a etapa nao fazer nada CALADA. Aconteceu comigo em 26/08: eu teria
    medido "o microssegmento nao ajuda" sem ele nunca ter sido aplicado."""
    if not tabela:
        return float(p)
    return float(_apply_microseg_calibration(
        float(p), league=a.league, split=a.split, side=a.side,
        bo=a.bo, phase=a.phase, table=tabela))


def cadeia(amostras: list[Amostra], *, tabela: dict, platt_time=None,
           platt_fusao=None, usar_ms1=True, usar_platt_time=True,
           usar_fusao=True, usar_ms2=True, usar_platt_fusao=True) -> list[float]:
    """Roda o caminho servido com as etapas que forem pedidas."""
    saida = []
    for a in amostras:
        p = float(a.p_team)
        if usar_ms1:
            p = _ms(p, a, tabela)
        if usar_platt_time and platt_time is not None:
            p = float(clip_prob(platt_time.predict_proba(p)))
        if usar_fusao:
            p = float(clip_prob(_fuse_probs_by_precision(
                p_team=p, p_players=float(a.p_players), n_team=float(a.n_team),
                n_players=float(a.n_players), team_scale=1.0, players_scale=1.0)))
        if usar_ms2:
            p = _ms(p, a, tabela)
        if usar_platt_fusao and platt_fusao is not None:
            p = float(clip_prob(platt_fusao.predict_proba(p)))
        saida.append(p)
    return saida


def variante(treino: list[Amostra], alvo: list[Amostra], *, tabela: dict,
             treino_final: list[Amostra] | None = None,
             familia_final: str = "platt", **chaves) -> list[float]:
    """Uma variante do caminho, com os calibradores REAJUSTADOS para ela.

    E o que torna a ablacao justa: cada versao do pipeline e avaliada com os
    calibradores que ELA teria, nao com os da versao completa."""
    y_tr = [a.y for a in treino]
    pt = None
    if chaves.get("usar_platt_time", True):
        base = cadeia(treino, tabela=tabela, usar_ms1=chaves.get("usar_ms1", True),
                      usar_platt_time=False, usar_fusao=False, usar_ms2=False,
                      usar_platt_fusao=False)
        pt = fit_platt_from_raw_probs(y_tr, base)
    pf = None
    if chaves.get("usar_platt_fusao", True):
        # O calibrador FINAL pode ser ajustado noutro conjunto: a distorcao que
        # ele corrige e da temporada, e o treino sao temporadas ANTIGAS. Ajustar
        # no val (recente) testa se o problema e defasagem em vez de metodo.
        fonte = treino_final if treino_final else treino
        base = cadeia(fonte, tabela=tabela, platt_time=pt,
                      usar_ms1=chaves.get("usar_ms1", True),
                      usar_platt_time=chaves.get("usar_platt_time", True),
                      usar_fusao=chaves.get("usar_fusao", True),
                      usar_ms2=chaves.get("usar_ms2", True),
                      usar_platt_fusao=False)
        y_fin = [a.y for a in (treino_final if treino_final else treino)]
        if familia_final == "beta":
            from .calibration import fit_beta_from_raw_probs
            pf = fit_beta_from_raw_probs(y_fin, base)
        else:
            pf = fit_platt_from_raw_probs(y_fin, base)
    return cadeia(alvo, tabela=tabela, platt_time=pt, platt_fusao=pf, **chaves)


def p_regua(amostras: list[Amostra], w_lineup: float) -> list[float]:
    """O que a nota oficial mede: sigmoid(logit(p_elo) + w_lineup * delta)."""
    return [float(sigmoid(logit(float(a.p_team)) + w_lineup * float(a.delta_eff)))
            for a in amostras]


def carregar(*, artifact: str = "ml_artifact.json",
             players_artifact: str = "players_artifact.json",
             csv_train: str = "CSV_HISTORICO", csv_current: str = "CSV_DIARIO",
             params: str = "params_fitted.json", val_cutoff: str = "2026-03-31",
             usar_cache: bool = True) -> dict:
    """{'treino','val','teste': [Amostra], 'tabela': {...}, 'w_lineup': float}"""
    if usar_cache and CACHE.exists():
        try:
            b = json.loads(CACHE.read_text(encoding="utf-8"))
            return {"treino": [Amostra(**d) for d in b["treino"]],
                    "val": [Amostra(**d) for d in b["val"]],
                    "teste": [Amostra(**d) for d in b["teste"]],
                    "tabela": b["tabela"], "w_lineup": b["w_lineup"]}
        except (OSError, ValueError, TypeError, KeyError):
            pass

    import pandas as pd

    from .io_oracle import load_oracle_elixir_games
    from .ml_eval import build_split

    caminhos = []
    for pasta in (csv_train, csv_current):
        base = ROOT / pasta
        if base.is_dir():
            caminhos.extend(str(x) for x in sorted(base.glob("*.csv")))
    quadros = []
    for c in caminhos:
        try:
            quadros.append(load_oracle_elixir_games(c, keep_playoffs=None))
        except (OSError, ValueError, KeyError):
            continue
    jogos = pd.concat(quadros, ignore_index=True).drop_duplicates("gameid")

    art = MLArtifact.load_json(str(ROOT / artifact))
    p_art = PlayersArtifact.load_json(str(ROOT / players_artifact))
    w_lineup = float((((art.meta or {}).get("players_layer") or {}).get("w_lineup") or 0.85))
    pr = load_match_player_rows(caminhos, keep_playoffs=None,
                                gameids=set(jogos["gameid"].astype(str)))
    brutas = _make_samples(art=art, p_art=p_art, games=jogos,
                           lineup_cache=_build_lineup_cache(pr), w_lineup=w_lineup)
    split = build_split(brutas, val_cutoff=val_cutoff)
    tabela = (_read_json_file_safe(ROOT / params).get("microseg_calibration") or {}).get("table") or {}

    def _conv(itens):
        fora = []
        for s in itens:
            fora.append(Amostra(
                gameid=str(getattr(s, "gameid", "") or ""),
                league=str(getattr(s, "league", "") or ""),
                split=str(getattr(s, "split", "") or ""),
                side=str(getattr(s, "side", "") or ""),
                bo=str(getattr(s, "bo_bucket", "") or ""),
                phase=str(getattr(s, "phase", "") or ""),
                month=str(getattr(s, "month", "") or ""),
                y=int(s.y), p_team=float(s.p_team), p_players=float(s.p_players),
                n_team=float(s.n_team), n_players=float(s.n_players),
                delta_eff=float(getattr(s, "delta_players_eff", 0.0) or 0.0)))
        return fora

    saida = {"treino": _conv(split.train.samples), "val": _conv(split.val.samples),
             "teste": _conv(split.test.samples), "tabela": tabela, "w_lineup": w_lineup}
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(
            {"treino": [asdict(a) for a in saida["treino"]],
             "val": [asdict(a) for a in saida["val"]],
             "teste": [asdict(a) for a in saida["teste"]],
             "tabela": tabela, "w_lineup": w_lineup}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass
    return saida
