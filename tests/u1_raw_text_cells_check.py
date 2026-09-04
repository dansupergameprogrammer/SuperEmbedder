"""tests/u1_raw_text_cells_check.py -- TE-92: the ctest driver for the frozen
raw-text slice's C++ cells (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1's
five verbs: semb_encoder_open / _close / _dims, semb_encode, semb_status_name).

WHY A DRIVER RATHER THAN TWO DIRECTLY-REGISTERED C++ TESTS. The two cells
(tests/u1_raw_text_contract_test.cpp, tests/u1_raw_text_parity_test.cpp)
link against symbols that do not exist at main@1a040a4, so their targets are
registered EXCLUDE_FROM_ALL and this driver builds them on demand: an
unresolved `semb_*` symbol is reported as RED-UNIMPLEMENTED BY NAME, with
the exact symbols missing, instead of breaking the whole tree's build or
leaving ctest with a "Not Run" -- the same red-first shape
tests/c12b_row_digest_check.py uses for an unbuilt instrument.

WHAT IT RUNS, once the targets link:

  MECHANISM (always): the synthetic model+tokenizer pair
  (tests/fixtures/regenerate_tokenizer_pair_fixture.py -- hidden 32, vocab
  384, context_cap 64, appended id 262, wrong id 263 = <|im_end|>), the
  contract cells K-01..K-14 and the parity cells P-00..P-05 over the 24-record
  mechanism corpus; the 128-vocab synthetic artifact (the C39/C40 fixture)
  is the --other-model for the mismatch cell.

  PRODUCT (when --model names the real Qwen3-Embedding-0.6B .sslm and
  --tokenizer the converter-emitted tokenizer artifact whose SHA-256 equals
  tests/fixtures/tokenizer/qwen3-embedding-0.6b-tokenizer.manifest.json):
  the same contract cells at dims 1024 / appended id 151643, and the parity
  cells over BOTH committed HF-derived populations -- the 239-document C12b
  corpus (tests/fixtures/c12b/corpus-239.jsonl) and the converter's 44-record
  golden pack (tests/fixtures/tokenizer/qwen3-embedding-0.6b-golden.json) --
  with wrong id 151645 (<|im_end|>, the D-SLM4731 confusion). Without them
  the product legs report MISSING PREREQUISITE, named.

Exit codes: 0 every evaluated cell PASS; 1 any FAIL, or RED-UNIMPLEMENTED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
PAIR_DIR_DEFAULT = REPO_ROOT / "build" / "_scratch" / "u1_pair"
TOKENIZER_MANIFEST = FIXTURES / "tokenizer" / "qwen3-embedding-0.6b-tokenizer.manifest.json"
GOLDEN_JSON = FIXTURES / "tokenizer" / "qwen3-embedding-0.6b-golden.json"
CORPUS_239 = FIXTURES / "c12b" / "corpus-239.jsonl"
FROZEN_SYMBOLS = ["semb_encoder_open", "semb_encoder_close", "semb_encoder_dims", "semb_encode", "semb_status_name"]
CANDIDATE_APPEND_ID = 151643
CANDIDATE_WRONG_ID = 151645  # <|im_end|>
CANDIDATE_DIMS = 1024


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def engine_source_args() -> List[str]:
    src = os.environ.get("SEMB_TEST_ENGINE_SOURCE")
    return ["--source", src] if src else []


def ensure_pair(pair_dir: Path) -> dict:
    manifest = pair_dir / "u1_pair.manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        fresh = all((pair_dir / name).exists() and sha256_file(pair_dir / name) == info["sha256"]
                    for name, info in m["files"].items())
        chk = FIXTURES / "tokenizer" / "u1-synthetic-checkpoint"
        fresh = fresh and m["checkpoint"]["tokenizer_json_sha256"] == sha256_file(chk / "tokenizer.json") \
            and m["mechanism_corpus_sha256"] == sha256_file(FIXTURES / "tokenizer" / "u1-mechanism-corpus.jsonl")
        if fresh:
            return m
    cmd = [sys.executable, str(FIXTURES / "regenerate_tokenizer_pair_fixture.py"), "--lock", "superslm.lock",
           "--out-dir", str(pair_dir)] + engine_source_args()
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    return json.loads(manifest.read_text(encoding="utf-8"))


def ensure_synthetic_128(path: Path) -> Path:
    if path.exists():
        return path
    cmd = [sys.executable, str(FIXTURES / "regenerate_synthetic_artifact.py"), "--lock", "superslm.lock",
           "--out", str(path)] + engine_source_args()
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    return path


def build_targets(cmake: str, build_dir: Path, targets: List[str]) -> Tuple[bool, List[str], str]:
    """Returns (built, unresolved frozen symbols, output tail)."""
    proc = subprocess.run([cmake, "--build", str(build_dir), "--target", *targets],
                          cwd=REPO_ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    unresolved = []
    for sym in FROZEN_SYMBOLS:
        # MSVC: LNK2019 unresolved external symbol semb_encoder_open referenced in ...
        # lld-link/clang: undefined symbol: semb_encoder_open
        # GNU ld: undefined reference to `semb_encoder_open'
        if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?" + sym + r"\b", out):
            unresolved.append(sym)
    return proc.returncode == 0, unresolved, "\n".join(out.splitlines()[-25:])


def find_exe(build_dir: Path, name: str) -> Optional[Path]:
    for cand in (build_dir / "tests" / f"{name}.exe", build_dir / "tests" / name,
                 build_dir / f"{name}.exe", build_dir / name):
        if cand.exists():
            return cand
    hits = list(build_dir.rglob(f"{name}.exe")) + [p for p in build_dir.rglob(name) if p.is_file()]
    return hits[0] if hits else None


def write_hex_tsv(records: List[Tuple[str, List[int], str]], path: Path, header: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# label\tcontent_ids\ttext_utf8_hex -- " + header + "\n")
        for label, ids, text in records:
            f.write("%s\t%s\t%s\n" % (label, ",".join(str(x) for x in ids), text.encode("utf-8").hex()))


def real_populations(out_dir: Path) -> List[Tuple[str, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pops = []
    recs = []
    for line in CORPUS_239.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        recs.append((d["label"], d["content_ids"], d["text"]))
    p = out_dir / "corpus239_expected_ids.tsv"
    write_hex_tsv(recs, p, "HF content_ids from tests/fixtures/c12b/corpus-239.jsonl (tools/c12b/mint_c12b_corpus.py)")
    pops.append(("corpus-239", p))
    g = json.loads(GOLDEN_JSON.read_text(encoding="utf-8"))
    recs = [("g-%03d" % i, r["ids"], r["text"]) for i, r in enumerate(g["records"])]
    p = out_dir / "golden44_expected_ids.tsv"
    write_hex_tsv(recs, p, "HF ids (add_special_tokens=False) from the converter's golden pack "
                           "tests/fixtures/tokenizer/qwen3-embedding-0.6b-golden.json")
    pops.append(("golden-44", p))
    return pops


class Table:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []
        self.failed = False

    def add(self, leg: str, state: str, observed: str) -> None:
        if state in ("FAIL", "RED-UNIMPLEMENTED"):
            self.failed = True
        self.rows.append((leg, state, observed))
        print(f"[{state}] {leg}: {observed}")
        sys.stdout.flush()


def run_cells(exe: Path, args: List[str], leg: str, table: Table) -> None:
    t0 = time.perf_counter()
    proc = subprocess.run([str(exe), *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    elapsed = time.perf_counter() - t0
    print(proc.stdout)
    if proc.stderr.strip():
        print(proc.stderr)
    n_pass = len(re.findall(r"^\[PASS\]", proc.stdout, re.M))
    n_fail = len(re.findall(r"^\[FAIL\]", proc.stdout, re.M))
    n_missing = len(re.findall(r"^\[MISSING PREREQUISITE\]", proc.stdout, re.M))
    ok = proc.returncode == 0 and n_fail == 0 and n_pass > 0
    table.add(leg, "PASS" if ok else "FAIL",
              f"exit {proc.returncode}; {n_pass} PASS, {n_fail} FAIL, {n_missing} MISSING PREREQUISITE in {elapsed:.1f}s")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", default="cmake")
    ap.add_argument("--model", default=os.environ.get("SEMB_C12B_MODEL", ""))
    ap.add_argument("--tokenizer", default=os.environ.get("SEMB_U1_TOKENIZER", ""))
    ap.add_argument("--pair-dir", default=str(PAIR_DIR_DEFAULT))
    ap.add_argument("--limit", type=int, default=0, help="cap the real populations' rows (0 = all)")
    ap.add_argument("--mutant-rows", type=int, default=8)
    ap.add_argument("--skip-build", action="store_true", help="assume the two targets are already built")
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    table = Table()

    # ---- fixtures -------------------------------------------------------------------------------
    try:
        pair = ensure_pair(Path(args.pair_dir))
        pair_dir = Path(args.pair_dir)
        other_model = ensure_synthetic_128(REPO_ROOT / "build" / "_scratch" / "synthetic_te62_c39.sslm")
    except Exception as ex:  # noqa: BLE001
        table.add("F0 fixtures (synthetic pair + 128-vocab artifact)", "FAIL", f"{type(ex).__name__}: {ex}")
        return 1
    table.add("F0 fixtures", "PASS", f"pair at {pair_dir} (engine {pair['engine_tag']}); other model {other_model.name}")

    # ---- build the two cells ---------------------------------------------------------------------
    targets = ["u1_raw_text_contract_test", "u1_raw_text_parity_test"]
    if not args.skip_build:
        built, unresolved, tail = build_targets(args.cmake_executable, build_dir, targets)
        if not built:
            if unresolved:
                table.add("B0 link the frozen raw-text cells", "RED-UNIMPLEMENTED",
                          "the frozen sec 3.1 verbs do not exist in the product: unresolved " + ", ".join(unresolved))
                print("\nu1_raw_text_cells_check: RED -- the five frozen verbs (" + ", ".join(FROZEN_SYMBOLS) +
                      ") are not defined by `superembedder` at this tip; every cell below is red-unimplemented, "
                      "not a verified pass:\n  K-01..K-14 (tests/u1_raw_text_contract_test.cpp)\n"
                      "  P-00..P-05 (tests/u1_raw_text_parity_test.cpp)\nlinker output tail:\n" + tail)
            else:
                table.add("B0 build the frozen raw-text cells", "FAIL", "build failed for a reason other than the "
                          "missing frozen symbols:\n" + tail)
            return 1
        table.add("B0 build the frozen raw-text cells", "PASS", "both targets linked")
    contract = find_exe(build_dir, "u1_raw_text_contract_test")
    parity = find_exe(build_dir, "u1_raw_text_parity_test")
    if not contract or not parity:
        table.add("B1 locate the built cells", "FAIL", f"contract={contract} parity={parity}")
        return 1

    # ---- the real tokenizer artifact, if configured ---------------------------------------------
    real_tokenizer = ""
    if args.tokenizer:
        tok = Path(args.tokenizer)
        if not tok.exists():
            table.add("T0 the real tokenizer artifact", "FAIL", f"--tokenizer {tok} does not exist")
        elif not TOKENIZER_MANIFEST.exists():
            table.add("T0 the real tokenizer artifact", "FAIL", f"no manifest at {TOKENIZER_MANIFEST}")
        else:
            want = json.loads(TOKENIZER_MANIFEST.read_text(encoding="utf-8"))["artifact"]
            got = sha256_file(tok)
            if got != want["sha256"] or tok.stat().st_size != want["bytes"]:
                table.add("T0 the real tokenizer artifact matches its committed manifest", "FAIL",
                          f"sha256={got} bytes={tok.stat().st_size}; manifest {want['sha256']} / {want['bytes']}")
            else:
                real_tokenizer = str(tok)
                table.add("T0 the real tokenizer artifact matches its committed manifest", "PASS",
                          f"{tok.name} sha256={got[:16]}... bytes={want['bytes']}")

    # ---- MECHANISM: the synthetic pair ----------------------------------------------------------
    pair_model = str(pair_dir / "u1_pair_model.sslm")
    pair_tok = str(pair_dir / "u1_pair_tokenizer.sslm")
    mech_args = ["--model", pair_model, "--tokenizer", pair_tok, "--append-id", str(pair["appended_token_id"]),
                 "--dims", "32", "--context-cap", "64", "--other-model", str(other_model),
                 "--truncated-tokenizer", str(pair_dir / "u1_pair_tokenizer.truncated.sslm")]
    if real_tokenizer:
        mech_args += ["--other-tokenizer", real_tokenizer]
    run_cells(contract, mech_args, "M1 contract cells K-01..K-14 on the synthetic pair", table)
    run_cells(parity, ["--model", pair_model, "--tokenizer", pair_tok, "--append-id", str(pair["appended_token_id"]),
                       "--wrong-append-id", "263", "--expected-ids", str(pair_dir / "u1_mechanism_expected_ids.tsv"),
                       "--mutant-rows", "64"],
              "M2 parity cells P-00..P-05 on the synthetic pair (24-record mechanism corpus)", table)

    # ---- PRODUCT: the real pair -------------------------------------------------------------------
    if not args.model or not real_tokenizer:
        table.add("R1 product cells on Qwen3-Embedding-0.6B", "MISSING PREREQUISITE",
                  "needs --model (SEMB_C12B_MODEL) and a manifest-matching --tokenizer (SEMB_U1_TOKENIZER); "
                  "neither artifact is committed")
    elif not Path(args.model).exists():
        table.add("R1 product cells on Qwen3-Embedding-0.6B", "FAIL", f"--model {args.model} does not exist")
    else:
        scratch = build_dir / "_u1_real"
        pops = real_populations(scratch)
        run_cells(contract, ["--model", args.model, "--tokenizer", real_tokenizer, "--append-id", str(CANDIDATE_APPEND_ID),
                             "--dims", str(CANDIDATE_DIMS), "--other-model", pair_model,
                             "--truncated-tokenizer", str(scratch / "qwen3_tokenizer.truncated.sslm")],
                  "R1 contract cells K-01..K-14 on the real pair", table)
        for name, tsv in pops:
            extra = ["--limit", str(args.limit)] if args.limit else []
            run_cells(parity, ["--model", args.model, "--tokenizer", real_tokenizer, "--append-id", str(CANDIDATE_APPEND_ID),
                               "--wrong-append-id", str(CANDIDATE_WRONG_ID), "--expected-ids", str(tsv),
                               "--mutant-rows", str(args.mutant_rows), *extra],
                      f"R2 parity cells P-00..P-05 on the real pair, population {name}", table)

    print("\nu1_raw_text_cells_check summary:")
    for leg, state, _ in table.rows:
        print(f"  {state:22s} {leg}")
    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
