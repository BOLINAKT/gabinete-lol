"""UI break probe for plays_app.py using Streamlit AppTest.

Stress scenarios:
- bootstrap
- page mode stale/invalid values
- forced analysis flow
- tab switching
- champions stale radio value
- players tab fuzz (names + malformed lines + submit)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.streamlit_apptest_core import (
    quiet_streamlit_bare_mode_warnings as core_quiet_streamlit_bare_mode_warnings,
    new_apptest_for_file as core_new_apptest_for_file,
    run_apptest_quiet as core_run_apptest_quiet,
)


def _quiet_streamlit_logs() -> None:
    logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
    logging.getLogger("streamlit.runtime.state.session_state_proxy").setLevel(logging.ERROR)
    core_quiet_streamlit_bare_mode_warnings()


def _run_probe(timeout: int = 240) -> int:
    try:
        pass  # type: ignore
    except Exception as exc:  # pragma: no cover - local utility
        print(f"SKIP: streamlit.testing.v1 indisponivel ({exc})")
        return 0

    _quiet_streamlit_logs()

    steps: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        steps.append((name, bool(ok), str(detail)))
        print(f"[{'OK' if ok else 'FAIL'}] {name} :: {detail}")

    def has_exc(at: Any) -> bool:
        return bool(getattr(at, "exception", []))

    def assert_no_exc(at: Any, name: str) -> bool:
        if has_exc(at):
            msgs = [str(e) for e in list(at.exception)[:3]]
            record(name, False, " | ".join(msgs))
            return False
        record(name, True, "sem excecoes")
        return True

    def ss_has(at: Any, key: str) -> bool:
        try:
            _ = at.session_state[key]
            return True
        except Exception:
            return False

    def ss_get(at: Any, key: str, default: Any = None) -> Any:
        try:
            return at.session_state[key]
        except Exception:
            return default

    root = ROOT
    try:
        os.chdir(root)
    except Exception:
        pass
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    at = core_new_apptest_for_file(root / "plays_app.py")
    at.session_state["_probe_skip_csv_bootstrap_gate"] = True
    core_run_apptest_quiet(at, timeout)
    if not assert_no_exc(at, "bootstrap"):
        return 2

    for mode in ["Fluxo Rápido", "Mercados", "Análise", "Completo", "VALOR_INVALIDO"]:
        at.session_state["ui_page_mode"] = mode
        core_run_apptest_quiet(at, timeout)
        assert_no_exc(at, f"ui_page_mode={mode}")

    sels = {s.key: s for s in at.selectbox}
    if "teamA" not in sels or "teamB" not in sels:
        record("team_selectors_present", False, "teamA/teamB ausentes")
    else:
        opts_a = [str(x) for x in list(getattr(sels["teamA"], "options", []) or []) if str(x)]
        opts_b = [str(x) for x in list(getattr(sels["teamB"], "options", []) or []) if str(x)]
        if len(opts_a) < 2 or not opts_b:
            record("team_selector_options", False, "opcoes insuficientes")
        else:
            t1 = opts_a[0]
            t2 = next((x for x in opts_b if x != t1), opts_b[0])
            at.session_state["teamA"] = t1
            at.session_state["teamB"] = t2
            at.session_state["bo"] = 3
            at.session_state["flow_stage"] = "results"
            at.session_state["_analysis_force_once"] = True
            core_run_apptest_quiet(at, timeout)
            assert_no_exc(at, "analysis_forced_results")
            record("p_map_used_presence", ss_has(at, "_p_map_used"), f"p_map_used={ss_get(at, '_p_map_used', None)}")

    for tabs in [
        ["Visão Geral"],
        ["Consistência de Mercado (Laplace)"],
        ["Series"],
        ["Players"],
        ["Campeões"],
        ["Parâmetros"],
        ["Rankings"],
        ["Resumo"],
        ["ConsistÃªncia de Mercado (Laplace)"],  # legacy-mojibake labels
        ["VisÃ£o Geral"],
    ]:
        at.session_state["selected_tab_names"] = tabs
        at.session_state["ui_page_mode"] = "Completo"
        core_run_apptest_quiet(at, timeout)
        assert_no_exc(at, f"tabs={tabs}")

    # Champions stale/invalid radio values (regression class that already happened in this project).
    for bad_value in ["", "___INVALID___"]:
        at.session_state["selected_tab_names"] = ["Campeões"]
        at.session_state["ch_blue_team"] = bad_value
        core_run_apptest_quiet(at, timeout)
        assert_no_exc(at, f"champions_invalid_radio={bad_value!r}")

    # Players fuzz block
    at.session_state["selected_tab_names"] = ["Players"]
    at.session_state["ui_page_mode"] = "Completo"
    at.run(timeout=timeout)
    assert_no_exc(at, "players_tab_open")

    text_areas = {w.key: w for w in at.text_area}
    if "pl_txtA_input" in text_areas and "pl_txtB_input" in text_areas:
        text_areas["pl_txtA_input"].set_value("faker\n\nINVALID@@@\nZeus\nOner\nGumayusi")
        text_areas["pl_txtB_input"].set_value("Chovy\nCanyon\nRuler\nDuro\nKiin")
        core_run_apptest_quiet(at, timeout)
        assert_no_exc(at, "players_names_fuzz")
    else:
        record("players_textareas_present", False, f"textareas={list(text_areas.keys())[:10]}")

    # Fill some line inputs with malformed values (parser should ignore invalids without crashing).
    fuzz_values = ["3.5,4.5", "abc,2.5", "999", "", "0.5,-1,2.5", "2,5"]
    i = 0
    for w in at.text_input:
        if str(w.key).startswith("pl_in_"):
            w.set_value(fuzz_values[i % len(fuzz_values)])
            i += 1
            if i >= 12:
                break
    if i:
        at.run(timeout=timeout)
        assert_no_exc(at, "players_lines_fuzz")
    else:
        record("players_line_inputs_present", False, "nenhum pl_in_* encontrado")

    for b in at.button:
        if (b.label or "").strip() == "Analisar players":
            b.click()
            break
    core_run_apptest_quiet(at, max(timeout, 300))
    assert_no_exc(at, "players_submit_after_fuzz")

    # Set invalid selectbox values one-by-one (combined mutation can break AppTest itself, so isolate by key).
    filter_keys = [
        "pl_stats_filter_team",
        "pl_stats_filter_lane",
        "pl_stats_filter_player",
        "pl_stats_filter_opp",
        "pl_mkt_filter_team",
        "pl_mkt_filter_lane",
        "pl_mkt_filter_market",
        "pl_mkt_filter_player",
    ]
    for key in filter_keys:
        at2 = core_new_apptest_for_file(root / "plays_app.py")
        at2.session_state["_probe_skip_csv_bootstrap_gate"] = True
        core_run_apptest_quiet(at2, timeout)
        if has_exc(at2):
            record(f"{key}:bootstrap", False, "erro no bootstrap")
            continue
        sels2 = {s.key: s for s in at2.selectbox}
        if "teamA" in sels2 and "teamB" in sels2:
            oa = [str(x) for x in list(getattr(sels2["teamA"], "options", []) or []) if str(x)]
            ob = [str(x) for x in list(getattr(sels2["teamB"], "options", []) or []) if str(x)]
            if oa and ob:
                t1 = oa[0]
                t2 = next((x for x in ob if x != t1), ob[0])
                at2.session_state["teamA"] = t1
                at2.session_state["teamB"] = t2
                at2.session_state["bo"] = 3
                at2.session_state["flow_stage"] = "results"
                at2.session_state["_analysis_force_once"] = True
                core_run_apptest_quiet(at2, timeout)
                at2.session_state["selected_tab_names"] = ["Players"]
                at2.session_state["ui_page_mode"] = "Completo"
                core_run_apptest_quiet(at2, timeout)
        at2.session_state[key] = "___INVALID___"
        core_run_apptest_quiet(at2, timeout)
        assert_no_exc(at2, f"invalid_filter={key}")

    fails = [s for s in steps if not s[1]]
    print("\nSUMMARY")
    print(f"steps={len(steps)} fails={len(fails)}")
    for name, ok, detail in steps:
        print(f"- {name}: {'OK' if ok else 'FAIL'} | {detail}")
    return 0 if not fails else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stress-test the Streamlit UI flow and stale state handling.")
    ap.add_argument("--timeout", type=int, default=240, help="Timeout per AppTest run (seconds).")
    args = ap.parse_args(argv)
    return _run_probe(timeout=max(60, int(args.timeout or 240)))


if __name__ == "__main__":
    raise SystemExit(main())
