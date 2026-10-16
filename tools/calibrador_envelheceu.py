# -*- coding: utf-8 -*-
"""O calibrador com grupo EM PRODUCAO ja envelheceu? (16/10/2026)

Aplica o bloco `postfusion_group_calibration` de params_fitted.json, pela MESMA
funcao que o app usa, nos jogos posteriores ao periodo em que ele foi ajustado,
e mede a inclinacao de calibracao (alvo 1; acima de 1 = timido).

Medido em 16/10/2026 (bloco de 06/09, ajustado em 2026-06..08; 1.458 jogos de
09-10/2026): o bloco ainda AJUDA (logloss 0,60171 -> 0,59650), mas o servido
ficou timido -- inclinacao 1,34 [1,14; 1,53], e nas BO3 ~1,8. O arquivo do
ajustador ja avisava: "o calibrador envelhece com a composicao".

FONTE (aberta em 16/10/2026): Van Calster et al. 2019, PMC6912996 -- "A slope
> 1 suggests the opposite, i.e., that risk estimates are too moderate."
LIMITE: o Platt do time aqui e ajustado no treino; o ajustador de producao o
ajusta em tudo. Diferenca pequena, mas existe.

Uso: python tools/calibrador_envelheceu.py [--desde 2026-09]
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_core.postfusion_calibration_core import _calibrador_com_grupo  # noqa: E402
from mlcore.calibration import fit_platt_from_raw_probs  # noqa: E402
from mlcore.replay_pre_jogo import cadeia, carregar  # noqa: E402
from tools.gate_calibrador_tier import _t1, inclinacao  # noqa: E402

bloco = json.loads((ROOT / "params_fitted.json").read_text(encoding="utf-8"))["postfusion_group_calibration"]
d = carregar()
tr, te, tab = d["treino"], d["teste"], d["tabela"]
pt = fit_platt_from_raw_probs(
    [a.y for a in tr],
    cadeia(tr, tabela=tab, usar_ms1=False, usar_platt_time=False,
           usar_fusao=False, usar_ms2=False, usar_platt_fusao=False))
DESDE = sys.argv[sys.argv.index("--desde") + 1] if "--desde" in sys.argv else "2026-09"
novos = [a for a in te if a.month >= DESDE]
base = cadeia(novos, tabela=tab, platt_time=pt, usar_ms1=True, usar_ms2=False, usar_platt_fusao=False)
servido = [_calibrador_com_grupo(bloco, a.bo, a.phase)(p) for a, p in zip(novos, base)]
ys = [a.y for a in novos]


def ll(ps):
    ps = np.clip(np.asarray(ps), 1e-9, 1 - 1e-9); y = np.asarray(ys, float)
    return float(-np.mean(y * np.log(ps) + (1 - y) * np.log(1 - ps)))


print(f"bloco ajustado em {bloco.get('ajustado_em')} ({bloco.get('periodo')}) | jogos de {DESDE} em diante: {len(novos)}")
print(f"logloss sem o bloco {ll(base):.5f} | com o bloco (o que a tela mostra) {ll(servido):.5f}")
for nome, f in (("todos", lambda a: True), ("T1", lambda a: _t1(a) == "T1"), ("resto", lambda a: _t1(a) != "T1")):
    ii = [i for i, a in enumerate(novos) if f(a)]
    s = inclinacao(np.array([servido[i] for i in ii]), [ys[i] for i in ii])
    print(f"  {nome:<6} n={len(ii):5d}  inclinacao do servido {s[0]:.3f} [{s[1]:.3f}, {s[2]:.3f}]")
for chave in sorted({f"{a.bo}|{a.phase}" for a in novos}):
    ii = [i for i, a in enumerate(novos) if f"{a.bo}|{a.phase}" == chave]
    if len(ii) >= 150:
        s = inclinacao(np.array([servido[i] for i in ii]), [ys[i] for i in ii])
        print(f"  grupo {chave:<12} n={len(ii):5d}  inclinacao {s[0]:.3f} [{s[1]:.3f}, {s[2]:.3f}]")
