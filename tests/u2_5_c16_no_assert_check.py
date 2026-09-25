"""U2 cloud build: U2-5's C16 (te267 sec 5 U2-5): a structural check that
`src/` and `include/` contain no `assert(` -- a guard written as `assert`
vanishes in a Release build, so a refusal would silently become success.

The rule matches `assert` as a whole identifier followed by `(` (so
`static_assert(` and `my_assert(` are not matches), in every file under
`src/` and `include/`, comments included (a commented-out guard is still a
guard someone may restore). Its vitality is checked in the cell on every run:
the rule must find a planted `assert(` and must pass `static_assert(`.

Green by construction today (0 matches); it keeps the count at 0.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULE = re.compile(r"(?<![A-Za-z0-9_])assert\s*\(")


def scan(text: str) -> list[int]:
    return [i + 1 for i, line in enumerate(text.splitlines()) if RULE.search(line)]


def main() -> int:
    fails = 0
    planted = "int f(int x) {\n  static_assert(sizeof(int) == 4);\n  assert(x > 0);\n  return x;\n}\n"
    vital = scan(planted) == [3] and not scan("static_assert(true);\nmy_assert(1);\n")
    print(f"[{'PASS' if vital else 'FAIL'}] C16 vitality: the rule finds a planted assert( and passes "
          f"static_assert(/my_assert(: planted hits {scan(planted)}")
    fails += 0 if vital else 1
    hits = []
    files = 0
    for root in ("src", "include"):
        for p in sorted((REPO_ROOT / root).rglob("*")):
            if p.is_file() and p.suffix in (".h", ".hpp", ".c", ".cc", ".cpp", ".cxx", ".inc", ".inl", ""):
                files += 1
                for ln in scan(p.read_text(encoding="utf-8", errors="replace")):
                    hits.append(f"{p.relative_to(REPO_ROOT)}:{ln}")
    ok = not hits and files > 0
    print(f"[{'PASS' if ok else 'FAIL'}] C16: no assert( in src/ or include/ ({files} files): "
          f"{len(hits)} match(es) {hits[:10]}")
    fails += 0 if ok else 1
    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
