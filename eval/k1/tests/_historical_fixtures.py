"""Shared historical fixtures for the K1 instrument's tests -- not a test module itself (no
`test_` functions; not collected by pytest's default discovery).

TE-57 review, L-7 (Observation): `_SEVEN_FILE_TUPLE_AT_6317E68` used to be defined twice,
identically, in `test_component_partition.py` and `test_recommissioning_gap.py`. Both copies
pin the same historical fact -- the commissioned-component tuple as it stood at `6317e68`,
before TE-55's K-1 (Significant) completed it to the design's real fifteen-file set -- and two
identical literals with nothing comparing them can drift silently if one is ever edited without
the other. One definition, imported by both, removes that possibility structurally."""
from __future__ import annotations

# The seven-file component tuple as it stood at 6317e68 (TE-55's own review target), before
# K-1's fix completed it to the design's real fifteen-file component set. Fixed here as a
# LITERAL list -- not `eval.k1.COMMISSIONED_COMPONENT_FILES` -- so every historical-reproduction
# test importing this keeps pinning the same historical fact regardless of how the live tuple
# grows (TE-55 review, K-4 (Minor)).
SEVEN_FILE_TUPLE_AT_6317E68 = (
    "eval/k1/bm25_baseline.py",
    "eval/k1/embed_runner.py",
    "eval/k1/gate.py",
    "eval/k1/guards.py",
    "eval/k1/rank_score.py",
    "eval/k1/runner.py",
    "eval/k1/sets_lock.py",
)
