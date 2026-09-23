# -*- coding: utf-8 -*-
"""GATE: a FORMA real bate a curva normal/Poisson nos totais?

O QUE JA SE SABIA, e esta escrito em mlcore/lines_engine.py:

    "Torres foi REJECT (piora -0.0017: std(z)=0.44 mas formato nao-normal)"

Ou seja: alguem ja mediu que o espalhamento das torres e exagerado (desvio de
z = 0,44, quando o certo e 1) e ja tentou o conserto obvio -- encolher o sd da
normal. PIOROU. A anotacao diz por que: o formato nao e normal.

MEDIDO DE NOVO EM 23/09/2026, e confirmando tudo:

    mercado      desvio de z   o que isso significa
    torres          0,437      espalhamento 129% exagerado
    dragoes         0,551      82% exagerado
    baroes          0,635      57% exagerado
    inibidores      0,651      54% exagerado
    abates          0,900      11% exagerado
    tempo           1,012      certo (ja calibrado em 2026-07-17)

E o formato, medido em 29.178 jogos: torres e uma contagem INTEIRA com piso
(quase nada abaixo de 8), pico em 11-12 e cauda a direita (assimetria 0,58).
Uma normal com sd 4,74 espalha peso de 2 a 21 -- onde nao acontece nada.

A HIPOTESE DESTE GATE e outra, e vem do que funcionou no handicap de abates
em 21/09/2026: nao encolher a normal, e sim TROCAR a normal pela forma
empirica dos residuos. La isso derrubou o erro de 5,3pp para 3,6pp.

Nos Poisson (dragoes/baroes/inibidores) o problema tem outra porta: o Poisson
forca variacao = media. Para dragoes isso da sd 2,13 onde o real e 1,11. O
`prob_over_from_total` la nem usa o campo sd -- usa a media --, entao encolher
o sd nunca teria ajudado. A forma empirica resolve os dois casos de uma vez.

PROTOCOLO -- o MESMO de tools/eval_totals_league_dispersion.py, que foi o gate
que reprovou a tentativa anterior:
  - replay prequencial por season, V0 fiel (build_profile hl=180, MIN_HIST=8);
  - a forma empirica e montada SO com anos anteriores;
  - avaliacao CEGA em 2026, Brier nas linhas padrao;
  - ACCEPT se o ganho passar de 0,0005.

Uso: python tools/eval_totais_forma_empirica.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A barra do gate anterior. Mexer nela seria mudar a regra depois do jogo.
BARRA = 0.0005

# Linhas avaliadas. O gate anterior usava UMA linha por mercado; aqui entram
# tambem as vizinhas, porque a casa oferece varias e e nelas que ele aposta --
# uma forma pode acertar a linha central e errar as laterais.
DESLOCAMENTOS = (-2.0, -1.0, 0.0, 1.0, 2.0)

MERCADOS = [
    ("kills", 27.5, "kills_for", "kills_against"),
    ("towers", 11.5, "towers_for", "towers_against"),
    ("dragons", 4.5, "dragons_for", "dragons_against"),
    ("barons", 1.5, "barons_for", "barons_against"),
    ("inhibitors", 2.5, "inhibitors_for", "inhibitors_against"),
    ("time", 32.5, "game_time_min", None),
]


def forma_empirica(residuos):
    """Os residuos ordenados. Consultar esta lista substitui a curva."""
    z = sorted(float(r) for r in residuos if r == r)
    return z


def prob_acima_empirica(linha, media, forma):
    """P(total > linha) pela forma: a fracao de residuos acima da folga.

    Sem forma devolve None -- cair na normal em silencio seria justamente o
    erro que este gate investiga.
    """
    if not forma:
        return None
    import bisect
    folga = float(linha) - float(media)
    i = bisect.bisect_right(forma, folga)
    return 1.0 - (i / len(forma))


def main() -> int:
    import numpy as np
    import pandas as pd

    from mlcore.lines_engine import prob_over_from_total
    from mlcore.stats_teams import build_team_games, load_team_rows
    from tools.nota_honesta import default_csvs

    # A MAQUINA DE COLETA e a do gate anterior, importada e nao copiada: ela
    # define o que "V0 fiel" quer dizer, e duas versoes disso divergiriam.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "eval_disp", str(ROOT / "tools" / "eval_totals_league_dispersion.py"))
    disp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disp)
    disp.MARKETS = MERCADOS          # mesma coleta, mais mercados

    tg = pd.concat([build_team_games(load_team_rows(str(c))) for c in default_csvs()],
                   ignore_index=True)
    tg["date"] = pd.to_datetime(tg["date"], errors="coerce")
    tg = tg.dropna(subset=["date"])

    # A COLETA leva ~5 minutos (replay de tres temporadas). Fica guardada,
    # porque as variantes comparadas abaixo usam exatamente os mesmos
    # registros -- recoletar para cada uma poria ruido de execucao no lugar
    # da diferenca entre elas.
    import json as _json
    # --servido: a media vem de `_expected_totals_dc`, o caminho da TELA, e
    # nao de `matchup_expected_totals` (V0). Para torres/baroes/inibidores as
    # duas sao iguais; para kills/dragoes/tempo o blend Dixon-Coles muda a
    # media, e a forma tem de ser medida em volta da media que a tela usa.
    servido = "--servido" in sys.argv
    guardado = ROOT / "scratchpad" / ("gate_totais_registros%s.json"
                                      % ("_servido" if servido else ""))
    if servido and not guardado.exists():
        registros = []
        for ano in (2024, 2025, 2026):
            if not (tg["date"].dt.year == ano).any():
                continue
            print("[gate] coletando %d pelo caminho SERVIDO..." % ano, flush=True)
            registros += _coletar_servido(tg, ano)
        print("[gate] %d registros" % len(registros))
        guardado.parent.mkdir(parents=True, exist_ok=True)
        guardado.write_text(_json.dumps(registros), encoding="utf-8")
        for r in registros:
            r["real"] = r["mean"] + r["z"] * r["sd"]
        return _avaliar(registros, disp)
    if guardado.exists():
        registros = _json.loads(guardado.read_text(encoding="utf-8"))
        print("[gate] %d registros reaproveitados de %s" % (len(registros), guardado.name))
        for r in registros:
            r["real"] = r["mean"] + r["z"] * r["sd"]
        return _avaliar(registros, disp)

    registros = []
    for ano in (2024, 2025, 2026):
        if not (tg["date"].dt.year == ano).any():
            continue
        print("[gate] coletando %d..." % ano, flush=True)
        registros += disp.collect_season(tg, ano)
    print("[gate] %d registros" % len(registros))
    guardado.parent.mkdir(parents=True, exist_ok=True)
    guardado.write_text(_json.dumps(registros), encoding="utf-8")

    # O `z` guardado permite recuperar o valor real: real = media + z*sd.
    for r in registros:
        r["real"] = r["mean"] + r["z"] * r["sd"]
    return _avaliar(registros, disp)


def _coletar_servido(tg, season):
    """Igual a `collect_season` do gate anterior, mas com a media DA TELA.

    Copiado e nao importado por um motivo so: la a media sai de
    `matchup_expected_totals(pA, pB)`, e aqui tem de sair de
    `_expected_totals_dc(hist, pA, pB)`, que precisa do historico. O resto --
    corte por dia, MIN_HIST, meia-vida, registro por jogo x mercado -- e o
    mesmo, linha por linha.
    """
    import pandas as pd

    from app_core.runtime_wrappers_core import _expected_totals_dc
    from mlcore.lines_engine import Filters, build_profile

    MIN_HIST, HL = 8, 180.0
    g = tg[(tg["date"].dt.year == season)
           & (tg["team"].astype(str) < tg["opponent"].astype(str))]
    g = g.sort_values("date").reset_index(drop=True)
    flt = Filters()
    out, cache = [], {}
    last_cut, hist = None, None
    for idx, r in enumerate(g.itertuples(index=False)):
        cut = pd.Timestamp(r.date).normalize()
        if last_cut is None or cut != last_cut:
            hist = tg[tg["date"] < cut]
            cache.clear()
            last_cut = cut
        if hist is None or hist.empty:
            continue

        def _prof(team):
            if team not in cache:
                cache[team] = build_profile(hist, team=str(team), filters=flt,
                                            half_life_days=HL)
            return cache[team]

        pA, pB = _prof(str(r.team)), _prof(str(r.opponent))
        if (int(getattr(pA, "n_games", 0)) < MIN_HIST
                or int(getattr(pB, "n_games", 0)) < MIN_HIST):
            continue
        try:
            totals = _expected_totals_dc(hist, pA, pB)
        except Exception:
            continue
        for metric, line, cf, ca in MERCADOS:
            tot = totals.get(metric)
            if (tot is None or not math.isfinite(float(tot.mean))
                    or not math.isfinite(float(tot.sd)) or float(tot.sd) <= 1e-6):
                continue
            try:
                actual = (float(getattr(r, cf)) if ca is None
                          else float(getattr(r, cf)) + float(getattr(r, ca)))
            except (TypeError, ValueError, AttributeError):
                continue
            if not math.isfinite(actual):
                continue
            out.append({"year": season, "metric": metric,
                        "mean": float(tot.mean), "sd": float(tot.sd),
                        "line": float(line), "y": 1 if actual > line else 0,
                        "z": (actual - float(tot.mean)) / float(tot.sd)})
        if (idx + 1) % 1500 == 0:
            print("  %d: %d/%d" % (season, idx + 1, len(g)), flush=True)
    return out


def _avaliar(registros, disp):
    import numpy as np

    from mlcore.lines_engine import MatchupTotals, prob_over_from_total
    # A distribuicao que o motor usa hoje, mercado por mercado.
    DIST = {"kills": "normal", "towers": "normal", "time": "normal",
            "dragons": "poisson", "barons": "poisson", "inhibitors": "poisson"}

    print()
    print("%-12s %8s %10s %10s %10s %10s  %s"
          % ("mercado", "jogos", "hoje", "so largura", "forma", "ganho forma",
             "veredito"))
    resumo = {}
    for metrica, linha_base, _cf, _ca in MERCADOS:
        passado = [r for r in registros if r["metric"] == metrica and r["year"] < 2026]
        cego = [r for r in registros if r["metric"] == metrica and r["year"] == 2026]
        if len(passado) < 1000 or len(cego) < 300:
            print("%-12s  (dados de menos: %d passado, %d cego)"
                  % (metrica, len(passado), len(cego)))
            continue

        forma = forma_empirica([r["real"] - r["mean"] for r in passado])

        # VARIANTE DO MEIO: a normal/Poisson com a LARGURA corrigida, sem
        # mexer no formato. E exatamente o que a tentativa de 2026-07-17
        # fez e viu piorar. Esta aqui para separar as duas causas: se a
        # forma so ganhar por ser mais estreita, esta coluna empata com ela.
        zs = [(r["real"] - r["mean"]) / r["sd"] for r in passado if r["sd"] > 0]
        k = float(np.std(zs, ddof=1)) if len(zs) > 50 else 1.0

        hoje, largura, nova = [], [], []
        for r in cego:
            for d in DESLOCAMENTOS:
                linha = float(linha_base) + d
                y = 1 if r["real"] > linha else 0
                t = MatchupTotals(mean=float(r["mean"]), sd=float(r["sd"]),
                                  dist=DIST[metrica])
                t_larg = MatchupTotals(mean=float(r["mean"]),
                                       sd=max(float(r["sd"]) * k, 1e-6),
                                       dist=DIST[metrica])
                p_hoje = prob_over_from_total(t, linha)
                p_larg = prob_over_from_total(t_larg, linha)
                p_nova = prob_acima_empirica(linha, r["mean"], forma)
                if not (p_hoje == p_hoje) or p_nova is None:
                    continue
                hoje.append((float(p_hoje), y))
                largura.append((float(p_larg), y))
                nova.append((float(p_nova), y))
        if len(hoje) < 500:
            continue
        b_hoje = disp._brier(hoje)
        b_larg = disp._brier(largura)
        b_nova = disp._brier(nova)
        ganho = b_hoje - b_nova
        v = "ACCEPT" if ganho > BARRA else ("REJECT" if ganho < 0 else "neutro")
        resumo[metrica] = (b_hoje, b_larg, b_nova, ganho, v)
        print("%-12s %8d %10.5f %10.5f %10.5f %+10.5f  %s"
              % (metrica, len(hoje), b_hoje, b_larg, b_nova, ganho, v))

    print()
    print("barra do gate: ganho > %.4f (a mesma do gate que reprovou a" % BARRA)
    print("tentativa anterior -- mudar a barra agora seria mudar a regra")
    print("depois do jogo)")
    print()
    print("linhas avaliadas por mercado: a padrao e as vizinhas (%s)"
          % ", ".join("%+.0f" % d for d in DESLOCAMENTOS))
    print()
    print("A COLUNA 'so largura' e a tentativa de 2026-07-17: mesma curva,")
    print("largura corrigida. Se ela ficar perto de 'hoje' e longe de 'forma',")
    print("o ganho vem do FORMATO -- e foi por isso que aquela tentativa")
    print("reprovou.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
