# -*- coding: utf-8 -*-
"""Retreino COMPLETO dos modelos live (o botão "Retreinar agora" chama isto).

Roda as fases em sequência e atualiza o manifest de frescor UMA vez no fim
(bug 2026-07-05: cada tool treinava mas nenhum atualizava o manifest — o
aviso de envelhecimento nunca sumia):
  6  = estado→vitória (live_models/minute_XX)
  7  = mercados live: kills/torres/dragões/barões/tempo (live_models/markets)
  8  = first-X pré-jogo (live_models/first_markets; quem falha no gate NÃO salva)
  10 = player props (live_models/player_props)

Uso:
  python tools/retrain_live_models_all.py                # todas (6,7,8,10)
  python tools/retrain_live_models_all.py --phases 7,8,10
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASES: dict[str, tuple[str, str, str]] = {
    # fase -> (script, subdir de modelos, arquivo de report)
    "6": ("tools/run_phase6_live_gate.py", "", "FASE6_LIVE.json"),
    "7": ("tools/run_phase7_markets_gate.py", "markets", "FASE7_MARKETS.json"),
    "8": ("tools/run_phase8_first_markets_gate.py", "first_markets", "FASE8_FIRST_MARKETS.json"),
    "10": ("tools/run_phase10_player_props_gate.py", "player_props", "FASE10_PLAYER_PROPS.json"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-cutoff", default="2026-03-31")
    ap.add_argument("--models-root", default="live_models")
    ap.add_argument("--n-bootstrap", default="500")
    ap.add_argument("--phases", default="6,7,8,10")
    args = ap.parse_args()

    root = Path(args.models_root)
    wanted = [p.strip() for p in str(args.phases).split(",") if p.strip() in PHASES]
    results: dict[str, int] = {}
    for phase in wanted:
        script, subdir, report = PHASES[phase]
        save_dir = str(root / subdir) if subdir else str(root)
        cmd = [sys.executable, str(ROOT / script),
               "--val-cutoff", str(args.val_cutoff),
               "--save-models-dir", save_dir,
               "--output", report,
               "--n-bootstrap", str(args.n_bootstrap)]
        print(f"\n{'=' * 72}\n[retrain_all] FASE {phase}: {script} -> {save_dir}\n{'=' * 72}", flush=True)
        rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
        results[phase] = rc
        print(f"[retrain_all] FASE {phase} terminou com rc={rc}", flush=True)

    # Manifest de frescor: uma atualização cobrindo tudo.
    try:
        from app_core.live_models_status_core import update_manifest_after_training
        csvs = [str(p) for d in ("CSV_HISTORICO", "CSV_DIARIO")
                for p in sorted((ROOT / d).glob("*.csv"))]
        update_manifest_after_training(
            str(root), csvs,
            extra={"last_gate": {"phases": {p: ("ok" if rc == 0 else f"rc={rc}")
                                            for p, rc in results.items()}}},
        )
        print(f"[retrain_all] manifest atualizado em {root}/manifest.json", flush=True)
    except Exception as exc:
        print(f"[retrain_all] AVISO: manifest não atualizado: {exc}", flush=True)

    return 0 if all(rc == 0 for rc in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
