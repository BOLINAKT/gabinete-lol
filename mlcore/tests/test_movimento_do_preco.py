# -*- coding: utf-8 -*-
"""De onde o preco veio -- e por que nao se chama "abertura".

ELE OBSERVOU (16/09/2026): "voce pode estar pegando algo que na realidade ja
mudou de odd ja tem um tempo, ele nao necessariamente abriu nessa odd ai que
voce esta pegando, ate porque voce nao pega a abertura".

Certissimo, e sem conserto possivel: o robo le de 3 em 3 horas, entao o
primeiro preco que vemos e o que estava la quando ele passou.

O QUE A PESQUISA DISSE (pedida por ele, fontes abertas em 16/09/2026):
  - o CLV so precisa do preco que ele pegou e do FECHAMENTO. "Opening odds
    are irrelevant to calculating CLV" (pinnacleoddsdropper.com);
  - o fechamento e mais afiado que a abertura, nao o contrario
    (boydsbets.com/opening-vs-closing-line);
  - e a abertura da Pinnacle ja e quase tao eficiente quanto o fechamento
    dela -- "almost no difference in market efficiency between Pinnacle's
    opening and closing prices", medido em 147.629 jogos
    (football-data.co.uk/blog/opening_price_wisdom.php).

Ou seja: nao pegar a abertura NAO quebra a regua. O buraco de verdade e o
fechamento, e esse da para atacar.

O que a tela passa a mostrar e o MOVIMENTO desde a primeira leitura nossa --
chamado de "visto desde", nunca de "abriu em". O nome errado transformaria
uma limitacao conhecida numa afirmacao falsa.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app_core.odds_coletadas_core import carregar_movimento, movimento_da_linha


def _hist(tmp: Path, linhas):
    (tmp / "odds_pinnacle_historico.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in linhas), encoding="utf-8")
    return tmp


class TestOMovimentoEHLido(unittest.TestCase):

    def test_guarda_o_PRIMEIRO_preco_visto_e_quando(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = _hist(Path(d), [
                {"chave": "k", "odd": 2.84, "lido_em": "2026-09-15T20:21:00-03:00"},
                {"chave": "k", "odd": 2.55, "lido_em": "2026-09-16T08:40:00-03:00"},
            ])
            m = carregar_movimento(raiz)
            self.assertEqual(m["k"]["primeiro"], 2.84)
            self.assertEqual(m["k"]["quando"], "2026-09-15T20:21:00-03:00")
            self.assertEqual(m["k"]["leituras"], 2)

    def test_calcula_a_variacao_do_primeiro_ate_agora(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = _hist(Path(d), [
                {"chave": "k", "odd": 2.84, "lido_em": "2026-09-15T20:21:00-03:00"},
                {"chave": "k", "odd": 2.55, "lido_em": "2026-09-16T08:40:00-03:00"},
            ])
            r = movimento_da_linha({"chave": "k", "odd": 2.55}, carregar_movimento(raiz))
            self.assertTrue(r["sabido"])
            self.assertAlmostEqual(r["variacao_pct"], 100 * (2.55 - 2.84) / 2.84, places=6)

    def test_linha_torta_no_historico_nao_apaga_o_resto(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "odds_pinnacle_historico.jsonl").write_text(
                '{"chave":"k","odd":2.0,"lido_em":"a"}\nnao e json\n'
                '{"chave":"k","odd":2.2,"lido_em":"b"}\n', encoding="utf-8")
            self.assertEqual(carregar_movimento(Path(d))["k"]["leituras"], 2)

    def test_sem_arquivo_devolve_vazio_e_nao_estoura(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(carregar_movimento(Path(d)), {})


class TestUmaLeituraNAOEhMovimento(unittest.TestCase):
    """PRINCIPIO IV: "0% de variacao" e uma afirmacao.

    Dizer que a linha nao andou, tendo visto ela UMA vez, inventa uma
    estabilidade que ninguem observou -- e estabilidade e justamente o que
    daria conforto para apostar.
    """

    def test_vista_uma_vez_NAO_vira_zero_por_cento(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = _hist(Path(d), [{"chave": "k", "odd": 2.84, "lido_em": "x"}])
            r = movimento_da_linha({"chave": "k", "odd": 2.84}, carregar_movimento(raiz))
            self.assertFalse(r["sabido"])
            self.assertIsNone(r["variacao_pct"])

    def test_mas_DIZ_que_viu_uma_vez(self):
        """Entre "nao sei" e "nao ha dado", o primeiro ainda informa."""
        with tempfile.TemporaryDirectory() as d:
            raiz = _hist(Path(d), [{"chave": "k", "odd": 2.84, "lido_em": "x"}])
            r = movimento_da_linha({"chave": "k", "odd": 2.84}, carregar_movimento(raiz))
            self.assertEqual(r["leituras"], 1)

    def test_linha_sem_historico_nenhum_devolve_nao_sei(self):
        r = movimento_da_linha({"chave": "nova", "odd": 2.0}, {})
        self.assertFalse(r["sabido"])
        self.assertEqual(r["leituras"], 0)

    def test_linha_sem_chave_nao_estoura(self):
        self.assertFalse(movimento_da_linha({}, {"k": {"primeiro": 2.0}})["sabido"])


class TestATelaNAOChamaDeABERTURA(unittest.TestCase):
    """O nome errado viraria uma limitacao conhecida em afirmacao falsa."""

    def test_o_texto_diz_DESDE_e_nao_abriu(self):
        from app_core.oportunidades_tab_core import _texto_do_movimento
        t = _texto_do_movimento({"_movimento": {
            "sabido": True, "variacao_pct": -10.2, "quando": "2026-09-15T20:21", "leituras": 2}})
        self.assertIn("desde", t)
        self.assertNotIn("abriu", t.lower())
        self.assertNotIn("abertura", t.lower())

    def test_diz_para_que_lado_andou(self):
        from app_core.oportunidades_tab_core import _texto_do_movimento
        self.assertIn("cai", _texto_do_movimento({"_movimento": {
            "sabido": True, "variacao_pct": -10.2, "quando": "x", "leituras": 2}}))
        self.assertIn("sobe", _texto_do_movimento({"_movimento": {
            "sabido": True, "variacao_pct": 6.5, "quando": "x", "leituras": 2}}))

    def test_sem_movimento_sabido_nao_inventa_texto(self):
        from app_core.oportunidades_tab_core import _texto_do_movimento
        self.assertEqual(_texto_do_movimento({"_movimento": {"sabido": False, "leituras": 0}}), "")

    def test_o_coletor_grava_a_CHAVE_no_retrato(self):
        """Sem a chave no retrato, a tela teria de remontar a identidade da
        aposta -- uma segunda implementacao, e elas divergem."""
        import inspect

        from tools import coletar_odds as c
        self.assertIn('linhas[-1]["chave"] = chave_da_linha(linhas[-1])',
                      inspect.getsource(c.normalizar))


if __name__ == "__main__":
    unittest.main()


class TestALeituraPertoDoApito(unittest.TestCase):
    """O buraco que a pesquisa apontou -- e que tinha conserto.

    Nao pegar a ABERTURA nao quebra o CLV: a formula so usa o preco que ele
    pegou e o FECHAMENTO. Nao pegar o FECHAMENTO quebra.

    E com o agendamento antigo (de 3 em 3 horas, aos :25) a ultima leitura
    antes de um jogo podia ficar 2h35 atras dele. Medido na agenda, os jogos
    de LoL comecam na HORA CHEIA -- 09, 10, 12, 14, 15, 16 e 20 UTC --, entao
    ler aos :50 poe a ultima leitura a ~10 minutos do apito.
    """

    def _crons(self):
        import yaml
        from pathlib import Path
        raiz = Path(__file__).resolve().parents[2]
        d = yaml.safe_load((raiz / ".github" / "workflows" / "odds.yml").read_text(
            encoding="utf-8"))
        return [c["cron"] for c in d[True]["schedule"]]

    def _minutos_das_leituras(self):
        """Todos os instantes de leitura do dia, em minutos desde 00:00 UTC.

        O campo de MINUTO tambem aceita lista ("43,53") desde 17/09/2026 --
        sao duas tentativas por hora, porque o GitHub derrubou 67% das
        janelas com uma so.
        """
        minutos = []
        for c in self._crons():
            partes = c.split()
            campo_m, campo_h = partes[0], partes[1]
            if "-" in campo_h:
                a, b = campo_h.split("-")
                horas = list(range(int(a), int(b) + 1))
            else:
                horas = [int(x) for x in campo_h.split(",")]
            for m in (int(x) for x in campo_m.split(",")):
                minutos.extend(x * 60 + m for x in horas)
        return sorted(minutos)

    def test_existe_a_janela_perto_do_apito(self):
        """A REGRA, nao o minuto: existe leitura na faixa de horario de jogo.

        A primeira versao deste teste travava o literal ":50". Quando o
        minuto mudou para :43/:53 -- porque o :50 caia na hora cheia, que a
        propria documentacao do GitHub chama de "high load times" -- o teste
        reprovou um conserto certo. Teste que guarda o literal em vez da
        regra atrapalha quem vem depois.
        """
        faixa = [c for c in self._crons() if "8-20" in c]
        self.assertTrue(faixa, "sumiu a leitura da faixa de jogos")

    def test_a_base_de_3_em_3_horas_continua(self):
        """Ela e quem constroi o historico de MOVIMENTO do preco."""
        self.assertTrue(any(c.startswith("25 ") for c in self._crons()))

    def test_todo_jogo_na_hora_cheia_tem_leitura_ATE_15_MIN_antes(self):
        leituras = self._minutos_das_leituras()
        for hora in (9, 10, 12, 14, 15, 16, 20):
            alvo = hora * 60
            antes = [l for l in leituras if l <= alvo]
            self.assertTrue(antes, "jogo as %02d:00 sem leitura antes" % hora)
            gap = alvo - max(antes)
            self.assertLessEqual(gap, 15,
                                 "jogo as %02d:00 UTC fica %d min sem leitura" % (hora, gap))

    def test_a_leitura_NAO_e_depois_do_apito(self):
        """Toda leitura da faixa de jogos cai ANTES da hora cheia.

        O agendador do GitHub atrasa; uma leitura marcada perto demais do
        apito chega depois dele, e ai o mercado pre-jogo ja sumiu -- o
        coletor descarta o que esta ao vivo.
        """
        for c in self._crons():
            if "8-20" not in c:
                continue
            for m in (int(x) for x in c.split()[0].split(",")):
                self.assertLessEqual(m, 55, "leitura marcada quase na hora cheia")
                self.assertGreaterEqual(60 - m, 5, "menos de 5 min de folga")

    def test_ha_MAIS_DE_UMA_tentativa_por_hora(self):
        """MEDIDO em 17/09/2026: com uma tentativa so, 14 de 21 janelas nao
        aconteceram (67%). Nenhum bloqueio da casa, nenhum erro -- elas
        simplesmente nao dispararam.

        A documentacao do GitHub diz que sob carga "some queued jobs may be
        dropped", e que a carga alta inclui o comeco de cada hora. Duas
        tentativas em minutos diferentes dao a segunda chance.
        """
        for c in self._crons():
            if "8-20" in c:
                minutos = c.split()[0].split(",")
                self.assertGreaterEqual(len(minutos), 2,
                                        "uma tentativa so ja perdeu 67% das janelas")
                return
        self.fail("nao ha janela na faixa de jogos")

    def test_os_minutos_fogem_dos_MAIS_DISPUTADOS(self):
        """:00, :15, :30 e :45 sao os minutos que todo mundo usa."""
        for c in self._crons():
            if "8-20" not in c:
                continue
            for m in (int(x) for x in c.split()[0].split(",")):
                self.assertNotIn(m, (0, 15, 30, 45),
                                 "minuto %d e dos mais disputados" % m)
