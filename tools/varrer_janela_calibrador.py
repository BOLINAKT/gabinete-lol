# -*- coding: utf-8 -*-
"""Escolhe a JANELA de ajuste do calibrador com grupo, por medição.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║                                                                             ║
║ 1. POR QUE ESTE ARQUIVO EXISTE:                                             ║
║    a janela de `tools/ajustar_calibrador_grupo.py` era `--janela 2500`, um  ║
║    número CRAVADO SEM MEDIR (registrado como tal em RETOMAR.md, seção 3,    ║
║    ponto 2). Este script mede qual deve ser.                                ║
║                                                                             ║
║ 1b. O QUE A FONTE DE JANELA ADAPTATIVA REALMENTE DIZ (conferido 04/09/2026):║
║    Davis SE, Greevy RA Jr, Lasko TA, Walsh CG, Matheny ME, "Detection of    ║
║    calibration drift in clinical prediction models to inform model          ║
║    updating", J. Biomed. Inform. 112:103611 (2020),                         ║
║    doi:10.1016/j.jbi.2020.103611 — https://pubmed.ncbi.nlm.nih.gov/33157313/║
║    Ele constrói curvas de calibração dinâmicas e DETECTA miscalibração      ║
║    crescente com JANELAS DESLIZANTES ADAPTATIVAS.                            ║
║    ATENÇÃO À EXTRAPOLAÇÃO: a janela adaptativa dele é de DETECÇÃO (quando   ║
║    avisar que derivou), não de AJUSTE (quantos jogos usar para ajustar o    ║
║    calibrador). Usar isso como base para escolher a janela de ajuste é      ║
║    analogia, não citação. O apoio direto para "não cravar o tamanho" está   ║
║    na fonte 5.                                                              ║
║                                                                             ║
║ 2. POR QUE A ESCOLHA É FEITA DENTRO DA CALIBRAÇÃO, E O TESTE CEGO NÃO É     ║
║    TOCADO AQUI:                                                             ║
║    o tamanho da janela é um HIPERPARÂMETRO como o L2 e o agrupamento.       ║
║    Escolhê-lo pelo desempenho no teste é o viés de seleção de Cawley &      ║
║    Talbot (JMLR 2010), o mesmo erro que a FONTE 3 de                        ║
║    `tools/gate_calibrador_final.py` registra ter sido cometido uma vez      ║
║    neste projeto. Este script vê `val` e nunca `teste`.                     ║
║                                                                             ║
║ 3. POR QUE VALIDAÇÃO PARA A FRENTE, E NÃO VALIDAÇÃO CRUZADA EMBARALHADA:    ║
║    a premissa da frente é DERIVA — a composição dos jogos muda ao longo do  ║
║    ano (medido: BO1 de fase regular sai de 36,8% para 49,7% do volume).     ║
║    Validação cruzada embaralhada mistura futuro no ajuste e mede a janela   ║
║    pela coisa errada: janela maior venceria só por ter mais dado. A         ║
║    pergunta real é "ajustar nos últimos N prevê melhor o que vem DEPOIS?",  ║
║    e só corte temporal responde isso.                                       ║
║                                                                             ║
║ 4. POR QUE VÁRIOS CORTES E NÃO UM:                                          ║
║    um corte só mede um pedaço de calendário e a escolha oscila com ele —    ║
║    é o mesmo motivo pelo qual o gate repete a validação cruzada (a FONTE 7  ║
║    dele: promediar mais modelos estabiliza a escolha).                      ║
║                                                                             ║
║ 5. O MÉTODO JÁ EXISTE E TEM NOME (pesquisado 04/09/2026, DEPOIS de eu o     ║
║    ter construído sozinho — a ordem certa era o contrário):                 ║
║    é validação de ORIGEM ROLANTE (rolling-origin / walk-forward), e na      ║
║    literatura de fluxo contínuo, avaliação PREQUENCIAL. Janela que expande  ║
║    serve a processo estacionário; janela deslizante fixa serve a processo   ║
║    que deriva, onde dado velho ATRAPALHA. O compromisso é conhecido: depois ║
║    de uma deriva, a janela maior se adapta mais devagar mas termina         ║
║    melhor — janela menor reage rápido e paga depois.                        ║
║    https://metricgate.com/docs/time-series-walk-forward-cv/                 ║
║    https://book.moa.cms.waikato.ac.nz/chapter_6.html/                       ║
║                                                                             ║
║ 6. O ERRO QUE ESTE ARQUIVO COMETEU, E QUE A LITERATURA JÁ PREVIA:           ║
║    a primeira versão avaliou blocos de 200 a 400 jogos logo após cada       ║
║    corte — horizonte de dias — e concluiu "janela curta ganha". O teste     ║
║    cego, que serve CINCO MESES à frente, disse o contrário: janela 900 deu  ║
║    ganho +0,01256 contra +0,02368 da calibração inteira, e o Z de           ║
║    Spiegelhalter virou de −2,94 para +6,88 (superconfiante).                ║
║    Isto é exatamente o que se sabe: janelas curtas ajudam o horizonte       ║
║    PRÓXIMO e não conferem a mesma vantagem em horizonte longo.              ║
║    Zanotti M., "On the retraining frequency of global models in retail      ║
║    demand forecasting", arXiv:2505.00356 —                                  ║
║    https://arxiv.org/pdf/2505.00356                                         ║
║    (domínio diferente — varejo, não e-sport. É analogia com apoio, não      ║
║    prova para o nosso caso; o que prova aqui é o teste cego.)               ║
║    REGRA PRÁTICA QUE FICA: o horizonte de avaliação tem que casar com o     ║
║    horizonte de serviço. E não dá para consertar alongando o horizonte      ║
║    aqui: a calibração inteira tem 3 meses e o serviço é de 5.               ║
║                                                                             ║
║ 7. FRAQUEZA CONHECIDA E NÃO CORRIGIDA DESTE SCRIPT:                         ║
║    ele escolhe janela E L2 no MESMO laço de validação, sem aninhamento. O   ║
║    remédio recomendado por Cawley & Talbot (fonte 2) é validação cruzada    ║
║    ANINHADA, com laço interno para hiperparâmetro e externo para medir.     ║
║    Como o resultado desta ferramenta foi REPROVADO pelo teste cego, a       ║
║    fraqueza não contaminou nada em produção — mas quem for reusar isto      ║
║    precisa saber.                                                           ║
║                                                                             ║
║ NÃO DECIDE LIGAR NADA. Só responde "qual janela", e grava a nota com        ║
║ carimbo em evidence/. Quem grava o bloco é ajustar_calibrador_grupo.py, e   ║
║ quem mede contra o teste cego é gate_calibrador_final.py.                   ║
║                                                                             ║
║ VEREDITO DESTE ARQUIVO (04/09/2026): a resposta que ele deu foi TESTADA E   ║
║ REPROVADA. Mantém-se no repositório como registro da medição e do erro de   ║
║ horizonte, não como recomendação. A janela em uso continua a de sempre.     ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
    python tools/varrer_janela_calibrador.py
    python tools/varrer_janela_calibrador.py --cortes 6 --bloco 300
"""
from __future__ import annotations

