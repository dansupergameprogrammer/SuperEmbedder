"""tests/epoch_store_constructions_check.py -- TE-162 (U1 slice 3): the
sub-plan's own cell 2, "the four able-to-fail constructions" plus "the
lifecycle pair" (`Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.3;
`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C32's own able-to-fail list,
quoted verbatim in the dispatch), extended by TE-170's own review-fix round
with construction 7 (C1: an archived entry deleted outright) and
construction 8 (M7: an archived twin whose bytes diverge) -- the
discriminating pair the review's own C1 finding and its own M7 coverage
gap named. Eight constructions, each executed against
`epoch_store_check.py`'s own parent-commit logic (cell 1(c)) in a SCRATCH
git repository this script builds under the build directory -- never the
product repository, never a hand-fabricated byte blob standing in for a
commit.

THE SCRATCH REPO. A fresh `git init` under `--scratch-dir`, `.gitattributes`
carrying `* -text` (the product repository's own rule, asserted rather than
inherited), and a BASE commit holding a well-formed TWO-ENTRY live store:
  - fp1: minted by `epoch_store_emit` from the synthetic tiny artifact
    (--synthetic-model/--synthetic-tokenizer/--synthetic-dims), one document
    (--doc-ids), under fp1's own REAL, emit-derived fingerprint -- genuinely
    well-formed and internally consistent, not fabricated.
  - fp2: a byte-for-byte COPY of fp1's own three files under a second,
    fixed, distinct 64-lowercase-hex directory name. Two entries under two
    DIFFERENT keys, both genuinely well-formed, without needing a second
    real artifact -- the lifecycle mechanics this cell exists to prove
    (append-only, archive-by-move, the three divergence statuses) operate
    on ANY two commits' worth of epoch-store/ trees and do not themselves
    depend on what a fingerprint denotes (that grading is cell 1(b)'s,
    against the build under test's OWN real fingerprint, entirely separate
    from this cell's lifecycle claim).

EACH CONSTRUCTION checks out a fresh branch from the BASE commit (so they
are independent, never interfering with each other), applies EXACTLY ONE
mutation (constructions 7 and 8 apply two, in two commits, since the
mutation under test is itself a SECOND commit against an already-archived
first commit -- see each's own comment), commits, then runs
`epoch_store_check.check_parent_commit` (imported directly, in-process,
stdout captured) with `--parent-ref` the relevant commit -- exactly the
shape cell 1(c) itself runs in production, applied here to a commit this
script controls completely.

  1. bytes moved under an unchanged fingerprint (fp1's vectors.f32 flipped,
     lineage.tsv held fixed)      -> SEMB_EPOCH_BYTES_DIVERGED
  2. the lineage digest moving alone (fp1's lineage.tsv flipped,
     vectors.f32/row-digest.tsv held fixed) -> SEMB_EPOCH_LINEAGE_DIVERGED
  3. an entry re-minted in place (fp1's three files wholesale-replaced with
     fp2's own original bytes)    -> SEMB_EPOCH_ENTRY_MODIFIED
  4. an append that leaves every prior entry untouched (a third entry, fp3,
     added; fp1/fp2 byte-identical to the base commit) -> GREEN
  5. archive-by-move accepted (fp2 removed from live/, its own original
     bytes appear byte-identical under archive/fp2/ in the SAME commit)
     -> GREEN ("archived")
  6. deletion without the archive twin refused (fp2 removed from live/,
     nothing added under archive/fp2/) -> SEMB_EPOCH_ENTRY_MODIFIED
  7. (C1, TE-170) an archived entry deleted outright: commit 1 archives
     fp2 (accepted, as in 5); commit 2 deletes archive/fp2/ entirely, so
     the entry exists at NEITHER live/ nor archive/ -> SEMB_EPOCH_ENTRY_MODIFIED
     against commit 1 as the parent -- the review's own scratch construction.
  8. (M7, TE-170) an archived twin that diverges: commit 1 archives fp2
     (accepted, as in 5); commit 2 flips one byte in archive/fp2/vectors.f32
     -> SEMB_EPOCH_ENTRY_MODIFIED against commit 1 as the parent -- the
     discriminating half construction 7 does not exercise (deletion vs.
     silent divergence).

RED-FIRST: run before the product's own store exists and before
epoch_store_check.py's own check_parent_commit is exercised against a real
build -- each construction below is a scratch fixture this script itself
builds and mutates, so every one runs and quotes a verdict regardless of
whether `epoch-store/` exists anywhere in the product tree (confirmed
independent of that fact: this script never reads the product repository's
own epoch-store/, only the scratch one it creates).

INSTRUMENT COMMISSIONING (StandardsDocument.md sec 5.4): `epoch_store_check.py`
is registered QUARANTINED against construction 4 (untouched append) as its
must-accept and construction 1 (bytes diverged) as its must-reject -- see
this suite's own registration record in the handoff casebook. This script
IS that must-reject/must-accept population, executed.

USAGE
  epoch_store_constructions_check.py --emit-binary <path>
    --synthetic-model <.sslm> --synthetic-tokenizer <.sslm>
    --synthetic-dims <n> --synthetic-tokens <tsv>
    --synthetic-terminator-id <n> --scratch-dir <dir> [--git <git-exe>]

Exit codes: 0 all constructions quote their expected verdict; 1 any
construction quotes something else (a dead check, or a check that cannot
fire on the class it exists to catch).
"""
from __future__ import annotations

