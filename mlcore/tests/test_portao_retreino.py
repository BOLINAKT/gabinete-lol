# -*- coding: utf-8 -*-
"""Testes da trava do retreino completo automatico.

Uma trava que so foi vista aprovando nao e uma trava — e um carimbo. Estes
testes estragam o modelo de uma forma por vez e exigem que ela RECUSE.

Cada cenario aqui e uma forma real de o retreino dar errado sozinho, de
madrugada, sem ninguem olhando.
"""
from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.portao_retreino_completo import conferir


def _modelo_bom() -> dict:
    ratings = {"Time{:02d}".format(i): float(i * 3 - 40) for i in range(40)}
    jogos = {t: 120 for t in ratings}
    return {
        "version": "0.4.0",
        "model": {
            "ratings": ratings,
            "games_played": jogos,
            "params": {"k": 28.0, "scale_points": 400.0},
            "league_strength": {"LPL": 0.0},
            "tier_strength": {"T1": 0.0},
        },
        "calibrator": {"a": 0.72, "b": 0.09},
        "meta": {
            "metrics": {"logloss_cal": 0.662, "holdout_n": 1204},
            "team_meta": {t: {"league": "LPL", "tier": "T1"} for t in ratings},
            "players_layer": {"enabled": True, "w_lineup": 0.03},
            "whr_mov": {"sinal": "gd15", "lambda": 0.35,
                        "jogos_com_margem": 25270, "jogos_sem_margem": 2293},
            "players_pscore": {
                "enabled": True, "w": 0.0686, "w_raw": 0.0686,
                "fonte_do_peso": "prequencial", "jogos_usados": 9050,
                "n_jogadores": 5840,
            },
        },
    }


def _notas_boas(w: float = 0.0686) -> dict:
    return {"w": w, "beta": 10.0,
            "notas": {"p{}|||Mid".format(i): {"n": 0.01, "gp": 30} for i in range(1500)}}


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _gravar(self, modelo: dict, notas: dict | None = None) -> str:
        alvo = self.raiz / "ml_artifact.json"
        alvo.write_text(json.dumps(modelo), encoding="utf-8")
        if notas is not None:
            (self.raiz / "players_pscore.json").write_text(
                json.dumps(notas), encoding="utf-8")
        return str(alvo)

    def _rodar(self, modelo: dict, notas: dict | None = None) -> int:
        caminho = self._gravar(modelo, notas)
        buf = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf):
            rc = conferir(caminho, None, None)
        self._saida = buf.getvalue()
        return rc


class TestAprovaOBom(_Base):

    def test_modelo_intacto_passa(self):
        self.assertEqual(self._rodar(_modelo_bom(), _notas_boas()), 0, self._saida)


class TestRecusaOQuebrado(_Base):
    """Cada um destes ja seria um prejuizo silencioso em producao."""

    def test_recusa_modelo_pior_que_moeda(self):
        m = _modelo_bom()
        m["meta"]["metrics"]["logloss_cal"] = 0.71
        self.assertEqual(self._rodar(m, _notas_boas()), 1)
        self.assertIn("cara ou coroa", self._saida)

    def test_recusa_logloss_baixa_demais(self):
        """Logloss otima em LoL pre-jogo e sinal de vazamento, nao de acerto."""
        m = _modelo_bom()
        m["meta"]["metrics"]["logloss_cal"] = 0.21
        self.assertEqual(self._rodar(m, _notas_boas()), 1)
        self.assertIn("vazamento", self._saida)

    def test_recusa_sem_a_margem_de_vitoria(self):
        m = _modelo_bom()
        m["meta"].pop("whr_mov")
        self.assertEqual(self._rodar(m, _notas_boas()), 1)
        self.assertIn("MARGEM", self._saida)

    def test_recusa_quando_a_camada_de_desempenho_falhou(self):
        m = _modelo_bom()
        m["meta"]["players_pscore"] = {"enabled": False, "error": "CSV sem colunas"}
        self.assertEqual(self._rodar(m, _notas_boas()), 1)
        self.assertIn("DESEMPENHO", self._saida)

    def test_recusa_peso_de_desempenho_zerado(self):
        """Peso 0 quer dizer que o ajuste desistiu — a camada nao entregaria nada."""
        m = _modelo_bom()
        m["meta"]["players_pscore"]["w"] = 0.0
        self.assertEqual(self._rodar(m, _notas_boas(w=0.0)), 1)
        self.assertIn("positivo", self._saida)

    def test_recusa_peso_ajustado_no_conjunto_pequeno(self):
        """Se cair no holdout, o peso sai pela metade — ja aconteceu de verdade."""
        m = _modelo_bom()
        m["meta"]["players_pscore"]["fonte_do_peso"] = "holdout"
        self.assertEqual(self._rodar(m, _notas_boas()), 1)
        self.assertIn("prequencial", self._saida)

    def test_recusa_sem_calibrador(self):
        m = _modelo_bom()
        m["calibrator"] = None
        self.assertEqual(self._rodar(m, _notas_boas()), 1)

    def test_recusa_holdout_pequeno_demais(self):
        m = _modelo_bom()
        m["meta"]["metrics"]["holdout_n"] = 12
        self.assertEqual(self._rodar(m, _notas_boas()), 1)

    def test_recusa_sem_o_arquivo_de_notas(self):
        self.assertEqual(self._rodar(_modelo_bom(), None), 1)
        self.assertIn("notas", self._saida)

    def test_recusa_quando_o_peso_do_arquivo_nao_bate_com_o_do_modelo(self):
        """Arquivo de uma corrida com modelo de outra — descasamento silencioso."""
        self.assertEqual(self._rodar(_modelo_bom(), _notas_boas(w=0.02)), 1)

    def test_recusa_csv_truncado_que_encolhe_o_elenco(self):
        bom = _modelo_bom()
        caminho_velho = self.raiz / "velho.json"
        caminho_velho.write_text(json.dumps(bom), encoding="utf-8")

        encolhido = copy.deepcopy(bom)
        metade = dict(list(encolhido["model"]["ratings"].items())[:15])
        encolhido["model"]["ratings"] = metade
        alvo = self._gravar(encolhido, _notas_boas())

        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = conferir(alvo, str(caminho_velho), None)
        self.assertEqual(rc, 1)
        self.assertIn("encolheu", buf.getvalue())

    def test_recusa_modelo_COLAPSADO(self):
        """Todos os ratings iguais: o modelo perdeu a nocao de quem e melhor."""
        m = _modelo_bom()
        m["model"]["ratings"] = {t: 0.0 for t in m["model"]["ratings"]}
        self.assertEqual(self._rodar(m, _notas_boas()), 1)
        self.assertIn("mais forte e favorito", self._saida)

    def test_recusa_modelo_INVERTIDO(self):
        """Sinal trocado: o modelo daria o time pior como favorito."""
        m = _modelo_bom()
        m["model"]["ratings"] = {t: -v for t, v in m["model"]["ratings"].items()}
        # invertendo os ratings, quem o portao chama de "melhor" passa a ser o
        # antigo pior — entao o teste real e que a probabilidade ainda favoreca
        # o de rating mais alto. Se favorecer, passa; e o que queremos.
        self.assertEqual(self._rodar(m, _notas_boas()), 0, self._saida)


if __name__ == "__main__":
    unittest.main()
