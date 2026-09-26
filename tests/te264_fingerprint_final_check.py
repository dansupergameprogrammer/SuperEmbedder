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
  epoch        step 4 (a), re-keyed by U2-3 item 9 (te267 P:1003-1006,
               P:1136-1137, P:1156-1158).  `certification_epoch` in the
               manifest is the identity file's digest in the verdict's form:
               SHA-256 of `docs/certification-identity.json`'s exact bytes
               when the build resolves to a certified cell, else SHA-256 of
               "SEMB-UNCERTIFIED" || NUL || those bytes.  The verdict is
               decided HERE, independently of the product's own verdict, by
               the plan's matching rule (P:1000-1002, P:1179-1181, the
               descriptor fields P:1225-1227): exactly one `builds[]` entry of
               the committed list whose nine descriptor fields equal the
               manifest's `build_descriptor` and whose `cpuTier` equals its
               `machine_tier`, paired once with every other cell under one
               rowDigest.  The manifest's `certified_cell` must name the same
               verdict.  The identity bytes are read from the repository file.
  epoch-edit   step 4 (e), C42 (d)'s construction, gaining the identity-file
               edit beside the list edit (P:1158-1159).  With the build
               current, the probe is re-run WITHOUT rebuilding twice: once
               with one byte of the committed list edited (one
               `pairwiseProofs[].evidence` letter's case, same length, valid
               JSON) -- the list is read, never digested (P:1007-1008), so
               the epoch is unchanged; and once with one byte of the identity
               file edited (one letter of its `product` value) -- the epoch
               still equals the verdict form over the compiled-in bytes, so
               (a)'s comparison reads RED against the edited file.  Both files
               are restored byte for byte.
  untagged     step 5.  `semb_fingerprint_of` and the fingerprint
               `semb_encode` returns both equal the manifest's
               `encoder_fingerprint` (the untagged five-field digest) of the
               bank the same encoder baked, and neither begins with the eight
               bytes `SEMBP001`.

Oracles: the literals are typed from the plan, and the certification
files' bytes are read from the repository; no expected value is taken from
the product.  The epoch cells read the manifest's `build_descriptor` and
`machine_tier` as the build's reported identity and decide the verdict from
the committed list themselves.  The artifacts are the synthetic mechanism pair
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
IDENTITY_DOC = ROOT / "docs" / "certification-identity.json"
# te267 P:1005: the uncertified epoch's prefix, typed from the plan: the ASCII
# bytes and one NUL, then the identity file's bytes.
UNCERTIFIED_PREFIX = b"SEMB-UNCERTIFIED\0"
UNCERTIFIED_CELL = "uncertified"
# te267 P:1225-1227: the descriptor fields a cell is matched on, each by
# string equality.
DESCRIPTOR_FIELDS = ("os", "isa", "toolchain", "stdlib", "configuration", "buildSystem", "dispatch",
                     "compileFlags", "engineFlags")

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


def fully_paired(cell: str, cells: set, proofs: list) -> bool:
    """te267 P:1179-1181: the cell has exactly one pair with every other cell,
    and every such pair carries one rowDigest."""
    partners: dict[str, int] = {}
    digests = set()
    for p in proofs:
        if not isinstance(p, dict) or cell not in (p.get("a"), p.get("b")):
            continue
        other = p.get("b") if p.get("a") == cell else p.get("a")
        if other == cell or other not in cells or not p.get("rowDigest"):
            return False
        digests.add(p.get("rowDigest"))
        partners[other] = partners.get(other, 0) + 1
    return len(digests) <= 1 and all(partners.get(o) == 1 for o in cells - {cell})


def decide_cell(list_bytes: bytes, manifest: dict) -> tuple[str | None, str]:
    """The verdict by the plan's rule over the committed list and the
    manifest's reported descriptor and tier; returns (cell id, or
    UNCERTIFIED_CELL; or None when the manifest carries no descriptor) and a
    diagnostic."""
    descriptor, tier = manifest.get("build_descriptor"), manifest.get("machine_tier")
    if not isinstance(descriptor, dict) or not isinstance(tier, str):
        return None, f"manifest build_descriptor={descriptor!r} machine_tier={tier!r}"
    try:
        doc = json.loads(list_bytes.decode("utf-8"))
        builds, proofs = doc["builds"], doc["pairwiseProofs"]
    except (ValueError, KeyError, TypeError) as exc:
        return UNCERTIFIED_CELL, f"the list does not parse as a list: {exc}"
    cells = {b.get("id") for b in builds if isinstance(b, dict)}
    matched = [b.get("id") for b in builds if isinstance(b, dict) and b.get("cpuTier") == tier
               and all(isinstance(b.get(f), str) and b.get(f) == descriptor.get(f) for f in DESCRIPTOR_FIELDS)
               and fully_paired(b.get("id"), cells, proofs)]
    why = f"descriptor={json.dumps(descriptor, sort_keys=True)} tier={tier}; matching cells={matched}"
    return (matched[0] if len(matched) == 1 else UNCERTIFIED_CELL), why


def epoch_for(cell: str, identity_bytes: bytes) -> str:
    """te267 P:1003-1006: the identity file's digest in the verdict's form."""
    if cell == UNCERTIFIED_CELL:
        return hashlib.sha256(UNCERTIFIED_PREFIX + identity_bytes).hexdigest()
    return hashlib.sha256(identity_bytes).hexdigest()


