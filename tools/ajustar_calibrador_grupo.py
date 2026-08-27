# -*- coding: utf-8 -*-
"""Produz os coeficientes do calibrador com grupo e os grava em params_fitted.json.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ Este script NÃO decide nada: ele PERSISTE o que tools/gate_calibrador_final ║
║ já escolheu e mediu. As fontes do desenho (grupo como feature, poucos       ║
║ grupos, escolha dentro da calibração, logloss decide, barra em conjunção,   ║
║ validação cruzada repetida) estão no bloco FONTES daquele arquivo.          ║
║                                                                             ║
║ A única decisão própria daqui é a JANELA de ajuste, e ela vem de medição:   ║
║ ajustar em dado RECENTE em vez de todo o histórico foi o que produziu o     ║
║ ganho (o calibrador de hoje é ajustado em temporadas antigas e a distorção  ║
║ a corrigir é da atual). A composição dos jogos muda ao longo do ano —       ║
║ medido: BO1 regular sai de 36,8% para 49,7% do volume entre a janela de     ║
║ calibração e o período seguinte —, por isso a janela é curta e o reajuste   ║
║ precisa ser periódico.                                                      ║
║                                                                             ║
║ SEGURANÇA (ML Test Score, Infra 6 e 7 — canário e rollback): escrever este  ║
║ bloco é o que LIGA a mudança; apagá-lo do params desliga. Sem --escrever,   ║
║ o script só mostra o que faria.                                             ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
    python tools/ajustar_calibrador_grupo.py            # so mostra
    python tools/ajustar_calibrador_grupo.py --escrever # grava em params_fitted.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util as _iu  # noqa: E402

from mlcore.calibration import _fit_logistic, fit_platt_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import cadeia, carregar  # noqa: E402
from mlcore.utils import logit, sigmoid  # noqa: E402

_spec = _iu.spec_from_file_location("_gate", ROOT / "tools" / "gate_calibrador_final.py")
_gate = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_gate)

CHAVE_PARAMS = "postfusion_group_calibration"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--janela", type=int, default=2500,
                    help="quantos jogos mais recentes usar no ajuste")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeticoes", type=int, default=5)
    ap.add_argument("--params", default="params_fitted.json")
    ap.add_argument("--escrever", action="store_true",
                    help="grava o bloco (sem isto, so mostra o que faria)")
    args = ap.parse_args()

    d = carregar()
    todas = d["treino"] + d["val"] + d["teste"]
    todas = [a for a in todas if a.month]
    todas.sort(key=lambda a: a.month)
    janela = todas[-int(args.janela):]
    tabela = d["tabela"]
    print(f"ajuste em {len(janela)} jogos mais recentes "
          f"({janela[0].month} -> {janela[-1].month})")

    # A cadeia ate ANTES do calibrador final, igual a do gate.
    pt = fit_platt_from_raw_probs(
        [a.y for a in todas],
        cadeia(todas, tabela=tabela, usar_ms1=False, usar_platt_time=False,
               usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
    base = cadeia(janela, tabela=tabela, platt_time=pt, usar_ms1=False,
                  usar_ms2=False, usar_platt_fusao=False)

    # Escolha do agrupamento e do L2 por validacao cruzada REPETIDA, dentro da
    # janela — nunca olhando o que vem depois.
    idx = list(range(len(janela)))
    conjuntos = []
    for r in range(int(args.repeticoes)):
        ordem = idx[:]
        random.Random(r).shuffle(ordem)
        conjuntos.append([ordem[i::args.folds] for i in range(args.folds)])

    melhor = (float("inf"), None, None)
    for nome, chave in _gate.AGRUPAMENTOS.items():
        niveis = sorted({chave(a) for a in janela})[1:]
        for l2 in (_gate.L2_CANDIDATOS if niveis else (1.0,)):
            perdas = []
            for dobras in conjuntos:
                for f in dobras:
                    fora = set(f)
                    dentro = [i for i in idx if i not in fora]
                    cal = _gate._ajusta([janela[i] for i in dentro],
                                        [base[i] for i in dentro], chave, niveis, l2)
                    perdas += _gate._perdas([cal(janela[i], base[i]) for i in f],
                                            [janela[i].y for i in f])
            m = sum(perdas) / len(perdas)
            if m < melhor[0]:
                melhor = (m, nome, l2)
            if not niveis:
                break
    _, nome_esc, l2_esc = melhor
    chave = _gate.AGRUPAMENTOS[nome_esc]
    niveis = sorted({chave(a) for a in janela})[1:]
    print(f"escolhido por validacao cruzada: '{nome_esc}' com L2={l2_esc:g} "
          f"({len(niveis) + 1} grupos)")

    def feats(a, p):
        z = logit(p)
        f = [z, 1.0]
        for nv in niveis:
            ind = 1.0 if chave(a) == nv else 0.0
            f += [ind * z, ind]
        return f
    pen = [1e-6, 1e-6] + [l2_esc] * (2 * len(niveis))
    w = _fit_logistic([feats(a, p) for a, p in zip(janela, base)],
                      [float(a.y) for a in janela], l2=pen, max_iter=300)

    # Confere a paridade AQUI tambem: o que o app vai calcular tem que bater
    # com o que acabou de ser ajustado. E o erro que originou tudo isto.
    from app_core.postfusion_calibration_core import _calibrador_com_grupo
    bloco = {"niveis": niveis, "w": [float(x) for x in w]}
    pior = 0.0
    for a, p in list(zip(janela, base))[:500]:
        esperado = sigmoid(sum(wi * fi for wi, fi in zip(w, feats(a, p))))
        obtido = _calibrador_com_grupo(bloco, a.bo, a.phase)(p)
        pior = max(pior, abs(obtido - esperado))
    print(f"paridade ajuste x aplicacao: maior diferenca {pior:.2e} "
          f"{'(ok)' if pior < 1e-9 else '<<< DIVERGIU'}")
    if pior >= 1e-9:
        print("ABORTADO: quem ajusta e quem aplica discordam.")
        return 1

    bloco.update({
        "agrupamento": nome_esc, "l2": l2_esc,
        "ajustado_em": datetime.now().strftime("%Y-%m-%d"),
        "n_ajuste": len(janela),
        "periodo": f"{janela[0].month}..{janela[-1].month}",
        "obs": ("Reajustar periodicamente: a composicao de formato/fase muda ao "
                "longo do ano e o calibrador envelhece com ela."),
    })
    print("\nbloco a gravar:")
    print(json.dumps({k: v for k, v in bloco.items() if k != "w"}, ensure_ascii=False, indent=1))
    print(f" w: {[round(x, 4) for x in bloco['w']]}")

    if not args.escrever:
        print("\n(--escrever nao informado: nada foi gravado)")
        return 0

    destino = ROOT / args.params
    atual = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {}
    atual[CHAVE_PARAMS] = bloco
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, destino)
    print(f"\n[gravado] {args.params} -> {CHAVE_PARAMS}")
    print("para DESFAZER: apague essa chave do arquivo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
