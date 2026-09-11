# -*- coding: utf-8 -*-
"""FASE 2 — compara variantes da cadeia com o rigor que o protocolo exige.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ 1. FATORIAL, NAO UM-DE-CADA-VEZ. "OFAT tem dois problemas serios: e         ║
║    grosseiramente ineficiente... e, mais grave, o experimentador fica       ║
║    incapaz de estudar interacoes", e "ignora interacoes entre fatores, o    ║
║    que pode levar a condicoes otimas falsas".                               ║
║    https://www.6sigma.us/six-sigma-in-focus/ofat-one-factor-at-a-time/      ║
║    Para ablacao especificamente: "quando componentes interagem, a ablacao   ║
║    um-de-cada-vez pode dar atribuicoes enganosas... os componentes devem    ║
║    ser removidos AOS PARES".                                                ║
║    https://www.emergentmind.com/topics/ablation-studies                     ║
║    (ambas abertas em 09/09/2026)                                            ║
║    MEDIDO AQUI: hybrid sozinho vale +0,17 de nota; com a forma ligada, so   ║
║    +0,08. A interacao (-0,09) so aparece no fatorial — os dois medem forma  ║
║    recente e se canibalizam.                                                ║
║                                                                             ║
║ 2. ERRO-PADRAO DIADICO. Cada jogo pertence a DOIS times, entao a            ║
║    dependencia nao e de um agrupamento so. E o caso classico de dado        ║
║    diadico, "onde a unidade observacional e um par (g,h)". O tratamento e   ║
║    o agrupamento em duas vias de Cameron, Gelbach & Miller: "obter tres     ║
║    matrizes de variancia robusta agrupando na primeira dimensao, na         ║
║    segunda, e na intersecao" -> V = V_a + V_b - V_par.                      ║
║    https://cameron.econ.ucdavis.edu/research/Cameron_Miller_JHR_2015_February.pdf
║    (aberta em 09/09/2026)                                                   ║
║    RESSALVA DA PROPRIA FONTE, registrada de proposito: mesmo o estimador de ║
║    duas vias "ainda subestima os erros-padrao" em dados diadicos. Entao o   ║
║    IC daqui e OTIMISTA; a direcao do residuo e conhecida e esta dita.       ║
║                                                                             ║
║ 3. COMPARACOES MULTIPLAS. Sao muitas variantes; a p<0,05 cada, aprovacoes   ║
║    falsas por acaso sao esperadas. Pratica: Benjamini-Hochberg como analise ║
║    primaria (controla taxa de falsas descobertas) e Holm-Bonferroni como    ║
║    checagem estrita (controla erro familiar).                               ║
║    https://casrai.org/guides/bonferroni-correction-and-multiple-comparisons ║
║    (aberta em 09/09/2026)                                                   ║
║                                                                             ║
║ 4. TESTE PAREADO, sempre. As variantes rodam nos MESMOS jogos; comparar     ║
║    medias independentes jogaria fora essa informacao e alargaria o IC a     ║
║    toa.                                                                     ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
  python tools/comparar_variantes.py --base diaria --cand diaria_hybrid
  python tools/comparar_variantes.py --fatorial
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PASTA = ROOT / "scratchpad" / "nota_honesta"


def carregar(marca: str) -> dict:
    """Aceita o sufixo curto da marca 'prod' OU o nome completo do arquivo.

    Nasceu so com o prefixo `nota_honesta_prod_`, e por isso nao conseguia
    comparar nada rodado com outra marca (`--marca margem`, por exemplo) —
    o que escondeu por um tempo qual numero pertencia a qual variante.
    Os candidatos vao do mais especifico ao mais geral, entao o
    comportamento antigo continua valendo palavra por palavra.
    """
    nome = str(marca).strip()
    if nome.endswith(".json"):
        nome = nome[:-5]
    candidatos = [
        PASTA / f"nota_honesta_prod_{nome}.json",   # jeito antigo, vem primeiro
        PASTA / f"{nome}.json",                     # nome completo do arquivo
        PASTA / f"nota_honesta_{nome}.json",        # sem o 'prod_'
        Path(nome).with_suffix(".json"),            # caminho solto
    ]
    for p in candidatos:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    tentados = "\n  ".join(str(c) for c in candidatos)
    raise SystemExit(f"variante ausente: '{marca}'. Procurei em:\n  {tentados}")


def _times_por_jogo() -> dict:
    """gameid -> (blue, red). Necessario para o agrupamento diadico."""
    from mlcore.io_oracle import load_oracle_elixir_games
    from tools.ml_quality_scorecard import default_csvs
    g = pd.concat([load_oracle_elixir_games(str(c)) for c in default_csvs()],
                  ignore_index=True)
    return {str(r.gameid): (str(r.blue), str(r.red)) for r in g.itertuples(index=False)}


def _ll(p: float, y: int) -> float:
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def _var_agrupada(d: np.ndarray, chaves: list) -> float:
    """Variancia da MEDIA de d, agrupando por `chaves` (cluster-robust)."""
    c = d - d.mean()
    somas: dict = {}
    for k, v in zip(chaves, c):
        somas[k] = somas.get(k, 0.0) + float(v)
    return float(sum(s * s for s in somas.values())) / (len(d) ** 2)


def comparar(base: dict, cand: dict, times: dict, nome: str = "") -> dict:
    """Diferenca pareada de logloss, com IC ingenuo e IC diadico."""
    b = {g: (p, y) for g, p, y in base.get("por_jogo", [])}
    c = {g: (p, y) for g, p, y in cand.get("por_jogo", [])}
    comuns = sorted(set(b) & set(c))
    if not comuns:
        raise SystemExit("as duas variantes nao compartilham jogos — nao da para parear")

    d = np.array([_ll(*b[g]) - _ll(*c[g]) for g in comuns], dtype=float)
    n = len(d)
    media = float(d.mean())

    # IC ingenuo (i.i.d.) — o que eu usava antes
    se_ing = float(d.std(ddof=1) / math.sqrt(n))

    # IC diadico: V = V_a + V_b - V_par  (Cameron/Gelbach/Miller)
    ta = [times.get(g, ("?", "?"))[0] for g in comuns]
    tb = [times.get(g, ("?", "?"))[1] for g in comuns]
    par = [tuple(sorted(x)) for x in zip(ta, tb)]
    v = _var_agrupada(d, ta) + _var_agrupada(d, tb) - _var_agrupada(d, par)
    se_dia = math.sqrt(v) if v > 0 else float("nan")

    z = 1.959963985
    return {
        "nome": nome, "n": n, "dif": media,
        "ic_ing": (media - z * se_ing, media + z * se_ing),
        "ic_dia": (media - z * se_dia, media + z * se_dia),
        "se_ing": se_ing, "se_dia": se_dia,
        "p": 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(media / se_dia) / math.sqrt(2.0))))
             if se_dia and math.isfinite(se_dia) and se_dia > 0 else float("nan"),
    }


def corrigir_multiplas(res: list) -> None:
    """Benjamini-Hochberg (primaria) e Holm-Bonferroni (estrita)."""
    validos = [r for r in res if math.isfinite(r.get("p", float("nan")))]
    m = len(validos)
    if not m:
        return
    # BH: ordena crescente, limiar i/m * alfa
    for i, r in enumerate(sorted(validos, key=lambda x: x["p"]), start=1):
        r["bh_limiar"] = 0.05 * i / m
        r["passa_bh"] = r["p"] <= r["bh_limiar"]
    # Holm: ordena crescente, limiar alfa/(m-i+1), e para no primeiro que falha
    parou = False
    for i, r in enumerate(sorted(validos, key=lambda x: x["p"]), start=1):
        r["holm_limiar"] = 0.05 / (m - i + 1)
        r["passa_holm"] = (not parou) and (r["p"] <= r["holm_limiar"])
        if not r["passa_holm"]:
            parou = True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fatorial", action="store_true",
                    help="Analisa o 2x2 hybrid x forma (efeitos principais e interacao).")
    ap.add_argument("--base", default="diaria")
    ap.add_argument("--cand", default="diaria_hybrid")
    args = ap.parse_args()

    times = _times_por_jogo()

    if not args.fatorial:
        r = comparar(carregar(args.base), carregar(args.cand), times,
                     f"{args.base} -> {args.cand}")
        print(f"{r['nome']}  n={r['n']}")
        print(f"  dif logloss  {r['dif']:+.5f}   (positivo = candidato melhor)")
        print(f"  IC95 ingenuo [{r['ic_ing'][0]:+.5f}, {r['ic_ing'][1]:+.5f}]")
        print(f"  IC95 diadico [{r['ic_dia'][0]:+.5f}, {r['ic_dia'][1]:+.5f}]  <- o que vale")
        return 0

    # ---- fatorial 2x2 ----
    celulas = {
        ("off", "off"): "diaria",
        ("on", "off"): "diaria_hybrid",
        ("off", "on"): "diaria_form",
        ("on", "on"): "diaria_hybrid_form",
    }
    dados = {k: carregar(v) for k, v in celulas.items()}
    print("FATORIAL 2x2 — hybrid_blend x season_form_blend\n")

    comps = [
        ("hybrid, com forma OFF", ("off", "off"), ("on", "off")),
        ("hybrid, com forma ON ", ("off", "on"), ("on", "on")),
        ("forma, com hybrid OFF", ("off", "off"), ("off", "on")),
        ("forma, com hybrid ON ", ("on", "off"), ("on", "on")),
    ]
    res = []
    for nome, a, b in comps:
        res.append(comparar(dados[a], dados[b], times, nome))
    corrigir_multiplas(res)

    print(f"{'comparacao':<24}{'dif ll':>10}{'IC95 diadico':>26}{'p':>9}  BH   Holm")
    for r in res:
        ic = f"[{r['ic_dia'][0]:+.5f}, {r['ic_dia'][1]:+.5f}]"
        bh = "sim" if r.get("passa_bh") else "nao"
        ho = "sim" if r.get("passa_holm") else "nao"
        print(f"{r['nome']:<24}{r['dif']:>+10.5f}{ic:>26}{r['p']:>9.4f}  {bh:<5}{ho}")

    # interacao = (efeito do hybrid com forma ON) - (com forma OFF)
    inter = res[1]["dif"] - res[0]["dif"]
    print(f"\nINTERACAO (efeito do hybrid com forma ON menos com forma OFF): {inter:+.5f}")
    print("  negativo = os dois se canibalizam (medem a mesma coisa)")
    print("\nRESSALVA: o IC diadico ainda SUBESTIMA o erro-padrao (Cameron/Miller);")
    print("o intervalo real e mais largo que o mostrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
