"""tests/epoch_store_constructions_check.py -- TE-162 (U1 slice 3): the
sub-plan's own cell 2, "the four able-to-fail constructions" plus "the
lifecycle pair" (`Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.3;
`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C32's own able-to-fail list,
quoted verbatim in the dispatch), extended by TE-170's own review-fix round
with construction 7 (C1: an archived entry deleted outright), construction
8 (M7: an archived twin whose bytes diverge), construction 9 (S5: an
unresolvable parent ref), and constructions 10-11 (M6: the builder's real
`tools/epoch-store/archive.py` driven as a subprocess, green, paired with
a raw deletion that bypasses it, red), further extended by TE-180's own
bare-cell round (D-SLM6428 cell B) with construction 12 (M11: every live
entry archived, not the store's first append). Twelve constructions, each
executed against `epoch_store_check.py`'s own parent-commit logic (cell
1(c)) in a
SCRATCH git repository this script builds under the build directory --
never the product repository, never a hand-fabricated byte blob standing
in for a commit.

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
  3. an entry re-minted in place (fp1's three files each get one byte
     flipped, together -- every member moves, distinct from constructions
     1 and 2, which each move exactly one member group) -> SEMB_EPOCH_ENTRY_MODIFIED
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
  9. (S5, TE-170) an unresolvable --parent-ref ("deadbee", no such object in
     ANY repository) -> a named FAIL, never the MISSING PREREQUISITE state
     a resolvable-but-treeless ref reports.
  10. (M6, TE-170) the real tools/epoch-store/archive.py tool, run as a
      subprocess against the scratch repository, archives fp4 (commit 1
      appends it, then archive.py moves it in commit 2) -> accepted (no
      FAIL rows), against commit 1 as the parent.
  11. (M6, TE-170) fp5 deleted directly, bypassing archive.py entirely (no
      archive/ twin) -> SEMB_EPOCH_ENTRY_MODIFIED against commit 1 as the
      parent -- the red pairing for construction 10's green.
  12. (M11, TE-174; bare cell B, TE-180, D-SLM6428) every live entry
      archived: commit 1 archives BOTH fp1 and fp2 (by move, together, from
      the base commit) so the parent's own live/ tree is absent because
      everything was archived, never because the store has not seen a
      first append; commit 2 is an unrelated ordinary append (fp3) -> the
      (1c) message, read against commit 1 as the parent, must name "every
      live entry has been archived (2 fingerprint(s) under archive/); this
      is not the store's first append," distinct by string from the
      genuinely-first-append message, and zero FAIL rows.

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
FP4_FIXED = "0" * 63 + "3"   # M6, TE-170: the archive.py-tool-driven pair
FP5_FIXED = "0" * 63 + "4"


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


def add_shared_args(p: argparse.ArgumentParser) -> None:
    """The base-repo setup's own flags, shared verbatim by this script's
    --leg-less `main()` and by the independent commissioning-leg script
    that imports build_base_repo() for the must-accept/must-reject pair
    TE-162-epoch-store-check's own registration needs (D-SLM6427/D-SLM6433
    ruling 1; D-SLM6466 ruling 1 moves that script to
    `Claude/Mendeleev/te189-probes/`, outside tests/, authored independently
    of this module's own builder) -- one definition, so the two scripts
    cannot drift on a default."""
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


class BaseRepo:
    """The scratch git repository this suite mutates, and its BASE commit:
    fp1 (a real, emit-minted entry) + fp2 (a byte-identical copy under a
    distinct key) -- see build_base_repo()'s own docstring. fp3/fp4/fp5 are
    reserved, fixed-shape fingerprints distinct from fp1/fp2 and from each
    other, minted by no tool, for constructions that need a THIRD/FOURTH/
    FIFTH key (never pre-populated in the base commit; a construction that
    wants one under live/ copies fp1's or fp2's own bytes to it itself)."""

    def __init__(self, repo: Path, git: str, repo_root: Path, base_sha: str,
                 fp1: str, fp2: str, fp3: str, fp4: str, fp5: str) -> None:
        self.repo = repo
        self.git = git
        self.repo_root = repo_root
        self.base_sha = base_sha
        self.fp1 = fp1
        self.fp2 = fp2
        self.fp3 = fp3
        self.fp4 = fp4
        self.fp5 = fp5


def build_base_repo(args) -> BaseRepo:
    """Mints fp1 for real (the SAME support tool cell 1(b) uses), builds a
    fresh scratch git repository, and commits the BASE state every
    construction branches from: fp1 (real, minted) + fp2 (a byte-identical
    copy of fp1 under a second, fixed, distinct key) -- see this module's
    own header comment, "THE SCRATCH REPO," for the full rationale (two
    genuinely well-formed entries under two different keys is enough to
    prove append-only/archive-by-move/the three divergence statuses,
    without needing a second real artifact).

    Shared by this script's own main() (the twelve-construction population)
    and by the independent commissioning-leg script under
    `Claude/Mendeleev/te189-probes/` (D-SLM6466 ruling 1) that imports this
    function for the must-accept/must-reject pair TE-162-epoch-store-check's
    own registration needs as two literal, independently-exit-coded commands
    (D-SLM6427/D-SLM6433) -- ONE base-repo setup, so the population both
    scripts build on top of cannot drift.

    Raises RuntimeError, with the same [FAIL] (setup) ... text main() used
    to print inline, on any setup failure -- the caller decides what that
    means for its own exit code (main() below returns 1; the commission-leg
    script's own accept/reject exit mapping, D-SLM6433 ruling 1, differs by
    leg and is that script's own to apply)."""
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
            raise RuntimeError(f"(setup) regenerate the synthetic tokenizer-capable pair: {ex}") from ex

    # ---- Mint fp1 for real, via the SAME support tool cell 1(b) uses. ----
    proc = subprocess.run(
        [args.emit_binary, "--model", synthetic_model, "--tokenizer", synthetic_tokenizer, "--dims",
         str(args.synthetic_dims), "--tokens", args.synthetic_tokens, "--terminator-id",
         str(args.synthetic_terminator_id), "--out-dir", str(emit_out), "--doc-ids", args.doc_id],
        cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"(setup) epoch_store_emit mints fp1: {proc.stdout}\n{proc.stderr}")
    fp1 = ""
    for line in proc.stdout.splitlines():
        if line.startswith("fingerprint="):
            fp1 = line.split("=", 1)[1]
    if not contract.is_fingerprint_dir_name(fp1):
        raise RuntimeError(f"(setup) epoch_store_emit reports a valid fingerprint: got {fp1!r}")
    fp2 = FP2_FIXED if FP2_FIXED != fp1 else "1" * 64
    fp3 = FP3_FIXED if FP3_FIXED not in (fp1, fp2) else "2" * 64
    fp4 = FP4_FIXED if FP4_FIXED not in (fp1, fp2, fp3) else "3" * 64
    fp5 = FP5_FIXED if FP5_FIXED not in (fp1, fp2, fp3, fp4) else "4" * 64
    print(f"[PASS] (setup) fp1 minted: {fp1}", flush=True)

    # ---- Build the scratch repo and its BASE commit: fp1 (real) + fp2
    # (a byte-identical copy under a distinct key). ----
    git_init_repo(repo, args.git)
    contract.entry_dir(repo, contract.LIVE_DIR, fp1).mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(emit_out / name, contract.entry_dir(repo, contract.LIVE_DIR, fp1) / name)
    copy_entry(repo, fp1, fp2)
    base_sha = commit_all(repo, args.git, "base: two well-formed live entries")
    print(f"[PASS] (setup) base commit with fp1+fp2: {base_sha}", flush=True)

    return BaseRepo(repo, args.git, repo_root, base_sha, fp1, fp2, fp3, fp4, fp5)


def main() -> int:
    p = argparse.ArgumentParser()
    add_shared_args(p)
    args = p.parse_args()

    try:
        base = build_base_repo(args)
    except RuntimeError as ex:
        print(f"[FAIL] {ex}")
        return 1
    repo, git, repo_root = base.repo, base.git, base.repo_root
    base_sha, fp1, fp2, fp3, fp4, fp5 = base.base_sha, base.fp1, base.fp2, base.fp3, base.fp4, base.fp5

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

    # ---- Construction 9 (S5, TE-170): an unresolvable parent ref is a
    # named FAIL, never the same MISSING PREREQUISITE state a resolvable
    # ref carrying no epoch-store/ tree yet reports. No new commit needed
    # -- the ref itself is what does not resolve, in ANY repository. ----
    out = captured_check_parent_commit(repo, "deadbee")
    expect("FAIL" in out and "ref resolves" in out, "construction-9-unresolvable-parent-ref-is-a-fail",
           "a --parent-ref git cannot resolve at all must be a named FAIL (S5)", failures)
    expect("MISSING PREREQUISITE" not in out, "construction-9-not-conflated-with-first-append",
           "must not be reported as the resolvable-ref-no-tree-yet 'first append has not landed' state", failures)

    # ---- Construction 10 (M6, TE-170; oracle corrected S9, TE-174): the
    # builder's real archive.py tool, run against the scratch repository,
    # archives an entry -- proving the check against the TOOL's own real
    # data path, not this script's hand-rolled copy+rmtree every other
    # construction above uses. archive.py is read-only to this seat; it is
    # invoked as a subprocess, never modified.
    #
    # S9, TE-174: the prior oracle ("FAIL" not in out and fp4 in out) is a
    # property of check_parent_commit's OWN OUTPUT, not of what archive.py
    # actually did to the tree -- a mutant tool that COPIES the three
    # members to archive/<fp4>/ and never removes live/<fp4>/ (dropping
    # step 3 of the tool's own header comment) leaves live/<fp4>/ in place,
    # yet the check still reports zero FAIL rows against a parent commit
    # that has nothing archived yet (MISSING PREREQUISITE, not a FAIL), so
    # the old oracle would say True on a tool that never archived anything.
    # The fix asserts the archive tool's OWN documented postcondition
    # directly, from raw bytes read off the filesystem before and after the
    # tool runs, never from the tool's own printed output: live/<fp4>/ is
    # gone, archive/<fp4>/ holds all three members, and every one is
    # byte-identical to what lived under live/<fp4>/ before the tool ran --
    # captured here independently of the tool's own printed digests, so a
    # tool that also miscomputes what it prints cannot pass by agreeing
    # with itself (M13, TE-176: the prior wording of this comment claimed
    # the assertion reads the tool's OWN printed SHA-256 values, which the
    # code below never does). ----
    checkout_new_branch(repo, args.git, "construction-10", base_sha)
    copy_entry(repo, fp1, fp4)
    c10_base_sha = commit_all(repo, args.git, "construction 10 commit 1: append fp4 (to be archived by the real tool)")
    fp4_live_dir = contract.entry_dir(repo, contract.LIVE_DIR, fp4)
    fp4_archive_dir = contract.entry_dir(repo, contract.ARCHIVE_DIR, fp4)
    fp4_before_bytes = {name: (fp4_live_dir / name).read_bytes() for name in contract.MEMBER_FILE_NAMES}
    archive_tool = repo_root / "tools" / "epoch-store" / "archive.py"
    archive_proc = subprocess.run([sys.executable, str(archive_tool), fp4, "--repo-root", str(repo)],
                                   capture_output=True, text=True)
    if archive_proc.returncode != 0:
        expect(False, "construction-10-archive-tool-succeeds",
               f"tools/epoch-store/archive.py exited {archive_proc.returncode}: "
               f"{archive_proc.stdout}{archive_proc.stderr}", failures)
    else:
        commit_all(repo, args.git, "construction 10 commit 2: archive.py moved fp4 to archive/")
        # The tool's own documented postcondition (S9): the live entry is
        # gone and the archive entry holds every member, byte-identical to
        # what was under live/ before the tool ran -- checked directly
        # against the filesystem, not inferred from the checker's summary.
        live_gone = not fp4_live_dir.exists()
        expect(live_gone, "construction-10-live-entry-removed",
               f"archive.py must remove live/{fp4}/ once every member is moved -- {fp4_live_dir} "
               f"{'is gone' if live_gone else 'still exists'}", failures)
        archive_members_ok = fp4_archive_dir.is_dir() and all(
            (fp4_archive_dir / name).is_file() and (fp4_archive_dir / name).read_bytes() == fp4_before_bytes[name]
            for name in contract.MEMBER_FILE_NAMES)
        expect(archive_members_ok, "construction-10-archive-entry-byte-identical",
               f"archive/{fp4}/ must hold all three members, each byte-identical to live/{fp4}/'s own bytes "
               "before the move -- a move that corrupts or drops a member's bytes in transit must fail this, "
               "S9 (M12, TE-176: a copy-only tool that leaves live/ in place fails the sibling assertion "
               "above, construction-10-live-entry-removed, not this one)", failures)
        # The checker's own read is still worth confirming (a real move it
        # cannot see would be its own defect), but per S9 it is no longer
        # the sole oracle -- the two assertions above are what a copy-only
        # mutant cannot pass.
        out = captured_check_parent_commit(repo, c10_base_sha)
        expect("FAIL" not in out and fp4 in out, "construction-10-archive-tool-accepted-by-checker",
               "an entry archived by the real archive.py tool (not this script's hand-rolled move) must be "
               "accepted (no FAIL rows) by the checker's own read -- M6", failures)

    # ---- Construction 11 (M6, TE-170): a raw deletion that bypasses
    # archive.py entirely (no archive/ twin at all) is refused -- pairs
    # construction 10's green, tool-driven path with a red one that skips
    # the tool. archive.py itself has no deletion mode (its only two
    # branches are "move to archive/, verified" and a named refusal, per
    # its own header comment) -- there is no "tool's own deletion path" to
    # invoke, so a raw filesystem deletion is the only way to construct
    # "the check must refuse a live entry removed without the tool ever
    # running." This is deliberately the same mutation shape construction
    # 6 already exercises (a live entry removed with no archive/ twin);
    # kept here as its own construction because M6's own pairing is
    # tool-driven-accept (10) beside non-tool-driven-refuse (11), not
    # because the check's refusal logic differs by construction -- S9's
    # own gap was specific to construction 10's oracle, never to this
    # one's. ----
    checkout_new_branch(repo, args.git, "construction-11", base_sha)
    copy_entry(repo, fp1, fp5)
    c11_base_sha = commit_all(repo, args.git, "construction 11 commit 1: append fp5")
    shutil.rmtree(contract.entry_dir(repo, contract.LIVE_DIR, fp5))
    commit_all(repo, args.git, "construction 11 commit 2: delete fp5 directly, bypassing archive.py")
    out = captured_check_parent_commit(repo, c11_base_sha)
    expect(contract.STATUS_ENTRY_MODIFIED in out and fp5 in out, "construction-11-raw-deletion-refused",
           "deleting a live entry directly, without running archive.py, must be reported "
           "SEMB_EPOCH_ENTRY_MODIFIED -- M6's own red pairing for construction 10's green", failures)

    # ---- Construction 12 (M11, TE-174; bare cell B, TE-180, D-SLM6428): the
    # parent commit's own live/ tree is ABSENT because every live entry has
    # been archived, not because the store has never seen a first append --
    # (1c)'s own message must distinguish the two, by string. Commit 1
    # archives BOTH fp1 and fp2 (by move, in ONE commit, from the base
    # commit) -- unlike constructions 5/7/8, which each archive fp2 alone
    # and always leave fp1 live, so the parent commit's own live/ tree is
    # never empty in any of constructions 1-11 (TE-177's own audit finding,
    # item 2). Commit 2 is an ordinary, unrelated append (fp3, copied from
    # fp1's own now-archived bytes -- fp1's live/ copy is gone after commit
    # 1, so fp3 is minted from the snapshot taken before the move) -- new
    # appends since the parent commit are informational and must not
    # disturb the message this construction exists to pin. The check then
    # runs with commit 1 (the fully-archived state) as --parent-ref, never
    # commit 2 -- exactly the shape M11's own fix reads (a parent commit
    # whose live/ tree is absent, diffed against a later HEAD). ----
    checkout_new_branch(repo, args.git, "construction-12", base_sha)
    fp1_live_dir = contract.entry_dir(repo, contract.LIVE_DIR, fp1)
    fp1_bytes = {name: (fp1_live_dir / name).read_bytes() for name in contract.MEMBER_FILE_NAMES}
    fp1_archive_dir = contract.entry_dir(repo, contract.ARCHIVE_DIR, fp1)
    fp1_archive_dir.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(fp1_live_dir / name, fp1_archive_dir / name)
    shutil.rmtree(fp1_live_dir)
    fp2_live_dir = contract.entry_dir(repo, contract.LIVE_DIR, fp2)
    fp2_archive_dir = contract.entry_dir(repo, contract.ARCHIVE_DIR, fp2)
    fp2_archive_dir.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.copyfile(fp2_live_dir / name, fp2_archive_dir / name)
    shutil.rmtree(fp2_live_dir)
    c12_archived_all_sha = commit_all(repo, args.git, "construction 12 commit 1: archive-by-move every live entry (fp1 and fp2)")
    out_archived_all = captured_check_parent_commit(repo, base_sha)
    expect("FAIL" not in out_archived_all and fp1 in out_archived_all and fp2 in out_archived_all,
           "construction-12-archive-both-still-accepted",
           "commit 1 (archive-by-move both fp1 and fp2 against the base commit as parent) must still be accepted, "
           "matching construction 5 applied twice", failures)
    fp3_live_dir = contract.entry_dir(repo, contract.LIVE_DIR, fp3)
    fp3_live_dir.mkdir(parents=True, exist_ok=True)
    for name in contract.MEMBER_FILE_NAMES:
        (fp3_live_dir / name).write_bytes(fp1_bytes[name])
    commit_all(repo, args.git, "construction 12 commit 2: append fp3 (an ordinary, unrelated append)")
    out = captured_check_parent_commit(repo, c12_archived_all_sha)
    expect("FAIL" not in out, "construction-12-no-fail-rows",
           "diffing the fp3-append commit against the fully-archived parent must produce zero FAIL rows "
           "(the archive/ half is unchanged between the two commits; fp3 is a new, informational append)", failures)
    expect("every live entry has been archived (2 fingerprint(s) under archive/)" in out and
           "this is not the store's first append" in out,
           "construction-12-archived-everything-message",
           "the (1c) parent-live-tree-absent message must read 'every live entry has been archived "
           "(2 fingerprint(s) under archive/); this is not the store's first append' -- distinct, by string, "
           "from the genuinely-first-append message (M11, TE-174)", failures)
    expect("store's own first append has not landed yet" not in out, "construction-12-not-conflated-with-first-append",
           "must not ALSO/instead report the genuinely-first-append message", failures)

    total_constructions = 12
    print(f"\nepoch_store_constructions_check: {total_constructions} construction(s), {len(failures)} failure(s): {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
