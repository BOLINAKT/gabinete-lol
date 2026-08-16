# -*- coding: utf-8 -*-
"""Caça a família de bug do 'Season inteira' (24/07): RAMOS IDÊNTICOS.

O bug: o card mostrava os números do split porque o código era
    try:    df_a_season = df_a.copy()
    except: df_a_season = df_a.copy()   # idêntico -> o fallback nunca corrigia
Assinatura de refactor que perdeu o código original. Ninguém vê num diff.

Detecta (AST, sem rodar nada):
  1. try/except onde o except faz o MESMO que o try;
  2. if/else com corpos idênticos;
  3. elif que repete um ramo anterior do mesmo if;
  4. atribuições onde os dois lados de um if/else escrevem o mesmo valor.

Uso: python tools/find_dead_branches.py [--json out.json]
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git", "backups", "evidence", "scratchpad"}


def _norm(node: ast.AST) -> str:
    """Dump normalizado do corpo (ignora números de linha)."""
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _body_sig(body: list[ast.stmt]) -> str:
    return "|".join(_norm(s) for s in body)


def _is_trivial(body: list[ast.stmt]) -> bool:
    """pass / return / continue / break / raise sozinhos: fallback legítimo."""
    if len(body) != 1:
        return False
    s = body[0]
    if isinstance(s, (ast.Pass, ast.Break, ast.Continue, ast.Raise)):
        return True
    if isinstance(s, ast.Return) and (s.value is None or isinstance(s.value, ast.Constant)):
        return True
    return False


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path, src_lines: list[str]):
        self.path = path
        self.lines = src_lines
        self.hits: list[dict] = []

    def _add(self, kind: str, lineno: int, detail: str) -> None:
        self.hits.append({
            "file": str(self.path.relative_to(ROOT)).replace("\\", "/"),
            "line": int(lineno),
            "kind": kind,
            "detail": detail,
            "code": self.lines[lineno - 1].strip() if 0 < lineno <= len(self.lines) else "",
        })

    def visit_Try(self, node: ast.Try) -> None:
        t = _body_sig(node.body)
        for h in node.handlers:
            if _is_trivial(h.body):
                continue
            if _body_sig(h.body) == t:
                self._add("try_except_identico", h.lineno,
                          "o except faz exatamente o mesmo que o try (fallback inerte)")
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if node.orelse and not _is_trivial(node.body) and not _is_trivial(node.orelse):
            # elif vira If aninhado no orelse; compara só else "de verdade"
            if not (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)):
                if _body_sig(node.body) == _body_sig(node.orelse):
                    self._add("if_else_identico", node.lineno,
                              "o else faz exatamente o mesmo que o if")
        # cadeia de elifs repetindo um ramo
        seen: list[tuple[str, int]] = []
        cur: ast.If | None = node
        while isinstance(cur, ast.If):
            if not _is_trivial(cur.body):
                sig = _body_sig(cur.body)
                for prev_sig, prev_line in seen:
                    if sig == prev_sig:
                        self._add("elif_repetido", cur.lineno,
                                  f"este ramo repete o da linha {prev_line}")
                        break
                seen.append((sig, cur.lineno))
            cur = cur.orelse[0] if (len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If)) else None
        self.generic_visit(node)


def scan(paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        v = _Visitor(p, src.splitlines())
        v.visit(tree)
        out.extend(v.hits)
    return out


def collect(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py")
            if not any(d in p.parts for d in SKIP_DIRS)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--path", default=str(ROOT))
    args = ap.parse_args()

    files = collect(Path(args.path))
    hits = scan(files)
    print(f"varridos {len(files)} arquivos .py")
    if not hits:
        print("nenhum ramo idêntico encontrado.")
        return 0
    by_kind: dict[str, int] = {}
    for h in hits:
        by_kind[h["kind"]] = by_kind.get(h["kind"], 0) + 1
    print(f"\nACHADOS: {len(hits)}  {by_kind}\n")
    for h in sorted(hits, key=lambda x: (x["kind"], x["file"], x["line"])):
        print(f"  [{h['kind']}] {h['file']}:{h['line']}")
        print(f"      {h['detail']}")
        if h["code"]:
            print(f"      > {h['code'][:100]}")
    if args.json:
        Path(args.json).write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[salvo] {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
