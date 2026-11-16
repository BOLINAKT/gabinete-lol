# -*- coding: utf-8 -*-
"""WHR com MARGEM DE VITORIA (resultado fracionario) — prova cega.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ POR QUE ESTE ARQUIVO EXISTE: o motor de producao e o WHR, e ele so enxerga  ║
║ "ganhou/perdeu". Um atropelo de 20 min conta igual a uma virada no baron.   ║
║ O MOVDA existe em mlcore/elo.py mas ficou ORFAO quando o WHR substituiu o   ║
║ Elo: whr_core.py nao tem por onde receber margem. A validacao que aprovou   ║
║ o WHR (evidence/eval_whr_2026.log) comparou WHR SEM margem contra Elo COM   ║
║ margem — trocou duas coisas de uma vez, e nao diz nada sobre WHR COM.       ║
║                                                                             ║
║ 1. A FORMA CERTA PARA UM MODELO BRADLEY-TERRY: resultado FRACIONARIO, nao   ║
║    empurrao no rating. O WHR resolve um MAP por Newton; somar um termo      ║
║    fora da verossimilhanca desalinha gradiente e Hessiana e o ponto fixo    ║
║    deixa de ser o modo de coisa nenhuma. Trocar y ∈ {0,1} por ỹ ∈ [0,1]     ║
║    mantem gradiente (ỹ − p) e Hessiana −p(1−p) EXATAMENTE como estao.       ║
║    Vitorias fracionarias sao pratica estabelecida em Bradley-Terry: no      ║
║    hoquei universitario a vitoria na prorrogacao vale 1/3 de vitoria.       ║
║    https://arxiv.org/abs/2112.01267  (aberta em 08/09/2026)                 ║
║    E e o que o artigo canonico de margem faz: "a magnitude do MOV e         ║
║    comprimida num valor entre 0 e 1, de modo que os ratings refletem o MOV  ║
║    mas continuam ancorados no resultado real" — Kovalchik (2020),           ║
║    "Extension of the Elo rating system to margin of victory", Int. J.       ║
║    Forecasting. https://www.sciencedirect.com/science/article/abs/pii/S0169207020300157
║    ATENCAO: a ScienceDirect devolve 403; eu NAO abri o artigo. A frase      ║
║    acima vem de resumo de busca, nao da fonte primaria. Tratar como indicio.║
║                                                                             ║
║ 2. A MARGEM TEM QUE SER RELATIVA A EXPECTATIVA, nao crua. Margem crua       ║
║    confunde "dominou porque e muito melhor" (ja esta no rating) com         ║
║    "dominou acima do que se esperava" (informacao nova). O MOVDA resolve    ║
║    com E[MOV|ΔR] = α·tanh(β·ΔR) + γ, e a tanh satura — o que tambem trata   ║
║    o problema do placar inflado no fim do jogo (garbage time).              ║
║    https://arxiv.org/html/2506.00348  (aberta em 08/09/2026)                ║
║    Numeros do artigo, 13.619 jogos NBA: Brier 0,2274 (Elo) -> 0,2258;       ║
║    acerto 62,77% -> 63,32%; convergencia 193 -> 166 jogos.                  ║
║    EXPECTATIVA CALIBRADA: o ganho la e da ORDEM DA NOSSA BARRA (0,002).     ║
║    E o maior beneficio deles — convergir mais rapido — e vantagem sobre     ║
║    Elo INCREMENTAL; o WHR reajusta a historia inteira e ja converge rapido  ║
║    por construcao. Essa ultima frase e INFERENCIA MINHA, nao do artigo.     ║
║                                                                             ║
║ 3. G-Elo (arXiv 2010.11187, aberta em 08/09/2026) faz o mesmo por outro     ║
║    caminho: discretiza o MOV em categorias ordinais e reescreve o score.    ║
║    Ganhos ~0,5-1% (Premier League) e ~3% (NFL). Preferi o continuo por ter  ║
║    menos parametros e por cair EXATAMENTE em producao quando lam=0.         ║
║                                                                             ║
║ 4. AVISO QUE A PESQUISA DEU E QUE MUDA O PROTOCOLO: ao mexer na escala do   ║
║    sinal, "a escala efetiva precisa ser reajustada para dar conta do ruido" ║
║    — por isso o w2 e RE-TUNADO para cada variante, e nao herdado. Comparar  ║
║    baseline tunado contra candidato nao-tunado seria injusto com o          ║
║    candidato.                                                               ║
║                                                                             ║
║ 5. NAO ACHEI NENHUMA literatura sobre margem em rating de LoL profissional  ║
║    (buscas em 08/09/2026). Ou seja: qual sinal de margem usar NAO tem       ║
║    resposta na literatura e TEM que ser medido. Por isso --mov e um grid.   ║
╚═════════════════════════════════════════════════════════════════════════════╝

PROTOCOLO (o mesmo de tools/eval_whr.py, para os numeros serem comparaveis):
  1) E[MOV|Δr] ajustado SO nos anos de treino, com o Δr do proprio WHR.
  2) (w2, lam) tunados prequencialmente no ano ANTERIOR ao cego.
  3) EVAL prequencial no ano cego: pontua ANTES de adicionar o jogo.
  4) Baseline = lam=0, que e BIT A BIT o WHR de producao.
  5) IC por bootstrap pareado na diferenca de logloss.

Uso:
  python tools/eval_whr_mov.py --oos-year 2026 --mov gd15
  python tools/eval_whr_mov.py --oos-year 2026 --mov todos
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.eval_interleague_levers import load_games, sos_points_from_train  # noqa: E402
from tools.ml_quality_scorecard import default_csvs  # noqa: E402

NAT = math.log(10.0) / 400.0
SIGMA0_ELO = 350.0
MAX_STEP = 1.0

# ---------------------------------------------------------------- sinais de margem
# Cada um devolve a margem NA PERSPECTIVA DE `r.team` (o "blue" da linha).
# `None` = indisponivel nesse jogo -> aquele jogo cai para o y binario puro.


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _mov_kills(r):
    a, b = _num(getattr(r, "kills_for", None)), _num(getattr(r, "kills_against", None))
    return None if a is None or b is None else a - b


def _mov_gold(r):
    a, b = _num(getattr(r, "gold_for", None)), _num(getattr(r, "gold_against", None))
    return None if a is None or b is None else a - b


def _mov_goldpm(r):
    """Ouro por MINUTO. Sem isso, jogo longo acumula margem so por ser longo."""
    d = _mov_gold(r)
    t = _num(getattr(r, "game_time_min", None))
    return None if d is None or t is None or t <= 1.0 else d / t


def _mov_gd15(r):
    """Ouro aos 15 min: ANTES da bola de neve, entao mede qualidade e nao inercia."""
    return _num(getattr(r, "golddiffat15_for", None))


def _mov_towers(r):
    a, b = _num(getattr(r, "towers_for", None)), _num(getattr(r, "towers_against", None))
    return None if a is None or b is None else a - b


# ---- candidatos acrescentados em 15/09/2026 ----
# Ele perguntou se ha ganho a extrair do que JA existe no CSV, antes de sair
# coletando dado novo. Medido na base inteira (28.964 jogos), a correlacao de
# cada um com a vitoria:
#     ouro@10 0,439 | ouro@15 0,531 | ouro@20 0,616
#     xp@10   0,404 | xp@15   0,504 | xp@20   0,590
#     cs@10   0,366 | cs@15   0,453 | cs@20   0,507
#
# CORRELACAO ALTA AQUI E ARMADILHA: aos 20 minutos o jogo ja esta decidido, e
# o "sinal" vira quase o proprio resultado — mede inercia, nao qualidade. O
# gd15 foi escolhido justamente por ficar antes da bola de neve. Medir gd10 e
# gd20 mostra o formato dessa curva em vez de deixa-la no argumento.


def _mov_gd10(r):
    """Ouro aos 10: ainda menos contaminado que os 15 — e com menos sinal."""
    return _num(getattr(r, "golddiffat10_for", None))


def _mov_gd20(r):
    """Ouro aos 20: correlacao maior com o resultado, e por isso suspeito."""
    return _num(getattr(r, "golddiffat20_for", None))


def _mov_xpd15(r):
    return _num(getattr(r, "xpdiffat15_for", None))


def _mov_csd15(r):
    return _num(getattr(r, "csdiffat15_for", None))


def _mov_dom15(r):
    """Ouro + XP + CS aos 15, com as escalas equalizadas pelo desvio medido.

    Os pesos NAO sao chutados: saem da razao entre os desvios na base inteira
    (ouro/xp = 1,32; ouro/cs = 68,9), para os tres entrarem com a mesma voz.
    Sem isso o ouro dominaria a soma por ser o numero maior.

    EXPECTATIVA HONESTA, escrita antes de medir: ouro e XP aos 15 correlacionam
    0,875 entre si — medem quase a mesma coisa. Pela licao do fatorial deste
    projeto, componentes assim se canibalizam, e o composto deve render pouco
    ou nada acima do gd15 sozinho. Se render, o interessante e por que.
    """
    g = _num(getattr(r, "golddiffat15_for", None))
    x = _num(getattr(r, "xpdiffat15_for", None))
    c = _num(getattr(r, "csdiffat15_for", None))
    if g is None or x is None or c is None:
        return None
    return g + 1.32 * x + 68.9 * c


SINAIS = {
    "kills": _mov_kills,      # o que o MOVDA orfao usava
    "gold": _mov_gold,
    "goldpm": _mov_goldpm,
    "gd15": _mov_gd15,
    "towers": _mov_towers,
    "gd10": _mov_gd10,
    "gd20": _mov_gd20,
    "xpd15": _mov_xpd15,
    "csd15": _mov_csd15,
    "dom15": _mov_dom15,
}


# ---------------------------------------------------------------- WHR com ỹ
def _solve_tridiag(diag: np.ndarray, off: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    n = len(diag)
    if n == 1:
        return rhs / diag
    for i in range(1, n):
        m = off[i - 1] / diag[i - 1]
        diag[i] -= m * off[i - 1]
        rhs[i] -= m * rhs[i - 1]
    x = np.zeros(n)
    x[-1] = rhs[-1] / diag[-1]
    for i in range(n - 2, -1, -1):
        x[i] = (rhs[i] - off[i] * x[i + 1]) / diag[i]
    return x


class WHRMov:
    """WHR de tools/eval_whr.py, com UMA diferenca: o resultado guardado na
    verossimilhanca e ỹ ∈ [0,1] em vez de y ∈ {0,1}. Com lam=0, ỹ == y e esta
    classe e bit a bit a de producao."""

    def __init__(self, w2_elo_per_day: float, league_prior_elo: dict):
        self.w2 = float(w2_elo_per_day) * NAT * NAT
        self.prior_mu = {k: float(v) * NAT for k, v in league_prior_elo.items()}
        self.days: dict[str, list[int]] = {}
        self.r: dict[str, np.ndarray] = {}
        self.mu0: dict[str, float] = {}
        self.games: dict[str, list[tuple]] = {}

    def _ensure_point(self, team: str, day: int, league: str) -> int:
        if team not in self.days:
            self.days[team] = [day]
            self.r[team] = np.array([self.prior_mu.get(league, 0.0)], dtype=float)
            self.mu0[team] = self.prior_mu.get(league, 0.0)
            self.games[team] = []
            return 0
        ds = self.days[team]
        if day > ds[-1]:
            ds.append(day)
            self.r[team] = np.append(self.r[team], self.r[team][-1])
            return len(ds) - 1
        return len(ds) - 1

    def rating_last(self, team: str):
        arr = self.r.get(team)
        return float(arr[-1]) if arr is not None and len(arr) else None

    def delta_nat(self, a: str, b: str, la: str, lb: str) -> float:
        ra = self.rating_last(a)
        rb = self.rating_last(b)
        if ra is None:
            ra = self.prior_mu.get(la, 0.0)
        if rb is None:
            rb = self.prior_mu.get(lb, 0.0)
        return ra - rb

    def p_win(self, a: str, b: str, la: str, lb: str) -> float:
        return 1.0 / (1.0 + math.exp(-self.delta_nat(a, b, la, lb)))

    def add_game(self, a: str, b: str, y_frac: float, day: int, la: str, lb: str) -> None:
        """y_frac = ỹ na perspectiva de `a`. O oponente recebe 1-ỹ, o que garante
        a simetria por construcao (e nao por uma segunda conta que pode divergir)."""
        ia = self._ensure_point(a, day, la)
        ib = self._ensure_point(b, day, lb)
        yf = min(max(float(y_frac), 0.0), 1.0)
        self.games[a].append((ia, b, ib, yf))
        self.games[b].append((ib, a, ia, 1.0 - yf))

    def refresh_team(self, team: str, iters: int = 2) -> None:
        ds = self.days.get(team)
        if not ds:
            return
        n = len(ds)
        r = self.r[team]
        s0 = (SIGMA0_ELO * NAT) ** 2
        for _ in range(int(iters)):
            grad = np.zeros(n)
            diag = np.zeros(n)
            off = np.zeros(max(n - 1, 0))
            grad[0] += -(r[0] - self.mu0[team]) / s0
            diag[0] += -1.0 / s0
            for i in range(n - 1):
                var = self.w2 * max(ds[i + 1] - ds[i], 1)
                d = (r[i + 1] - r[i]) / var
                grad[i] += d
                grad[i + 1] -= d
                diag[i] -= 1.0 / var
                diag[i + 1] -= 1.0 / var
                off[i] += 1.0 / var
            for (idx, opp, oidx, yf) in self.games[team]:
                ro = self.r[opp][min(oidx, len(self.r[opp]) - 1)]
                p = 1.0 / (1.0 + math.exp(-(r[idx] - ro)))
                # A UNICA linha que muda em relacao ao WHR de producao: yf no
                # lugar de y. A Hessiana NAO depende do resultado, entao segue
                # exata — e por isso o Newton continua valido.
                grad[idx] += (yf - p)
                diag[idx] -= p * (1.0 - p)
            dx = _solve_tridiag(diag.copy(), off.copy(), -grad)
            np.clip(dx, -MAX_STEP, MAX_STEP, out=dx)
            r += dx
        self.r[team] = r


# ---------------------------------------------------------------- E[MOV | Δr]
def fit_expected_mov(g, *, ate_ano: int, league_points: dict, w2: float,
                     mov_fn) -> dict:
    """Passada 1: WHR SEM margem nos anos < ate_ano, coletando (Δr, MOV).
    Ajusta E[MOV|Δr] = a*tanh(b*Δr) + c por minimos quadrados, com grid em b.

    Δr aqui e o do PROPRIO WHR (em unidades naturais), nao o do Elo — a
    expectativa tem que ser a expectativa DESTE modelo, senao o residuo
    carrega o vies do outro."""
    whr = WHRMov(w2, league_points)
    xs: list[float] = []
    ys: list[float] = []
    n_sem = 0
    for r in g.itertuples(index=False):
        if int(r.yr) >= int(ate_ano):
            break
        bl, rl = r.dl, r.ol
        dr = whr.delta_nat(str(r.team), str(r.opponent), bl or "", rl or "")
        mov = mov_fn(r)
        if mov is None:
            n_sem += 1
        else:
            xs.append(dr)
            ys.append(float(mov))
        day = int(r.date.toordinal())
        whr.add_game(str(r.team), str(r.opponent), float(int(r.win)), day, bl or "", rl or "")
        whr.refresh_team(str(r.team), iters=2)
        whr.refresh_team(str(r.opponent), iters=2)

    if len(xs) < 200:
        raise SystemExit(f"[mov] amostra insuficiente para ajustar E[MOV]: n={len(xs)}")

    X = np.asarray(xs, dtype=float)
    Y = np.asarray(ys, dtype=float)
    melhor = None
    for b in (0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
        T = np.tanh(b * X)
        A = np.column_stack([T, np.ones_like(T)])
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        resid = Y - A @ coef
        sse = float(resid @ resid)
        if melhor is None or sse < melhor["sse"]:
            melhor = {"a": float(coef[0]), "b": float(b), "c": float(coef[1]),
                      "sse": sse, "s": float(resid.std(ddof=2)), "n": len(X)}
    melhor["n_sem_mov"] = n_sem
    return melhor


# ---------------------------------------------------------------- replay
def run(g, *, score_year: int, league_points: dict, w2: float, lam: float,
        mov_fn, fit: dict, folga: float = 0.0, full_every: int = 400) -> dict:
    """Replay prequencial. Pontua os jogos de score_year ANTES de adiciona-los.
    A pontuacao usa SEMPRE o y binario de verdade — a margem entra so no
    aprendizado, nunca na nota."""
    whr = WHRMov(w2, league_points)
    a_m, b_m, c_m, s_m = fit["a"], fit["b"], fit["c"], max(fit["s"], 1e-9)
    seg_acc = {"inter": [0.0, 0, 0], "same": [0.0, 0, 0]}
    perdas: list[float] = []       # para o bootstrap pareado
    yfs: list[float] = []          # distribuicao de ỹ, para diagnostico
    ys: list[float] = []           # o y binario, PAREADO com yfs
    chaves: list[tuple] = []       # (mes, liga) de cada jogo PONTUADO
    n_sem_mov = 0
    count = 0
    for r in g.itertuples(index=False):
        if int(r.yr) > int(score_year):
            break
        bl, rl = r.dl, r.ol
        dr = whr.delta_nat(str(r.team), str(r.opponent), bl or "", rl or "")
        if bl and rl and int(r.yr) == int(score_year):
            p = 1.0 / (1.0 + math.exp(-dr))
            pc = min(max(p, 1e-6), 1 - 1e-6)
            y = int(r.win)
            ll = -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
            seg = "inter" if bl != rl else "same"
            seg_acc[seg][0] += ll
            seg_acc[seg][1] += 1
            seg_acc[seg][2] += 1 if ((p >= 0.5) == (y == 1)) else 0
            perdas.append(ll)
            # Guardado para o recorte: um ganho concentrado em um mes ou em uma
            # liga so nao e um ganho, e um acidente. Ver quebra_por().
            chaves.append((f"{r.date.year}-{r.date.month:02d}", str(bl or "?")))

        y = float(int(r.win))
        # FOLGA (o "headroom" do G-Elo): a vitoria normal nao vale 1, vale 1-folga.
        # Sem isso, o teto de 1 come metade da informacao — medido em 08/09/2026:
        # com folga=0, 72,5% dos jogos ficavam no batente, e o modelo so conseguia
        # DESCONTAR de quem ganhou mal, nunca PREMIAR quem ganhou dominando.
        base = folga + y * (1.0 - 2.0 * folga)
        yf = base
        if lam != 0.0:
            mov = mov_fn(r)
            if mov is None:
                n_sem_mov += 1
            else:
                esperado = a_m * math.tanh(b_m * dr) + c_m
                yf = min(max(base + lam * (mov - esperado) / s_m, 0.0), 1.0)
        yfs.append(yf)
        ys.append(y)

        day = int(r.date.toordinal())
        whr.add_game(str(r.team), str(r.opponent), yf, day, bl or "", rl or "")
        whr.refresh_team(str(r.team), iters=2)
        whr.refresh_team(str(r.opponent), iters=2)
        count += 1
        if count % int(full_every) == 0:
            for t in whr.days:
                whr.refresh_team(t, iters=1)

    out = {"perdas": perdas, "n_sem_mov": n_sem_mov, "chaves": chaves}
    for seg, (ll, n, hits) in seg_acc.items():
        out[seg] = {"logloss": ll / n if n else float("nan"), "n": n,
                    "acc": hits / n if n else float("nan")}
    tot_n = out["same"]["n"] + out["inter"]["n"]
    out["geral"] = {
        "logloss": (out["same"]["logloss"] * out["same"]["n"]
                    + out["inter"]["logloss"] * out["inter"]["n"]) / max(tot_n, 1),
        "n": tot_n,
        "acc": (out["same"]["acc"] * out["same"]["n"]
                + out["inter"]["acc"] * out["inter"]["n"]) / max(tot_n, 1),
    }
    # Diagnostico do resultado fracionario. O numero que importa e "cruzou":
    # quantas vezes a margem foi tao contraria a expectativa que o resultado
    # fracionario DISCORDA de quem realmente ganhou. Isso e agressivo — um time
    # que venceu passa a contar como derrota parcial — e precisa ficar a vista,
    # nao escondido dentro de um lam que so o logloss justifica.
    yfa = np.asarray(yfs, dtype=float)
    ya = np.asarray(ys, dtype=float)
    cruzou = ((ya >= 0.5) & (yfa < 0.5)) | ((ya < 0.5) & (yfa > 0.5))
    grudou = (yfa <= 0.0) | (yfa >= 1.0)
    out["yf"] = {
        "min": float(yfa.min()), "max": float(yfa.max()),
        "frac_cruzou": float(cruzou.mean()),
        "frac_no_batente": float(grudou.mean()),
        "ajuste_medio_abs": float(np.abs(yfa - ya).mean()),
    }
    return out


def bootstrap_pareado(a: list[float], b: list[float], n_rep: int = 2000,
                      semente: int = 20260908) -> tuple[float, float, float]:
    """IC 95% da diferenca media (a - b) por bootstrap pareado.
    a = perdas do baseline, b = perdas do candidato -> positivo = candidato melhor."""
    if len(a) != len(b) or not a:
        return (float("nan"),) * 3
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, len(d), size=(int(n_rep), len(d)))
    medias = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))


def quebra_por(base: dict, cand: dict, idx: int, titulo: str, min_n: int = 60) -> None:
    """Ganho recortado por mes (idx=0) ou por liga (idx=1).

    POR QUE ISTO EXISTE: um IC apertado num ano so diz que o ganho nao e ruido
    DENTRO daquele ano — nao diz que ele e estavel. Se o ganho inteiro vier de
    um mes, ou de uma liga, e coincidencia com cara de descoberta. O teste util
    e ver o SINAL em cada recorte, nao o tamanho."""
    from collections import defaultdict
    d = defaultdict(lambda: [0.0, 0])
    for (ch, b, c) in zip(cand["chaves"], base["perdas"], cand["perdas"]):
        k = ch[idx]
        d[k][0] += (b - c)
        d[k][1] += 1
    linhas = [(k, v[0] / v[1], v[1]) for k, v in d.items() if v[1] >= min_n]
    if not linhas:
        return
    linhas.sort(key=lambda t: -t[2])
    pos = sum(1 for _, g, _ in linhas if g > 0)
    print(f"\n[mov] {titulo} ({len(linhas)} recortes com n>={min_n}): "
          f"{pos} com ganho, {len(linhas)-pos} com perda")
    for k, g, n in linhas[:14]:
        marca = "ok " if g > 0 else "PIOROU"
        print(f"        {k:<16} n={n:>5}  dif {g:>+8.5f}  {marca}")


def main() -> int:
    ap = argparse.ArgumentParser(description="WHR com margem de vitoria (prova cega).")
    ap.add_argument("--oos-year", type=int, default=2026)
    ap.add_argument("--mov", default="gd15",
                    help="kills|gold|goldpm|gd15|towers|gd10|gd20|xpd15|csd15|dom15|todos")
    # A grade PRECISA ir alem do otimo, senao o "melhor" e so a borda. Na
    # primeira rodada (08/09/2026) os quatro sinais escolheram 0,5 — que era o
    # ultimo valor — entao o teto subiu.
    ap.add_argument("--lams", default="0,0.1,0.2,0.35,0.5,0.75,1.0,1.5,2.0")
    ap.add_argument("--w2s", default="20,60,150")
    ap.add_argument("--folgas", default="0.0",
                    help="folga do G-Elo: vitoria normal vale 1-folga (0 = sem folga)")
    args = ap.parse_args()
    folgas = [float(x) for x in args.folgas.split(",")]

    oos = int(args.oos_year)
    tune = oos - 1
    lams = [float(x) for x in args.lams.split(",")]
    w2s = [float(x) for x in args.w2s.split(",")]
    # Aceita lista separada por virgula: rodar "todos" quando so interessam
    # tres candidatos gasta tempo de maquina a toa.
    if args.mov == "todos":
        sinais = list(SINAIS)
    else:
        sinais = [x.strip() for x in str(args.mov).split(",") if x.strip()]
    for s in sinais:
        if s not in SINAIS:
            raise SystemExit(f"sinal desconhecido: {s} (use {'|'.join(SINAIS)})")

    g = load_games(default_csvs())
    lp_oos = sos_points_from_train(g, oos, 400.0)
    lp_tune = sos_points_from_train(g, tune, 400.0)
    print(f"[mov] jogos: {len(g)} | cego={oos} | tune={tune}", flush=True)

    resumo = []
    for sinal in sinais:
        mov_fn = SINAIS[sinal]
        print(f"\n{'='*72}\n[mov] SINAL = {sinal}\n{'='*72}", flush=True)

        # --- ajuste de E[MOV|Δr] com dados de TREINO do tune (nada do cego)
        fit_t = fit_expected_mov(g, ate_ano=tune, league_points=lp_tune,
                                 w2=60.0, mov_fn=mov_fn)
        print(f"[mov] E[MOV|dr] (treino<{tune}): a={fit_t['a']:.3f} b={fit_t['b']:.3f} "
              f"c={fit_t['c']:.3f} desvio_residuo={fit_t['s']:.3f} "
              f"n={fit_t['n']} sem_mov={fit_t['n_sem_mov']}", flush=True)

        # --- tune de (w2, lam) no ano anterior ao cego
        print(f"[mov] tune (w2, lam) em {tune}:", flush=True)
        melhor = None
        for w2 in w2s:
            for lam in lams:
                for folga in folgas:
                    if lam == 0.0 and folga != 0.0:
                        continue   # sem margem, folga so encolhe o rating
                    res = run(g, score_year=tune, league_points=lp_tune, w2=w2,
                              lam=lam, folga=folga, mov_fn=mov_fn, fit=fit_t)
                    ll = res["geral"]["logloss"]
                    print(f"   w2={w2:>6.0f} lam={lam:<5} folga={folga:<5} -> "
                          f"geral {ll:.4f} (n={res['geral']['n']})", flush=True)
                    if melhor is None or ll < melhor[0]:
                        melhor = (ll, w2, lam, folga)
        _, w2s_, lam_s, folga_s = melhor
        print(f"[mov] escolhido no tune: w2={w2s_:.0f} lam={lam_s} folga={folga_s}",
              flush=True)

        # --- ajuste de E[MOV] para o cego (agora pode usar ate <oos)
        fit_o = fit_expected_mov(g, ate_ano=oos, league_points=lp_oos,
                                 w2=w2s_, mov_fn=mov_fn)
        print(f"[mov] E[MOV|dr] (treino<{oos}): a={fit_o['a']:.3f} b={fit_o['b']:.3f} "
              f"c={fit_o['c']:.3f} desvio_residuo={fit_o['s']:.3f} n={fit_o['n']}",
              flush=True)

        # --- EVAL CEGO: baseline (lam=0, = producao) vs candidato
        print(f"\n[mov] EVAL CEGO {oos}:", flush=True)
        base = run(g, score_year=oos, league_points=lp_oos, w2=w2s_, lam=0.0,
                   mov_fn=mov_fn, fit=fit_o)
        cand = run(g, score_year=oos, league_points=lp_oos, w2=w2s_, lam=lam_s,
                   folga=folga_s, mov_fn=mov_fn, fit=fit_o)

        print(f"{'seg':<8}{'n':>7} | {'BASE ll':>9}{'acc':>8} | "
              f"{'MOV ll':>9}{'acc':>8} | {'dif ll':>9}")
        for seg in ("same", "inter", "geral"):
            b, c = base[seg], cand[seg]
            print(f"{seg:<8}{b['n']:>7} | {b['logloss']:>9.4f}{100*b['acc']:>7.1f}% | "
                  f"{c['logloss']:>9.4f}{100*c['acc']:>7.1f}% | "
                  f"{b['logloss']-c['logloss']:>+9.4f}")

        dif, lo, hi = bootstrap_pareado(base["perdas"], cand["perdas"])
        print(f"\n[mov] dif media (base - mov) = {dif:+.5f}  "
              f"IC95% [{lo:+.5f}, {hi:+.5f}]  (positivo = margem melhor)")
        print(f"[mov] jogos sem sinal de margem no replay: {cand['n_sem_mov']}")
        yf = cand["yf"]
        print(f"[mov] y~: faixa [{yf['min']:.3f}, {yf['max']:.3f}] | "
              f"ajuste medio {yf['ajuste_medio_abs']:.3f} | "
              f"no batente {100*yf['frac_no_batente']:.1f}% | "
              f"DISCORDA de quem ganhou em {100*yf['frac_cruzou']:.1f}% dos jogos")

        quebra_por(base, cand, 0, "ganho por MES")
        quebra_por(base, cand, 1, "ganho por LIGA")

        # Barra da casa: ganho > 0,002 E limite inferior do IC > 0.
        passa = (dif > 0.002) and (lo > 0.0)
        veredito = "ACEITA" if passa else "REJEITA"
        if lam_s == 0.0:
            veredito = "REJEITA (o proprio tune escolheu lam=0)"
        print(f"[mov] VEREDITO ({sinal}): {veredito}")
        resumo.append((sinal, lam_s, w2s_, folga_s, dif, lo, hi, veredito))

    if len(resumo) > 1:
        print(f"\n{'='*72}\nRESUMO\n{'='*72}")
        print(f"{'sinal':<9}{'lam':>6}{'w2':>6}{'dif ll':>10}{'IC95 inf':>11}"
              f"{'IC95 sup':>11}  veredito")
        for s, l, w, fg, d, lo, hi, v in resumo:
            print(f"{s:<9}{l:>6}{w:>6.0f}{fg:>7}{d:>+10.5f}{lo:>+11.5f}{hi:>+11.5f}  {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
