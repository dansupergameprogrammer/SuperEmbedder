"""U2-1: the shared library's export list, generated from semb.h, and the
export-count check against the linked library.

semb.h is the one source of truth for what the shared library exports. This
tool scans it by one rule and writes the platform's export list from that scan
alone, never from a name pattern:

  a declaration is a line matching
    ^(?:SEMB_API\\s+)?(semb_status|const char\\*)\\s+(semb_[a-z0-9_]+)\\(
  -- an optional SEMB_API token (the macro's name as the header's source text
  spells it, never its expansion) ahead of the return type and the verb name.

  python tools/generate_export_list.py generate --header <semb.h>
      --format def|version-script|exported-symbols --out <file>
  python tools/generate_export_list.py check --header <semb.h> --library <shared library>
      [--format elf|macho] [--nm nm]

`generate` writes:
  def               EXPORTS, then one scanned name per line (Windows);
  version-script    { global: <one line per name>; local: *; }; (Linux);
  exported-symbols  one name per line, each with Mach-O's leading underscore,
                    no wildcard (macOS -exported_symbols_list).

`check` is the release-blocking export-count check: it re-derives the set
from semb.h by the same rule, reads the linked library's defined dynamic
symbols (`nm -D --defined-only` on ELF, `nm -gU` on Mach-O), and accepts only
exact equality. Anything else prints one line naming every missing and every
extra symbol and exits 1:

  SEMB_EXPORT_LIST_MISMATCH missing=[...] extra=[...]

A scan that reads no declaration refuses too: an empty list is never accepted
as the header's.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SCAN = re.compile(r"^(?:SEMB_API\s+)?(semb_status|const char\*)\s+(semb_[a-z0-9_]+)\(", re.MULTILINE)


def declared(header: Path) -> list[str]:
    names = [m.group(2) for m in SCAN.finditer(header.read_text(encoding="utf-8"))]
    if len(names) != len(set(names)):
        raise ValueError(f"{header}: a verb is declared twice")
    return names


def render(names: list[str], fmt: str) -> str:
    if fmt == "def":
        return "EXPORTS\n" + "".join(f"  {n}\n" for n in names)
    if fmt == "version-script":
        return "{\n  global:\n" + "".join(f"    {n};\n" for n in names) + "  local:\n    *;\n};\n"
    if fmt == "exported-symbols":
        return "".join(f"_{n}\n" for n in names)
    raise ValueError(f"unknown format {fmt!r}")


def exported(library: Path, fmt: str, nm: str) -> set[str]:
    cmd = [nm, "-D", "--defined-only", str(library)] if fmt == "elf" else [nm, "-gU", str(library)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd)} failed: {r.stderr.strip()}")
    names = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        name = parts[2]
        if fmt == "macho" and name.startswith("_"):
            name = name[1:]
        names.add(name)
    return names


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--header", required=True, type=Path)
    g.add_argument("--format", required=True, choices=("def", "version-script", "exported-symbols"))
    g.add_argument("--out", required=True, type=Path)
    c = sub.add_parser("check")
    c.add_argument("--header", required=True, type=Path)
    c.add_argument("--library", required=True, type=Path)
    c.add_argument("--format", choices=("elf", "macho"), default="elf")
    c.add_argument("--nm", default="nm")
    args = ap.parse_args(argv)

    try:
        names = declared(args.header)
    except (OSError, ValueError) as e:
        print(f"generate_export_list: {e}", file=sys.stderr)
        return 2
    if not names:
        print(f"SEMB_EXPORT_LIST_MISMATCH the scan of {args.header} reads no declaration")
        return 1

    if args.cmd == "generate":
        text = render(names, args.format)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # Written only when the bytes change, so an unchanged header does not
        # relink the library.
        if not args.out.exists() or args.out.read_text(encoding="utf-8") != text:
            args.out.write_text(text, encoding="utf-8", newline="\n")
        return 0

    try:
        have = exported(args.library, args.format, args.nm)
    except (OSError, RuntimeError) as e:
        print(f"generate_export_list: {e}", file=sys.stderr)
        return 2
    want = set(names)
    missing, extra = sorted(want - have), sorted(have - want)
    if missing or extra:
        print(f"SEMB_EXPORT_LIST_MISMATCH missing={missing} extra={extra}")
        return 1
    print(f"generate_export_list: {args.library.name} exports exactly the {len(want)} verbs semb.h declares")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
