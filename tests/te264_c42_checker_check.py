"""U1 Slice 7 step 4 (c), re-based by U2-3: the C42 release checker's constructions over a real-shaped package
(TE-264; `Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.7 step 4; `Claude/Plans/SuperEmbedder_Plan.md`
sec 4.1a and sec 8 C42; D-SLM7206; `Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3 items 4, 9, 10, 12 and
its Must-accepts, D-SLM7309).

    python tools/check_certified_builds.py --root <package root>

reads the package root's list, identity file, lock, proof corpus and derivation inputs, and each cell's runs. It
exits 0 when the package is accepted and 1 when it is refused, and names every refused clause on its own output
line `REFUSED C42(<clause>)`. Run against the repository root it checks the committed package.

THE MUST-ACCEPT IS A REAL-SHAPED PACKAGE (te267 P:1962-1970), replacing Slice 7's three-row
`"toolchain": "synthetic"` package, which C42 (b') refuses (P:1253-1256). The test builds it from committed real
data that exists before the build:
  - the two interim cells in cell form, `msvc19.33-auto@avx2` and `clangcl18.1.8-auto@avx2` (P:1139-1140), with
    item 1's descriptor fields: `toolchain` and `stdlib` as the descriptor's one formatting function writes
    them for MSVC 19.33.31631 and clang-cl 18.1.8 under the `vcvars64 -vcvars_ver=14.33` STL, `202205` (P:1148;
    reasoned from `src/superembedder/semb_build_descriptor.h`, not compiled here), `Release`, `cmake`, `auto`,
    and flag-record digests recomputed here from the records the run directory carries (P:1245-1249);
  - the committed interim runs' real 239-line `row-digests.tsv` (corpus-239's labels, in order) and the
    committed list's artifact and host strings;
  - the committed identity file, unchanged, with a lock carrying its `enginePin`, the committed proof corpus and
    the tree's derivation inputs (`src/`, `include/`, `cmake/`, `CMakeLists.txt`, `superslm.lock`,
    `tests/fixtures/wq/`, P:1056-1057), so clauses (c), (c') and (h) read a consistent tree;
  - per run, item 12's file set: a bake manifest in item 12's schema carrying the identity's corpus values
    (`count`, `corpus_digest`, `token_id_digest`), the cell's `build_descriptor` and `machine_tier` and the
    member epoch; `compile-flags.json` and `engine-flags.json`; `token-id-digest.txt` equal to the identity's
    `tokenIdDigest`; and a `run.json` copying the manifest, recording its SHA-256, the run's own `runId`, the
    engine pin and the tree's derivation-input digest (P:1231-1236). The pair names both runs' ids (`runIds`).
The manifests are constructed, not written by a bake: no bake of the real artifact runs in this test. Once the
interim cells are re-executed on the U2-3 tree, the committed package is the second must-accept (P:1969-1970).

CELLS, each on a fresh copy of that package; a refusal naming another clause, or none, fails its cell:
  must-accept   the unedited package -> exit 0, no REFUSED line
  (a)           the one pairwiseProofs entry deleted -> REFUSED C42(a) only
  (b)           the pair's rowDigest disagrees with its runs' evidence (evidence unchanged) -> C42(b) only
  (c)           the engine pin bumped in the lock and the identity file together, the runs not re-run -> C42(c)
                and C42(c') only: the runs record a pin the identity no longer names (P:1162-1163), and the lock
                is a derivation input (P:1057)
  (c')          one byte of one `src/` file edited after the runs were recorded -> C42(c') only (item 4,
                P:1059-1060; red-first (4), P:1722)
  (m1)          one cell's `toolchain` changed to `MSVC 19.44.35214.0`, its runs unchanged -> C42(b') only
  (m2)          both cells' `row-digests.tsv` cut to one line, `run.json`'s and the pair's `rowDigest`
                recomputed to match -> C42(b') only
  (m3)          the pair's `runIds` entry for one cell changed to `never-ran` -> C42(b') only
                (m1)-(m3) are the code reviewer's constructions (P:1828-1842)
  committed     the repository's own committed package -> exit 0, no REFUSED line. RED in the cloud and until the
                interim cells are re-executed on the U2-3 tree into item 12's file set and the list is rewritten
                in cell form (P:1139-1144), and the lock carries the platform-free `tree=` (P:1463-1465): owed to
                the dev box.

Exit codes: 0 every cell PASS; 1 any FAIL.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_certified_builds.py"
EVIDENCE = "docs/certification/interim"
IDENTITY = "docs/certification-identity.json"
LIST = "docs/certified-builds.json"
CORPUS = "tests/fixtures/c12b/corpus-239.jsonl"
# te267 P:1056-1057: the derivation inputs the package root must carry for clause (c').
DERIVATION_INPUTS = ("src", "include", "cmake", "CMakeLists.txt", "tests/fixtures/wq")
# The interim cells' real 239-line row digests (both cells' files are byte-identical). U2-3's re-executed
# msvc19.33-auto@avx2 run replaced the Slice 7 run at win-x64-msvc-avx2-zen2/ (item 9) with the same bytes.
REAL_ROWS = ROOT / EVIDENCE / "msvc19.33-auto@avx2" / "row-digests.tsv"
DATE = "2026-09-25"

# The two interim cells in cell form (P:1139-1140). toolchain/stdlib: semb_build_descriptor.h's formatting of
# MSVC 19.33.31631 (_MSC_FULL_VER 193331631, _MSC_BUILD 0) and clang-cl 18.1.8 under the 14.33 STL (202205).
CELLS = {
    "msvc19.33-auto@avx2": {"toolchain": "MSVC 193331631.0", "family": "msvc", "runId": "u23-interim-msvc19.33-avx2"},
    "clangcl18.1.8-auto@avx2": {"toolchain": "Clang 18.1.8 (MSVC frontend 193331631)", "family": "clangcl",
                                "runId": "u23-interim-clangcl18.1.8-avx2"},
}
COMMON_DESCRIPTOR = {"os": "windows", "isa": "x86-64", "stdlib": "MSVC STL 202205", "configuration": "Release",
                     "buildSystem": "cmake", "dispatch": "auto"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def flag_digest(record: dict) -> str:
    """te267 P:1374: SHA-256 over the record's canonical JSON (sorted keys, no whitespace)."""
    return sha(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def product_record(family: str) -> dict:
    """A tokenized product record of the shape item 13 writes (P:1359-1367): location roots as tokens, includes
    in order, every other argument sorted; no residual location."""
    flags = sorted(["/DNDEBUG", "/EHsc", "/MD", "/O2", "/Ob2", "-std:c++20", "/fp:precise", "/GR"]
                   + (["-fms-compatibility-version=19.33"] if family == "clangcl" else []))
    return {f"superembedder:<src>/src/superembedder/{tu}": {
        "includes": ["-I<src>/include", "-I<build>/generated", "-external:I<engine>/include"], "flags": flags}
        for tu in ("encoder.cpp", "certification.cpp", "engine_adapter_interim.cpp")}


def engine_record(family: str) -> dict:
    flags = sorted(["/DNDEBUG", "/EHsc", "/MD", "/O2", "/Ob2", "-std:c++20"]
                   + (["-fms-compatibility-version=19.33"] if family == "clangcl" else []))
    return {f"superslm:<src>/src/{tu}": {"includes": ["-I<src>/include", "-I<src>/src"], "flags": flags}
            for tu in ("matmul.cpp", "forward_sites.cpp")}


def dump(obj) -> bytes:
    return (json.dumps(obj, indent=2) + "\n").encode("utf-8")


def load_derivation_tool():
    sys.path.insert(0, str(ROOT / "tools"))
    import derivation_inputs  # noqa: E402  -- the package script's own producer of derivationInputsSha256
    return derivation_inputs


def write_package(root: Path) -> dict:
    """Writes the consistent real-shaped package under `root`; returns {"list": ..., "identity": bytes}."""
    for entry in DERIVATION_INPUTS:
        src, dest = ROOT / entry, root / entry
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copyfile(src, dest)
    (root / CORPUS).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / CORPUS, root / CORPUS)
    identity_bytes = (ROOT / IDENTITY).read_bytes()
    identity = json.loads(identity_bytes.decode("ascii"))
    (root / IDENTITY).parent.mkdir(parents=True, exist_ok=True)
    (root / IDENTITY).write_bytes(identity_bytes)
    pin, pc = identity["enginePin"], identity["proofCorpus"]
    (root / "superslm.lock").write_bytes(
        f"tag={pin['tag']}\ncommit={pin['commit']}\ntree={pin['engine_tree_sha']}\n".encode("ascii"))
    tree_digest = load_derivation_tool().digest(root)
    product_commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                                    text=True).stdout.strip()

    committed = json.loads((ROOT / LIST).read_bytes().decode("utf-8"))
    artifact, host = committed["builds"][0]["artifact"], committed["builds"][0]["host"]
    model_sha, tokenizer_sha = re.findall(r"sha256=([0-9a-f]{64})", artifact)
    rows = REAL_ROWS.read_bytes()
    token = pc["tokenIdDigest"]
    member_epoch = sha(identity_bytes)
    compiled_list_sha = sha((ROOT / LIST).read_bytes())  # pass one compiles an earlier list (P:1084-1085)

    builds = []
    for cell_id, spec in CELLS.items():
        compile_rec, engine_rec = product_record(spec["family"]), engine_record(spec["family"])
        descriptor = dict(COMMON_DESCRIPTOR, toolchain=spec["toolchain"], compileFlags=flag_digest(compile_rec),
                          engineFlags=flag_digest(engine_rec))
        builds.append(dict({"id": cell_id}, **descriptor, cpuTier="avx2", artifact=artifact, host=host,
                           evidence=EVIDENCE))
        manifest = {
            "encoder_fingerprint": sha(b"five-field fingerprint " + cell_id.encode()),
            "model_sha": model_sha, "tokenizer_sha": tokenizer_sha,
            "template_sha256": sha(b"template"), "witness_sha": sha(b"witness"),
            "certification_epoch": member_epoch,
            "certification_identity_path": IDENTITY, "certified_builds_path": LIST,
            "certified_builds_sha256": compiled_list_sha, "certified_cell": cell_id,
            "build_descriptor": {k: descriptor[k] for k in ("os", "isa", "toolchain", "stdlib", "configuration",
                                                            "buildSystem", "dispatch", "compileFlags",
                                                            "engineFlags")},
            "count": pc["rows"], "dims": 1024, "metric": "cosine", "dtype": "float32",
            "row_digest": sha(b"the reference bank is REL-4's; no bank bytes exist before it"),
            "corpus_digest": pc["corpusDigest"], "machine_tier": "avx2", "token_id_digest": token,
        }
        manifest_bytes = dump(manifest)
        d = root / EVIDENCE / cell_id
        d.mkdir(parents=True)
        (d / "row-digests.tsv").write_bytes(rows)
        (d / "token-id-digest.txt").write_bytes((token + "\n").encode("ascii"))
        (d / "bake-manifest.semb.json").write_bytes(manifest_bytes)
        (d / "compile-flags.json").write_bytes(dump({"family": spec["family"], "record": compile_rec,
                                                     "residual": []}))
        (d / "engine-flags.json").write_bytes(dump({"family": spec["family"], "record": engine_rec,
                                                    "residual": []}))
        run = {"cellId": cell_id, "runId": spec["runId"], "date": DATE, "pass": "provisional", "host": host,
               "manifestSha256": sha(manifest_bytes), "buildDescriptor": manifest["build_descriptor"],
               "machineTier": "avx2", "certificationEpoch": member_epoch,
               "certifiedBuildsSha256": compiled_list_sha, "certifiedCell": cell_id,
               "dispatchedTier": "avx2", "hostBestTier": "avx2", "enginePin": dict(pin),
               "productCommit": product_commit, "derivationInputsSha256": tree_digest,
               "rowDigest": sha(rows), "tokenIdDigest": token}
        (d / "run.json").write_bytes(dump(run))
    a, b = list(CELLS)
    doc = {"schemaVersion": 1, "release": "1.0.0-interim (te264 must-accept package)", "builds": builds,
           "pairwiseProofs": [{"a": a, "b": b, "runIds": [CELLS[a]["runId"], CELLS[b]["runId"]],
                               "rowDigest": sha(rows), "tokenIdDigest": token}]}
    write_doc(root, doc)
    return {"list": doc, "identity": identity_bytes}


