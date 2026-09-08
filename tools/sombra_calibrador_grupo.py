# -*- coding: utf-8 -*-
"""SOMBRA do calibrador com grupo — roda em 100% do tráfego sem servir nada.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║                                                                             ║
║ 1. POR QUE SOMBRA ANTES DE LIGAR:                                           ║
║    o candidato recebe 100% do tráfego de produção e a saída dele NÃO afeta   ║
║    decisão nenhuma; compara-se a distribuição de saída contra a do modelo    ║
║    servido. O que a prática recomenda observar é exatamente o que este       ║
║    script imprime: taxa de concordância, divergência de distribuição, e os   ║
║    casos em que os dois discordam — que são os mais informativos. A ideia é  ║
║    confirmar o comportamento na distribuição VIVA, não só no conjunto de     ║
║    avaliação.                                                                ║
║    https://arize.com/glossary/shadow-deployment/                             ║
║    https://atlan.com/know/shadow-deployment-for-ml-models/                   ║
║                                                                             ║
║ 1b. CORREÇÃO DE UMA FONTE ERRADA (04/09/2026) — importante:                  ║
║    `RETOMAR.md` (seção 3, ponto 1) atribuía a                                ║
║    https://resiliotech.com/blog/model-canary-releases-shadow-traffic-guide   ║
║    a frase "se o candidato prevê sistematicamente diferente, provavelmente   ║
║    é distorção de calibração ou numérica, mesmo que a métrica offline        ║
║    pareça boa". A página foi aberta em 04/09/2026 e NÃO diz isso: o único    ║
║    trecho sobre sombra ali é "Compare the shadow outputs against the         ║
║    production baseline using statistical A/B testing methods".               ║
║    A afirmação forte segue SEM FONTE. Ela não é usada para decidir nada      ║
║    aqui: este script mede e mostra, e quem decide se o modelo ACERTA mais    ║
║    é o gate, com teste cego e intervalo de confiança.                        ║
║                                                                             ║
║ 2. POR QUE ISTO NÃO É REDUNDANTE COM O GATE:                                 ║
║    o gate responde "acerta mais?" (logloss, IC, barra da casa). A sombra     ║
║    responde "muda o que aparece na tela, e quanto?". São perguntas           ║
║    diferentes: um calibrador pode ganhar logloss e ainda assim mexer o       ║
║    número de tantos jogos que o dono precise saber ANTES.                    ║
║                                                                             ║
║ 2b. CORREÇÃO DE UMA AFIRMAÇÃO MINHA (05/09/2026): aqui estava escrito que    ║
║    "a inclinação global é 1,296, e maior que 1 significa AFIAR". Isso        ║
║    descreve a MÉDIA e ela ENGANA. Aberto por grupo, o efeito muda de SINAL:  ║
║    BO1 e BO3 de playoffs são afiados (inclinação 1,4 a 1,8), enquanto BO3 e  ║
║    BO5 de fase regular são ACHATADOS com força (0,50 a 0,60) — e esses       ║
║    somam quase 38% dos jogos. Ou seja: o modelo é subconfiante em BO1 e      ║
║    SUPERCONFIANTE em série longa, e o calibrador conserta cada um para o     ║
║    seu lado. Por isso a tabela POR GRUPO existe, e por isso ela vem antes    ║
║    da leitura agregada.                                                      ║
║    SEM FONTE, e sustentado por MEDIÇÃO NOSSA (corrigido em 06/09/2026): eu   ║
║    citava aqui um artigo do MLflow para "agregado esconde deriva por         ║
║    segmento". A página foi aberta e NÃO diz isso — ela trata de limiares     ║
║    por feature, não por coorte. A afirmação fica sem fonte externa, e não    ║
║    precisa de uma: nesta própria ferramenta o agregado dizia "AFIA" enquanto ║
║    38% dos jogos eram ACHATADOS. A evidência é o nosso próprio número.       ║
║    (A inclinação impressa na tabela é PONTA A PONTA na tela — inclui o       ║
║    microssegmento do time —, por isso não bate com o coeficiente cru do      ║
║    bloco. É o que o dono vê, que é o que esta ferramenta existe para dizer.) ║
║                                                                             ║
║ 3. POR QUE MEDIR TROCA DE FAVORITO SEPARADAMENTE:                            ║
║    para quem aposta, um jogo que cruza os 50% muda a DECISÃO, não só o       ║
║    preço. Diferença média em pontos percentuais esconde isso; a contagem de  ║
║    cruzamentos, não.                                                        ║
║                                                                             ║
║ NÃO LIGA NADA e NÃO GRAVA em params_fitted.json. Só mede e guarda a nota.   ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
    python tools/sombra_calibrador_grupo.py
"""
from __future__ import annotations

import argparse
import importlib.util as _iu
import json
import math
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass


def _raiz() -> Path:
    """Raiz do repositório pelo git — nunca parents[N] (armadilha do CLAUDE.md)."""
    saida = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           cwd=str(Path(__file__).resolve().parent),
                           capture_output=True, text=True, check=True)
    return Path(saida.stdout.strip())


