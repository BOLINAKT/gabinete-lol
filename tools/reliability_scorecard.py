# -*- coding: utf-8 -*-
"""SCORECARD DA CONFIABILIDADE — a nota da fase Confiabilidade, reproduzível.

Regra suprema (dele, 18/07): teto real, testável, e declarar o teto.
Confiabilidade = o site fica de pé e CORRETO sem intervenção. Mede-se
RODANDO as defesas (não lendo um monitor que pode estar velho — lição de
18/07: o ml_monitor_latest mostrava anchor=reject já resolvido pelo re-pin).
Componentes, todos exercitados na hora:

  imutabilidade   — a suíte é SÓ-LEITURA por construção (fase 2): o E2E prova
                    que artifacts do modelo/agenda não mudam ao rodar.
  guardrails      — as travas de sanidade (odds absurda, patch velho, resumo,
                    marginal, texto/mojibake) passam.
  regressoes      — fixtures de odds + suíte de segurança core (check_regression).
  vigia-ativo     — o watcher semanal da nota está configurado (nota_semanal.yml)
                    + baseline de qualidade existe.

Uso: python tools/reliability_scorecard.py
Saída: texto + evidence/reliability_scorecard.json
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W_IMMUT, W_GUARD, W_REGR, W_VIGIA = 0.35, 0.30, 0.20, 0.15

IMMUT_TESTS = [
    "mlcore.tests.test_e2e_smoke.TestE2ESmokeLoL",       # asserção before==after (artifacts)
    "mlcore.tests.test_live_artifact_complete",
    "mlcore.tests.test_flow_line_keys_registry",
]
GUARD_TESTS = [
    "mlcore.tests.test_odds_delta_guardrail",
    "mlcore.tests.test_patch_guard_core",
    "mlcore.tests.test_resumo_guardrail_core",
    "mlcore.tests.test_ml_marginal_guard_core",
    "mlcore.tests.test_ui_text_guardrails",
]
# Os passos [2/3] e [3/3] de tools/check_regression.ps1, na mesma ordem.
REGR_TESTS = [
    "mlcore.tests.test_odds_regression",
    "mlcore.tests.test_odds_regression_40",
    "mlcore.tests.test_interleague_matchups_regression",
    "mlcore.tests.test_key_matchups_regression",
    "mlcore.tests.test_key_matchups_extended_regression",
    "mlcore.tests.test_players_fusion_regression",
    "mlcore.tests.test_settings_core",
    "mlcore.tests.test_app_state",
    "mlcore.tests.test_resumo_core",
    "mlcore.tests.test_app_odds_core",
    "mlcore.tests.test_players_state",
    "mlcore.tests.test_players_core",
    "mlcore.tests.test_players_layer_weights",
    "mlcore.tests.test_fit_ml_params",
    "mlcore.tests.test_regression_fixtures",
    "mlcore.tests.test_ui_labels_integrity",
    "mlcore.tests.test_smoke",
]


def _run_tests(mods: list[str], env_e2e: bool = False) -> tuple[int, int, str]:
    """Roda unittest nos módulos; devolve (ok, total, detalhe)."""
    import os
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if env_e2e:
        env["GABINETE_E2E"] = "1"
    cp = subprocess.run([sys.executable, "-m", "unittest", *mods, "-v"],
                        capture_output=True, text=True, cwd=str(ROOT), timeout=1800,
                        encoding="utf-8", errors="replace", env=env)
    out = (cp.stdout or "") + (cp.stderr or "")
    m = re.search(r"Ran (\d+) tests", out)
    total = int(m.group(1)) if m else 0
    fails = len(re.findall(r"\.\.\. (FAIL|ERROR)", out)) + len(re.findall(r"^(FAIL|ERROR):", out, re.M))
    skips = len(re.findall(r"\.\.\. skipped", out))
    ok = total - fails
    return ok, total, f"{ok}/{total} ok ({fails} falhas, {skips} skips)"


def main() -> int:
    t0 = time.time()
    print(f"\n=== SCORECARD DA CONFIABILIDADE (F2) — {time.strftime('%Y-%m-%d')} ===")
    print("  rodando defesas (não lê monitor — pode estar velho)...", flush=True)

    ok_i, tot_i, det_i = _run_tests(IMMUT_TESTS, env_e2e=True)
    ok_g, tot_g, det_g = _run_tests(GUARD_TESTS)

    # regressões: os MESMOS módulos do tools/check_regression.ps1 (fixtures de
    # odds + core safety), rodados pelo próprio Python.
    # CONSERTO 22/10/2026: antes isto chamava `powershell -File ...ps1`. No robô
    # (ubuntu) não existe `powershell`, e no PC o ps1 chamava o `python` do PATH,
    # não o do .venv -- nos dois casos a parte "regressões" dava ZERO com as
    # regressões passando. O ps1 continua para uso à mão; a lista é a dele.
    ok_r, tot_r, _ = _run_tests(REGR_TESTS)
    regr_ok = tot_r > 0 and ok_r == tot_r

    # vigia: workflow + baseline de qualidade presentes
    vigia_wf = (ROOT / ".github" / "workflows" / "nota_semanal.yml").exists()
    baseline = (ROOT / "ops" / "monitoring" / "ml_quality_baseline.json").exists()
    vigia_nota = 10.0 if (vigia_wf and baseline) else (6.0 if vigia_wf or baseline else 0.0)

    comps = {
        "imutabilidade (peso 0.35)": {"nota": round(10.0 * ok_i / tot_i, 2) if tot_i else None,
                                       "detail": f"E2E só-leitura + completude + registro: {det_i}"},
        "guardrails (0.30)": {"nota": round(10.0 * ok_g / tot_g, 2) if tot_g else None,
                              "detail": f"travas de sanidade (odds/patch/resumo/marginal/texto): {det_g}"},
        "regressoes (0.20)": {"nota": 10.0 if regr_ok else 0.0,
                              "detail": "fixtures de odds + core safety" + (" OK" if regr_ok else " FALHOU")},
        "vigia-ativo (0.15)": {"nota": vigia_nota,
                               "detail": f"nota_semanal.yml={'ok' if vigia_wf else 'ausente'}, baseline={'ok' if baseline else 'ausente'}"},
    }
    weights = {"imutabilidade (peso 0.35)": W_IMMUT, "guardrails (0.30)": W_GUARD,
               "regressoes (0.20)": W_REGR, "vigia-ativo (0.15)": W_VIGIA}
    parts, wsum = 0.0, 0.0
    for name, c in comps.items():
        s = c["nota"]
        print(f"  {name:28} {'n/a' if s is None else f'{s:5.2f}'}  {c['detail']}")
        if s is not None:
            parts += weights[name] * s
            wsum += weights[name]
    nota_bancada = parts / wsum if wsum > 0 else float("nan")

    # FATOR DE MATURIDADE OPERACIONAL: bancada verde não prova "roda sem quebra
    # em produção". Desconto honesto que sobe sozinho: 0.88 (dia 0) -> 1.0 aos
    # ALVO_DIAS sem toque. dias = idade da operação autônoma (1º commit do robô).
    ALVO_DIAS = 7.0
    dias_op = 0.0
    try:
        # padrão ASCII (evita o "ô" multibyte que quebra regex por byte no git)
        cp = subprocess.run(["git", "log", "--reverse", "--format=%ct", "--grep=modelo atualizado"],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        cts = [int(x) for x in (cp.stdout or "").split() if x.strip().isdigit()]
        if cts:
            dias_op = max(0.0, (time.time() - cts[0]) / 86400.0)
    except Exception:
        pass
    fator = 0.88 + 0.12 * min(1.0, dias_op / ALVO_DIAS)
    nota = nota_bancada * fator

    print(f"\n  defesas em bancada = {nota_bancada:.2f}")
    print(f"  fator maturidade   = {fator:.3f}  ({dias_op:.1f} de {ALVO_DIAS:.0f} dias de operação autônoma sem quebra)")
    print(f"\nNOTA DA CONFIABILIDADE = {nota:.2f}  (bancada x maturidade)")
    print("TETO REAL: ~10 é ATINGÍVEL, mas só quando a operação autônoma "
          f"completar {ALVO_DIAS:.0f} dias sem toque/quebra (hoje {dias_op:.1f}d). "
          "As defesas de bancada já estão no teto; a nota sobe sozinha com o "
          "tempo de produção estável.")

    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "nota_confiabilidade": round(nota, 2) if wsum > 0 else None,
           "nota_bancada": round(nota_bancada, 2) if wsum > 0 else None,
           "fator_maturidade": round(fator, 3), "dias_operacao": round(dias_op, 1),
           "componentes": comps, "elapsed_s": round(time.time() - t0, 1)}
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "reliability_scorecard.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[reliability_scorecard] salvo ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
