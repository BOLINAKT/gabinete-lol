# -*- coding: utf-8 -*-
"""Nota de jogador por desempenho, rota a rota, para o Radar.

POR QUE ESTA TELA (pedido do dono em 13/09/2026)
O Radar ja mostra QUEM joga cada rota (monta o draft em cima disso), e o
veredito de vencedor dele e o numero do pre — que aplica a camada de
jogadores. So que o Radar mostrava o RESULTADO e escondia a razao: nao dava
para ver de onde vinha a vantagem de escalacao, nem qual rota a produzia.

POR QUE SO AGORA FOI POSSIVEL
As notas sao chaveadas por `playerid`; o Radar tem o NOME. Era o mesmo
desencontro que mantinha a camada inteira inerte em producao (achado em
13/09/2026). Com o indice de apelidos, o nome passa a resolver a chave.

PRINCIPIO V — NAO REIMPLEMENTAR PARA MEDIR
O total e a cobertura saem de `delta_da_escalacao`, a MESMA funcao que o
caminho servido chama. Se este painel somasse por conta propria, ele poderia
mostrar um numero bonito e diferente do que a odd usou — que e o tipo de
divergencia que este projeto ja pagou caro (o Radar discordando do pre,
24/07/2026).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

ROTAS = ("top", "jng", "mid", "bot", "sup")
ROTULOS = {"top": "TOP", "jng": "JNG", "mid": "MID", "bot": "ADC", "sup": "SUP"}


def _nota_de(pac: Mapping[str, Any], jogador: str, rota_curta: str) -> Optional[float]:
    """Nota do jogador nessa rota, ou None quando nao ha.

    PRINCIPIO IV: quem nao tem nota devolve None e a tela mostra um traco.
    Devolver 0,0 faria um desconhecido parecer exatamente mediano.
    """
    from mlcore.players_layer import norm_pos
    from mlcore.players_pscore_core import resolver_chave

    rota = norm_pos(rota_curta)
    if not rota or not str(jogador or "").strip():
        return None
    chave = resolver_chave(pac.get("notas") or {}, pac.get("apelidos") or {},
                           str(jogador), rota)
    if not chave:
        return None
    try:
        return float((pac["notas"][chave] or {}).get("n"))
    except (KeyError, TypeError, ValueError):
        return None


def montar_painel(
    pac: Optional[Mapping[str, Any]],
    *,
    roster_a: Mapping[str, str],
    roster_b: Mapping[str, str],
    minimo_cobertura: int = 5,
) -> Dict[str, Any]:
    """Linhas por rota + o total, do jeito que o pre aplica.

    Devolve `disponivel=False` com um motivo em vez de meia-tabela: painel
    pela metade sobre escalacao incompleta engana mais do que informa.
    """
    if not isinstance(pac, Mapping) or not isinstance(pac.get("notas"), Mapping):
        return {"disponivel": False, "motivo": "sem arquivo de notas de jogador"}
    # Arquivo anterior ao indice de nomes (13/09/2026): o Radar so tem o NOME
    # do jogador e as notas sao por id, entao NADA resolveria e o painel sairia
    # inteiro com tracos. Tabela vazia nao informa — ela so parece defeito.
    if not isinstance(pac.get("apelidos"), Mapping) or not pac.get("apelidos"):
        return {"disponivel": False,
                "motivo": "arquivo de notas ainda sem o indice de nomes"}

    linhas: List[Dict[str, Any]] = []
    for rota in ROTAS:
        ja = str((roster_a or {}).get(rota, "") or "").strip()
        jb = str((roster_b or {}).get(rota, "") or "").strip()
        na = _nota_de(pac, ja, rota)
        nb = _nota_de(pac, jb, rota)
        linhas.append({
            "rota": rota,
            "rotulo": ROTULOS.get(rota, rota.upper()),
            "jogador_a": ja, "nota_a": na,
            "jogador_b": jb, "nota_b": nb,
            "delta": (na - nb) if (na is not None and nb is not None) else None,
        })

    # O total vem da funcao do caminho servido, nunca de uma soma local.
    from mlcore.players_pscore_core import delta_da_escalacao
    from mlcore.players_layer import norm_pos
    delta, cobertura = delta_da_escalacao(
        pac.get("notas") or {},
        blue_lineup={norm_pos(r): str((roster_a or {}).get(r, "") or "") for r in ROTAS},
        red_lineup={norm_pos(r): str((roster_b or {}).get(r, "") or "") for r in ROTAS},
        apelidos=pac.get("apelidos") or {},
    )

    w = 0.0
    try:
        w = float(pac.get("w", 0.0) or 0.0)
    except (TypeError, ValueError):
        w = 0.0
    if not math.isfinite(w):
        w = 0.0

    entra = int(cobertura) >= int(minimo_cobertura) and abs(w) > 1e-12
    return {
        "disponivel": True,
        "linhas": linhas,
        "delta_total": float(delta),
        "cobertura": int(cobertura),
        "w": float(w),
        # O deslocamento no logito e exatamente o que o pre soma. Se a camada
        # nao entra, ele e 0 — e a tela diz por que, em vez de mostrar um
        # numero que ninguem usou.
        "deslocamento": float(w * delta) if entra else 0.0,
        "entra_na_conta": bool(entra),
        "motivo": ("ok" if entra else
                   ("escalacao incompleta ({}/{} com nota)".format(
                       int(cobertura), int(minimo_cobertura))
                    if int(cobertura) < int(minimo_cobertura) else "peso zero")),
    }


def efeito_na_probabilidade(p: Any, deslocamento: Any) -> Optional[float]:
    """A probabilidade SEM a camada, dado o p que ja a inclui.

    Serve para a tela dizer "sem os jogadores seria X" — o tamanho real da
    vantagem de escalacao, em vez de um numero solto no logito, que nao quer
    dizer nada para quem aposta.
    """
    try:
        pf = float(p)
        d = float(deslocamento)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(pf) and math.isfinite(d)) or not (0.0 < pf < 1.0):
        return None
    z = math.log(pf / (1.0 - pf)) - d
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
