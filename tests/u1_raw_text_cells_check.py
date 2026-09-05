"""tests/u1_raw_text_cells_check.py -- TE-92, re-entered at TE-94 (D-SLM6314
resolution): the ctest driver for the frozen raw-text slice's C++ cells
(`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1's five verbs: semb_encoder_open /
_close / _dims, semb_encode, semb_status_name).

WHY A DRIVER RATHER THAN TWO DIRECTLY-REGISTERED C++ TESTS. The two cells
(tests/u1_raw_text_contract_test.cpp, tests/u1_raw_text_parity_test.cpp)
link against symbols that did not exist at main@1a040a4, so their targets are
registered EXCLUDE_FROM_ALL and this driver builds them on demand: an
unresolved `semb_*` symbol is reported as RED-UNIMPLEMENTED BY NAME, with
the exact symbols missing, instead of breaking the whole tree's build or
leaving ctest with a "Not Run" -- the same red-first shape
tests/c12b_row_digest_check.py uses for an unbuilt instrument.

WHAT IT RUNS, once the targets link:

  MECHANISM (always): the synthetic model+tokenizer pair
  (tests/fixtures/regenerate_tokenizer_pair_fixture.py -- hidden 32, vocab
  384, context_cap 64, <|endoftext|> = 262, wrong id 263 = <|im_end|>, plus
  the no-<|endoftext|> tokenizer variant for the absent-template cell), the
  contract cells K-01..K-17 and the parity cells P-00..P-05 over the 24-record
  mechanism corpus; the 128-vocab synthetic artifact (the C39/C40 fixture)
  is the --other-model for the join-mismatch cell.

  PRODUCT (when --model names the real Qwen3-Embedding-0.6B .sslm and
  --tokenizer the converter-emitted tokenizer artifact whose SHA-256 equals
  tests/fixtures/tokenizer/qwen3-embedding-0.6b-tokenizer.manifest.json):
  the same contract cells at dims 1024 and the parity cells over BOTH
  committed HF-derived populations -- the 239-document C12b corpus
  (tests/fixtures/c12b/corpus-239.jsonl) and the converter's 44-record
  golden pack (tests/fixtures/tokenizer/qwen3-embedding-0.6b-golden.json) --
  with the interim oracle's end token 151643 and wrong id 151645 (<|im_end|>,
  the D-SLM4731 confusion). Without them the product legs report MISSING
  PREREQUISITE, named.

  DIAGNOSTIC (--diag-legacy-layout, never the verdict): builds the same two
  cells with SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER -- the retired 496d036
  seven-member semb_config -- and runs them on the synthetic pair, so that
  against a product still carrying that layout (where every open otherwise
  refuses SEMB_STRUCT_SIZE_MISMATCH, P-1) each cell's OWN red is visible and
  attributable. Reported as [DIAG] rows; they never change the exit code.

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
LITERAL_SPECIAL_RECORD = ("u1-literal-endoftext", [CANDIDATE_APPEND_ID], "<|endoftext|>")
PAIR_FILES = ["u1_pair_model.sslm", "u1_pair_tokenizer.sslm", "u1_pair_tokenizer_no_endoftext.sslm",
              "u1_mechanism_expected_ids.tsv"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def engine_source_args() -> List[str]:
    src = os.environ.get("SEMB_TEST_ENGINE_SOURCE")
    return ["--source", src] if src else []


def pair_is_fresh(m: dict, pair_dir: Path) -> bool:
    if m.get("schema") != "semb_u1_pair_fixture_manifest_v2":
        return False
    if any(name not in m.get("files", {}) for name in PAIR_FILES):
        return False
    if not all((pair_dir / name).exists() and sha256_file(pair_dir / name) == info["sha256"]
               for name, info in m["files"].items()):
        return False
    chk = FIXTURES / "tokenizer" / "u1-synthetic-checkpoint"
    chk2 = FIXTURES / "tokenizer" / "u1-synthetic-checkpoint-no-endoftext"
    return (m["checkpoint"]["tokenizer_json_sha256"] == sha256_file(chk / "tokenizer.json")
            and m["checkpoint"]["tokenizer_config_json_sha256"] == sha256_file(chk / "tokenizer_config.json")
            and m.get("checkpoint_no_endoftext", {}).get("tokenizer_json_sha256") == sha256_file(chk2 / "tokenizer.json")
            and m.get("checkpoint_no_endoftext", {}).get("tokenizer_config_json_sha256") == sha256_file(chk2 / "tokenizer_config.json")
            and m["mechanism_corpus_sha256"] == sha256_file(FIXTURES / "tokenizer" / "u1-mechanism-corpus.jsonl"))


def ensure_pair(pair_dir: Path) -> dict:
    manifest = pair_dir / "u1_pair.manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        if pair_is_fresh(m, pair_dir):
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
                          cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
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
    # P-05 is a U1 composition claim, not a property of C12b's semantic
    # population or the converter's general tokenizer pack. Commission it
    # explicitly in each generated parity population. Put it first so a
    # developer's --limit smoke still exercises the literal-special case.
    recs.insert(0, LITERAL_SPECIAL_RECORD)
    p = out_dir / "corpus239_expected_ids.tsv"
    write_hex_tsv(recs, p, "HF content_ids from tests/fixtures/c12b/corpus-239.jsonl (tools/c12b/mint_c12b_corpus.py)")
    pops.append(("corpus-239", p))
    g = json.loads(GOLDEN_JSON.read_text(encoding="utf-8"))
    recs = [LITERAL_SPECIAL_RECORD]
    recs += [("g-%03d" % i, r["ids"], r["text"]) for i, r in enumerate(g["records"])]
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


def run_cells(exe: Path, args: List[str], leg: str, table: Table, diag: bool = False) -> None:
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
    summary = f"exit {proc.returncode}; {n_pass} PASS, {n_fail} FAIL, {n_missing} MISSING PREREQUISITE in {elapsed:.1f}s"
    if diag:
        table.add(leg, "DIAG", summary + " (diagnostic: never the verdict)")
    else:
        table.add(leg, "PASS" if ok else "FAIL", summary)



SEAM_SYMBOLS = ["semb_test_seam_" + name for name in
                ("arm_park", "parked", "wait_parked", "release", "acquisitions", "reset")]
SEAM_DOCS = ["A small red boat.", "The green forest grows.", "Numbers: 17, 29, 43."]


def workspace_interface(build_dir: Path, table: Table) -> bool:
    """Compare actual commands per source, then evaluated compile/link contracts."""
    import shlex
    try:
        commands = json.loads((build_dir / "compile_commands.json").read_text(encoding="utf-8"))
        groups = {"superembedder": {}, "superembedder_testseam": {}}
        for row in commands:
            command = row.get("command", "")
            for target in groups:
                if f"CMakeFiles/{target}.dir/" not in command.replace("\\", "/"):
                    continue
                normalized = []
                tokens = row.get("arguments") or shlex.split(command, posix=False)
                skip_next = False
                for token in tokens:
                    if skip_next:
                        skip_next = False
                        continue
                    token = token.replace("\\", "/").strip('"')
                    if token in ("-o", "-MF", "-MT"):
                        skip_next = True
                        continue
                    if token.startswith(("/Fo", "/Fd")):
                        continue
                    if token in ("-DSEMB_ENABLE_WORKSPACE_TEST_SEAM=1", "/DSEMB_ENABLE_WORKSPACE_TEST_SEAM=1"):
                        if target == 'superembedder':
                            raise ValueError('test seam definition leaked onto production')
                        continue
                    if token.lstrip('-/').startswith('I') and token[2:].strip('"').rstrip('/') == str(REPO_ROOT / 'tests').replace('\\', '/'):
                        if target == 'superembedder':
                            raise ValueError('test include path leaked onto production')
                        continue
                    normalized.append(token)
                groups[target][str(Path(row['file']).resolve())] = normalized
        prod, seam = groups.values()
        if not prod or prod.keys() != seam.keys():
            raise ValueError(f"actual source command membership differs: {prod.keys()} / {seam.keys()}")
        mismatch = {src: (prod[src], seam[src]) for src in prod if prod[src] != seam[src]}
        if mismatch:
            raise ValueError("effective compile commands differ: " + json.dumps(mismatch, indent=2))
        manifests = list((build_dir / 'tests').glob('k15-interface-*.txt'))
        if not manifests:
            raise ValueError('missing evaluated target-interface manifest')
        for manifest in manifests:
            props = dict(line.split('=', 1) for line in manifest.read_text().splitlines())
            for key, value in props.items():
                if key.endswith('.production') and value != props[key.replace('.production', '.testseam')]:
                    raise ValueError(f"effective {key} differs in {manifest}")
            want_define = props['selection'] == 'library'
            for target in groups:
                for src, tokens in groups[target].items():
                    if any('SUPERSLM_C38_INLINE_PERTURBATION=1' in t for t in tokens) != want_define:
                        raise ValueError(f"C38 selection {props['selection']!r} differs for {target}: {src}")
        table.add('K-15 interface prerequisite', 'PASS', f'{len(prod)} actual source commands and evaluated link/standard/runtime interfaces identical; C38 selection verified')
        return True
    except (OSError, ValueError, KeyError) as exc:
        table.add('K-15 interface prerequisite', 'FAIL', str(exc))
        return False


def workspace_child(exe: Path, args: List[str], label: str, table: Table,
                    receipt: Optional[dict] = None) -> Optional[str]:
    # The real parent owns termination and wait. An optional diagnostic receipt
    # exposes that first-party result; it never changes a deadline or verdict.
    with subprocess.Popen([str(exe), *args], cwd=REPO_ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace') as child:
        try:
            stdout, stderr = child.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()  # waits/reaps the terminated child
            if receipt is not None:
                receipt.update(pid=child.pid, returncode=child.returncode, timed_out=True,
                               reaped=child.poll() is not None, stdout=stdout, stderr=stderr)
            table.add(label, 'FAIL', '600-second child deadline; child killed and waited; last output:\n' + stdout[-4000:])
            return None
        if receipt is not None:
            receipt.update(pid=child.pid, returncode=child.returncode, timed_out=False,
                           reaped=child.poll() is not None, stdout=stdout, stderr=stderr)
        proc = subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    if proc.returncode != 0 or '[FAIL]' in proc.stdout:
        table.add(label, 'FAIL', f'child exit {proc.returncode}')
        return None
    return proc.stdout


def run_workspace_suite(args, build_dir: Path, pair_dir: Path, real_tokenizer: str, table: Table) -> None:
    populations = [('M3', str(pair_dir / 'u1_pair_model.sslm'), str(pair_dir / 'u1_pair_tokenizer.sslm'), 32)]
    if args.model and real_tokenizer and Path(args.model).is_file():
        populations.append(('R3', args.model, real_tokenizer, CANDIDATE_DIMS))
    else:
        table.add('R3 K-15d/e/f/g', 'MISSING PREREQUISITE', 'requires configured real model and manifest-matching tokenizer')
    interface_ok = workspace_interface(build_dir, table)
    try:
        proc = subprocess.run([args.cmake_executable, '--build', str(build_dir), '--target',
                               'superembedder', 'superembedder_testseam', 'u1_workspace_seam_test'],
                              cwd=REPO_ROOT, capture_output=True, text=True, errors='replace', timeout=600)
    except subprocess.TimeoutExpired:
        table.add('B3 seam build', 'FAIL', 'SETUP FAILURE: build exceeded 600-second deadline')
        return
    output = proc.stdout + proc.stderr
    (build_dir / 'tests' / 'k15-seam-build.log').write_text(output, encoding='utf-8')
    absent = REPO_ROOT / 'tests' / 'u1_workspace_seam_absent_check.py'
    prod_lib = next(iter(build_dir.glob('superembedder.lib')), build_dir / 'libsuperembedder.a')
    seam_lib = next(iter((build_dir / 'tests').glob('superembedder_testseam.lib')), build_dir / 'tests' / 'libsuperembedder_testseam.a')
    scan = subprocess.run([sys.executable, str(absent), '--production', str(prod_lib), '--testseam', str(seam_lib)],
                          capture_output=True, text=True, timeout=30)
    print(scan.stdout)
    if scan.returncode:
        table.add('K-18 presence control', 'RED-UNIMPLEMENTED' if '[RED-UNIMPLEMENTED]' in scan.stdout else 'FAIL', scan.stdout.strip())
    else:
        table.add('K-18a/b', 'PASS', 'actual production absence and seam presence')
    if proc.returncode:
        unresolved = [sym for sym in SEAM_SYMBOLS if re.search(
            r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?" + sym + r"\b", output)]
        for label, _, _, _ in populations:
            table.add(label + ' K-15d/e/f/g', 'RED-UNIMPLEMENTED' if unresolved else 'FAIL',
                      ('missing builder seam definitions: ' + ', '.join(unresolved)) if unresolved else
                      'SETUP FAILURE (not product red):\n' + '\n'.join(output.splitlines()[-30:]))
        return
    seam = find_exe(build_dir, 'u1_workspace_seam_test')
    production = find_exe(build_dir, 'u1_raw_text_contract_test')
    if not seam or not production:
        table.add('B3 executables', 'FAIL', f'SETUP FAILURE: seam={seam}, production={production}')
        return
    for label, model, tokenizer, dims in populations:
        common = ['--model', model, '--tokenizer', tokenizer, '--dims', str(dims)]
        for cell in ('K-15d', 'K-15e', 'K-15g', 'K-15h'):
            out = workspace_child(seam, [*common, '--cell', cell], label + ' ' + cell, table)
            if out is not None:
                table.add(label + ' ' + cell, 'PASS', 'bounded isolated child; named statuses, canaries, acquisitions and serial bytes')
        if not interface_ok:
            table.add(label + ' K-15f', 'FAIL', 'effective interface prerequisite failed; byte parity not credited')
            continue
        reused = workspace_child(seam, [*common, '--cell', 'K-15f'], label + ' K-15f multi-document reuse', table)
        if reused is not None:
            table.add(label + ' K-15f multi-document reuse', 'PASS', 'three armed documents on the same handle')
        for doc in SEAM_DOCS:
            observed = []
            for name, exe, extra in [('production', production, []), ('unarmed', seam, []), ('armed/released', seam, ['--armed'])]:
                out = workspace_child(exe, [*common, '--print-vector-hex', doc, *extra], label + ' K-15f ' + name, table)
                matches = re.findall(r'^VECTOR_HEX ([0-9a-f]+)$', out or '', re.M)
                observed.append(matches[0] if len(matches) == 1 and len(matches[0]) == dims * 8 else None)
            table.add(label + ' K-15f ' + repr(doc), 'PASS' if observed[0] is not None and len(set(observed)) == 1 else 'FAIL',
                      'actual production/unarmed/armed-released binary32 byte comparison')


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", default="cmake")
    ap.add_argument("--model", default=os.environ.get("SEMB_C12B_MODEL", ""))
    ap.add_argument("--tokenizer", default=os.environ.get("SEMB_U1_TOKENIZER", ""))
    ap.add_argument("--pair-dir", default=str(PAIR_DIR_DEFAULT))
    ap.add_argument("--limit", type=int, default=0, help="cap the real populations' rows (0 = all)")
    ap.add_argument("--mutant-rows", type=int, default=8)
    ap.add_argument("--skip-build", action="store_true", help="assume the targets are already built")
    ap.add_argument("--diag-legacy-layout", action="store_true",
                    help="also build and run the cells under the retired 496d036 config layout; [DIAG] rows only")
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
    table.add("F0 fixtures", "PASS", f"pair at {pair_dir} (engine {pair['engine_tag']}; "
              f"{len(pair['files'])} files incl. the no-<|endoftext|> variant); other model {other_model.name}")

    # ---- build the cells ---------------------------------------------------------------------------
    targets = ["u1_raw_text_contract_test", "u1_raw_text_parity_test"]
    if args.diag_legacy_layout:
        targets += ["u1_raw_text_contract_test_legacy", "u1_raw_text_parity_test_legacy"]
    if not args.skip_build:
        built, unresolved, tail = build_targets(args.cmake_executable, build_dir, targets)
        if not built:
            if unresolved:
                table.add("B0 link the frozen raw-text cells", "RED-UNIMPLEMENTED",
                          "the frozen sec 3.1 verbs do not exist in the product: unresolved " + ", ".join(unresolved))
                print("\nu1_raw_text_cells_check: RED -- the five frozen verbs (" + ", ".join(FROZEN_SYMBOLS) +
                      ") are not defined by `superembedder` at this tip; every cell below is red-unimplemented, "
                      "not a verified pass:\n  K-01..K-17 (tests/u1_raw_text_contract_test.cpp)\n"
                      "  P-00..P-05 (tests/u1_raw_text_parity_test.cpp)\nlinker output tail:\n" + tail)
            else:
                table.add("B0 build the frozen raw-text cells", "FAIL", "build failed for a reason other than the "
                          "missing frozen symbols:\n" + tail)
            return 1
        table.add("B0 build the frozen raw-text cells", "PASS", f"{len(targets)} target(s) linked")
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
    pair_tok_no_eot = str(pair_dir / "u1_pair_tokenizer_no_endoftext.sslm")
    mech_scratch = build_dir / "_u1_contract_scratch"
    mech_scratch.mkdir(parents=True, exist_ok=True)
    mech_args = ["--model", pair_model, "--tokenizer", pair_tok, "--dims", "32", "--context-cap", "64",
                 "--other-model", str(other_model), "--absent-end-token-tokenizer", pair_tok_no_eot,
                 "--scratch-dir", str(mech_scratch), "--workspace-precedence"]
    if real_tokenizer:
        mech_args += ["--other-tokenizer", real_tokenizer]
    run_cells(contract, mech_args, "M1 contract cells K-01..K-17 plus K-06i on the synthetic pair", table)
    parity_mech_args = ["--model", pair_model, "--tokenizer", pair_tok, "--append-id", str(pair["appended_token_id"]),
                        "--wrong-append-id", "263", "--expected-ids", str(pair_dir / "u1_mechanism_expected_ids.tsv"),
                        "--mutant-rows", "64"]
    run_cells(parity, parity_mech_args, "M2 parity cells P-00..P-05 on the synthetic pair (24-record mechanism corpus)", table)

    # ---- PRODUCT: the real pair -------------------------------------------------------------------
    if not args.model or not real_tokenizer:
        table.add("R1 product cells on Qwen3-Embedding-0.6B", "MISSING PREREQUISITE",
                  "needs --model (SEMB_C12B_MODEL) and a manifest-matching --tokenizer (SEMB_U1_TOKENIZER); "
                  "neither artifact is committed")
    elif not Path(args.model).exists():
        table.add("R1 product cells on Qwen3-Embedding-0.6B", "FAIL", f"--model {args.model} does not exist")
    else:
        scratch = build_dir / "_u1_real"
        scratch.mkdir(parents=True, exist_ok=True)
        pops = real_populations(scratch)
        run_cells(contract, ["--model", args.model, "--tokenizer", real_tokenizer, "--dims", str(CANDIDATE_DIMS),
                             "--other-model", pair_model, "--absent-end-token-tokenizer", pair_tok_no_eot,
                             "--scratch-dir", str(scratch)],
                  "R1 contract cells K-01..K-17 on the real pair", table)
        for name, tsv in pops:
            extra = ["--limit", str(args.limit)] if args.limit else []
            run_cells(parity, ["--model", args.model, "--tokenizer", real_tokenizer, "--append-id", str(CANDIDATE_APPEND_ID),
                               "--wrong-append-id", str(CANDIDATE_WRONG_ID), "--expected-ids", str(tsv),
                               "--mutant-rows", str(args.mutant_rows), *extra],
                      f"R2 parity cells P-00..P-05 on the real pair, population {name}", table)

    # ---- DIAGNOSTIC: the retired 496d036 config layout ---------------------------------------------
    if args.diag_legacy_layout:
        contract_legacy = find_exe(build_dir, "u1_raw_text_contract_test_legacy")
        parity_legacy = find_exe(build_dir, "u1_raw_text_parity_test_legacy")
        if not contract_legacy or not parity_legacy:
            table.add("D0 locate the legacy-layout diagnostic cells", "DIAG", f"contract={contract_legacy} parity={parity_legacy}")
        else:
            run_cells(contract_legacy, mech_args + ["--legacy-append-id", str(pair["appended_token_id"])],
                      "D1 [DIAG] contract cells under the retired seven-member semb_config, synthetic pair", table, diag=True)
            run_cells(parity_legacy, parity_mech_args + ["--legacy-append-id", str(pair["appended_token_id"])],
                      "D2 [DIAG] parity cells under the retired seven-member semb_config, synthetic pair", table, diag=True)
            if args.model and real_tokenizer and Path(args.model).exists():
                scratch = build_dir / "_u1_real_legacy"
                scratch.mkdir(parents=True, exist_ok=True)
                pops = real_populations(scratch)
                run_cells(contract_legacy, ["--model", args.model, "--tokenizer", real_tokenizer, "--dims", str(CANDIDATE_DIMS),
                                            "--other-model", pair_model, "--absent-end-token-tokenizer", pair_tok_no_eot,
                                            "--scratch-dir", str(scratch), "--legacy-append-id", str(CANDIDATE_APPEND_ID)],
                          "D3 [DIAG] contract cells under the retired seven-member semb_config, real pair", table, diag=True)
                for name, tsv in pops:
                    extra = ["--limit", str(args.limit)] if args.limit else []
                    run_cells(parity_legacy, ["--model", args.model, "--tokenizer", real_tokenizer, "--append-id", str(CANDIDATE_APPEND_ID),
                                              "--wrong-append-id", str(CANDIDATE_WRONG_ID), "--expected-ids", str(tsv),
                                              "--mutant-rows", str(args.mutant_rows), "--legacy-append-id", str(CANDIDATE_APPEND_ID), *extra],
                              f"D4 [DIAG] parity cells under the retired seven-member semb_config, real pair, population {name}", table, diag=True)

    run_workspace_suite(args, build_dir, pair_dir, real_tokenizer, table)

    print("\nu1_raw_text_cells_check summary:")
    for leg, state, _ in table.rows:
        print(f"  {state:22s} {leg}")
    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
