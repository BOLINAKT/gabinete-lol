"""Atualizar o modelo quando entra CSV novo — um comando, na ordem certa.

Faz, em sequência e à prova de esquecer um passo:
  1) mostra a NOTA atual (antes);
  2) backup do artefato + players (timestamp, *.pre_update_*);
  3) REBUILD do modelo nos CSVs atuais (train_offline, com os defaults validados:
     SOS + dynamic_k + alpha=60 + cap=75 + players via --fit-players; holdout=30);
  4) mostra a NOTA nova (depois);
  5) regenera as fixtures de regressão (re-pina as previsões ao novo artefato);
  6) roda o guard de artefato completo + as regressões (consistência).

Assim a nota fica sempre MEDIDA e consistente: muda só quando os dados/modelo
mudam de propósito, nunca por um passo esquecido. NÃO roda o fit de 6h (esse é
opcional/separado — tools/start_full_fit_resume.ps1).

  python tools/atualizar_modelo.py                 # rebuild + nota + fixtures + testes
  python tools/atualizar_modelo.py --no-tests      # pula a suíte (mais rápido)
  python tools/atualizar_modelo.py --holdout-days 30
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _csvs() -> list[str]:
    out: list[str] = []
    for sub in ("CSV_HISTORICO", "CSV_DIARIO"):
        d = ROOT / sub
        if d.is_dir():
            out.extend(str(p) for p in sorted(d.glob("*.csv")))
    return out


def _run(cmd: list[str], *, title: str) -> int:
    print(f"\n{'=' * 64}\n>> {title}\n{'=' * 64}", flush=True)
    print("  $ " + " ".join(Path(c).name if c.endswith('.py') else c for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def _scorecard(title: str) -> None:
    _run([PY, str(ROOT / "tools" / "ml_fusion_scorecard.py")], title=title)


def main() -> int:
    ap = argparse.ArgumentParser(description="Atualiza o modelo (rebuild + nota + fixtures + testes).")
    ap.add_argument("--holdout-days", type=int, default=30, help="Holdout p/ calibração (deploy validado usa 30).")
    ap.add_argument("--no-tests", action="store_true", help="Pula a suíte de testes no fim.")
    ap.add_argument("--no-regen", action="store_true", help="Não regenera as fixtures de regressão.")
    args = ap.parse_args()

    csvs = _csvs()
    if not csvs:
        print("ERRO: nenhum CSV em CSV_HISTORICO/ ou CSV_DIARIO/.")
        return 2
    print(f"CSVs encontrados ({len(csvs)}):")
    for c in csvs:
        print("  -", Path(c).name)

    art = ROOT / "ml_artifact.json"
    players = ROOT / "players_artifact.json"

    # 1) Nota ANTES (se já há artefato).
    if art.exists():
        _scorecard("NOTA ATUAL (antes do rebuild)")
    else:
        print("\n(sem ml_artifact.json ainda — primeiro build)")

    # 2) Backup.
    ts = time.strftime("%Y%m%d_%H%M%S")
    for f in (art, players):
        if f.exists():
            bak = f.with_suffix(f.suffix + f".pre_update_{ts}")
            bak.write_bytes(f.read_bytes())
            print(f"backup: {f.name} -> {bak.name}")

    # 3) Rebuild (defaults validados; --fit-players já é default ON).
    cmd = [PY, "-m", "mlcore.train_offline", "--out", str(art), "--players-out", str(players),
           "--holdout-days", str(int(args.holdout_days))]
    for c in csvs:
        cmd += ["--csv", c]
    rc = _run(cmd, title="REBUILD do modelo (train_offline)")
    if rc != 0:
        print("\nERRO: rebuild falhou. Artefato antigo preservado (e há backup). Abortando.")
        return rc

    # 4) Nota DEPOIS.
    _scorecard("NOTA NOVA (depois do rebuild)")

    # 5) Regen fixtures.
    if not args.no_regen:
        _run([PY, str(ROOT / "tools" / "update_regression_fixtures.py")], title="Regenerar fixtures de regressão")

    # 6) Testes: guard de artefato completo + regressões (consistência).
    if not args.no_tests:
        rc_t = _run(
            [PY, "-m", "unittest",
             "mlcore.tests.test_live_artifact_complete",
             "mlcore.tests.test_interleague_matchups_regression",
             "mlcore.tests.test_key_matchups_regression",
             "mlcore.tests.test_key_matchups_extended_regression"],
            title="Guard de artefato + testes de regressão",
        )
        if rc_t != 0:
            print("\nATENÇÃO: testes falharam — confira o output acima.")
            return rc_t

    print("\n" + "=" * 64)
    print("OK: modelo atualizado, nota medida e fixtures re-pinadas.")
    print("Compare a NOTA ANTES vs NOTA NOVA acima. Backups em *.pre_update_" + ts)
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
