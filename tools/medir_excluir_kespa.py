# -*- coding: utf-8 -*-
"""MEDIÇÃO: treinar SEM o KeSPA Cup melhora a previsão dos jogos sérios?

Achado 24/07 (com ele): o modelo acerta 38,9% no KeSPA Cup (logloss 1,009) vs
66,7% na LCK — é torneio de exibição, times testam roster. Esses 108 jogos de
2026 puxaram o segmento mesma-liga de 9,1 para 8,5.

Pergunta: se o modelo NÃO aprender com KeSPA, ele fica melhor nos jogos que
importam (LCK/LPL/LEC/...)? Avaliação SÓ em jogos sérios nos dois casos, para a
comparação ser justa — excluir do treino não pode ser confundido com excluir da
prova.

Uso: python tools/medir_excluir_kespa.py
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]
EXHIBITION = ("kespa",)  # substring, case-insensitive


def _is_exhibition(league: str) -> bool:
    s = str(league or "").casefold()
    return any(k in s for k in EXHIBITION)


def _fit(csv_paths: list[str], out: Path) -> bool:
    import subprocess
    cmd = [sys.executable, "-m", "mlcore.train_offline", "--out", str(out),
           "--holdout-days", "30", "--no-fit-players"]
    for c in csv_paths:
        cmd += ["--csv", str(c)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print("  [fit] FALHOU:", (r.stderr or "")[-400:])
    return r.returncode == 0


def _eval(artifact: Path, games: pd.DataFrame) -> tuple[float, float, int]:
    from mlcore.artifact import MLArtifact
    art = MLArtifact.load_json(str(artifact))
    tot = acc = 0.0
    n = 0
    for r in games.itertuples(index=False):
        try:
            p = float(art.model.p_blue(str(r.team), str(r.opponent)))
            y = float(r.win)
        except Exception:
            continue
        p = min(max(p, 1e-9), 1 - 1e-9)
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        acc += 1.0 if (p >= 0.5) == (y >= 0.5) else 0.0
        n += 1
    return (tot / n if n else float("nan")), (acc / n if n else float("nan")), n


def main() -> int:
    from mlcore.stats_teams import load_team_rows, build_team_games

    # Avaliação: jogos SÉRIOS de 2026 (lado azul, 1 linha por jogo).
    tg = build_team_games(load_team_rows(str(ROOT / CSVS[2])))
    blue = tg[tg["side"].astype(str).str.lower() == "blue"].copy()
    serious = blue[~blue["league"].map(_is_exhibition)]
    print(f"avaliação: {len(serious)} jogos sérios de 2026 (KeSPA fora da prova nos dois casos)")

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)

        # A) treino COM tudo (como é hoje)
        print("\n[A] treinando COM KeSPA (baseline)... ~10min")
        art_a = td_p / "with.json"
        if not _fit([str(ROOT / c) for c in CSVS], art_a):
            return 1

        # B) treino SEM os jogos de exibição
        print("[B] treinando SEM KeSPA... ~10min")
        csv_b = []
        for c in CSVS:
            fp = ROOT / c
            df = pd.read_csv(fp, low_memory=False)
            if "league" in df.columns:
                keep = ~df["league"].map(_is_exhibition)
                cut = int((~keep).sum())
                df = df[keep]
                print(f"   {fp.name[:24]}: -{cut} linhas de exibição")
            out = td_p / f"b_{fp.name}"
            df.to_csv(out, index=False)
            csv_b.append(str(out))
        art_b = td_p / "without.json"
        if not _fit(csv_b, art_b):
            return 1

        la, aa, na = _eval(art_a, serious)
        lb, ab, nb = _eval(art_b, serious)

    print("\n=== RESULTADO (avaliado só em jogos SÉRIOS) ===")
    print(f"{'treino':16} {'logloss':>9} {'acuracia':>9} {'n':>6}")
    print(f"{'COM KeSPA':16} {la:>9.4f} {100*aa:>8.1f}% {na:>6}")
    print(f"{'SEM KeSPA':16} {lb:>9.4f} {100*ab:>8.1f}% {nb:>6}")
    d = la - lb
    print(f"\nganho de logloss ao excluir: {d:+.4f}  (positivo = SEM KeSPA é melhor)")
    print("veredito:", "ACCEPT — excluir" if d > 0.002 else ("~neutro" if d > -0.002 else "REJECT — manter"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
