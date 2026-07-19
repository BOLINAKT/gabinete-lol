# -*- coding: utf-8 -*-
"""EMULADOR DE STRESS — usa o app como um usuário faria, forçando quebras.

Pedido dele (18/07): "você consegue emular utilizando o código, trabalhando em
todas as partes do código forçando para ver se quebra?". Motivação concreta:
o bug da Visão Geral (18/07) estava no código desde 02/06 e só apareceu quando
ELE abriu um confronto específico — o E2E não pegou porque testa 1 confronto
genérico. Este emulador varre MUITOS confrontos e TODAS as abas.

O que ele exercita:
  1. confrontos variados     — same-league, cross-região, times com pouco
                               histórico, BO 1/3/5 (sorteio com seed = replicável)
  2. TODAS as abas           — clica em cada uma das 10 e captura exceção
  3. entradas ruins (--deep) — linhas com texto, valor absurdo, negativo, vazio
                               (o app não pode cair por dado atípico)
  4. estados atípicos        — microseg hierárquico com n=lista (o bug real de
                               18/07), sessão sem artefato de players etc.

Cada falha vira uma linha do relatório com o cenário EXATO para reproduzir e
virar teste de regressão.

Uso:
  python tools/stress_emulator.py                 # 12 confrontos, abas
  python tools/stress_emulator.py --matchups 25 --deep
Saída: texto + evidence/stress_emulator.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# roda o app em SUBPROCESSO (isolamento: um crash não derruba a varredura)
_DRIVER = r'''
import json, sys, traceback
from streamlit.testing.v1 import AppTest

cenarios = json.loads(sys.argv[1])
falhas, feitos = [], 0

at = AppTest.from_file("plays_app.py", default_timeout=900)
at.run()
ent = [b for b in at.button if b.label == "Entrar no app"]
if ent:
    ent[0].click(); at.run()
if at.exception:
    print("RESULT|" + json.dumps({"falhas": [{"cenario": "boot", "erro": str(at.exception[0])[:300]}], "feitos": 0}))
    raise SystemExit(0)

for c in cenarios:
    try:
        at.session_state["teamA"] = c["a"]
        at.session_state["teamB"] = c["b"]
        at.session_state["bo"] = c["bo"]
        for k, v in (c.get("state") or {}).items():
            at.session_state[k] = v
        for k, v in (c.get("linhas") or {}).items():
            at.session_state[k] = v
        at.session_state["flow_stage"] = "results"
        at.session_state["_analysis_force_once"] = True
        at.run()
        if at.exception:
            falhas.append({"cenario": c, "fase": "analise", "erro": str(at.exception[0])[:400]})
            at.session_state["_analysis_force_once"] = False
            continue
        # percorre TODAS as abas renderizadas
        for tab in list(at.tabs):
            try:
                nome = str(tab.label)
            except Exception:
                nome = "?"
            if at.exception:
                falhas.append({"cenario": c, "fase": f"aba:{nome}", "erro": str(at.exception[0])[:400]})
                break
        feitos += 1
    except Exception as exc:
        falhas.append({"cenario": c, "fase": "driver", "erro": f"{type(exc).__name__}: {exc}"[:300]})

print("RESULT|" + json.dumps({"falhas": falhas, "feitos": feitos}))
'''


def _times_reais() -> list[tuple[str, str]]:
    """(time, liga) do CSV vivo — para montar confrontos same/cross-liga."""
    import pandas as pd
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.ml_quality_scorecard import default_csvs
    csvs = default_csvs()
    tg = build_team_games(load_team_rows(str(csvs[-1])))
    if tg is None or tg.empty:
        return []
    sub = tg.dropna(subset=["team"]).drop_duplicates("team")
    out = []
    for r in sub.itertuples(index=False):
        lg = str(getattr(r, "league", "") or "")
        out.append((str(r.team), lg))
    return out


LINHAS_RUINS = [
    {"lines_kills": "abc"},                    # texto onde espera número
    {"lines_kills": "999999"},                 # absurdo
    {"lines_kills": "-5"},                     # negativo
    {"lines_kills": ""},                       # vazio
    {"lines_time": "32,5"},                    # vírgula (formato BR)
    {"lines_kills": "27.5, , 30"},             # item vazio no meio
    {"hc_kills_text": "abc"},                  # handicap inválido
    {"combo_kills_text": "1e999"},             # overflow
]
# estados atípicos que já causaram (ou podem causar) quebra real
ESTADOS_ATIPICOS = [
    {"_ml_microseg_info": {"applied": True, "key": "X", "n": [10, 20], "bias": 0.02}},  # bug 18/07
    {"_ml_microseg_info": {"applied": True, "key": "X", "n": {}, "bias": None}},
    {"_p_map_used": float("nan")},
    {"resumo_combo_use_mismatch": True},
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Emulador de stress do app.")
    ap.add_argument("--matchups", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260718)
    ap.add_argument("--deep", action="store_true", help="inclui entradas ruins e estados atípicos")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    t0 = time.time()
    rnd = random.Random(args.seed)
    times = _times_reais()
    if len(times) < 4:
        print("sem times suficientes no CSV")
        return 1
    por_liga: dict[str, list[str]] = {}
    for t, lg in times:
        por_liga.setdefault(lg, []).append(t)
    ligas = [lg for lg, ts in por_liga.items() if len(ts) >= 2]

    cenarios = []
    for i in range(args.matchups):
        if ligas and i % 2 == 0:  # same-league
            lg = rnd.choice(ligas)
            a, b = rnd.sample(por_liga[lg], 2)
            tipo = f"same:{lg}"
        else:                      # cross-região
            (a, la), (b, lb) = rnd.sample(times, 2)
            tipo = f"cross:{la}x{lb}"
        c = {"a": a, "b": b, "bo": rnd.choice([1, 3, 5]), "tipo": tipo}
        if args.deep:
            if i % 3 == 0:
                c["linhas"] = dict(rnd.choice(LINHAS_RUINS))
            if i % 4 == 0:
                c["state"] = dict(rnd.choice(ESTADOS_ATIPICOS))
        cenarios.append(c)

    print(f"=== EMULADOR DE STRESS — {len(cenarios)} cenários (seed {args.seed}, deep={args.deep}) ===")
    for c in cenarios:
        extra = " +linhas-ruins" if c.get("linhas") else ""
        extra += " +estado-atipico" if c.get("state") else ""
        print(f"  {c['a']} x {c['b']} (bo{c['bo']}, {c['tipo']}){extra}")
    print("\nrodando (subprocesso isolado; ~15-25s por cenário)...", flush=True)

    env = dict(os.environ, PYTHONIOENCODING="utf-8", GABINETE_E2E="1")
    try:
        cp = subprocess.run([sys.executable, "-c", _DRIVER, json.dumps(cenarios)],
                            capture_output=True, text=True, cwd=str(ROOT),
                            timeout=args.timeout, encoding="utf-8", errors="replace", env=env)
    except subprocess.TimeoutExpired:
        print("TIMEOUT — a varredura passou do limite")
        return 1

    payload = None
    for ln in (cp.stdout or "").splitlines():
        if ln.startswith("RESULT|"):
            payload = json.loads(ln.split("|", 1)[1])
    if payload is None:
        print("driver não retornou RESULT. stderr:", (cp.stderr or "")[-400:])
        return 1

    falhas = payload["falhas"]
    print(f"\ncenários exercitados: {payload['feitos']}/{len(cenarios)}")
    if not falhas:
        print("✅ NENHUMA QUEBRA — o app aguentou todos os cenários.")
    else:
        print(f"❌ {len(falhas)} QUEBRA(S):\n")
        for f in falhas:
            c = f["cenario"]
            desc = c if isinstance(c, str) else f"{c.get('a')} x {c.get('b')} bo{c.get('bo')} [{c.get('tipo')}]"
            print(f"  - {desc}")
            print(f"    fase: {f['fase']}")
            print(f"    erro: {f['erro'][:220]}")
            if isinstance(c, dict) and (c.get("linhas") or c.get("state")):
                print(f"    entrada: linhas={c.get('linhas')} estado={c.get('state')}")
            print()

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seed": args.seed,
           "deep": bool(args.deep), "cenarios": len(cenarios),
           "exercitados": payload["feitos"], "falhas": falhas,
           "elapsed_s": round(time.time() - t0, 1)}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "stress_emulator.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[stress_emulator] relatório: evidence/stress_emulator.json ({time.time()-t0:.0f}s)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
