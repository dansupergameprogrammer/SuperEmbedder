#!/usr/bin/env python3
"""Re-runs the fetch that produces ``eval/k1/sets.lock.json``. Executed 2026-08-25 to
produce the committed lock file; re-run only to refresh pins (e.g. after a license is
derived by Linnaeus and needs writing into the lock).

Usage:
    py -3.13 eval/k1/tools/mint_sets_lock.py [set_name ...]

With no arguments, mints all four sets (design Section 2). Merges into the existing
sets.lock.json rather than overwriting sets not named.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1.sets_lock import mint_sets_lock, read_sets_lock, write_sets_lock

LOCK_PATH = Path(__file__).resolve().parents[1] / "sets.lock.json"


def main() -> None:
    names = sys.argv[1:] or None
    existing = read_sets_lock(LOCK_PATH) if LOCK_PATH.exists() else {}
    fresh = mint_sets_lock(names)
    existing.update(fresh)
    write_sets_lock(existing, LOCK_PATH)
    for name, entry in existing.items():
        print(f"{name}: corpus={entry.corpus_docs} queries_test={entry.queries_test} "
              f"qrels_test_rows={entry.qrels_test_rows} revision={entry.revision}")
    print(f"written {LOCK_PATH}")


if __name__ == "__main__":
    main()
