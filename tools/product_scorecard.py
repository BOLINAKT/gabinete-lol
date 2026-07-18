# -*- coding: utf-8 -*-
"""SCORECARD DO PRODUTO — a nota do produto inteiro, reproduzível.

Regra suprema (dele, 18/07): teto real por fase, testável e replicável;
quando não der, avisar. Este consolida as RÉGUAS DE FASE (cada uma salva seu
evidence/*.json) numa nota de produto ponderada — mesmo comando -> mesmo
número. Fases sem régua própria (só Visual, aceite do dono) entram marcadas.

Cada fase: nota MEDIDA (📊, lida do evidence) + peso + teto real declarado.
AVISA se algum evidence estiver velho (re-rodar a régua da fase).

Uso:
  python tools/product_scorecard.py            # lê os evidence existentes
  python tools/product_scorecard.py --run      # roda as réguas baratas antes
Saída: texto + evidence/product_scorecard.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence"
STALE_DAYS = 30

# fase -> (peso, arquivo de evidence, chave da nota, teto real declarado, régua p/ --run)
PHASES = [
    ("Vencedor (ML)",   25, "fusion_scorecard.json",      "nota_fusao",         9.5, "tools/ml_fusion_scorecard.py"),
    ("Dados/automação", 15, "data_scorecard.json",        "nota_dados",         9.5, "tools/data_scorecard.py"),
    ("Totais",          15, "totals_scorecard.json",      "nota_totais",        6.5, "tools/totals_scorecard.py"),
    ("Live",            10, "live_scorecard.json",        "nota_live",          9.5, "tools/live_scorecard.py"),
    ("Confiabilidade",  10, "reliability_scorecard.json", "nota_confiabilidade", 10.0, "tools/reliability_scorecard.py"),
    ("Código/testes",   10, "code_scorecard.json",        "nota",               9.0, "tools/code_scorecard.py"),
    ("Players",          5, "players_scorecard.json",     "nota_players",       9.0, "tools/players_scorecard.py"),
    ("Portabilidade",    5, "portability_scorecard.json", "nota_portabilidade", 10.0, "tools/portability_scorecard.py"),
]
# Visual: sem régua numérica — aceite explícito do dono (18/07 "visual já está
# bom"). Entra como aceite, não medição; peso 5.
VISUAL = ("Visual", 5, 8.5, "aceite do dono (não medido — 'visual já está bom', 18/07)")


def _age_days(iso: str) -> float | None:
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Nota do produto (consolida réguas de fase).")
    ap.add_argument("--run", action="store_true", help="Roda as réguas baratas antes de consolidar (não roda fusion/totals, caras).")
    args = ap.parse_args()

    if args.run:
        for _, _, ev, _, _, tool in PHASES:
            if "fusion" in tool or "totals" in tool:
                continue  # caras: usar evidence existente
            print(f"  rodando {tool}...", flush=True)
            subprocess.run([sys.executable, tool], cwd=str(ROOT), timeout=1800,
                           capture_output=True, text=True)

    print(f"\n=== SCORECARD DO PRODUTO — {time.strftime('%Y-%m-%d')} ===")
    print(f"{'fase':18} {'peso':>4} {'nota':>6} {'teto':>5} {'idade':>7}  fonte")
    rows = []
    wsum = psum = 0.0
    stale = []
    for name, peso, ev_file, key, teto, _tool in PHASES:
        p = EV / ev_file
        nota = age = None
        src = ev_file
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                nota = d.get(key)
                age = _age_days(str(d.get("generated_at", "")))
            except (OSError, json.JSONDecodeError):
                pass
        if nota is None:
            print(f"{name:18} {peso:>4} {'n/a':>6} {teto:>5.1f} {'—':>7}  (evidence ausente — rode {_tool})")
            continue
        if age is not None and age > STALE_DAYS:
            stale.append(f"{name} ({age:.0f}d)")
        age_s = f"{age:.0f}d" if age is not None else "?"
        flag = " ⚠" if (age is not None and age > STALE_DAYS) else ""
        print(f"{name:18} {peso:>4} {nota:>6.2f} {teto:>5.1f} {age_s:>7}{flag}")
        rows.append((name, peso, float(nota), teto))
        wsum += peso
        psum += peso * float(nota)

    # Visual (aceite)
    vname, vpeso, vnota, vsrc = VISUAL
    print(f"{vname:18} {vpeso:>4} {vnota:>6.2f} {'—':>5} {'aceite':>7}  {vsrc}")
    rows.append((vname, vpeso, vnota, None))
    wsum += vpeso
    psum += vpeso * vnota

    produto = psum / wsum if wsum > 0 else float("nan")
    # teto do produto = média ponderada dos tetos (Visual usa a própria nota-aceite)
    teto_psum = sum(p * (t if t is not None else n) for (_n, p, n, t) in rows)
    teto_prod = teto_psum / wsum if wsum > 0 else float("nan")

    print(f"\nNOTA DO PRODUTO = {produto:.2f} / 10   (teto real do conjunto ~{teto_prod:.1f})")
    medidas = sum(1 for r in rows if r[0] != "Visual")
    print(f"  {medidas}/{len(rows)} fases com nota MEDIDA por régua reproduzível (só Visual é aceite do dono).")
    if stale:
        print(f"  ⚠ AVISO — réguas VELHAS (> {STALE_DAYS}d), re-rodar: {', '.join(stale)}")
    print("\n  Onde ainda há subida REAL (nota < teto): " +
          ", ".join(f"{n} ({v:.1f}->{t:.1f})" for (n, _p, v, t) in rows if t is not None and v < t - 0.15) or "nenhuma — tudo no teto")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nota_produto": round(produto, 2), "teto_produto": round(teto_prod, 2),
           "fases": [{"fase": n, "peso": p, "nota": v, "teto": t} for (n, p, v, t) in rows],
           "stale": stale}
    EV.mkdir(exist_ok=True)
    (EV / "product_scorecard.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[product_scorecard] salvo: evidence/product_scorecard.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
