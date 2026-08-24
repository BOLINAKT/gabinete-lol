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

# O console do Windows e cp1252 e a saida tem acento e o simbolo de aviso. Sem
# isto, o UnicodeEncodeError derruba a regua JUSTAMENTE quando ha algo a avisar —
# o pior momento possivel para o relatorio sumir (visto 16/08/2026, mesma familia
# do que estourava no train_offline com nome de time em chines).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "evidence"
# 10 dias: o vigia semanal re-mede tudo toda segunda, entao uma regua com mais de
# ~1,5 semana significa que alguma rodada FALHOU. O limite antigo (30) era frouxo
# demais — em 16/08/2026 sete das oito fases estavam com 26-29 dias e o scorecard
# nao avisou nada, porque 29 < 30. A nota do produto virou uma foto de julho.
STALE_DAYS = 10

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
# Visual REMOVIDO da nota (decisão dele 18/07): não é dimensão de medição —
# é dirigido por feedback direto ("o que eu não gostar eu peço para mudar").
# Com isso a nota do produto é 100% MEDIDA por régua (zero rubrica).


def _age_days(iso: str) -> float | None:
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Nota do produto (consolida réguas de fase).")
    ap.add_argument("--run", action="store_true", help="Roda as réguas baratas antes de consolidar (não roda fusion/totals, caras).")
    ap.add_argument("--strict", action="store_true",
                    help="Sai com erro se alguma régua estiver velha (> STALE_DAYS). "
                         "Para o vigia semanal falhar em vez de anunciar foto antiga.")
    args = ap.parse_args()

    if args.run:
        for _, _, ev, _, _, tool in PHASES:
            if "fusion" in tool or "totals" in tool:
                continue  # caras: usar evidence existente
            print(f"  rodando {tool}...", flush=True)
            # LOUD: antes isto engolia a falha (capture_output sem checar o
            # returncode) e a fase simplesmente continuava velha, sem explicacao.
            # Foi assim que a regua de Dados passou 29 dias quebrada por um
            # UnicodeEncodeError — o sintoma aparecia como "nota velha", que nao
            # aponta para a causa. Regua que falha tem que GRITAR.
            try:
                r = subprocess.run([sys.executable, tool], cwd=str(ROOT), timeout=1800,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace")
            except subprocess.TimeoutExpired:
                print(f"  ✗ {tool} ESTOUROU O TEMPO (1800s) — fase segue com nota velha")
                continue
            if r.returncode != 0:
                cauda = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
                print(f"  ✗ {tool} FALHOU (exit {r.returncode}) — fase segue com nota velha")
                for l in cauda:
                    print(f"      {l}")

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
        print(f"{name:18} {peso:>4} {nota:>6.2f} {teto:>5.1f} {age_s:>7}{flag}  {src}")
        rows.append((name, peso, float(nota), teto))
        wsum += peso
        psum += peso * float(nota)

    produto = psum / wsum if wsum > 0 else float("nan")
    teto_psum = sum(p * (t if t is not None else n) for (_n, p, n, t) in rows)
    teto_prod = teto_psum / wsum if wsum > 0 else float("nan")

    print(f"\nNOTA DO PRODUTO = {produto:.2f} / 10   (teto real do conjunto ~{teto_prod:.1f})")
    print(f"  {len(rows)}/{len(rows)} fases com nota MEDIDA por régua reproduzível (Visual saiu da nota: "
          "dirigido por feedback dele, não por medição).")
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
    print("\n[product_scorecard] salvo: evidence/product_scorecard.json")
    # Sai != 0 quando ha regua velha, para o vigia semanal poder FALHAR e abrir
    # issue em vez de anunciar uma nota que e foto antiga. --strict porque o uso
    # interativo (ele rodando no PC) nao deve quebrar por causa de idade.
    if stale and bool(getattr(args, "strict", False)):
        print(f"  [strict] saindo com erro: {len(stale)} régua(s) velha(s)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
