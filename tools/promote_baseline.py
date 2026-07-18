from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class StepResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    ok: bool
    started_at_utc: str
    finished_at_utc: str


def _run(name: str, cmd: list[str]) -> StepResult:
    started = datetime.now(timezone.utc).isoformat()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    finished = datetime.now(timezone.utc).isoformat()
    return StepResult(
        name=name,
        command=cmd,
        returncode=int(p.returncode),
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        ok=(int(p.returncode) == 0),
        started_at_utc=started,
        finished_at_utc=finished,
    )


def _snapshot_dir(tag: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return ROOT / "ops" / "baselines" / f"{stamp}_{tag}"


def _write_report(out_dir: Path, report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "promotion_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_checklist(out_dir: Path, overall_ok: bool, steps: list[StepResult]) -> None:
    lines = [
        f"# Checklist de Promocao - {out_dir.name}",
        "",
        "## Pipeline",
    ]
    for s in steps:
        marker = "x" if s.ok else " "
        lines.append(f"- [{marker}] {s.name}")
    lines.extend(
        [
            "",
            "## Status",
            f"- [{'x' if overall_ok else ' '}] Promocao {'aprovada' if overall_ok else 'reprovada'}",
            "",
            "## Evidencias",
            "- [x] promotion_report.json",
            "- [x] manifest.json",
        ]
    )
    (out_dir / "CHECKLIST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one-command baseline promotion pipeline.")
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--artifact", default="ml_artifact.json")
    ap.add_argument("--expectations", default="ops/key_matchup_expectations.json")
    ap.add_argument("--skip-key-gate", action="store_true")
    ap.add_argument(
        "--key-gate-mode",
        choices=["app", "artifact"],
        default="app",
        help="app=semantic gate from final app pipeline; artifact=raw ml_artifact gate.",
    )
    args = ap.parse_args()

    steps: list[StepResult] = []

    commands = [
        (
            "Gerar fixtures de regressao",
            [
                sys.executable,
                "tools/generate_odds_fixtures.py",
                "--artifact",
                args.artifact,
                "--out-small",
                "mlcore/tests/fixtures/odds_regression.json",
                "--out-large",
                "mlcore/tests/fixtures/odds_regression_40.json",
            ],
        ),
        (
            "Compilar arquivos criticos",
            [
                sys.executable,
                "-m",
                "py_compile",
                "plays_app.py",
                "mlcore/elo.py",
                "tools/generate_odds_fixtures.py",
                "tools/create_baseline_snapshot.py",
                "tools/promote_baseline.py",
            ],
        ),
        (
            "Teste regressao ancora",
            [sys.executable, "-m", "unittest", "mlcore.tests.test_odds_regression"],
        ),
        (
            "Teste regressao 40",
            [sys.executable, "-m", "unittest", "mlcore.tests.test_odds_regression_40"],
        ),
        (
            "Teste regressao entreligas",
            [sys.executable, "-m", "unittest", "mlcore.tests.test_interleague_matchups_regression"],
        ),
        (
            "Teste smoke",
            [sys.executable, "-m", "unittest", "mlcore.tests.test_smoke"],
        ),
    ]
    if not bool(args.skip_key_gate):
        if str(args.key_gate_mode) == "artifact":
            commands.append(
                (
                    "Gate confrontos-chave (artifact)",
                    [
                        sys.executable,
                        "tools/validate_key_matchups.py",
                        "--artifact",
                        args.artifact,
                        "--expectations",
                        args.expectations,
                    ],
                )
            )
        else:
            commands.append(
                (
                    "Gate confrontos-chave (app semantico)",
                    [
                        sys.executable,
                        "tools/anchor_regression_suite.py",
                        "--mode",
                        "app",
                        "--expectations",
                        args.expectations,
                        "--out",
                        "anchor_regression_report.promotion.json",
                        "--timeout",
                        "420",
                    ],
                )
            )
    commands.extend(
        [
        (
            "Criar snapshot baseline",
            [sys.executable, "tools/create_baseline_snapshot.py", "--tag", args.tag],
        ),
        ]
    )

    for name, cmd in commands:
        res = _run(name, cmd)
        steps.append(res)
        if not res.ok:
            break

    out_dir = _snapshot_dir(args.tag)
    overall_ok = all(s.ok for s in steps) and len(steps) == len(commands)

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "tag": args.tag,
        "artifact": args.artifact,
        "expectations": args.expectations,
        "skip_key_gate": bool(args.skip_key_gate),
        "key_gate_mode": str(args.key_gate_mode),
        "overall_ok": overall_ok,
        "steps": [
            {
                "name": s.name,
                "ok": s.ok,
                "returncode": s.returncode,
                "command": s.command,
                "started_at_utc": s.started_at_utc,
                "finished_at_utc": s.finished_at_utc,
                "stdout": s.stdout,
                "stderr": s.stderr,
            }
            for s in steps
        ],
    }
    _write_report(out_dir, report)
    _write_checklist(out_dir, overall_ok, steps)

    if overall_ok:
        print(f"[ok] Promocao aprovada: {out_dir}")
        # Promoção aprovada = novo estado BOM => re-pina as bandas das âncoras
        # a partir dele (guarda de deriva; decisão dele 18/07 — as bandas de
        # março apodreceram caladas e passaram a reprovar tudo). Falha do
        # re-pin NÃO derruba a promoção (bandas antigas ficam + alarme de
        # idade do anchor_regression_suite avisa).
        try:
            rp = subprocess.run(
                [sys.executable, "tools/repin_key_matchup_expectations.py"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=3600,
            )
            print(f"[repin] bandas das ancoras: {'ok' if rp.returncode == 0 else 'FALHOU (bandas antigas mantidas)'}")
        except Exception as exc:
            print(f"[repin] FALHOU ({type(exc).__name__}) — bandas antigas mantidas")
        return 0

    print(f"[error] Promocao reprovada: {out_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
