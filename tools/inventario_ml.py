# -*- coding: utf-8 -*-
"""FASE 1 — inventario de TUDO que mexe na probabilidade, extraido do codigo.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ 1. O FORMATO e o de "system card": model cards "se estendem em system cards ║
║    que documentam a pilha inteira, e CADA CARD DE COMPONENTE vira uma peca  ║
║    de evidencia que o system card agrega". O que um card registra: detalhes ║
║    do modelo, uso pretendido, metricas, dados de avaliacao, analises        ║
║    quantitativas e ressalvas — mais procedencia (autor, data, versao).      ║
║    https://www.emergentmind.com/topics/model-cards-and-datasheets           ║
║    (aberta em 09/09/2026)                                                   ║
║                                                                             ║
║ 2. POR QUE A COLUNA "escolhido como melhor de N" EXISTE — maldicao do       ║
║    vencedor: "forma comprovavel de vies de selecao, que leva a superestimar ║
║    o valor das nossas vitorias"; "efeitos escolhidos por serem grandes      ║
║    tendem a superestimar o efeito verdadeiro... mesmo quando movidos por    ║
║    ruido amostral", e "melhorias reportadas tendem a superestimar os ganhos ║
║    reais quando replicadas".                                                ║
║    https://accountablealgorithm.substack.com/p/the-winners-curse-in-machine-learning
║    (aberta em 09/09/2026)                                                   ║
║    MEDIDO AQUI (09/09/2026): o `best_form` declara +0.005125 de logloss;    ║
║    aplicado com correcao temporal em 7 dobras independentes, a nota foi de  ║
║    7.06 para 6.99 — NAO replicou. Por isso todo ganho declarado neste       ║
║    inventario entra como SUSPEITO ate revalidacao independente.             ║
║                                                                             ║
║ 3. POR QUE SEPARAR "vive no treino" de "vive depois do treino" — a          ║
║    metodologia de ablacao manda "distinguir ablacao por REMOCAO (omitida no ║
║    treino E no teste) da ablacao IMPRECISA (corrompida so no teste)", e so  ║
║    a primeira permite comparacao justa. Peca de treino exige retreino para  ║
║    ser ablacionada; peca de pos-treino nao.                                 ║
║    https://www.emergentmind.com/topics/controlled-ablation-study            ║
║    (aberta em 09/09/2026)                                                   ║
║                                                                             ║
║ 4. ESTE ARQUIVO NAO DIGITA NADA DE MEMORIA. Tudo e extraido do codigo, do   ║
║    ml_artifact.json e do params_fitted.json. Inventario escrito a mao       ║
║    apodrece — foi o que aconteceu com a lista anterior, onde eu presumi     ║
║    "ligada" = "nunca medida" e errei em pelo menos tres pecas.              ║
╚═════════════════════════════════════════════════════════════════════════════╝

Uso:
  python tools/inventario_ml.py             # tabela na tela
  python tools/inventario_ml.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Chaves que denunciam um ganho declarado dentro de um bloco de params_fitted.
_CHAVES_GANHO = ("improvement_logloss", "improvement_logloss_vs_no_form",
                 "gain_logloss", "delta_logloss", "improvement_brier")


def _achar_ganho(bloco) -> tuple[float | None, str]:
    """Ganho declarado dentro do bloco, se houver, e de qual chave veio."""
    if not isinstance(bloco, dict):
        return None, ""
    for k in _CHAVES_GANHO:
        if k in bloco:
            try:
                return float(bloco[k]), k
            except (TypeError, ValueError):
                pass
    # blocos com baseline/best explicitos (o padrao do fit deste projeto)
    for a, b in (("baseline", "best"),):
        if isinstance(bloco.get(a), dict) and isinstance(bloco.get(b), dict):
            try:
                return float(bloco[a]["logloss"]) - float(bloco[b]["logloss"]), f"{a}-{b}"
            except (TypeError, ValueError, KeyError):
                pass
    return None, ""


# Qual grade pertence a qual bloco. Explicito de proposito: a primeira versao
# usava heuristica ("acha qualquer chave grid*") e atribuiu N=49 a TODOS os
# blocos, inclusive aos que nao tem grade. Inventario com numero errado e pior
# que inventario nenhum — foi o defeito que ele existe para consertar.
_GRADE_DO_BLOCO = {
    "best": "grid",                 # grade de team_scale x players_scale
    "best_combined": "grid",
    "best_by_league": "grid",
    "best_form": "grid_form_top20",  # top20 GRAVADO; a grade real foi maior
    "best_form_by_league": "grid_form_top20",
    "best_form_by_macro": "grid_form_top20",
}

# Blocos que NAO sao pecas: sao registro do proprio ajuste ou dado derivado.
_NAO_E_PECA = {
    "baseline": "registro do fit (linha de base, nao e estagio)",
    "best_folds": "registro do fit (as dobras usadas)",
    "best_form_baseline_no_form": "registro do fit (contrafactual sem forma)",
    "blind_backtest_by_league": "registro de medicao, nao e estagio",
    "league_macro_map": "dado (mapa liga->macro)",
    "patch_snapshot": "dado derivado do CSV (patch mais recente por liga)",
}


def _n_configs(bloco, nome: str, todos: dict) -> int | None:
    """Quantas configuracoes concorreram — o N da 'maldicao do vencedor'."""
    chave = _GRADE_DO_BLOCO.get(nome)
    if not chave:
        return None
    v = todos.get(chave)
    return len(v) if isinstance(v, list) else None


def pecas_dos_params() -> list[dict]:
    """Cada bloco do params_fitted vira um card."""
    p = ROOT / "params_fitted.json"
    if not p.exists():
        return []
    todos = json.loads(p.read_text(encoding="utf-8"))
    quando = str(todos.get("generated_at") or "")
    origem = str(todos.get("artifact") or "")
    fora = {"generated_at", "artifact", "players_artifact", "csvs", "samples_total",
            "speed_profile", "players_context_budget", "min_train_games",
            "w_lineup_used", "fit_plan"}
    saida = []
    for nome, bloco in todos.items():
        if nome in fora or nome.startswith("grid"):
            continue
        ganho, de_onde = _achar_ganho(bloco)
        saida.append({
            "peca": nome,
            "nao_e_peca": _NAO_E_PECA.get(nome, ""),
            "onde": "params_fitted.json",
            "momento": "depois do treino",
            "ligada": None,
            "ajustado_em": quando,
            "ajustado_na_maquina": ("outra" if "steam" in origem.lower() else "esta"),
            "ganho_declarado": ganho,
            "ganho_de": de_onde,
            "melhor_de_n": _n_configs(bloco, nome, todos),
            "suspeito_maldicao": bool(_GRADE_DO_BLOCO.get(nome)),
            "revalidado_independente": False,
        })
    return saida


def pecas_do_pipeline() -> list[dict]:
    """Os estagios que o motor e o pre-live registram no traco."""
    saida = []
    for arq, momento in (("app_core/ml_pre_engine_core.py", "motor"),
                         ("app_core/ml_pre_live_pipeline_core.py", "pre-live")):
        src = (ROOT / arq).read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'stage\s*=\s*"([a-z0-9_]+)"', src):
            nome = m.group(1)
            if any(x["peca"] == nome for x in saida):
                continue
            saida.append({
                "peca": nome, "onde": arq, "momento": momento,
                "ligada": None, "ajustado_em": "", "ajustado_na_maquina": "",
                "ganho_declarado": None, "ganho_de": "", "melhor_de_n": None,
                "suspeito_maldicao": False, "revalidado_independente": False,
            })
    return saida


def pecas_do_treino() -> list[dict]:
    """O que vive DENTRO do treino — ablacao aqui exige retreino (fonte 3)."""
    art = ROOT / "ml_artifact.json"
    meta = json.loads(art.read_text(encoding="utf-8")).get("meta", {}) if art.exists() else {}
    pl = meta.get("players_layer") or {}
    itens = [
        ("rating do time (WHR)", f"core={meta.get('core')} w2={meta.get('whr_w2')}", True),
        ("margem de vitoria no WHR", str(meta.get("whr_mov") or "DESLIGADA"),
         bool(meta.get("whr_mov"))),
        ("calibrador Platt do time", f"a={(meta.get('metrics') or {}).get('cal_a')}", True),
        ("camada de jogadores", f"w_lineup={pl.get('w_lineup')} "
                                f"(cru={pl.get('w_lineup_raw')})",
         bool(float(pl.get("w_lineup") or 0.0) > 0)),
    ]
    return [{
        "peca": nome, "onde": "ml_artifact.json / treino", "momento": "dentro do treino",
        "ligada": lig, "ajustado_em": str(meta.get("trained_at") or ""),
        "ajustado_na_maquina": "esta", "ganho_declarado": None, "ganho_de": det,
        "melhor_de_n": None, "suspeito_maldicao": False,
        "revalidado_independente": False,
    } for nome, det, lig in itens]


def estado_das_bandeiras(pecas: list[dict]) -> None:
    """Preenche 'ligada' para os estagios, lendo o estado real do app."""
    try:
        from tools.cadeia_servida import estado_do_app
        ss = estado_do_app()
    except Exception as e:
        print(f"(nao consegui montar o estado do app: {e})")
        return
    for p in pecas:
        if p["ligada"] is not None:
            continue
        for chave in (f"ml_{p['peca']}_enabled", f"{p['peca']}_enabled",
                      f"ml_{p['peca']}"):
            if chave in ss:
                p["ligada"] = bool(ss.get(chave))
                p["bandeira"] = chave
                break


def medido_no_app(pecas):
    """Preenche 'ligada'/'disparou' com o TRACO CAPTURADO DO APP REAL.

    Fonte de verdade > palpite de nome de bandeira. O golden veio de dirigir o
    app headless (tools/caracterizacao_cadeia.py --capturar), entao 'disparou'
    aqui e observacao, nao inferencia.
    """
    g = ROOT / "evidence" / "golden_cadeia_servida.json"
    if not g.exists():
        return
    try:
        ouro = json.loads(g.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    visto = {}
    for c in ouro.get("confrontos", []):
        for ch in (c.get("chamadas") or []):
            for passo in (ch.get("passos") or []):
                nome = str(passo.get("stage") or "")
                if not nome:
                    continue
                d = visto.setdefault(nome, {"disparou": 0, "de": 0, "enabled": None})
                d["de"] += 1
                d["disparou"] += 1 if passo.get("applied") else 0
                if passo.get("enabled") is not None:
                    d["enabled"] = bool(passo.get("enabled"))
    for x in pecas:
        v = visto.get(x["peca"])
        if not v:
            continue
        x["disparou_em"] = f"{v['disparou']}/{v['de']} confrontos medidos"
        if x["ligada"] is None and v["enabled"] is not None:
            x["ligada"] = v["enabled"]
        elif x["ligada"] is None and v["disparou"] > 0:
            x["ligada"] = True


def quem_le(pecas):
    """Algum codigo LE este bloco de params? Bloco que ninguem le e peso morto."""
    import subprocess
    for x in pecas:
        if x["onde"] != "params_fitted.json":
            continue
        try:
            r = subprocess.run(
                ["git", "grep", "-l", "--", x["peca"], "--", "*.py"],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60)
            arquivos = [l for l in (r.stdout or "").splitlines()
                        if l and "/tests/" not in l and "inventario_ml" not in l]
        except Exception:
            arquivos = []
        x["lido_por"] = len(arquivos)
        if not arquivos:
            x["alerta"] = "NINGUEM LE este bloco"


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventario das pecas de ML.")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    pecas = pecas_do_treino() + pecas_do_pipeline() + pecas_dos_params()
    estado_das_bandeiras(pecas)
    medido_no_app(pecas)
    quem_le(pecas)

    print(f"{'peca':<40}{'momento':<18}{'ligada':<9}{'ganho decl.':>13}"
          f"{'melhor/N':>10}  {'ajustado':<12}observado")
    print("-" * 108)
    registros = [x for x in pecas if x.get("nao_e_peca")]
    pecas = [x for x in pecas if not x.get("nao_e_peca")]
    for p in sorted(pecas, key=lambda x: (x["momento"], x["peca"])):
        g = f"{p['ganho_declarado']:+.5f}" if isinstance(p["ganho_declarado"], float) else "-"
        n = str(p["melhor_de_n"] or "-")
        lig = {True: "sim", False: "NAO", None: "?"}[p["ligada"]]
        quando = (p["ajustado_em"] or "")[:10]
        marca = " *" if p["suspeito_maldicao"] else ""
        obs = p.get("disparou_em", "")
        if p.get("alerta"):
            obs = p["alerta"]
        print(f"{p['peca'][:39]:<40}{p['momento']:<18}{lig:<9}{g:>13}{n:>10}  "
              f"{quando:<12}{obs}{marca}")

    n_susp = sum(1 for p in pecas if p["suspeito_maldicao"])
    n_val = sum(1 for p in pecas if p["revalidado_independente"])
    print("-" * 108)
    if registros:
        print("\nNAO SAO PECAS (registro do ajuste ou dado derivado):")
        for r in registros:
            print(f"  {r['peca']:<38} {r['nao_e_peca']}")
    print("-" * 108)
    print(f"{len(pecas)} pecas | {n_susp} com ganho declarado por selecao (*) "
          f"| {n_val} revalidadas em dados independentes")
    print("\n(*) 'melhor de N' -> ganho declarado esta inflado pela maldicao do vencedor.")
    print("    Medido em 09/09/2026: best_form declara +0.005125 e NAO replicou.")

    if args.json:
        Path(args.json).write_text(json.dumps(pecas, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"\ngravado em {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
