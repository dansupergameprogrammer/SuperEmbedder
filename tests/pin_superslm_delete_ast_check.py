"""tests/pin_superslm_delete_ast_check.py -- TE-73: the structural cell that
closes the data-loss class R-1 and Q-1 kept re-opening one site at a time.
TE-75: two structural defects closed -- the check used to test the BOUND
NAME a call used, not what that name resolves to, so an aliased import
dodged it; and it returned an empty violation list -- indistinguishable
from a real pass -- when handed no files at all.

WHY THIS EXISTS (TE-73, brief "the pin tool gets one deletion primitive, and
nothing else in it can delete"): three consecutive fix rounds (TE-69's Q-1,
TE-71's R-1) each guarded the ONE deletion site a reviewer had just named
and left a sibling site -- written with a different idiom, in the same
file -- untouched. `Claude/CLAUDE.md`'s own standing rule (StandardsDocument
Sec4) is that a rule enforced by a person remembering every call site is a
rule that has already failed; the fix removes the class rather than adding
another guarded site. `tools/pin-superslm/pin_superslm.py` now has exactly
ONE function, `_remove_owned`, permitted to call a real deletion primitive
anywhere in the module.

THE POPULATION THIS CELL COVERS (TE-75 S-1): every filesystem-deletion
callable in `os`, `shutil` and `pathlib` this codebase could plausibly
reach --
    os.remove, os.unlink, os.rmdir, os.removedirs
    shutil.rmtree
    pathlib.Path.unlink, pathlib.Path.rmdir
-- resolved to that ORIGIN (module + attribute), never to the bound name a
call site happens to use. `import x`, `import x as y`, and `from x import a
[as b]` are all resolved through the module's own `ast.Import`/
`ast.ImportFrom` nodes into a name->(module, attribute) map BEFORE any call
is classified, so `from shutil import rmtree as x; x(p)` and
`from os import remove as f; f(p)` resolve to `shutil.rmtree` and
`os.remove` exactly as their unaliased forms do -- a renamed import cannot
dodge this, because the check never looks at the name, only at what the
name is bound to. `Path.unlink`/`Path.rmdir` have no non-deletion meaning
in this codebase and are flagged on ANY receiver; `os.path.remove` does not
exist, and `list.remove` (or any other `.remove()`) is ordinary Python with
no relation to filesystem deletion here, so "remove" is deliberately NOT
in the generic on-any-receiver set (TE-75 M-4) -- it is only caught through
`os.remove`'s own resolved origin.

Usage: `find_deletion_violations(paths)` returns a list of
`DeletionViolation` (file, line, description) for every deletion-primitive
call found outside `_remove_owned`, resolved as above. Raises `ValueError`
if `paths` is empty (TE-75 S-2) -- an empty population is a defect in the
caller, not a clean scan, and must never be indistinguishable from one.
`scan(paths)` is the same check plus the count of modules actually
scanned, for a caller (the matrix leg) that wants to assert that count
explicitly rather than trust an empty pass.

Run directly (`python tests/pin_superslm_delete_ast_check.py <path>...`) to
print violations and exit 1 if any exist, 2 if given no paths, 0 otherwise
-- used standalone to show this red against a historical revision
(`git show <rev>:path > tmp`) and green at the tip.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

PRIMITIVE_FUNCTION_NAME = "_remove_owned"

# TE-75 S-1: the population this cell covers, keyed by the REAL module a
# name must resolve to, not by what a call site happens to spell it as.
MODULE_DELETION_TARGETS: dict[str, set[str]] = {
    "os": {"remove", "unlink", "rmdir", "removedirs"},
    "shutil": {"rmtree"},
}

# TE-75 M-4: pathlib.Path's own deletion methods, flagged on ANY receiver
# (a Path instance is rarely a simple, import-resolvable Name) because
# neither name means anything else in this codebase. "remove" is
# deliberately absent -- list.remove() is ordinary Python and is not a
# filesystem-deletion call; os.remove is still caught, through its
# resolved MODULE origin above, not through this receiver-agnostic set.
PATH_METHOD_TARGETS: set[str] = {"unlink", "rmdir"}


@dataclass(frozen=True)
class DeletionViolation:
    file: Path
    line: int
    description: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.description}"


ImportMap = dict  # str -> tuple[str, str | None]


def _build_import_map(tree: ast.Module) -> "ImportMap":
    """Maps every local name this module can call to (module, attr): attr
    is None when the local name is bound to the WHOLE module (`import os`,
    `import os as o` -> `o` bound to `("os", None)`); it names the real
    attribute when the local name is bound to ONE MEMBER of that module
    (`from os import remove as f` -> `f` bound to `("os", "remove")`,
    identically to the unaliased `from os import remove` -> `remove` bound
    to `("os", "remove")`). This is the whole fix for TE-75 S-1: every call
    site is classified against what its callee RESOLVES to, computed once
    here from the module's own import statements, never against the bound
    name a dodge could rename."""
    import_map: "ImportMap" = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                import_map[local] = (alias.name, None)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:  # a relative `from . import x` -- not this codebase's pattern
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                import_map[local] = (node.module, alias.name)
    return import_map


def _classify_call(node: ast.Call, import_map: "ImportMap") -> str | None:
    """Returns a short description if `node` resolves to a deletion
    primitive, else None."""
    func = node.func
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and base.id in import_map:
            module, bound_attr = import_map[base.id]
            if bound_attr is None and module in MODULE_DELETION_TARGETS and func.attr in MODULE_DELETION_TARGETS[module]:
                return f"{base.id}.{func.attr}(...) -- resolves to {module}.{func.attr}"
        # Not resolvable to a known module import (a local variable, an
        # unresolved name, or a call expression like pathlib.Path(p)) --
        # the receiver-agnostic Path-method check.
        if func.attr in PATH_METHOD_TARGETS:
            return f"<expr>.{func.attr}(...) -- Path-style deletion method"
        return None
    if isinstance(func, ast.Name) and func.id in import_map:
        module, bound_attr = import_map[func.id]
        if bound_attr is not None and module in MODULE_DELETION_TARGETS and bound_attr in MODULE_DELETION_TARGETS[module]:
            return f"{func.id}(...) -- resolves to {module}.{bound_attr}"
    return None


def _function_line_ranges(tree: ast.Module, name: str) -> list[tuple[int, int]]:
    """Every top-level (or nested) function/method literally named `name`,
    as (first_line, last_line) inclusive. More than one definition (e.g. a
    class method shadowing a module function) is deliberately tolerated --
    every one of them is treated as part of the primitive."""
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            last = node.lineno
            for sub in ast.walk(node):
                if hasattr(sub, "lineno"):
                    last = max(last, sub.lineno)
            ranges.append((node.lineno, last))
    return ranges


def find_deletion_violations(paths: list[Path]) -> list[DeletionViolation]:
    """TE-75 S-2: raises ValueError on an empty `paths` -- an empty
    population must never read as a clean scan. Every real caller
    (main() below, and the matrix leg in tools/ci/run_configure_matrix.py)
    goes through this, so neither can bypass it by skipping their own
    guard."""
    if not paths:
        raise ValueError(
            "find_deletion_violations() called with an empty path list -- refusing to report a "
            "clean scan over nothing. Point it at the real tools/pin-superslm/*.py files."
        )
    violations: list[DeletionViolation] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        import_map = _build_import_map(tree)
        primitive_ranges = _function_line_ranges(tree, PRIMITIVE_FUNCTION_NAME)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            description = _classify_call(node, import_map)
            if description is None:
                continue
            line = node.lineno
            inside_primitive = any(lo <= line <= hi for lo, hi in primitive_ranges)
            if not inside_primitive:
                violations.append(DeletionViolation(path, line, description))
    return violations


def scan(paths: list[Path]) -> tuple[int, list[DeletionViolation]]:
    """(modules_scanned, violations) -- the count a caller can assert on
    directly, so "how many files did this actually look at" never has to
    be inferred from an empty violation list (TE-75 S-2)."""
    violations = find_deletion_violations(paths)
    return len(paths), violations


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: pin_superslm_delete_ast_check.py <file.py> [<file.py> ...]", file=sys.stderr)
        return 2
    paths = [Path(a) for a in argv]
    modules_scanned, violations = scan(paths)
    if violations:
        print(f"FAIL: {len(violations)} deletion-primitive call(s) outside {PRIMITIVE_FUNCTION_NAME}() "
              f"({modules_scanned} module(s) scanned):")
        for v in violations:
            print(f"  {v}")
        return 1
    print(f"PASS: every deletion-primitive call is inside {PRIMITIVE_FUNCTION_NAME}() "
          f"({modules_scanned} module(s) scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