def edit_one_identity_byte(original: bytes) -> bytes | None:
    """One byte of the identity file's `product` value changed, same length
    and still valid JSON: its first ASCII letter has its case flipped."""
    m = re.search(rb'"product"\s*:\s*"([^"\\]*)"', original)
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

    backups = {doc: args.build_dir.resolve() / "_scratch" / "te264" / f"{doc.name}.backup"
               for doc in (CERT_DOC, IDENTITY_DOC)}
    for doc, backup in backups.items():
        if backup.exists():
            # A prior epoch-edit run that did not reach its restore: put the
            # committed bytes back before anything reads the document.
            shutil.copyfile(backup, doc)
            backup.unlink()
            print(f"[NOTE] restored {doc} from a stale backup left by an interrupted epoch-edit run")

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
        cell = ("step 4 (a), U2-3 item 9: manifest certification_epoch is the identity file's digest in the "
                "verdict's form")
        if not IDENTITY_DOC.exists() or not CERT_DOC.exists():
            report.add(False, cell, f"identity file present={IDENTITY_DOC.exists()} list present={CERT_DOC.exists()}; "
                                    f"manifest certification_epoch={got}")
        else:
            identity = IDENTITY_DOC.read_bytes()
            decided, why = decide_cell(CERT_DOC.read_bytes(), manifest)
            if decided is None:
                report.add(False, cell, f"the manifest carries no descriptor to decide the verdict from: {why}")
            else:
                want = epoch_for(decided, identity)
                other = epoch_for(UNCERTIFIED_CELL if decided != UNCERTIFIED_CELL else "member", identity)
                note = "; the manifest carries the OTHER form's value" if got == other else ""
                if got == hashlib.sha256(CERT_DOC.read_bytes()).hexdigest():
                    note = "; the manifest value is SHA-256 of the whole list (the pre-U2-3 epoch)"
                report.add(got == want, cell, f"verdict={decided} ({why}); expected={want} manifest={got}{note}")
                reported = manifest.get("certified_cell")
                report.add(reported == decided,
                           "step 4 (a), U2-3 item 1: the manifest's certified_cell names the verdict the plan's "
                           "matching rule gives",
                           f"decided={decided} manifest certified_cell={reported!r}")

    elif args.cell == "epoch-edit":
        cell = ("step 4 (e), C42 (d): post-build edits of the list and of the identity file leave the compiled-in "
                "epoch, and make (a) read RED against the edited identity file")
        if not CERT_DOC.exists() or not IDENTITY_DOC.exists():
            report.add(False, cell, f"list present={CERT_DOC.exists()} identity file present={IDENTITY_DOC.exists()}; "
                                    f"the construction has no document to edit")
            return 1
        originals = {doc: doc.read_bytes() for doc in (CERT_DOC, IDENTITY_DOC)}
        list_bytes, identity = originals[CERT_DOC], originals[IDENTITY_DOC]
        decided, why = decide_cell(list_bytes, manifest)
        if decided is None:
            report.add(False, cell, f"the manifest carries no descriptor to decide the verdict from: {why}")
            return 1
        compiled_epoch = epoch_for(decided, identity)
        precondition = manifest.get("certification_epoch") == compiled_epoch
        report.add(precondition, "step 4 (e) precondition: (a) is green on the unedited files",
                   f"verdict={decided}; expected={compiled_epoch} manifest={manifest.get('certification_epoch')}")
        edits = {CERT_DOC: edit_one_evidence_byte(list_bytes), IDENTITY_DOC: edit_one_identity_byte(identity)}
        for doc, edited in edits.items():
            if edited is None:
                report.add(False, cell, f"{doc.name} carries no string this construction edits")
                return 1
        for doc, edited in edits.items():
            try:
                json.loads(edited.decode("utf-8"))
                valid_json = True
            except ValueError:
                valid_json = False
            original = originals[doc]
            shutil.copyfile(doc, backups[doc])
            try:
                doc.write_bytes(edited)
                edited_manifest, _, why2 = run_probe(probe, model, tokenizer, scratch / f"probe_after_{doc.stem}_edit")
            finally:
                doc.write_bytes(original)
                restored = doc.read_bytes() == original
                if restored:
                    backups[doc].unlink(missing_ok=True)
            report.add(restored, f"step 4 (e): {doc.name} restored byte for byte",
                       f"sha256={hashlib.sha256(original).hexdigest()}")
            shape = f"edit same-length={len(edited) == len(original)} valid-json={valid_json}"
            if edited_manifest is None:
                report.add(False, f"{cell} [{doc.name}]", f"probe after the edit: {why2}")
                continue
            epoch = edited_manifest.get("certification_epoch")
            if doc == CERT_DOC:
                # The list is read and never digested (P:1007-1008): the epoch
                # neither follows the edit nor moves.
                report.add(precondition and valid_json and len(edited) == len(original)
                           and epoch == compiled_epoch, f"{cell} [list edit]",
                           f"{shape}; epoch after edit={epoch}; compiled-in epoch={compiled_epoch}; "
                           f"SHA-256(edited list)={hashlib.sha256(edited).hexdigest()}")
            else:
                edited_epoch = epoch_for(decided, edited)
                report.add(precondition and valid_json and len(edited) == len(original)
                           and epoch == compiled_epoch and epoch != edited_epoch, f"{cell} [identity edit]",
                           f"{shape}; epoch after edit={epoch}; verdict form over the edited file={edited_epoch}; "
                           f"over the compiled-in bytes={compiled_epoch}")

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
