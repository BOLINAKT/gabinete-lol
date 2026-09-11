# -*- coding: utf-8 -*-
"""A CADEIA SERVIDA, chamavel fora da tela — sem reimplementar nada.

╔══ FONTES ═══════════════════════════════════════════════════════════════════╗
║ O PROBLEMA (redescoberto medindo, em 09/09/2026, e ja escrito em            ║
║ mlcore/replay_pre_jogo.py em 26/08): existem TRES implementacoes da          ║
║ probabilidade pre-jogo e a nota oficial mede a mais simples. A causa raiz    ║
║ e que "o caminho servido nao e chamavel fora da interface, entao quem        ║
║ precisa medir REIMPLEMENTA — e cada um para num ponto diferente".            ║
║                                                                             ║
║ 1. REIMPLEMENTAR E O ANTI-PADRAO, com nome. A literatura de divergencia      ║
║    treino/servico descreve exatamente isto: times "reimplementam a logica    ║
║    de features no caminho de producao... numa linguagem diferente, num       ║
║    calendario diferente", e a cura e "definir a transformacao UMA VEZ" em    ║
║    vez de escrever uma versao para treino e outra para inferencia. Este      ║
║    arquivo NAO contem uma linha de matematica de probabilidade: ele so       ║
║    monta os colaboradores e chama run_ml_pre_pipeline, o codigo de producao. ║
║    https://chalk.ai/blog/what-is-a-feature-store  (aberta em 09/09/2026)     ║
║                                                                             ║
║ 2. A COSTURA JA EXISTIA. "Costura" (seam, Michael Feathers) e "um lugar      ║
║    onde se altera o comportamento do programa sem alterar o codigo"; a       ║
║    forma preferida e a polimorfica, "por injecao de dependencia, montando o  ║
║    grafo de objetos em tempo de execucao", que permite "programas de teste   ║
║    usarem dubles no lugar das dependencias de producao".                     ║
║    run_ml_pre_engine_layers recebe session_state como Mapping comum e ~20    ║
║    colaboradores injetados: a costura estava pronta e nunca foi usada para   ║
║    medir. Nao houve cirurgia aqui — houve montagem.                          ║
║    https://mike-bland.com/2023/08/23/legacy-code-seams-and-the-most-important-design-guideline.html
║    (aberta em 09/09/2026)                                                    ║
║                                                                             ║
║ 3. POR QUE O PROXIMO PASSO E TESTE DE CARACTERIZACAO, e nao sair medindo:    ║
║    a sequencia do Feathers e achar o ponto de mudanca, achar o ponto de      ║
║    teste, quebrar dependencias, ESCREVER TESTES DE CARACTERIZACAO — que      ║
║    "capturam o comportamento atual" e dao "uma linha de base" — e so entao   ║
║    mexer. Sem esse passo, esta bancada seria a QUARTA reimplementacao com    ║
║    cara de primeira. Ela so vale depois de provar que reproduz o app.        ║
║    (mesma fonte 2, secao de characterization tests)                          ║
║                                                                             ║
║ 4. NENHUM DUBLE DEVOLVE NUMERO. Colaborador que eu nao consiga montar vira   ║
║    _proibido(), que ESTOURA se chamado. Um duble que devolvesse 0.0 ou 0.5   ║
║    faria a bancada medir um caminho inventado com cara de servido — a mesma  ║
║    familia das dividas D5/D8/D9 deste projeto (ausencia virando numero       ║
║    plausivel).                                                               ║
╚═════════════════════════════════════════════════════════════════════════════╝

O MAPA DA CADEIA SERVIDA (levantado lendo o codigo em 09/09/2026):
    p_raw  = model.p_blue(...)                     <- rating WHR
    p_cal  = artifact.calibrator.predict_proba()   <- Platt  (ml_artifact_pricing_core)
    -> entra no motor como p_map_used
    governador de confianca / incerteza            (condicional)
    fusao com jogadores                            (SO com use_lineup=True)
    calibrador de grupo pos-fusao                  (condicional)
    -> pre-live pipeline                           (mais 7 pontos de mudanca)

A NOTA OFICIAL (ml_fusion_scorecard.py) mede APENAS o p_raw. Este arquivo
existe para acabar com isso.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, MutableMapping

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- os MESMOS modulos que o plays_app importa (nada reescrito aqui) ---------
from app_core.app_state import bootstrap_state, get_state_schema  # noqa: E402
from app_core.ml_settings_runtime_core import (  # noqa: E402
    build_runtime_param_defaults, local_runtime_defaults,
)
from app_core.artifact_loaders_core import (  # noqa: E402
    _file_sig, _load_artifact_cached, _load_fitted_params_cached,
    _load_players_artifact_cached,
)
from app_core.calibrate_p_core import calibrate_p_from_artifact as _calibrate_p_core  # noqa: E402
from app_core.ml_adjust_helpers_core import (  # noqa: E402
    _apply_ml_uncertainty_adjust, _fuse_probs_by_precision, _p_from_diff_points,
)
from app_core.ml_pre_pipeline_core import run_ml_pre_pipeline  # noqa: E402
from app_core.visao_geral_ml_pipeline_core import build_pre_engine_input  # noqa: E402
from mlcore.bo import prob_win_series  # noqa: E402
from mlcore.players_layer import compute_delta_and_confidence  # noqa: E402

ARQ_CONFIG = ROOT / ".gabinete_settings.json"
FIT_PARAMS = ROOT / "params_fitted.json"


def _proibido(nome: str) -> Callable[..., Any]:
    """Duble que ESTOURA. Ver FONTES item 4: melhor quebrar do que inventar."""
    def _f(*a: Any, **k: Any) -> Any:
        raise RuntimeError(
            f"colaborador '{nome}' foi CHAMADO mas a bancada nao o montou. "
            "Monte-o de verdade — nao devolva um numero plausivel aqui."
        )
    return _f


def estado_do_app(*, usar_config_salva: bool = True) -> Dict[str, Any]:
    """session_state igual ao do app: defaults + o que o dono salvou.

    Ler o .gabinete_settings.json NAO e detalhe: e nele que estao as chaves que
    DECIDEM a cadeia. Medido em 09/09/2026: use_lineup_adjust=False, o que
    corta as DUAS fusoes (ambas exigem use_lineup). Medir com os defaults em
    vez do arquivo mediria um app que ninguem usa.

    ARMADILHA QUE ME PEGOU AO ESCREVER ISTO (09/09/2026): a primeira versao usava
    so APP_STATE_DEFAULTS e a chave `ml_postfusion_cal_enabled` saia AUSENTE — a
    bancada teria medido o calibrador de grupo desligado, quando o app o liga.
    O app monta o estado em DUAS camadas alem do schema, e a ordem importa:
        1) build_runtime_param_defaults(schema) -> bootstrap_state
        2) local_runtime_defaults()             -> setdefault
    Replicado abaixo na mesma ordem (plays_app.py:684-702).
    """
    ss: Dict[str, Any] = {}
    if usar_config_salva and ARQ_CONFIG.exists():
        try:
            bruto = json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
            salvos = bruto.get("settings") if isinstance(bruto, dict) else None
            if isinstance(salvos, dict):
                ss.update(salvos)   # o que o dono salvou VENCE os defaults
        except (OSError, ValueError, json.JSONDecodeError) as e:
            raise SystemExit(f"config salva ilegivel ({e}); nao vou medir com defaults "
                             "fingindo que e a sua config")

    esquema = get_state_schema()
    bootstrap_state(
        ss,
        defaults=build_runtime_param_defaults(esquema.get("defaults", {})),
        migrations=dict(esquema.get("migrations", {})),
        constraints=dict(esquema.get("constraints", {})),
    )
    for k, v in local_runtime_defaults().items():
        ss.setdefault(k, v)
    return ss


def _calibrate_p_from_artifact(artifact_path: str, p_raw: float) -> float:
    """Copia EXATA do invólucro do plays_app (linha 1146): mesma funcao de core,
    mesmo ctx de duas chaves. Se o app mudar, isto tem que mudar junto — e o
    teste de caracterizacao e quem pega."""
    return _calibrate_p_core(
        artifact_path, p_raw,
        ctx={"_file_sig": _file_sig, "_load_artifact_cached": _load_artifact_cached},
    )


def callbacks_do_motor() -> Dict[str, Callable[..., Any]]:
    """Os mesmos callbacks que visao_tab_core monta (linha 458).

    Os que so rodam com use_lineup=True ficam como _proibido: se algum dia a
    cadeia passar por eles, a bancada QUEBRA em vez de medir errado calada.
    """
    try:
        from app_core.confidence_governor_core import apply_confidence_governor
    except ImportError:
        apply_confidence_governor = _proibido("apply_confidence_governor_fn")
    try:
        from app_core.league_filters_core import league_is_excluded
    except ImportError:
        league_is_excluded = _proibido("league_is_excluded_fn")

    return {
        "league_is_excluded_fn": league_is_excluded,
        "apply_ml_uncertainty_adjust_fn": _apply_ml_uncertainty_adjust,
        "prob_win_series_fn": prob_win_series,
        "load_players_artifact_cached_fn": _load_players_artifact_cached,
        "file_sig_fn": _file_sig,
        "calibrate_p_from_artifact_fn": _calibrate_p_from_artifact,
        "fuse_probs_by_precision_fn": _fuse_probs_by_precision,
        "p_from_diff_points_fn": _p_from_diff_points,
        "compute_delta_and_confidence_fn": compute_delta_and_confidence,
        "apply_confidence_governor_fn": apply_confidence_governor,
        # --- so alcancaveis com use_lineup=True ---
        "fit_players_lane_for_league_fn": _proibido("fit_players_lane_for_league_fn"),
        "fit_players_league_weight_for_league_fn": _proibido("fit_players_league_weight_for_league_fn"),
        "delta_players_effect_fn": _proibido("delta_players_effect_fn"),
        "transfer_signal_from_details_fn": _proibido("transfer_signal_from_details_fn"),
        "lineup_continuity_from_details_fn": _proibido("lineup_continuity_from_details_fn"),
        "score_team_fn": _proibido("score_team_fn"),
        "elo_season_players_p_map_fn": _proibido("elo_season_players_p_map_fn"),
    }


def coef_grupo() -> Any:
    """O bloco do calibrador de grupo, lido como o app le (visao_tab_core:497)."""
    try:
        return ((_load_fitted_params_cached(_file_sig(str(FIT_PARAMS))) or {})
                .get("postfusion_group_calibration") or None)
    except Exception:
        return None


def diagnostico(ss: Mapping[str, Any]) -> None:
    """Quais chaves DECIDEM a cadeia, e como elas estao agora."""
    chaves = [
        ("use_lineup_adjust", "liga as DUAS fusoes com jogadores"),
        ("ml_players_w_lineup", "peso do lineup (so vale se a de cima for True)"),
        ("ml_engine", "qual motor roda"),
        ("ml_postfusion_cal_enabled", "calibrador de grupo pos-fusao"),
        ("ml_uncertainty_enabled", "governador de incerteza"),
        ("ml_marginal_trust_enabled", "guardiao marginal"),
    ]
    print("CHAVES QUE DECIDEM A CADEIA SERVIDA")
    for k, porque in chaves:
        v = ss.get(k, "<ausente>")
        print(f"  {k:<32} = {str(v):<10}  ({porque})")
    bloco = coef_grupo()
    print(f"  {'bloco do calibrador de grupo':<32} = "
          f"{'presente' if bloco else 'AUSENTE':<10}  (params_fitted.json)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Cadeia servida, fora da tela.")
    ap.add_argument("--diagnostico", action="store_true",
                    help="Mostra as chaves que decidem a cadeia e sai.")
    ap.add_argument("--defaults", action="store_true",
                    help="Ignora a config salva e usa so os defaults do app.")
    args = ap.parse_args()

    ss = estado_do_app(usar_config_salva=not args.defaults)
    print(f"session_state montado: {len(ss)} chaves "
          f"({'config salva + defaults' if not args.defaults else 'so defaults'})\n")
    diagnostico(ss)

    cbs = callbacks_do_motor()
    montados = sum(1 for f in cbs.values() if getattr(f, "__name__", "") != "_f")
    print(f"\ncolaboradores: {montados} montados de verdade, "
          f"{len(cbs) - montados} como armadilha (estouram se chamados)")
    print("\n(0.1 pronto: o codigo de producao e alcancavel. Falta o 0.2 — "
          "provar que ele devolve o mesmo numero do app.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
