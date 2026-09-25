"""tests/te331_u2_export_surface_check.py -- TE-331 (U2-1): the generated
export list, the `SEMB_API` markings, and the release-blocking export-count
check (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-1; F41, TE-313, TE-327).

FOUR CELLS. Each runs its must-reject in the cell: a cell whose predicate
accepts the mutant is read FAIL, so none of them can pass by being unable to
fail.

  GENERATED-LIST   `tools/generate_export_list.py generate` writes, from
                   semb.h alone, the platform's list: a version script
                   `{ global: <one line per scanned name>; local: *; };`, a
                   .def (`EXPORTS` then exactly the names) and a Mach-O list
                   (one `_name` per line, no wildcard) -- each naming exactly
                   the set this cell's own scan reads, never a pattern.
                   Must-rejects: the glob script `{ global: semb_*; local: *; };`
                   is refused by the cell's predicate; and the tool, run on a
                   scratch copy of semb.h with one declaration removed, writes
                   a list without that name (a tool that emits a fixed list
                   fails here). Marking-invariance: the tool reads the same
                   set from a scratch copy with every SEMB_API token removed.

  SEMB-API-MARKED  every declaration the scan reads is marked SEMB_API, and
                   SEMB_API marks nothing else: a SEMB_API token outside the
                   preprocessor lines and comments is always the prefix of a
                   scanned declaration. The macro's own definition lines are
                   not markings and are not counted. Must-rejects: a scratch
                   copy with the marking removed from one declaration, and one
                   with SEMB_API added to a non-verb declaration, are refused.

  SCAN-RULE-MUTATION-PROOF  the plan's corrected rule reads the fourteen
                   frozen verbs (the twelve of `c8d4147` plus U2-7's
                   semb_encoder_open_memory and semb_encode_query) from the
                   header as committed and from a same-line-marked scratch copy;
                   the un-prefixed rule reads 0 from the same-line-marked copy,
                   reproducing F41's finding against this tree's header text.

  EXPORT-COUNT-CHECK  `generate_export_list.py check` is the release-blocking
                   check: it accepts a shared object exporting exactly semb.h's
                   scan, and refuses by name, `SEMB_EXPORT_LIST_MISMATCH`,
                   naming every missing and every extra symbol:
                     - under-export (hidden visibility, no SEMB_API: 0 of N
                       exported -- the must-reject the plan names);
                     - one verb missing;
                     - one internal `semb_` name exported beside the verbs.
                   Scratch shared objects built here with the system C
                   compiler; ELF only (the Windows .def and the macOS list are
                   owed to those members). With --library (the build's
                   libsemb.so), the check also accepts the product's own
                   library, and the root CMakeLists.txt runs the check as the
                   shared target's POST_BUILD step.

EXIT: 0 only if every cell is PASS.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADER = REPO_ROOT / "include" / "superembedder" / "semb.h"
TOOL = REPO_ROOT / "tools" / "generate_export_list.py"

CORRECT_RULE = re.compile(r"^(?:SEMB_API\s+)?(semb_status|const char\*)\s+(semb_[a-z0-9_]+)\(", re.MULTILINE)
WRONG_RULE = re.compile(r"^(semb_status|const char\*)\s+(semb_[a-z0-9_]+)\(", re.MULTILINE)
# The twelve verbs of c8d4147's semb.h plus U2-7 items 1 and 2 ("fourteen
# frozen semb_* verbs", te267 sec 5 U2-7 item 6).
FROZEN = {
    "semb_encoder_open", "semb_encoder_close", "semb_encoder_dims", "semb_encode", "semb_encode_batch",
    "semb_bank_open", "semb_bank_close", "semb_query_open", "semb_query_encode", "semb_query_close",
    "semb_fingerprint_of", "semb_status_name", "semb_encoder_open_memory", "semb_encode_query",
}


def scan(text: str, rule=CORRECT_RULE) -> list[str]:
    return [m.group(2) for m in rule.finditer(text)]


def strip_comments_and_pp(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in text.splitlines())


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


# --------------------------------------------------------------------------
def list_names(text: str, fmt: str) -> tuple[set[str], bool]:
    """(names, well-formed) of a generated list, by this cell's own reading."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if fmt == "version-script":
        m = re.fullmatch(r"\{\s*global:\s*(.*?)\s*local:\s*\*;\s*\};", " ".join(lines), re.S)
        if not m:
            return set(), False
        items = [i.strip() for i in m.group(1).split(";") if i.strip()]
        return set(items), all(re.fullmatch(r"semb_[a-z0-9_]+", i) for i in items)
    if fmt == "def":
        if not lines or lines[0] != "EXPORTS":
            return set(), False
        return set(lines[1:]), all(re.fullmatch(r"semb_[a-z0-9_]+", i) for i in lines[1:])
    return {ln[1:] for ln in lines}, all(re.fullmatch(r"_semb_[a-z0-9_]+", ln) for ln in lines)


