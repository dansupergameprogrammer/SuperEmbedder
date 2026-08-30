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
from *runs* to *refuses*. ``main()`` carries a set's ``license``/``license_source``/
``license_derived`` forward from the existing entry whenever the fresh fetch cannot supply
them (which is always, for license -- the fetch has no license step at all), so a re-mint can
never regress a license a prior derivation already landed.

**TE-44 review, G-4:** F-9's original remedy hand-wrote the carry-forward for the license
group only. ``SetLockEntry`` carries a second, identically-shaped ``*_derived`` group -- BM25
parameters (``bm25_k1``/``bm25_b``/``bm25_params_derived``) -- that ``_fetch_one_set`` also
never supplies (``sets_lock.py``: always returns ``bm25_params_derived=False`` with BEIR's
stated defaults), and the license-only fix left it uncovered. It fails worse than license did:
a blanked license flips the gate loudly (``check_license_present`` refuses); a blanked BM25
parameter is silently replaced by a plausible non-``None`` default, so
``check_bm25_params_present`` (which only tests for ``None``) stays green while the gate
scores against BEIR defaults instead of derived values. ``DERIVED_FIELD_GROUPS`` below names
every such group once; ``main()`` carries forward whichever groups a re-mint would otherwise
regress, so a third group added to ``SetLockEntry`` in the future is covered by adding one
entry here rather than a third hand-written clause.
"""
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1.sets_lock import mint_sets_lock, read_sets_lock, write_sets_lock

LOCK_PATH = Path(__file__).resolve().parents[1] / "sets.lock.json"

# Every ``SetLockEntry`` field group that carries its own ``*_derived`` provenance flag,
# mapped to the flag field plus every field the flag governs (TE-44 review, G-4). A re-mint's
# fresh fetch never supplies a group whose derivation this fetch has no step for -- it always
# reports that group's ``*_derived`` flag as ``False`` -- so a group already derived on the
# existing entry is carried forward whole rather than blanked by ``existing.update(fresh)``.
DERIVED_FIELD_GROUPS: Dict[str, List[str]] = {
    "license_derived": ["license", "license_source", "license_derived"],
    "bm25_params_derived": ["bm25_k1", "bm25_b", "bm25_params_derived"],
}


def main() -> None:
    names = sys.argv[1:] or None
    existing = read_sets_lock(LOCK_PATH) if LOCK_PATH.exists() else {}
    fresh = mint_sets_lock(names)
    for name, entry in fresh.items():
        old = existing.get(name)
        if old is None:
            continue
        for flag_field, group_fields in DERIVED_FIELD_GROUPS.items():
            if getattr(old, flag_field) and not getattr(entry, flag_field):
                # This group was already derived on the existing entry and the fresh fetch
                # cannot supply it -- never let a re-mint regress a group a prior derivation
                # already landed (TE-40 review, F-9; TE-44 review, G-4).
                for field_name in group_fields:
                    setattr(entry, field_name, getattr(old, field_name))
    existing.update(fresh)
    write_sets_lock(existing, LOCK_PATH)
    for name, entry in existing.items():
        print(f"{name}: corpus={entry.corpus_docs} queries_test={entry.queries_test} "
              f"qrels_test_rows={entry.qrels_test_rows} revision={entry.revision}")
    print(f"written {LOCK_PATH}")


if __name__ == "__main__":
    main()
