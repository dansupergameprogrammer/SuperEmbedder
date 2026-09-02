"""tests/pin_superslm_delete_ast_check.py -- TE-73: the structural cell that
closes the data-loss class R-1 and Q-1 kept re-opening one site at a time.

WHY THIS EXISTS (TE-73, brief "the pin tool gets one deletion primitive, and
nothing else in it can delete"): three consecutive fix rounds (TE-69's Q-1,
TE-71's R-1) each guarded the ONE deletion site a reviewer had just named
and left a sibling site -- written with a different idiom, in the same
file -- untouched. `Claude/CLAUDE.md`'s own standing rule (StandardsDocument
Sec4) is that a rule enforced by a person remembering every call site is a
rule that has already failed; the fix removes the class rather than adding
another guarded site. `tools/pin-superslm/pin_superslm.py` now has exactly
ONE function, `_remove_owned`, permitted to call a real deletion primitive
(`shutil.rmtree`, `os.remove`, `os.unlink`, `os.rmdir`, or a `Path.unlink()`/
`Path.rmdir()` method call) anywhere in the module. This file walks that
module's own AST (never trusts a grep, which a renamed import or a `from
shutil import rmtree as x` could dodge) and asserts that every such call
lands inside `_remove_owned`'s own line range -- nowhere else, in that
module or in any sibling module under the same package.

Usage: `find_deletion_violations(paths)` returns a list of
`DeletionViolation` (file, line, description) for every deletion-primitive
call found outside `_remove_owned`. An empty list is the passing state.
Run directly (`python tests/pin_superslm_delete_ast_check.py <path>...`) to
print violations and exit 1 if any exist, 0 otherwise -- used standalone to
show this red against a historical revision (`git show <rev>:path > tmp`)
and green at the tip.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

PRIMITIVE_FUNCTION_NAME = "_remove_owned"

# Deletion-primitive attribute names this check flags regardless of the
# object they are called on: os.remove/os.unlink/os.rmdir (module-level
# functions) and Path.unlink()/Path.rmdir() (bound methods) collapse to the
# same three attribute names; shutil.rmtree is checked by its own (module,
# attr) pair since "rmtree" as a bare method name is not otherwise used in
# this codebase.
_OS_STYLE_ATTRS = {"remove", "unlink", "rmdir"}


@dataclass(frozen=True)
class DeletionViolation:
    file: Path
    line: int
    description: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.description}"


def _is_deletion_call(node: ast.Call) -> str | None:
    """Returns a short description if `node` is a deletion-primitive call,
    else None. Deliberately structural (AST shape), not textual -- a rename
    of the local `shutil` import, or a re-export, does not change what
    ast.Attribute/ast.Name nodes are actually present here."""
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr == "rmtree":
            # shutil.rmtree(...) -- the module-qualified form this codebase
            # has always used. A bare `rmtree(...)` (no attribute access) is
            # caught by the ast.Name branch below instead.
            if isinstance(func.value, ast.Name) and func.value.id == "shutil":
                return "shutil.rmtree(...)"
            return f"<expr>.rmtree(...) -- non-shutil-qualified, still a deletion primitive"
        if func.attr in _OS_STYLE_ATTRS:
            if isinstance(func.value, ast.Name) and func.value.id == "os":
                return f"os.{func.attr}(...)"
            # Any other object's .remove()/.unlink()/.rmdir() -- Path's own
            # unlink()/rmdir(), or an equivalent, are the only realistic
            # callers of these three names on a non-`os` object in this
            # codebase; flagged the same way regardless of the receiver.
            return f"<expr>.{func.attr}(...) -- Path-style deletion method"
    elif isinstance(func, ast.Name):
        if func.id in ("rmtree",):
            return f"{func.id}(...) -- bare call to a module-level deletion helper"
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
    violations: list[DeletionViolation] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        primitive_ranges = _function_line_ranges(tree, PRIMITIVE_FUNCTION_NAME)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            description = _is_deletion_call(node)
            if description is None:
                continue
            line = node.lineno
            inside_primitive = any(lo <= line <= hi for lo, hi in primitive_ranges)
            if not inside_primitive:
                violations.append(DeletionViolation(path, line, description))
    return violations


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: pin_superslm_delete_ast_check.py <file.py> [<file.py> ...]", file=sys.stderr)
        return 2
    paths = [Path(a) for a in argv]
    violations = find_deletion_violations(paths)
    if violations:
        print(f"FAIL: {len(violations)} deletion-primitive call(s) outside {PRIMITIVE_FUNCTION_NAME}():")
        for v in violations:
            print(f"  {v}")
        return 1
    print(f"PASS: every deletion-primitive call is inside {PRIMITIVE_FUNCTION_NAME}()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