def list_ok(text: str, fmt: str, want: set[str]) -> bool:
    names, well_formed = list_names(text, fmt)
    return well_formed and names == want


def generate(header: Path, fmt: str, out: Path) -> str | None:
    r = run([sys.executable, str(TOOL), "generate", "--header", str(header), "--format", fmt, "--out", str(out)])
    return out.read_text(encoding="utf-8") if r.returncode == 0 and out.exists() else None


def cell_generated_list(work: Path) -> str:
    if not TOOL.exists():
        print(f"[FAIL] GENERATED-LIST: {TOOL.relative_to(REPO_ROOT)} does not exist")
        return "FAIL"
    text = HEADER.read_text(encoding="utf-8")
    want = set(scan(text))
    ok = True
    for fmt in ("version-script", "def", "exported-symbols"):
        got = generate(HEADER, fmt, work / f"list.{fmt}")
        good = got is not None and list_ok(got, fmt, want)
        ok &= good
        print(f"  {fmt}: {'exactly the scan' if good else 'NOT the scan'} "
              f"({len(list_names(got or '', fmt)[0])} names, scan {len(want)})")
    glob = "{\n  global:\n    semb_*;\n  local:\n    *;\n};\n"
    rej_glob = not list_ok(glob, "version-script", want)
    dropped = sorted(want)[0]
    minus = work / "semb_minus_one.h"
    minus.write_text(re.sub(rf"^(?:SEMB_API\s+)?\S+[ \t]+{dropped}\(", "/* removed */ void removed_declaration(",
                            text, count=1, flags=re.M), encoding="utf-8")
    got_minus = generate(minus, "version-script", work / "list_minus.map")
    follows = got_minus is not None and list_ok(got_minus, "version-script", want - {dropped})
    unmarked = work / "semb_unmarked.h"
    unmarked.write_text(re.sub(r"^SEMB_API\s+", "", text, flags=re.M), encoding="utf-8")
    got_unmarked = generate(unmarked, "version-script", work / "list_unmarked.map")
    invariant = got_unmarked is not None and list_ok(got_unmarked, "version-script", want)
    status = "PASS" if ok and rej_glob and follows and invariant else "FAIL"
    print(f"[{status}] GENERATED-LIST: every format names exactly semb.h's {len(want)} scanned verbs ({ok}); "
          f"must-reject glob script refused ({rej_glob}); the list follows the header (one declaration removed "
          f"-> {dropped} absent) ({follows}); SEMB_API-stripped header gives the same list ({invariant})")
    return status


# --------------------------------------------------------------------------
def marking_ok(text: str) -> tuple[bool, str]:
    body = strip_comments_and_pp(text)
    decls = list(CORRECT_RULE.finditer(body))
    unmarked = [m.group(2) for m in decls if not m.group(0).startswith("SEMB_API")]
    marked_starts = {m.start() for m in decls if m.group(0).startswith("SEMB_API")}
    tokens = [m.start() for m in re.finditer(r"\bSEMB_API\b", body)]
    stray = [t for t in tokens if t not in marked_starts]
    ok = bool(decls) and not unmarked and not stray
    return ok, f"{len(decls)} declarations, unmarked {unmarked}, SEMB_API tokens not marking one: {len(stray)}"


def cell_semb_api_marked() -> str:
    text = HEADER.read_text(encoding="utf-8")
    ok, detail = marking_ok(text)
    first = sorted(scan(text))[0]
    m_unmark = re.sub(rf"^SEMB_API\s+(\S+[ \t]+{first}\()", r"\1", text, count=1, flags=re.M)
    m_extra = text.replace("#ifdef __cplusplus", "SEMB_API\nint semb_internal_not_a_verb(void);\n#ifdef __cplusplus", 1)
    rej_unmark = m_unmark != text and not marking_ok(m_unmark)[0]
    rej_extra = m_extra != text and not marking_ok(m_extra)[0]
    status = "PASS" if ok and rej_unmark and rej_extra else "FAIL"
    print(f"[{status}] SEMB-API-MARKED: {detail}; must-rejects refused: {first} unmarked ({rej_unmark}), "
          f"SEMB_API on a non-verb ({rej_extra})")
    return status


# --------------------------------------------------------------------------
def cell_scan_rule_mutation_proof() -> str:
    header = HEADER.read_text(encoding="utf-8")
    same_line = WRONG_RULE.sub(lambda m: "SEMB_API " + m.group(0), re.sub(r"^SEMB_API\s*\n", "", header,
                                                                          flags=re.M))
    committed_correct = set(scan(header))
    same_correct = set(scan(same_line))
    same_wrong = set(scan(same_line, WRONG_RULE))
    ok = committed_correct == FROZEN and same_correct == FROZEN and not same_wrong
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] SCAN-RULE-MUTATION-PROOF: the corrected rule reads the {len(FROZEN)} frozen verbs from the "
          f"committed header ({committed_correct == FROZEN}; {len(committed_correct)}) and from a same-line-marked "
          f"copy ({same_correct == FROZEN}); the un-prefixed rule reads {len(same_wrong)} from that copy (want 0)"
          + ("" if committed_correct == FROZEN else
             f"; missing {sorted(FROZEN - committed_correct)} extra {sorted(committed_correct - FROZEN)}"))
    return status