import argparse
import importlib.util as _iu
import json
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
    """A raiz do repositório vem do git, nunca de parents[N].

    Armadilha registrada no CLAUDE.md: as ferramentas moram em `tools/` no LoL
    e na raiz no Dota, e `parents[N]` fazia a régua medir a Área de Trabalho.
    """
    saida = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           cwd=str(Path(__file__).resolve().parent),
                           capture_output=True, text=True, check=True)
    return Path(saida.stdout.strip())


ROOT = _raiz()
sys.path.insert(0, str(ROOT))

from mlcore.calibration import fit_platt_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import cadeia, carregar  # noqa: E402

_spec = _iu.spec_from_file_location("_gate", ROOT / "tools" / "gate_calibrador_final.py")
_gate = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_gate)

JANELAS = (750, 1000, 1500, 2000, 2500, 3000, 4000, 0)  # 0 = todo o histórico


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cortes", type=int, default=5,
                    help="quantos cortes temporais avaliar (fonte 4)")
    ap.add_argument("--bloco", type=int, default=300,
                    help="quantos jogos depois do corte entram na avaliacao")
    ap.add_argument("--agrupamento", default="formato + fase",
                    help="o que o gate ja escolheu por validacao cruzada")
    ap.add_argument("--janelas", default="",
                    help="grade de janelas, separada por virgula (0 = todo o "
                         "historico). Vazio usa a grade padrao.")
    ap.add_argument("--out", default="evidence/varredura_janela_calibrador.json")
    args = ap.parse_args()

    d = carregar()
    tr, va, tab = d["treino"], d["val"], d["tabela"]
    va = [a for a in va if a.month]
    va.sort(key=lambda a: a.month)

    # Mesma base do gate: sem microssegmento, com o Platt do time ajustado no
    # treino. O que se escolhe aqui e SO a janela do calibrador final.
    pt = fit_platt_from_raw_probs(
        [a.y for a in tr],
        cadeia(tr, tabela=tab, usar_ms1=False, usar_platt_time=False,
               usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
    base = cadeia(va, tabela=tab, platt_time=pt, usar_ms1=False, usar_ms2=False,
                  usar_platt_fusao=False)

    chave = _gate.AGRUPAMENTOS[args.agrupamento]
    n = len(va)
    print(f"calibracao: {n} jogos ({va[0].month} -> {va[-1].month})")
    print(f"teste cego: NAO TOCADO aqui (fonte 2)")
    print(f"agrupamento fixo: '{args.agrupamento}'\n")

    # Cortes espalhados no fim da calibracao. Cada corte c ajusta em va[:c] (os
    # ultimos N deles) e mede em va[c:c+bloco] — sempre para a FRENTE.
    cortes = []
    for k in range(int(args.cortes)):
        c = n - int(args.bloco) * (k + 1)
        if c >= 400:
            cortes.append(c)
    cortes.reverse()
    if not cortes:
        print("dado insuficiente para varrer.")
        return 1
    print(f"{len(cortes)} cortes temporais, avaliando {args.bloco} jogos apos cada um\n")

    grade = (tuple(int(x) for x in args.janelas.split(",") if x.strip())
             if args.janelas.strip() else JANELAS)

    linhas = []
    print(f"{'janela':>8}{'L2':>7}{'logloss adiante':>18}{'cortes':>9}")
    melhor = (float("inf"), None, None)
    for jan in grade:
        for l2 in _gate.L2_CANDIDATOS:
            perdas, usados = [], 0
            for c in cortes:
                ini = 0 if jan == 0 else max(0, c - jan)
                dentro = list(range(ini, c))
                if len(dentro) < 200:
                    continue
                fora = list(range(c, min(n, c + int(args.bloco))))
                if not fora:
                    continue
                amostras = [va[i] for i in dentro]
                niveis = sorted({chave(a) for a in amostras})[1:]
                cal = _gate._ajusta(amostras, [base[i] for i in dentro],
                                    chave, niveis, l2)
                perdas += _gate._perdas([cal(va[i], base[i]) for i in fora],
                                        [va[i].y for i in fora])
                usados += 1
            if not perdas:
                continue
            m = sum(perdas) / len(perdas)
            rot = "todos" if jan == 0 else str(jan)
            linhas.append({"janela": jan, "l2": l2, "logloss": m, "cortes": usados})
            print(f"{rot:>8}{l2:>7g}{m:>18.5f}{usados:>9}")
            if m < melhor[0]:
                melhor = (m, jan, l2)

    perda_esc, jan_esc, l2_esc = melhor
    rot = "todos" if jan_esc == 0 else str(jan_esc)
    print(f"\nMELHOR: janela={rot}  L2={l2_esc:g}  logloss adiante={perda_esc:.5f}")

    ref = [x for x in linhas if x["janela"] == 2500 and x["l2"] == 1.0]
    if ref:
        delta = ref[0]["logloss"] - perda_esc
        print(f"contra o 2500 cravado (L2=1): {delta:+.5f} de logloss")
        print("  lembrete: a barra da casa (>0,002, p<0,05, IC acima de zero) vale")
        print("  para o ganho FINAL contra producao, medido no teste cego pelo")
        print("  gate — nao para esta escolha interna.")

    destino = ROOT / args.out
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "repo": "gabinete-lol",
        "n_calibracao": n,
        "periodo": f"{va[0].month}..{va[-1].month}",
        "cortes": cortes,
        "bloco": int(args.bloco),
        "agrupamento": args.agrupamento,
        "escolhido": {"janela": jan_esc, "l2": l2_esc, "logloss_adiante": perda_esc},
        "tabela": linhas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[salvo] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
