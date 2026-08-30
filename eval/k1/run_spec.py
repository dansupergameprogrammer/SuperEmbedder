"""Run specs -- the roster and parameters for Run 0 (scout), Run 1 (full protocol), and the
smoke run, all executed by the same code path (``runner.py``), per the build brief: "the
runner takes a run spec so both are the same code path."

Design reference: te33-k1-gate-design-2026-08-25.md Section 1 (Run 0/1/2), Section 7.1
(measured throughput and the batch sizes it justifies), Section 9.1 (the Qwen3-Embedding-0.6B
and Q-A1 pooling-variant roster additions), Section 16 (SCIDOCS as the publishable-set
substitute for NFCorpus and FiQA-2018 on Run 1's public row).

Model revisions below are pinned commit shas resolved via HfApi.model_info() this session
(2026-08-25) against the local D:\\hf_cache resident snapshots -- see the build log for the
resolution command and output.

**TE-39, 2026-08-30: Run 1's set list and model roster, updated post-scout.** The scout
(Run 0, D-SLM4710) resolvably killed both pooled Qwen2.5-Instruct incumbents and D-SLM4719
ratified Qwen3-Embedding-0.6B as the sole 1.0 candidate, retiring the incumbents outright
(D-SLM4723 reduces K1-Run-1's roster to Qwen3-Embedding-0.6B alone against the reference and
BM25). SCIDOCS was minted (design Section 16, D-SLM4705/D-SLM4686) as the fifth set: NFCorpus
and FiQA-2018 carry an ambiguous publication license and are retained as **internal
diagnostics** -- still run, still gating F1/F2 -- while SCIDOCS carries the **public row** in
their place, alongside SciFact and ArguAna. ``PUBLIC_SETS`` and ``INTERNAL_DIAGNOSTIC_SETS``
below name this split so a caller (or the launcher script that composes a run's packet) can
label each set's readings without re-deriving the disposition from the design prose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from eval.k1.embed_runner import ModelSpec, POOLING_NATIVE, POOLING_PS1_PRE_NORM, POOLING_PS2_POST_NORM
from eval.k1.set_roster import ALL_LOCKED_SETS, INTERNAL_DIAGNOSTIC_SETS, PUBLIC_SETS

# Pinned revisions (HfApi.model_info().sha, resolved 2026-08-25).
QWEN25_1_5B_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
QWEN25_0_5B_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
QWEN3_EMB_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
BGE_SMALL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"

QWEN3_EMB_QUERY_PROMPT = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query:"
)

# Design Section 16 / D-SLM4686: which of Run 1's five sets carry the public-facing row and
# which are retained as internal diagnostics (still run, still gating F1/F2 internally, but
# never surfaced as a public product claim -- their license is ambiguous on publication, not
# on local evaluation). Both groups gate; this split is legibility only.
#
# TE-40 review, F-7: these three names -- and their single source of truth -- now live in
# `eval.k1.set_roster`, a leaf module with no imports, so reading them never pulls in the
# embedding stack this module (`run_spec.py`) needs for its own `ModelSpec` roster. Imported
# here (not redefined) so every existing `run_spec.PUBLIC_SETS` /
# `run_spec.ALL_LOCKED_SETS` reference keeps working unchanged. `gate.py::GATE_REQUIRED_SETS`
# reads `set_roster.ALL_LOCKED_SETS` directly rather than through this re-export: a set added
# to either group in `set_roster.py` by a future amendment is required by the gate the moment
# it is added there, with no second edit.

MAX_LENGTH = 512  # design Section 7.1: the decided setting

# Batch sizes at the 512-token cell (design Section 7.1's measured table); Qwen3-Embedding
# has no measured rate (Section 7.2's [A] scaling note) -- 8 is a conservative choice
# between the 0.5B and 1.5B measured batch sizes, stated here rather than measured.
BATCH_1_5B = 4
BATCH_0_5B = 8
BATCH_QWEN3_EMB = 8
BATCH_BGE_SMALL = 64


def qwen25_1_5b(pooling: str, suffix: str) -> ModelSpec:
    return ModelSpec(
        name=f"qwen2.5-1.5b-instruct-{suffix}", hf_repo="Qwen/Qwen2.5-1.5B-Instruct",
        revision=QWEN25_1_5B_REVISION, pooling=pooling, batch_size=BATCH_1_5B, max_length=MAX_LENGTH,
    )


def qwen25_0_5b(pooling: str, suffix: str) -> ModelSpec:
    return ModelSpec(
        name=f"qwen2.5-0.5b-instruct-{suffix}", hf_repo="Qwen/Qwen2.5-0.5B-Instruct",
        revision=QWEN25_0_5B_REVISION, pooling=pooling, batch_size=BATCH_0_5B, max_length=MAX_LENGTH,
    )


QWEN3_EMB_0_6B = ModelSpec(
    name="qwen3-embedding-0.6b", hf_repo="Qwen/Qwen3-Embedding-0.6B", revision=QWEN3_EMB_REVISION,
    pooling=POOLING_NATIVE, batch_size=BATCH_QWEN3_EMB, max_length=MAX_LENGTH,
    query_prompt=QWEN3_EMB_QUERY_PROMPT,
)

BGE_SMALL_REFERENCE = ModelSpec(
    name="bge-small-en-v1.5-reference", hf_repo="BAAI/bge-small-en-v1.5", revision=BGE_SMALL_REVISION,
    pooling=POOLING_NATIVE, batch_size=BATCH_BGE_SMALL, max_length=MAX_LENGTH,
)


@dataclass
class RunSpec:
    run_id: str
    set_names: List[str]
    models: List[ModelSpec]
    is_gate_reading: bool  # False for Run 0 (design Section 1: "never a gate reading");
                            # True for Run 1. Standing is per-set, per eval.k1.COMMISSIONED_SETS
                            # and eval.k1.COMMISSIONING_NOTICE -- not restated here (TE-40
                            # review, F-8: this comment previously asserted a superseded
                            # blanket "still quarantined," which was already false for the
                            # four commissioned sets when it was written).
    include_bm25: bool = True
    r1_independent_scorer: bool = True
    max_corpus_docs: Optional[int] = None  # smoke-only; never set on Run 0 or Run 1
    allow_missing_license: bool = False  # mechanism-check only; never True on a real run
    chance_trials: int = 1000
    k: int = 10
    seed: int = 0
    device: str = "cuda"


def run0_scout() -> RunSpec:
    """Design Section 1: SciFact + NFCorpus, the full candidate field, ranking evidence
    only -- never a gate reading (D-SLM4656)."""
    models = [
        qwen25_1_5b(POOLING_PS1_PRE_NORM, "ps1"),
        qwen25_0_5b(POOLING_PS1_PRE_NORM, "ps1"),
        qwen25_1_5b(POOLING_PS2_POST_NORM, "ps2"),
        qwen25_0_5b(POOLING_PS2_POST_NORM, "ps2"),
        QWEN3_EMB_0_6B,
        BGE_SMALL_REFERENCE,
    ]
    return RunSpec(
        run_id="run0-scout", set_names=["scifact", "nfcorpus"], models=models,
        is_gate_reading=False,
    )


def run1_full(models: Optional[List[ModelSpec]] = None) -> RunSpec:
    """Design Section 1/9.1/16: five sets (SciFact, NFCorpus, FiQA-2018, ArguAna, SCIDOCS --
    ``PUBLIC_SETS + INTERNAL_DIAGNOSTIC_SETS`` above), the roster reduced to the candidate
    still standing after the scout and the reference it is graded against.

    **TE-39, 2026-08-30.** The scout (Run 0, D-SLM4710) resolvably killed both pooled
    Qwen2.5-Instruct incumbents; D-SLM4719 ratified Qwen3-Embedding-0.6B as the sole 1.0
    candidate and D-SLM4723 reduces K1-Run-1's roster to it alone against the reference and
    BM25 -- this default replaces the provisional three-candidate-down-to-survivors roster
    D-SLM4627 stated before the scout ran. ``include_bm25`` stays at ``RunSpec``'s default
    (``True``): BM25 (F2's floor) and the reference (F1's floor) are both still evaluated on
    every set, including the two internal-diagnostic sets -- design Section 16: "the two
    restricted sets are retained as internal diagnostics -- they are still run, still gate
    the model at F1/F2 exactly as designed."
    """
    models = models or [
        QWEN3_EMB_0_6B,
        BGE_SMALL_REFERENCE,
    ]
    return RunSpec(
        run_id="run1-full",
        set_names=["scifact", "nfcorpus", "fiqa", "arguana", "scidocs"],
        models=models,
        is_gate_reading=True,
    )


def smoke(max_corpus_docs: int = 50, allow_missing_license: bool = False) -> RunSpec:
    """The build brief's bench proof: loader -> embed -> score -> report, end to end, on a
    tiny slice. Uses the ratified 1.0 candidate (Qwen3-Embedding-0.6B, D-SLM4719/D-SLM4723)
    plus the reference, on SciFact (the original proven set) and SCIDOCS (TE-39's addition --
    a smoke that only re-runs the four old sets proves nothing about the fifth). A smoke run
    is a mechanism check, not the product claim (`StandardsDocument.md` Section 5.4): it
    proves the pipeline executes end to end on real data, not that the readings decide
    anything.

    ``allow_missing_license=False`` by default as of TE-39 -- Linnaeus's license derivation
    has run and every set's ``sets.lock`` entry now carries a derived license string (stage
    (a)), so the mechanism check the flag existed for (build-log spec gap G-1) no longer
    applies. Callers exercising the pre-derivation mechanism explicitly still can by passing
    ``allow_missing_license=True``; the real gate path (Run 0, Run 1) never sets it, per the
    design's own Section 2.4."""
    models = [
        QWEN3_EMB_0_6B,
        BGE_SMALL_REFERENCE,
    ]
    return RunSpec(
        run_id="smoke-scifact-scidocs-50", set_names=["scifact", "scidocs"], models=models,
        is_gate_reading=False, max_corpus_docs=max_corpus_docs,
        allow_missing_license=allow_missing_license, chance_trials=200,
    )
