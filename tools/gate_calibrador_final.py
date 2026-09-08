# -*- coding: utf-8 -*-
"""GATE do calibrador final do pré-jogo — escolha honesta, teste tocado UMA vez.

O número servido é subconfiante: quando diz 69%, acontece ~76%. A causa medida
não é o método, é DEFASAGEM — o calibrador final é ajustado em temporadas
antigas e a distorção a corrigir é da atual.

Este gate escolhe COMO consertar sem trapacear na escolha.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║                                                                             ║
║ 1. POR QUE O CALIBRADOR RECEBE O GRUPO COMO FEATURE, em vez de um           ║
║    calibrador separado por grupo:                                           ║
║    pesquisa sobre calibração condicional — "usar representações baseadas    ║
║    em características em vez de calibradores separados por grupo, para      ║
║    agrupar a força estatística entre os grupos". Elimina o corte arbitrário ║
║    de "mínimo N por grupo": grupo pequeno encolhe sozinho para o global.    ║
║                                                                             ║
║ 2. POR QUE POUCOS GRUPOS:                                                   ║
║    sample complexity de multicalibração — impor calibração por grupo custa  ║
║    erro^-3 de dado contra erro^-2 da calibração simples, e o mecanismo      ║
║    estima médias em células que ficam pequenas. Medido aqui: com 79 grupos  ║
║    (BO x liga) o ganho SOME e o IC cruza zero.                              ║
║                                                                             ║
║ 3. POR QUE A ESCOLHA DE L2 E DE AGRUPAMENTO É FEITA DENTRO DO CONJUNTO DE   ║
║    CALIBRAÇÃO, e o teste é tocado uma vez só:                               ║
║    Cawley & Talbot (JMLR 2010), "On Over-fitting in Model Selection and     ║
║    Subsequent Selection Bias in Performance Evaluation" — usar o mesmo      ║
║    conjunto para escolher hiperparâmetro e medir desempenho gera viés       ║
║    otimista e leva a escolher modelos complexos demais.                     ║
║    ISTO CORRIGE UM ERRO MEU: na primeira rodada eu comparei os valores de   ║
║    L2 e as estruturas de agrupamento pelo desempenho NO TESTE.              ║
║                                                                             ║
║ 4. POR QUE NÃO USO A REGRA DE UM ERRO-PADRÃO:                               ║
║    a evidência é mista — ela ajuda em seleção esparsa de variáveis, mas em  ║
║    estimação/predição "frequentemente tem desempenho pior". O nosso caso é  ║
║    predição.                                                                ║
║                                                                             ║
║ 8. POR QUE EXISTE `--janela`, E POR QUE ELA CORTA TAMBÉM A ESCOLHA:         ║
║    a premissa desta frente é DEFASAGEM: o calibrador de hoje é ajustado em  ║
║    temporada velha e a distorção a corrigir é da atual. Servir com os N     ║
║    jogos mais recentes exige MEDIR com os N mais recentes — medir na        ║
║    calibração inteira e servir numa janela é divergência treino/serviço,    ║
║    que já apareceu duas vezes neste projeto (`scope_meta`).                 ║
║    O tamanho de N NÃO é escolhido aqui: ele vem de                          ║
║    `tools/varrer_janela_calibrador.py`, que o mede por validação de origem  ║
║    rolante DENTRO da calibração, sem tocar no teste cego (a fonte 3 vale    ║
║    para a janela como vale para o L2).                                     ║
║                                                                             ║
║    RESULTADO DE 04/09/2026 — NEGATIVO, e é por isso que o default é 0:      ║
║    aquela varredura recomendou 900 com L2=3. Levado ao teste cego UMA vez,  ║
║    o 900 perdeu para a calibração inteira: ganho +0,01256 [+0,00460,        ║
║    +0,02006] contra +0,02368 [+0,01847, +0,02866], e o Z de Spiegelhalter   ║
║    virou de −2,94 para +6,88 — trocou subconfiança por superconfiança.      ║
║    Causa: a varredura avaliava horizonte de dias e o serviço é de meses.    ║
║    Detalhe e fontes na FONTE 6 daquele arquivo.                             ║
║    **A janela fica em 0 (calibração inteira). `--janela` existe para que a  ║
║    medição seja repetível, não porque esteja em uso.**                      ║
║    E NÃO varrer janela contra o teste cego para "achar uma melhor": isso é  ║
║    exatamente o viés da fonte 3.                                            ║
║                                                                             ║
║ 5. POR QUE A LOGLOSS DECIDE E O ECE SÓ INFORMA:                             ║
║    recalibração monotônica preserva a resolução, então a diferença de       ║
║    logloss entre candidatos É a diferença de calibração — medida por regra  ║
║    de pontuação própria, sem binning e sem viés de estimação. ECE binado é  ║
║    estimador enviesado e sensível ao número de caixas.                      ║
║                                                                             ║
║ 7. POR QUE A VALIDAÇÃO CRUZADA É REPETIDA:                                  ║
║    a curva de VC saiu PLANA (diferenças na 5ª casa entre valores de L2), e  ║
║    escolher o mínimo de curva plana é escolher ruído — o que se via na      ║
║    replicação: os cortes que escolheram L2 baixo generalizaram pior.        ║
║    Literatura de estabilidade: "modelos com baixo erro de VC que são        ║
║    ESTÁVEIS generalizam melhor que os instáveis", e "aumentar K melhora a   ║
║    estabilidade por promediar mais modelos".                                ║
║                                                                             ║
║ 9. POR QUE A BASE DE COMPARAÇÃO MUDOU EM 05/09/2026 (dívida D8):            ║
║    até aqui o "hoje" era `variante(tr, te, tabela=tab)` com os defaults, e  ║
║    os defaults ligam o microssegmento da fusão e o Platt da fusão. O APP    ║
║    NÃO RODA essas duas etapas. Era medir contra base mais fraca que a       ║
║    realidade — e base fraca infla ganho. A prática em teste A/B é comparar  ║
║    contra o melhor método do sistema em produção, não contra uma base       ║
║    conveniente; base fraca "atrapalha entender" o efeito real.              ║
║    https://arxiv.org/html/2409.12116v1                                      ║
║    Medido: base velha 0,58577 contra produção 0,58109 (+0,00469,            ║
║    IC [+0,00339, +0,00587]). O ganho do calibrador cai de +0,02368 para     ║
║    +0,01899 — e continua passando na barra da casa.                         ║
║                                                                             ║
║ 10. O NOME DISSO é DIVERGÊNCIA TREINO/SERVIÇO (training-serving skew): o    ║
║    pipeline de avaliação calcula de um jeito e o serviço de outro.          ║
║    O que as fontes DIZEM (conferido abrindo as páginas em 06/09/2026):      ║
║      - a definição: "o descasamento entre os dados ou features usados no    ║
║        treino e os vistos no momento de servir".                            ║
║        https://www.giskard.ai/glossary/training-serving-skew                ║
║      - a REGRA DE OURO: "garanta que treino e produção se imitem o mais     ║
║        perto possível"; e "use o MESMO esquema para validar os dados de     ║
║        treino e os de serviço".                                             ║
║        https://developers.google.com/machine-learning/crash-course/production-ml-systems/monitoring ║
║                                                                             ║
║    O QUE É INFERÊNCIA MINHA, e estava escrito aqui como se fosse das        ║
║    fontes (corrigido em 06/09/2026): que **o teste cego não consegue        ║
║    revelar isso**, porque o conjunto de teste é construído pelo mesmo       ║
║    pipeline de avaliação e herda a divergência. NENHUMA das duas páginas    ║
║    diz isso. Continua valendo como raciocínio, e foi o que aconteceu na     ║
║    prática — o erro só apareceu lendo o caminho servido, não medindo —,     ║
║    mas é conclusão minha, sustentada pelo caso, não por autoridade.         ║
║                                                                             ║
║    Isto é o item MONITORAMENTO 3 da régua das 28 ("treino e serviço não     ║
║    divergem"), VERMELHO nos dois repositórios desde 26/08. Terceira         ║
║    ocorrência na semana (D8, D9, D10). A régua estava certa.                ║
║    Isto é o item MONITORAMENTO 3 da régua das 28 ("treino e serviço não     ║
║    divergem"), que já estava VERMELHO nos dois repositórios desde 26/08     ║
║    por causa do `scope_meta`. Esta é a terceira ocorrência. A régua estava  ║
║    certa e ninguém tinha ido atrás.                                         ║
║                                                                             ║
║ 6. POR QUE HÁ BOOTSTRAP PAREADO E A BARRA É CONJUNÇÃO:                      ║
║    critério da casa, já usado em tools/run_phase8_first_markets_gate.py:    ║
║    accept = (ganho > 0.002) E (p < 0.05) E (ci_lo > 0).                     ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso: python tools/gate_calibrador_final.py
"""
from __future__ import annotations

