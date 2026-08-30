"""The locked-set roster names -- ``PUBLIC_SETS``, ``INTERNAL_DIAGNOSTIC_SETS``,
``ALL_LOCKED_SETS`` -- as a leaf module with no imports beyond ``__future__``, so reading the
roster never pulls in the embedding stack.

**TE-40 review, F-7 (Significant, `Claude/Poirot/41424b0-te40-k1-instrument-review.md`).**
Before this module existed, `gate.py` read `ALL_LOCKED_SETS` from `run_spec.py`, and
`run_spec.py` imports `embed_runner.py`, which imports `torch` and `numpy`. Importing
`gate.py` -- the one module whose job is reading a JSON packet and computing pass/fail --
therefore pulled the entire CUDA-era embedding stack for a five-element tuple of strings
(measured: `gate.py` had zero first-party imports at commit `0003151`; at `41424b0`,
`import eval.k1.gate` took 2.74s and left `torch`/`numpy` resident). `run_spec.py`
re-exports these three names (`from eval.k1.set_roster import ...`), so nothing importing
`run_spec.PUBLIC_SETS`/`run_spec.ALL_LOCKED_SETS`/etc. has to change; `gate.py` imports
directly from here instead, restoring its dependency-free import.

Design reference: `te33-k1-gate-design-2026-08-25.md` Section 16 (the publishable-set
disposition, SCIDOCS specified as the fifth locked set).
"""
from __future__ import annotations

# Design Section 16 / D-SLM4686: which of Run 1's five sets carry the public-facing row and
# which are retained as internal diagnostics (still run, still gating F1/F2 internally, but
# never surfaced as a public product claim -- their license is ambiguous on publication, not
# on local evaluation). Both groups gate identically; this split is legibility only.
PUBLIC_SETS = ("scifact", "arguana", "scidocs")
INTERNAL_DIAGNOSTIC_SETS = ("nfcorpus", "fiqa")

# The full locked-set roster the design's aggregation rule (Section 4.3, amended by Section
# 16) requires F1 and F2 to hold on -- both groups above gate identically, so this is their
# union, not a third list maintained by hand. `gate.py::GATE_REQUIRED_SETS`,
# `sets_lock.py::SET_REGISTRY`'s keys, and `sets.lock.json`'s own keys are all reconciled
# against this tuple by `tests/test_roster_lock_reconciliation.py` (TE-40 review, F-5).
ALL_LOCKED_SETS = PUBLIC_SETS + INTERNAL_DIAGNOSTIC_SETS
