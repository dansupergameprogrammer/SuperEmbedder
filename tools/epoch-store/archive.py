"""tools/epoch-store/archive.py -- TE-164 (U1 slice 3 build): archive-by-move
as a TOOL, not a discipline (`Claude/Plans/SuperEmbedder_Plan.md` sec 8,
C32: "an entry leaves the live store only by ARCHIVE-BY-MOVE ... it
appears, byte-identical, at a named archive path in the same commit that
removes it from the live store"). This tool is what makes that true by
construction, rather than leaving a builder to hand-move three files and
possibly drop one, rename one, or leave a stray byte behind: it moves the
whole entry, verifies every moved file is byte-identical to what it was
before the move, and leaves the tree in a state where a single commit
carries the pair -- the shape `tests/epoch_store_constructions_check.py`'s
own construction 5 (archive-by-move accepted) and construction 6 (deletion
without the archive twin refused) already grade, via
`tests/epoch_store_check.py`'s own check_parent_commit, unchanged.

WHAT IT DOES. Given a fingerprint hex and a repository root:
  1. Refuses (exit 1, named) if epoch-store/live/<fp>/ does not exist, is
     missing any of the three contract members, or if
     epoch-store/archive/<fp>/ already exists (never overwrites a prior
     archive entry under the same key).
  2. Moves the three member files from live/<fp>/ to archive/<fp>/
     (creating the archive directory first), verifying each file's own
     SHA-256 is unchanged after the move -- a move that silently corrupted
     a byte is a hard failure, not a printed warning.
  3. Removes the now-empty live/<fp>/ directory.
  4. Prints each moved member's own SHA-256 (unchanged before/after) so a
     caller can quote byte-identity without re-reading the files.
Leaves nothing to `git mv` guessing paths or a hand-written shell loop.

USAGE
  archive.py <fingerprint-hex> [--repo-root <dir>]

Exit codes: 0 archived; 1 refused (named); 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# The shared contract module (tests/epoch_store_contract.py) -- an IMPORT,
# never an edit, matching tests/epoch_store_check.py's own
# `sys.path.insert(0, .../tests)` convention for the identical module, so
# this tool's own path/member-name constants can never drift from the
# cells that grade its output.
_THIS_DIR = Path(__file__).resolve().parent
_TESTS_DIR = _THIS_DIR.parent.parent / "tests"
sys.path.insert(0, str(_TESTS_DIR))
import epoch_store_contract as contract  # noqa: E402


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("fingerprint_hex")
    p.add_argument("--repo-root", default=".")
    args = p.parse_args()

    fp = args.fingerprint_hex.lower()
    if not contract.is_fingerprint_dir_name(fp):
        print(f"archive.py: '{args.fingerprint_hex}' is not a 64-lowercase-hex fingerprint", file=sys.stderr)
        return 2

    repo_root = Path(args.repo_root)
    live_dir = contract.entry_dir(repo_root, contract.LIVE_DIR, fp)
    archive_dir = contract.entry_dir(repo_root, contract.ARCHIVE_DIR, fp)

    if not live_dir.is_dir():
        print(f"archive.py: refused -- no live entry at {live_dir}", file=sys.stderr)
        return 1
    missing = [name for name in contract.MEMBER_FILE_NAMES if not (live_dir / name).is_file()]
    if missing:
        print(f"archive.py: refused -- live entry at {live_dir} is missing member(s): {missing}", file=sys.stderr)
        return 1
    if archive_dir.exists():
        print(f"archive.py: refused -- an archive entry already exists at {archive_dir} "
              "(never overwrites a prior archive under the same key)", file=sys.stderr)
        return 1

    before_digests = {name: sha256_of(live_dir / name) for name in contract.MEMBER_FILE_NAMES}

    archive_dir.mkdir(parents=True, exist_ok=False)
    for name in contract.MEMBER_FILE_NAMES:
        shutil.move(str(live_dir / name), str(archive_dir / name))

    after_digests = {name: sha256_of(archive_dir / name) for name in contract.MEMBER_FILE_NAMES}
    for name in contract.MEMBER_FILE_NAMES:
        if before_digests[name] != after_digests[name]:
            print(f"archive.py: INTERNAL FAILURE -- {name} changed during the move "
                  f"(before={before_digests[name]} after={after_digests[name]})", file=sys.stderr)
            return 1

    # live/<fp>/ is now empty (its three members moved) -- remove it so the
    # entry exists at exactly one path, matching the contract's own "leaves
    # the live store only by archive-by-move" language.
    try:
        live_dir.rmdir()
    except OSError as ex:
        print(f"archive.py: moved every member but could not remove now-empty {live_dir}: {ex}", file=sys.stderr)
        return 1

    print(f"archived: {fp}")
    for name in contract.MEMBER_FILE_NAMES:
        print(f"  {name}: sha256={after_digests[name]} (byte-identical to the live entry before the move)")
    print(f"  live:    {live_dir} (removed)")
    print(f"  archive: {archive_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