import argparse
import json
import math
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

from mlcore.calibration import _fit_logistic, fit_platt_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import cadeia, carregar, variante  # noqa: E402
from mlcore.agrupamentos import AGRUPAMENTOS as _AGRUPAMENTOS_COMPARTILHADOS  # noqa: E402
from mlcore.agrupamentos import chave_de_amostra as _chave_de_amostra  # noqa: E402
from mlcore.utils import logit, sigmoid  # noqa: E402

EPS = 1e-12

# Candidatos. Poucos de proposito (fonte 2), e a escolha entre eles acontece
# DENTRO do conjunto de calibracao (fonte 3).
# As chaves vem de mlcore/agrupamentos.py — FONTE UNICA, a mesma que o app
# usa para servir (divida D10). Manter uma copia aqui foi o que permitiu o
# aplicador so saber "formato + fase" sem ninguem perceber.
AGRUPAMENTOS = {
    _nome: (lambda a, _n=_nome: _chave_de_amostra(_n, a))
    for _nome in _AGRUPAMENTOS_COMPARTILHADOS
}
L2_CANDIDATOS = (0.03, 0.1, 0.3, 1.0, 3.0, 10.0)


def _perdas(ps, ys):
    return [-(math.log(min(max(p, EPS), 1 - EPS)) if y == 1
              else math.log(1 - min(max(p, EPS), 1 - EPS))) for p, y in zip(ps, ys)]