import argparse
import io
import contextlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import epoch_store_check as checker  # noqa: E402 (reuses cell 1(c)'s own logic, never a re-invented copy)
import epoch_store_contract as contract  # noqa: E402

FP2_FIXED = "0" * 63 + "1"   # a fixed, valid-shaped, distinct-from-fp1 fingerprint (guarded below)
FP3_FIXED = "0" * 63 + "2"


def run(cmd: List[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def git_init_repo(repo: Path, git: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run([git, "init", "-q"], repo)
    run([git, "config", "user.email", "epoch-store-constructions@test"], repo)
    run([git, "config", "user.name", "epoch_store_constructions_check"], repo)
    (repo / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    run([git, "add", "-A"], repo)
    run([git, "commit", "-q", "-m", "scratch repo init"], repo)


def commit_all(repo: Path, git: str, message: str) -> str:
    run([git, "add", "-A"], repo)
    run([git, "commit", "-q", "-m", message], repo)
    return run([git, "rev-parse", "HEAD"], repo).strip()


def checkout_new_branch(repo: Path, git: str, name: str, base_sha: str) -> None:
    run([git, "checkout", "-q", "-B", name, base_sha], repo)


def copy_entry(repo: Path, from_fp: str, to_fp: str, section: str = contract.LIVE_DIR) -> None:
    src = contract.entry_dir(repo, section, from_fp)
    dst = contract.entry_dir(repo, section, to_fp)
    dst.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(src / name, dst / name)


def flip_one_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())
    if not data:
        raise RuntimeError(f"cannot flip a byte in an empty file: {path}")
    data[0] ^= 0xFF
    path.write_bytes(bytes(data))


def captured_check_parent_commit(repo: Path, parent_ref: str) -> str:
    """Runs epoch_store_check.check_parent_commit in-process against
    `repo`, resetting its module-level counters first, and returns
    everything it printed -- the named status (if any) is embedded in that
    text, exactly as cell 1(c) would emit it in production."""
    checker.g_cells = 0
    checker.g_failures = 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        checker.check_parent_commit(repo, parent_ref)
    return buf.getvalue()


def expect(condition: bool, name: str, detail: str, failures: List[str]) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}: {detail}", flush=True)
    if not condition:
        failures.append(name)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--emit-binary", required=True)
    p.add_argument("--repo-root", required=True)
    p.add_argument("--synthetic-model", default="", help="empty = regenerate tests/fixtures/regenerate_tokenizer_pair_fixture.py's own pair")
    p.add_argument("--synthetic-tokenizer", default="")
    p.add_argument("--synthetic-dims", type=int, default=32)
    p.add_argument("--synthetic-tokens", default="tests/fixtures/c12b/synthetic-corpus.tokens.tsv")
    p.add_argument("--synthetic-terminator-id", type=int, default=262)
    p.add_argument("--scratch-dir", required=True)
    p.add_argument("--git", default="git")
    p.add_argument("--doc-id", default="syn-a", help="one document id from --synthetic-tokens to mint fp1 from")
    args = p.parse_args()

    scratch = Path(args.scratch_dir)
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    repo = scratch / "repo"
    emit_out = scratch / "emit-fp1"
    repo_root = Path(args.repo_root)

    synthetic_model = args.synthetic_model
    synthetic_tokenizer = args.synthetic_tokenizer
    if not synthetic_model or not synthetic_tokenizer:
        try:
            pair_model, pair_tokenizer = contract.ensure_synthetic_pair(repo_root)
            synthetic_model = synthetic_model or pair_model
            synthetic_tokenizer = synthetic_tokenizer or pair_tokenizer
        except RuntimeError as ex:
            print(f"[FAIL] (setup) regenerate the synthetic tokenizer-capable pair: {ex}")
            return 1

    # ---- Mint fp1 for real, via the SAME support tool cell 1(b) uses. ----
    proc = subprocess.run(
        [args.emit_binary, "--model", synthetic_model, "--tokenizer", synthetic_tokenizer, "--dims",
         str(args.synthetic_dims), "--tokens", args.synthetic_tokens, "--terminator-id",
         str(args.synthetic_terminator_id), "--out-dir", str(emit_out), "--doc-ids", args.doc_id],
        cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[FAIL] (setup) epoch_store_emit mints fp1: {proc.stdout}\n{proc.stderr}")
        return 1
    fp1 = ""
    for line in proc.stdout.splitlines():
        if line.startswith("fingerprint="):
            fp1 = line.split("=", 1)[1]
    if not contract.is_fingerprint_dir_name(fp1):
        print(f"[FAIL] (setup) epoch_store_emit reports a valid fingerprint: got {fp1!r}")
        return 1
    fp2 = FP2_FIXED if FP2_FIXED != fp1 else "1" * 64
    fp3 = FP3_FIXED if FP3_FIXED not in (fp1, fp2) else "2" * 64
    print(f"[PASS] (setup) fp1 minted: {fp1}")

    # ---- Build the scratch repo and its BASE commit: fp1 (real) + fp2
    # (a byte-identical copy under a distinct key). ----
    git_init_repo(repo, args.git)
    contract.entry_dir(repo, contract.LIVE_DIR, fp1).mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(emit_out / name, contract.entry_dir(repo, contract.LIVE_DIR, fp1) / name)
    copy_entry(repo, fp1, fp2)
    base_sha = commit_all(repo, args.git, "base: two well-formed live entries")
    print(f"[PASS] (setup) base commit with fp1+fp2: {base_sha}")

    failures: List[str] = []

    # ---- Construction 1: bytes moved under an unchanged fingerprint. ----
    checkout_new_branch(repo, args.git, "construction-1", base_sha)
    flip_one_byte(contract.entry_dir(repo, contract.LIVE_DIR, fp1) / contract.VECTORS_FILE_NAME)
    commit_all(repo, args.git, "construction 1: flip a byte in fp1 vectors.f32")
    out = captured_check_parent_commit(repo, base_sha)
    expect(contract.STATUS_BYTES_DIVERGED in out and fp1 in out, "construction-1-bytes-diverged",
           "flipping vectors.f32 alone must be reported SEMB_EPOCH_BYTES_DIVERGED", failures)
    expect(contract.STATUS_LINEAGE_DIVERGED not in out, "construction-1-no-false-lineage-status",
           "must not ALSO report SEMB_EPOCH_LINEAGE_DIVERGED (lineage.tsv was untouched)", failures)

    # ---- Construction 2: the lineage digest moving alone. ----
    checkout_new_branch(repo, args.git, "construction-2", base_sha)
    flip_one_byte(contract.entry_dir(repo, contract.LIVE_DIR, fp1) / contract.LINEAGE_FILE_NAME)
    commit_all(repo, args.git, "construction 2: flip a byte in fp1 lineage.tsv")
    out = captured_check_parent_commit(repo, base_sha)
    expect(contract.STATUS_LINEAGE_DIVERGED in out and fp1 in out, "construction-2-lineage-diverged",
           "flipping lineage.tsv alone must be reported SEMB_EPOCH_LINEAGE_DIVERGED", failures)
    expect(contract.STATUS_BYTES_DIVERGED not in out, "construction-2-no-false-bytes-status",
           "must not ALSO report SEMB_EPOCH_BYTES_DIVERGED (vectors.f32/row-digest.tsv were untouched)", failures)

    # ---- Construction 3: an entry re-minted in place (every member
    # replaced with different-but-well-formed bytes). ----
    checkout_new_branch(repo, args.git, "construction-3", base_sha)
    # Every one of fp1's three members moves together -- a wholesale
    # re-mint, distinct from constructions 1 and 2 (which each move
    # exactly one member group).
    for name in contract.MEMBER_FILE_NAMES:
        flip_one_byte(contract.entry_dir(repo, contract.LIVE_DIR, fp1) / name)
    commit_all(repo, args.git, "construction 3: re-mint fp1 wholesale")
    out = captured_check_parent_commit(repo, base_sha)
    expect(contract.STATUS_ENTRY_MODIFIED in out and fp1 in out, "construction-3-entry-modified",
           "replacing every member together must be reported SEMB_EPOCH_ENTRY_MODIFIED", failures)

    # ---- Construction 4: an append that leaves every prior entry
    # untouched -> GREEN. ----
    checkout_new_branch(repo, args.git, "construction-4", base_sha)
    copy_entry(repo, fp1, fp3)
    commit_all(repo, args.git, "construction 4: append fp3, fp1/fp2 untouched")
    out = captured_check_parent_commit(repo, base_sha)
    expect("FAIL" not in out, "construction-4-untouched-append-is-green",
           "a pure append must produce zero FAIL rows (fp1/fp2 byte-identical; fp3 is a new, informational append)",
           failures)

    # ---- Construction 5: archive-by-move accepted. ----
    checkout_new_branch(repo, args.git, "construction-5", base_sha)
    fp2_live = contract.entry_dir(repo, contract.LIVE_DIR, fp2)
    fp2_archive = contract.entry_dir(repo, contract.ARCHIVE_DIR, fp2)
    fp2_archive.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(fp2_live / name, fp2_archive / name)
    shutil.rmtree(fp2_live)
    commit_all(repo, args.git, "construction 5: archive-by-move fp2")
    out = captured_check_parent_commit(repo, base_sha)
    expect("FAIL" not in out and fp2 in out, "construction-5-archive-by-move-accepted",
           "a live entry moved byte-identically to archive/ in the same commit must be accepted (no FAIL rows)",
           failures)

    # ---- Construction 6: deletion without the archive twin refused. ----
    checkout_new_branch(repo, args.git, "construction-6", base_sha)
    shutil.rmtree(contract.entry_dir(repo, contract.LIVE_DIR, fp2))
    commit_all(repo, args.git, "construction 6: delete fp2, no archive twin")
    out = captured_check_parent_commit(repo, base_sha)
    expect(contract.STATUS_ENTRY_MODIFIED in out and fp2 in out, "construction-6-deletion-without-archive-refused",
           "deleting a live entry with no byte-identical archive/ twin must be reported SEMB_EPOCH_ENTRY_MODIFIED",
           failures)

    # ---- Construction 7 (C1, TE-170): an archived entry deleted outright,
    # once it exists at NEITHER live/ nor archive/, is refused. Two commits:
    # commit 1 archives fp2 (accepted, matching construction 5); commit 2
    # deletes the archived twin with no live entry to fall back to -- the
    # review's own scratch construction (Poirot C1). ----
    checkout_new_branch(repo, args.git, "construction-7", base_sha)
    fp2_live = contract.entry_dir(repo, contract.LIVE_DIR, fp2)
    fp2_archive = contract.entry_dir(repo, contract.ARCHIVE_DIR, fp2)
    fp2_archive.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(fp2_live / name, fp2_archive / name)
    shutil.rmtree(fp2_live)
    c7_archived_sha = commit_all(repo, args.git, "construction 7 commit 1: archive-by-move fp2")
    out_archived = captured_check_parent_commit(repo, base_sha)
    expect("FAIL" not in out_archived and fp2 in out_archived, "construction-7-archive-by-move-still-accepted",
           "commit 1 (archive-by-move) must still be accepted, matching construction 5", failures)
    shutil.rmtree(fp2_archive)
    commit_all(repo, args.git, "construction 7 commit 2: delete the archived twin outright")
    out = captured_check_parent_commit(repo, c7_archived_sha)
    expect(contract.STATUS_ENTRY_MODIFIED in out and fp2 in out, "construction-7-archived-twin-deleted-refused",
           "deleting an archived entry outright, once it exists at neither live/ nor archive/, must be reported "
           "SEMB_EPOCH_ENTRY_MODIFIED -- the review's own scratch construction, C1", failures)

    # ---- Construction 8 (M7, TE-170): an archived twin whose bytes differ
    # from what was archived is refused -- the discriminating half of
    # archive-by-move construction 7 does not exercise (outright deletion
    # vs. silent divergence). ----
    checkout_new_branch(repo, args.git, "construction-8", base_sha)
    fp2_live = contract.entry_dir(repo, contract.LIVE_DIR, fp2)
    fp2_archive = contract.entry_dir(repo, contract.ARCHIVE_DIR, fp2)
    fp2_archive.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(fp2_live / name, fp2_archive / name)
    shutil.rmtree(fp2_live)
    c8_archived_sha = commit_all(repo, args.git, "construction 8 commit 1: archive-by-move fp2")
    flip_one_byte(fp2_archive / contract.VECTORS_FILE_NAME)
    commit_all(repo, args.git, "construction 8 commit 2: flip a byte in the archived twin")
    out = captured_check_parent_commit(repo, c8_archived_sha)
    expect(contract.STATUS_ENTRY_MODIFIED in out and fp2 in out, "construction-8-archived-twin-diverged-refused",
           "an archived twin whose bytes differ from what was archived must be reported SEMB_EPOCH_ENTRY_MODIFIED "
           "-- the discriminating half of archive-by-move, M7", failures)

    print(f"\nepoch_store_constructions_check: 8 construction(s), {len(failures)} failure(s): {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
