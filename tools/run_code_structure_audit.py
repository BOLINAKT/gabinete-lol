from __future__ import annotations

import ast
import hashlib
import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Set


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [ROOT / "app_core", ROOT / "mlcore", ROOT / "tools"]
REPORT_PATH = ROOT / "ops" / "monitoring" / "code_structure_audit_report.json"
OVERSIZED_MODULE_LINE_LIMIT = 1200
TARGET_HELPERS = {
    "_f",
    "_clip_prob",
    "_logit",
    "_sigmoid",
    "_safe_logit",
    "_safe_sigmoid",
}


def _read_source(path: Path) -> str:
    last_error: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text()


def _iter_python_files() -> List[Path]:
    out: List[Path] = [ROOT / "plays_app.py"]
    for root in SOURCE_ROOTS:
        out.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted({path.resolve() for path in out})


def _module_name_for_path(path: Path) -> str:
    rel = path.resolve().relative_to(ROOT)
    parts = list(rel.parts)
    if parts == ["plays_app.py"]:
        return "plays_app"
    if parts[-1] == "__init__.py":
        return ".".join(parts[:-1])
    parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def _resolve_from_import(module_name: str, node: ast.ImportFrom) -> str | None:
    base = module_name.split(".")
    if module_name != "plays_app" and len(base) > 1:
        base = base[:-1]
    elif module_name == "plays_app":
        base = []
    if node.level:
        if node.level > len(base):
            resolved_parts: List[str] = []
        else:
            resolved_parts = base[: len(base) - node.level + 1]
    else:
        resolved_parts = []
    if node.module:
        resolved_parts.extend(str(node.module).split("."))
    if not resolved_parts:
        return None
    return ".".join(part for part in resolved_parts if part)


def _import_graph() -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = {}
    for path in _iter_python_files():
        try:
            src = _read_source(path)
            tree = ast.parse(src)
        except Exception:
            continue
        module_name = _module_name_for_path(path)
        imports: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        imports.add(str(alias.name))
            elif isinstance(node, ast.ImportFrom):
                resolved = _resolve_from_import(module_name, node)
                if resolved:
                    imports.add(resolved)
        graph[module_name] = imports
    return graph


def _helper_duplicates() -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for root in SOURCE_ROOTS:
        for path in root.rglob("*.py"):
            try:
                src = _read_source(path)
                tree = ast.parse(src)
            except Exception:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name not in TARGET_HELPERS:
                    continue
                body = ast.get_source_segment(src, node) or ""
                normalized = "\n".join(line.strip() for line in body.splitlines())
                fingerprint = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
                key = f"{node.name}:{fingerprint}"
                group = groups.setdefault(
                    key,
                    {"name": node.name, "hash": fingerprint, "occurrences": []},
                )
                group["occurrences"].append(
                    {"path": str(path.relative_to(ROOT)), "line": int(node.lineno)}
                )
    out = [group for group in groups.values() if len(group["occurrences"]) > 1]
    out.sort(key=lambda item: (-len(item["occurrences"]), item["name"], item["hash"]))
    return out


def _legacy_artifacts() -> List[str]:
    hits: List[str] = []
    for root in SOURCE_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(ROOT))
            name = path.name.lower()
            if name.endswith(".pyc") and ("_legacy" in rel or "_legacy_backup" in rel):
                hits.append(rel)
            elif name.endswith(("_recovered.py", "_restored.py", ".bak.py")):
                hits.append(rel)
    hits.sort()
    return hits


def _compiled_artifacts() -> List[str]:
    hits: List[str] = []
    for root in SOURCE_ROOTS:
        for path in root.rglob("*"):
            rel = str(path.relative_to(ROOT))
            name = path.name.lower()
            if path.is_dir() and name == "__pycache__":
                hits.append(rel)
            elif path.is_file() and name.endswith(".pyc"):
                hits.append(rel)
    hits.sort()
    return hits


def _archive_artifacts() -> List[str]:
    hits: List[str] = []
    for root in (ROOT / "app_core", ROOT / "mlcore", ROOT / "tools"):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".zip", ".tar", ".gz", ".bz2", ".xz"}:
                hits.append(str(path.relative_to(ROOT)))
    hits.sort()
    return hits


def _oversized_modules() -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for path in _iter_python_files():
        try:
            src = _read_source(path)
        except Exception:
            continue
        line_count = int(src.count("\n") + (1 if src else 0))
        if line_count < OVERSIZED_MODULE_LINE_LIMIT:
            continue
        hits.append(
            {
                "path": str(path.relative_to(ROOT)),
                "lines": line_count,
                "bytes": int(path.stat().st_size),
            }
        )
    hits.sort(key=lambda item: (-int(item["lines"]), item["path"]))
    return hits


def _stacked_streamlit_caches() -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for path in [ROOT / "plays_app.py", *(ROOT / "app_core").rglob("*.py")]:
        if "__pycache__" in path.parts:
            continue
        try:
            src = _read_source(path)
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = []
            for dec in node.decorator_list:
                text = ast.get_source_segment(src, dec) or ""
                if "cache_data" in text or "cache_resource" in text:
                    decorators.append(text.strip())
            if len(decorators) > 1:
                hits.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "function": str(node.name),
                        "line": int(node.lineno),
                        "decorators": decorators,
                    }
                )
    hits.sort(key=lambda item: (item["path"], int(item["line"])))
    return hits


def _unreferenced_app_core_modules() -> List[Dict[str, Any]]:
    graph = _import_graph()
    runtime_importers: Dict[str, Set[str]] = {}
    test_importers: Dict[str, Set[str]] = {}

    for importer, imports in graph.items():
        target_bucket = test_importers if importer.startswith("mlcore.tests.") else runtime_importers
        for imported in imports:
            target_bucket.setdefault(imported, set()).add(importer)

    hits: List[Dict[str, Any]] = []
    for path in sorted((ROOT / "app_core").glob("*.py")):
        if path.name == "__init__.py":
            continue
        module_name = _module_name_for_path(path)
        runtime_refs = sorted(runtime_importers.get(module_name, set()))
        test_refs = sorted(test_importers.get(module_name, set()))
        if runtime_refs:
            continue
        hits.append(
            {
                "path": str(path.relative_to(ROOT)),
                "module": module_name,
                "test_only": bool(test_refs),
                "test_importers": test_refs,
            }
        )
    return hits


def build_report() -> Dict[str, Any]:
    report = {
        "version": "code_structure_audit_v2",
        "helper_duplicate_groups": _helper_duplicates(),
        "legacy_artifacts": _legacy_artifacts(),
        "compiled_artifacts": _compiled_artifacts(),
        "archive_artifacts": _archive_artifacts(),
        "oversized_modules": _oversized_modules(),
        "stacked_streamlit_caches": _stacked_streamlit_caches(),
        "unreferenced_app_core_modules": _unreferenced_app_core_modules(),
    }
    report["summary"] = {
        "helper_duplicate_groups": len(report["helper_duplicate_groups"]),
        "legacy_artifacts": len(report["legacy_artifacts"]),
        "compiled_artifacts": len(report["compiled_artifacts"]),
        "archive_artifacts": len(report["archive_artifacts"]),
        "oversized_modules": len(report["oversized_modules"]),
        "stacked_streamlit_caches": len(report["stacked_streamlit_caches"]),
        "unreferenced_app_core_modules": len(report["unreferenced_app_core_modules"]),
    }
    return report


def main() -> int:
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
