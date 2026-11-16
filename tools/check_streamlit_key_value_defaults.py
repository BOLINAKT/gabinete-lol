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
DEFAULT_KWARGS = {"value", "default"}


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        yield path


def _is_streamlit_call(node: ast.Call) -> bool:
    fn = node.func
    return isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "st"


def main() -> int:
    violations: list[str] = []
    for path in _iter_python_files(ROOT):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception as exc:
            violations.append(f"{path}:parse_error:{type(exc).__name__}:{exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_streamlit_call(node):
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if "key" in kwargs and (kwargs & DEFAULT_KWARGS):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{getattr(node.func, 'attr', 'unknown')}")

    if violations:
        print("streamlit_key_value_defaults_guard=FAIL")
        for row in violations:
            print(row)
        return 2

    print("streamlit_key_value_defaults_guard=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
