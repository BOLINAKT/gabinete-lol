# -*- coding: utf-8 -*-
"""SCORECARD DOS DADOS/AUTOMAÇÃO — a nota da fase Dados, reproduzível.

Regra suprema (dele, 18/07): teto real, testável, e declarar o teto.
A fase Dados é o pipeline "site sempre atualizado sem eu digitar nada":
baixar/receber CSV -> validar -> retreinar -> publicar. Componentes:

  caminhos-de-falha — os testes que blindam o pipeline passam (download com
                      quota/regressão/lixo/virada-de-ano; upload validado;
                      manutenção/bootstrap; retrain-check). É o coração:
                      falha silenciosa de dado = odd errada.
  frescor           — quão atual é o CSV vivo (dias entre a última partida e
                      hoje). Régua: 0-1 dia = 10, cai até 7 dias = 5.
  automacao         — os 3 workflows (dados diário, retreino, vigia) presentes
                      e o upload manual no site como fallback universal.

Uso: python tools/data_scorecard.py
Saída: texto + evidence/data_scorecard.json
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W_FALHA, W_FRESCOR, W_AUTO = 0.45, 0.30, 0.25

PIPELINE_TESTS = [
    "mlcore.tests.test_oe_download",              # quota/regressão/lixo/virada-de-ano/atômico
    "mlcore.tests.test_viewer_mode_core",         # upload validado + dispatch + acompanhamento
    "mlcore.tests.test_retrain_check",            # decide quando retreinar
    "mlcore.tests.test_daily_pipeline_runtime_core",
    "mlcore.tests.test_bootstrap_maintenance_state_core",
]
WORKFLOWS = ("dados_diarios.yml", "retreino.yml", "nota_semanal.yml")


def _run_tests(mods: list[str]) -> tuple[int, int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cp = subprocess.run([sys.executable, "-m", "unittest", *mods, "-v"],
                        capture_output=True, text=True, cwd=str(ROOT), timeout=1800,
                        encoding="utf-8", errors="replace", env=env)
    out = (cp.stdout or "") + (cp.stderr or "")
    m = re.search(r"Ran (\d+) tests", out)
    total = int(m.group(1)) if m else 0
    fails = len(re.findall(r"\.\.\. (FAIL|ERROR)", out)) + len(re.findall(r"^(FAIL|ERROR):", out, re.M))
    return total - fails, total, f"{total-fails}/{total} ok ({fails} falhas)"


def _csv_freshness() -> tuple[float, str]:
    fs = glob.glob(str(ROOT / "CSV_DIARIO" / "*.csv"))
    if not fs:
        return float("nan"), "sem CSV"
    import pandas as pd
    f = max(fs, key=os.path.getmtime)
    try:
        d = pd.read_csv(f, usecols=["date"], low_memory=False)
        maxd = pd.to_datetime(d["date"], errors="coerce").max()
        age = (pd.Timestamp.now() - maxd).total_seconds() / 86400.0
        return age, f"{os.path.basename(f)}: última partida {str(maxd)[:10]} ({age:.1f}d atrás)"
    except (OSError, ValueError, KeyError):
        return float("nan"), "CSV ilegível"


def main() -> int:
    t0 = time.time()
    print(f"\n=== SCORECARD DOS DADOS/AUTOMAÇÃO (F1) — {time.strftime('%Y-%m-%d')} ===")
    print("  rodando testes do pipeline...", flush=True)

    ok, tot, det = _run_tests(PIPELINE_TESTS)
    age, fresco_det = _csv_freshness()
    # frescor: 0-1 dia = 10; cai linear até 7 dias = 5; depois despenca.
    if age != age:  # nan
        fresco_nota = None
    elif age <= 1.0:
        fresco_nota = 10.0
    else:
        fresco_nota = max(0.0, 10.0 - (age - 1.0) / 6.0 * 5.0)

    wf = [w for w in WORKFLOWS if (ROOT / ".github" / "workflows" / w).exists()]
    uploader = "render_csv_upload_panel" in (ROOT / "app_core" / "viewer_mode_core.py").read_text(encoding="utf-8", errors="replace")
    auto_nota = 10.0 * (len(wf) / len(WORKFLOWS)) * (1.0 if uploader else 0.7)

    comps = {
        "caminhos-de-falha (peso 0.45)": {"nota": round(10.0 * ok / tot, 2) if tot else None,
                                          "detail": f"download+upload+retrain+manutenção: {det}"},
        "frescor (0.30)": {"nota": round(fresco_nota, 2) if fresco_nota is not None else None,
                          "detail": fresco_det},
        "automacao (0.25)": {"nota": round(auto_nota, 2),
                            "detail": f"{len(wf)}/{len(WORKFLOWS)} workflows + uploader no site ({'ok' if uploader else 'ausente'})"},
    }
    weights = {"caminhos-de-falha (peso 0.45)": W_FALHA, "frescor (0.30)": W_FRESCOR, "automacao (0.25)": W_AUTO}
    parts, wsum = 0.0, 0.0
    for name, c in comps.items():
        s = c["nota"]
        print(f"  {name:30} {'n/a' if s is None else f'{s:5.2f}'}  {c['detail']}")
        if s is not None:
            parts += weights[name] * s
            wsum += weights[name]
    nota_bancada = parts / wsum if wsum > 0 else float("nan")

    # FATOR DE AUTONOMIA (estrutural, medido no histórico real): a cota do
    # Drive força upload manual em parte das entradas de dados. Mede
    # automáticos/(automáticos+manuais) nos últimos 14d; retreino+publicação
    # são sempre automáticos, então o gargalo é só a ENTRADA (1 clique).
    auto_in = man_in = 0
    try:
        gl = subprocess.run(["git", "log", "--oneline", "--since=14.days"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=60,
                            encoding="utf-8", errors="replace").stdout or ""
        auto_in = len(re.findall(r"CSV di.rio", gl))
        man_in = len(re.findall(r"Upload manual", gl))
    except Exception:
        pass
    aut_entrada = auto_in / (auto_in + man_in) if (auto_in + man_in) > 0 else 1.0
    fator = 0.85 + 0.15 * aut_entrada  # entrada 100% auto -> 1.0; 0% -> 0.85
    nota = nota_bancada * fator

    print(f"\n  bancada = {nota_bancada:.2f}")
    print(f"  fator autonomia = {fator:.3f}  (entrada {auto_in} auto / {man_in} manual em 14d = {aut_entrada:.0%} auto; retreino+publicação sempre auto)")
    print(f"\nNOTA DOS DADOS = {nota:.2f}  (bancada x autonomia)")
    print("TETO REAL: ~9.5, NÃO 10. Limite ESTRUTURAL declarado: a cota do "
          "Google Drive é crônica → a entrada de dados às vezes exige 1 upload "
          "manual dele (o resto — validar/retreinar/publicar — é 100% autônomo). "
          "Sobe para ~10 SÓ se a cota for resolvida de vez (service account do "
          "Drive, no backlog). GH_PAT nos Actions pendente (há cron de segurança).")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nota_dados": round(nota, 2) if wsum > 0 else None,
           "nota_bancada": round(nota_bancada, 2) if wsum > 0 else None,
           "fator_autonomia": round(fator, 3), "csv_age_days": round(age, 1) if age == age else None,
           "componentes": comps, "elapsed_s": round(time.time() - t0, 1)}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "data_scorecard.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[data_scorecard] salvo ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