def write_doc(root: Path, doc: dict) -> None:
    path = root / LIST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump(doc))


def run_checker(root: Path, checker: Path) -> tuple[int | None, set[str], str]:
    if not checker.is_file():
        return None, set(), f"{checker} does not exist"
    proc = subprocess.run([sys.executable, str(checker), "--root", str(root)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    out = proc.stdout + proc.stderr
    clauses = set(re.findall(r"^REFUSED C42\(([a-i]'?)\)", out, re.M))
    return proc.returncode, clauses, out[-900:]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch", type=Path, default=None)
    ap.add_argument("--checker", type=Path, default=CHECKER,
                    help="the checker under test (default: tools/check_certified_builds.py)")
    args = ap.parse_args(argv)
    scratch = args.scratch or Path(tempfile.mkdtemp(prefix="te264_c42_"))
    failed = False

    def report(ok: bool, cell: str, detail: str) -> None:
        nonlocal failed
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")
        failed |= not ok

    def refused_on(root: Path, cell: str, want: set[str]) -> None:
        rc, clauses, tail = run_checker(root, args.checker)
        report(rc == 1 and clauses == want, cell, f"exit={rc}; refused clauses={sorted(clauses)} "
                                                  f"(want {sorted(want)}); {tail!r}")

    try:
        def fresh(name: str) -> tuple[Path, dict]:
            root = scratch / name
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True)
            return root, write_package(root)

        root, _ = fresh("accept")
        rc, clauses, tail = run_checker(root, args.checker)
        report(rc == 0 and not clauses, "must-accept: the real-shaped two-cell interim package is accepted",
               f"exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")

        root, pkg = fresh("a_pair_deleted")
        edited = copy.deepcopy(pkg["list"])
        del edited["pairwiseProofs"][0]
        write_doc(root, edited)
        refused_on(root, "C42 (a): the one pair deleted is refused on (a) alone", {"a"})

        root, pkg = fresh("b_row_digest_forged")
        edited = copy.deepcopy(pkg["list"])
        edited["pairwiseProofs"][0]["rowDigest"] = sha(b"a digest no run produced")
        write_doc(root, edited)
        refused_on(root, "C42 (b): a rowDigest that disagrees with its runs' evidence files is refused on (b) alone",
                   {"b"})

        root, pkg = fresh("c_pin_bumped")
        pin = json.loads(pkg["identity"].decode("ascii"))["enginePin"]
        bumped = {"tag": "v9.9.9", "commit": "1" * 40, "engine_tree_sha": "2" * 64}
        text = pkg["identity"].decode("ascii")
        for k in ("tag", "commit", "engine_tree_sha"):
            text = text.replace(f'"{k}": "{pin[k]}"', f'"{k}": "{bumped[k]}"')
        (root / IDENTITY).write_bytes(text.encode("ascii"))
        (root / "superslm.lock").write_bytes(
            f"tag={bumped['tag']}\ncommit={bumped['commit']}\ntree={bumped['engine_tree_sha']}\n".encode("ascii"))
        refused_on(root, "C42 (c): the engine pin bumped in the lock and the identity file without re-running is "
                         "refused on (c) and (c') alone", {"c", "c'"})

        root, _ = fresh("c_prime_src_edit")
        target = root / "src" / "superembedder" / "encoder.cpp"
        data = bytearray(target.read_bytes())
        data[-2] = ord(" ") if data[-2] != ord(" ") else ord("\t")
        target.write_bytes(bytes(data))
        refused_on(root, "C42 (c'): a one-byte src/ edit after the runs were recorded is refused on (c') alone",
                   {"c'"})

        root, pkg = fresh("m1_toolchain_no_run_recorded")
        edited = copy.deepcopy(pkg["list"])
        edited["builds"][0]["toolchain"] = "MSVC 19.44.35214.0"
        write_doc(root, edited)
        refused_on(root, "C42 (b') m1: a cell toolchain no run recorded is refused on (b') alone", {"b'"})

        root, pkg = fresh("m2_one_row_proof")
        one = REAL_ROWS.read_bytes().split(b"\n", 1)[0] + b"\n"
        for cell_id in CELLS:
            d = root / EVIDENCE / cell_id
            (d / "row-digests.tsv").write_bytes(one)
            run = json.loads((d / "run.json").read_bytes())
            run["rowDigest"] = sha(one)
            (d / "run.json").write_bytes(dump(run))
        edited = copy.deepcopy(pkg["list"])
        edited["pairwiseProofs"][0]["rowDigest"] = sha(one)
        write_doc(root, edited)
        refused_on(root, "C42 (b') m2: a one-row proof, every digest made consistent, is refused on (b') alone",
                   {"b'"})

        root, pkg = fresh("m3_run_never_ran")
        edited = copy.deepcopy(pkg["list"])
        edited["pairwiseProofs"][0]["runIds"][1] = "never-ran"
        write_doc(root, edited)
        refused_on(root, "C42 (b') m3: a pair naming a run that never ran is refused on (b') alone", {"b'"})

        rc, clauses, tail = run_checker(ROOT, args.checker)
        committed = ROOT / LIST
        report(rc == 0 and not clauses and committed.is_file(),
               "committed: the repository's own interim certification package is accepted (owed to the dev box: "
               "the re-executed interim cells, the cell-form list and the platform-free lock)",
               f"document present={committed.is_file()}; exit={rc}; refused clauses={sorted(clauses)}; {tail!r}")
    finally:
        if not args.scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    print(f"\nte264_c42_checker_check: {'FAILED' if failed else 'all cells PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
