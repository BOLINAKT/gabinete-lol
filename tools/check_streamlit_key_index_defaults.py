from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "backups",
    "evidence",
    "lixeira",
    "stabilization_snapshots",
}
WIDGETS = {"selectbox", "radio", "multiselect", "slider", "number_input", "select_slider"}


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        yield path


def _is_streamlit_widget_call(node: ast.Call) -> bool:
    fn = node.func
    return (
        isinstance(fn, ast.Attribute)
        and isinstance(fn.value, ast.Name)
        and fn.value.id == "st"
        and fn.attr in WIDGETS
    )


def _detect_violation(node: ast.Call) -> str | None:
    fn = node.func
    if not isinstance(fn, ast.Attribute):
        return None
    kwargs = {kw.arg for kw in node.keywords if kw.arg}
    if "key" not in kwargs:
        return None
    if fn.attr in {"selectbox", "radio"} and "index" in kwargs:
        return "index_kw"
    if fn.attr == "multiselect" and "default" in kwargs:
        return "default_kw"
    if fn.attr == "select_slider" and "value" in kwargs:
        return "value_kw"
    if fn.attr == "slider" and len(node.args) >= 4:
        return "value_pos"
    if fn.attr == "number_input" and len(node.args) >= 2:
        return "value_pos"
    return None


def main() -> int:
    violations: list[str] = []
    for path in _iter_python_files(ROOT):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception as exc:
            violations.append(f"{path}:parse_error:{type(exc).__name__}:{exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_streamlit_widget_call(node):
                continue
            violation = _detect_violation(node)
            if violation:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{getattr(node.func, 'attr', 'unknown')}:{violation}"
                )

    if violations:
        print("streamlit_key_index_defaults_guard=FAIL")
        for row in violations:
            print(row)
        return 2

    print("streamlit_key_index_defaults_guard=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
