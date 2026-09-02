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

Any hit refuses. Constructions, all real, all fired by this module's own
run_construction() (shared with tests/witness_structural_matrix.py's
C31(iv) and C36(e) legs, which import it rather than re-implementing it --
sec 8's own framing: one property, two cell names, one shared
implementation):

  MUST-ACCEPT -- the tip's own witness_main.cpp: zero hits (confirmed by
  reading, this session and TE-84's own; this module now makes it a
  check that can fail rather than a claim nobody runs).
  MUST-REJECT, one per declared rule class (TE-89, TE-88 review S-7: only
  getenv had one before this round -- the other two declared classes had
  never been shown able to fire):
    - getenv -- a scratch COPY with one line inserted:
      getenv("SEMB_WITNESS_SHA_OVERRIDE") assigned into the printed
      digest.
    - file_open -- a scratch COPY opening a path DERIVED from model_path
      (a sidecar file), never model_path itself -- the exact shape TE-89
      found the carve-out (below) wrongly exempting when it was
      evaluated over the whole LINE rather than the call's own argument.
    - socket_or_ipc -- a scratch COPY calling socket(...).
  MUST-ACCEPT regression (TE-89, S-7) -- a scratch COPY opening
  model_path.c_str() ITSELF (the carve-out's own positive case) must
  stay unflagged, confirming the argument-scoped carve-out below did not
  become "never exempt anything."

THIS CELL IS GREEN AT THE TIP BY DESIGN -- the property already holds --
and every one of its constructions fires now (unlike C31(i)/C31(ii)/
C36(a), which are red at this tip for a real, named reason).

Usage: `python tests/witness_no_foreign_reading_check.py --selftest` runs
every construction above and exits 0 only if all of them fire correctly.
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
# TE-89 (TE-88 review S-7): every alternative now matches THROUGH its own
# call's opening '(' (the constructor form gains `\s*\w*\s*\(` to consume
# an optional local-variable name, e.g. `std::ifstream sidecar(`) --
# find_foreign_reading_violations() uses the match's own end position to
# locate and extract the call's real argument list, rather than treating
# the carve-out as a whole-LINE substring test.
FILE_OPEN_PATTERN = re.compile(
    r"\b(?:fopen|_wfopen|CreateFileA|CreateFileW)\s*\("
    r"|::open\s*\("
    r"|\bstd::(?:ifstream|ofstream|fstream)\b\s*\w*\s*\("
)
SOCKET_IPC_PATTERN = re.compile(
    r"\b(?:socket|connect|bind|listen|accept|send|sendto|recv|recvfrom|popen|"
    r"CreateNamedPipeA|CreateNamedPipeW|WSAStartup)\s*\("
)

# The CLI-supplied artifact path this TU parses (--model) -- sec 4.4d item
# 3's own carve-out: a file-open call against THIS path is not a foreign
# read. Named by the variable witness_main.cpp itself uses.
CLI_SUPPLIED_PATH_TOKEN = "model_path"
# TE-89 (TE-88 review S-7): the carve-out exempts a file-open call whose
# FIRST ARGUMENT, trimmed, is exactly one of these two spellings -- never a
# call whose argument merely CONTAINS the token (`std::string(model_path) +
# ".sidecar"` builds a DIFFERENT path and is not exempt) and never a call on
# a line that merely mentions an unrelated identifier containing the
# substring (the old whole-line check's other false-negative shape).
_CLI_SUPPLIED_PATH_EXEMPT_ARGS = (CLI_SUPPLIED_PATH_TOKEN, f"{CLI_SUPPLIED_PATH_TOKEN}.c_str()")


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


def _match_paren_span(text: str, open_idx: int) -> int:
    """Returns the index one past the matching ')' for the '(' at
    `open_idx` in `text`. `text` must already be comment/string-blanked
    (`_strip_comments_and_strings`'s own output) so a paren inside a
    string literal or a comment cannot throw off the depth count. Raises
    ValueError if the parens never balance -- a construction this scan
    cannot parse is reported as a violation by the caller rather than
    silently waved through (see find_foreign_reading_violations below)."""
    assert text[open_idx] == "("
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError(f"unbalanced parentheses starting at offset {open_idx}")


def _first_top_level_argument(arg_text: str) -> str:
    """The text of a call's FIRST argument -- up to the first comma at
    paren-nesting depth 0 (a nested call's own commas, e.g.
    `f(g(a, b), c)`, do not split the first argument early), or the whole
    text when there is no such comma (a single-argument call)."""
    depth = 0
    for i, c in enumerate(arg_text):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            return arg_text[:i]
    return arg_text


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

    # getenv and socket/IPC carry no carve-out at all -- a per-line scan is
    # sufficient and stays unchanged.
    for lineno, line in enumerate(stripped_lines, start=1):
        raw_line = raw_lines[lineno - 1] if lineno - 1 < len(raw_lines) else ""
        if GETENV_PATTERN.search(line):
            violations.append(ForeignReadingViolation(path, lineno, "getenv", raw_line))
        if SOCKET_IPC_PATTERN.search(line):
            violations.append(ForeignReadingViolation(path, lineno, "socket_or_ipc", raw_line))

    # TE-89 (TE-88 review S-7): the file-open rule's own carve-out used to
    # be evaluated over the WHOLE LINE (`CLI_SUPPLIED_PATH_TOKEN not in
    # line`), which exempted a call whenever the token appeared ANYWHERE
    # on the line -- including inside an expression that builds a
    # DIFFERENT path from it (`std::ifstream sidecar(std::string(model_path)
    # + ".sidecar")` reads a different file and was wrongly exempted) and a
    # call on a line that merely mentions an unrelated identifier whose
    # name happens to contain the substring. This scans the whole
    # comment/string-blanked TEXT (a call's own argument list is not
    # bounded to one line in general, though this project's own style
    # keeps it there) and requires the call's FIRST ARGUMENT, trimmed, to
    # equal EXACTLY `model_path` or `model_path.c_str()` before exempting
    # it -- an expression that merely contains that identifier is flagged.
    for m in FILE_OPEN_PATTERN.finditer(stripped):
        open_idx = m.end() - 1
        lineno = stripped.count("\n", 0, m.start()) + 1
        raw_line = raw_lines[lineno - 1] if lineno - 1 < len(raw_lines) else ""
        try:
            close_idx = _match_paren_span(stripped, open_idx)
        except ValueError:
            # A call this scan cannot parse is reported, not exempted --
            # never waved through because the carve-out could not be
            # evaluated.
            violations.append(ForeignReadingViolation(path, lineno, "file_open", raw_line))
            continue
        first_arg = _first_top_level_argument(stripped[open_idx + 1:close_idx - 1]).strip()
        if first_arg in _CLI_SUPPLIED_PATH_EXEMPT_ARGS:
            continue
        violations.append(ForeignReadingViolation(path, lineno, "file_open", raw_line))

    violations.sort(key=lambda v: v.line)
    return violations


def _inject(text: str, anchor: str, insert: str) -> str:
    if anchor not in text:
        raise ValueError("anchor text not found")
    return text.replace(anchor, anchor + "\n" + insert, 1)


def run_construction() -> tuple[bool, str]:
    """MUST-ACCEPT against the tip's own witness_main.cpp, plus one
    MUST-REJECT construction per rule class this module declares (TE-89,
    TE-88 review S-7: the file-open and socket/IPC classes previously had
    no must-reject at all -- only getenv did, which meant only one of
    three declared classes had ever been shown able to fire), plus a
    MUST-ACCEPT regression check that the file-open carve-out's own
    positive case (a call that genuinely opens model_path itself) still
    exempts correctly now that the carve-out is argument-scoped rather
    than line-scoped. Returns (passed, message) -- passed True only if
    EVERY construction fires correctly. Shared by this module's own
    --selftest and by tests/witness_structural_matrix.py's C31(iv)/C36(e)
    legs."""
    if not WITNESS_MAIN.exists():
        return False, f"MUST-ACCEPT could not run: {WITNESS_MAIN} does not exist"

    accept_violations = find_foreign_reading_violations(WITNESS_MAIN)
    if accept_violations:
        return False, ("MUST-ACCEPT FAILED: the tip's own witness_main.cpp is flagged, which must "
                        f"never happen: {[str(v) for v in accept_violations]}")

    scratch_dir = REPO_ROOT / "build" / "_scratch" / "witness_no_foreign_reading_check"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    text = WITNESS_MAIN.read_text(encoding="utf-8")
    anchor = "  // witness_sha = SHA-256(W-A || W-B || W-Q), sec 4.4b's own formula.\n" \
             "  uint8_t witness_sha[32];"
    if anchor not in text:
        return False, (f"constructions could not be built: the anchor text used to insert each "
                        f"one is no longer present in {WITNESS_MAIN} -- update this check's own "
                        f"anchor to match the current source")

    messages: list[str] = []

    # MUST-REJECT (getenv) -- unchanged from TE-86.
    getenv_file = scratch_dir / "witness_main_mustreject_getenv.cpp"
    getenv_file.write_text(_inject(
        text, anchor,
        "  // TE-86 MUST-REJECT construction only -- never present at the tip.\n"
        "  if (const char* semb_test_override = getenv(\"SEMB_WITNESS_SHA_OVERRIDE\")) {\n"
        "    std::memcpy(witness_sha, semb_test_override, sizeof(witness_sha));\n"
        "  }",
    ), encoding="utf-8")
    getenv_hits = [v for v in find_foreign_reading_violations(getenv_file) if v.kind == "getenv"]
    if not getenv_hits:
        return False, (f"MUST-REJECT (getenv) FAILED: the scratch copy with an inserted "
                        f"getenv(\"SEMB_WITNESS_SHA_OVERRIDE\") line was NOT flagged -- the check "
                        f"cannot detect the hazard it exists to catch.")
    messages.append(f"MUST-REJECT (getenv): flagged at {getenv_hits[0]}")

    # MUST-REJECT (file_open, TE-89 S-7) -- a path DERIVED from model_path
    # but not EQUAL to it (a sidecar file): the exact shape the review
    # found the old line-scoped carve-out wrongly exempting.
    file_open_file = scratch_dir / "witness_main_mustreject_file_open.cpp"
    file_open_file.write_text(_inject(
        text, anchor,
        "  // TE-89 S-7 MUST-REJECT construction only -- never present at the tip. Opens a path\n"
        "  // DERIVED from model_path (a sidecar file), never model_path itself.\n"
        "  std::ifstream semb_test_sidecar(std::string(model_path) + \".sidecar\");",
    ), encoding="utf-8")
    file_open_hits = [v for v in find_foreign_reading_violations(file_open_file) if v.kind == "file_open"]
    if not file_open_hits:
        return False, (f"MUST-REJECT (file_open, derived path) FAILED: a scratch copy opening a "
                        f"path DERIVED from model_path (std::string(model_path) + \".sidecar\") was "
                        f"NOT flagged -- the carve-out is exempting more than the CLI-supplied path "
                        f"itself.")
    messages.append(f"MUST-REJECT (file_open, derived path): flagged at {file_open_hits[0]}")

    # MUST-REJECT (socket_or_ipc, TE-89 S-7).
    socket_file = scratch_dir / "witness_main_mustreject_socket.cpp"
    socket_file.write_text(_inject(
        text, anchor,
        "  // TE-89 S-7 MUST-REJECT construction only -- never present at the tip.\n"
        "  int semb_test_sock = socket(2, 1, 0);\n"
        "  (void)semb_test_sock;",
    ), encoding="utf-8")
    socket_hits = [v for v in find_foreign_reading_violations(socket_file) if v.kind == "socket_or_ipc"]
    if not socket_hits:
        return False, (f"MUST-REJECT (socket_or_ipc) FAILED: a scratch copy calling "
                        f"socket(2, 1, 0) was NOT flagged -- the check cannot detect the hazard it "
                        f"exists to catch.")
    messages.append(f"MUST-REJECT (socket_or_ipc): flagged at {socket_hits[0]}")

    # MUST-ACCEPT regression (TE-89 S-7): a call whose argument genuinely
    # IS model_path (not merely mentions it) must still be exempted --
    # confirms the argument-scoped carve-out did not become "never exempt
    # anything."
    carveout_file = scratch_dir / "witness_main_mustaccept_carveout.cpp"
    carveout_file.write_text(_inject(
        text, anchor,
        "  // TE-89 S-7 MUST-ACCEPT construction only -- never present at the tip. Opens\n"
        "  // model_path ITSELF -- sec 4.4d item 3's own carve-out -- must NOT be flagged.\n"
        "  std::ifstream semb_test_model_open(model_path.c_str());",
    ), encoding="utf-8")
    carveout_hits = [v for v in find_foreign_reading_violations(carveout_file) if v.kind == "file_open"]
    if carveout_hits:
        return False, (f"MUST-ACCEPT (carve-out) FAILED: a scratch copy opening "
                        f"model_path.c_str() ITSELF was flagged -- the carve-out no longer exempts "
                        f"the one case sec 4.4d item 3 says it should: {[str(v) for v in carveout_hits]}")
    messages.append("MUST-ACCEPT (carve-out): model_path.c_str() open correctly NOT flagged")

    return True, (f"MUST-ACCEPT: {WITNESS_MAIN} -- 0 violations. " + "; ".join(messages))


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
