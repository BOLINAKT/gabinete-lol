# -*- coding: utf-8 -*-
"""Le as odds que o robo coletou da Pinnacle.

O APP NAO VAI A REDE. Quem coleta e o robo (tools/coletar_odds.py, no GitHub
Actions, de 3 em 3 horas); aqui so se le o arquivo que ele gravou. Cada visita
do app viraria uma ida a casa de apostas -- e o risco de bloqueio de IP cai
sobre ELE, que perderia o acesso ao site onde aposta.

A IDADE VEM SEMPRE JUNTO, e isto nao e enfeite. Odd e um preco vivo: a de tres
horas atras pode ja nao existir. Mostrar vantagem calculada sobre preco velho
seria mandar ele apostar num numero que nao esta mais na tela da casa -- e o
sintoma apareceria como "isso ai nao bate", que nao aponta para a causa.
Mesma licao da agenda coletada.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

NOME_DO_ARQUIVO = "odds_pinnacle.json"

# Acima disto o preco ja nao serve para decidir. O robo roda de 3 em 3 horas,
# entao passar de 4 significa que alguma corrida falhou.
HORAS_ATE_ENVELHECER = 4.0


def _idade_em_horas(carimbo: Any) -> float | None:
    """Quantas horas tem a leitura, ou None quando nao da para saber."""
    txt = str(carimbo or "").strip()
    if not txt:
        return None
    try:
        quando = datetime.fromisoformat(txt)
    except (TypeError, ValueError):
        return None
    agora = datetime.now(quando.tzinfo) if quando.tzinfo else datetime.now()
    return (agora - quando).total_seconds() / 3600.0


def carregar_odds_coletadas(raiz: Path, *, nome: str = NOME_DO_ARQUIVO) -> Dict[str, Any]:
    """As odds + a idade delas, ou o MOTIVO de nao haver.

    PRINCIPIO IV: ausencia nao vira lista vazia calada. "Nao ha aposta com
    vantagem" e "nao consegui ler as odds" sao coisas MUITO diferentes para
    quem vai apostar, e na tela vazia as duas ficam identicas.
    """
    alvo = Path(raiz) / str(nome)
    vazio = {"jogos": [], "linhas": [], "idade_horas": None, "lido_em": ""}
    if not alvo.exists():
        return {**vazio, "motivo": "o robo ainda nao coletou (arquivo ausente)"}
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {**vazio, "motivo": "arquivo ilegivel ({})".format(type(e).__name__)}
    if not isinstance(dados, dict):
        return {**vazio, "motivo": "arquivo com formato inesperado"}

    jogos = dados.get("jogos")
    linhas = dados.get("linhas")
    if not isinstance(jogos, list) or not isinstance(linhas, list):
        return {**vazio, "motivo": "arquivo sem a lista de jogos ou de linhas"}

    jogos_ok: List[Dict[str, Any]] = [j for j in jogos if isinstance(j, dict)]
    linhas_ok: List[Dict[str, Any]] = [l for l in linhas if isinstance(l, dict)]

    idade = _idade_em_horas(dados.get("lido_em"))
    motivo = ""
    if not linhas_ok:
        motivo = "a leitura nao trouxe linha nenhuma"
    return {
        "jogos": jogos_ok,
        "linhas": linhas_ok,
        "idade_horas": idade,
        "lido_em": str(dados.get("lido_em") or ""),
        "velha": bool(idade is not None and idade > HORAS_ATE_ENVELHECER),
        "motivo": motivo,
    }


def times_da_coleta(odds: Dict[str, Any]) -> List[str]:
    """Os nomes de time como a CASA os escreve, sem repetir.

    Sao esses nomes que precisam ser casados com o CSV -- e e por aqui que a
    tela sabe quais ainda faltam ensinar.
    """
    vistos: List[str] = []
    for j in (odds.get("jogos") or []):
        if not isinstance(j, dict):
            continue
        for k in ("casa", "fora"):
            n = str(j.get(k) or "").strip()
            if n and n not in vistos:
                vistos.append(n)
    return vistos
