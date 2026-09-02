"""tests/witness_no_foreign_reading_check.py -- TE-86 (U0 slice C): the
structural check for C31(iv) (SEMB_WITNESS_FOREIGN_READING) and C36(e)'s
identical property (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4d item 3,
sec 8 C31/C36) -- both names describe the SAME absence: no code path in
the witness executable's own translation unit reads any of the five
fingerprint fields from outside the process that computed them.

WHY A STRUCTURAL CHECK, NOT A RUNTIME STATUS (sec 8, D-SLM6156): the
property being proven is the ABSENCE of a code path. A runtime `SEMB_*`
refusal has nothing to construct a violation of -- there is no code path
to make return the wrong thing. Proven, if at all, by a check that reads
the source and can itself fail (never a claim nobody runs).

METHOD (on tests/pin_superslm_delete_ast_check.py's own grep pattern,
adapted for C++ source rather than Python AST -- no C++ parser is
available in this project, so this is a deliberately unambitious lexer,
not a frontend): scan src/witness/witness_main.cpp for three classes of
forbidden call, after blanking out // line comments, /* */ block
comments, and quoted string/char literals character-for-character (same
length, so reported line numbers stay accurate) -- a forbidden-looking
token inside a comment or a string literal does not false-positive.

  1. getenv / std::getenv -- any read of process environment.
  2. A file-open call against a path other than the CLI-supplied model
     artifact path (this TU's own `model_path` variable) -- fopen,
     _wfopen, POSIX ::open, the Win32 CreateFileA/CreateFileW family, or
     constructing a std::ifstream/ofstream/fstream.
  3. A socket or IPC-adjacent API -- socket/connect/bind/listen/accept/
     send*/recv*, POSIX popen, the Win32 named-pipe family, or
     WSAStartup.

Any hit refuses. Two constructions, both real, both fired by this
module's own run_construction() (shared with
tests/witness_structural_matrix.py's C31(iv) and C36(e) legs, which
import it rather than re-implementing it -- sec 8's own framing: one
property, two cell names, one shared implementation):

  MUST-ACCEPT -- the tip's own witness_main.cpp: zero hits (confirmed by
  reading, this session and TE-84's own; this module now makes it a
  check that can fail rather than a claim nobody runs).
  MUST-REJECT -- a scratch COPY of witness_main.cpp (never the tracked
  file) with one line inserted: a getenv("SEMB_WITNESS_SHA_OVERRIDE")
  call whose result is assigned into the printed digest. The check must
  flag it, by the getenv rule specifically.

THIS CELL IS GREEN AT THE TIP BY DESIGN -- the property already holds --
and both of its constructions fire now (unlike C31(i)/C31(ii)/C36(a),
which are red at this tip for a real, named reason).

Usage: `python tests/witness_no_foreign_reading_check.py --selftest` runs
both constructions and exits 0 only if both fire correctly.
`python tests/witness_no_foreign_reading_check.py <file.cpp> ...` scans
the given file(s) directly and exits 1 if any violation is found, 0
otherwise -- used to grade an arbitrary file (e.g. a future W-Q
translation unit) against the same rule.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WITNESS_MAIN = REPO_ROOT / "src" / "witness" / "witness_main.cpp"

GETENV_PATTERN = re.compile(r"\b(?:std::)?getenv\s*\(")
FILE_OPEN_PATTERN = re.compile(
    r"\b(?:fopen|_wfopen|CreateFileA|CreateFileW)\s*\("
    r"|::open\s*\("
    r"|\bstd::(?:ifstream|ofstream|fstream)\b"
)
SOCKET_IPC_PATTERN = re.compile(
    r"\b(?:socket|connect|bind|listen|accept|send|sendto|recv|recvfrom|popen|"
    r"CreateNamedPipeA|CreateNamedPipeW|WSAStartup)\s*\("
)

# The CLI-supplied artifact path this TU parses (--model) -- sec 4.4d item
# 3's own carve-out: a file-open call against THIS path is not a foreign
# read. Named by the variable witness_main.cpp itself uses.
CLI_SUPPLIED_PATH_TOKEN = "model_path"


@dataclass(frozen=True)
class ForeignReadingViolation:
    file: Path
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: [{self.kind}] {self.text.strip()}"


def _strip_comments_and_strings(source: str) -> str:
    """Blanks out // line comments, /* */ block comments, and quoted
    string/char literals -- character-for-character (newlines preserved,
    everything else replaced with a space), so line numbers stay accurate
    and a forbidden-looking token inside a comment or a string literal
    does not false-positive. Deliberately unambitious: this project's own
    witness_main.cpp has no raw string literals, trigraphs, or line
    continuations, and this is a lexer for THIS check, not a C++
    frontend."""
    out: list[str] = []
    i = 0
    n = len(source)
    in_line_comment = False
    in_block_comment = False
    in_string = False
    in_char = False
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
                out.append(c)
            else:
                out.append(" ")
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                out.append("  ")
                in_block_comment = False
                i += 2
                continue
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        if in_string:
            if c == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if c == '"':
                in_string = False
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        if in_char:
            if c == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if c == "'":
                in_char = False
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line_comment = True
            out.append("  ")
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            out.append("  ")
            i += 2
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "'":
            in_char = True
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def find_foreign_reading_violations(path: Path) -> list[ForeignReadingViolation]:
    """Every forbidden call in `path`, resolved as above. Raises
    ValueError if `path` does not exist -- a missing file must never read
    as a clean scan (the same discipline
    tests/pin_superslm_delete_ast_check.py's find_deletion_violations()
    holds for an empty path list)."""
    if not path.exists():
        raise ValueError(f"find_foreign_reading_violations(): {path} does not exist -- refusing to "
                         f"report a clean scan over a file that was never read")
    raw = path.read_text(encoding="utf-8")
    stripped = _strip_comments_and_strings(raw)
    stripped_lines = stripped.splitlines()
    raw_lines = raw.splitlines()
    violations: list[ForeignReadingViolation] = []
    for lineno, line in enumerate(stripped_lines, start=1):
        raw_line = raw_lines[lineno - 1] if lineno - 1 < len(raw_lines) else ""
        if GETENV_PATTERN.search(line):
            violations.append(ForeignReadingViolation(path, lineno, "getenv", raw_line))
        if SOCKET_IPC_PATTERN.search(line):
            violations.append(ForeignReadingViolation(path, lineno, "socket_or_ipc", raw_line))
        if FILE_OPEN_PATTERN.search(line):
            # sec 4.4d item 3's own carve-out: a file-open call against the
            # CLI-supplied artifact path is not a foreign read -- flagged
            # only when the CLI-supplied path token is ABSENT from the
            # same line.
            if CLI_SUPPLIED_PATH_TOKEN not in line:
                violations.append(ForeignReadingViolation(path, lineno, "file_open", raw_line))
    return violations


def run_construction() -> tuple[bool, str]:
    """Both constructions, real, executed: MUST-ACCEPT against the tip's
    own witness_main.cpp, MUST-REJECT against a scratch copy with one
    getenv(...) line inserted and assigned into the printed digest.
    Returns (passed, message) -- passed True only if BOTH fire correctly.
    Shared by this module's own --selftest and by
    tests/witness_structural_matrix.py's C31(iv)/C36(e) legs."""
    if not WITNESS_MAIN.exists():
        return False, f"MUST-ACCEPT could not run: {WITNESS_MAIN} does not exist"

    accept_violations = find_foreign_reading_violations(WITNESS_MAIN)
    if accept_violations:
        return False, ("MUST-ACCEPT FAILED: the tip's own witness_main.cpp is flagged, which must "
                        f"never happen: {[str(v) for v in accept_violations]}")

    scratch_dir = REPO_ROOT / "build" / "_scratch" / "witness_no_foreign_reading_check"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_file = scratch_dir / "witness_main_mustreject.cpp"
    text = WITNESS_MAIN.read_text(encoding="utf-8")
    anchor = "  // witness_sha = SHA-256(W-A || W-B || W-Q), sec 4.4b's own formula.\n" \
             "  uint8_t witness_sha[32];"
    if anchor not in text:
        return False, (f"MUST-REJECT could not be constructed: the anchor text used to insert the "
                        f"getenv(...) override is no longer present in {WITNESS_MAIN} -- update this "
                        f"check's own anchor to match the current source")
    injected = text.replace(
        anchor,
        "  // witness_sha = SHA-256(W-A || W-B || W-Q), sec 4.4b's own formula.\n"
        "  uint8_t witness_sha[32];\n"
        "  // TE-86 MUST-REJECT construction only -- never present at the tip.\n"
        "  if (const char* semb_test_override = getenv(\"SEMB_WITNESS_SHA_OVERRIDE\")) {\n"
        "    std::memcpy(witness_sha, semb_test_override, sizeof(witness_sha));\n"
        "  }",
        1,
    )
    scratch_file.write_text(injected, encoding="utf-8")

    reject_violations = find_foreign_reading_violations(scratch_file)
    getenv_hits = [v for v in reject_violations if v.kind == "getenv"]
    if not getenv_hits:
        return False, (f"MUST-REJECT FAILED: the scratch copy with an inserted "
                        f"getenv(\"SEMB_WITNESS_SHA_OVERRIDE\") line was NOT flagged -- the check "
                        f"cannot detect the hazard it exists to catch. All violations found: "
                        f"{[str(v) for v in reject_violations]}")

    return True, (f"MUST-ACCEPT: {WITNESS_MAIN} -- 0 violations. MUST-REJECT: scratch copy with one "
                  f"inserted getenv(\"SEMB_WITNESS_SHA_OVERRIDE\") line assigned into witness_sha -- "
                  f"flagged at {getenv_hits[0]}")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--selftest":
        passed, message = run_construction()
        print(("PASS: " if passed else "FAIL: ") + message)
        return 0 if passed else 1
    if not argv:
        print("usage: witness_no_foreign_reading_check.py <file.cpp> [<file.cpp> ...] | --selftest",
              file=sys.stderr)
        return 2
    all_violations: list[ForeignReadingViolation] = []
    scanned = 0
    for a in argv:
        all_violations.extend(find_foreign_reading_violations(Path(a)))
        scanned += 1
    if all_violations:
        print(f"FAIL: {len(all_violations)} foreign-reading violation(s) across {scanned} file(s):")
        for v in all_violations:
            print(f"  {v}")
        return 1
    print(f"PASS: no foreign-reading violations across {scanned} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
