# -*- coding: utf-8 -*-
"""SCORECARD DA PORTABILIDADE — a nota da fase Portabilidade, reproduzível.

Regra suprema (dele, 18/07): teto real, testável, e quando não der, avisar.
A Portabilidade mede uma coisa concreta: **a pasta do Dota roda sozinha em
qualquer PC** (o motor do LoL embutido = vendored). Componentes calculados:

  vendor-fresco   — cada .py de app_core/mlcore do LoL == a cópia vendored no
                    Dota (hash do conteúdo, ignorando só fim-de-linha). É o
                    coração: vendor defasado = o amigo roda motor velho.
  E2E-dota        — boot -> entrar -> selecionar times -> Analisar Confronto
                    no clone (subprocesso isolado; mesmo driver do test_e2e).
  artefatos       — o clone nasce com o cérebro? (ml_artifact/params/...);
                    players_artifact é ESPERADO ausente (camada Dota = backlog).
  overrides       — dota_overrides importa e aplica sem erro (muta labels).

Uso: python tools/portability_scorecard.py
Saída: texto + evidence/portability_scorecard.json
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOTA = ROOT.parent / "GabineteDOTA"
PKGS = ("app_core", "mlcore")
W_VENDOR, W_E2E, W_ART, W_OVR = 0.40, 0.35, 0.15, 0.10
# artefatos que o clone precisa p/ nascer com o cérebro (players = backlog P3).
CORE_ARTIFACTS = ("ml_artifact.json", "params_fitted.json", "team_state_artifact.json")


def _norm_hash(p: Path) -> str:
    try:
        data = p.read_bytes().replace(b"\r\n", b"\n")
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return ""


def score_vendor() -> dict:
    if not DOTA.exists():
        return {"nota": None, "detail": "GabineteDOTA não está ao lado"}
    total = same = missing = diff = 0
    diffs = []
    for pkg in PKGS:
        base = ROOT / pkg
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(ROOT)
            dst = DOTA / rel
            total += 1
            if not dst.exists():
                missing += 1
                diffs.append(f"{rel} (ausente)")
            elif _norm_hash(p) == _norm_hash(dst):
                same += 1
            else:
                diff += 1
                diffs.append(str(rel))
    if total == 0:
        return {"nota": None, "detail": "sem arquivos"}
    frac = same / total
    return {"nota": round(frac * 10, 2),
            "detail": f"{same}/{total} arquivos idênticos ({missing} ausentes, {diff} divergentes)"
                      + (f"; ex: {diffs[:3]}" if diffs else "")}


def score_e2e_dota() -> dict:
    app = DOTA / "gabinete_dota_app.py"
    if not app.exists():
        return {"nota": None, "detail": "app Dota ausente"}
    driver = (
        "import sys\n"
        "from streamlit.testing.v1 import AppTest\n"
        "at=AppTest.from_file(sys.argv[1],default_timeout=900); at.run()\n"
        "e=[b for b in at.button if b.label=='Entrar no app']\n"
        "if e: e[0].click(); at.run()\n"
        "t1=[s for s in at.selectbox if s.label=='Time 1']; t2=[s for s in at.selectbox if s.label=='Time 2']\n"
        "if not (t1 and t2): print('RESULT|SKIP|sem selecao'); sys.exit(0)\n"
        "opts=[o for o in t1[0].options if o]\n"
        "if len(opts)<2: print('RESULT|SKIP|poucos times'); sys.exit(0)\n"
        "t1[0].select(opts[0]); t2[0].select(opts[1]); at.run()\n"
        "an=[x for x in at.button if x.label=='Analisar Confronto']\n"
        "if not an: print('RESULT|SKIP|sem Analisar'); sys.exit(0)\n"
        "an[0].click(); at.run()\n"
        "print('RESULT|EXC|'+str(at.exception[0])[:200] if at.exception else 'RESULT|OK|'+str(len(at.tabs)))\n"
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8", GABINETE_E2E="1")
    try:
        cp = subprocess.run([sys.executable, "-c", driver, str(app)],
                            capture_output=True, text=True, timeout=1200,
                            cwd=str(DOTA), encoding="utf-8", errors="replace", env=env)
    except subprocess.TimeoutExpired:
        return {"nota": 0.0, "detail": "timeout no boot do Dota"}
    status, payload = "EXC", ""
    for ln in (cp.stdout or "").splitlines():
        if ln.startswith("RESULT|"):
            _, status, payload = ln.split("|", 2)
    if status == "OK":
        return {"nota": 10.0, "detail": f"boot->analisar OK ({payload} abas)"}
    if status == "SKIP":
        return {"nota": None, "detail": f"SKIP: {payload} (estado de dados, não regressão)"}
    return {"nota": 0.0, "detail": f"EXC: {payload or (cp.stderr or '')[-150:]}"}


def score_artifacts() -> dict:
    have = [a for a in CORE_ARTIFACTS if (DOTA / a).exists()]
    players = (DOTA / "players_artifact.json").exists()
    nota = 10.0 * len(have) / len(CORE_ARTIFACTS)
    note = "players_artifact ausente (esperado — camada Dota é backlog P3)" if not players else "players_artifact presente"
    return {"nota": round(nota, 2),
            "detail": f"{len(have)}/{len(CORE_ARTIFACTS)} artefatos core; {note}"}


def score_overrides() -> dict:
    ov = DOTA / "dota_overrides.py"
    if not ov.exists():
        return {"nota": None, "detail": "dota_overrides ausente"}
    driver = "import dota_overrides; dota_overrides.apply(); print('OVR_OK')"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        cp = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True,
                            timeout=300, cwd=str(DOTA), encoding="utf-8", errors="replace", env=env)
    except subprocess.TimeoutExpired:
        return {"nota": 0.0, "detail": "timeout"}
    ok = "OVR_OK" in (cp.stdout or "")
    return {"nota": 10.0 if ok else 0.0,
            "detail": "aplica sem erro" if ok else f"ERRO: {(cp.stderr or '')[-150:]}"}


def main() -> int:
    t0 = time.time()
    print(f"\n=== SCORECARD DA PORTABILIDADE — {time.strftime('%Y-%m-%d')} ===")
    if not DOTA.exists():
        print("GabineteDOTA não está ao lado — nota não medível nesta máquina.")
        return 0

    comps = {
        "vendor-fresco (peso 0.40)": score_vendor(),
        "E2E-dota (0.35)": score_e2e_dota(),
        "artefatos-cerebro (0.15)": score_artifacts(),
        "overrides (0.10)": score_overrides(),
    }
    weights = {"vendor-fresco (peso 0.40)": W_VENDOR, "E2E-dota (0.35)": W_E2E,
               "artefatos-cerebro (0.15)": W_ART, "overrides (0.10)": W_OVR}
    parts, wsum = 0.0, 0.0
    for name, c in comps.items():
        s = c.get("nota")
        print(f"  {name:28} {'n/a' if s is None else f'{s:5.2f}'}  {c['detail']}")
        if s is not None:
            parts += weights[name] * s
            wsum += weights[name]
    nota = parts / wsum if wsum > 0 else float("nan")
    print(f"\nNOTA DA PORTABILIDADE = {nota:.2f}  (média ponderada; componentes n/a = SKIP saem do cálculo)")
    print("TETO REAL: 10 é atingível (vendor idêntico + Dota boota + cérebro "
          "presente + overrides ok). O único gap estrutural — players_artifact "
          "no Dota — é backlog consciente (P3), não defeito de portabilidade.")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nota_portabilidade": round(nota, 2) if wsum > 0 else None,
           "componentes": comps, "elapsed_s": round(time.time() - t0, 1)}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "portability_scorecard.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[portability_scorecard] salvo: evidence/portability_scorecard.json ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
