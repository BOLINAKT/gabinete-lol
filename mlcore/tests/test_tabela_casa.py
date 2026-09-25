# -*- coding: utf-8 -*-
"""As tres tabelas no formato da bet365 (pedido dele, 25/09/2026).

"eu quero o design igual eu te mandei... e eu clique dentro das linhas para
que eu altere eles... a fair e padrao, nao altera, e se eu mudar a do
modelo, ele vai mudar a da pinnacle tambem".
"""
from __future__ import annotations

import json
import re
import unittest

from app_core.tabela_casa_core import altura, html_das_tabelas, linhas_da_tela


def _justa(**k):
    base = {
        "jogo": 1, "casa": "FlyQuest", "fora": "Shopify Rebellion", "periodo": 1,
        "mercado": "Total - Kills - mapa 1", "nome_pt": "Total - Kills - mapa 1",
        "forma": "total", "tipo_linha": "total", "conta": "modelo",
        "linha_modelo": 24.5, "odd_modelo_a": 2.05, "odd_modelo_b": 1.95,
        "grade": [
            {"linha": 24.5, "odd_modelo_a": 2.05, "odd_modelo_b": 1.95, "casa_a": 1.68,
             "casa_b": 2.08, "vantagem_a": -18.0, "vantagem_b": 6.8, "principal": False},
            {"linha": 25.5, "odd_modelo_a": 2.25, "odd_modelo_b": 1.80, "casa_a": 1.83,
             "casa_b": 1.83, "vantagem_a": -14.0, "vantagem_b": 1.7, "principal": True},
            {"linha": 23.5, "odd_modelo_a": 1.9, "odd_modelo_b": 2.1, "casa_a": None,
             "casa_b": None, "vantagem_a": None, "vantagem_b": None, "principal": False},
        ],
    }
    base.update(k)
    return base


class TestOQueATelaRecebe(unittest.TestCase):

    def test_totais_viram_a_secao_Totais_com_o_nome_da_casa(self):
        l = linhas_da_tela([_justa(),
                            _justa(mercado="(Map 1) Total Turrets Destroyed", nome_pt="Torres")])
        self.assertEqual({x["secao"] for x in l}, {"Totais"})
        self.assertEqual([x["rotulo"] for x in sorted(l, key=lambda x: x["ordem"])],
                         ["Total de Kills", "Total de Torres"])

    def test_comeca_na_linha_PRINCIPAL_da_pinnacle(self):
        self.assertEqual(linhas_da_tela([_justa()])[0]["inicial"], 25.5)

    def test_a_fair_e_a_linha_justa_do_modelo(self):
        f = linhas_da_tela([_justa()])[0]["fair"]
        self.assertEqual((f["linha"], f["oa"], f["ob"]), (24.5, 2.05, 1.95))

    def test_handicap_e_kills_por_time(self):
        l = linhas_da_tela([
            _justa(forma="handicap", tipo_linha="handicap", mercado="Handicap - Kills - mapa 1"),
            _justa(forma="total_time", time="away", mercado="Total do time - Kills - mapa 1")])
        por = {x["secao"]: x for x in l}
        self.assertEqual(por["Handicap de Kills"]["tipo"], "handicap")
        self.assertEqual(por["Kills por time"]["rotulo"], "Shopify Rebellion")

    def test_sem_grade_nao_entra(self):
        self.assertEqual(linhas_da_tela([_justa(grade=[])]), [])


class TestAPagina(unittest.TestCase):

    def _html(self):
        return html_das_tabelas(linhas_da_tela([_justa()]), "LCS — FlyQuest x Shopify")

    def test_os_numeros_vao_dentro_da_pagina(self):
        h = self._html()
        dados = re.search(r"const DADOS = (\[.*?\]);\n", h, re.S).group(1)
        self.assertEqual(json.loads(dados)[0]["inicial"], 25.5)

    def test_as_tres_tabelas_e_o_clique_na_linha(self):
        h = self._html()
        for t in ("Fair (modelo)", '"Modelo"', '"Pinnacle"', ".ln.clica", "sel[m.id] = Number"):
            self.assertIn(t, h)

    def test_nao_vai_a_internet(self):
        """O app nunca vai a rede: nada de script, fonte ou folha de fora."""
        h = self._html()
        self.assertNotRegex(h, r"(?i)(src|href)\s*=\s*[\"']?https?:")
        self.assertNotIn("@import", h)

    def test_texto_do_time_nao_quebra_a_pagina(self):
        h = html_das_tabelas(linhas_da_tela([_justa(casa="</script><b>x")]), "t")
        self.assertNotIn("</script><b>", h.split("const DADOS")[1].split(";\n")[0])

    def test_nomes_de_time_sao_protegidos_na_tela(self):
        h = self._html()
        self.assertIn("esc(m.casa)", h)
        self.assertIn("esc(m.rotulo)", h)

    def test_altura_cresce_com_as_linhas(self):
        um = altura(linhas_da_tela([_justa()]))
        dois = altura(linhas_da_tela([_justa(), _justa(mercado="(Map 1) Total Barons Killed")]))
        self.assertGreater(dois, um)


if __name__ == "__main__":
    unittest.main()
