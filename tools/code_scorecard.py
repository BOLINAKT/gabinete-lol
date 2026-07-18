# -*- coding: utf-8 -*-
"""SCORECARD DE CÓDIGO — a nota de código calculada (regra 7, 18/07/2026).

Mesmo comando → mesmo número. 13 componentes, TODOS visíveis no relatório,
média SIMPLES declarada (sem peso escondido) + UMA trava: suíte com falha
derruba a nota final para no máximo 3.0.

ESCOPO COMPLETO (pedido dele 18/07: "todo o código"):
  PROD    = app_core/ + mlcore/ (sem tests/fixtures/_recovered)
  TOOLS   = tools/*.py
  TESTS   = mlcore/tests/*.py (teste também é código)
  SCRIPTS = *.py da raiz (plays_app etc.)
Escopo por componente (declarado na tabela): TUDO = PROD+TOOLS+TESTS+SCRIPTS.
 1. suíte verde [suíte]                    8. guardas estado≠código [suíte]
 2. módulos com teste [PROD]               9. cobertura de linha [PROD]
 3. monolito [TUDO]                       10. complexidade radon [TUDO]
 4. refs fora do registro [PROD+SCRIPTS]  11. código morto [TUDO−TESTS]*
 5. duplicação [TUDO]                     12. camadas/ciclos [PROD]
 6. pyflakes [TUDO]                       13. Maintainability Index [TUDO]
 7. E2E presentes [suíte]
(*vulture em testes = falso positivo em massa, métodos test_* "não usados";
 refs de registro em TESTS ficam fora porque os snapshots de equivalência
 usam literais DE PROPÓSITO.)
+ painel: hotspots churn(git 90d)×SLOC [TUDO] — onde fatiar/testar primeiro.

Uso:
  python tools/code_scorecard.py            # completo (~15 min: suíte+coverage)
  python tools/code_scorecard.py --fast     # pula suíte e coverage
  python tools/code_scorecard.py --root ..\\GabineteDOTA   # outro repo
Saída: texto + evidence/code_scorecard.json (no root analisado)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PKGS = ("app_core", "mlcore")
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "_recovered", "fixtures", ".venv", "venv"}

MONO_FREE_SLOC = 800
MONO_PENALTY_DIV = 600
CC_HIGH = 15              # ref. web: mediana <10, >15 sinaliza
MI_LOW = 10               # rank C do radon (escala do mi_visit; o "65" da web é a
                          # escala re-normalizada do Visual Studio, outra régua)
DUP_WINDOW = 6
REGISTRY_RE = re.compile(r"\"lines_(kills|towers|dragons|barons|inhib|time)\"")
GUARD_TESTS = (
    "test_live_artifact_complete.py",
    "test_e2e_smoke.py",
    "test_flow_line_keys_registry.py",
)
E2E_CLASSES = ("TestE2ESmokeLoL", "TestE2ESmokeLoLViewer", "TestE2ESmokeDota")


class Files:
    def __init__(self, root: Path):
        self.root = root

        def _ok(p: Path) -> bool:
            return not any(part in EXCLUDE_DIRS for part in p.parts)

        self.prod: list[Path] = []
        self.tests: list[Path] = []
        for pkg in PKGS:
            base = root / pkg
            if not base.exists():
                continue
            for p in sorted(base.rglob("*.py")):
                if not _ok(p):
                    continue
                (self.tests if "tests" in p.parts else self.prod).append(p)
        self.tools = [p for p in sorted((root / "tools").glob("*.py"))] if (root / "tools").exists() else []
        self.scripts = [p for p in sorted(root.glob("*.py"))]
        self.all = self.prod + self.tools + self.tests + self.scripts


def _sloc(path: Path) -> int:
    try:
        return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                   if ln.strip() and not ln.strip().startswith("#"))
    except OSError:
        return 0


def _run(root: Path, cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root),
                        timeout=timeout, encoding="utf-8", errors="replace")
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def comp_suite(root: Path, fast: bool) -> dict:
    """1. Suíte: nº de testes + verde. Falha => nota final <= 3.0."""
    if fast:
        return {"score": None, "detail": "pulado (--fast)"}
    if not (root / "mlcore" / "tests").exists():
        return {"score": None, "detail": "sem suíte neste root"}
    rc, out = _run(root, [sys.executable, "-m", "unittest", "discover", "-s", "mlcore/tests"], timeout=1800)
    m = re.search(r"Ran (\d+) tests", out)
    n = int(m.group(1)) if m else 0
    green = bool(re.search(r"\nOK( \(|\s*$)", out)) and rc == 0
    fails = len(re.findall(r"^(FAIL|ERROR):", out, re.M))
    return {"score": 10.0 if green else 0.0,
            "detail": f"{n} testes, {'verde' if green else f'{fails} falhas'}", "n_tests": n}


def comp_module_tests(f: Files) -> dict:
    """2. % de módulos PROD com teste correspondente ou importados por teste."""
    test_names = {p.stem for p in f.tests}
    imported: set[str] = set()
    for tp in f.tests:
        try:
            txt = tp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"(?:from|import) (?:app_core|mlcore)\.(\w+)", txt):
            imported.add(m.group(1))
    mods = [p for p in f.prod if p.name != "__init__.py"]
    covered = [p for p in mods if (f"test_{p.stem}" in test_names) or (p.stem in imported)]
    pct = len(covered) / len(mods) if mods else 0.0
    return {"score": round(pct * 10, 2), "detail": f"{len(covered)}/{len(mods)} módulos PROD com teste ({pct:.0%})"}


def comp_monolith(f: Files) -> dict:
    """3. Monolito [TUDO]: -1 ponto a cada 600 SLOC acima de 800 (top-5)."""
    sizes = sorted(((_sloc(p), p) for p in f.all), reverse=True)[:5]
    penalty = sum(max(0, s - MONO_FREE_SLOC) / MONO_PENALTY_DIV for s, _ in sizes)
    top = ", ".join(f"{p.name}={s}" for s, p in sizes[:3])
    return {"score": round(max(0.0, 10.0 - penalty), 2), "detail": f"top: {top}"}


def comp_registry(f: Files) -> dict:
    """4. Refs hardcoded de line keys [PROD+SCRIPTS, fora stats_config] (-0.25/ref)."""
    count, where = 0, {}
    for p in f.prod + f.scripts:
        if p.name == "stats_config.py":
            continue
        try:
            n = len(REGISTRY_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            n = 0
        if n:
            where[p.name] = n
            count += n
    return {"score": round(max(0.0, 10.0 - 0.25 * count), 2), "detail": f"{count} refs ({where})"}


def comp_duplication(f: Files) -> dict:
    """5. Duplicação [TUDO]: janelas de 6 linhas repetidas entre arquivos (ref <5-10%)."""
    seen: dict[str, str] = {}
    dup, total = 0, 0
    for p in f.all:
        try:
            lines = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()]
        except OSError:
            continue
        lines = [ln for ln in lines if ln and not ln.startswith("#")]
        for i in range(0, max(0, len(lines) - DUP_WINDOW + 1)):
            win = "\n".join(lines[i:i + DUP_WINDOW])
            if len(win) < 80:
                continue
            h = hashlib.sha1(win.encode()).hexdigest()
            total += 1
            other = seen.get(h)
            if other is not None and other != p.name:
                dup += 1
            else:
                seen[h] = p.name
    rate = dup / total if total else 0.0
    return {"score": round(max(0.0, 10.0 - rate * 100.0), 2), "detail": f"{rate:.1%} janelas duplicadas ({dup}/{total})"}


def comp_pyflakes(root: Path, f: Files) -> dict:
    """6. Higiene pyflakes [TUDO] (-0.1/aviso ACIONÁVEL).

    Só conta avisos SEM `# noqa` na linha citada: o pyflakes puro (diferente
    do flake8) não respeita a supressão que o dev marcou de propósito —
    re-exports (`# noqa: F401 - re-exported`), probes de disponibilidade em
    try/except etc. Contá-los penalizava higiene intencional (lição da
    varredura 18/07). O `plays_app` usa o padrão globals()->ctx: seus imports
    "unused" são consumidos por reflexão; ficam de fora deste componente."""
    src_cache: dict[str, list[str]] = {}

    def _has_noqa(path_str: str, line_no: int, symbol: str = "") -> bool:
        try:
            lines = src_cache.get(path_str)
            if lines is None:
                lines = (root / path_str).read_text(encoding="utf-8", errors="replace").splitlines()
                src_cache[path_str] = lines
            if not (0 < line_no <= len(lines)):
                return False
            if "# noqa" in lines[line_no - 1].lower():
                return True
            # Import multi-linha: pyflakes aponta o `from X import (`, mas o
            # `# noqa` fica na linha do símbolo. Varre até o `)` e casa o símbolo.
            if symbol and lines[line_no - 1].rstrip().endswith("("):
                for j in range(line_no, min(line_no + 40, len(lines))):
                    ltxt = lines[j]
                    if symbol in ltxt and "# noqa" in ltxt.lower():
                        return True
                    if ltxt.rstrip().endswith(")"):
                        break
            return False
        except (OSError, IndexError):
            return False

    # path:line:col: message — path pode ter drive do Windows (C:\...), então
    # casa o path completo de forma não-gulosa antes de :line:col:.
    line_re = re.compile(r"^(.*?):(\d+):\d+: (.*)$")
    actionable, suppressed, skipped_playsapp = 0, 0, 0
    batch = [str(p) for p in f.all]
    for i in range(0, len(batch), 150):
        rc, out = _run(root, [sys.executable, "-m", "pyflakes", *batch[i:i + 150]], timeout=600)
        for ln in out.splitlines():
            if not ln.strip():
                continue
            m = line_re.match(ln)
            if not m:
                actionable += 1
                continue
            path_str, line_no, msg = m.group(1), int(m.group(2)), m.group(3)
            if path_str.replace("\\", "/").endswith("plays_app.py"):
                skipped_playsapp += 1
                continue
            # símbolo entre aspas na mensagem, último componente pontilhado
            sym = ""
            qm = re.search(r"'([^']+)'", msg)
            if qm:
                sym = qm.group(1).split(".")[-1].split(" ")[0]
            if _has_noqa(path_str, line_no, sym):
                suppressed += 1
            else:
                actionable += 1
    return {"score": round(max(0.0, 10.0 - 0.1 * actionable), 2),
            "detail": f"{actionable} avisos acionaveis ({suppressed} noqa + {skipped_playsapp} plays_app globals ignorados)"}


def comp_e2e(f: Files) -> dict:
    """7. E2E presentes."""
    txt = ""
    for p in f.tests:
        if p.name.startswith("test_e2e"):
            txt += p.read_text(encoding="utf-8", errors="replace")
    found = [c for c in E2E_CLASSES if c in txt]
    return {"score": round(10.0 * len(found) / len(E2E_CLASSES), 2), "detail": f"{len(found)}/{len(E2E_CLASSES)} E2E"}


def comp_guards(f: Files) -> dict:
    """8. Guardas estado≠código presentes."""
    names = {p.name for p in f.tests}
    found = [g for g in GUARD_TESTS if g in names]
    return {"score": round(10.0 * len(found) / len(GUARD_TESTS), 2), "detail": f"{len(found)}/{len(GUARD_TESTS)} guardas"}


def comp_coverage(root: Path, fast: bool) -> dict:
    """9. Cobertura de LINHA real [PROD] (coverage.py sob a suíte; % => /10)."""
    if fast:
        return {"score": None, "detail": "pulado (--fast)"}
    if not (root / "mlcore" / "tests").exists():
        return {"score": None, "detail": "sem suíte neste root"}
    src = ",".join(PKGS)
    rc, _ = _run(root, [sys.executable, "-m", "coverage", "run", f"--source={src}",
                        "-m", "unittest", "discover", "-s", "mlcore/tests"], timeout=3600)
    rc2, out = _run(root, [sys.executable, "-m", "coverage", "report", "--format=total"], timeout=300)
    try:
        pct = float(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"score": 0.0, "detail": f"coverage falhou (rc={rc}/{rc2})"}
    return {"score": round(pct / 10.0, 2), "detail": f"{pct:.1f}% das linhas PROD cobertas pela suíte"}


def comp_complexity(f: Files) -> dict:
    """10. Complexidade [TUDO]: fração de funções CC>15 (cada 1% = -0.5)."""
    from radon.complexity import cc_visit
    total, high, worst = 0, 0, []
    for p in f.all:
        try:
            blocks = cc_visit(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for b in blocks:
            total += 1
            if b.complexity > CC_HIGH:
                high += 1
                worst.append((b.complexity, f"{p.name}:{b.name}"))
    frac = high / total if total else 0.0
    worst.sort(reverse=True)
    top = ", ".join(f"{n}({c})" for c, n in worst[:3])
    return {"score": round(max(0.0, 10.0 - frac * 100 * 0.5), 2),
            "detail": f"{high}/{total} funções CC>{CC_HIGH} ({frac:.1%}); piores: {top}"}


def comp_dead_code(root: Path, f: Files) -> dict:
    """11. Código morto [TUDO−TESTS] (vulture conf>=80; -0.1/item)."""
    targets = [str(p) for p in f.prod + f.tools + f.scripts]
    rc, out = _run(root, [sys.executable, "-m", "vulture", *targets, "--min-confidence", "80"], timeout=900)
    items = [ln for ln in out.splitlines() if ".py:" in ln]
    return {"score": round(max(0.0, 10.0 - 0.1 * len(items)), 2), "detail": f"{len(items)} itens (conf>=80%)"}


def comp_layers(f: Files) -> dict:
    """12. Camadas [PROD]: mlcore->app_core = -2; ciclo em app_core = -1."""
    imports: dict[str, set[str]] = {}
    violations = []
    for p in f.prod:
        pkg = p.parts[len(f.root.parts)]
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
            elif isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
        if pkg == "mlcore" and any(m.split(".")[0] == "app_core" for m in mods):
            violations.append(p.name)
        if pkg == "app_core":
            imports[p.stem] = {m.split(".")[1] for m in mods
                               if m.startswith("app_core.") and len(m.split(".")) > 1}
    cycles: set[tuple] = set()

    def dfs(node: str, path: list[str]) -> None:
        for nxt in imports.get(node, ()):
            if nxt in path:
                cycles.add(tuple(sorted(path[path.index(nxt):] + [nxt])))
            elif len(path) < 12:
                dfs(nxt, path + [nxt])

    for start in imports:
        dfs(start, [start])
    score = max(0.0, 10.0 - 2.0 * len(violations) - 1.0 * len(cycles))
    cyc_txt = "; ".join("<->".join(sorted(set(c))[:3]) for c in list(cycles)[:2])
    return {"score": round(score, 2),
            "detail": f"{len(violations)} violacoes mlcore->app_core, {len(cycles)} ciclos ({cyc_txt})"}


def comp_mi(f: Files) -> dict:
    """13. Maintainability Index [TUDO]: fração com MI<10=rank C do radon (1% = -0.5)."""
    from radon.metrics import mi_visit
    low, total, worst = 0, 0, []
    for p in f.all:
        try:
            mi = mi_visit(p.read_text(encoding="utf-8", errors="replace"), multi=True)
        except Exception:
            continue
        total += 1
        if mi < MI_LOW:
            low += 1
            worst.append((mi, p.name))
    frac = low / total if total else 0.0
    worst.sort()
    top = ", ".join(f"{n}({mi:.0f})" for mi, n in worst[:3])
    return {"score": round(max(0.0, 10.0 - frac * 100 * 0.5), 2),
            "detail": f"{low}/{total} arquivos MI<{MI_LOW} ({frac:.1%}); piores: {top}"}


def hotspots(root: Path, f: Files) -> list[dict]:
    rc, out = _run(root, ["git", "log", "--since=90.days", "--name-only", "--pretty=format:"], timeout=120)
    churn: dict[str, int] = {}
    for ln in out.splitlines():
        ln = ln.strip().replace("\\", "/")
        if ln.endswith(".py"):
            churn[ln] = churn.get(ln, 0) + 1
    rows = []
    for p in f.all:
        rel = str(p.relative_to(root)).replace("\\", "/")
        c = churn.get(rel, 0)
        s = _sloc(p)
        rows.append({"file": rel, "churn_90d": c, "sloc": s, "risco": c * s})
    rows.sort(key=lambda r: -r["risco"])
    return rows[:12]


def main() -> int:
    ap = argparse.ArgumentParser(description="Nota de código calculada (13 componentes; regra 7).")
    ap.add_argument("--fast", action="store_true", help="Pula suíte e coverage.")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="Raiz do repo a medir.")
    args = ap.parse_args()

    t0 = time.time()
    root = Path(args.root).resolve()
    f = Files(root)
    print(f"[code_scorecard] root={root.name} | PROD={len(f.prod)} TOOLS={len(f.tools)} "
          f"TESTS={len(f.tests)} SCRIPTS={len(f.scripts)} (total {len(f.all)})")

    comps = {
        "01_suite": comp_suite(root, args.fast),
        "02_modulos_com_teste": comp_module_tests(f),
        "03_monolito": comp_monolith(f),
        "04_registro_hardcoded": comp_registry(f),
        "05_duplicacao": comp_duplication(f),
        "06_pyflakes": comp_pyflakes(root, f),
        "07_e2e": comp_e2e(f),
        "08_guardas_estado": comp_guards(f),
        "09_cobertura_linha": comp_coverage(root, args.fast),
        "10_complexidade": comp_complexity(f),
        "11_codigo_morto": comp_dead_code(root, f),
        "12_camadas_ciclos": comp_layers(f),
        "13_maintainability": comp_mi(f),
    }

    scored = {k: v for k, v in comps.items() if v.get("score") is not None}
    nota = sum(v["score"] for v in scored.values()) / len(scored)
    trava = ""
    s1 = comps["01_suite"].get("score")
    if s1 is not None and s1 < 10.0:
        nota = min(nota, 3.0)
        trava = " (TRAVADA: suite nao esta 100% verde)"

    print(f"\n{'componente':26} {'nota':>6}  detalhe")
    for k, v in comps.items():
        s = v.get("score")
        print(f"{k:26} {('n/a' if s is None else f'{s:5.2f}'):>6}  {v['detail']}")
    print(f"\nNOTA DE CODIGO = {nota:.2f}{trava}  (media simples dos {len(scored)} componentes medidos)")

    print("\nHOTSPOTS (churn 90d x tamanho — onde fatiar/testar primeiro):")
    hs = hotspots(root, f)
    for r in hs:
        print(f"  {r['file']:52} churn={r['churn_90d']:>3} sloc={r['sloc']:>5} risco={r['risco']:>7}")

    out_dir = root / "evidence"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "code_scorecard.json").write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root), "nota": round(nota, 2), "trava": bool(trava),
        "componentes": comps, "hotspots": hs,
        "elapsed_s": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[code_scorecard] relatorio salvo: {out_dir / 'code_scorecard.json'} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
