# -*- coding: utf-8 -*-
"""Compara dois artefatos de modelo rating a rating, para conferir rollback.

╔══ POR QUE ESTE ARQUIVO EXISTE ═════════════════════════════════════════════╗
║ A margem de vitoria so pode entrar em producao se houver como sair. A       ║
║ garantia prometida na especificacao 001 (SC-005 / FR-005) e forte: com a    ║
║ margem desligada o modelo tem de ser IDENTICO ao de antes, nao "parecido".  ║
║                                                                            ║
║ Isto e um Golden Master / teste de caracterizacao: "capture a saida do      ║
║ sistema legado, depois compare a saida do sistema novo contra ela — se      ║
║ forem iguais, o comportamento foi preservado".                              ║
║ https://michaelfeathers.silvrback.com/characterization-testing              ║
║ (aberta em 11/09/2026)                                                     ║
║                                                                            ║
║ ARMADILHA JA PISADA: nao compare contra o backup .pre_update_*. Aquele      ║
║ artefato e uma atualizacao INCREMENTAL em cima de um treino completo        ║
║ antigo, e um treino completo novo nunca vai bater com ele — a diferenca     ║
║ seria de cadencia, nao de margem, e o teste diria "vazou" sem ter vazado.   ║
║ O controle certo e o CODIGO de antes da margem rodando nos MESMOS CSVs.     ║
╚════════════════════════════════════════════════════════════════════════════╝
"""
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
import argparse
import io
import json


def _ratings(caminho):
    d = json.load(io.open(caminho, encoding="utf-8"))
    onde = d.get("model", d)
    for chave in ("ratings", "team_ratings", "teams"):
        if isinstance(onde.get(chave), dict):
            return onde[chave], d.get("meta", {})
    raise SystemExit("nao achei os ratings em {}".format(caminho))


def _numero(v):
    """Extrai o numero do rating, seja ele solto ou dentro de um dicionario."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("rating", "r", "elo", "base_strength", "residual"):
            if isinstance(v.get(k), (int, float)):
                return float(v[k])
    return None


def comparar(a, b):
    ra, ma = _ratings(a)
    rb, mb = _ratings(b)

    so_a = sorted(set(ra) - set(rb))
    so_b = sorted(set(rb) - set(ra))
    comuns = sorted(set(ra) & set(rb))

    difs = []
    ilegiveis = 0
    for t in comuns:
        na, nb = _numero(ra[t]), _numero(rb[t])
        if na is None or nb is None:
            ilegiveis += 1
            continue
        difs.append((abs(na - nb), t, na, nb))
    difs.sort(reverse=True)

    print("A = {}".format(a))
    print("B = {}".format(b))
    print("")
    print("  times so em A .............. {}".format(len(so_a)))
    print("  times so em B .............. {}".format(len(so_b)))
    print("  times em ambos ............. {}".format(len(comuns)))
    if ilegiveis:
        print("  ratings nao numericos ...... {}".format(ilegiveis))
    if so_a[:5]:
        print("  exemplos so em A: {}".format(", ".join(so_a[:5])))
    if so_b[:5]:
        print("  exemplos so em B: {}".format(", ".join(so_b[:5])))

    if not difs:
        print("\n  NADA COMPARAVEL — pare e olhe o formato dos arquivos.")
        return 2

    maior = difs[0][0]
    iguais = sum(1 for d, _, _, _ in difs if d == 0.0)
    print("")
    print("  identicos bit a bit ........ {} de {}".format(iguais, len(difs)))
    print("  maior diferenca ............ {:.12g}".format(maior))
    print("  diferenca media ............ {:.12g}".format(
        sum(d for d, _, _, _ in difs) / len(difs)))

    if maior > 0:
        print("\n  os 5 que mais divergem:")
        for d, t, na, nb in difs[:5]:
            print("    {:<28} {:.10f}  vs  {:.10f}   (dif {:.3g})".format(
                t[:28], na, nb, d))

    print("")
    if so_a or so_b:
        print("  VEREDITO: os conjuntos de times diferem — NAO e rollback limpo.")
        return 1
    if maior == 0.0:
        print("  VEREDITO: IDENTICOS bit a bit. O rollback e limpo.")
        return 0
    if maior < 1e-9:
        print("  VEREDITO: iguais dentro do erro de ponto flutuante ({:.3g}).".format(maior))
        print("            Aceitavel, mas NAO e bit a bit — registre o numero.")
        return 0
    print("  VEREDITO: DIVERGEM. A margem esta vazando para o caminho desligado.")
    print("            PARE. Nao suba isso.")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a")
    ap.add_argument("b")
    args = ap.parse_args()
    raise SystemExit(comparar(args.a, args.b))


if __name__ == "__main__":
    main()
