# -*- coding: utf-8 -*-
"""Trava de seguranca do retreino COMPLETO automatico.

╔══ POR QUE ESTE ARQUIVO EXISTE ═════════════════════════════════════════════╗
║ O robo roda 3x ao dia, mas so faz atualizacao INCREMENTAL, que usa o       ║
║ caminho antigo. Duas coisas que estao em producao so entram por inteiro    ║
║ num treino COMPLETO:                                                       ║
║   - a margem de vitoria (o incremental nao a conhece);                     ║
║   - a camada de jogadores por desempenho (idem).                           ║
║ Sem retreino completo periodico, as duas vao se diluindo sozinhas. Ate     ║
║ 11/09/2026 nao havia NENHUM agendado: os que houve (16/08, 15/07, 02/06)   ║
║ foram disparados a mao, por acaso.                                         ║
║                                                                            ║
║ Retreinar sozinho sem trava seria pior que nao retreinar: um modelo        ║
║ quebrado entraria no ar sem ninguem olhando. Esta trava e o olho.          ║
╚════════════════════════════════════════════════════════════════════════════╝

╔══ POR QUE NAO E UM DUELO CONTRA O MODELO ATUAL ════════════════════════════╗
║ A pratica de mercado para promover modelo e campeao-vs-desafiante: treina  ║
║ o novo, mede os DOIS no mesmo conjunto separado, e so promove se o novo    ║
║ ganhar.                                                                    ║
║ https://www.snowflake.com/en/developers/guides/ml-champion-challenger-model-deployment/
║ https://docs.databricks.com/aws/en/machine-learning/mlops/mlops-workflow   ║
║ (as duas abertas em 11/09/2026)                                            ║
║                                                                            ║
║ AQUI ESSE DUELO SERIA VICIADO, e a favor do lado errado. O campeao e o     ║
║ modelo que vem recebendo atualizacao incremental 3x ao dia — ou seja, ele  ║
║ JA TREINOU nos jogos dos ultimos 30 dias. O desafiante e um treino         ║
║ completo com esses mesmos 30 dias DE FORA. Medir os dois nessa janela e    ║
║ comparar quem estudou a prova com quem nao estudou. O campeao venceria     ║
║ quase sempre, e o retreino nunca aconteceria — que e exatamente o problema ║
║ que ele existe para resolver.                                              ║
║                                                                            ║
║ E nao da para achar uma janela justa: qualquer jogo que o desafiante nao   ║
║ viu, o campeao ja absorveu no incremental do mesmo dia.                    ║
║                                                                            ║
║ Entao a pergunta muda de "o novo e MELHOR?" para "o novo esta INTEIRO?".   ║
║ A razao de retreinar nao e vencer um teste, e reconstruir direito o que o  ║
║ incremental nao sabe reconstruir.                                          ║
║                                                                            ║
║ ISTO E JULGAMENTO MEU, nao citacao — as fontes acima descrevem o duelo,    ║
║ nao dispensam dele. Registrado como decisao, para poder ser contestada.    ║
║                                                                            ║
║ A rede de seguranca de verdade e o BACKUP: o retreino guarda o modelo      ║
║ anterior com sufixo .pre_update_*, e voltar e renomear arquivo.            ║
╚════════════════════════════════════════════════════════════════════════════╝

Uso:
  python tools/portao_retreino_completo.py --novo ml_artifact.json
  python tools/portao_retreino_completo.py --novo novo.json --antigo velho.json

Devolve 0 se o modelo pode subir, 1 se nao pode. Diz sempre o porque.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Um palpite de moeda da logloss 0,6931. Acima disso o modelo e pior que
# chutar, e nao existe cenario em que isso seja aceitavel.
MOEDA = 0.6931471805599453
# Abaixo deste piso, desconfie: logloss baixa demais em LoL pre-jogo quer
# dizer vazamento, nao genialidade. O melhor honesto medido aqui fica ~0,66.
PISO_SUSPEITO = 0.45
# Quanto o elenco de times pode encolher de um treino para o outro sem que
# isso seja sinal de CSV truncado.
QUEDA_MAX_TIMES = 0.15


class Portao:
    def __init__(self) -> None:
        self.falhas: list[str] = []
        self.avisos: list[str] = []
        self.oks: list[str] = []

    def exige(self, condicao: bool, titulo: str, detalhe: str = "") -> bool:
        if condicao:
            self.oks.append(titulo + (" — " + detalhe if detalhe else ""))
            return True
        self.falhas.append(titulo + (" — " + detalhe if detalhe else ""))
        return False

    def avisa(self, condicao: bool, titulo: str, detalhe: str = "") -> None:
        if condicao:
            self.oks.append(titulo + (" — " + detalhe if detalhe else ""))
        else:
            self.avisos.append(titulo + (" — " + detalhe if detalhe else ""))

    def relatorio(self) -> int:
        print("\n" + "=" * 72)
        for t in self.oks:
            print("  OK      " + t)
        for t in self.avisos:
            print("  AVISO   " + t)
        for t in self.falhas:
            print("  FALHOU  " + t)
        print("=" * 72)
        if self.falhas:
            print("\nVEREDITO: NAO SUBIR. {} verificacao(oes) falharam.".format(len(self.falhas)))
            print("O modelo anterior continua no ar. Ha backup .pre_update_* para conferir.")
            return 1
        if self.avisos:
            print("\nVEREDITO: pode subir, com {} aviso(s) acima.".format(len(self.avisos)))
        else:
            print("\nVEREDITO: pode subir. Tudo conferido.")
        return 0


def _carregar(caminho: str) -> dict:
    return json.loads(Path(caminho).expanduser().read_text(encoding="utf-8"))


def conferir(novo_path: str, antigo_path: str | None, pscore_path: str | None) -> int:
    p = Portao()

    try:
        novo = _carregar(novo_path)
    except (OSError, ValueError) as e:
        print("FALHOU: nao consegui ler o modelo novo: {}".format(e))
        return 1

    modelo = novo.get("model") or {}
    meta = novo.get("meta") or {}
    metricas = meta.get("metrics") or {}

    # ---------- 1. o artefato esta inteiro ----------
    p.exige(bool(modelo.get("ratings")), "o modelo tem ratings de time",
            "{} times".format(len(modelo.get("ratings") or {})))
    p.exige(isinstance(novo.get("calibrator"), dict) and
            math.isfinite(float((novo.get("calibrator") or {}).get("a", float("nan")))),
            "o calibrador esta presente e com numeros validos",
            json.dumps(novo.get("calibrator")))
    p.exige(bool(modelo.get("params")), "os parametros do motor estao presentes")

    # ---------- 2. as metricas fazem sentido ----------
    ll = float(metricas.get("logloss_cal", float("nan")))
    if p.exige(math.isfinite(ll), "a logloss do holdout e um numero", str(ll)):
        p.exige(ll < MOEDA,
                "o modelo e melhor que chutar cara ou coroa",
                "logloss {:.5f} contra {:.5f} da moeda".format(ll, MOEDA))
        p.exige(ll > PISO_SUSPEITO,
                "a logloss nao esta baixa demais (sinal de vazamento)",
                "logloss {:.5f}, piso de desconfianca {:.2f}".format(ll, PISO_SUSPEITO))
    n_hold = int(metricas.get("holdout_n", 0) or 0)
    p.exige(n_hold >= 200, "o holdout tem jogos suficientes para valer",
            "{} jogos".format(n_hold))

    # ---------- 3. as camadas que deviam existir existem ----------
    pl = meta.get("players_layer") or {}
    p.exige(bool(pl.get("enabled")), "a camada de jogadores (antiga) foi montada",
            str(pl.get("error") or ""))

    mov = meta.get("whr_mov") or {}
    p.exige(bool(mov), "a MARGEM DE VITORIA foi aplicada no treino",
            "sinal={} lambda={}".format(mov.get("sinal"), mov.get("lambda")))
    if mov:
        com = int(mov.get("jogos_com_margem", 0) or 0)
        sem = int(mov.get("jogos_sem_margem", 0) or 0)
        tot = com + sem
        p.exige(tot > 0 and (com / tot) > 0.5,
                "a maioria dos jogos tem o dado da margem",
                "{} com, {} sem".format(com, sem))

    ps = meta.get("players_pscore") or {}
    if p.exige(bool(ps.get("enabled")),
               "a camada de jogadores POR DESEMPENHO foi montada",
               str(ps.get("error") or "")):
        w = float(ps.get("w", 0.0) or 0.0)
        p.exige(math.isfinite(w) and w > 0.0,
                "o peso da camada por desempenho e positivo",
                "w={:.4f} (cru {:.4f})".format(w, float(ps.get("w_raw", 0.0) or 0.0)))
        # O ajuste converge para ~0,066. Muito longe disso quer dizer que o
        # conjunto de ajuste encolheu, e o peso virou ruido.
        p.avisa(0.01 <= w <= 0.25,
                "o peso por desempenho esta na faixa esperada",
                "w={:.4f}, esperado entre 0,01 e 0,25".format(w))
        p.exige(str(ps.get("fonte_do_peso", "")) == "prequencial",
                "o peso foi ajustado no conjunto grande (prequencial)",
                "fonte={} em {} jogos".format(ps.get("fonte_do_peso"),
                                              ps.get("jogos_usados")))
        p.exige(int(ps.get("n_jogadores", 0) or 0) > 1000,
                "ha jogadores suficientes com nota",
                "{} jogadores".format(ps.get("n_jogadores")))

    # ---------- 4. o arquivo de notas existe e casa com o meta ----------
    alvo_ps = pscore_path or str(Path(novo_path).expanduser().with_name("players_pscore.json"))
    try:
        pac = _carregar(alvo_ps)
        p.exige(isinstance(pac.get("notas"), dict) and len(pac["notas"]) > 1000,
                "o arquivo de notas por desempenho esta no lugar",
                "{} jogadores em {}".format(len(pac.get("notas") or {}), Path(alvo_ps).name))
        if ps:
            p.exige(abs(float(pac.get("w", -1)) - float(ps.get("w", -2))) < 1e-12,
                    "o peso do arquivo bate com o peso registrado no modelo")
    except (OSError, ValueError) as e:
        p.falhas.append("nao consegui ler o arquivo de notas ({}): {}".format(alvo_ps, e))

    # ---------- 5. nao encolheu de forma suspeita ----------
    if antigo_path and Path(antigo_path).expanduser().exists():
        try:
            antigo = _carregar(antigo_path)
            n_novo = len((novo.get("model") or {}).get("ratings") or {})
            n_velho = len((antigo.get("model") or {}).get("ratings") or {})
            if n_velho > 0:
                queda = 1.0 - (n_novo / n_velho)
                p.exige(queda <= QUEDA_MAX_TIMES,
                        "o elenco de times nao encolheu de forma suspeita",
                        "{} -> {} times ({:+.1%})".format(n_velho, n_novo, -queda))
        except (OSError, ValueError) as e:
            p.avisos.append("nao consegui comparar com o modelo anterior: {}".format(e))
    else:
        p.avisos.append("sem modelo anterior para comparar o tamanho do elenco")

    # ---------- 6. o modelo produz probabilidade de gente ----------
    #
    # A primeira versao desta checagem sorteava PARES CONSECUTIVOS da lista de
    # times e exigia que as probabilidades nao fossem todas iguais. Era fragil:
    # pares consecutivos costumam ter forcas parecidas, entao davam quase a
    # mesma probabilidade e a trava acusava colapso onde nao havia.
    #
    # A pergunta certa e mais simples e mais dura: o modelo sabe que o time
    # mais forte e favorito contra o mais fraco? Um modelo colapsado devolve
    # 0,5 para isso. Um modelo invertido devolve menos de 0,5.
    try:
        from mlcore.artifact import MLArtifact
        from mlcore.tiers import tier_for_league
        art = MLArtifact.load_json(str(novo_path))

        ratings = dict((novo.get("model") or {}).get("ratings") or {})
        # So times com historico: um time de um jogo so nao diz nada.
        gp = dict(modelo.get("games_played") or {})
        com_jogo = [t for t in ratings if float(gp.get(t, 0) or 0) >= 20] or list(ratings)
        ordenados = sorted(com_jogo, key=lambda t: float(ratings.get(t, 0.0)))

        def _p(a: str, b: str) -> float:
            lg = ((meta.get("team_meta") or {}).get(a) or {}).get("league") or "LPL"
            t = str(tier_for_league(lg))
            return float(art.model.p_blue(a, b, blue_league=lg, red_league=lg,
                                          blue_tier=t, red_tier=t))

        if len(ordenados) < 4:
            p.avisos.append("times de menos para pontuar confrontos de exemplo")
        else:
            pior, melhor = ordenados[0], ordenados[-1]
            p_forte = _p(melhor, pior)
            p_fraco = _p(pior, melhor)
            meio = ordenados[len(ordenados) // 2]

            p.exige(0.02 < p_forte < 0.98 and 0.02 < p_fraco < 0.98,
                    "as probabilidades de exemplo sao plausiveis",
                    "{} x {} = {:.3f}".format(melhor[:18], pior[:18], p_forte))
            p.exige(p_forte > 0.55,
                    "o modelo sabe que o time mais forte e favorito",
                    "{:.3f} a favor do melhor rating (colapsado daria 0,500)".format(p_forte))
            p.exige(abs((p_forte + p_fraco) - 1.0) < 0.05,
                    "trocar os lados espelha a probabilidade",
                    "{:.3f} + {:.3f} = {:.3f}".format(p_forte, p_fraco, p_forte + p_fraco))
            p.exige(abs(_p(melhor, meio) - p_forte) > 1e-6 or abs(
                        float(ratings.get(meio, 0.0)) - float(ratings.get(pior, 0.0))) < 1e-9,
                    "confrontos diferentes dao probabilidades diferentes")
    except Exception as e:  # noqa: BLE001 - a trava nao pode derrubar o robo
        p.falhas.append("nao consegui pontuar confrontos de exemplo: {}: {}".format(
            type(e).__name__, e))

    return p.relatorio()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--novo", required=True, help="Modelo recem-treinado a conferir.")
    ap.add_argument("--antigo", default=None,
                    help="Modelo anterior, so para comparar tamanho de elenco.")
    ap.add_argument("--pscore", default=None,
                    help="Arquivo de notas por desempenho (padrao: ao lado do modelo).")
    a = ap.parse_args()
    return conferir(a.novo, a.antigo, a.pscore)


if __name__ == "__main__":
    raise SystemExit(main())
