"""U2 cloud build: U2-10's C65 commissioning constructions (te267 sec 5 U2-10,
C65 "Commissioned before its verdicts count"). The builder builds the census
tool (Builds item 5); the test author constructs, before the build:

  must-accept  the pin-step archive (this tree's libsuperembedder.a) against a
               table of its own 37 names (tools/c_boundary_table.json): the
               census accepts.
  must-reject  the same archive with one C-linkage definition added outside the
               table, compiled by the member's own build path (the build's own
               compile command for a product TU, with only the source and
               output swapped), refused `SEMB_C_LINKAGE_UNLISTED <name>`.
  vitality     the table with one row whose function the archive lacks,
               refused `SEMB_C_LINKAGE_STALE <name>`.

The census tool's command line is this suite's statement of it (a build-time
item: the builder's tool matches it, or this script changes with it):

  python tools/c_boundary_census.py --archive <lib> --table <json>
      --toolchain-lists <json> --family <family>
  exit 0 on accept; nonzero on refusal, with one line per refusal:
  `SEMB_C_LINKAGE_UNLISTED <name>` or `SEMB_C_LINKAGE_STALE <name>`.

RED TODAY: the tool does not exist, so the constructions cannot run (the
plan: "its red state is its must-reject, which runs with its must-accept once
the tool exists"). The constructions themselves are built and self-checked
here now, by this script's own ELF symbol rule, so they are ready when the
tool lands.
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "c_boundary_census.py"
TABLE = REPO_ROOT / "tools" / "c_boundary_table.json"
LISTS = REPO_ROOT / "tools" / "c_boundary_toolchain_lists.json"
UNLISTED = "semb_c65_commissioning_unlisted"
STALE = "semb_c65_commissioning_stale"
FAMILY = "gcc13.3.0"


def elf_unmangled(archive: Path) -> set[str]:
    out = subprocess.run(["nm", "--defined-only", str(archive)], capture_output=True, text=True,
                         errors="replace").stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in ("T", "W") and not parts[2].startswith("_Z"):
            names.add(parts[2])
    return names


def build_mutant_archive(build_dir: Path, archive: Path, work: Path) -> tuple[Path | None, str]:
    """The same archive plus one C-linkage definition, compiled by the build's own command."""
    comp = subprocess.run(["ninja", "-C", str(build_dir), "-t", "compdb"], capture_output=True, text=True)
    if comp.returncode:
        return None, "ninja -t compdb failed (the must-reject needs the member's own compile command)"
    entry = next((e for e in json.loads(comp.stdout)
                  if e["file"].endswith("src/superembedder/encoder.cpp")
                  and "superembedder.dir" in e["output"]), None)
    if entry is None:
        return None, "no compile command for the shipped target's encoder.cpp"
    src = work / "c65_unlisted.cpp"
    obj = work / "c65_unlisted.cpp.o"
    src.write_text(f'extern "C" int {UNLISTED}(void) {{ return 65; }}\n', encoding="utf-8")
    argv = shlex.split(entry["command"])
    for i, a in enumerate(argv):
        if a == "-o":
            argv[i + 1] = str(obj)
        elif a == "-c":
            argv[i + 1] = str(src)
        elif a in ("-MF", "-MT", "-MQ"):
            argv[i + 1] = str(work / "c65_unlisted.d")
    r = subprocess.run(argv, cwd=entry["directory"], capture_output=True, text=True)
    if r.returncode:
        return None, "compile failed: " + (r.stdout + r.stderr)[-800:]
    mutant = work / "libsuperembedder_c65_unlisted.a"
    shutil.copy2(archive, mutant)
    r = subprocess.run(["ar", "r", str(mutant), str(obj)], capture_output=True, text=True)
    if r.returncode:
        return None, "ar failed: " + r.stderr
    return mutant, ""


def run_tool(archive: Path, table: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--archive", str(archive), "--table", str(table),
                           "--toolchain-lists", str(LISTS), "--family", FAMILY],
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--archive", required=True)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    archive = Path(args.archive)
    work = build_dir / "_scratch" / "c65"
    work.mkdir(parents=True, exist_ok=True)
    fails = 0

    def verdict(ok: bool, cell: str, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")

    table = json.loads(TABLE.read_text(encoding="utf-8"))
    names = {r["name"] for r in table["rows"]}
    # Construction self-checks (this script's own ELF rule, not the tool's).
    base = elf_unmangled(archive)
    verdict(base == names and len(names) == 37, "C65 construction: must-accept archive defines exactly the 37 rows",
            f"archive {len(base)}, table {len(names)}, archive-only {sorted(base - names)}, "
            f"table-only {sorted(names - base)}")
    mutant, why = build_mutant_archive(build_dir, archive, work)
    if mutant is None:
        verdict(False, "C65 construction: must-reject archive", why)
    else:
        extra = elf_unmangled(mutant) - base
        verdict(extra == {UNLISTED}, "C65 construction: must-reject archive adds exactly one unlisted C definition",
                f"added {sorted(extra)}")
    stale_table = dict(table)
    stale_table["rows"] = list(table["rows"]) + [dict(table["rows"][-1], name=STALE)]
    stale_path = work / "c_boundary_table_c65_stale.json"
    stale_path.write_text(json.dumps(stale_table, indent=1), encoding="utf-8")
    verdict(STALE not in base, "C65 construction: vitality table carries one row the archive lacks", STALE)

    if not TOOL.exists():
        verdict(False, "C65 must-accept / must-reject / vitality",
                f"the census tool {TOOL.relative_to(REPO_ROOT)} does not exist (U2-10 Builds item 5); "
                "the constructions above are ready for it")
        print(f"TOTAL fail={fails}")
        return 1
    r = run_tool(archive, TABLE)
    verdict(r.returncode == 0, "C65 must-accept: pin-step archive vs its own 37 names",
            f"exit {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}")
    if mutant is not None:
        r = run_tool(mutant, TABLE)
        verdict(r.returncode != 0 and f"SEMB_C_LINKAGE_UNLISTED {UNLISTED}" in r.stdout,
                "C65 must-reject: one unlisted C-linkage definition -> SEMB_C_LINKAGE_UNLISTED",
                f"exit {r.returncode}: {r.stdout.strip()[-300:]}")
    r = run_tool(archive, stale_path)
    verdict(r.returncode != 0 and f"SEMB_C_LINKAGE_STALE {STALE}" in r.stdout,
            "C65 vitality: a table row the archive lacks -> SEMB_C_LINKAGE_STALE",
            f"exit {r.returncode}: {r.stdout.strip()[-300:]}")
    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