# --------------------------------------------------------------------------
def build_so(work: Path, name: str, funcs: list[str], hidden: bool, cc: str) -> Path | None:
    src = work / f"{name}.c"
    src.write_text("".join(f"void {f}(void) {{}}\n" for f in funcs), encoding="utf-8")
    so = work / f"lib{name}.so"
    args = [cc, "-shared", "-fPIC", "-o", str(so), str(src)] + (["-fvisibility=hidden"] if hidden else [])
    r = run(args)
    if r.returncode:
        print(f"  compile {name} failed: {r.stderr.strip()[-300:]}")
        return None
    return so


def check(library: Path) -> subprocess.CompletedProcess:
    return run([sys.executable, str(TOOL), "check", "--header", str(HEADER), "--library", str(library),
                "--format", "elf"])


def cell_export_count_check(work: Path, library: str, cc: str) -> str:
    if not TOOL.exists():
        print(f"[FAIL] EXPORT-COUNT-CHECK: {TOOL.relative_to(REPO_ROOT)} does not exist")
        return "FAIL"
    if sys.platform == "win32" or not shutil.which("nm") or not shutil.which(cc):
        print("[MISSING PREREQUISITE] EXPORT-COUNT-CHECK: needs ELF, nm and a C compiler; the Windows .def and "
              "the dumpbin /exports reading are owed to the MSVC members")
        return "MISSING PREREQUISITE"
    verbs = sorted(scan(HEADER.read_text(encoding="utf-8")))
    ok = True
    exact = build_so(work, "exact", verbs, False, cc)
    r = check(exact) if exact else None
    acc = r is not None and r.returncode == 0 and "SEMB_EXPORT_LIST_MISMATCH" not in r.stdout
    ok &= acc
    print(f"  must-accept (exactly the {len(verbs)} verbs): exit {r.returncode if r else '-'} ({acc})")

    def refuses(so: Path | None, missing: list[str], extra: list[str], label: str) -> bool:
        if so is None:
            return False
        r = check(so)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("SEMB_EXPORT_LIST_MISMATCH")), "")
        good = r.returncode != 0 and line != "" and all(n in line for n in missing) and \
            all(n in line for n in extra)
        m = re.search(r"missing=\[(.*?)\]", line)
        named_missing = len(re.findall(r"semb_[a-z0-9_]+", m.group(1))) if m else -1
        good &= named_missing == len(missing)
        print(f"  must-reject ({label}): exit {r.returncode}, names {named_missing} missing ({good}): {line[:160]}")
        return good

    ok &= refuses(build_so(work, "hidden", verbs, True, cc), verbs, [], f"under-export, 0 of {len(verbs)}")
    ok &= refuses(build_so(work, "minus", verbs[1:], False, cc), verbs[:1], [], f"{verbs[0]} missing")
    leak = "semb_interim_encoder_open"
    ok &= refuses(build_so(work, "extra", verbs + [leak], False, cc), [], [leak], f"{leak} exported")
    own = "not given"
    if library:
        r = check(Path(library))
        own_ok = r.returncode == 0
        ok &= own_ok
        own = f"exit {r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}"
    cm = (REPO_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    # A reading of the root CMakeLists.txt: the shared target's POST_BUILD runs
    # this tool's `check` (a failing POST_BUILD fails the build).
    step = re.search(r'add_custom_command\(TARGET superembedder_shared POST_BUILD\s+COMMAND\s+'
                     r'"\$\{Python3_EXECUTABLE\}"\s+"\$\{_semb_export_tool\}"\s+check\b', cm) is not None and \
        re.search(r'set\(_semb_export_tool\s+"\$\{CMAKE_SOURCE_DIR\}/tools/generate_export_list\.py"\)', cm) is not None
    ok &= step
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] EXPORT-COUNT-CHECK: accepts exact equality and refuses SEMB_EXPORT_LIST_MISMATCH by name on "
          f"under-export, a missing verb and an extra name; the build's own libsemb.so: {own}; the root "
          f"CMakeLists.txt runs the check after the shared library links ({step})")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", default="", help="the build's shared library (libsemb.so)")
    ap.add_argument("--work", default="", help="scratch directory")
    ap.add_argument("--cc", default="cc")
    args = ap.parse_args()
    work = Path(args.work) if args.work else REPO_ROOT / "build" / "_scratch" / "te331_export_surface"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    results = [
        cell_generated_list(work),
        cell_semb_api_marked(),
        cell_scan_rule_mutation_proof(),
        cell_export_count_check(work, args.library, args.cc),
    ]
    red = [r for r in results if r == "FAIL"]
    print(f"TOTAL cells={len(results)} failed={len(red)}: {results}")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
