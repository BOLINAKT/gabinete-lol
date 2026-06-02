"""Fix Portuguese diacritic mojibake — ONLY in user-visible UI strings.

Strategy: targets string literals that are:
  - First positional argument to st.<ui_method>(...)
  - Value of a label="..." / help="..." / placeholder="..." kwarg

Leaves alone:
  - dict keys, variable comparisons, tab identifiers
  - docstrings, comments
  - test fixtures

Usage
-----
    python tools/fix_ui_diacritics.py --dry          # preview
    python tools/fix_ui_diacritics.py --apply        # write
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(__file__).resolve().parent.parent


# Broken → fixed mappings (safe set — diacritic-only changes, no semantic shift)
WORD_FIXES: Dict[str, str] = {
    "analise": "análise",
    "informacao": "informação",
    "informacoes": "informações",
    "opcao": "opção",
    "opcoes": "opções",
    "selecao": "seleção",
    "configuracao": "configuração",
    "configuracoes": "configurações",
    "exibicao": "exibição",
    "navegacao": "navegação",
    "previsao": "previsão",
    "previsoes": "previsões",
    "atencao": "atenção",
    "operacao": "operação",
    "operacoes": "operações",
    "estagio": "estágio",
    "secao": "seção",
    "secoes": "seções",
    "atribuicao": "atribuição",
    "aplicacao": "aplicação",
    "aplicacoes": "aplicações",
    "edicao": "edição",
    "definicao": "definição",
    "verificacao": "verificação",
    "composicao": "composição",
    "posicao": "posição",
    "posicoes": "posições",
    "representacao": "representação",
    "consideracao": "consideração",
    "consideracoes": "considerações",
    "inclusao": "inclusão",
    "exclusao": "exclusão",
    "inicializacao": "inicialização",
    "sugestao": "sugestão",
    "sugestoes": "sugestões",
    "metrica": "métrica",
    "metricas": "métricas",
    "periodo": "período",
    "periodos": "períodos",
    "numero": "número",
    "numeros": "números",
    "historico": "histórico",
    "historicos": "históricos",
    "memoria": "memória",
    "memorias": "memórias",
    "campeoes": "campeões",
    "distancia": "distância",
    "funcao": "função",
    "funcoes": "funções",
    "calculo": "cálculo",
    "calculos": "cálculos",
    "padrao": "padrão",
    "padroes": "padrões",
    "alteracao": "alteração",
    "alteracoes": "alterações",
    "execucao": "execução",
    "execucoes": "execuções",
    "manutencao": "manutenção",
    "decisao": "decisão",
    "decisoes": "decisões",
    "regiao": "região",
    "regioes": "regiões",
    "conclusao": "conclusão",
    "conclusoes": "conclusões",
    "rapido": "rápido",
    "rapida": "rápida",
    "rapidos": "rápidos",
    "rapidas": "rápidas",
    "critico": "crítico",
    "critica": "crítica",
    "minimo": "mínimo",
    "minima": "mínima",
    "maximo": "máximo",
    "maxima": "máxima",
    "automatico": "automático",
    "automatica": "automática",
    "tecnico": "técnico",
    "tecnica": "técnica",
    "logico": "lógico",
    "logica": "lógica",
    "analitico": "analítico",
    "analitica": "analítica",
    "estatistica": "estatística",
    "estatisticas": "estatísticas",
    "estrategico": "estratégico",
    "estrategica": "estratégica",
    "publico": "público",
    "publica": "pública",
    "porem": "porém",
    "alem": "além",
    "tambem": "também",
    "esta": "está",
    "estao": "estão",
    "sao": "são",
    "nao": "não",
    "vao": "vão",
    "so": "só",
    "ja": "já",
    "ate": "até",
}


# Patterns that mark a string as USER-VISIBLE (i.e., gets rendered to UI).
# We only fix matches inside one of these patterns.
ST_UI_METHODS = (
    "markdown", "caption", "info", "warning", "error", "success",
    "button", "metric", "expander", "container", "code",
    "text", "title", "subheader", "header", "write",
    "text_input", "number_input", "selectbox", "radio", "toggle",
    "checkbox", "multiselect", "slider", "text_area", "color_picker",
    "date_input", "time_input", "file_uploader", "camera_input",
    "form", "form_submit_button", "download_button",
    "tabs", "popover",
)

# Build regex: match `st.METHOD(` and capture the entire call's first argument string.
ST_METHOD_PATTERN = "|".join(re.escape(m) for m in ST_UI_METHODS)


def _replace_in_string(s: str) -> Tuple[str, int]:
    """Apply WORD_FIXES to a string s, return (new_s, n_changes)."""
    new_s = s
    n = 0
    for broken, fixed in WORD_FIXES.items():
        pattern_lower = r"(?<![A-Za-zÀ-ÿ_])" + re.escape(broken) + r"(?![A-Za-zÀ-ÿ_])"
        replaced, c = re.subn(pattern_lower, fixed, new_s)
        if c:
            new_s = replaced
            n += c
        pattern_cap = r"(?<![A-Za-zÀ-ÿ_])" + re.escape(broken.capitalize()) + r"(?![A-Za-zÀ-ÿ_])"
        replaced, c = re.subn(pattern_cap, fixed.capitalize(), new_s)
        if c:
            new_s = replaced
            n += c
    return new_s, n


def fix_text(text: str) -> Tuple[str, List[Tuple[int, str, str]]]:
    """Targeted fix: only modifies strings inside st.<ui_method>(...)
    first positional argument, or after label=/help=/placeholder=/value= kwargs
    inside an st.* call.
    """
    changes: List[Tuple[int, str, str]] = []
    new_text = text

    # Regex: match a string literal (single or double quoted, no escapes inside)
    # immediately following `st.METHOD(` or after `label=`/`help=`/`placeholder=`/`value=`
    target_kwargs = ("label", "help", "placeholder", "value")
    kwargs_alt = "|".join(target_kwargs)

    # First-arg pattern: st.METHOD( "..." OR  st.METHOD( '...'
    first_arg = re.compile(
        r"(\bst\.(?:" + ST_METHOD_PATTERN + r")\s*\(\s*)"
        r"(['\"])((?:(?!\2).)*?)\2"
    )
    # kwarg pattern: label="..." or help='...'
    kwarg_arg = re.compile(
        r"\b(" + kwargs_alt + r")\s*=\s*(['\"])((?:(?!\2).)*?)\2"
    )

    def _replace_match(m: re.Match) -> str:
        prefix, quote, inner = m.group(1), m.group(2), m.group(3)
        new_inner, n_changes = _replace_in_string(inner)
        if n_changes > 0:
            line_no = new_text.count("\n", 0, m.start()) + 1
            changes.append((line_no, inner[:80], new_inner[:80]))
        return f"{prefix}{quote}{new_inner}{quote}"

    new_text = first_arg.sub(_replace_match, new_text)

    def _replace_kwarg(m: re.Match) -> str:
        name, quote, inner = m.group(1), m.group(2), m.group(3)
        new_inner, n_changes = _replace_in_string(inner)
        if n_changes > 0:
            line_no = new_text.count("\n", 0, m.start()) + 1
            changes.append((line_no, inner[:80], new_inner[:80]))
        return f"{name}={quote}{new_inner}{quote}"

    new_text = kwarg_arg.sub(_replace_kwarg, new_text)

    return new_text, changes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--paths", nargs="*", default=["app_core", "plays_app.py"])
    args = ap.parse_args()
    if not args.dry and not args.apply:
        ap.error("Specify --dry or --apply")

    files: List[Path] = []
    for p in args.paths:
        pp = ROOT / p
        if pp.is_dir():
            files.extend(sorted(pp.glob("*.py")))
        elif pp.is_file():
            files.append(pp)
    total_files = 0
    total_changes = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text, changes = fix_text(text)
        if not changes:
            continue
        total_files += 1
        total_changes += len(changes)
        print(f"\n=== {f.relative_to(ROOT)} ({len(changes)} edits) ===")
        for ln, before, after in changes[:6]:
            print(f"  L{ln}: {before}")
            print(f"     -> {after}")
        if len(changes) > 6:
            print(f"  ... ({len(changes) - 6} more)")
        if args.apply:
            f.write_text(new_text, encoding="utf-8")
    mode = "applied" if args.apply else "preview"
    print(f"\n[{mode}] Files: {total_files} | Edits: {total_changes}")


if __name__ == "__main__":
    main()
