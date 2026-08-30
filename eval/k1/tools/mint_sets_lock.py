#!/usr/bin/env python3
"""Re-runs the fetch that produces ``eval/k1/sets.lock.json``. Executed 2026-08-25 to
produce the committed lock file; re-run only to refresh pins (e.g. after a license is
derived by Linnaeus and needs writing into the lock).

Usage:
    py -3.13 eval/k1/tools/mint_sets_lock.py [set_name ...]

With no arguments, mints every set in ``eval.k1.sets_lock.SET_REGISTRY`` (design Section 2's
four sets plus Section 16's SCIDOCS amendment). Merges into the existing sets.lock.json
rather than overwriting sets not named.

``_fetch_one_set`` always returns ``license=None, license_derived=False`` -- the fetch has no
license step, design Section 2.4 routes that to the deriver. **TE-40 review, F-9:** before
this fix, ``main()`` merged a fresh fetch's ``license=None`` straight over an existing entry's
already-derived license, so a bare re-mint silently blanked every named set's license back
out -- taking every real gate path (``sets_lock.load_set``'s ``check_license_present`` guard)
from *runs* to *refuses*. ``main()`` now carries a set's ``license``/``license_source``/
``license_derived`` forward from the existing entry whenever the fresh fetch cannot supply
them (which is always, for license -- the fetch has no license step at all), so a re-mint can
never regress a license a prior derivation already landed.
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
    for name, entry in fresh.items():
        old = existing.get(name)
        if old is not None and old.license_derived and not entry.license_derived:
            # The fetch has no license step (design Section 2.4 routes that to the deriver)
            # -- it always returns license=None, license_derived=False. Never let a re-mint
            # regress a license a prior derivation already landed (TE-40 review, F-9).
            entry.license = old.license
            entry.license_source = old.license_source
            entry.license_derived = old.license_derived
    existing.update(fresh)
    write_sets_lock(existing, LOCK_PATH)
    for name, entry in existing.items():
        print(f"{name}: corpus={entry.corpus_docs} queries_test={entry.queries_test} "
              f"qrels_test_rows={entry.qrels_test_rows} revision={entry.revision}")
    print(f"written {LOCK_PATH}")


if __name__ == "__main__":
    main()
