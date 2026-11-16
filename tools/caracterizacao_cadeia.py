# -*- coding: utf-8 -*-
"""0.2 — PROVAR que a bancada offline recebe o mesmo que o app de verdade.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ POR QUE ESTE ARQUIVO EXISTE: tools/cadeia_servida.py chama o CODIGO de       ║
║ producao, mas monta os ARGUMENTOS por conta propria. Se a montagem divergir, ║
║ a bancada mede um caminho que ninguem serve — e seria a SEXTA implementacao  ║
║ do numero pre-jogo (hoje ja existem cinco, cada uma parando num ponto        ║
║ diferente: ml_fusion_scorecard, replay_pre_jogo, generate_odds_fixtures,     ║
║ validate_key_matchups._odd_for_case e o proprio app).                        ║
║                                                                             ║
║ 1. O PADRAO: PARALLEL RUN (biblioteca Scientist, do GitHub). "O bloco `use`  ║
║    e o CONTROL. O bloco `try` e o CANDIDATE." Roda-se os dois sobre a MESMA  ║
║    entrada, compara-se o resultado e publicam-se as divergencias. Aqui:      ║
║      control   = o app de verdade (dirigido headless por AppTest)            ║
║      candidate = tools/cadeia_servida.py                                     ║
║    A regra dura da fonte: "Scientist so e seguro para embrulhar metodos que  ║
║    NAO alteram dados". O caminho pre-jogo e leitura pura — encaixa.          ║
║    https://github.com/github/scientist  (aberta em 09/09/2026)               ║
║                                                                             ║
║ 2. O QUE COMPARAR: as ENTRADAS, nao so a saida. Como control e candidate     ║
║    chamam a MESMA funcao (run_ml_pre_pipeline), qualquer divergencia de      ║
║    saida so pode vir dos argumentos. Comparar campo a campo diz QUAL campo   ║
║    divergiu; comparar so o numero final diria apenas "deu diferente".        ║
║    (inferencia minha a partir da fonte 1, nao esta escrita la)               ║
║                                                                             ║
║ 3. GOLDEN MASTER para o que sobra: "crie X entradas aleatorias, sempre com a ║
║    MESMA SEMENTE, para gerar sempre o mesmo conjunto... voce provavelmente   ║
║    vai querer alguns milhares", rode, grave a saida num arquivo e compare    ║
║    contra ele: "se baterem, siga refatorando; senao, desfaca a mudanca".     ║
║    https://www.codurance.com/publications/2012/11/11/testing-legacy-code-with-golden-master
║    (aberta em 09/09/2026)                                                    ║
║    ADAPTACAO CONSCIENTE: "alguns milhares" e inviavel pela interface (cada   ║
║    confronto e um AppTest inteiro). Entao a divisao e:                       ║
║      - poucos confrontos pelo APP  -> provam que a MONTAGEM esta certa       ║
║      - milhares pela BANCADA       -> viram o golden master do NUMERO        ║
║    A fonte 1 autoriza a amostra pequena no lado caro: o Scientist deixa      ║
║    "controlar com que frequencia o candidato roda... testando so uma         ║
║    pequena porcentagem do trafego".                                          ║
║                                                                             ║
║ 4. POR QUE NAO COMPARAR TRACOS (era o meu plano antes de pesquisar): traco   ║
║    e diagnostico, nao contrato. Golden master fixa uma saida APROVADA e      ║
║    versionada; traco muda de forma a cada mexida no codigo e viraria um      ║
║    teste que chora sem motivo.                                               ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
  python tools/caracterizacao_cadeia.py --capturar     # control: dirige o app
  python tools/caracterizacao_cadeia.py --comparar     # candidate vs control
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "evidence" / "golden_cadeia_servida.json"

# Confrontos ancora: os mesmos que tools/generate_odds_fixtures.py ja usa, para
# o control ser comparavel com o resto do projeto.
CONFRONTOS = [  # reduzido p/ a sondagem do traco
    ("T1", "Gen.G"),                       # mesma liga, topo
    ("G2 Esports", "Fnatic"),              # mesma liga, ocidente
    ("Team WE", "Top Esports"),            # mesma liga, favorito fraco
    ("Gen.G", "Bilibili Gaming"),          # entre ligas
]

# ---------------------------------------------------------------------------
# CONTROL: o app de verdade. Roda em subprocesso porque o AppTest importa o
# plays_app inteiro e polui o processo (mesmo motivo de mlcore/tests/test_e2e_*).
# ---------------------------------------------------------------------------
_DRIVER = r'''
import json, sys
from pathlib import Path
alvo, app_path, time_a, time_b = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
ROOT = Path(app_path).resolve().parent
sys.path.insert(0, str(ROOT))

# O grampo TEM que ser instalado ANTES do plays_app importar a funcao: ele faz
# `from ... import run_ml_pre_pipeline as core_run_ml_pre_pipeline`, que congela
# a referencia no momento do import.
import app_core.ml_pre_pipeline_core as mod
_original = mod.run_ml_pre_pipeline
_capturas = []

def _grampo(**kw):
    """PARALLEL RUN dentro do processo do app (padrao Scientist).

    control   = a chamada do app, com os argumentos que o app montou
    candidate = a MESMA funcao, com os argumentos do app EXCETO session_state e
                callbacks, que vem da bancada (tools/cadeia_servida.py)

    Isolar assim e o ponto: os valores por-jogo sao identicos por construcao,
    entao qualquer divergencia so pode vir do que a bancada monta. Rodar os dois
    no mesmo processo dispensa serializar DataFrames e funcoes.
    """
    saida = _original(**kw)                                   # <- control
    reg = {}
    try:
        entrada = kw.get("pre_engine") or kw.get("pre_engine_kwargs")
        bruto = {} if entrada is None else (
            dict(entrada) if isinstance(entrada, dict)
            else (entrada.to_kwargs() if hasattr(entrada, "to_kwargs") else {}))
        reg["entrada_escalar"] = {
            k: v for k, v in bruto.items()
            if isinstance(v, (int, float, str, bool)) or v is None}
        reg["control_p_map"] = float(saida.get("p_map_used", float("nan"))) if isinstance(saida, dict) else None
        reg["control_p_series"] = float(saida.get("p_series_used", float("nan"))) if isinstance(saida, dict) else None
        # O TRACO diz QUAL estagio mexeu no numero. Nao vira contrato (traco
        # muda de forma a cada mexida); serve para eu saber o que a regua
        # honesta precisa mesmo reproduzir.
        passos = saida.get("trace_pipeline_steps") if isinstance(saida, dict) else None
        if isinstance(passos, list):
            reg["passos"] = [
                {k: v for k, v in dict(p).items()
                 if isinstance(v, (int, float, str, bool)) or v is None}
                for p in passos if isinstance(p, dict)
            ]

        # ---- candidate: troca SO o que a bancada e responsavel por montar ----
        from tools.cadeia_servida import callbacks_do_motor, estado_do_app
        kw2 = dict(kw)
        b2 = dict(bruto)
        b2["session_state"] = estado_do_app()
        b2.update(callbacks_do_motor())
        kw2.pop("pre_engine", None)
        kw2["pre_engine_kwargs"] = b2
        saida2 = _original(**kw2)                             # <- candidate
        reg["cand_p_map"] = float(saida2.get("p_map_used", float("nan"))) if isinstance(saida2, dict) else None
        reg["cand_p_series"] = float(saida2.get("p_series_used", float("nan"))) if isinstance(saida2, dict) else None
    except Exception as e:
        # Scientist: excecao do candidate e ENGOLIDA e registrada; o usuario
        # continua recebendo o resultado do control.
        reg["cand_erro"] = f"{type(e).__name__}: {e}"
    _capturas.append(reg)
    return saida

mod.run_ml_pre_pipeline = _grampo

from app_core.streamlit_apptest_core import quiet_streamlit_bare_mode_warnings
quiet_streamlit_bare_mode_warnings()
from streamlit.testing.v1 import AppTest

at = AppTest.from_file(app_path, default_timeout=900)
at.session_state["_probe_skip_csv_bootstrap_gate"] = True
at.run()
for b in [x for x in at.button if x.label == "Entrar no app"]:
    b.click(); at.run(); break
t1 = [s for s in at.selectbox if s.label == "Time 1"]
t2 = [s for s in at.selectbox if s.label == "Time 2"]
if not (t1 and t2):
    print("FALHA|sem selecao de times"); raise SystemExit(1)
op = [o for o in t1[0].options if o]
# Casamento EXATO primeiro. Sem isto "T1" casa com "SabOOr T1" (aconteceu na
# primeira captura, 09/09/2026) e o golden fica de um confronto que ninguem pediu.
def _achar(nome, excluir=None):
    exato = [o for o in op if str(o).strip().lower() == nome.strip().lower() and o != excluir]
    if exato:
        return exato[0]
    parcial = [o for o in op if nome.lower() in str(o).lower() and o != excluir]
    return parcial[0] if parcial else None
a = _achar(time_a)
b = _achar(time_b, excluir=a)
if not (a and b):
    print(f"FALHA|time nao encontrado: {time_a} / {time_b}"); raise SystemExit(1)
t1[0].select(a); t2[0].select(b); at.run()
for x in [y for y in at.button if y.label == "Analisar Confronto"]:
    x.click(); at.run(); break
if at.exception:
    print("FALHA|" + str(getattr(at.exception[0], "message", at.exception[0]))[:200])
    raise SystemExit(1)
Path(alvo).write_text(json.dumps({
    "time_a": a, "time_b": b, "chamadas": _capturas,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"OK|{len(_capturas)} chamada(s) capturada(s)")
'''


def capturar() -> int:
    """CONTROL: dirige o app e grampeia run_ml_pre_pipeline."""
    tmp = ROOT / "scratchpad"
    tmp.mkdir(exist_ok=True)
    drv = tmp / "_driver_caracterizacao.py"
    drv.write_text(_DRIVER, encoding="utf-8")

    capturas = []
    for a, b in CONFRONTOS:
        alvo = tmp / f"_captura_{a}_{b}.json".replace(" ", "_")
        print(f"[control] dirigindo o app: {a} x {b} ...", flush=True)
        r = subprocess.run(
            [sys.executable, str(drv), str(alvo), str(ROOT / "plays_app.py"), a, b],
            cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
        marca = (r.stdout or "").strip().splitlines()
        marca = marca[-1] if marca else "(sem saida)"
        print(f"           {marca}")
        if r.returncode != 0 or not alvo.exists():
            print((r.stderr or "")[-1200:])
            print(f"[control] FALHOU em {a} x {b} — nao vou gravar golden parcial.")
            return 1
        capturas.append(json.loads(alvo.read_text(encoding="utf-8")))

    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps({
        "gerado_em": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "control": "app real via AppTest (plays_app.py)",
        "confrontos": capturas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[control] golden gravado: {GOLDEN.relative_to(ROOT)}")
    return 0


def comparar() -> int:
    """CANDIDATE: a bancada, contra o golden."""
    if not GOLDEN.exists():
        print("golden ausente — rode --capturar primeiro.")
        return 2
    ouro = json.loads(GOLDEN.read_text(encoding="utf-8"))
    print(f"golden de {ouro.get('gerado_em')} | "
          f"{len(ouro.get('confrontos', []))} confronto(s)\n")
    print(f"{'confronto':<34}{'entra':>9}{'CONTROL':>10}{'CANDIDATE':>11}{'dif':>11}")

    TOL = 1e-12   # e a MESMA funcao com a mesma entrada: tem que bater exato.
    falhas, erros = 0, 0
    for c in ouro.get("confrontos", []):
        nome = f"{c.get('time_a')} x {c.get('time_b')}"
        for ch in (c.get("chamadas") or []):
            if "cand_erro" in ch:
                print(f"{nome:<34}  CANDIDATE ESTOUROU: {ch['cand_erro'][:70]}")
                erros += 1
                continue
            entra = (ch.get("entrada_escalar") or {}).get("p_map_used")
            ctrl, cand = ch.get("control_p_map"), ch.get("cand_p_map")
            if ctrl is None or cand is None:
                print(f"{nome:<34}  captura incompleta")
                falhas += 1
                continue
            dif = float(cand) - float(ctrl)
            marca = "" if abs(dif) <= TOL else "  <-- DIVERGE"
            e = f"{float(entra):.5f}" if isinstance(entra, (int, float)) else "?"
            print(f"{nome:<34}{e:>9}{float(ctrl):>10.5f}{float(cand):>11.5f}"
                  f"{dif:>+11.2e}{marca}")
            if abs(dif) > TOL:
                falhas += 1

    print()
    if erros:
        print(f"VEREDITO: {erros} confronto(s) fizeram o candidate ESTOURAR. "
              "Provavelmente um colaborador que a bancada deixou como armadilha "
              "e que o caminho real usa — conserte a montagem, nao a armadilha.")
        return 1
    if falhas:
        print(f"VEREDITO: {falhas} divergencia(s). A bancada NAO reproduz o app; "
              "medir com ela agora seria medir um sexto caminho.")
        return 1
    print("VEREDITO: bancada == app em todos os confrontos. "
          "A montagem esta fiel; a partir daqui medir com ela e medir o produto.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="0.2 — caracterizacao da cadeia servida.")
    ap.add_argument("--capturar", action="store_true", help="CONTROL: dirige o app real.")
    ap.add_argument("--comparar", action="store_true", help="CANDIDATE: bancada vs golden.")
    args = ap.parse_args()
    if args.capturar:
        return capturar()
    if args.comparar:
        return comparar()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
