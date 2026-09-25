"""U2 cloud build: U2-0 item 1's interpreter gate (te267 sec 5 U2-0, "The
tests that need the converter refuse an interpreter too old for it, by name;
configure refuses nothing").

Configures a scratch build of this tree with an interpreter whose
`unicodedata.unidata_version` is older than the converter's (15.1.0, Python
3.13's), then reads the registered tests (`ctest --show-only=json-v1`):

  (1) configure succeeds (configure refuses nothing) and prints one line
      naming both versions;
  (2) a gate test is registered (a FIXTURES_SETUP test) and, run, fails with
      a line naming both versions;
  (3) every ctest that runs a fixture regenerator pinning the converter's
      Unicode version requires that gate (FIXTURES_REQUIRED) -- the regenerator
      set is derived here from the sources' code (imports and non-docstring
      string constants, never comments), not listed: a script is in it if it
      imports or runs the converter, or imports or runs a script in it (an
      import closure: a script that imports a regenerating module counts);
  (4) in THIS build (the interpreter the build was configured with), the gate,
      if registered, passes.

RED TODAY: no gate exists (U2-0 item 1's wiring is not yet built).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONVERTER_UNICODE = "15.1.0"


def code_refs(path: Path) -> set[str]:
    """What a script's code (never its comments or docstrings) names: imported
    module names, and every non-docstring string constant."""
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.update(a.name.split(".")[-1] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            refs.add(node.module.split(".")[-1])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            refs.add(node.value)
    return refs


def names(refs: set[str], target_stem: str) -> bool:
    return any(r == target_stem or r.endswith(target_stem + ".py") or (target_stem + ".py") in r for r in refs)


def regenerator_scripts() -> set[Path]:
    files = [p for p in list((REPO_ROOT / "tests").rglob("*.py")) + list((REPO_ROOT / "tools").rglob("*.py"))
             if "_scratch" not in p.parts and p.resolve() != Path(__file__).resolve()]
    refs = {p: code_refs(p) for p in files}
    reg = {p for p, r in refs.items() if names(r, "convert_tokenizer")}
    changed = True
    while changed:
        changed = False
        for p, r in refs.items():
            if p not in reg and any(names(r, q.stem) for q in reg):
                reg.add(p)
                changed = True
    return reg


def show_tests(build: Path) -> list[dict]:
    r = subprocess.run(["ctest", "--show-only=json-v1"], cwd=build, capture_output=True, text=True)
    return json.loads(r.stdout).get("tests", []) if r.returncode == 0 else []


def props(t: dict) -> dict:
    return {p["name"]: p["value"] for p in t.get("properties", [])}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--prefix-path", required=True)
    ap.add_argument("--old-python", default="")
    args = ap.parse_args(argv)
    fails = 0

    def verdict(ok: bool, cell: str, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")

    old = args.old_python
    if not old:
        for cand in ("python3.12", "python3.11", "python3.10"):
            if shutil.which(cand):
                old = shutil.which(cand)
                break
    if not old:
        print("[MISSING PREREQUISITE] U2-0 interpreter gate: no interpreter older than 3.13 on PATH")
        return 0
    old_uv = subprocess.run([old, "-c", "import unicodedata; print(unicodedata.unidata_version)"],
                            capture_output=True, text=True).stdout.strip()
    regs = regenerator_scripts()
    print(f"interpreter {old} (unicodedata {old_uv}); converter {CONVERTER_UNICODE}; "
          f"{len(regs)} regenerator script(s): {sorted(str(p.relative_to(REPO_ROOT)) for p in regs)}")

    scratch = Path(args.build_dir) / "_scratch" / "u2_0_python_gate"
    shutil.rmtree(scratch, ignore_errors=True)
    cfg = subprocess.run(["cmake", "-S", str(REPO_ROOT), "-B", str(scratch), "-G", "Ninja",
                          "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_PREFIX_PATH={args.prefix_path}",
                          f"-DPython3_EXECUTABLE={old}"], capture_output=True, text=True, errors="replace")
    out = cfg.stdout + cfg.stderr
    named = [ln for ln in out.splitlines() if old_uv in ln and CONVERTER_UNICODE in ln]
    verdict(cfg.returncode == 0, "(1) configure with the old interpreter succeeds (configure refuses nothing)",
            f"exit {cfg.returncode}")
    verdict(len(named) >= 1, "(1) configure prints one line naming both Unicode versions",
            named[0].strip()[:200] if named else f"no line names both {old_uv} and {CONVERTER_UNICODE}")
    tests = show_tests(scratch) if cfg.returncode == 0 else []
    gates = {t["name"]: props(t) for t in tests if props(t).get("FIXTURES_SETUP")}
    verdict(bool(gates), "(2) a gate test (FIXTURES_SETUP) is registered", f"{sorted(gates) or 'none'}")
    gate_fixtures = set()
    for p in gates.values():
        v = p["FIXTURES_SETUP"]
        gate_fixtures.update(v if isinstance(v, list) else [v])
    if gates:
        name = sorted(gates)[0]
        run = subprocess.run(["ctest", "-R", f"^{re.escape(name)}$", "--output-on-failure"], cwd=scratch,
                             capture_output=True, text=True, errors="replace")
        verdict(run.returncode != 0 and old_uv in run.stdout and CONVERTER_UNICODE in run.stdout,
                "(2) the gate fails with a line naming both versions", f"exit {run.returncode}")
    missing = []
    reg_tests = 0
    for t in tests:
        cmd = t.get("command") or []
        if not any(Path(c).resolve() in regs for c in cmd if c.endswith(".py")):
            continue
        reg_tests += 1
        req = props(t).get("FIXTURES_REQUIRED") or []
        req = set(req if isinstance(req, list) else [req])
        if not (req & gate_fixtures):
            missing.append(t["name"])
    verdict(reg_tests > 0 and not missing,
            f"(3) every ctest running a regenerator requires the gate ({reg_tests} such tests)",
            f"{len(missing)} without it: {missing[:12]}{' ...' if len(missing) > 12 else ''}")
    # (4) this build's interpreter.
    here = show_tests(Path(args.build_dir))
    here_gates = [t["name"] for t in here if props(t).get("FIXTURES_SETUP")]
    if here_gates:
        run = subprocess.run(["ctest", "-R", f"^{re.escape(here_gates[0])}$"], cwd=args.build_dir,
                             capture_output=True, text=True)
        verdict(run.returncode == 0, "(4) in this build the gate passes", f"exit {run.returncode}")
    else:
        verdict(True, "(4) in this build no gate is registered (interpreter new enough)", "none")
    shutil.rmtree(scratch, ignore_errors=True)
    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
