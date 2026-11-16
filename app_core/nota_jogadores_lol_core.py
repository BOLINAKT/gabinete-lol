# -*- coding: utf-8 -*-
"""Mistura da NOTA POR JOGADOR na chance do mapa (LoL, 28/10/2026, aprovada por ele).

nota_jogadores_lol.json (robo de retreino, tools/nota_jogadores_lol.py) traz a forca
de cada time = media das notas do ultimo elenco. Entra DEPOIS do blend hibrido --
o mesmo ponto da regua em que foi provada:
    logit = c * ((1-w)*logit(p_modelo) + w*logit(p_jogador))

SO EM JOGO DE LIGA NACIONAL (a regra que ele escolheu): os dois times com a MESMA
liga de origem e o jogo nao entre regioes. Fora disso (Mundial, MSI, EMEA Masters,
promocao), a prova cega deu ganho zero ou negativo e nada muda.
Sem o arquivo ou sem um dos times nele: None, e o app segue como sempre.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

ARQ = Path(__file__).resolve().parents[1] / "nota_jogadores_lol.json"
_CACHE: Dict[str, Any] = {"mtime": None, "dados": None}


def _dados() -> Optional[dict]:
    try:
        mt = ARQ.stat().st_mtime
    except OSError:
        return None
    if _CACHE["mtime"] != mt:
        try:
            _CACHE["dados"] = json.loads(ARQ.read_text(encoding="utf-8"))
            _CACHE["mtime"] = mt
        except (OSError, ValueError):
            return None
    return _CACHE["dados"]


def _lg(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def p_com_jogadores(time_a: str, time_b: str, p_modelo: float, *, entre_regioes: bool = False,
                    dados: Optional[dict] = None) -> Dict[str, Any]:
    """{aplicado, motivo, p_final?, p_jogador?, ...}. Nunca levanta."""
    d = dados if dados is not None else _dados()
    try:
        p_modelo = float(p_modelo)
    except (TypeError, ValueError):
        return {"aplicado": False, "motivo": "sem chance do modelo"}
    if not d or not math.isfinite(p_modelo):
        return {"aplicado": False, "motivo": "sem o arquivo da nota por jogador"}
    times = d.get("times") or {}
    a, b = times.get(str(time_a)), times.get(str(time_b))
    if not a or not b:
        return {"aplicado": False, "motivo": "time sem nota por jogador"}
    la, lb = a.get("liga_de_origem"), b.get("liga_de_origem")
    if entre_regioes or not la or la != lb:
        return {"aplicado": False, "motivo": f"so em jogo de liga nacional ({la or '?'} x {lb or '?'})",
                "liga_a": la, "liga_b": lb}
    par = d.get("parametros") or {}
    w, c = float(par.get("w_jogador", 0.7)), float(par.get("temperatura", 1.3))
    p_j = 1.0 / (1.0 + 10 ** (-(float(a["forca"]) - float(b["forca"])) / 400.0))
    z = c * ((1 - w) * _lg(p_modelo) + w * _lg(p_j))
    return {"aplicado": True, "motivo": f"liga nacional ({la})", "p_jogador": p_j,
            "p_final": 1.0 / (1.0 + math.exp(-z)), "w": w, "c": c,
            "forca_a": float(a["forca"]), "forca_b": float(b["forca"]), "liga_a": la, "liga_b": lb}
