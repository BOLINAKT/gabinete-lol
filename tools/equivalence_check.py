# -*- coding: utf-8 -*-
"""REDE DE EQUIVALÊNCIA para refatorar código de CÁLCULO sem mudar resultado.

Regra (dele, 19/07): as 3 funções de complexidade alta são de MATEMÁTICA —
refatorar não pode mexer nem no último decimal. Este utilitário tira uma
"impressão digital" dos NÚMEROS que a função produz (ignorando campos
voláteis como timestamps) para comparar ANTES x DEPOIS do refactor.

Fluxo de uso:
  1. python tools/equivalence_check.py --save      (antes de tocar no código)
  2. ... refatora ...
  3. python tools/equivalence_check.py --check     (tem que dar IDÊNTICO)

Alvos cobertos:
  team_state  — mlcore.state_team_artifact.build_team_state_artifact
                (mu/sigma/gp por time, com dados REAIS; ~2 min)

Saída: evidence/equivalence_<alvo>.json (golden) + veredito no terminal.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

# Windows: o console é cp1252 e os emojis do veredito (✅/❌) estouravam com
# UnicodeEncodeError JUSTO na hora de reportar DIFERENÇAS — a rede de segurança
# quebrava calada quando mais importava. Forçar UTF-8 na saída resolve todos.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EV = ROOT / "evidence"
# campos que mudam a cada execução e NÃO indicam diferença de cálculo
VOLATEIS = {"generated_at", "created_at", "timestamp", "elapsed_s", "run_id"}


def _num(v):
    """Normaliza número p/ comparação estável (NaN vira marcador textual)."""
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Inf" if v > 0 else "-Inf"
        return round(v, 12)  # 12 casas: pega qualquer mudança real de cálculo
    return v


def fingerprint_team_state() -> dict:
    """Roda build_team_state_artifact com os CSVs REAIS e extrai os números."""
    from mlcore.state_team_artifact import build_team_state_artifact
    from tools.ml_quality_scorecard import default_csvs

    t0 = time.time()
    art = build_team_state_artifact(default_csvs(), include_players_for_roster=False)
    dt = time.time() - t0

    teams = art.get("teams") or {}
    # números por time, ordenados (a ordem do dict não deve importar)
    numeros = {}
    for key in sorted(teams):
        d = teams[key]
        if not isinstance(d, dict):
            continue
        numeros[key] = {k: _num(d.get(k)) for k in ("mu", "sigma", "gp", "wins", "losses")}

    by_league = art.get("by_league") or {}
    ligas = {lg: _num((by_league.get(lg) or {}).get("games")) for lg in sorted(by_league)}

    return {
        "alvo": "team_state",
        "n_times": len(numeros),
        "n_ligas": len(ligas),
        "n_gameids": len(art.get("processed_gameids") or []),
        "numeros": numeros,
        "ligas": ligas,
        "params": {k: _num(v) for k, v in sorted((art.get("params") or {}).items())
                   if k not in VOLATEIS and not isinstance(v, (dict, list))},
        "elapsed_s": round(dt, 1),
    }


ALVOS = {"team_state": fingerprint_team_state}


def _path(alvo: str) -> Path:
    return EV / f"equivalence_{alvo}.json"


def _comparar(golden: dict, atual: dict) -> list[str]:
    difs: list[str] = []
    for campo in ("n_times", "n_ligas", "n_gameids"):
        if golden.get(campo) != atual.get(campo):
            difs.append(f"{campo}: {golden.get(campo)} -> {atual.get(campo)}")
    g_num, a_num = golden.get("numeros") or {}, atual.get("numeros") or {}
    sumiram = sorted(set(g_num) - set(a_num))
    novos = sorted(set(a_num) - set(g_num))
    if sumiram:
        difs.append(f"times que SUMIRAM ({len(sumiram)}): {sumiram[:5]}")
    if novos:
        difs.append(f"times NOVOS ({len(novos)}): {novos[:5]}")
    mudou = 0
    exemplos: list[str] = []
    for k in sorted(set(g_num) & set(a_num)):
        if g_num[k] != a_num[k]:
            mudou += 1
            if len(exemplos) < 5:
                dif = {kk: (g_num[k].get(kk), a_num[k].get(kk))
                       for kk in g_num[k] if g_num[k].get(kk) != a_num[k].get(kk)}
                exemplos.append(f"{k}: {dif}")
    if mudou:
        difs.append(f"times com NUMERO DIFERENTE: {mudou}")
        difs.extend(f"   {e}" for e in exemplos)
    if (golden.get("ligas") or {}) != (atual.get("ligas") or {}):
        difs.append("contagem de jogos por liga mudou")
    if (golden.get("params") or {}) != (atual.get("params") or {}):
        difs.append("params do artefato mudaram")
    return difs


def main() -> int:
    ap = argparse.ArgumentParser(description="Rede de equivalência p/ refactor de cálculo.")
    ap.add_argument("--alvo", default="team_state", choices=sorted(ALVOS))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", action="store_true", help="grava o golden (ANTES do refactor)")
    g.add_argument("--check", action="store_true", help="compara com o golden (DEPOIS)")
    args = ap.parse_args()

    EV.mkdir(exist_ok=True)
    print(f"[equivalence] alvo={args.alvo} — rodando com dados REAIS (pode levar ~2 min)...", flush=True)
    atual = ALVOS[args.alvo]()
    print(f"[equivalence] {atual['n_times']} times, {atual['n_ligas']} ligas "
          f"({atual['elapsed_s']}s)")

    p = _path(args.alvo)
    if args.save:
        p.write_text(json.dumps(atual, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"✅ GOLDEN salvo: {p}")
        print("   Agora pode refatorar. Ao terminar: --check")
        return 0

    if not p.exists():
        print(f"❌ golden ausente ({p}). Rode --save antes de refatorar.")
        return 1
    golden = json.loads(p.read_text(encoding="utf-8"))
    difs = _comparar(golden, atual)
    if not difs:
        print("✅ EQUIVALENTE — nenhum número mudou. Refactor seguro.")
        return 0
    print(f"❌ DIFERENÇAS ({len(difs)}) — o refactor MUDOU o resultado:")
    for d in difs:
        print("   " + d)
    print("\n   NÃO promover. Reverter ou corrigir até dar equivalente.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
