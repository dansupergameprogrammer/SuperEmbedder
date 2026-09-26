"""Slice 6's executable `semb` CLI contract (C24, C18, C5, and TE-232's C9
re-encode, stdin session, plain-text corpus, and `--raw` cells).

CLI choices where the plan deliberately leaves syntax/output open:
  * model selection is verb-local `--model <sslm> --tokenizer <sslm>`;
  * `query --hex` writes exactly one `VECTOR_HEX=<lowercase hex>` line;
  * `query --stdin --hex` reads one UTF-8 query per line and writes one such
    line per query, while stderr reports `query_handle_opens=1` once;
  * `query --top 5` writes one JSON object per input with five `hits`;
  * `semb verify <name> --corpus <path> --model <sslm> --tokenizer <sslm>`
    re-encodes the corpus and compares row digests (plan sec 3.1 / C9); the
    `--corpus` argument is required, not optional (D-SLM6630);
  * a corpus whose digest disagrees with the manifest's `corpus_digest` is
    refused as `semb verify: SEMB_CORPUS_DIGEST_MISMATCH (35)` with exit 1
    -- the status appended to the frozen `semb_status` enum at ordinal 35
    (D-SLM6663; U1 Slice 7 step 1, TE-264);
  * a plain-text corpus is one document per line with ids = line numbers;
    the numbering base the plan leaves open is pinned to ZERO, the smallest
    reading (D-SLM6632): the first line's id is "0", as a decimal string;
  * `query --stdin` is a session: one line's result must arrive before the
    next line is written, not after standard input closes;
  * `query --raw` writes exactly `dims * 4` float32 bytes, unpadded;
  * the query parser's option/data boundary (D-SLM6637, TE-235 for TE-233's
    S-1): `--` ends option parsing and every argument after it is data, so
    option-shaped query text is passed after the boundary
    (`query <name> --model <m> --tokenizer <t> -- --help` emits the vector for
    the text `--help`); before the boundary an argument matching a known
    option spelling is control syntax, never query text, and one-shot query
    text that spells an option without a boundary is refused by name --
    exit 0 without a vector is the silent-success shape the review executed
    at 6991a85;
  * `query --top` ranks against the bank the checked handle validated; the
    CLI driver reads no `.wvbank.json`/`.wvbank.bin` itself (plan sec 3.1's
    checked path; TE-233's S-2);
  * `query --help` names every implemented output mode, `--raw` included,
    and every conflicting mode combination is refused (TE-233's M-1) -- a
    refusal is the exact status AND the exact `where` context
    (`named_refusal`, tightened TE-237 for TE-236's M-3), never a bare
    nonzero exit;
  * the corpus format rule selects JSONL for a `.jsonl` extension without
    regard to case (D-SLM6638, TE-235): a corpus named `.JSONL` bakes with
    the ids its rows carry, never as plain text with line-number ids;
  * `semb bake` skips a document only when empty text (utf8_len == 0) is
    its ONLY defect -- its id must independently pass the library's own
    id checks (non-empty, no NUL byte, valid UTF-8); an empty-text
    document with a malformed id is refused by the library for that
    defect, never skipped (D-SLM7405, TE-317; corrected TE-320 S-2). A
    skipped id colliding with a kept or another skipped id refuses
    SEMB_DOCUMENT_ID_DUPLICATE, UNLESS some other kept document would
    itself fail the library's own per-document checks (a bad id or
    invalid UTF-8 text) AT ANY POSITION -- before or after the colliding
    twin, since the library validates every document before it checks
    uniqueness -- in which case the real call runs and the library
    reports that document's own defect instead. This applies identically
    at both `bake` and `verify`'s own call sites (TE-320 M-2; corrected
    TE-317 round 3 N-4, corrected wording TE-326 M-4). Skips are reported
    one line per id on stderr, the id escaped beyond JSON's own minimum
    (also DEL, the C1 range U+0080-U+009F, and U+2028/U+2029, all as a
    backslash-u escape) so no line-splitting consumer (including Python's own
    `str.splitlines()`, which this very file uses) can split one skip
    into two, and no raw control byte reaches the terminal (`skipped
    "<id>": SEMB_INPUT_EMPTY`, plan `te267-u2-release-plan.md` U2-8's own
    shape; TE-320 S-4, corrected TE-317 round 3 N-3, extended TE-326 R-1
    -- this wider escaping is local to stderr; the sidecar and every
    manifest keep exactly the bytes the shared JSON writer produces), and
    recorded in a `<stem>.skipped.json` sidecar (a JSON array of `{"id",
    "reason"}`) written atomically on EVERY successful bake (temp file,
    closed and checked AFTER close -- not merely after the write -- then
    renamed into place, so a flush failure at close cannot report success
    or replace a good prior sidecar; and on either failure branch, any
    PRIOR sidecar at the final path is also removed best-effort, unless
    that path is a directory, which stays untouched -- TE-320 S-1, S-4,
    M-1, M-3, hardened TE-317 round 3 N-2, extended TE-326 M-5); a
    non-empty corpus left with nothing to bake after skipping still
    refuses SEMB_INPUT_EMPTY. `semb verify` skips identically on its
    re-encode and reports the same way, but its corpus-identity verdict
    comes ONLY from the existing row/corpus digest comparison -- it does
    not read the sidecar at all, which is informational only (conductor
    direction D-SLM7433, TE-317 round 3, revising TE-320's own S-3 remedy
    after TE-324 found it made verify's verdict depend on a file outside
    the bank that nothing binds to it). Every other per-document refusal
    (invalid UTF-8 text, empty/invalid id, duplicate id among non-empty
    documents) and the library's own all-or-nothing batch refusal are
    unchanged.
These are the smallest machine-readable forms that let this test compare the
CLI to the C ABI without parsing presentation text.  The planner owns their
ratification; this file pins the test-author choice until then.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The cap-512 pair mint alone takes ~390-410 s on an idle 4-core box, so a
# 480 s bound on it timed out under `ctest -j`, where it competes for the
# same cores. 1,800 s leaves ~4x headroom; the ctest TIMEOUT on this test
# (tests/CMakeLists.txt) is set above this plus the rest of the run.
MINT_TIMEOUT_S = 1800
STATUSES = {
    "fingerprint": "SEMB_FINGERPRINT_MISMATCH",
    "schema": "SEMB_MANIFEST_SCHEMA_UNSUPPORTED",
    "size": "SEMB_BANK_SIZE_MISMATCH",
    "artifact": "SEMB_ARTIFACT_SHA_MISMATCH",
}


def find(build: Path, name: str) -> Path | None:
    candidates = [build / f"{name}.exe", build / name, build / "tests" / f"{name}.exe", build / "tests" / name]
    return next((p for p in candidates if p.exists()), next(iter(build.rglob(f"{name}.exe")), None))


class Report:
    def __init__(self) -> None: self.failed = False
    def add(self, state: str, cell: str, detail: str) -> None:
        print(f"[{state}] {cell}: {detail}")
        # SKIPPED (TE-326 T-4(c)) is distinct from BLOCKED: it names a cell
        # this platform cannot produce the precondition for (no POSIX
        # /dev/full on Windows), not a missing apparatus or a real defect --
        # it does not fail the run. BLOCKED keeps its existing meaning
        # (a real precondition failed) and keeps failing the run.
        self.failed |= state in {"FAIL", "RED-UNIMPLEMENTED", "BLOCKED"}


def call(args: list[str], stdin: str | None = None, timeout: int = 420) -> subprocess.CompletedProcess[str]:
    # Standard input goes as UTF-8 bytes: a text-mode pipe writes each "\n" as CRLF on Windows, and the CLI reads a
    # CR before the LF as text (README: "a CR before the LF is text"). Output is decoded as text mode would, CRLF
    # read as LF.
    proc = subprocess.run(args, cwd=ROOT, input=None if stdin is None else stdin.encode("utf-8"),
                          capture_output=True, timeout=timeout)
    decode = lambda b: b.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(proc.args, proc.returncode, decode(proc.stdout), decode(proc.stderr))


def call_bytes(args: list[str], timeout: int = 420) -> subprocess.CompletedProcess[bytes]:
    """Runs one command with stdout captured as raw bytes (for `--raw`)."""
    return subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout)


def stdin_session(semb: Path, stem: Path, base: list[str], text: str,
                  bound_s: float) -> tuple[str | None, list[str], int | None]:
    """Drives `query --stdin` as a live session (plan sec 3.1: ONE query
    handle serving many queries).  Writes one query line, keeps standard
    input open, and waits up to ``bound_s`` for that line's result; only then
    is the second line written and input closed.  Returns the first result
    line (None if it did not arrive within the bound), every line emitted
    after input closed, and the exit code.  A correct session has already
    emitted the first result before the close, so exactly one result remains
    after it; a batch-read CLI emits both only after the close."""
    proc = subprocess.Popen([str(semb), "query", "--stdin", str(stem), "--hex", *base],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=ROOT)
    emitted: "queue.Queue[bytes | None]" = queue.Queue()

    def read_lines() -> None:
        for raw in proc.stdout:
            emitted.put(raw)
        emitted.put(None)

    threading.Thread(target=read_lines, daemon=True).start()
    try:
        proc.stdin.write((text + "\n").encode("utf-8"))
        proc.stdin.flush()
        try:
            first: str | None = emitted.get(timeout=bound_s).decode("utf-8", "replace").strip()
        except queue.Empty:
            first = None
        proc.stdin.write((text + "\n").encode("utf-8"))
        proc.stdin.flush()
        proc.stdin.close()
        after_close: list[str] = []
        while True:
            try:
                raw = emitted.get(timeout=bound_s)
            except queue.Empty:
                break
            if raw is None:
                break
            after_close.append(raw.decode("utf-8", "replace").strip())
        code: int | None = proc.wait(timeout=120)
        return first, after_close, code
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def probe_vector_hex(probe: Path, model: str, tokenizer: str, stem: Path,
                     text: str) -> tuple[str | None, subprocess.CompletedProcess[str]]:
    """The library's own one-shot query bytes for ``text`` through the frozen
    C ABI probe -- the oracle the option-shaped-text cells compare against."""
    run = call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(stem), "--text", text])
    match = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", run.stdout, re.M) if run.returncode == 0 else None
    return (match.group(1) if match else None), run


def stdin_top_session(semb: Path, stem: Path, base: list[str], text: str, bound_s: float,
                      replace_with: Path | None) -> tuple[str | None, str | None, int | None]:
    """Drives ``query --stdin --top 5`` as a live session and, between the
    two queries, overwrites the session bank's pair files on disk with
    another bank's (TE-233 S-2's staged replacement, which the open-to-reread
    window cannot receive from outside the process).  Returns the first and
    second answer lines (None if the bound passed without an answer) and the
    exit code; standard input is held open until the second answer is
    requested, so a batch-read CLI reports no first answer."""
    proc = subprocess.Popen([str(semb), "query", "--stdin", str(stem), "--top", "5", *base],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=ROOT)
    emitted: "queue.Queue[bytes | None]" = queue.Queue()

    def read_lines() -> None:
        for raw in proc.stdout:
            emitted.put(raw)
        emitted.put(None)

    threading.Thread(target=read_lines, daemon=True).start()
    try:
        def answer() -> str | None:
            try:
                return emitted.get(timeout=bound_s).decode("utf-8", "replace").strip()
            except queue.Empty:
                return None

        proc.stdin.write((text + "\n").encode("utf-8"))
        proc.stdin.flush()
        first = answer()
        if replace_with is not None:
            for suffix in (".wvbank.json", ".wvbank.bin"):
                shutil.copyfile(Path(str(replace_with) + suffix), Path(str(stem) + suffix))
        proc.stdin.write((text + "\n").encode("utf-8"))
        proc.stdin.flush()
        proc.stdin.close()
        second = answer()
        while True:  # drain any trailing output before waiting on the exit code
            try:
                raw = emitted.get(timeout=bound_s)
            except queue.Empty:
                break
            if raw is None:
                break
        code: int | None = proc.wait(timeout=120)
        return first, second, code
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def pair_read_lines(source: str) -> list[str]:
    """TE-233 S-2's structural half: every line of the CLI driver that names a
    bank pair file by its literal extension.  ``semb_bank_open`` is the only
    permitted reader of the ``.wvbank.json``/``.wvbank.bin`` pair; a
    driver-side second copy beside the checked open is exactly the
    unvalidated re-read the review found."""
    flagged = []
    for number, line in enumerate(source.splitlines(), 1):
        if '".wvbank.json"' in line or '".wvbank.bin"' in line:
            flagged.append(f"line {number}: {line.strip()}")
    return flagged


def expect_status(report: Report, cell: str, proc: subprocess.CompletedProcess[str], status: str) -> None:
    text = proc.stdout + proc.stderr
    report.add("PASS" if proc.returncode != 0 and status in text else "FAIL", cell,
               f"exit={proc.returncode}; expected {status}; stderr={proc.stderr[-400:]!r}")


def named_refusal(proc: subprocess.CompletedProcess[str], context: str,
                  status: str = "SEMB_NULL_ARGUMENT") -> bool:
    """The suite's tightened refusal pin (TE-237, TE-236's M-3): a refusal is
    the exact status AND the exact ``where`` context src/main.cpp's Refuse
    prints (``<where>: <status> (<ordinal>)`` on stderr) -- never a bare
    nonzero exit.  An unnamed crash or an unrelated refusal (a different
    context, or a different status under the right context) must not pass,
    which the old ``returncode != 0 and "SEMB_" in output`` shape let
    through.  Anchored (TE-238's M-3, D-SLM6644): exit 1 and ONE stderr line
    that is exactly ``<context>: <status> (<ordinal>)`` -- the context and
    status as unrelated substrings, split across lines or streams, do not
    pass.  A module-level function (not an inline expression) so the
    mutation harness can import and exercise it against constructed
    outputs."""
    line = re.compile(r"^" + re.escape(context) + r": " + re.escape(status) + r" \(\d+\)\r?$", re.M)
    return proc.returncode == 1 and line.search(proc.stderr) is not None


# TE-264 (U1 Slice 7 step 1): `semb verify`'s corpus-digest refusal in the
# pinned `<context>: <status> (<ordinal>)` form, SEMB_CORPUS_DIGEST_MISMATCH
# appended at enum ordinal 35 (`Claude/Plans/te140-u1-remainder-sequencing.md`
# sec 4.7 step 1; D-SLM6663).
CORPUS_DIGEST_REFUSAL_LINE = "semb verify: SEMB_CORPUS_DIGEST_MISMATCH (35)"


def verify_corpus_digest_refusal(proc: subprocess.CompletedProcess[str]) -> bool:
    """Exit 1 and one stderr line that is exactly CORPUS_DIGEST_REFUSAL_LINE.
    The line without an ordinal, or with any other ordinal, does not pass."""
    lines = [line.rstrip("\r") for line in proc.stderr.splitlines()]
    return proc.returncode == 1 and lines.count(CORPUS_DIGEST_REFUSAL_LINE) == 1


def copied_stem(source: Path, destination: Path) -> None:
    for suffix in (".wvbank.json", ".wvbank.bin", ".semb.json"):
        shutil.copyfile(Path(str(source) + suffix), Path(str(destination) + suffix))


def mutate(stem: Path, kind: str) -> None:
    if kind == "size":
        with Path(str(stem) + ".wvbank.bin").open("ab") as f: f.write(b"\0")
        return
    manifest = Path(str(stem) + ".semb.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if kind == "fingerprint": data["encoder_fingerprint"] = "00" * 32
    elif kind == "schema":
        bank = Path(str(stem) + ".wvbank.json")
        header = json.loads(bank.read_text(encoding="utf-8")); header["schemaVersion"] = 999
        bank.write_text(json.dumps(header), encoding="utf-8")
        return
    elif kind == "artifact": data.setdefault("provenance", {})["artifact_sha"] = "00" * 32
    manifest.write_text(json.dumps(data), encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--cmake-executable", required=True)
    args = ap.parse_args(argv)
    report = Report(); scratch = args.build_dir / "_scratch" / "te230_cli"
    shutil.rmtree(scratch, ignore_errors=True); scratch.mkdir(parents=True)
    try:
        pair = ROOT / "build" / "_scratch" / "te222_c17_pair"
        model_path, tokenizer_path = pair / "u1_pair_model.sslm", pair / "u1_pair_tokenizer.sslm"
        if not model_path.exists() or not tokenizer_path.exists():
            fixture = ROOT / "tests" / "fixtures" / "wq" / "regenerate_c17_highcap_pair_fixture.py"
            generated = call([sys.executable, str(fixture), "--lock", "superslm.lock", "--out-dir", str(pair)],
                             timeout=MINT_TIMEOUT_S)
            if generated.returncode:
                raise RuntimeError((generated.stdout + generated.stderr)[-3000:])
        model, tokenizer = str(pair / "u1_pair_model.sslm"), str(pair / "u1_pair_tokenizer.sslm")
        report.add("PASS", "cap-512 synthetic tokenizer-pair fixture", str(pair))
    except Exception as exc:
        model = tokenizer = ""
        report.add("FAIL", "synthetic tokenizer-pair fixture", f"{type(exc).__name__}: {exc}")
    built = call([args.cmake_executable, "--build", str(args.build_dir), "--target", "semb", "te230_semb_cli_probe"], timeout=420)
    if built.returncode:
        report.add("FAIL", "CLI apparatus", (built.stdout + built.stderr)[-1000:])
    semb, probe = find(args.build_dir, "semb"), find(args.build_dir, "te230_semb_cli_probe")
    if not semb or not probe:
        report.add("FAIL", "CLI apparatus", "semb or te230_semb_cli_probe was not produced")
        return 1
    help_run = call([str(semb), "query", "--help"])
    report.add("PASS" if help_run.returncode == 0 and "diagnostic" in (help_run.stdout + help_run.stderr).lower() else "FAIL",
               "CLI one-shot diagnostic help", "query --help must name one-shot query a diagnostic")
    # TE-235 (TE-233 M-1): the help names every implemented output mode.
    missing_modes = [mode for mode in ("--stdin", "--hex", "--top", "--raw")
                     if mode not in (help_run.stdout + help_run.stderr)]
    report.add("PASS" if not missing_modes else "FAIL",
               "M-1 query --help names every implemented output mode",
               "help names --stdin, --hex, --top, and --raw" if not missing_modes else
               f"RED: query --help omits {', '.join(missing_modes)}; the usage line presents the modes as "
               "exclusive, so every implemented mode must be named for a consumer to discover it")
    # TE-235 (TE-233 S-2), structural half: the CLI driver reads no bank pair
    # file itself -- semb_bank_open is the only permitted reader of the pair.
    # The scan is first proven able to fire on a synthetic driver text that
    # does read the pair, so a clean result means the scan worked, not that
    # it is dead.  What this check misses, stated plainly: a driver that
    # re-reads through a second semb_bank_open, extension strings assembled
    # dynamically, or reads moved to another translation unit -- none of
    # them appear as literals in src/main.cpp; the behavioral session cell
    # is the other half.
    synthetic_reads = pair_read_lines(
        'bool Load(const std::string& stem) { return ReadFile(stem + ".wvbank.bin", &payload); }')
    driver_reads = pair_read_lines((ROOT / "src" / "main.cpp").read_text(encoding="utf-8", errors="replace"))
    if synthetic_reads:
        report.add("PASS" if not driver_reads else "FAIL",
                   "S-2a the query driver reads no bank pair file itself",
                   "src/main.cpp names no .wvbank.json/.wvbank.bin; every pair read is semb_bank_open's" if not driver_reads else
                   "RED: the CLI driver reads the bank pair itself beside the checked open -- " + "; ".join(driver_reads))
    else:
        report.add("FAIL", "S-2a the query driver reads no bank pair file itself",
                   "the structural scan is dead: a synthetic driver text that reads .wvbank.bin was not flagged")
    corpus = ROOT / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl"; good = scratch / "good"
    base = ["--model", model, "--tokenizer", tokenizer]
    bake = call([str(semb), "bake", str(corpus), "--out", str(good), *base])
    if bake.returncode != 0:
        report.add("RED-UNIMPLEMENTED" if "semb " in bake.stdout else "FAIL", "CLI bake baseline",
                   f"exit={bake.returncode}; {bake.stderr[-500:]!r}")
    files_ok = all(Path(str(good) + s).is_file() for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
    report.add("PASS" if files_ok else "FAIL", "CLI bake triple",
               "writes exactly the bank pair plus manifest" if files_ok else
               "RED-UNIMPLEMENTED: the stub returned success without writing the required triple")
    text = "A concise query for the CLI contract."
    library_good = scratch / "library_good"
    library_bake = call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(library_good),
                         "--bake-corpus", str(corpus)])
    library_ok = library_bake.returncode == 0 and all(Path(str(library_good) + s).is_file()
                                                       for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
    report.add("PASS" if library_ok else "FAIL", "library bake baseline",
               (library_bake.stdout + library_bake.stderr)[-400:])
    lib = call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(library_good), "--text", text]) if library_ok else None
    lib_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", lib.stdout, re.M) if lib else None
    report.add("PASS" if lib and lib.returncode == 0 and lib_hex else "FAIL", "library bank opens through semb_bank_open",
               lib.stderr[-400:] if lib else "library bake did not produce a triple")
    if files_ok and lib_hex:
        one = call([str(semb), "query", str(good), text, "--hex", *base])
        one_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", one.stdout, re.M)
        report.add("PASS" if one.returncode == 0 and one_hex and one_hex.group(1) == lib_hex.group(1) else "FAIL",
                   "CLI one-shot bytes equal library", "one-shot query is the documented diagnostic")
        lines = [text, "A second query proves session reuse."]
        session = call([str(semb), "query", "--stdin", str(good), "--hex", *base], stdin="\n".join(lines) + "\n")
        session_hex = re.findall(r"^VECTOR_HEX=([0-9a-f]+)$", session.stdout, re.M)
        report.add("PASS" if session.returncode == 0 and len(session_hex) == len(lines) and session_hex[0] == lib_hex.group(1) and "query_handle_opens=1" in session.stderr else "FAIL",
                   "CLI stdin one handle", "observable=query_handle_opens=1; each stdin vector is library-equal")
        # TE-232 cell 2: --stdin is a session, not a batch read.  The first
        # line's result must arrive while standard input is still open and
        # before the second line is written.
        first, after_close, session_code = stdin_session(semb, good, base, text, 20.0)
        first_hex = re.fullmatch(r"VECTOR_HEX=([0-9a-f]+)", first) if first else None
        report.add("PASS" if first_hex and first_hex.group(1) == lib_hex.group(1) else "FAIL",
                   "CLI stdin session serves the first query before input closes",
                   "first result is library-equal and arrived within 20s while input stayed open" if first_hex else
                   "RED: no result arrived within the 20s bound while standard input stayed open -- "
                   "the CLI reads all of standard input before encoding anything")
        second_hex = re.fullmatch(r"VECTOR_HEX=([0-9a-f]+)", after_close[0]) if len(after_close) == 1 else None
        report.add("PASS" if second_hex and second_hex.group(1) == lib_hex.group(1) and session_code == 0 else "FAIL",
                   "CLI stdin session serves the second query after input closes",
                   "exactly one library-equal result remained after the close, exit 0" if second_hex else
                   f"RED: {len(after_close)} results arrived only after input closed "
                   f"(expected exactly 1, already served before the close), exit={session_code}")
        # TE-232 cell 4: query --raw writes exactly dims * 4 float32 bytes,
        # unpadded, equal to the library's bytes for the same text.
        raw = call_bytes([str(semb), "query", str(good), text, "--raw", *base])
        dims = json.loads(Path(str(good) + ".semb.json").read_text(encoding="utf-8")).get("dims")
        library_bytes = bytes.fromhex(lib_hex.group(1))
        raw_ok = (raw.returncode == 0 and isinstance(dims, int) and raw.stdout == library_bytes
                  and len(library_bytes) == dims * 4)
        report.add("PASS" if raw_ok else "FAIL", "CLI query --raw writes the vector bytes",
                   f"exactly dims*4={dims * 4 if isinstance(dims, int) else '?'} bytes, library-equal" if raw_ok else
                   f"RED: --raw is not a CLI option; exit={raw.returncode}, stdout={len(raw.stdout)} bytes, "
                   f"expected exactly {dims * 4 if isinstance(dims, int) else 'dims*4'} bytes equal to the library's")
        # TE-235 (TE-233 S-1), D-SLM6637: the end-of-options boundary `--`
        # makes option-shaped text queryable -- the CLI must emit the
        # library's own bytes for the text `--help`.
        help_boundary = call([str(semb), "query", str(good), *base, "--", "--help"])
        help_boundary_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", help_boundary.stdout, re.M)
        help_oracle, help_oracle_run = probe_vector_hex(probe, model, tokenizer, library_good, "--help")
        help_ok = (help_oracle is not None and help_boundary.returncode == 0
                   and help_boundary_hex is not None and help_boundary_hex.group(1) == help_oracle)
        report.add("PASS" if help_ok else "FAIL",
                   "S-1 the boundary `--` makes option-shaped text queryable (--help)",
                   "the CLI emits the library's own bytes for the text `--help`" if help_ok else
                   f"RED: exit={help_boundary.returncode}, vector={'yes' if help_boundary_hex else 'no'}, "
                   f"library oracle={'yes' if help_oracle else f'no: {help_oracle_run.stderr[-120:]!r}'}; the parser "
                   "scans the whole argument vector for option spellings and has no end-of-options boundary, so "
                   f"`--help` anywhere prints usage and exits -- output: {(help_boundary.stdout + help_boundary.stderr)[:120]!r}")
        # The same boundary for a second option spelling: `--stdin` is the
        # flag that turns one-shot query into a session, so without a
        # boundary it can never be one-shot query text.
        stdin_boundary = call([str(semb), "query", str(good), *base, "--", "--stdin"])
        stdin_boundary_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", stdin_boundary.stdout, re.M)
        stdin_oracle, stdin_oracle_run = probe_vector_hex(probe, model, tokenizer, library_good, "--stdin")
        stdin_ok = (stdin_oracle is not None and stdin_boundary.returncode == 0
                    and stdin_boundary_hex is not None and stdin_boundary_hex.group(1) == stdin_oracle)
        report.add("PASS" if stdin_ok else "FAIL",
                   "S-1 the boundary `--` makes option-shaped text queryable (--stdin)",
                   "the CLI emits the library's own bytes for the text `--stdin`" if stdin_ok else
                   f"RED: exit={stdin_boundary.returncode}, vector={'yes' if stdin_boundary_hex else 'no'}, "
                   f"library oracle={'yes' if stdin_oracle else f'no: {stdin_oracle_run.stderr[-120:]!r}'}; `--stdin` "
                   "is scanned as a flag from anywhere and `--` is collected as a positional, so the command is "
                   "read as a malformed session instead of a one-shot query for the text `--stdin` -- output: "
                   f"{(stdin_boundary.stdout + stdin_boundary.stderr)[:120]!r}")
        # The review's exact command (TE-233 S-1, executed on this binary by
        # the reviewer): option-shaped text with NO boundary must refuse by
        # name -- TE-237 (TE-236's M-3) pins the exact refusal D-SLM6637
        # names: the context `semb query --help` and the status
        # SEMB_NULL_ARGUMENT, never any nonzero exit (an unnamed crash or an
        # unrelated refusal passed the old `not exit-0-vectorless` shape).
        silent = call([str(semb), "query", str(good), "--help", *base])
        silent_ok = named_refusal(silent, "semb query --help")
        report.add("PASS" if silent_ok else "FAIL",
                   "S-1 option-shaped text without a boundary refuses as `semb query --help: SEMB_NULL_ARGUMENT`",
                   "exit 1 with the exact D-SLM6637 refusal context" if silent_ok else
                   f"RED: exit={silent.returncode}; output={(silent.stdout + silent.stderr)[:160]!r}; the "
                   "boundary-less option shape must refuse naming `semb query --help` and SEMB_NULL_ARGUMENT, "
                   "not exit 0 vectorless (the silent-success shape the review executed at 6991a85) and not any "
                   "unnamed nonzero exit")
    else:
        report.add("BLOCKED", "CLI one-shot bytes equal library", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin one handle", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin session serves the first query before input closes", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin session serves the second query after input closes", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI query --raw writes the vector bytes", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "S-1 the boundary `--` makes option-shaped text queryable (--help)", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "S-1 the boundary `--` makes option-shaped text queryable (--stdin)", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "S-1 option-shaped text without a boundary refuses as `semb query --help: SEMB_NULL_ARGUMENT`", "CLI baseline triple and library vector are required")
    # C24: output directory begins empty; no final, partial, or temporary file survives refusal.
    empty = scratch / "empty.jsonl"; empty.write_text("", encoding="utf-8"); empty_stem = scratch / "empty" / "out"; empty_stem.parent.mkdir()
    c24 = call([str(semb), "bake", str(empty), "--out", str(empty_stem), *base])
    leftovers = list(empty_stem.parent.iterdir())
    report.add("PASS" if c24.returncode != 0 and "SEMB_CORPUS_EMPTY" in c24.stderr and not leftovers else "FAIL",
               "C24 empty corpus", f"exit={c24.returncode}; leftovers={[p.name for p in leftovers]}")
    for kind, status in STATUSES.items():
        if library_ok:
            stem = scratch / f"library_c18_{kind}"; copied_stem(library_good, stem); mutate(stem, kind)
            expect_status(report, f"C18/{kind}/library", call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(stem), "--text", text]), status)
        else:
            report.add("BLOCKED", f"C18/{kind}/library", "cap-512 fixture library bake did not produce a triple")
        if files_ok:
            cli_stem = scratch / f"cli_c18_{kind}"; copied_stem(good, cli_stem); mutate(cli_stem, kind)
            expect_status(report, f"C18/{kind}/query", call([str(semb), "query", str(cli_stem), text, "--hex", *base]), status)
            expect_status(report, f"C18/{kind}/verify", call([str(semb), "verify", str(cli_stem), "--corpus", str(corpus), *base]), status)
        else:
            report.add("BLOCKED", f"C18/{kind}/query", "CLI baseline triple was not produced")
            report.add("BLOCKED", f"C18/{kind}/verify", "CLI baseline triple was not produced")
    if files_ok:
        # TE-232 cell 1: `semb verify <name> --corpus <path> --model --tokenizer`
        # re-encodes the corpus and compares row digests (plan sec 3.1, C9).
        # The bank holds ids and vectors, never text, so the re-encode needs
        # the corpus; `--corpus` is required (D-SLM6630).
        accepted = call([str(semb), "verify", str(good), "--corpus", str(corpus), *base])
        report.add("PASS" if accepted.returncode == 0 else "FAIL", "verify untouched bank accepts",
                   "the untouched bank with its own corpus exits 0" if accepted.returncode == 0 else
                   f"RED: verify with --corpus is refused before any re-encode: exit={accepted.returncode}; "
                   f"{(accepted.stdout + accepted.stderr)[-200:]!r}")
        no_corpus = call([str(semb), "verify", str(good), *base])
        report.add("PASS" if no_corpus.returncode != 0 and "SEMB_" in (no_corpus.stdout + no_corpus.stderr) else "FAIL",
                   "verify without --corpus is refused by name",
                   "verify without --corpus is a named refusal" if no_corpus.returncode != 0 else
                   f"RED: verify without --corpus exited {no_corpus.returncode}; the re-encode corpus is "
                   "required, so the missing argument must be refused")
        edited = scratch / "edited_corpus.jsonl"
        rows = corpus.read_text(encoding="utf-8").splitlines()
        last = json.loads(rows[-1]); last["text"] += " -- edited by the digest cell"
        edited.write_text("\n".join(rows[:-1] + [json.dumps(last)]) + "\n", encoding="utf-8")
        mismatch = call([str(semb), "verify", str(good), "--corpus", str(edited), *base])
        # TE-264 (U1 Slice 7 step 1; D-SLM6663): the refusal carries the
        # pinned `<context>: <status> (<ordinal>)` form every other refusal
        # line carries, with SEMB_CORPUS_DIGEST_MISMATCH at enum ordinal 35,
        # and the pinned refusal exit (1).  The expected line is typed here
        # from the plan, not read from the product's enum.
        mismatch_ok = verify_corpus_digest_refusal(mismatch)
        report.add("PASS" if mismatch_ok else "FAIL", "verify edited corpus is refused by the corpus digest",
                   "a corpus that is not the one baked is refused with the exact line "
                   f"{CORPUS_DIGEST_REFUSAL_LINE!r} and exit 1" if mismatch_ok else
                   f"RED: the edited corpus must be refused with exactly one stderr line "
                   f"{CORPUS_DIGEST_REFUSAL_LINE!r} and exit 1; exit={mismatch.returncode}; "
                   f"'semb verify' stderr lines={[l for l in mismatch.stderr.splitlines() if l.startswith('semb verify')]!r}")
        # A bank consistent on disk but not what this encoder emits: flip a
        # payload byte and rewrite the manifest row_digest to SHA-256 of the
        # new payload.  semb_bank_open recomputes exactly that digest
        # (src/superembedder/bank.cpp, row_digest check), so it accepts; only
        # a re-encode can see the tamper -- which is what C9 is for.
        reencode = scratch / "c9_reencode"; copied_stem(good, reencode)
        payload = Path(str(reencode) + ".wvbank.bin"); data = bytearray(payload.read_bytes()); data[len(data) // 2] ^= 1; payload.write_bytes(data)
        manifest = Path(str(reencode) + ".semb.json")
        reencoded_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        reencoded_manifest["row_digest"] = hashlib.sha256(payload.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(reencoded_manifest), encoding="utf-8")
        opened = call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(reencode), "--text", text])
        bank_ok = opened.returncode == 0 and "VECTOR_HEX=" in opened.stdout
        report.add("PASS" if bank_ok else "FAIL", "C9 re-encode precondition: semb_bank_open accepts the tampered bank",
                   "the rewritten row_digest makes the flipped payload self-consistent on disk" if bank_ok else
                   f"the tampered bank was refused at open: exit={opened.returncode}; {(opened.stdout + opened.stderr)[-300:]!r}")
        re_verified = call([str(semb), "verify", str(reencode), "--corpus", str(corpus), *base])
        reencode_ok = re_verified.returncode != 0 and "SEMB_BANK_DIGEST_MISMATCH" in (re_verified.stdout + re_verified.stderr)
        report.add("PASS" if reencode_ok else "FAIL", "C9 re-encode refusal: verify catches a bank bank-open accepts",
                   "only a re-encode can see this tamper: refused as SEMB_BANK_DIGEST_MISMATCH" if reencode_ok else
                   f"RED: the self-consistent tampered bank must be refused by the re-encode as "
                   f"SEMB_BANK_DIGEST_MISMATCH; exit={re_verified.returncode}; "
                   f"{(re_verified.stdout + re_verified.stderr)[-200:]!r}")
        digest_stem = scratch / "same_size_digest"; copied_stem(good, digest_stem)
        payload = Path(str(digest_stem) + ".wvbank.bin"); data = bytearray(payload.read_bytes()); data[len(data) // 2] ^= 1; payload.write_bytes(data)
        expect_status(report, "verify same-size payload digest", call([str(semb), "verify", str(digest_stem), "--corpus", str(corpus), *base]), "SEMB_BANK_DIGEST_MISMATCH")
        # TE-232 cell 3: a plain-text corpus is one document per line, ids =
        # line numbers, base ZERO (D-SLM6632): the first line's id is "0".
        plain_lines = [json.loads(line)["text"] for line in corpus.read_text(encoding="utf-8").splitlines()]
        plain = scratch / "plain_corpus.txt"
        plain.write_text("\n".join(plain_lines) + "\n", encoding="utf-8", newline="\n")  # LF on every platform
        equivalent = scratch / "plain_equivalent.jsonl"
        equivalent.write_text("\n".join(json.dumps({"id": str(i), "text": line})
                                         for i, line in enumerate(plain_lines)) + "\n", encoding="utf-8")
        plain_bake = call([str(semb), "bake", str(plain), "--out", str(scratch / "plain_bank"), *base])
        equivalent_bake = call([str(semb), "bake", str(equivalent), "--out", str(scratch / "plain_jsonl_bank"), *base])
        plain_ok = plain_bake.returncode == 0 and equivalent_bake.returncode == 0
        if plain_ok:
            header = json.loads(Path(str(scratch / "plain_bank") + ".wvbank.json").read_text(encoding="utf-8"))
            expected_ids = [str(i) for i in range(len(plain_lines))]
            ids_ok = header.get("ids") == expected_ids
            vectors_ok = (Path(str(scratch / "plain_bank") + ".wvbank.bin").read_bytes()
                          == Path(str(scratch / "plain_jsonl_bank") + ".wvbank.bin").read_bytes())
        else:
            ids_ok = vectors_ok = False
        report.add("PASS" if ids_ok else "FAIL", "plain-text corpus bakes with line-number ids",
                   f"the bank's ids are the 0-based line numbers, {len(plain_lines)} of them" if ids_ok else
                   f"RED: a plain-text corpus is refused -- the CLI's only corpus loader is JSONL; "
                   f"exit={plain_bake.returncode}; {(plain_bake.stdout + plain_bake.stderr)[-200:]!r}")
        report.add("PASS" if vectors_ok else "FAIL", "plain-text vectors byte-equal the JSONL bake",
                   "the same documents baked from JSONL produce identical vector bytes" if vectors_ok else
                   "RED: the plain-text bake did not produce vectors comparable to the JSONL bake")
        inspect_manifest = Path(str(good) + ".semb.json"); inspect = call([str(semb), "inspect", str(inspect_manifest)])
        report.add("PASS" if inspect.returncode == 0 and inspect_manifest.read_text(encoding="utf-8") in inspect.stdout else "FAIL",
                   "CLI inspect opens no encoder", "inspect succeeds while the configured model artifact is absent")
        # TE-235 (TE-233 M-1), tightened TE-237 (TE-236's M-3): the output
        # modes are exclusive; every conflicting combination is refused by
        # name -- the exact status SEMB_NULL_ARGUMENT AND both conflicting
        # flag names in the refusal context (`semb query --raw --hex:
        # SEMB_NULL_ARGUMENT (N)`), never a bare nonzero exit. Each command
        # uses a MISSING model and tokenizer path, so a pass proves the
        # refusal precedes any encoder or bank open: with the guard deleted,
        # the command would proceed to open the missing model and refuse
        # without the flag names, which this cell rejects -- the old
        # `returncode != 0 and "SEMB_" in output` shape passed exactly that.
        # `--raw --stdin` is driven with exactly the one positional a valid
        # stdin session takes (the stem; no query text), so deleting the
        # mode-conflict guard turns this cell red instead of the generic
        # stdin-arity check keeping it green the way the two-positional
        # command shape did.
        missing_base = ["--model", str(scratch / "te230_missing_model.sslm"),
                        "--tokenizer", str(scratch / "te230_missing_tokenizer.sslm")]
        for flags, context in ((["--hex", "--top", "5"], "semb query --hex --top"),
                               (["--raw", "--hex"], "semb query --raw --hex"),
                               (["--raw", "--top", "5"], "semb query --raw --top"),
                               (["--raw", "--stdin"], "semb query --raw --stdin")):
            if "--stdin" in flags:
                command = [str(semb), "query", str(good), *flags, *missing_base]
            else:
                command = [str(semb), "query", str(good), text, *flags, *missing_base]
            clash = call(command)
            clash_ok = named_refusal(clash, context)
            # `--raw --hex` at a silently-resolving base emits raw float bytes
            # on stdout; keep the quoted snippet console-printable (cp1252).
            snippet = (clash.stdout + clash.stderr)[:160].encode("ascii", "backslashreplace").decode("ascii")
            report.add("PASS" if clash_ok else "FAIL",
                       f"M-1 conflicting output modes refused by name ({' '.join(flags)})",
                       f"exit 1 refusing as `{context}: SEMB_NULL_ARGUMENT` before any open" if clash_ok else
                       f"RED: exit={clash.returncode}; output={snippet!r}; the combination must refuse naming "
                       f"`{context}` and SEMB_NULL_ARGUMENT before any open -- accepted-and-silent, an unnamed "
                       "nonzero exit, or a refusal without both flag names all fail this cell")
        # TE-235 (TE-233 S-2), behavioral half: a --stdin --top session
        # answers from the bank the checked handle validated even after the
        # pair files on disk are replaced between queries.  GREEN at 6991a85
        # (the current CLI loads its --top copy once, before the session
        # loop); this cell guards a per-query re-read, which is why the
        # structural cell above is the half that is red at the base.
        replacement_corpus = scratch / "s2_replacement.jsonl"
        replacement_corpus.write_text("\n".join(
            json.dumps({"id": f"REPLACED-{i:02d}",
                        "text": f"Replacement row {i}: text the original bank never baked."})
            for i in range(16)) + "\n", encoding="utf-8")
        replacement_stem = scratch / "s2_replacement_bank"
        replacement_bake = call([str(semb), "bake", str(replacement_corpus), "--out", str(replacement_stem), *base])
        if replacement_bake.returncode != 0:
            report.add("FAIL", "S-2b a --stdin --top session ranks the validated bank after its files are replaced",
                       f"apparatus: the replacement bank bake failed; exit={replacement_bake.returncode}; "
                       f"{(replacement_bake.stdout + replacement_bake.stderr)[-300:]!r}")
        else:
            session_stem = scratch / "s2_session"
            copied_stem(good, session_stem)
            first_line, second_line, session_code = stdin_top_session(
                semb, session_stem, base, text, 20.0, replacement_stem)

            def hit_ids(line: str | None) -> list[str] | None:
                if line is None:
                    return None
                try:
                    return [hit["id"] for hit in json.loads(line)["hits"]]
                except (ValueError, KeyError, TypeError):
                    return None

            first_ids, second_ids = hit_ids(first_line), hit_ids(second_line)
            original_ids = {json.loads(row)["id"] for row in corpus.read_text(encoding="utf-8").splitlines()}
            session_ok = (session_code == 0 and isinstance(first_ids, list) and isinstance(second_ids, list)
                          and first_ids == second_ids and set(second_ids) <= original_ids)
            report.add("PASS" if session_ok else "FAIL",
                       "S-2b a --stdin --top session ranks the validated bank after its files are replaced",
                       "both answers rank the same wb ids; the on-disk replacement never reached the ranking" if session_ok else
                       f"RED: after the pair files were replaced mid-session, answer 1 ranked {first_ids} and "
                       f"answer 2 ranked {second_ids} (exit={session_code}); the session answered from the disk "
                       "bytes rather than the bank snapshot the checked handle validated")
        # TE-235 (the conductor's .JSONL finding, D-SLM6638): the corpus
        # format rule selects JSONL by the path without regard to case; at
        # 6991a85 only a lower-case `.jsonl` does, so the same rows bake
        # silently as plain text with line-number ids.
        upper = scratch / "upper_corpus.JSONL"
        shutil.copyfile(corpus, upper)
        upper_bake = call([str(semb), "bake", str(upper), "--out", str(scratch / "upper_bank"), *base])
        upper_ids = None
        if upper_bake.returncode == 0:
            upper_ids = json.loads(Path(str(scratch / "upper_bank") + ".wvbank.json")
                                   .read_text(encoding="utf-8")).get("ids")
        row_ids = [json.loads(row)["id"] for row in corpus.read_text(encoding="utf-8").splitlines()]
        upper_ids_ok = upper_bake.returncode == 0 and upper_ids == row_ids
        report.add("PASS" if upper_ids_ok else "FAIL",
                   "an upper-case .JSONL corpus bakes with the ids its rows carry",
                   "the bank's ids are the rows' own ids, same as the lower-case bake" if upper_ids_ok else
                   f"RED: exit={upper_bake.returncode}; ids={(upper_ids or [])[:4]}... -- only a lower-case "
                   "`.jsonl` selects the JSONL rule, so .JSONL rows bake as plain text with line-number ids")
        upper_vectors_ok = (upper_bake.returncode == 0
                            and Path(str(scratch / "upper_bank") + ".wvbank.bin").read_bytes()
                            == Path(str(good) + ".wvbank.bin").read_bytes())
        report.add("PASS" if upper_vectors_ok else "FAIL",
                   "an upper-case .JSONL corpus bakes vectors byte-equal the .jsonl bake",
                   "the identical corpus named .jsonl and .JSONL produces identical vector bytes" if upper_vectors_ok else
                   "RED: the .JSONL bake's vector bytes differ from the .jsonl bake's -- each JSON line was "
                   "taken as whole-line document text")
        # TE-317 (D-SLM7405), fix round TE-320: `semb bake` skips exactly the
        # documents the library refuses as SEMB_INPUT_EMPTY (utf8_len == 0)
        # and reports what it skipped; the library's own all-or-nothing
        # batch refusal is untouched. The inserted id (447488) is K1-Run-2's
        # own BEIR fiqa document -- the empty-text row that killed a 3-hour
        # bake (D-SLM7404) and the reason this ticket exists.
        mixed_rows = corpus.read_text(encoding="utf-8").splitlines()
        mixed_rows.insert(9, json.dumps({"id": "447488", "text": ""}))
        mixed_corpus = scratch / "mixed_empty_corpus.jsonl"
        mixed_corpus.write_text("\n".join(mixed_rows) + "\n", encoding="utf-8")
        mixed_stem = scratch / "mixed_bank"
        mixed_bake = call([str(semb), "bake", str(mixed_corpus), "--out", str(mixed_stem), *base])
        skip_line_ok = (mixed_bake.returncode == 0 and 'skipped "447488": SEMB_INPUT_EMPTY' in mixed_bake.stderr)
        report.add("PASS" if skip_line_ok else "FAIL",
                   "TE-317 bake skips one empty document among good ones and reports it",
                   f"exit 0, stderr names the id: {mixed_bake.stderr.strip()!r}" if skip_line_ok else
                   f"RED: exit={mixed_bake.returncode}; stderr={mixed_bake.stderr[-300:]!r}; expected exit 0 with "
                   'the line \'skipped "447488": SEMB_INPUT_EMPTY\' (plan U2-8\'s own stderr shape, id JSON-quoted per N-3)')
        # T-2 (TE-320): the sidecar's exact content, not a substring -- the
        # JSON array (S-4/M-1) holds exactly one entry, with both fields.
        sidecar = Path(str(mixed_stem) + ".skipped.json")
        sidecar_entries = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else None
        sidecar_ok = sidecar_entries == [{"id": "447488", "reason": "empty_text"}]
        report.add("PASS" if sidecar_ok else "FAIL",
                   "TE-317/T-2 bake writes the skipped-document sidecar with exact content",
                   f"{sidecar.name} == [{{'id': '447488', 'reason': 'empty_text'}}]" if sidecar_ok else
                   f"RED: {sidecar} is missing or its content is {sidecar_entries!r}, expected exactly "
                   "[{'id': '447488', 'reason': 'empty_text'}] -- the skip record must survive the terminal")
        mixed_header_ok = mixed_rows_ok = False
        if mixed_bake.returncode == 0 and files_ok:
            good_header = json.loads(Path(str(good) + ".wvbank.json").read_text(encoding="utf-8"))
            mixed_header = json.loads(Path(str(mixed_stem) + ".wvbank.json").read_text(encoding="utf-8"))
            mixed_header_ok = mixed_header.get("ids") == good_header.get("ids")
            mixed_rows_ok = (Path(str(mixed_stem) + ".wvbank.bin").read_bytes()
                            == Path(str(good) + ".wvbank.bin").read_bytes())
        report.add("PASS" if mixed_header_ok else "FAIL",
                   "TE-317 bank rows equal the good documents alone (ids)",
                   "the skipped document's id is absent; every good id survives, in order" if mixed_header_ok else
                   "RED: the mixed bake's ids do not equal baking the good documents alone")
        report.add("PASS" if mixed_rows_ok else "FAIL",
                   "TE-317 bank rows equal the good documents alone (bytes)",
                   "row bytes are identical to baking the good documents alone" if mixed_rows_ok else
                   "RED: the mixed bake's row bytes differ from baking the same good documents alone")
        # TE-320 S-1: the sidecar must never go stale. A clean re-bake (no
        # empty documents at all) at the SAME stem that just held a skip
        # must overwrite the sidecar to the empty array, not leave the old
        # entry sitting beside a bank that no longer has it.
        clean_rebake = call([str(semb), "bake", str(corpus), "--out", str(mixed_stem), *base])
        stale_sidecar = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else None
        stale_ok = clean_rebake.returncode == 0 and stale_sidecar == []
        report.add("PASS" if stale_ok else "FAIL",
                   "TE-320 S-1 a clean re-bake at the same stem clears a stale sidecar",
                   "re-bake exit 0, sidecar == []" if stale_ok else
                   f"RED: exit={clean_rebake.returncode}; sidecar={stale_sidecar!r}, expected [] -- the sidecar "
                   "from the PRIOR bake at this stem must not survive a bake that skipped nothing")
        # TE-320 S-2: a document is skipped only when empty text is its ONLY
        # defect. An empty text paired with a NUL byte or invalid UTF-8 in
        # the id must still be refused by the library's own id check
        # (SEMB_DOCUMENT_ID_INVALID), never silently skipped -- these
        # corpora are built as raw bytes because a NUL or an invalid UTF-8
        # byte cannot be expressed through json.dumps.
        nul_id_corpus = scratch / "nul_id_corpus.jsonl"
        nul_id_corpus.write_bytes(
            b"\n".join(row.encode("utf-8") for row in mixed_rows[:3]) +
            b'\n{"id": "a\\u0000b", "text": ""}\n')
        nul_id_bake = call([str(semb), "bake", str(nul_id_corpus), "--out", str(scratch / "nul_id_bank"), *base])
        nul_id_ok = named_refusal(nul_id_bake, "semb_bake_to_path", "SEMB_DOCUMENT_ID_INVALID")
        report.add("PASS" if nul_id_ok else "FAIL",
                   "TE-320 S-2 an empty-text document with a NUL byte in its id is refused, not skipped",
                   "refused `semb_bake_to_path: SEMB_DOCUMENT_ID_INVALID (19)`" if nul_id_ok else
                   f"RED: exit={nul_id_bake.returncode}; stderr={nul_id_bake.stderr[-300:]!r}; a NUL-id document "
                   "must reach the library's own id check, not be swallowed as \"empty\"")
        bad_utf8_id_corpus = scratch / "bad_utf8_id_corpus.jsonl"
        bad_utf8_id_corpus.write_bytes(
            b"\n".join(row.encode("utf-8") for row in mixed_rows[:3]) +
            b'\n{"id": "a\xffb", "text": ""}\n')
        bad_utf8_id_bake = call([str(semb), "bake", str(bad_utf8_id_corpus), "--out", str(scratch / "bad_utf8_id_bank"), *base])
        bad_utf8_id_ok = named_refusal(bad_utf8_id_bake, "semb_bake_to_path", "SEMB_DOCUMENT_ID_INVALID")
        report.add("PASS" if bad_utf8_id_ok else "FAIL",
                   "TE-320 S-2 an empty-text document with invalid UTF-8 in its id is refused, not skipped",
                   "refused `semb_bake_to_path: SEMB_DOCUMENT_ID_INVALID (19)`" if bad_utf8_id_ok else
                   f"RED: exit={bad_utf8_id_bake.returncode}; stderr={bad_utf8_id_bake.stderr[-300:]!r}; an "
                   "invalid-UTF-8-id document must reach the library's own id check, not be swallowed as \"empty\"")
        # T-1 (TE-320): the id_len > 0 guard itself -- an empty id paired
        # with empty text is refused the same way, and no te230 cell built
        # this input before this fix round.
        empty_id_corpus = scratch / "empty_id_corpus.jsonl"
        empty_id_rows = [json.loads(r) for r in mixed_rows[:3]] + [{"id": "", "text": ""}]
        empty_id_corpus.write_text("\n".join(json.dumps(r) for r in empty_id_rows) + "\n", encoding="utf-8")
        empty_id_bake = call([str(semb), "bake", str(empty_id_corpus), "--out", str(scratch / "empty_id_bank"), *base])
        empty_id_ok = named_refusal(empty_id_bake, "semb_bake_to_path", "SEMB_DOCUMENT_ID_INVALID")
        report.add("PASS" if empty_id_ok else "FAIL",
                   "TE-320 T-1 an empty id with empty text is refused, not skipped",
                   "refused `semb_bake_to_path: SEMB_DOCUMENT_ID_INVALID (19)`" if empty_id_ok else
                   f"RED: exit={empty_id_bake.returncode}; stderr={empty_id_bake.stderr[-300:]!r}")
        # TE-320 M-2: a duplicate id where one twin is empty must still be
        # refused SEMB_DOCUMENT_ID_DUPLICATE -- filtering must not make one
        # id disappear from the duplicate check by removing its empty twin
        # from the batch before the check would otherwise see it.
        dup_rows = [json.loads(r) for r in mixed_rows[:3]]
        dup_rows.append({"id": dup_rows[0]["id"], "text": ""})
        dup_corpus = scratch / "dup_id_corpus.jsonl"
        dup_corpus.write_text("\n".join(json.dumps(r) for r in dup_rows) + "\n", encoding="utf-8")
        dup_bake = call([str(semb), "bake", str(dup_corpus), "--out", str(scratch / "dup_id_bank"), *base])
        dup_ok = named_refusal(dup_bake, "semb bake", "SEMB_DOCUMENT_ID_DUPLICATE")
        report.add("PASS" if dup_ok else "FAIL",
                   "TE-320 M-2 a duplicate id where one twin is empty still refuses SEMB_DOCUMENT_ID_DUPLICATE",
                   "refused `semb bake: SEMB_DOCUMENT_ID_DUPLICATE (20)`" if dup_ok else
                   f"RED: exit={dup_bake.returncode}; stderr={dup_bake.stderr[-300:]!r}; the corpus named one id "
                   "twice and this must not disappear because one copy was skipped")
        # TE-320 F4 (Mendeleev te319): the sidecar write can fail after the
        # bank is already valid -- pre-create a directory at the sidecar's
        # own path so the write (temp file + rename, M-3) cannot land, and
        # confirm the bank triple still exists while bake itself refuses.
        # Extended TE-326 M-5: a directory at the sidecar path is an
        # obstruction the caller created, not a stale record, so
        # RemoveStaleSidecarBestEffort must leave it exactly as a directory
        # (never remove or replace it).
        f4_stem = scratch / "f4_sidecar_fail"
        f4_sidecar_path = Path(str(f4_stem) + ".skipped.json")
        f4_sidecar_path.mkdir(parents=True)
        f4_bake = call([str(semb), "bake", str(mixed_corpus), "--out", str(f4_stem), *base])
        f4_triple_ok = all(Path(str(f4_stem) + s).is_file() for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
        f4_dir_stayed = f4_sidecar_path.is_dir()
        f4_ok = (named_refusal(f4_bake, "semb bake skipped-sidecar", "SEMB_ARTIFACT_UNREADABLE")
                and f4_triple_ok and f4_dir_stayed)
        report.add("PASS" if f4_ok else "FAIL",
                   "TE-320 F4 a sidecar write failure refuses, with the bank triple already valid",
                   "refused `semb bake skipped-sidecar: SEMB_ARTIFACT_UNREADABLE (11)`, bank triple present, "
                   "directory obstruction left exactly as a directory (TE-326 M-5)" if f4_ok else
                   f"RED: exit={f4_bake.returncode}; stderr={f4_bake.stderr[-300:]!r}; triple_ok={f4_triple_ok}; "
                   f"sidecar_path_is_still_a_directory={f4_dir_stayed}")
        # TE-326 T-4(a): the skip-collision duplicate check at the VERIFY
        # call site specifically -- not only bake's. A corpus naming a kept
        # bank id twice (once normally, once as an empty twin) must refuse
        # SEMB_DOCUMENT_ID_DUPLICATE from `semb verify` too; the N-4
        # precedence cell above only ever calls `bake`, so it cannot
        # discriminate a mutant that deletes the check at the verify site
        # alone (TE-326 Mutant A).
        verify_dup_rows = [json.loads(r) for r in mixed_rows[:3]]
        verify_dup_rows.append({"id": verify_dup_rows[0]["id"], "text": ""})
        verify_dup_corpus = scratch / "verify_dup_id_corpus.jsonl"
        verify_dup_corpus.write_text("\n".join(json.dumps(r) for r in verify_dup_rows) + "\n", encoding="utf-8")
        verify_dup_check = call([str(semb), "verify", str(good), "--corpus", str(verify_dup_corpus), *base])
        verify_dup_ok = named_refusal(verify_dup_check, "semb verify", "SEMB_DOCUMENT_ID_DUPLICATE")
        report.add("PASS" if verify_dup_ok else "FAIL",
                   "TE-326 T-4(a) verify refuses a skip-collision duplicate, at the verify call site itself",
                   "refused `semb verify: SEMB_DOCUMENT_ID_DUPLICATE (20)`" if verify_dup_ok else
                   f"RED: exit={verify_dup_check.returncode}; {(verify_dup_check.stdout + verify_dup_check.stderr)[-300:]!r}; "
                   "a corpus naming one id twice (one kept, one empty twin) must be refused by verify too, not "
                   "only by bake")
        # TE-326 T-4(b): an id containing a line break stays on ONE stderr
        # line. Every existing stderr assertion in this suite uses the id
        # 447488 (no special characters), so a remedy that quotes the id
        # without escaping it (TE-326 Mutant B) would still pass every
        # other cell; this one specifically checks line count.
        lf_id_rows = [json.loads(mixed_rows[0]), {"id": "a\nb", "text": ""}]
        lf_id_corpus = scratch / "lf_id_corpus.jsonl"
        lf_id_corpus.write_text("\n".join(json.dumps(r) for r in lf_id_rows) + "\n", encoding="utf-8")
        lf_id_bake = call([str(semb), "bake", str(lf_id_corpus), "--out", str(scratch / "lf_id_bank"), *base])
        lf_stderr_lines = [line for line in lf_id_bake.stderr.splitlines() if line.startswith("skipped ")]
        lf_id_ok = (lf_id_bake.returncode == 0 and lf_stderr_lines == ['skipped "a\\nb": SEMB_INPUT_EMPTY'])
        report.add("PASS" if lf_id_ok else "FAIL",
                   "TE-326 T-4(b) an id containing a line break stays on exactly one stderr line",
                   'exactly one line, skipped "a\\nb": SEMB_INPUT_EMPTY' if lf_id_ok else
                   f"RED: exit={lf_id_bake.returncode}; skip-lines={lf_stderr_lines!r}; expected exactly one line "
                   'reading skipped "a\\nb": SEMB_INPUT_EMPTY -- an unescaped LF in the id splits it into two')
        # TE-326 T-4(c) / N-2: the close-time write-failure check
        # (WriteSkippedSidecar's explicit close() + check before rename)
        # has no pin anywhere in this suite; its only prior evidence was a
        # harness outside the repository (WSL GCC in the round-3 build log,
        # MSVC named-pipe in this review). The CLI's own ctest target runs
        # on ubuntu-latest in CI, where `/dev/full` always fails a write at
        # flush -- symlinking the sidecar's OWN temp path to it reproduces
        # the exact failure class through the real CLI. Not reproducible on
        # native Windows (no write-always-fails device exists), so this
        # cell reports BLOCKED with a named reason there rather than
        # silently passing or silently not existing.
        if os.name == "posix" and Path("/dev/full").exists():
            n2_stem = scratch / "n2_close_check"
            n2_bake_1 = call([str(semb), "bake", str(mixed_corpus), "--out", str(n2_stem), *base])
            n2_sidecar_path = Path(str(n2_stem) + ".skipped.json")
            n2_prior_sidecar_existed = n2_bake_1.returncode == 0 and n2_sidecar_path.is_file()
            n2_tmp_path = Path(str(n2_stem) + ".skipped.json.tmp")
            if n2_tmp_path.exists():
                n2_tmp_path.unlink()
            n2_tmp_path.symlink_to("/dev/full")
            n2_bake_2 = call([str(semb), "bake", str(mixed_corpus), "--out", str(n2_stem), *base])
            n2_triple_ok = all(Path(str(n2_stem) + s).is_file() for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
            # TE-326 M-5: the close-time failure removes the PRIOR sidecar
            # (best effort) instead of leaving it stale beside the new bank.
            n2_stale_removed = not n2_sidecar_path.exists()
            n2_ok = (n2_prior_sidecar_existed
                    and named_refusal(n2_bake_2, "semb bake skipped-sidecar", "SEMB_ARTIFACT_UNREADABLE")
                    and n2_triple_ok and n2_stale_removed)
            report.add("PASS" if n2_ok else "FAIL",
                       "TE-326 T-4(c)/N-2 a close-time write failure (/dev/full) refuses and clears the stale sidecar",
                       "refused `semb bake skipped-sidecar: SEMB_ARTIFACT_UNREADABLE (11)`, bank triple valid, "
                       "prior sidecar removed (TE-326 M-5)" if n2_ok else
                       f"RED: prior_sidecar_existed={n2_prior_sidecar_existed}; exit={n2_bake_2.returncode}; "
                       f"stderr={n2_bake_2.stderr[-300:]!r}; triple_ok={n2_triple_ok}; stale_removed={n2_stale_removed}")
        else:
            report.add("SKIPPED", "TE-326 T-4(c)/N-2 a close-time write failure (/dev/full) refuses and clears the stale sidecar",
                       f"POSIX /dev/full is unavailable on this platform (os.name={os.name!r}); this cell runs on "
                       "Linux CI (ubuntu-latest), where the CLI's ctest target is exercised")
        # A non-empty corpus where every document is empty has nothing left
        # to bake: refused exactly as an all-empty batch, SEMB_INPUT_EMPTY,
        # never SEMB_CORPUS_EMPTY (that status is reserved for a corpus with
        # zero documents, C24 above) -- and no leftover file, matching C24's
        # own hygiene.
        all_empty_rows = [json.dumps({"id": f"empty-{i}", "text": ""}) for i in range(3)]
        all_empty_corpus = scratch / "all_empty_corpus.jsonl"
        all_empty_corpus.write_text("\n".join(all_empty_rows) + "\n", encoding="utf-8")
        all_empty_stem = scratch / "all_empty" / "out"; all_empty_stem.parent.mkdir()
        all_empty_bake = call([str(semb), "bake", str(all_empty_corpus), "--out", str(all_empty_stem), *base])
        all_empty_leftovers = list(all_empty_stem.parent.iterdir())
        all_empty_ok = (named_refusal(all_empty_bake, "semb bake", "SEMB_INPUT_EMPTY")
                        and not all_empty_leftovers)
        report.add("PASS" if all_empty_ok else "FAIL",
                   "TE-317 a corpus where every document is empty still refuses (SEMB_INPUT_EMPTY, no leftovers)",
                   "refused as `semb bake: SEMB_INPUT_EMPTY (8)`, no leftover files" if all_empty_ok else
                   f"RED: exit={all_empty_bake.returncode}; stderr={all_empty_bake.stderr[-300:]!r}; "
                   f"leftovers={[p.name for p in all_empty_leftovers]}")
        # Re-bake the mixed corpus once more (the stale-sidecar cell above
        # left `mixed_stem` clean) so the round-trip cells below verify
        # against a freshly baked bank.
        mixed_bake_2 = call([str(semb), "bake", str(mixed_corpus), "--out", str(mixed_stem), *base])
        if mixed_bake_2.returncode == 0:
            # TE-320 S-3: verify reports its own skips on stderr, exactly as
            # bake does, and accepts its own real corpus.
            mixed_verify = call([str(semb), "verify", str(mixed_stem), "--corpus", str(mixed_corpus), *base])
            mixed_verify_ok = mixed_verify.returncode == 0 and 'skipped "447488": SEMB_INPUT_EMPTY' in mixed_verify.stderr
            report.add("PASS" if mixed_verify_ok else "FAIL",
                       "TE-317/S-3 verify skips identically, reports it, and the bank verifies OK",
                       "exit 0, stderr names the skipped id" if mixed_verify_ok else
                       f"RED: exit={mixed_verify.returncode}; {(mixed_verify.stdout + mixed_verify.stderr)[-300:]!r}; "
                       "verify must skip the same document bake did AND report it, or its re-encode is refused "
                       "SEMB_INPUT_EMPTY instead of comparing digests")
            # TE-317 round 3 (conductor direction D-SLM7433, revising TE-320's
            # own S-3 remedy after TE-324's N-1): verify's corpus-identity
            # verdict comes ONLY from the row/corpus digest comparison it
            # already made before this ticket -- it does not read the bank's
            # sidecar at all. A corpus with extra empty documents the bank
            # never saw re-bakes to the IDENTICAL kept set (the extra
            # documents contribute nothing), so it verifies OK -- the
            # opposite of round 2's own cell, which this replaces.
            extra_empty_corpus = scratch / "mixed_plus_extra_empty.jsonl"
            extra_empty_corpus.write_text(
                mixed_corpus.read_text(encoding="utf-8") +
                "\n".join(json.dumps({"id": f"X{i}", "text": ""}) for i in range(3)) + "\n",
                encoding="utf-8")
            extra_verify = call([str(semb), "verify", str(mixed_stem), "--corpus", str(extra_empty_corpus), *base])
            extra_verify_ok = extra_verify.returncode == 0
            report.add("PASS" if extra_verify_ok else "FAIL",
                       "TE-317 round 3 a corpus with extra empty documents re-bakes identically and verifies OK",
                       "the extra empty documents contribute nothing kept; digests match, verify accepts" if extra_verify_ok else
                       f"RED: exit={extra_verify.returncode}; {(extra_verify.stdout + extra_verify.stderr)[-300:]!r}; "
                       "under D-SLM7433 this corpus re-bakes to the identical kept set and must verify OK")
            # TE-317 round 3, requirement 1 (N-1's path (a)): a bank moved or
            # copied as its three library-written files, with no sidecar at
            # all, verifies OK against its real corpus -- verify's verdict
            # cannot depend on a file the library never writes and this
            # project's own copied_stem() helper never copies.
            copied_bank_stem = scratch / "mixed_copied_no_sidecar"
            copied_stem(mixed_stem, copied_bank_stem)
            copied_has_no_sidecar = not Path(str(copied_bank_stem) + ".skipped.json").exists()
            copied_verify = call([str(semb), "verify", str(copied_bank_stem), "--corpus", str(mixed_corpus), *base])
            copied_verify_ok = copied_has_no_sidecar and copied_verify.returncode == 0
            report.add("PASS" if copied_verify_ok else "FAIL",
                       "TE-317 round 3 a copied bank (three files, no sidecar) verifies OK against its real corpus",
                       "the copy carries no sidecar; verify accepts on the digest comparison alone" if copied_verify_ok else
                       f"RED: sidecar_present={not copied_has_no_sidecar}; exit={copied_verify.returncode}; "
                       f"{(copied_verify.stdout + copied_verify.stderr)[-300:]!r}")
            # TE-317 round 3, requirement 1 (N-1's path (b)): a bank whose
            # sidecar is STALE (names ids that are not this bank's, as a
            # failed re-bake's sidecar write would leave) still verifies OK
            # by the digests alone -- the sidecar's content is never read.
            stale_bank_stem = scratch / "mixed_stale_sidecar"
            copied_stem(mixed_stem, stale_bank_stem)
            Path(str(stale_bank_stem) + ".skipped.json").write_text(
                json.dumps([{"id": "totally-unrelated-id", "reason": "empty_text"}]), encoding="utf-8")
            stale_verify = call([str(semb), "verify", str(stale_bank_stem), "--corpus", str(mixed_corpus), *base])
            stale_verify_ok = stale_verify.returncode == 0
            report.add("PASS" if stale_verify_ok else "FAIL",
                       "TE-317 round 3 a bank with a stale sidecar verifies by the digests alone",
                       "a sidecar naming an unrelated id is never read; verify accepts on the digest comparison" if stale_verify_ok else
                       f"RED: exit={stale_verify.returncode}; {(stale_verify.stdout + stale_verify.stderr)[-300:]!r}")
            # An unparseable sidecar (not even valid JSON) must be ignored
            # the same way -- verify no longer has any code path that reads
            # or validates it.
            garbage_bank_stem = scratch / "mixed_garbage_sidecar"
            copied_stem(mixed_stem, garbage_bank_stem)
            Path(str(garbage_bank_stem) + ".skipped.json").write_text("not json at all [", encoding="utf-8")
            garbage_verify = call([str(semb), "verify", str(garbage_bank_stem), "--corpus", str(mixed_corpus), *base])
            garbage_verify_ok = garbage_verify.returncode == 0
            report.add("PASS" if garbage_verify_ok else "FAIL",
                       "TE-317 round 3 a bank with an unparseable sidecar verifies by the digests alone",
                       "unparseable sidecar content is never read; verify accepts on the digest comparison" if garbage_verify_ok else
                       f"RED: exit={garbage_verify.returncode}; {(garbage_verify.stdout + garbage_verify.stderr)[-300:]!r}")
            # TE-317 round 3 (N-4): the skip-collision duplicate check must
            # not preempt a defect the library would refuse for FIRST, in
            # its own per-document order over the kept batch. A corpus with
            # invalid UTF-8 text at an earlier index and a
            # duplicate-with-empty-twin later must report the library's own
            # refusal (SEMB_INVALID_UTF8), not the CLI's own
            # SEMB_DOCUMENT_ID_DUPLICATE.
            precedence_good = [json.loads(r) for r in mixed_rows[:3]]
            precedence_corpus = scratch / "precedence_corpus.jsonl"
            precedence_corpus.write_bytes(
                json.dumps(precedence_good[0]).encode("utf-8") + b"\n" +
                b'{"id": "bad", "text": "x\xffy"}\n' +
                json.dumps(precedence_good[1]).encode("utf-8") + b"\n" +
                json.dumps({"id": precedence_good[1]["id"], "text": ""}).encode("utf-8") + b"\n")
            precedence_bake = call([str(semb), "bake", str(precedence_corpus), "--out", str(scratch / "precedence_bank"), *base])
            precedence_ok = named_refusal(precedence_bake, "semb_bake_to_path", "SEMB_INVALID_UTF8")
            report.add("PASS" if precedence_ok else "FAIL",
                       "TE-317 round 3 N-4 a multi-defect corpus reports the library's own first refusal",
                       "refused `semb_bake_to_path: SEMB_INVALID_UTF8 (9)`, the library's own precedence" if precedence_ok else
                       f"RED: exit={precedence_bake.returncode}; stderr={precedence_bake.stderr[-300:]!r}; the "
                       "CLI's own collision check must not preempt a defect the library would refuse for first")
        else:
            report.add("BLOCKED", "TE-317/S-3 verify skips identically, reports it, and the bank verifies OK",
                       "the mixed-corpus bake did not succeed")
            report.add("BLOCKED", "TE-317 round 3 a corpus with extra empty documents re-bakes identically and verifies OK",
                       "the mixed-corpus bake did not succeed")
            report.add("BLOCKED", "TE-317 round 3 a copied bank (three files, no sidecar) verifies OK against its real corpus",
                       "the mixed-corpus bake did not succeed")
            report.add("BLOCKED", "TE-317 round 3 a bank with a stale sidecar verifies by the digests alone",
                       "the mixed-corpus bake did not succeed")
            report.add("BLOCKED", "TE-317 round 3 a bank with an unparseable sidecar verifies by the digests alone",
                       "the mixed-corpus bake did not succeed")
            report.add("BLOCKED", "TE-317 round 3 N-4 a multi-defect corpus reports the library's own first refusal",
                       "the mixed-corpus bake did not succeed")
        # TE-326 M-4: the defect-beats-duplicate rule applies to a kept
        # defect at ANY position, not only one earlier than the colliding
        # twin -- step 9 validates every document before step 10's
        # uniqueness check ever runs (encoder.cpp), so a defect AFTER the
        # twin still outranks the duplicate. The N-4 cell above puts the
        # bad-UTF-8 document BEFORE the twin (index 1, twin at 2); this one
        # puts the twin first (index 1) and the bad-UTF-8 document after it
        # (index 2), so a scan that stopped at the twin (TE-326 Mutant C)
        # would wrongly refuse SEMB_DOCUMENT_ID_DUPLICATE instead of
        # reporting the library's own SEMB_INVALID_UTF8.
        after_good = [json.loads(r) for r in mixed_rows[:3]]
        after_corpus = scratch / "defect_after_twin_corpus.jsonl"
        after_corpus.write_bytes(
            json.dumps(after_good[0]).encode("utf-8") + b"\n" +
            json.dumps(after_good[1]).encode("utf-8") + b"\n" +
            json.dumps({"id": after_good[1]["id"], "text": ""}).encode("utf-8") + b"\n" +
            b'{"id": "bad", "text": "x\xffy"}\n')
        after_bake = call([str(semb), "bake", str(after_corpus), "--out", str(scratch / "defect_after_twin_bank"), *base])
        after_ok = named_refusal(after_bake, "semb_bake_to_path", "SEMB_INVALID_UTF8")
        report.add("PASS" if after_ok else "FAIL",
                   "TE-326 M-4 a kept defect AFTER the colliding twin still outranks the duplicate refusal",
                   "refused `semb_bake_to_path: SEMB_INVALID_UTF8 (9)`, the library's own precedence" if after_ok else
                   f"RED: exit={after_bake.returncode}; stderr={after_bake.stderr[-300:]!r}; a defect anywhere in "
                   "kept -- including after the colliding twin -- must outrank the CLI's own duplicate refusal")
        # TE-326 R-1: beyond LF/CR/ESC (round 3's own N-3 fix), the stderr
        # id also escapes U+2028 (LINE SEPARATOR) -- a de facto line
        # boundary to Python's own str.splitlines(), which this very test
        # file uses to find "skipped " lines. An id carrying U+2028 raw
        # would split into two lines the same way an unescaped LF did.
        ls_id_rows = [json.loads(mixed_rows[0]), {"id": "ls ps", "text": ""}]
        ls_id_corpus = scratch / "ls_id_corpus.jsonl"
        ls_id_corpus.write_text("\n".join(json.dumps(r) for r in ls_id_rows) + "\n", encoding="utf-8")
        ls_id_bake = call([str(semb), "bake", str(ls_id_corpus), "--out", str(scratch / "ls_id_bank"), *base])
        ls_stderr_lines = [line for line in ls_id_bake.stderr.splitlines() if line.startswith("skipped ")]
        ls_id_ok = (ls_id_bake.returncode == 0 and ls_stderr_lines == ['skipped "ls\\u2028ps": SEMB_INPUT_EMPTY'])
        report.add("PASS" if ls_id_ok else "FAIL",
                   "TE-326 R-1 an id containing U+2028 (LINE SEPARATOR) stays on exactly one stderr line",
                   'exactly one line, skipped "ls\\u2028ps": SEMB_INPUT_EMPTY' if ls_id_ok else
                   f"RED: exit={ls_id_bake.returncode}; skip-lines={ls_stderr_lines!r}; expected exactly one line "
                   'reading skipped "ls\\u2028ps": SEMB_INPUT_EMPTY -- a raw U+2028 is a line boundary to '
                   "Python's str.splitlines(), among other consumers")
        # F5 (Mendeleev te319): verify's own twin of the all-empty bake
        # cell -- a non-empty, all-empty corpus against an existing good
        # bank refuses SEMB_INPUT_EMPTY, the same status bake uses for the
        # same shape of corpus.
        f5_all_empty_corpus = scratch / "f5_all_empty_corpus.jsonl"
        f5_all_empty_corpus.write_text(
            "\n".join(json.dumps({"id": f"z{i}", "text": ""}) for i in range(2)) + "\n", encoding="utf-8")
        f5_verify = call([str(semb), "verify", str(good), "--corpus", str(f5_all_empty_corpus), *base])
        f5_ok = named_refusal(f5_verify, "semb verify", "SEMB_INPUT_EMPTY")
        report.add("PASS" if f5_ok else "FAIL",
                   "TE-320 F5 verify refuses SEMB_INPUT_EMPTY on an all-empty corpus",
                   "refused `semb verify: SEMB_INPUT_EMPTY (8)`" if f5_ok else
                   f"RED: exit={f5_verify.returncode}; {(f5_verify.stdout + f5_verify.stderr)[-300:]!r}")
        # Control: the library's own all-or-nothing batch refusal is
        # untouched. The CLI probe's --bake-corpus mode calls
        # semb_bake_to_path directly with NO filtering (tests/te230_semb_cli_probe.cpp),
        # so feeding it the same mixed corpus proves the library still
        # refuses the whole batch on the one empty document.
        library_mixed_stem = scratch / "library_mixed_bank"
        library_mixed = call([str(probe), "--model", model, "--tokenizer", tokenizer,
                              "--stem", str(library_mixed_stem), "--bake-corpus", str(mixed_corpus)])
        library_mixed_ok = (library_mixed.returncode == 1
                            and "semb_bake_to_path: SEMB_INPUT_EMPTY (8)" in library_mixed.stderr)
        report.add("PASS" if library_mixed_ok else "FAIL",
                   "TE-317 the library itself still refuses the unfiltered batch (control)",
                   "semb_bake_to_path: SEMB_INPUT_EMPTY (8), unchanged" if library_mixed_ok else
                   f"RED: exit={library_mixed.returncode}; stderr={library_mixed.stderr[-300:]!r}; the library's "
                   "own all-or-nothing batch refusal must be untouched by the CLI's skip behaviour")
    else:
        report.add("BLOCKED", "verify untouched bank accepts", "CLI baseline triple was not produced")
        report.add("BLOCKED", "verify without --corpus is refused by name", "CLI baseline triple was not produced")
        report.add("BLOCKED", "verify edited corpus is refused by the corpus digest", "CLI baseline triple was not produced")
        report.add("BLOCKED", "C9 re-encode precondition: semb_bank_open accepts the tampered bank", "CLI baseline triple was not produced")
        report.add("BLOCKED", "C9 re-encode refusal: verify catches a bank bank-open accepts", "CLI baseline triple was not produced")
        report.add("BLOCKED", "verify same-size payload digest", "CLI baseline triple was not produced")
        report.add("BLOCKED", "plain-text corpus bakes with line-number ids", "CLI baseline triple was not produced")
        report.add("BLOCKED", "plain-text vectors byte-equal the JSONL bake", "CLI baseline triple was not produced")
        report.add("BLOCKED", "CLI inspect opens no encoder", "CLI baseline manifest was not produced")
        report.add("BLOCKED", "M-1 conflicting output modes refused by name (--hex --top 5)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "M-1 conflicting output modes refused by name (--raw --hex)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "M-1 conflicting output modes refused by name (--raw --top 5)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "M-1 conflicting output modes refused by name (--raw --stdin)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "S-2b a --stdin --top session ranks the validated bank after its files are replaced", "CLI baseline triple was not produced")
        report.add("BLOCKED", "an upper-case .JSONL corpus bakes with the ids its rows carry", "CLI baseline triple was not produced")
        report.add("BLOCKED", "an upper-case .JSONL corpus bakes vectors byte-equal the .jsonl bake", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 bake skips one empty document among good ones and reports it", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317/T-2 bake writes the skipped-document sidecar with exact content", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 bank rows equal the good documents alone (ids)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 bank rows equal the good documents alone (bytes)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 S-1 a clean re-bake at the same stem clears a stale sidecar", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 S-2 an empty-text document with a NUL byte in its id is refused, not skipped", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 S-2 an empty-text document with invalid UTF-8 in its id is refused, not skipped", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 T-1 an empty id with empty text is refused, not skipped", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 M-2 a duplicate id where one twin is empty still refuses SEMB_DOCUMENT_ID_DUPLICATE", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 F4 a sidecar write failure refuses, with the bank triple already valid", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-326 T-4(a) verify refuses a skip-collision duplicate, at the verify call site itself", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-326 T-4(b) an id containing a line break stays on exactly one stderr line", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-326 T-4(c)/N-2 a close-time write failure (/dev/full) refuses and clears the stale sidecar", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 a corpus where every document is empty still refuses (SEMB_INPUT_EMPTY, no leftovers)", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317/S-3 verify skips identically, reports it, and the bank verifies OK", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 round 3 a corpus with extra empty documents re-bakes identically and verifies OK", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 round 3 a copied bank (three files, no sidecar) verifies OK against its real corpus", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 round 3 a bank with a stale sidecar verifies by the digests alone", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 round 3 a bank with an unparseable sidecar verifies by the digests alone", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 round 3 N-4 a multi-defect corpus reports the library's own first refusal", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-326 M-4 a kept defect AFTER the colliding twin still outranks the duplicate refusal", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-326 R-1 an id containing U+2028 (LINE SEPARATOR) stays on exactly one stderr line", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-320 F5 verify refuses SEMB_INPUT_EMPTY on an all-empty corpus", "CLI baseline triple was not produced")
        report.add("BLOCKED", "TE-317 the library itself still refuses the unfiltered batch (control)", "CLI baseline triple was not produced")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