ROOT = _raiz()
sys.path.insert(0, str(ROOT))

from mlcore.calibration import fit_platt_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import cadeia, carregar, variante  # noqa: E402

_spec = _iu.spec_from_file_location("_gate", ROOT / "tools" / "gate_calibrador_final.py")
_gate = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeticoes", type=int, default=5)
    ap.add_argument("--out", default="evidence/sombra_calibrador_grupo.json")
    args = ap.parse_args()

    d = carregar()
    tr, va, te, tab = d["treino"], d["val"], d["teste"], d["tabela"]

    # O que e SERVIDO hoje. CORRIGIDO em 05/09/2026 (divida D8): os defaults de
    # `variante` ligam o microssegmento da fusao e o Platt da fusao, e o APP NAO
    # RODA essas duas — dependem de callbacks que nunca sao injetados no caminho
    # servido. A sombra de 04/09 comparou contra a cadeia errada e por isso
    # exagerou o susto: dizia 7,15pp de diferenca media e 8,43% de troca de
    # favorito; contra a tela de verdade e 6,22pp e 6,53%.
    hoje = variante(tr, te, tabela=tab, usar_ms2=False, usar_platt_fusao=False)

    pt = fit_platt_from_raw_probs(
        [a.y for a in tr],
        cadeia(tr, tabela=tab, usar_ms1=False, usar_platt_time=False,
               usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
    b_va = cadeia(va, tabela=tab, platt_time=pt, usar_ms1=False, usar_ms2=False,
                  usar_platt_fusao=False)
    b_te = cadeia(te, tabela=tab, platt_time=pt, usar_ms1=False, usar_ms2=False,
                  usar_platt_fusao=False)

    # Mesma escolha do gate, feita DENTRO da calibracao (fonte 3 do gate).
    idx = list(range(len(va)))
    conjuntos = []
    for r in range(int(args.repeticoes)):
        ordem = idx[:]
        random.Random(r).shuffle(ordem)
        conjuntos.append([ordem[i::args.folds] for i in range(args.folds)])
    melhor = (float("inf"), None, None)
    for nome, chave in _gate.AGRUPAMENTOS.items():
        niveis = sorted({chave(a) for a in va})[1:]
        for l2 in (_gate.L2_CANDIDATOS if niveis else (1.0,)):
            perdas = []
            for dobras in conjuntos:
                for f in dobras:
                    fora = set(f)
                    dentro = [i for i in idx if i not in fora]
                    cal = _gate._ajusta([va[i] for i in dentro],
                                        [b_va[i] for i in dentro], chave, niveis, l2)
                    perdas += _gate._perdas([cal(va[i], b_va[i]) for i in f],
                                            [va[i].y for i in f])
            m = sum(perdas) / len(perdas)
            if m < melhor[0]:
                melhor = (m, nome, l2)
            if not niveis:
                break
    _, nome_esc, l2_esc = melhor
    chave = _gate.AGRUPAMENTOS[nome_esc]
    niveis = sorted({chave(a) for a in va})[1:]
    cal = _gate._ajusta(va, b_va, chave, niveis, l2_esc)
    novo = [cal(a, p) for a, p in zip(te, b_te)]

    n = len(te)
    print(f"SOMBRA em {n} jogos ({min(a.month for a in te)} -> "
          f"{max(a.month for a in te)}), agrupamento '{nome_esc}', L2={l2_esc:g}")
    print("nada foi servido: o resultado do candidato e descartado (fonte 1)\n")

    dif = [nv - hj for nv, hj in zip(novo, hoje)]
    absd = sorted(abs(x) for x in dif)

    def pct(v):
        return absd[min(int(v * len(absd)), len(absd) - 1)]

    media_hoje = sum(hoje) / n
    media_novo = sum(novo) / n
    extremos_hoje = sum(1 for p in hoje if p < 0.2 or p > 0.8) / n
    extremos_novo = sum(1 for p in novo if p < 0.2 or p > 0.8) / n

    print(f"{'':<26}{'hoje':>10}{'candidato':>12}")
    print(f"{'probabilidade media':<26}{media_hoje:>10.4f}{media_novo:>12.4f}")
    print(f"{'jogos fora de 20-80%':<26}{extremos_hoje:>10.1%}{extremos_novo:>12.1%}")
    print()
    print(f"diferenca media (candidato - hoje): {sum(dif) / n:+.4f}")
    print(f"diferenca absoluta media          : {sum(absd) / n:.4f}"
          f"  ({100 * sum(absd) / n:.2f} pontos percentuais)")
    print(f"mediana / p90 / p99 / maior       : "
          f"{100 * pct(.5):.2f}pp / {100 * pct(.9):.2f}pp / "
          f"{100 * pct(.99):.2f}pp / {100 * absd[-1]:.2f}pp")
    print()
    for limite in (0.01, 0.02, 0.05, 0.10):
        q = sum(1 for x in absd if x > limite)
        print(f"  jogos que mexem mais de {100 * limite:>4.0f}pp: {q:>5}  ({q / n:.1%})")

    trocam = sum(1 for hj, nv in zip(hoje, novo) if (hj - .5) * (nv - .5) < 0)
    print(f"\nTROCAM DE FAVORITO (cruzam os 50%): {trocam} de {n} ({trocam / n:.2%}) (fonte 3)")

    print("\npor faixa do numero de hoje:")
    print(f"{'faixa':<12}{'n':>6}{'hoje diz':>10}{'candidato':>11}{'muda':>9}")
    faixas = []
    for lo_, hi_ in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        par = [(hj, nv) for hj, nv in zip(hoje, novo) if lo_ <= hj < hi_]
        if len(par) < 50:
            continue
        mh = sum(h for h, _ in par) / len(par)
        mn = sum(v for _, v in par) / len(par)
        print(f"{f'{lo_:.0%}-{hi_:.0%}':<12}{len(par):>6}{mh:>10.1%}{mn:>11.1%}"
              f"{100 * (mn - mh):>+8.2f}pp")
        faixas.append({"faixa": f"{lo_:.0%}-{hi_:.0%}", "n": len(par),
                       "hoje": round(mh, 4), "candidato": round(mn, 4)})

    # POR GRUPO — acrescentado em 05/09/2026 porque a media MENTIU. O resumo
    # agregado dizia "AFIA as probabilidades", e isso e verdade so para o grupo
    # mais numeroso: em quase 38% dos jogos o calibrador faz o CONTRARIO,
    # puxando forte para o centro. Media que esconde o sinal de metade dos
    # casos e pior que numero nenhum, e "agregado esconde deriva por segmento"
    # e a razao pela qual monitoramento se faz POR FATIA (fonte 4).
    # https://mlflow.org/articles/why-monitor-model-drift-production/
    print("\nPOR GRUPO — a media esconde isto:")
    print(f"{'grupo':<14}{'n':>7}{'% jogos':>10}{'inclinacao':>12}{'efeito':>10}")
    por_grupo = {}
    for a, hj, nv in zip(te, hoje, novo):
        por_grupo.setdefault(f"{a.bo}|{a.phase}", []).append((hj, nv))
    grupos = []
    for g, par in sorted(por_grupo.items(), key=lambda kv: -len(kv[1])):
        if len(par) < 30:
            continue
        # inclinacao empirica: espalhamento em logito depois / antes
        def _lg(x):
            x = min(max(x, 1e-9), 1 - 1e-9)
            return math.log(x / (1 - x))
        a_ = [_lg(h) for h, _ in par]
        b_ = [_lg(n) for _, n in par]
        ma, mb = sum(a_) / len(a_), sum(b_) / len(b_)
        va = sum((x - ma) ** 2 for x in a_)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a_, b_))
        incl = cov / va if va > 0 else float("nan")
        ef = "AFIA" if incl > 1.02 else ("achata" if incl < 0.98 else "neutro")
        print(f"{g:<14}{len(par):>7}{100*len(par)/n:>9.1f}%{incl:>12.3f}{ef:>10}")
        grupos.append({"grupo": g, "n": len(par), "inclinacao": round(incl, 4), "efeito": ef})

    # Veredito: a sombra NAO aprova nem reprova sozinha. Ela diz o tamanho do
    # susto, para a decisao de ligar ser tomada sabendo.
    afia = extremos_novo > extremos_hoje
    print("\nleitura:")
    print(f"  NA MEDIA o candidato {'AFIA' if afia else 'SUAVIZA'} "
          f"(jogos fora de 20-80% vao de {extremos_hoje:.1%} para {extremos_novo:.1%}),")
    print("  mas olhe a tabela por grupo antes de acreditar nisso: o efeito muda")
    print("  de SINAL entre formatos. Media agregada aqui engana.")
    print("  a sombra nao aprova nem reprova: quem decide se ACERTA mais e o")
    print("  gate. Isto aqui diz quanto a TELA muda, para ninguem ser pego de")
    print("  surpresa depois de ligar.")

    destino = ROOT / args.out
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "repo": "gabinete-lol",
        "n_jogos": n,
        "periodo": f"{min(a.month for a in te)}..{max(a.month for a in te)}",
        "escolha": {"agrupamento": nome_esc, "l2": l2_esc},
        "media_hoje": round(media_hoje, 4), "media_candidato": round(media_novo, 4),
        "dif_media": round(sum(dif) / n, 5),
        "dif_abs_media_pp": round(100 * sum(absd) / n, 3),
        "p50_pp": round(100 * pct(.5), 3), "p90_pp": round(100 * pct(.9), 3),
        "p99_pp": round(100 * pct(.99), 3), "maior_pp": round(100 * absd[-1], 3),
        "trocam_favorito": trocam, "trocam_favorito_frac": round(trocam / n, 5),
        "fora_20_80_hoje": round(extremos_hoje, 4),
        "fora_20_80_candidato": round(extremos_novo, 4),
        "faixas": faixas,
        "por_grupo": grupos,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[salvo] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
