"""Identify Python modules with no importers — candidates for deletion.

Walks app_core/ and mlcore/, finds every module, and greps the rest of the
codebase for any import or string reference to it. Modules with ZERO
references outside themselves are flagged as dead.

Caveats:
- Misses dynamic loads (importlib, __import__, getattr by string)
- Misses modules referenced only in deleted files
- A "test_X.py" file is normal — only `test_*.py` files are excluded from
  scanning as importer candidates (they exist to test something, not because
  some other module needs them)
"""
from __future__ import annotations

import re
import sys

# Console cp1252 no Windows derruba qualquer print com acento/emoji — e o estouro
# vem no fim, depois do trabalho todo feito. Ver tools/find_silent_failures.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError, ValueError):
    pass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["app_core", "mlcore"]
EXCLUDE_DIR_NAMES = {"__pycache__", "tests"}
EXTRA_SCAN_FILES = ["plays_app.py"]


def list_modules() -> list[Path]:
    out: list[Path] = []
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            if any(part in EXCLUDE_DIR_NAMES for part in f.parts):
                continue
            if f.name == "__init__.py":
                continue
            out.append(f)
    return out


def module_id(path: Path) -> str:
    """Build a dotted module id from path: app_core/foo/bar.py -> app_core.foo.bar"""
    rel = path.relative_to(ROOT)
    parts = list(rel.parts)
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def basename(path: Path) -> str:
    return path.stem


def find_references(target_id: str, target_basename: str, self_path: Path) -> list[Path]:
    """Return all files that import or reference target_id / target_basename, excluding self."""
    pattern1 = re.compile(rf"\b{re.escape(target_id)}\b")
    pattern2 = re.compile(rf"\bfrom\s+{re.escape(target_id)}\s+import\b")
    pattern3 = re.compile(rf"\bimport\s+{re.escape(target_id)}\b")
    # Also a bare basename in import statements (relative imports)
    pattern4 = re.compile(rf"\b(from|import)\s+(\w+\.)*{re.escape(target_basename)}\b")

    hits: list[Path] = []
    paths_to_scan: list[Path] = []
    for d in [*SCAN_DIRS, "tools"]:
        bd = ROOT / d
        if not bd.is_dir():
            continue
        for f in bd.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            if f == self_path:
                continue
            paths_to_scan.append(f)
    for extra in EXTRA_SCAN_FILES:
        p = ROOT / extra
        if p.is_file() and p != self_path:
            paths_to_scan.append(p)

    for f in paths_to_scan:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if (pattern1.search(text) or pattern2.search(text)
                or pattern3.search(text) or pattern4.search(text)):
            hits.append(f)
    return hits


def main() -> int:
    modules = list_modules()
    print(f"Scanning {len(modules)} modules for references...")
    dead: list[tuple[Path, str]] = []
    weak: list[tuple[Path, str, int]] = []  # only referenced from tests
    for m in modules:
        mid = module_id(m)
        basen = basename(m)
        refs = find_references(mid, basen, m)
        # Classify
        non_test_refs = [r for r in refs if "test_" not in r.name]
        if not refs:
            dead.append((m, mid))
        elif not non_test_refs:
            weak.append((m, mid, len(refs)))

    print(f"\n=== Dead modules ({len(dead)}, no references anywhere) ===")
    for m, _mid in dead:
        rel = m.relative_to(ROOT)
        print(f"  {rel}")

    print(f"\n=== Weak modules ({len(weak)}, only referenced from test files) ===")
    for m, _mid, n in weak:
        rel = m.relative_to(ROOT)
        print(f"  {rel}  ({n} test refs)")

    print(f"\nTotal modules: {len(modules)} | Dead: {len(dead)} | Weak (test-only): {len(weak)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
