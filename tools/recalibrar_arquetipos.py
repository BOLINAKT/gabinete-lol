# -*- coding: utf-8 -*-
"""RECALIBRAÇÃO dos arquétipos de comp (pedido dele 24/07).

Bug achado: uma comp de engage puro (Malphite/Amumu/Galio/Jinx/Leona) era
classificada como SCALING. Causas na fórmula antiga:
  - Engage PENALIZADO por não ser 'dive' (engage = engage + 0.6*dive + ...);
    engage de CC pesado (≠ dive) afundava.
  - Scaling DEFAULT: carry_scaling + late são altos em toda comp de teamfight.

Aqui: (1) mede normas (média/desvio) de todos os componentes em comps REAIS;
(2) fórmula nova (Engage=engage+frontline+teamfight; Scaling com régua + desconto
de engage; Poke=poke+siege; Split=splitpush+side); (3) valida em comps conhecidas.
Só imprime as constantes pra colar no radar_confronto_core quando os casos óbvios
acertarem.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_core.champion_knowledge_core import load_champion_knowledge_registry  # noqa: E402
from app_core.comp_archetype_core import build_comp_profile  # noqa: E402
from app_core.radar_confronto_core import ROLE_ORDER, norm_position  # noqa: E402
from app_core.players_data_core import load_player_rows  # noqa: E402

CSVS = [
    "CSV_HISTORICO/2024_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_HISTORICO/2025_LoL_esports_match_data_from_OraclesElixir.csv",
    "CSV_DIARIO/2026_LoL_esports_match_data_from_OraclesElixir.csv",
]

# componentes usados na fórmula nova (style, macro, window)
STYLE = ["engage", "frontline", "teamfight", "poke", "siege", "splitpush", "skirmish", "dive", "pick", "peel"]
MACRO = ["carry_scaling", "siege_pressure", "side_pressure", "dive_threat", "tempo_pressure"]
WINDOW = ["early", "mid", "late"]


def _real_comp_profiles(reg, limit=6000):
    prof_cache: dict[tuple, dict] = {}
    profs = []
    seen = 0
    for csv in CSVS:
        fp = ROOT / csv
        if not fp.exists():
            continue
        pdf = load_player_rows(csv_path=str(fp))
        for (gid, team), grp in pdf.groupby(["gameid", "teamname"]):
            pos = {}
            for r in grp.itertuples(index=False):
                p = norm_position(getattr(r, "position", ""))
                c = str(getattr(r, "champion", "") or "").strip()
                if p and c and p not in pos:
                    pos[p] = c
            if len(pos) < 5:
                continue
            picks = tuple(pos[r] for r in ROLE_ORDER)
            if picks not in prof_cache:
                prof_cache[picks] = build_comp_profile(registry=reg, picks=list(picks), role_order=list(ROLE_ORDER))
            profs.append(prof_cache[picks])
            seen += 1
            if seen >= limit:
                return profs
    return profs


def _measure_norms(profs):
    norms = {}
    for grp, keys in (("style_scores", STYLE), ("macro_scores", MACRO), ("window_scores", WINDOW)):
        for k in keys:
            vals = np.array([float((p.get(grp) or {}).get(k, 0.0) or 0.0) for p in profs], dtype=float)
            norms[k] = (float(np.mean(vals)), float(np.std(vals) or 1.0))
    return norms


def _z(prof, grp, k, norms):
    mean, std = norms.get(k, (0.0, 1.0))
    v = float((prof.get(grp) or {}).get(k, 0.0) or 0.0)
    return (v - mean) / (std if std > 1e-9 else 1.0)


def classify_new(prof, norms):
    zS = lambda k: _z(prof, "style_scores", k, norms)   # noqa: E731
    zM = lambda k: _z(prof, "macro_scores", k, norms)   # noqa: E731
    zW = lambda k: _z(prof, "window_scores", k, norms)  # noqa: E731
    scores = {
        # Engage: CC/teamfight (NÃO exige dive). dive/pick entram como bônus leve.
        "Engage": zS("engage") + 0.8 * zS("frontline") + 0.7 * zS("teamfight")
                  + 0.3 * zS("dive") + 0.2 * zM("dive_threat"),
        # Poke/siege
        "Poke": zS("poke") + 0.7 * zS("siege") + 0.4 * zM("siege_pressure"),
        # Scaling: só quando REALMENTE tende ao late — desconta engage/frontline
        # pra comp de teamfight não cair aqui por padrão.
        "Scaling": zW("late") - 0.7 * zW("early") + 0.5 * zM("carry_scaling")
                   - 0.6 * zS("engage") - 0.4 * zS("frontline"),
        # Split-push
        "Split-push": zS("splitpush") + 0.7 * zM("side_pressure") + 0.4 * zS("skirmish"),
    }
    return max(scores, key=lambda k: scores[k]), {k: round(v, 2) for k, v in scores.items()}


# comps conhecidas p/ validar (top jng mid bot sup)
KNOWN = {
    "Engage": [
        ["Malphite", "Amumu", "Galio", "Jinx", "Leona"],
        ["Ornn", "Sejuani", "Orianna", "Kai'Sa", "Rakan"],
    ],
    "Poke": [
        ["Jayce", "Nidalee", "Xerath", "Ezreal", "Karma"],
        ["Kennen", "Nidalee", "Ziggs", "Ezreal", "Lulu"],
    ],
    "Scaling": [
        ["Gnar", "Graves", "Kassadin", "Aphelios", "Yuumi"],
        ["Kayle", "Kindred", "Azir", "Jinx", "Nami"],
    ],
    "Split-push": [
        ["Fiora", "Graves", "Twisted Fate", "Kai'Sa", "Tahm Kench"],
        ["Camille", "Trundle", "Yone", "Ezreal", "Braum"],
    ],
}


def main():
    reg = load_champion_knowledge_registry()
    print("medindo normas em comps reais...")
    profs = _real_comp_profiles(reg)
    print(f"comps reais amostradas: {len(profs)}")
    norms = _measure_norms(profs)

    print("\n=== VALIDAÇÃO em comps conhecidas ===")
    acertos, total = 0, 0
    for esperado, comps in KNOWN.items():
        for picks in comps:
            prof = build_comp_profile(registry=reg, picks=picks, role_order=list(ROLE_ORDER))
            got, sc = classify_new(prof, norms)
            ok = (got == esperado)
            acertos += ok
            total += 1
            print(f"  [{'OK ' if ok else 'ERRO'}] esperado {esperado:11} -> {got:11} {sc}  {picks}")
    print(f"\nacertos: {acertos}/{total}")

    from collections import Counter
    dist = Counter(classify_new(p, norms)[0] for p in profs)
    print("distribuição nas comps reais:", {k: f"{100*v/len(profs):.0f}%" for k, v in dist.most_common()})

    print("\n=== NORMAS (colar em _ARCH_NORMS) ===")
    import json
    print(json.dumps({k: [round(m, 4), round(s, 4)] for k, (m, s) in norms.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
