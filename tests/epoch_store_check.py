"""tests/epoch_store_check.py -- TE-162 (U1 slice 3): the sub-plan's own
cell 1, "the store check itself" (`Claude/Plans/te140-u1-remainder-sequencing.md`
sec 4.3; `Claude/Plans/SuperEmbedder_Plan.md` sec 8, C32). Registered in
ctest, run against a repository and a build:

  (a) every LIVE entry's three members are well-formed and internally
      consistent: each row-digest.tsv line's own digest is recomputable
      from the corresponding slice of vectors.f32, and both files' own
      "all" lines are recomputable from the full blob/stream.
  (b) the entry keyed by the fingerprint the build under test emits NOW
      exists and matches, byte for byte, what that build emits -- the
      SYNTHETIC leg always; the REAL-ARTIFACT leg when --real-model and
      --real-tokenizer are configured (SEMB_C12B_MODEL / SEMB_U1_TOKENIZER,
      this suite's own established cache vars for the real Qwen3-Embedding-
      0.6B artifact).
  (c) against the PARENT commit's own epoch-store/ tree (read through
      `git show <parent-ref>:epoch-store/...`, never the working tree):
      no live entry present there was modified in HEAD, and no live entry
      present there was deleted in HEAD unless a byte-identical twin now
      exists under archive/ at the SAME fingerprint in HEAD -- AND no entry
      ALREADY under archive/ in the parent commit was modified or removed
      in HEAD (C1, TE-170): an entry may never leave archive/ either, so the
      parent's own archive/ tree is read and diffed against HEAD's the same
      way live/ is. A parent ref git cannot resolve at all (a bad ref, a
      shallow clone missing the object) is a named FAIL, distinct from a
      resolvable ref that simply carries no epoch-store/ tree yet (S5,
      TE-170).

Every outcome is a named PASS/FAIL row naming the entry and the member; the
three SEMB_EPOCH_* names (tests/epoch_store_contract.py) are the FAIL rows'
own names, per the partition that module and tests/semb_epoch_store_contract.h
both fix (see either file's own header comment for the full statement):
  - vectors.f32 and/or row-digest.tsv differ at an unchanged fingerprint,
    lineage.tsv held fixed -> SEMB_EPOCH_BYTES_DIVERGED.
  - lineage.tsv differs alone -> SEMB_EPOCH_LINEAGE_DIVERGED.
  - every member differs (a wholesale re-mint), a live entry vanished with
    no archived twin, or an ALREADY-archived entry's own bytes moved or
    vanished -> SEMB_EPOCH_ENTRY_MODIFIED. Every FAIL row names WHICH
    member(s) diverged and how (missing, or present-but-different) rather
    than one generic message (M2, TE-170).
A leg (a)/(b)/(c) never applicable at this run (no store; the real leg not
configured; nothing archived yet) reports MISSING PREREQUISITE, named,
never a silent PASS or a FAIL for a precondition this cell does not itself
own -- except an UNRESOLVABLE parent ref, which is always a FAIL (S5).

RED AT 310c47d, BY NAME: `epoch-store/` does not exist anywhere in
`--repo-root` (confirmed this round, `Claude/Mendeleev/
te142-te140-subplan-coverage-audit-2026-09-06.md` sec 1's own absent-surface
grep). Leg (a) reports "no live/ directory" (MISSING PREREQUISITE, zero
entries to check -- an empty store is not itself a defect); leg (b) reports
FAIL, named, for both the synthetic and (when configured) the real leg,
since neither fingerprint's entry exists to match; leg (c) reports MISSING
PREREQUISITE ("parent commit carries no epoch-store/ tree either") until a
first commit lands one.

INSTRUMENT COMMISSIONING (StandardsDocument.md sec 5.4): this script emits
deciding PASS/FAIL/named-status rows and is registered QUARANTINED
(`Claude/Tooling/instrument-commission.ps1 -Register`) with the constructions
population (tests/epoch_store_constructions_check.py) as its must-reject
population and the untouched-append construction as its must-accept.
Commissioning (actually running -Commission) is another seat's, per the
dispatch.

USAGE
  epoch_store_check.py --repo-root <dir> --emit-binary <path>
    --synthetic-model <.sslm> --synthetic-tokenizer <.sslm>
    --synthetic-dims <n> --synthetic-tokens <tsv>
    --synthetic-terminator-id <n> --scratch-dir <dir>
    [--real-model <.sslm> --real-tokenizer <.sslm> --real-dims <n>
     --real-tokens <tsv> --real-terminator-id <n> --real-corpus-jsonl <jsonl>]
    [--parent-ref HEAD~1]

Exit codes: 0 every evaluated row PASS or MISSING PREREQUISITE; 1 any FAIL.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import epoch_store_contract as contract  # noqa: E402 (sibling module, deliberate reuse)

g_cells = 0
g_failures = 0


def verdict(ok: bool, cell: str, observed: str) -> None:
    global g_cells, g_failures
    g_cells += 1
    if not ok:
        g_failures += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {observed}", flush=True)


def missing(cell: str, why: str) -> None:
    global g_cells
    g_cells += 1
    print(f"[MISSING PREREQUISITE] {cell}: {why}", flush=True)


def read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except OSError:
        return None


def check_entry_internal_consistency(repo_root: Path, fingerprint_hex: str) -> None:
    """Cell 1(a): one live entry's three members are well-formed and
    internally consistent, with no dependence on any artifact or build --
    pure file-format and digest arithmetic."""
    entry_dir = contract.entry_dir(repo_root, contract.LIVE_DIR, fingerprint_hex)
    label = f"live entry {fingerprint_hex}"
    vectors_path = entry_dir / contract.VECTORS_FILE_NAME
    row_digest_path = entry_dir / contract.ROW_DIGEST_FILE_NAME
    lineage_path = entry_dir / contract.LINEAGE_FILE_NAME

    vectors = read_bytes(vectors_path)
    if vectors is None:
        verdict(False, f"(1a) {label}: {contract.VECTORS_FILE_NAME} exists", f"cannot read {vectors_path}")
        return
    verdict(True, f"(1a) {label}: {contract.VECTORS_FILE_NAME} exists", f"{len(vectors)} bytes")

    try:
        row_digest_text = row_digest_path.read_text(encoding="utf-8")
    except OSError as ex:
        verdict(False, f"(1a) {label}: {contract.ROW_DIGEST_FILE_NAME} readable", str(ex))
        return
    try:
        per_doc, all_value = contract.parse_row_digest_tsv(row_digest_text)
    except ValueError as ex:
        verdict(False, f"(1a) {label}: {contract.ROW_DIGEST_FILE_NAME} well-formed", str(ex))
        return
    verdict(True, f"(1a) {label}: {contract.ROW_DIGEST_FILE_NAME} well-formed", f"{len(per_doc)} document row(s)")

    document_count = len(per_doc)
    if document_count == 0 or len(vectors) % document_count != 0:
        verdict(False, f"(1a) {label}: vectors.f32 length divides evenly by document_count",
                f"len={len(vectors)} document_count={document_count}")
        return
    row_bytes = len(vectors) // document_count
    verdict(True, f"(1a) {label}: row stride recovered", f"{row_bytes} bytes/row ({row_bytes // 4} float32 dims)")

    # Each row-digest.tsv line's own digest recomputes from vectors.f32's
    # corresponding slice, IN THE ORDER row-digest.tsv itself states.
    mismatches = 0
    for i, (doc_id, declared) in enumerate(per_doc.items()):
        row_slice = vectors[i * row_bytes:(i + 1) * row_bytes]
        actual = contract.sha256_hex(row_slice)
        if actual != declared:
            mismatches += 1
    verdict(mismatches == 0, f"(1a) {label}: every row-digest.tsv line recomputes from vectors.f32",
            f"{mismatches} of {document_count} row(s) mismatched" if mismatches else f"all {document_count} row(s) match")

    actual_all = contract.sha256_hex(vectors)
    verdict(actual_all == all_value, f"(1a) {label}: row-digest.tsv's 'all' line recomputes from vectors.f32",
            f"declared={all_value} actual={actual_all}")

    try:
        lineage_text = lineage_path.read_text(encoding="utf-8")
        lineage_per_doc, lineage_all = contract.parse_lineage_tsv(lineage_text)
        verdict(len(lineage_per_doc) == document_count,
                f"(1a) {label}: lineage.tsv carries the same document_count as row-digest.tsv",
                f"lineage={len(lineage_per_doc)} row-digest={document_count}")
        verdict(set(lineage_per_doc.keys()) == set(per_doc.keys()),
                f"(1a) {label}: lineage.tsv and row-digest.tsv name the same document ids", "checked")
    except (OSError, ValueError) as ex:
        verdict(False, f"(1a) {label}: {contract.LINEAGE_FILE_NAME} well-formed", str(ex))


def run_emit(repo_root: Path, emit_binary: str, model: str, tokenizer: str, dims: int, tokens: str,
             terminator_id: int, out_dir: Path, corpus_jsonl: Optional[str]) -> Tuple[bool, str, Dict[str, str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [emit_binary, "--model", model, "--tokenizer", tokenizer, "--dims", str(dims), "--tokens", tokens,
           "--terminator-id", str(terminator_id), "--out-dir", str(out_dir)]
    if corpus_jsonl:
        cmd += ["--corpus-jsonl", corpus_jsonl]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    fields: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            fields[k] = v
    return proc.returncode == 0, proc.stdout + proc.stderr, fields


def check_leg(repo_root: Path, emit_binary: str, label: str, model: str, tokenizer: str, dims: int, tokens: str,
              terminator_id: int, corpus_jsonl: Optional[str], scratch_dir: Path) -> None:
    """Cell 1(b): the entry keyed by this leg's own fingerprint matches
    byte for byte what the build emits now."""
    out_dir = scratch_dir / f"emit-{label}"
    ok, log, fields = run_emit(repo_root, emit_binary, model, tokenizer, dims, tokens, terminator_id, out_dir, corpus_jsonl)
    if not ok:
        verdict(False, f"(1b, {label}) epoch_store_emit succeeds", log.strip().splitlines()[-1] if log.strip() else "no output")
        return
    fingerprint_hex = fields.get("fingerprint", "")
    if not contract.is_fingerprint_dir_name(fingerprint_hex):
        verdict(False, f"(1b, {label}) epoch_store_emit reports a valid fingerprint", f"got {fingerprint_hex!r}")
        return
    verdict(True, f"(1b, {label}) build under test's own fingerprint", fingerprint_hex)

    entry_dir = contract.entry_dir(repo_root, contract.LIVE_DIR, fingerprint_hex)
    for name, status in ((contract.VECTORS_FILE_NAME, contract.STATUS_BYTES_DIVERGED),
                          (contract.ROW_DIGEST_FILE_NAME, contract.STATUS_BYTES_DIVERGED),
                          (contract.LINEAGE_FILE_NAME, contract.STATUS_LINEAGE_DIVERGED)):
        committed = read_bytes(entry_dir / name)
        emitted = read_bytes(out_dir / name)
        if committed is None:
            # RED-FIRST, BY DESIGN A FAIL (never MISSING PREREQUISITE): the
            # store's own absence is the unimplemented feature this cell
            # exists to prove exists, not an optional precondition -- see
            # tests/c2_lineage_equality_test.cpp's own identical reasoning.
            verdict(False, f"(1b, {label}) live/{fingerprint_hex}/{name} matches what the build emits now",
                    f"no live entry under {fingerprint_hex} (epoch-store/ absent or this entry not yet minted -- "
                    "the red-first state at 310c47d)")
            continue
        match = committed == emitted
        verdict(match, f"(1b, {label}) live/{fingerprint_hex}/{name} matches what the build emits now",
                "byte-identical" if match else f"{status} -- committed {len(committed)} bytes, emitted {len(emitted or b'')} bytes differ")


def git_show_tree_paths(repo_root: Path, ref: str, subtree: str) -> Optional[Dict[str, bytes]]:
    """Returns {relative-path-under-subtree: blob-bytes} for every blob
    `git ls-tree -r` finds under `subtree` at `ref`, or None if `ref` has no
    such tree at all (a distinct, non-failing state -- e.g. the parent
    commit predates the store's own first append)."""
    ls = subprocess.run(["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", ref, "--", subtree],
                         capture_output=True, text=True)
    if ls.returncode != 0 or not ls.stdout.strip():
        return None
    out: Dict[str, bytes] = {}
    for rel in ls.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        show = subprocess.run(["git", "-C", str(repo_root), "show", f"{ref}:{rel}"], capture_output=True)
        if show.returncode != 0:
            continue
        key = rel[len(subtree) + 1:] if rel.startswith(subtree + "/") else rel
        out[key] = show.stdout
    return out


def diverged_members(parent_members: Dict[str, bytes], head_dir: Path) -> List[str]:
    """Compares one entry's parent-commit bytes, member by member, against
    what is on disk at `head_dir` now. Returns a list naming each member
    that diverged -- missing entirely, or present but byte-different -- so
    a FAIL row can name WHICH member moved instead of one generic message
    (M2). An empty list means every member is present and byte-identical."""
    out: List[str] = []
    for name, parent_bytes in parent_members.items():
        head_bytes = read_bytes(head_dir / name)
        if head_bytes is None:
            out.append(f"{name} (missing)")
        elif head_bytes != parent_bytes:
            out.append(f"{name} (differs)")
    return out


def check_parent_commit(repo_root: Path, parent_ref: str) -> None:
    """Cell 1(c): no live entry the parent commit carried was modified or
    deleted-without-archive in HEAD, and no entry ALREADY under archive/ in
    the parent commit was modified or removed in HEAD either (C1: "an
    entry leaves the live store only by ARCHIVE-BY-MOVE ... an entry may
    never leave archive/" -- the destination of that move needs the same
    protection as the source, which the prior version of this check never
    read)."""
    parent_live = git_show_tree_paths(repo_root, parent_ref, contract.LIVE_DIR)
    parent_fingerprints: List[str] = []
    if parent_live is None:
        missing(f"(1c) parent commit ({parent_ref}) carries an epoch-store/live/ tree to diff against",
                "no such tree -- the store's own first append has not landed yet")
    else:
        verdict(True, f"(1c) parent commit ({parent_ref}) epoch-store/live/ tree read", f"{len(parent_live)} blob(s)")

        parent_fingerprints = sorted({k.split("/", 1)[0] for k in parent_live if "/" in k})
        for fp in parent_fingerprints:
            prefix = fp + "/"
            parent_members = {k[len(prefix):]: v for k, v in parent_live.items() if k.startswith(prefix)}
            head_entry_dir = contract.entry_dir(repo_root, contract.LIVE_DIR, fp)
            head_members: Dict[str, Optional[bytes]] = {}
            for name in contract.MEMBER_FILE_NAMES:
                head_members[name] = read_bytes(head_entry_dir / name)

            if all(v is None for v in head_members.values()):
                # Deleted from live/ entirely in HEAD -- must be archived byte-identically.
                archive_dir = contract.entry_dir(repo_root, contract.ARCHIVE_DIR, fp)
                diverged = diverged_members(parent_members, archive_dir)
                verdict(not diverged, f"(1c) {fp}: deleted from live/ has a byte-identical archive/ twin",
                        "archived" if not diverged else f"{contract.STATUS_ENTRY_MODIFIED} -- " + "; ".join(diverged))
                continue

            vectors_changed = head_members[contract.VECTORS_FILE_NAME] != parent_members.get(contract.VECTORS_FILE_NAME)
            row_digest_changed = head_members[contract.ROW_DIGEST_FILE_NAME] != parent_members.get(contract.ROW_DIGEST_FILE_NAME)
            lineage_changed = head_members[contract.LINEAGE_FILE_NAME] != parent_members.get(contract.LINEAGE_FILE_NAME)
            bytes_group_changed = vectors_changed or row_digest_changed

            if bytes_group_changed and lineage_changed:
                verdict(False, f"(1c) {fp}: live entry unchanged since parent commit",
                        f"{contract.STATUS_ENTRY_MODIFIED} -- every member differs (re-minted in place)")
            elif bytes_group_changed:
                verdict(False, f"(1c) {fp}: live entry unchanged since parent commit",
                        f"{contract.STATUS_BYTES_DIVERGED} -- vectors.f32/row-digest.tsv moved, lineage.tsv held fixed")
            elif lineage_changed:
                verdict(False, f"(1c) {fp}: live entry unchanged since parent commit",
                        f"{contract.STATUS_LINEAGE_DIVERGED} -- lineage.tsv moved alone")
            else:
                verdict(True, f"(1c) {fp}: live entry unchanged since parent commit", "byte-identical")

    # ---- C1: the archive half. Once an entry exists under archive/, it may
    # never leave -- every member the parent commit held there must still be
    # present and byte-identical in HEAD. The prior version of this check
    # read parent_live only, so a live entry archived in one commit could be
    # deleted outright, or silently edited, in a later commit with zero
    # FAIL rows anywhere. ----
    parent_archive = git_show_tree_paths(repo_root, parent_ref, contract.ARCHIVE_DIR)
    if parent_archive is None:
        missing(f"(1c) parent commit ({parent_ref}) carries an epoch-store/archive/ tree to diff against",
                "no such tree -- nothing has been archived yet")
    else:
        verdict(True, f"(1c) parent commit ({parent_ref}) epoch-store/archive/ tree read", f"{len(parent_archive)} blob(s)")
        archive_fingerprints = sorted({k.split("/", 1)[0] for k in parent_archive if "/" in k})
        for fp in archive_fingerprints:
            prefix = fp + "/"
            parent_members = {k[len(prefix):]: v for k, v in parent_archive.items() if k.startswith(prefix)}
            head_archive_dir = contract.entry_dir(repo_root, contract.ARCHIVE_DIR, fp)
            diverged = diverged_members(parent_members, head_archive_dir)
            verdict(not diverged, f"(1c) {fp}: archived entry unchanged since parent commit (an entry may never leave archive/, C1)",
                    "byte-identical" if not diverged else f"{contract.STATUS_ENTRY_MODIFIED} -- " + "; ".join(diverged))

    if parent_live is not None:
        head_fingerprints = set(contract.list_live_fingerprints(repo_root))
        new_appends = head_fingerprints - set(parent_fingerprints)
        verdict(True, "(1c) new appends since parent commit (informational, not a divergence)",
                f"{len(new_appends)} new fingerprint(s): {sorted(new_appends)}" if new_appends else "none")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", required=True)
    p.add_argument("--emit-binary", required=True)
    p.add_argument("--synthetic-model", default="", help="empty = regenerate tests/fixtures/regenerate_tokenizer_pair_fixture.py's own pair (see epoch_store_contract.ensure_synthetic_pair's own header comment for why NOT regenerate_synthetic_artifact.py's single-file fixture)")
    p.add_argument("--synthetic-tokenizer", default="")
    p.add_argument("--synthetic-dims", type=int, default=32)
    p.add_argument("--synthetic-tokens", default="tests/fixtures/c12b/synthetic-corpus.tokens.tsv")
    p.add_argument("--synthetic-terminator-id", type=int, default=262,
                    help="regenerate_tokenizer_pair_fixture.py's own <|endoftext|> id; the c12b fixture's ids (max 127) fit its 384-entry vocab")
    p.add_argument("--scratch-dir", required=True)
    p.add_argument("--real-model", default="", help="SEMB_C12B_MODEL; empty = the real-artifact leg is MISSING PREREQUISITE")
    p.add_argument("--real-tokenizer", default="", help="SEMB_U1_TOKENIZER")
    p.add_argument("--real-dims", type=int, default=1024)
    p.add_argument("--real-tokens", default="tests/fixtures/c12b/corpus-239.tokens.tsv")
    p.add_argument("--real-terminator-id", type=int, default=151643,
                    help="corpus-239.manifest.json's own appended_token_id")
    p.add_argument("--real-corpus-jsonl", default="tests/fixtures/c12b/corpus-239.jsonl")
    p.add_argument("--parent-ref", default="HEAD~1")
    args = p.parse_args()

    repo_root = Path(args.repo_root)
    scratch_dir = Path(args.scratch_dir)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # ---- (a) internal consistency of every live entry actually present. ----
    live_fingerprints = contract.list_live_fingerprints(repo_root)
    if not live_fingerprints:
        missing("(1a) at least one live entry exists to check", "epoch-store/live/ is absent or empty at this repo root")
    else:
        for fp in live_fingerprints:
            check_entry_internal_consistency(repo_root, fp)

    # ---- (b) synthetic leg, always. ----
    synthetic_model = args.synthetic_model
    synthetic_tokenizer = args.synthetic_tokenizer
    if not synthetic_model or not synthetic_tokenizer:
        try:
            pair_model, pair_tokenizer = contract.ensure_synthetic_pair(repo_root)
            synthetic_model = synthetic_model or pair_model
            synthetic_tokenizer = synthetic_tokenizer or pair_tokenizer
        except RuntimeError as ex:
            verdict(False, "(1b, synthetic) regenerate the synthetic tokenizer-capable pair", str(ex))
            synthetic_model = ""
    if synthetic_model:
        check_leg(repo_root, args.emit_binary, "synthetic", synthetic_model, synthetic_tokenizer,
                  args.synthetic_dims, args.synthetic_tokens, args.synthetic_terminator_id, None, scratch_dir)

    # ---- (b) real-artifact leg, when configured. ----
    if args.real_model and args.real_tokenizer:
        check_leg(repo_root, args.emit_binary, "real_artifact", args.real_model, args.real_tokenizer, args.real_dims,
                  args.real_tokens, args.real_terminator_id, args.real_corpus_jsonl or None, scratch_dir)
    else:
        missing("(1b, real_artifact) leg runs", "--real-model/--real-tokenizer not configured (MISSING PREREQUISITE, not a FAIL)")

    # ---- (c) parent-commit diff. ----
    check_parent_commit(repo_root, args.parent_ref)

    print(f"\nepoch_store_check: {g_cells} cell(s), {g_failures} failure(s)")
    return 1 if g_failures else 0


if __name__ == "__main__":
    sys.exit(main())
