# -*- coding: utf-8 -*-
"""O resumo de cada regua "modelo contra a Pinnacle", gravado para o app ler.

POR QUE (25/09/2026). As tres reguas (vencedor, total de kills, handicap de
kills) so existiam no terminal: para saber se o modelo ganha da casa era
preciso me pedir para roda-las. Com o resumo em evidence/, o robo as roda
toda semana e o app mostra o placar, com a amostra e o aviso de "ainda nao
da para concluir" quando for o caso.

A CONTA E A MESMA EM TODAS: logloss do modelo e da casa (sem margem) nas
mesmas apostas, contra o que aconteceu; incerteza agrupada por PARTIDA (as
linhas do mesmo mapa acertam ou erram juntas).
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "evidence"


def resumo(casos: List[Mapping[str, Any]], chave_modelo: str, *,
           minimo: int) -> Optional[Dict[str, Any]]:
    """{partidas, logloss_modelo, logloss_casa, diferenca, margem_erro,
    bateu, conclusivo, nota_modelo, nota_casa} -- ou None sem casos.

    Usa so os casos em que `chave_modelo` existe. `nota_*` na escala do
    projeto: 5,0 = cara ou coroa, 9,5 = elite (_grade_from_logloss).
    """
    usados = [c for c in casos if c.get(chave_modelo) is not None]
    if not usados:
        return None

    def _perda(p, y):
        q = min(max(float(p), 1e-9), 1 - 1e-9)
        return -(y * math.log(q) + (1 - y) * math.log(1 - q))

    por: Dict[Any, List[float]] = {}
    lm = lc = 0.0
    for c in usados:
        a, b = _perda(c[chave_modelo], c["y"]), _perda(c["p_casa"], c["y"])
        lm += a
        lc += b
        por.setdefault(c["partida"], []).append(a - b)
    n = len(usados)
    lm, lc = lm / n, lc / n
    medias = [sum(v) / len(v) for v in por.values()]
    erro = None
    if len(medias) > 1:
        mu = sum(medias) / len(medias)
        dp = math.sqrt(sum((x - mu) ** 2 for x in medias) / (len(medias) - 1))
        erro = 1.96 * dp / math.sqrt(len(medias))

    def _nota(ll):
        return max(0.0, min(10.0, 5.0 + (0.6931 - ll) / (0.6931 - 0.55) * 4.5))
    return {
        "apostas": n, "partidas": len(medias), "minimo": int(minimo),
        "logloss_modelo": lm, "logloss_casa": lc, "diferenca": lm - lc,
        "margem_erro": erro,
        "bateu": int(sum(1 for x in medias if x < 0)),
        "nota_modelo": _nota(lm), "nota_casa": _nota(lc),
        "conclusivo": bool(len(medias) >= minimo and erro is not None
                           and abs(lm - lc) > erro),
    }


def gravar(nome: str, dados: Mapping[str, Any]) -> Path:
    PASTA.mkdir(parents=True, exist_ok=True)
    alvo = PASTA / ("regua_pinnacle_%s.json" % nome)
    alvo.write_text(json.dumps({"gerado_em": datetime.now().isoformat(timespec="seconds"),
                                **dados}, ensure_ascii=False, indent=1), encoding="utf-8")
    return alvo


def ler_todas(raiz: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    fora: Dict[str, Dict[str, Any]] = {}
    for p in sorted(((raiz or ROOT) / "evidence").glob("regua_pinnacle_*.json")):
        try:
            fora[p.stem.replace("regua_pinnacle_", "")] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return fora