def _ll(ps, ys):
    return sum(_perdas(ps, ys)) / max(1, len(ys))


def _ece(ps, ys, bins=10):
    cx = {}
    for p, y in zip(ps, ys):
        cx.setdefault(min(bins - 1, int(p * bins)), []).append((p, y))
    n = len(ys)
    return sum((len(v) / n) * abs(sum(q for q, _ in v) / len(v)
                                  - sum(w for _, w in v) / len(v)) for v in cx.values())


def _z_spiegelhalter(ps, ys):
    num = den = 0.0
    for p, y in zip(ps, ys):
        p = min(max(p, 1e-9), 1 - 1e-9)
        num += (y - p) * (1 - 2 * p)
        den += ((1 - 2 * p) ** 2) * p * (1 - p)
    z = num / math.sqrt(den) if den > 0 else float("nan")
    return z, math.erfc(abs(z) / math.sqrt(2.0))


def _ic(a, b, n_boot=2000, semente=17):
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    r = random.Random(semente)
    v = sorted(sum(d[r.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    media = sum(d) / n
    return media, v[int(0.025 * n_boot)], v[int(0.975 * n_boot)]


def _ajusta(amostras, ps, chave, niveis, l2_grupo):
    """Um calibrador so, com o grupo como FEATURE (fonte 1).

    Termos globais quase sem penalidade; desvios por grupo penalizados por
    l2_grupo — e por isso grupo com pouco dado encolhe para o global sozinho,
    sem eu escolher um corte de tamanho minimo."""
    def feats(a, p):
        z = logit(p)
        f = [z, 1.0]
        for nv in niveis:
            ind = 1.0 if chave(a) == nv else 0.0
            f += [ind * z, ind]
        return f
    X = [feats(a, p) for a, p in zip(amostras, ps)]
    pen = [1e-6, 1e-6] + [l2_grupo] * (2 * len(niveis))
    w = _fit_logistic(X, [float(a.y) for a in amostras], l2=pen, max_iter=300)
    return lambda a, p: sigmoid(sum(wi * fi for wi, fi in zip(w, feats(a, p))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeticoes", type=int, default=5,
                    help="repeticoes da validacao cruzada (reduz a variancia da escolha)")
    ap.add_argument("--janela", type=int, default=0,
                    help="usar so os N jogos mais RECENTES da calibracao "
                         "(0 = todos, o comportamento de sempre). Ver fonte 8.")
    ap.add_argument("--out", default="evidence/gate_calibrador_final.json")
    args = ap.parse_args()

    d = carregar()
    tr, va, te, tab = d["treino"], d["val"], d["teste"], d["tabela"]
    ys_te = [a.y for a in te]

    # BASE DE COMPARACAO — corrigida em 05/09/2026 (divida D8).
    # `variante(...)` com os defaults liga TODAS as etapas, inclusive o
    # microssegmento da fusao e o Platt da fusao. O APP NAO RODA ESSAS DUAS:
    # elas dependem de callbacks que nunca sao injetados no caminho servido
    # (o contrato MlPreEngineInput nem tem os campos). Comparar contra elas e
    # comparar contra uma base PIOR que a realidade — a armadilha "base fraca
    # da ACCEPT falso" do CLAUDE.md, cometida por este proprio arquivo.
    # Medido: a base antiga da 0,58577 e a de producao 0,58109 (+0,00469,
    # IC [+0,00339, +0,00587]). Quem decide agora e a de producao.
    hoje_com_pos = variante(tr, te, tabela=tab)
    hoje = variante(tr, te, tabela=tab, usar_ms2=False, usar_platt_fusao=False)

    # Base comum: sem microssegmento (medido: atrapalha) e com o Platt do time
    # ajustado no treino (medido: ajuda). O que este gate escolhe e SO o
    # calibrador FINAL.
    pt = fit_platt_from_raw_probs(
        [a.y for a in tr],
        cadeia(tr, tabela=tab, usar_ms1=False, usar_platt_time=False,
               usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
    b_va = cadeia(va, tabela=tab, platt_time=pt, usar_ms1=False, usar_ms2=False,
                  usar_platt_fusao=False)
    b_te = cadeia(te, tabela=tab, platt_time=pt, usar_ms1=False, usar_ms2=False,
                  usar_platt_fusao=False)

    # JANELA (fonte 8): o calibrador servido e ajustado nos jogos mais recentes,
    # entao a calibracao aqui e cortada do mesmo jeito — na ESCOLHA e no ajuste
    # final. Medir com toda a calibracao e servir com os ultimos N seria medir
    # uma coisa e servir outra, que e a divergencia treino/servico que este
    # projeto ja pegou duas vezes.
    if int(args.janela) > 0:
        ordem = sorted(range(len(va)), key=lambda i: (va[i].month or ""))
        ordem = ordem[-int(args.janela):]
        va = [va[i] for i in ordem]
        b_va = [b_va[i] for i in ordem]
        print(f"janela: ultimos {len(va)} jogos da calibracao "
              f"({va[0].month} -> {va[-1].month})")

    print(f"calibracao: {len(va)} jogos | teste cego: {len(te)} jogos")
    print(f"escolha por validacao cruzada de {args.folds} dobras DENTRO da "
          f"calibracao — o teste e tocado uma vez so (fonte 3)\n")

    # ---- escolha interna, sem tocar no teste -------------------------------
    # VALIDACAO CRUZADA REPETIDA. A curva de VC saiu PLANA (diferencas na 5a
    # casa decimal entre valores de L2), e escolher o minimo de curva plana e
    # escolher ruido. Repetir com semeaduras diferentes reduz a variancia da
    # estimativa — "aumentar K melhora a estabilidade por promediar mais
    # modelos" (fonte 7). Sem isso, a escolha de L2 oscilava entre 0.1 e 3
    # conforme o corte de tempo, e os cortes que escolheram 0.1 generalizaram
    # pior.
    idx = list(range(len(va)))
    conjuntos = []
    for r in range(int(args.repeticoes)):
        ordem = idx[:]
        random.Random(r).shuffle(ordem)
        conjuntos.append([ordem[i::args.folds] for i in range(args.folds)])

    print(f"{'agrupamento':<22}{'L2':>7}{'logloss VC':>12}")
    melhor = (float("inf"), None, None)
    tabela_vc = []
    for nome, chave in AGRUPAMENTOS.items():
        niveis = sorted({chave(a) for a in va})[1:]
        for l2 in (L2_CANDIDATOS if niveis else (1.0,)):
            perdas_vc = []
            for dobras in conjuntos:
              for f in dobras:
                fora = set(f)
                dentro = [i for i in idx if i not in fora]
                am_tr = [va[i] for i in dentro]
                p_tr = [b_va[i] for i in dentro]
                cal = _ajusta(am_tr, p_tr, chave, niveis, l2)
                perdas_vc += _perdas([cal(va[i], b_va[i]) for i in f],
                                     [va[i].y for i in f])
            m = sum(perdas_vc) / len(perdas_vc)
            tabela_vc.append({"agrupamento": nome, "l2": l2, "logloss_vc": round(m, 5)})
            print(f"{nome:<22}{l2:>7g}{m:>12.5f}")
            if m < melhor[0]:
                melhor = (m, nome, l2)
            if not niveis:
                break
    _, nome_esc, l2_esc = melhor
    print(f"\nESCOLHIDO pela validacao cruzada: '{nome_esc}' com L2={l2_esc:g}")

    # ---- teste cego, tocado UMA vez ---------------------------------------
    chave = AGRUPAMENTOS[nome_esc]
    niveis = sorted({chave(a) for a in va})[1:]
    cal = _ajusta(va, b_va, chave, niveis, l2_esc)
    novo = [cal(a, p) for a, p in zip(te, b_te)]

    g, lo, hi = _ic(_perdas(hoje, ys_te), _perdas(novo, ys_te))
    z_h, p_h = _z_spiegelhalter(hoje, ys_te)
    z_n, p_n = _z_spiegelhalter(novo, ys_te)
    z_a, p_a = _z_spiegelhalter(hoje_com_pos, ys_te)
    print(f"\n{'':<26}{'logloss':>10}{'ECE':>8}{'Z':>9}{'p':>9}")
    print(f"{'hoje (o app roda ISTO)':<26}{_ll(hoje, ys_te):>10.5f}"
          f"{_ece(hoje, ys_te):>8.3f}{z_h:>9.2f}{p_h:>9.4f}")
    print(f"{'novo':<26}{_ll(novo, ys_te):>10.5f}{_ece(novo, ys_te):>8.3f}"
          f"{z_n:>9.2f}{p_n:>9.4f}")
    print(f"{'(base velha, NAO servida)':<26}{_ll(hoje_com_pos, ys_te):>10.5f}"
          f"{_ece(hoje_com_pos, ys_te):>8.3f}{z_a:>9.2f}{p_a:>9.4f}")
    print(f"\nganho {g:+.5f}   IC 95% [{lo:+.5f}, {hi:+.5f}]")

    # A titulo de contraste, o numero que este gate reportava ate 05/09 — para
    # quem comparar com evidencias antigas nao achar que houve regressao.
    g0, lo0, hi0 = _ic(_perdas(hoje_com_pos, ys_te), _perdas(novo, ys_te))
    print(f"(contra a base velha, so para conferir historico: {g0:+.5f} "
          f"[{lo0:+.5f}, {hi0:+.5f}] — NAO decide)")

    passa = bool(g > 0.002 and lo > 0)
    print(f"barra da casa (ganho>0.002 E ci_lo>0): {'PASSA' if passa else 'NAO passa'} (fonte 6)")

    print("\ncurva de confiabilidade no teste cego:")
    print(f"{'faixa':<12}{'n':>6}{'diz':>9}{'acontece':>11}{'antes dizia':>13}{'antes acontecia':>17}")
    for lo_, hi_ in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        s = [(p, y) for p, y in zip(novo, ys_te) if lo_ <= p < hi_]
        a_ = [(p, y) for p, y in zip(hoje, ys_te) if lo_ <= p < hi_]
        if len(s) < 50 or len(a_) < 50:
            continue
        print(f"{f'{lo_:.0%}-{hi_:.0%}':<12}{len(s):>6}"
              f"{sum(p for p, _ in s) / len(s):>9.1%}{sum(y for _, y in s) / len(s):>11.1%}"
              f"{sum(p for p, _ in a_) / len(a_):>13.1%}{sum(y for _, y in a_) / len(a_):>17.1%}")

    destino = ROOT / str(args.out)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "escolha": {"agrupamento": nome_esc, "l2": l2_esc,
                    "janela": int(args.janela), "n_calibracao": len(va)},
        "validacao_cruzada": tabela_vc,
        "base": ("producao: sem microssegmento da fusao e sem Platt da fusao, "
                 "porque o app nao roda esses dois (divida D8)"),
        "logloss_base_velha": round(_ll(hoje_com_pos, ys_te), 5),
        "ganho_contra_base_velha": round(g0, 5),
        "teste": {"logloss_hoje": round(_ll(hoje, ys_te), 5),
                  "logloss_novo": round(_ll(novo, ys_te), 5),
                  "ganho": round(g, 5), "ic_lo": round(lo, 5), "ic_hi": round(hi, 5),
                  "z_hoje": round(z_h, 2), "z_novo": round(z_n, 2), "passa": passa},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[salvo] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
