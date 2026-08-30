"""Test for ``eval/k1/tools/mint_scidocs.py`` (TE-40 code review, Finding F-14 (Minor),
`Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project records tree).

``SCIDOCS_REPO`` duplicated ``eval.k1.sets_lock.SET_REGISTRY["scidocs"]`` -- both named the
same repo id (``mteb/scidocs``), with nothing reconciling them. The fix reads the registry
directly rather than keeping a second, hand-maintained copy of the same identifier."""
from __future__ import annotations

import eval.k1.tools.mint_scidocs as mod
from eval.k1.sets_lock import SET_REGISTRY


def test_mint_scidocs_reads_the_repo_id_from_the_registry_not_a_second_hardcoded_copy():
    assert not hasattr(mod, "SCIDOCS_REPO"), (
        "mint_scidocs.py should read eval.k1.sets_lock.SET_REGISTRY['scidocs'] directly "
        "rather than keeping its own redundant hardcoded repo id"
    )
    import inspect

    source = inspect.getsource(mod.main)
    assert 'SET_REGISTRY["scidocs"]' in source
