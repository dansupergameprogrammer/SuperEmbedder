"""U2-10 Builds item 5: the C-linkage census (C65).

Reads every external, defined, unmangled function symbol in a member's static
archive and accepts the archive only when each one is a row of the boundary
table (tools/c_boundary_table.json) or is on its compiler family's toolchain
list (tools/c_boundary_toolchain_lists.json), and every table row is defined.

  python tools/c_boundary_census.py --archive <lib> --table <json>
      --toolchain-lists <json> --family <family> [--format auto|elf|coff]

Exit 0 on accept. On refusal, exit 1 with one line per refusal on stdout:

  SEMB_C_LINKAGE_UNLISTED <name>   defined in the archive, in neither the
                                   table nor the family's list
  SEMB_C_LINKAGE_STALE <name>      a table row the archive does not define

Exit 2 when the archive cannot be read (a usage error, never an accept).

The symbol rule, per object format:
  ELF   `nm --defined-only <archive>`: type T or W, name without the `_Z`
        prefix.
  COFF  `dumpbin /symbols <archive>`: a `SECTn ... notype () External` line
        whose name carries no `?`.

A family whose list is null has not been derived yet; its list is read as
empty, so every name outside the table refuses, and a note says so on stderr.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_COFF_LINE = re.compile(r"\bSECT[0-9A-F]+\s+notype \(\)\s+External\s+\|\s+(\S+)")


def elf_names(archive: Path) -> set[str]:
    r = subprocess.run(["nm", "--defined-only", str(archive)], capture_output=True, text=True,
                       errors="replace")
    if r.returncode:
        raise RuntimeError(f"nm failed on {archive}: {r.stderr.strip()}")
    names = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in ("T", "W") and not parts[2].startswith("_Z"):
            names.add(parts[2])
    return names


def coff_names(archive: Path) -> set[str]:
    dumpbin = shutil.which("dumpbin") or shutil.which("dumpbin.exe")
    if not dumpbin:
        raise RuntimeError("dumpbin is not on PATH (a COFF archive needs the member's own toolchain)")
    r = subprocess.run([dumpbin, "/symbols", str(archive)], capture_output=True, text=True,
                       errors="replace")
    if r.returncode:
        raise RuntimeError(f"dumpbin failed on {archive}: {r.stderr.strip()}")
    names = set()
    for line in r.stdout.splitlines():
        m = _COFF_LINE.search(line)
        if m and "?" not in m.group(1):
            names.add(m.group(1))
    return names


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--toolchain-lists", required=True)
    ap.add_argument("--family", required=True)
    ap.add_argument("--format", choices=("auto", "elf", "coff"), default="auto")
    args = ap.parse_args(argv)

    archive = Path(args.archive)
    if not archive.is_file():
        print(f"c_boundary_census: no archive at {archive}", file=sys.stderr)
        return 2
    fmt = args.format
    if fmt == "auto":
        fmt = "coff" if archive.suffix.lower() == ".lib" else "elf"
    try:
        defined = coff_names(archive) if fmt == "coff" else elf_names(archive)
        table = json.loads(Path(args.table).read_text(encoding="utf-8"))
        lists = json.loads(Path(args.toolchain_lists).read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError) as e:
        print(f"c_boundary_census: {e}", file=sys.stderr)
        return 2

    rows = {row["name"] for row in table["rows"]}
    family = lists.get("families", {}).get(args.family)
    if family is None:
        print(f"c_boundary_census: family {args.family!r} is not in {args.toolchain_lists}",
              file=sys.stderr)
        return 2
    toolchain = family.get("list")
    if toolchain is None:
        print(f"c_boundary_census: note: family {args.family!r} has no derived list yet; "
              "it is read as empty", file=sys.stderr)
        toolchain = []
    allowed = rows | set(toolchain)

    refusals = [f"SEMB_C_LINKAGE_UNLISTED {name}" for name in sorted(defined - allowed)]
    refusals += [f"SEMB_C_LINKAGE_STALE {name}" for name in sorted(rows - defined)]
    for line in refusals:
        print(line)
    if refusals:
        return 1
    print(f"c_boundary_census: accept: {len(defined)} unmangled external definitions, "
          f"{len(rows)} table rows, family {args.family}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
