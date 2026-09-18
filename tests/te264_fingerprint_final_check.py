"""U1 Slice 7 red tests for the final fingerprint (TE-264; steps 3, 4 and 5 of
`Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.7).

Every cell bakes a two-document bank through `semb_bake_to_path` on one
encoder handle (tests/te264_fingerprint_probe.cpp) and reads the manifest's
clear components (`<stem>.semb.json`).  One cell per step, selected with
`--cell`, so each step's red test turns green at its own step:

  template     step 3.  `template_sha256` in the manifest equals
               SHA-256(LE64(len f) || f || LE64(len p) || p || LE64(len e) || e)
               with f the empty PS-N document frame, p the query-prefix
               literal of plan sec 2.1 and e the end-token literal
               `<|endoftext|>` of plan sec 3.2 -- all three typed here.
  epoch        step 4 (a).  `certification_epoch` in the manifest equals the
               SHA-256 of `docs/certified-builds.json`'s exact bytes, read by
               this test from the repository file.
  epoch-edit   step 4 (e), C42 (d)'s construction.  With the build current,
               the committed document is edited by one byte (one
               `pairwiseProofs[].evidence` string, same length, still valid
               JSON), the probe is re-run WITHOUT rebuilding, and cell (a)'s
               comparison must read RED against the edited file while the
               epoch still equals the SHA-256 of the bytes the build compiled
               in.  The file is restored byte for byte.
  untagged     step 5.  `semb_fingerprint_of` and the fingerprint
               `semb_encode` returns both equal the manifest's
               `encoder_fingerprint` (the untagged five-field digest) of the
               bank the same encoder baked, and neither begins with the eight
               bytes `SEMBP001`.

Oracles: the literals are typed from the plan, and the certification
document's bytes are read from the repository; no expected value is taken
from the product.  The artifacts are the synthetic mechanism pair
(tests/u1_raw_text_cells_check.py's `ensure_pair`) unless --model and
--tokenizer are given; `template_sha256` and `certification_epoch` do not
depend on the artifacts.

Exit codes: 0 the cell PASSES; 1 it FAILS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

CERT_DOC = ROOT / "docs" / "certified-builds.json"

# Plan sec 2.1 (the query-side instruction prefix, character for character)
# and plan sec 3.2 (the compiled-in end-token literal).  PS-N's document
# frame is the empty byte string (plan sec 3.3's template row).
QUERY_PREFIX = b"Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
END_TOKEN = b"<|endoftext|>"
DOCUMENT_FRAME = b""
PROVISIONAL_TAG = b"SEMBP001"


def le64(n: int) -> bytes:
    return struct.pack("<Q", n)


def expected_template() -> str:
    stream = b"".join(le64(len(x)) + x for x in (DOCUMENT_FRAME, QUERY_PREFIX, END_TOKEN))
    return hashlib.sha256(stream).hexdigest()


def two_literal_template() -> str:
    """Diagnostic only: the pre-D-8 form (frame and prefix, no end token),
    used to name the reason a red reading is red."""
    stream = b"".join(le64(len(x)) + x for x in (DOCUMENT_FRAME, QUERY_PREFIX))
    return hashlib.sha256(stream).hexdigest()


def find_exe(build: Path, name: str) -> Path | None:
    for cand in (build / "tests" / f"{name}.exe", build / "tests" / name, build / f"{name}.exe", build / name):
        if cand.exists():
            return cand
    return None


class Report:
    def __init__(self) -> None:
        self.failed = False

    def add(self, ok: bool, cell: str, detail: str) -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")
        sys.stdout.flush()
        self.failed |= not ok


def run_probe(probe: Path, model: str, tokenizer: str, stem: Path) -> tuple[dict | None, dict, str]:
    """Runs the probe; returns (manifest or None, printed values, diagnostic)."""
    for suffix in (".wvbank.json", ".wvbank.bin", ".semb.json"):
        Path(str(stem) + suffix).unlink(missing_ok=True)
    proc = subprocess.run([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(stem)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=900)
    values = dict(re.findall(r"^([A-Z_]+)=(\S+)$", proc.stdout, re.M))
    refusals = [l for l in proc.stderr.splitlines() if re.match(r"^semb_\w+: SEMB_\w+ \(\d+\)$", l)]
    manifest_path = Path(str(stem) + ".semb.json")
    if proc.returncode != 0 or not manifest_path.exists():
        return None, values, f"probe exit={proc.returncode}; refusals={refusals}"
    return json.loads(manifest_path.read_text(encoding="utf-8")), values, ""


def edit_one_evidence_byte(original: bytes) -> bytes | None:
    """One byte of the first `pairwiseProofs[].evidence` string changed, same
    length and still valid JSON: the first ASCII letter of that string has
    its case flipped.  None when the document carries no such string."""
    m = re.search(rb'"evidence"\s*:\s*"([^"\\]*)"', original)
    if not m:
        return None
    for i in range(m.start(1), m.end(1)):
        c = original[i:i + 1]
        if c.isalpha():
            return original[:i] + c.swapcase() + original[i + 1:]
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--cell", required=True, choices=["template", "epoch", "epoch-edit", "untagged"])
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args(argv)
    report = Report()
    scratch = args.build_dir.resolve() / "_scratch" / "te264" / args.cell
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)

    backup = args.build_dir.resolve() / "_scratch" / "te264" / "certified-builds.json.backup"
    if backup.exists():
        # A prior epoch-edit run that did not reach its restore: put the
        # committed bytes back before anything reads the document.
        shutil.copyfile(backup, CERT_DOC)
        backup.unlink()
        print(f"[NOTE] restored {CERT_DOC} from a stale backup left by an interrupted epoch-edit run")

    model, tokenizer = args.model, args.tokenizer
    if not model or not tokenizer:
        import u1_raw_text_cells_check as u1raw
        pair_dir = u1raw.PAIR_DIR_DEFAULT
        u1raw.ensure_pair(pair_dir)
        model, tokenizer = str(pair_dir / "u1_pair_model.sslm"), str(pair_dir / "u1_pair_tokenizer.sslm")

    built = subprocess.run([args.cmake_executable, "--build", str(args.build_dir), "--target", "te264_fingerprint_probe"],
                           cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=900)
    probe = find_exe(args.build_dir, "te264_fingerprint_probe")
    if built.returncode != 0 or probe is None:
        report.add(False, f"{args.cell}: probe build", (built.stdout + built.stderr)[-1500:])
        return 1

    stem = scratch / "probe"
    manifest, values, why = run_probe(probe, model, tokenizer, stem)
    if manifest is None:
        report.add(False, f"{args.cell}: probe bake", why)
        return 1

    if args.cell == "template":
        want, got = expected_template(), manifest.get("template_sha256")
        note = ""
        if got == two_literal_template():
            note = "; the manifest value is the two-literal form (frame, prefix) with no end token"
        report.add(got == want,
                   "step 3: manifest template_sha256 equals the independent three-literal recomputation "
                   "(empty PS-N frame, plan sec 2.1 query prefix, plan sec 3.2 end token)",
                   f"expected={want} manifest={got}{note}")

    elif args.cell == "epoch":
        got = manifest.get("certification_epoch")
        # Diagnostic only, never the oracle: the U1 pending sentinel the
        # provisional tree hashes in place of the document.
        sentinel = hashlib.sha256(b"SEMB-CERTIFIED-BUILDS-PENDING-AFTER-U1-RAW-ENCODER-SLICE").hexdigest()
        note = "; the manifest value is SHA-256 of the pending sentinel" if got == sentinel else ""
        if not CERT_DOC.exists():
            report.add(False, "step 4 (a): manifest certification_epoch equals SHA-256 of docs/certified-builds.json",
                       f"docs/certified-builds.json is absent from the repository; manifest certification_epoch={got}{note}")
        else:
            want = hashlib.sha256(CERT_DOC.read_bytes()).hexdigest()
            report.add(got == want,
                       "step 4 (a): manifest certification_epoch equals SHA-256 of docs/certified-builds.json",
                       f"expected={want} manifest={got}{note}")

    elif args.cell == "epoch-edit":
        cell = "step 4 (e), C42 (d): a post-build edit of docs/certified-builds.json makes (a) read RED"
        if not CERT_DOC.exists():
            report.add(False, cell, "docs/certified-builds.json is absent; the construction has no document to edit")
            return 1
        original = CERT_DOC.read_bytes()
        original_sha = hashlib.sha256(original).hexdigest()
        precondition = manifest.get("certification_epoch") == original_sha
        report.add(precondition, "step 4 (e) precondition: (a) is green on the unedited document",
                   f"expected={original_sha} manifest={manifest.get('certification_epoch')}")
        edited = edit_one_evidence_byte(original)
        if edited is None:
            report.add(False, cell, "the document carries no pairwiseProofs[].evidence string with a letter to edit")
            return 1
        try:
            json.loads(edited.decode("utf-8"))
            valid_json = True
        except ValueError:
            valid_json = False
        shutil.copyfile(CERT_DOC, backup)
        try:
            CERT_DOC.write_bytes(edited)
            edited_manifest, _, why2 = run_probe(probe, model, tokenizer, scratch / "probe_after_edit")
        finally:
            CERT_DOC.write_bytes(original)
            restored = hashlib.sha256(CERT_DOC.read_bytes()).hexdigest() == original_sha
            if restored:
                backup.unlink(missing_ok=True)
        report.add(restored, "step 4 (e): docs/certified-builds.json restored byte for byte",
                   f"sha256={original_sha}")
        if edited_manifest is None:
            report.add(False, cell, f"probe after the edit: {why2}")
        else:
            epoch = edited_manifest.get("certification_epoch")
            edited_sha = hashlib.sha256(edited).hexdigest()
            report.add(precondition and valid_json and len(edited) == len(original)
                       and epoch != edited_sha and epoch == original_sha, cell,
                       f"edit same-length={len(edited) == len(original)} valid-json={valid_json}; "
                       f"epoch after edit={epoch}; SHA-256(edited file)={edited_sha}; "
                       f"SHA-256(compiled-in bytes)={original_sha}")

    elif args.cell == "untagged":
        want = manifest.get("encoder_fingerprint")
        of, enc = values.get("FINGERPRINT_OF"), values.get("ENCODE_FINGERPRINT")
        tag_hex = PROVISIONAL_TAG.hex()
        report.add(of == want and enc == want,
                   "step 5: semb_fingerprint_of and semb_encode's fingerprint equal the manifest's untagged "
                   "encoder_fingerprint of the bank the same encoder baked",
                   f"manifest={want} fingerprint_of={of} encode={enc}")
        report.add(bool(of) and bool(enc) and not of.startswith(tag_hex) and not enc.startswith(tag_hex),
                   "step 5: neither ABI fingerprint begins with the eight bytes SEMBP001",
                   f"first 8 bytes: fingerprint_of={(of or '')[:16]} encode={(enc or '')[:16]} (SEMBP001={tag_hex})")

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
