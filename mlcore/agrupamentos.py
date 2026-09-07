# -*- coding: utf-8 -*-
"""Como o calibrador com grupo monta a CHAVE do grupo — fonte única.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║                                                                             ║
║ POR QUE ESTE ARQUIVO EXISTE (dívida D10, 06/09/2026):                       ║
║   `app_core/postfusion_calibration_core._calibrador_com_grupo` montava a    ║
║   chave FIXA como `f"{bo}|{phase}"`. Mas o gate oferece quatro              ║
║   agrupamentos e a validação cruzada escolhe entre eles — ou seja, só UM    ║
║   dos quatro era representável no app.                                      ║
║   Apareceu ao reajustar contra o modelo de 06/09: a VC escolheu             ║
║   "formato BO", a paridade acusou 2,8e-01 e o ajustador ABORTOU sem gravar. ║
║   O guarda funcionou — mas o reajuste ficou bloqueado, com o bloco em       ║
║   produção ajustado sobre um modelo já velho.                               ║
║                                                                             ║
║ 1. O ARTEFATO TEM QUE SE DESCREVER, e o serviço não pode assumir:           ║
║    a prática é o artefato do modelo carregar a própria assinatura/esquema   ║
║    junto dos pesos — assim "o código de serviço não precisa cravar          ║
║    suposições sobre o que o modelo espera". É o que passa a acontecer aqui: ║
║    o bloco em `params_fitted.json` já grava `agrupamento`, e agora o        ║
║    aplicador LÊ esse campo em vez de adivinhar.                             ║
║    https://mlflow.org/docs/latest/ml/model/signatures/                      ║
║                                                                             ║
║ 2. UMA DEFINIÇÃO SÓ, USADA POR QUEM AJUSTA E POR QUEM SERVE:                ║
║    quando a transformação é reimplementada de um lado, ela "começa idêntica ║
║    e deriva" — é a origem clássica da divergência treino/serviço. Por isso  ║
║    o gate/ajustador e o app passam a importar as chaves DAQUI, e não cada   ║
║    um manter a sua. Este projeto pagou por isso três vezes nesta semana     ║
║    (D8, D9, D10).                                                           ║
║    https://feast.dev/blog/what-is-a-feature-store/                          ║
║                                                                             ║
║ CUIDADO AO MEXER: `bo` e `phase` são STRING (ver `Amostra` em               ║
║ mlcore/replay_pre_jogo.py). Comparar com int aqui faria a chave nunca       ║
║ casar, o calibrador cair no global calado, e ninguém notar — que é          ║
║ exatamente o modo de falha da D10.                                          ║
╚═════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

from typing import Any, Callable, Dict

# O agrupamento assumido para bloco ANTIGO, gravado antes de 06/09/2026, que
# nao tem o campo `agrupamento`. Era o unico que o aplicador sabia montar,
# entao e o unico que pode estar em producao sem o campo.
PADRAO_LEGADO = "formato + fase"


def _norm(v: Any) -> str:
    return "" if v is None else str(v)


# Cada entrada recebe (bo, phase) — os dois como vem do caminho servido — e
# devolve a chave do grupo. NAO mudar o texto das chaves: ele e gravado dentro
# do bloco em params_fitted.json e lido de volta.
AGRUPAMENTOS: Dict[str, Callable[[Any, Any], str]] = {
    "nenhum (so global)": lambda bo, phase: "*",
    "formato BO": lambda bo, phase: _norm(bo),
    "fase": lambda bo, phase: _norm(phase),
    "formato + fase": lambda bo, phase: f"{_norm(bo)}|{_norm(phase)}",
}


def chave(nome: str, bo: Any, phase: Any) -> str:
    """A chave do grupo para (bo, phase), segundo o agrupamento `nome`.

    Agrupamento desconhecido levanta — melhor falhar alto do que servir o
    calibrador global calado achando que aplicou o grupo."""
    try:
        f = AGRUPAMENTOS[str(nome)]
    except KeyError:
        raise KeyError(
            f"agrupamento desconhecido: {nome!r}. "
            f"Conhecidos: {sorted(AGRUPAMENTOS)}") from None
    return f(bo, phase)


def chave_de_amostra(nome: str, amostra: Any) -> str:
    """Mesma chave, a partir de uma `Amostra` do replay.

    Existe para quem AJUSTA usar exatamente a funcao de quem SERVE (fonte 2)."""
    return chave(nome, getattr(amostra, "bo", None), getattr(amostra, "phase", None))


def nome_do_bloco(coef: Any) -> str:
    """Le o agrupamento declarado no bloco; bloco velho cai no legado."""
    if isinstance(coef, dict):
        n = coef.get("agrupamento")
        if n:
            return str(n)
    return PADRAO_LEGADO
