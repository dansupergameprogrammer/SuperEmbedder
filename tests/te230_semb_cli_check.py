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
    refused as `SEMB_CORPUS_DIGEST_MISMATCH` -- a PROPOSED status (D-SLM6631)
    that is not yet in the frozen `semb_status` enum and is filed for the
    planner to ratify or rename;
  * a plain-text corpus is one document per line with ids = line numbers;
    the numbering base the plan leaves open is pinned to ZERO, the smallest
    reading (D-SLM6632): the first line's id is "0", as a decimal string;
  * `query --stdin` is a session: one line's result must arrive before the
    next line is written, not after standard input closes;
  * `query --raw` writes exactly `dims * 4` float32 bytes, unpadded.
These are the smallest machine-readable forms that let this test compare the
CLI to the C ABI without parsing presentation text.  The planner owns their
ratification; this file pins the test-author choice until then.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
        self.failed |= state in {"FAIL", "RED-UNIMPLEMENTED", "BLOCKED"}


def call(args: list[str], stdin: str | None = None, timeout: int = 420) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


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


def expect_status(report: Report, cell: str, proc: subprocess.CompletedProcess[str], status: str) -> None:
    text = proc.stdout + proc.stderr
    report.add("PASS" if proc.returncode != 0 and status in text else "FAIL", cell,
               f"exit={proc.returncode}; expected {status}; stderr={proc.stderr[-400:]!r}")


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
            generated = call([sys.executable, str(fixture), "--lock", "superslm.lock", "--out-dir", str(pair)], timeout=480)
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
    else:
        report.add("BLOCKED", "CLI one-shot bytes equal library", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin one handle", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin session serves the first query before input closes", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin session serves the second query after input closes", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI query --raw writes the vector bytes", "CLI baseline triple and library vector are required")
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
        mismatch_ok = mismatch.returncode != 0 and "SEMB_CORPUS_DIGEST_MISMATCH" in (mismatch.stdout + mismatch.stderr)
        report.add("PASS" if mismatch_ok else "FAIL", "verify edited corpus is refused by the corpus digest",
                   "a corpus that is not the one baked is refused as SEMB_CORPUS_DIGEST_MISMATCH (D-SLM6631, proposed)" if mismatch_ok else
                   f"RED: the edited corpus must be refused naming the corpus digest; exit={mismatch.returncode}; "
                   f"{(mismatch.stdout + mismatch.stderr)[-200:]!r}")
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
        plain = scratch / "plain_corpus.txt"; plain.write_text("\n".join(plain_lines) + "\n", encoding="utf-8")
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
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
