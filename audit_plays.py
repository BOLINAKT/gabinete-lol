# -*- coding: utf-8 -*-
"""Audit plays_app.py: find dead functions, 1-liner shims, orphaned imports."""
import ast
from pathlib import Path

SRC = Path("plays_app.py")
TAB_MODULES = [
    Path("app_core/params_tab_core.py"),
    Path("app_core/visao_tab_core.py"),
    Path("app_core/consistencia_tab_core.py"),
]
APP_CORE_DIR = Path("app_core")
MLCORE_DIR = Path("mlcore")

code = SRC.read_text(encoding="utf-8")
lines = code.splitlines()

# ---------------------------------------------------------------------------
# 1. Collect all function definitions in plays_app.py
# ---------------------------------------------------------------------------
tree = ast.parse(code)
func_nodes = {
    n.name: n
    for n in ast.walk(tree)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.col_offset == 0
}
print(f"Top-level functions: {len(func_nodes)}")

# ---------------------------------------------------------------------------
# 2. Find all call sites of each function
#    - in plays_app.py itself (module-level code outside function defs)
#    - in the 3 extracted tab modules (via ctx.get("name") pattern)
#    - in any other app_core/mlcore file (direct import + call is impossible,
#      but they might reference the name as string in ctx.get("name"))
# ---------------------------------------------------------------------------

def collect_name_refs(code_str):
    """Return set of all Name ids and string literals that look like function names."""
    refs = set()
    try:
        tree2 = ast.parse(code_str)
        for n in ast.walk(tree2):
            if isinstance(n, ast.Name):
                refs.add(n.id)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                # ctx.get("_some_func") pattern
                refs.add(n.value)
    except SyntaxError:
        pass
    return refs

# Collect refs from the 3 tab modules
tab_refs = set()
for tp in TAB_MODULES:
    if tp.exists():
        tab_refs |= collect_name_refs(tp.read_text(encoding="utf-8"))

# Collect refs from plays_app.py itself (as both names and strings)
plays_refs = collect_name_refs(code)

# Combine
all_refs = plays_refs | tab_refs

# ---------------------------------------------------------------------------
# 3. Classify functions
# ---------------------------------------------------------------------------

# Functions that are 1-liners or 2-liners (shims)
def func_body_lines(node):
    return node.end_lineno - node.lineno  # excludes def line

shims = {}       # name → (lineno, end_lineno, body_lines)
large_fns = {}   # name → (lineno, end_lineno, body_lines) — >50 lines

for name, node in func_nodes.items():
    bl = func_body_lines(node)
    if bl <= 3:
        shims[name] = (node.lineno, node.end_lineno, bl)
    elif bl > 50:
        large_fns[name] = (node.lineno, node.end_lineno, bl)

# Dead = not referenced anywhere outside their own definition
dead_funcs = []
for name in func_nodes:
    # Remove self-reference: count refs excluding the function's own lines
    fn_node = func_nodes[name]
    # Check if name appears in refs (outside its own def)
    if name not in all_refs:
        dead_funcs.append((name, func_nodes[name].lineno, func_nodes[name].end_lineno))
    # Also check: referenced only inside itself (recursive)
    # (harder, skip for now)

# Shims that are just 1:1 wrappers (body is a single return/call statement)
def is_simple_shim(node, src_lines):
    body = node.body
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Return):
            return True
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            return True
    return False

simple_shims = {
    name: (node.lineno, node.end_lineno)
    for name, node in func_nodes.items()
    if name in shims and is_simple_shim(node, lines)
}

# ---------------------------------------------------------------------------
# 4. Find orphaned imports in plays_app.py
#    (imported names never referenced in the file after imports)
# ---------------------------------------------------------------------------

# Collect all imported names
imported_names = {}  # alias → (module, lineno)
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        for alias in node.names:
            name = alias.asname or alias.name
            imported_names[name] = (mod, node.lineno)
    elif isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.asname or alias.name.split('.')[0]
            imported_names[name] = (alias.name, node.lineno)

# Find names that are imported but never used in plays_app.py code
# (they might be used in tab modules via ctx — those are OK)
# We only flag ones NOT in plays_refs (direct use in plays_app.py)
# and NOT in the function definitions (they might be passed to ctx implicitly)

# Actually: if an imported name is ONLY referenced in the ctx.get("name") string
# in the tab modules, it's still needed in plays_app.py. So we skip this check
# for tab-referenced names.

orphaned_imports = []
for name, (mod, lineno) in imported_names.items():
    # Count direct references in plays_app.py (as Name nodes, not string literals)
    ref_count = sum(1 for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and n.id == name)
    # The import itself counts as 1 (the alias definition doesn't create a Name node)
    # So if ref_count == 0, it's orphaned
    if ref_count == 0 and name not in tab_refs:
        orphaned_imports.append((name, mod, lineno))

# ---------------------------------------------------------------------------
# 5. Print report
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
print(f"DEAD FUNCTIONS (not referenced anywhere): {len(dead_funcs)}")
for name, start, end in sorted(dead_funcs, key=lambda x: x[1]):
    print(f"  L{start}-{end} ({end-start+1}L)  {name}")

print(f"\n{'='*60}")
print(f"LARGE FUNCTIONS (>50L, candidates to move): {len(large_fns)}")
for name, (start, end, _bl) in sorted(large_fns.items(), key=lambda x: -(x[1][2])):
    in_tabs = "  [tab-ref]" if name in tab_refs else ""
    in_plays = "  [plays-ref]" if name in plays_refs else ""
    print(f"  L{start}-{end} ({end-start+1}L)  {name}{in_tabs}{in_plays}")

print(f"\n{'='*60}")
print(f"SIMPLE 1-LINER SHIMS (candidates to inline/remove): {len(simple_shims)}")
for name, (start, end) in sorted(simple_shims.items(), key=lambda x: x[1][0]):
    in_tabs = " [tab]" if name in tab_refs else ""
    in_plays = " [plays]" if name in plays_refs else ""
    print(f"  L{start}-{end}  {name}{in_tabs}{in_plays}")

print(f"\n{'='*60}")
print(f"ORPHANED IMPORTS (imported but never used in plays_app.py): {len(orphaned_imports)}")
for name, mod, lineno in sorted(orphaned_imports, key=lambda x: x[2]):
    print(f"  L{lineno}  {name}  (from {mod})")

print(f"\nTotal lines: {len(lines)}")
