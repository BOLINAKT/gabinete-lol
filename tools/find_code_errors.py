from __future__ import annotations

import argparse
import ast
import builtins
import json
import os
import subprocess
import symtable
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS: tuple[Path, ...] = (
    ROOT / "plays_app.py",
    ROOT / "app_core",
    ROOT / "mlcore",
    ROOT / "tools",
)
IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "evidence",
    "ops",
}
BUILTIN_NAMES = set(dir(builtins))
MODULE_MAGIC_NAMES = {
    "__name__",
    "__file__",
    "__package__",
    "__loader__",
    "__spec__",
    "__doc__",
    "__cached__",
    "__annotations__",
}


def _default_out_path(profile: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "evidence" / f"code_error_scan_{profile}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "report.json"


def _read_source(path: Path) -> str:
    last_error: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except Exception as exc:  # pragma: no cover - defensive fallback
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _looks_ignored(path: Path) -> bool:
    return any(part in IGNORED_PARTS for part in path.parts)


def collect_python_files(raw_paths: Sequence[str] | None = None) -> list[Path]:
    targets = [Path(p) for p in (raw_paths or ())]
    if not targets:
        targets = list(DEFAULT_TARGETS)

    resolved: set[Path] = set()
    for raw in targets:
        path = raw if raw.is_absolute() else (ROOT / raw)
        if not path.exists():
            continue
        if path.is_file():
            rel_or_abs = path.resolve()
            try:
                rel_or_abs = rel_or_abs.relative_to(ROOT)
            except ValueError:
                pass
            if path.suffix == ".py" and not _looks_ignored(rel_or_abs):
                resolved.add(path.resolve())
            continue
        for sub in path.rglob("*.py"):
            rel = sub.resolve().relative_to(ROOT)
            if _looks_ignored(rel):
                continue
            resolved.add(sub.resolve())
    return sorted(resolved)


def find_syntax_errors(paths: Sequence[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in paths:
        try:
            src = _read_source(path)
            compile(src, str(path), "exec")
        except SyntaxError as exc:
            out.append(
                {
                    "path": _display_path(path),
                    "line": int(exc.lineno or 0),
                    "column": int(exc.offset or 0),
                    "error": str(exc.msg or "syntax error"),
                    "text": str(exc.text or "").strip(),
                }
            )
        except Exception as exc:
            out.append(
                {
                    "path": _display_path(path),
                    "line": 0,
                    "column": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "text": "",
                }
            )
    return out


def _target_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {str(node.id)}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out: set[str] = set()
        for elt in node.elts:
            out.update(_target_names(elt))
        return out
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return set()


def _pattern_bound_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.MatchAs) and child.name:
            out.add(str(child.name))
        elif isinstance(child, ast.MatchStar) and child.name:
            out.add(str(child.name))
    return out


class _LoadNameVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: list[tuple[str, int, int]] = []

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.names.append((str(node.id), int(getattr(node, "lineno", 0) or 0), int(getattr(node, "col_offset", 0) or 0)))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return


def _loaded_names(node: ast.AST | None) -> list[tuple[str, int, int]]:
    if node is None:
        return []
    vis = _LoadNameVisitor()
    vis.visit(node)
    return list(vis.names)


def _scope_key(*, scope_type: str, name: str, lineno: int) -> tuple[str, str, int]:
    return (str(scope_type), str(name), int(lineno))


def _scope_key_for_node(node: ast.AST) -> tuple[str, str, int] | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _scope_key(scope_type="function", name=str(node.name), lineno=int(getattr(node, "lineno", 0) or 0))
    if isinstance(node, ast.ClassDef):
        return _scope_key(scope_type="class", name=str(node.name), lineno=int(getattr(node, "lineno", 0) or 0))
    return None


def _build_symtable_map(table: symtable.SymbolTable) -> dict[tuple[str, str, int], symtable.SymbolTable]:
    out = {
        _scope_key(scope_type=str(table.get_type()), name=str(table.get_name()), lineno=int(table.get_lineno() or 0)): table,
    }
    for child in table.get_children():
        out.update(_build_symtable_map(child))
    return out


class _FunctionLocalCollector:
    def __init__(self) -> None:
        self.locals: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()

    def collect(self, statements: Sequence[ast.stmt]) -> tuple[set[str], set[str], set[str]]:
        for stmt in statements:
            self._visit_stmt(stmt)
        return set(self.locals), set(self.globals), set(self.nonlocals)

    def _visit_block(self, statements: Sequence[ast.stmt]) -> None:
        for stmt in statements:
            self._visit_stmt(stmt)

    def _visit_stmt(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.locals.add(str(stmt.name))
            return
        if isinstance(stmt, ast.Global):
            self.globals.update(str(x) for x in stmt.names)
            return
        if isinstance(stmt, ast.Nonlocal):
            self.nonlocals.update(str(x) for x in stmt.names)
            return
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                self.locals.update(_target_names(target))
            return
        if isinstance(stmt, ast.AnnAssign):
            self.locals.update(_target_names(stmt.target))
            return
        if isinstance(stmt, ast.AugAssign):
            self.locals.update(_target_names(stmt.target))
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self.locals.update(_target_names(stmt.target))
            self._visit_block(stmt.body)
            self._visit_block(stmt.orelse)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                self.locals.update(_target_names(item.optional_vars))
            self._visit_block(stmt.body)
            return
        if isinstance(stmt, ast.If):
            self._visit_block(stmt.body)
            self._visit_block(stmt.orelse)
            return
        if isinstance(stmt, ast.While):
            self._visit_block(stmt.body)
            self._visit_block(stmt.orelse)
            return
        if isinstance(stmt, ast.Try):
            self._visit_block(stmt.body)
            self._visit_block(stmt.orelse)
            self._visit_block(stmt.finalbody)
            for handler in stmt.handlers:
                if handler.name:
                    self.locals.add(str(handler.name))
                self._visit_block(handler.body)
            return
        if isinstance(stmt, ast.Match):
            for case in stmt.cases:
                self.locals.update(_pattern_bound_names(case.pattern))
                self._visit_block(case.body)
            return
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                self.locals.add(str(alias.asname or alias.name.split(".", 1)[0]))
            return
        if isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                self.locals.add(str(alias.asname or alias.name))
            return


def _parameter_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    out: set[str] = set()
    args = fn.args
    for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        out.add(str(arg.arg))
    if args.vararg:
        out.add(str(args.vararg.arg))
    if args.kwarg:
        out.add(str(args.kwarg.arg))
    return out


def _line_excerpt(lines: Sequence[str], line_no: int) -> str:
    if line_no <= 0 or line_no > len(lines):
        return ""
    return str(lines[line_no - 1]).strip()


def _record_load_issues(
    *,
    node: ast.AST | None,
    assigned: set[str],
    local_names: set[str],
    global_like: set[str],
    issues: list[dict[str, Any]],
    seen: set[tuple[str, str, int]],
    path: Path,
    function_name: str,
    source_lines: Sequence[str],
) -> None:
    for name, line_no, col_no in _loaded_names(node):
        if name not in local_names:
            continue
        if name in assigned or name in global_like or name in BUILTIN_NAMES:
            continue
        key = (str(path), str(name), int(line_no))
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            {
                "path": _display_path(path),
                "function": function_name,
                "name": str(name),
                "line": int(line_no),
                "column": int(col_no) + 1,
                "snippet": _line_excerpt(source_lines, int(line_no)),
                "reason": "local variable is loaded before a prior assignment in the same function",
            }
        )


def _analyze_block(
    statements: Sequence[ast.stmt],
    *,
    assigned: set[str],
    local_names: set[str],
    global_like: set[str],
    issues: list[dict[str, Any]],
    seen: set[tuple[str, str, int]],
    path: Path,
    function_name: str,
    source_lines: Sequence[str],
) -> set[str]:
    current = set(assigned)
    for stmt in statements:
        current = _analyze_stmt(
            stmt,
            assigned=current,
            local_names=local_names,
            global_like=global_like,
            issues=issues,
            seen=seen,
            path=path,
            function_name=function_name,
            source_lines=source_lines,
        )
    return current


def _analyze_stmt(
    stmt: ast.stmt,
    *,
    assigned: set[str],
    local_names: set[str],
    global_like: set[str],
    issues: list[dict[str, Any]],
    seen: set[tuple[str, str, int]],
    path: Path,
    function_name: str,
    source_lines: Sequence[str],
) -> set[str]:
    current = set(assigned)

    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return current | {str(stmt.name)}
    if isinstance(stmt, (ast.Global, ast.Nonlocal)):
        return current
    if isinstance(stmt, ast.Import):
        return current | {str(alias.asname or alias.name.split(".", 1)[0]) for alias in stmt.names}
    if isinstance(stmt, ast.ImportFrom):
        return current | {str(alias.asname or alias.name) for alias in stmt.names}
    if isinstance(stmt, ast.Assign):
        _record_load_issues(
            node=stmt.value,
            assigned=current,
            local_names=local_names,
            global_like=global_like,
            issues=issues,
            seen=seen,
            path=path,
            function_name=function_name,
            source_lines=source_lines,
        )
        for target in stmt.targets:
            _record_load_issues(
                node=target if not isinstance(target, ast.Name) else None,
                assigned=current,
                local_names=local_names,
                global_like=global_like,
                issues=issues,
                seen=seen,
                path=path,
                function_name=function_name,
                source_lines=source_lines,
            )
        assigned_now = set()
        for target in stmt.targets:
            assigned_now.update(_target_names(target))
        return current | assigned_now
    if isinstance(stmt, ast.AnnAssign):
        _record_load_issues(
            node=stmt.value,
            assigned=current,
            local_names=local_names,
            global_like=global_like,
            issues=issues,
            seen=seen,
            path=path,
            function_name=function_name,
            source_lines=source_lines,
        )
        return current | _target_names(stmt.target)
    if isinstance(stmt, ast.AugAssign):
        _record_load_issues(
            node=stmt.target,
            assigned=current,
            local_names=local_names,
            global_like=global_like,
            issues=issues,
            seen=seen,
            path=path,
            function_name=function_name,
            source_lines=source_lines,
        )
        _record_load_issues(
            node=stmt.value,
            assigned=current,
            local_names=local_names,
            global_like=global_like,
            issues=issues,
            seen=seen,
            path=path,
            function_name=function_name,
            source_lines=source_lines,
        )
        return current | _target_names(stmt.target)
    if isinstance(stmt, ast.Expr):
        _record_load_issues(node=stmt.value, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    if isinstance(stmt, ast.Return):
        _record_load_issues(node=stmt.value, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    if isinstance(stmt, ast.Raise):
        _record_load_issues(node=stmt.exc, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        _record_load_issues(node=stmt.cause, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    if isinstance(stmt, ast.Assert):
        _record_load_issues(node=stmt.test, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        _record_load_issues(node=stmt.msg, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    if isinstance(stmt, ast.If):
        _record_load_issues(node=stmt.test, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        body_out = _analyze_block(stmt.body, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        else_out = _analyze_block(stmt.orelse, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines) if stmt.orelse else set(current)
        return current | (body_out & else_out)
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        _record_load_issues(node=stmt.iter, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        loop_assigned = current | _target_names(stmt.target)
        _analyze_block(stmt.body, assigned=set(loop_assigned), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        _analyze_block(stmt.orelse, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    if isinstance(stmt, ast.While):
        _record_load_issues(node=stmt.test, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        _analyze_block(stmt.body, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        _analyze_block(stmt.orelse, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        entered = set(current)
        for item in stmt.items:
            _record_load_issues(node=item.context_expr, assigned=entered, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
            entered |= _target_names(item.optional_vars)
        body_out = _analyze_block(stmt.body, assigned=set(entered), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current | body_out
    if isinstance(stmt, ast.Try):
        body_out = _analyze_block(stmt.body, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        handler_outs: list[set[str]] = []
        for handler in stmt.handlers:
            handler_assigned = set(current)
            if handler.type is not None:
                _record_load_issues(node=handler.type, assigned=handler_assigned, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
            if handler.name:
                handler_assigned.add(str(handler.name))
            handler_outs.append(
                _analyze_block(handler.body, assigned=handler_assigned, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
            )
        orelse_out = _analyze_block(stmt.orelse, assigned=set(body_out), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        _analyze_block(stmt.finalbody, assigned=set(current), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        after_try = current | body_out | orelse_out
        for handler_out in handler_outs:
            after_try |= handler_out
        return after_try
    if isinstance(stmt, ast.Match):
        _record_load_issues(node=stmt.subject, assigned=current, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        for case in stmt.cases:
            case_assigned = current | _pattern_bound_names(case.pattern)
            _record_load_issues(node=case.guard, assigned=case_assigned, local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
            _analyze_block(case.body, assigned=set(case_assigned), local_names=local_names, global_like=global_like, issues=issues, seen=seen, path=path, function_name=function_name, source_lines=source_lines)
        return current
    return current


def find_unbound_local_suspects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for path in paths:
        try:
            source = _read_source(path)
            tree = ast.parse(source)
        except Exception:
            continue
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            collector = _FunctionLocalCollector()
            local_names, global_names, nonlocal_names = collector.collect(node.body)
            local_names |= _parameter_names(node)
            local_names -= global_names
            local_names -= nonlocal_names
            _analyze_block(
                node.body,
                assigned=_parameter_names(node),
                local_names=local_names,
                global_like=(global_names | nonlocal_names),
                issues=issues,
                seen=seen,
                path=path,
                function_name=str(node.name),
                source_lines=source_lines,
            )
    issues.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["name"])))
    return issues


def _module_defined_names(tree: ast.Module) -> set[str]:
    collector = _FunctionLocalCollector()
    local_names, _, _ = collector.collect(tree.body)
    return set(local_names)


def find_undefined_name_suspects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int]] = set()
    for path in paths:
        try:
            source = _read_source(path)
            tree = ast.parse(source)
            scope_map = _build_symtable_map(symtable.symtable(source, str(path), "exec"))
        except Exception:
            continue
        source_lines = source.splitlines()
        module_names = _module_defined_names(tree) | MODULE_MAGIC_NAMES
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            scope_key = _scope_key_for_node(node)
            if scope_key is None:
                continue
            table = scope_map.get(scope_key)
            if table is None:
                continue
            for stmt in getattr(node, "body", []):
                for name, line_no, col_no in _loaded_names(stmt):
                    if name in BUILTIN_NAMES or name in module_names:
                        continue
                    try:
                        symbol = table.lookup(name)
                    except KeyError:
                        symbol = None
                    if symbol is not None and (
                        symbol.is_local()
                        or symbol.is_parameter()
                        or symbol.is_imported()
                        or symbol.is_nonlocal()
                        or symbol.is_free()
                    ):
                        continue
                    key = (str(path), str(node.name), str(name), int(line_no))
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(
                        {
                            "path": _display_path(path),
                            "scope": str(node.name),
                            "scope_type": "class" if isinstance(node, ast.ClassDef) else "function",
                            "name": str(name),
                            "line": int(line_no),
                            "column": int(col_no) + 1,
                            "snippet": _line_excerpt(source_lines, int(line_no)),
                            "reason": "name is referenced but not defined in local, enclosing, module, or builtin scope",
                        }
                    )
    issues.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["name"])))
    return issues


def _constant_truthiness(node: ast.AST | None) -> tuple[bool, str] | None:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
        return (bool(value), repr(value))
    except Exception:
        pass
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _constant_truthiness(node.operand)
        if inner is None:
            return None
        return (not bool(inner[0]), f"not {inner[1]}")
    if isinstance(node, ast.BoolOp):
        values: list[tuple[bool, str]] = []
        for child in node.values:
            truth = _constant_truthiness(child)
            if truth is None:
                return None
            values.append(truth)
        if isinstance(node.op, ast.And):
            return (all(part[0] for part in values), " and ".join(part[1] for part in values))
        if isinstance(node.op, ast.Or):
            return (any(part[0] for part in values), " or ".join(part[1] for part in values))
    return None


class _ConstantBranchVisitor(ast.NodeVisitor):
    def __init__(self, *, path: Path, source_lines: Sequence[str]) -> None:
        self.path = path
        self.source_lines = source_lines
        self.scope_stack: list[str] = ["<module>"]
        self.issues: list[dict[str, Any]] = []

    def _scope_name(self) -> str:
        return str(self.scope_stack[-1])

    def _add_issue(
        self,
        *,
        node: ast.AST,
        kind: str,
        reason: str,
        truthiness: str,
        dead_branch: str,
    ) -> None:
        line_no = int(getattr(node, "lineno", 0) or 0)
        col_no = int(getattr(node, "col_offset", 0) or 0) + 1
        self.issues.append(
            {
                "path": _display_path(self.path),
                "scope": self._scope_name(),
                "kind": str(kind),
                "line": line_no,
                "column": col_no,
                "truthiness": str(truthiness),
                "dead_branch": str(dead_branch),
                "snippet": _line_excerpt(self.source_lines, line_no),
                "reason": str(reason),
            }
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_stack.append(str(node.name))
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(str(node.name))
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(str(node.name))
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_If(self, node: ast.If) -> None:
        truth = _constant_truthiness(node.test)
        if truth is not None:
            truth_label = "truthy" if bool(truth[0]) else "falsy"
            if bool(truth[0]) and list(node.orelse or []):
                dead_branch = "orelse"
                reason = "if condition is statically truthy"
            elif not bool(truth[0]):
                dead_branch = "body"
                reason = "if condition is statically falsy"
            else:
                dead_branch = ""
                reason = ""
            if reason:
                self._add_issue(
                    node=node,
                    kind="if",
                    reason=reason,
                    truthiness=f"{truth_label} ({truth[1]})",
                    dead_branch=dead_branch,
                )
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        truth = _constant_truthiness(node.test)
        if truth is not None and not bool(truth[0]):
            self._add_issue(
                node=node,
                kind="while",
                reason="while condition is statically falsy",
                truthiness=f"falsy ({truth[1]})",
                dead_branch="body",
            )
        self.generic_visit(node)


def find_constant_branch_suspects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for path in paths:
        try:
            source = _read_source(path)
            tree = ast.parse(source)
        except Exception:
            continue
        vis = _ConstantBranchVisitor(path=path, source_lines=source.splitlines())
        vis.visit(tree)
        issues.extend(vis.issues)
    issues.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["kind"])))
    return issues


def find_mutable_default_suspects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for path in paths:
        try:
            source = _read_source(path)
            tree = ast.parse(source)
        except Exception:
            continue
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional_defaults = list(node.args.defaults)
            positional_names = [arg.arg for arg in list(node.args.posonlyargs) + list(node.args.args)]
            if positional_defaults:
                positional_pairs = zip(positional_names[-len(positional_defaults):], positional_defaults)
            else:
                positional_pairs = []
            keyword_pairs = [
                (arg.arg, default)
                for arg, default in zip(list(node.args.kwonlyargs), list(node.args.kw_defaults))
                if default is not None
            ]
            for param_name, default_node in list(positional_pairs) + keyword_pairs:
                if not isinstance(default_node, (ast.List, ast.Dict, ast.Set)):
                    continue
                line_no = int(getattr(default_node, "lineno", getattr(node, "lineno", 0)) or 0)
                col_no = int(getattr(default_node, "col_offset", 0) or 0) + 1
                issues.append(
                    {
                        "path": _display_path(path),
                        "function": str(node.name),
                        "name": str(param_name),
                        "line": line_no,
                        "column": col_no,
                        "snippet": _line_excerpt(source_lines, line_no),
                        "reason": f"parameter '{param_name}' uses a mutable default value",
                        "mutable_type": type(default_node).__name__.lower(),
                    }
                )
    issues.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["name"])))
    return issues


def _literal_hashable_key(node: ast.AST | None) -> tuple[bool, Any]:
    if node is None:
        return (False, None)
    try:
        value = ast.literal_eval(node)
    except Exception:
        return (False, None)
    try:
        hash(value)
    except Exception:
        return (False, None)
    return (True, value)


def find_duplicate_dict_key_suspects(paths: Sequence[Path]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, int, Any]] = set()
    for path in paths:
        try:
            source = _read_source(path)
            tree = ast.parse(source)
        except Exception:
            continue
        source_lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            first_seen: dict[Any, tuple[int, int]] = {}
            for key_node in list(node.keys):
                ok, key_value = _literal_hashable_key(key_node)
                if not ok:
                    continue
                line_no = int(getattr(key_node, "lineno", getattr(node, "lineno", 0)) or 0)
                col_no = int(getattr(key_node, "col_offset", 0) or 0) + 1
                if key_value not in first_seen:
                    first_seen[key_value] = (line_no, col_no)
                    continue
                dedupe_key = (str(path), line_no, key_value)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                first_line, first_col = first_seen[key_value]
                issues.append(
                    {
                        "path": _display_path(path),
                        "key": repr(key_value),
                        "line": line_no,
                        "column": col_no,
                        "snippet": _line_excerpt(source_lines, line_no),
                        "reason": f"dict literal repeats key {key_value!r}; later value overrides the earlier one",
                        "first_occurrence_line": int(first_line),
                        "first_occurrence_column": int(first_col),
                    }
                )
    issues.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["key"])))
    return issues


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    root_s = str(ROOT)
    pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
    if pythonpath:
        if root_s not in pythonpath.split(os.pathsep):
            env["PYTHONPATH"] = root_s + os.pathsep + pythonpath
    else:
        env["PYTHONPATH"] = root_s
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_cmd(cmd: Sequence[str], *, timeout: int) -> dict[str, Any]:
    try:
        cp = subprocess.run(
            [str(x) for x in cmd],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30, int(timeout)),
            env=_subprocess_env(),
        )
        output = ((cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")).strip()
        return {
            "ok": int(cp.returncode) == 0,
            "returncode": int(cp.returncode),
            "output": output,
            "cmd": [str(x) for x in cmd],
            "error": "",
        }
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else "")).strip()
        return {
            "ok": False,
            "returncode": 124,
            "output": output,
            "cmd": [str(x) for x in cmd],
            "error": f"timeout>{int(timeout)}s",
        }
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "returncode": None,
            "output": "",
            "cmd": [str(x) for x in cmd],
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_repo_checks(*, profile: str, include_repo_checks: bool) -> list[dict[str, Any]]:
    if not include_repo_checks:
        return []
    specs: list[tuple[str, list[str], int]] = [
        (
            "streamlit_key_value_defaults_guard",
            [sys.executable, "tools/check_streamlit_key_value_defaults.py"],
            120,
        ),
        (
            "streamlit_key_index_defaults_guard",
            [sys.executable, "tools/check_streamlit_key_index_defaults.py"],
            120,
        ),
    ]
    if str(profile) == "full":
        specs.append(
            (
                "stabilization_gate_quick",
                [sys.executable, "tools/run_stabilization_gate.py", "--profile", "quick", "--timeout", "120"],
                900,
            )
        )
    rows: list[dict[str, Any]] = []
    for name, cmd, timeout in specs:
        res = _run_cmd(cmd, timeout=timeout)
        row = {
            "check": str(name),
            "ok": bool(res.get("ok")),
            "returncode": res.get("returncode"),
            "cmd": list(res.get("cmd") or []),
            "error": str(res.get("error") or ""),
            "output_tail": str(res.get("output") or "")[-6000:],
        }
        rows.append(row)
        print(f"[{'OK' if row['ok'] else 'FAIL'}] {name}")
    return rows


def _print_issue_preview(label: str, rows: Sequence[dict[str, Any]], limit: int = 8) -> None:
    if not rows:
        return
    print(f"\n{label}:")
    for row in list(rows)[: max(1, int(limit))]:
        path = str(row.get("path") or "")
        line = int(row.get("line") or 0)
        name = str(row.get("name") or row.get("kind") or row.get("error") or row.get("reason") or "").strip()
        snippet = str(row.get("snippet") or row.get("text") or "").strip()
        suffix = f" :: {snippet}" if snippet else ""
        print(f"- {path}:{line} {name}{suffix}")


def build_report(
    *,
    profile: str,
    paths: Sequence[Path],
    syntax_errors: Sequence[dict[str, Any]],
    unbound_local_suspects: Sequence[dict[str, Any]],
    undefined_name_suspects: Sequence[dict[str, Any]],
    constant_branch_suspects: Sequence[dict[str, Any]],
    mutable_default_suspects: Sequence[dict[str, Any]],
    duplicate_dict_key_suspects: Sequence[dict[str, Any]],
    repo_checks: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    failed_repo_checks = [row for row in repo_checks if not bool(row.get("ok"))]
    if syntax_errors or failed_repo_checks:
        decision = "fail"
    elif (
        unbound_local_suspects
        or undefined_name_suspects
        or constant_branch_suspects
        or mutable_default_suspects
        or duplicate_dict_key_suspects
    ):
        decision = "warn"
    else:
        decision = "clean"
    return {
        "version": "code_error_scan_v3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": str(profile),
        "scanned_files": len(paths),
        "decision": decision,
        "summary": {
            "syntax_errors": len(syntax_errors),
            "unbound_local_suspects": len(unbound_local_suspects),
            "undefined_name_suspects": len(undefined_name_suspects),
            "constant_branch_suspects": len(constant_branch_suspects),
            "mutable_default_suspects": len(mutable_default_suspects),
            "duplicate_dict_key_suspects": len(duplicate_dict_key_suspects),
            "repo_checks_total": len(repo_checks),
            "repo_checks_failed": len(failed_repo_checks),
        },
        "files": [_display_path(path) for path in paths],
        "syntax_errors": list(syntax_errors),
        "unbound_local_suspects": list(unbound_local_suspects),
        "undefined_name_suspects": list(undefined_name_suspects),
        "constant_branch_suspects": list(constant_branch_suspects),
        "mutable_default_suspects": list(mutable_default_suspects),
        "duplicate_dict_key_suspects": list(duplicate_dict_key_suspects),
        "repo_checks": list(repo_checks),
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan the repo for likely code errors and emit a JSON report.")
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--path", action="append", default=[], help="Optional file or directory to scan. Can be repeated.")
    ap.add_argument("--out", default="", help="Optional JSON report path.")
    ap.add_argument(
        "--include-repo-checks",
        action="store_true",
        help="Run repo-level guards in addition to static scanning. Default only when no custom path is provided.",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    os.chdir(ROOT)
    paths = collect_python_files(args.path)
    include_repo_checks = bool(args.include_repo_checks or not list(args.path or []))
    out_path = Path(str(args.out)).expanduser() if str(args.out or "").strip() else _default_out_path(str(args.profile))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[scan] files={len(paths)} profile={args.profile}")
    syntax_errors = find_syntax_errors(paths)
    unbound_local_suspects = find_unbound_local_suspects(paths)
    undefined_name_suspects = find_undefined_name_suspects(paths)
    constant_branch_suspects = find_constant_branch_suspects(paths)
    mutable_default_suspects = find_mutable_default_suspects(paths)
    duplicate_dict_key_suspects = find_duplicate_dict_key_suspects(paths)
    repo_checks = run_repo_checks(profile=str(args.profile), include_repo_checks=include_repo_checks)

    report = build_report(
        profile=str(args.profile),
        paths=paths,
        syntax_errors=syntax_errors,
        unbound_local_suspects=unbound_local_suspects,
        undefined_name_suspects=undefined_name_suspects,
        constant_branch_suspects=constant_branch_suspects,
        mutable_default_suspects=mutable_default_suspects,
        duplicate_dict_key_suspects=duplicate_dict_key_suspects,
        repo_checks=repo_checks,
    )
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "code_error_scan "
        f"decision={report['decision']} "
        f"syntax={report['summary']['syntax_errors']} "
        f"unbound_suspects={report['summary']['unbound_local_suspects']} "
        f"undefined_name_suspects={report['summary']['undefined_name_suspects']} "
        f"constant_branch_suspects={report['summary']['constant_branch_suspects']} "
        f"mutable_default_suspects={report['summary']['mutable_default_suspects']} "
        f"duplicate_dict_key_suspects={report['summary']['duplicate_dict_key_suspects']} "
        f"repo_checks_failed={report['summary']['repo_checks_failed']} "
        f"out={out_path}"
    )
    _print_issue_preview("Syntax errors", syntax_errors)
    _print_issue_preview("Unbound local suspects", unbound_local_suspects)
    _print_issue_preview("Undefined name suspects", undefined_name_suspects)
    _print_issue_preview("Constant branch suspects", constant_branch_suspects)
    _print_issue_preview("Mutable default suspects", mutable_default_suspects)
    _print_issue_preview("Duplicate dict key suspects", duplicate_dict_key_suspects)

    if report["decision"] == "fail":
        return 2
    if report["decision"] == "warn":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
