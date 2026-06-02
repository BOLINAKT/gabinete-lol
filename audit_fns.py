# -*- coding: utf-8 -*-
"""Find outer-scope dependencies of specific large functions in plays_app.py."""
import ast
from pathlib import Path

SRC = Path("plays_app.py")
code = SRC.read_text(encoding="utf-8")
tree = ast.parse(code)

BUILTINS = {
    'True','False','None','print','len','str','int','float','list','dict','set','tuple',
    'range','enumerate','zip','map','filter','isinstance','issubclass','hasattr','getattr',
    'setattr','delattr','type','id','hash','repr','abs','min','max','sum','sorted',
    'reversed','any','all','open','next','iter','vars','dir','globals','locals',
    'callable','super','object','bool','format','round','pow','divmod','bin','oct',
    'hex','chr','ord','bytes','bytearray','frozenset','slice',
    'Exception','ValueError','TypeError','KeyError','IndexError','AttributeError',
    'OSError','IOError','RuntimeError','StopIteration','NotImplementedError',
    'AssertionError','ImportError','NameError','ZeroDivisionError','OverflowError',
    'BaseException','KeyboardInterrupt','SystemExit','GeneratorExit',
    'UnicodeDecodeError','UnicodeEncodeError','UnicodeError',
    'FileNotFoundError','PermissionError','IsADirectoryError',
    'ConnectionError','TimeoutError','LookupError','ArithmeticError',
    '__name__','__file__','__doc__','NotImplemented','Ellipsis',
}

TARGET_FNS = [
    "_run_auto_maintenance_now",
    "_csv_bootstrap_gate",
    "_ensure_csv_runtime_ready",
    "_render_calibracoes",
    "_inject_global_ui_css",
    "_render_csv_prepare_live_dashboard",
    "_render_csv_prepare_report_summary",
    "_render_csv_prepare_artifacts_cards",
    "_render_global_maintenance_banner",
    "_render_global_feature_trace_banner",
]


def get_fn_node(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name and n.col_offset == 0:
            return n
    return None


def collect_names_in_fn(fn_node):
    """Collect all local definitions and all name references in a function body."""
    local = set()
    refs = set()

    class V(ast.NodeVisitor):
        def _c(self, t):
            if isinstance(t, ast.Name): local.add(t.id)
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts: self._c(e)
            elif isinstance(t, ast.Starred): self._c(t.value)

        def visit_FunctionDef(self, n):
            if n is not fn_node:
                local.add(n.name)
            else:
                # Add params to local
                for arg in n.args.args + n.args.posonlyargs + n.args.kwonlyargs:
                    local.add(arg.arg)
                if n.args.vararg: local.add(n.args.vararg.arg)
                if n.args.kwarg: local.add(n.args.kwarg.arg)
                self.generic_visit(n)
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, n): local.add(n.name)
        def visit_Assign(self, n):
            for t in n.targets: self._c(t)
            self.generic_visit(n)
        def visit_AugAssign(self, n):
            self._c(n.target); self.generic_visit(n)
        def visit_AnnAssign(self, n):
            self._c(n.target)
            if n.value: self.generic_visit(n)
        def visit_For(self, n):
            self._c(n.target); self.generic_visit(n)
        def visit_With(self, n):
            for i in n.items:
                if i.optional_vars: self._c(i.optional_vars)
            self.generic_visit(n)
        def visit_ExceptHandler(self, n):
            if n.name: local.add(n.name)
            self.generic_visit(n)
        def visit_NamedExpr(self, n):
            if isinstance(n.target, ast.Name): local.add(n.target.id)
            self.generic_visit(n)
        def visit_Name(self, n):
            refs.add(n.id)
        def visit_Import(self, n):
            for a in n.names: local.add(a.asname or a.name.split('.')[0])
        def visit_ImportFrom(self, n):
            for a in n.names:
                if a.name != '*': local.add(a.asname or a.name)

    V().visit(fn_node)
    return local, refs


# Collect all names defined in the global scope
global_names = set()
for n in ast.walk(tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.col_offset == 0:
        global_names.add(n.name)
    elif isinstance(n, ast.ImportFrom):
        for a in n.names:
            if a.name != '*': global_names.add(a.asname or a.name)
    elif isinstance(n, ast.Import):
        for a in n.names: global_names.add(a.asname or a.name.split('.')[0])
    elif isinstance(n, ast.Assign) and getattr(n, 'col_offset', 99) == 0:
        for t in n.targets:
            if isinstance(t, ast.Name): global_names.add(t.id)

for fn_name in TARGET_FNS:
    fn = get_fn_node(tree, fn_name)
    if not fn:
        print(f"\n{fn_name}: NOT FOUND")
        continue
    local, refs = collect_names_in_fn(fn)
    outer = (refs - local - BUILTINS) & global_names
    print(f"\n{fn_name} (L{fn.lineno}-{fn.end_lineno}, {fn.end_lineno-fn.lineno+1}L)")
    print(f"  Outer refs ({len(outer)}): {', '.join(sorted(outer))}")
