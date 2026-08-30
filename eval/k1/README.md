# U-K1 -- the K1 retrieval-quality gate's instrument

Design of record: `Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md` (Wizard project
records tree). This directory is the instrument only -- the code that loads pinned public
retrieval sets, embeds candidates, ranks and scores them, and emits a result packet. It does
not decide anything; see **Commissioning**, below.

## Commissioning

Per `StandardsDocument.md` 5.4 ("An instrument is commissioned before its verdicts are
load-bearing -- and never by its own maker"): the commissioning constructions -- a
must-accept and two must-reject constructions, design Section 6.4 -- are authored by a seat
independent of this instrument's builder, not by this package. **Until those three
constructions are executed and fire correctly for a given set, every reading this instrument
produces on that set is quarantined: recorded, never acted on, never headlined, and not read
into any gate verdict as load-bearing.** As of 2026-08-30 (see **Commissioning status** below)
all three fire correctly on all five sets in `eval.k1.COMMISSIONED_SETS` (SciFact, NFCorpus,
FiQA-2018, ArguAna, SCIDOCS), and the instrument's readings on those five sets are
load-bearing -- currently every set `eval.k1.set_roster.ALL_LOCKED_SETS` locks.
`eval.k1.COMMISSIONING_DECISIONS` cites the exact decision ID that commissioned each set.

**SCIDOCS carries a Note that survives its COMMISSIONED status: its must-reject-1 construction
fires by a narrow margin** -- exceeds its own executed resolving power by roughly 3e-05, a
genuine boundary case independently measured twice, corroborated across three seeds,
non-replicating at two alternate embedding dimensions, and independently backed by an F2
(local BM25 floor) rejection of the same construction at roughly 11x its own resolving power
regardless of how the boundary itself resolves. This is stated here, not only in the code's
own `eval.k1.COMMISSIONING_NOTICE`, so a reader of "SCIDOCS: COMMISSIONED" alone still learns
it.

A construction that fires does not retroactively validate a different, unexecuted
configuration (commissioning spec Section 5): a set the design locks in the future, before an
independent seat runs the constructions against it and logs the verdict, carries no
commissioning of its own, whatever the gate's own required-set roster says. This is a
separate condition from, and additional to, the design's own component re-commissioning rule:
any subsequent change to the loader, ranker, scorer, or guard requires the affected
constructions to be re-fired, on every set they touch, before a new reading from the changed
code is trusted. Every entry point prints the current status
(`eval.k1.COMMISSIONING_NOTICE`) before emitting a result -- that constant is this
package's one standing statement of status; this section restates it for a reader who has
not opened the code, and is not itself the source of truth.
`eval/k1/tests/test_commissioned_sets_pin.py` pins `eval.k1.COMMISSIONED_SETS` against
`eval.k1.COMMISSIONING_DECISIONS` and, where the sibling Wizard records repository is
reachable, against the cited decision-log entries themselves.

## The six components (design Section 6.2)

| # | Component | File |
|---|---|---|
| 1 | Pinned set loader + `sets.lock` | `sets_lock.py`, `sets.lock.json`, `tools/mint_sets_lock.py` |
| 2 | Embedding runner | `embed_runner.py`, `pooling.py` |
| 3 | Ranker + dual scorer | `rank_score.py` |
| 4 | The zero-qrels guard | `guards.py` |
| 5 | `anchors.json` + its fetch step | `anchors.py`, `anchors.json`, `tools/mint_anchors.py` |
| 6 | BM25 baseline | `bm25_baseline.py` |

Orchestration (not itself one of the six, but required to run any of them together):
`run_spec.py` (Run 0 / Run 1 / smoke rosters) and `runner.py` (`run_gate()`, one code path
for all three).

**The gate (design Section 4, not one of the six components -- the decision layer that reads
the instrument's readings)**: `gate.py`. Computes the F1/F2 floor arithmetic
(`evaluate_gate`) over an executed run packet and is wired into `runner.run_gate()` as the
packet's `gate_verdict` field and into `render_human_table`'s text report. Computing this
arithmetic does not itself decide the packet's standing -- a `gate_verdict` carries exactly
the standing of the readings it was computed from, per `eval.k1.COMMISSIONING_NOTICE`.

## Commissioning status

An independent seat executed the commissioning constructions three times as the instrument's
build round answered successive findings:

- **First execution** (`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md`)
  returned **NOT COMMISSIONED**, blocked by two build findings, both fixed in the U-K1 fix
  round (`Claude/Brunel/u-k1-fix1-2026-08-25.md`):
  - **Finding A (D-SLM4688)** -- 5 of ArguAna's 1,406 test queries' qrels rows referenced a
    corpus-id genuinely absent from the pinned corpus (confirmed against a second,
    independent mirror of the same upstream data -- not a fetch or join defect in this
    loader). Fixed by `sets_lock.reconcile_qrels_to_corpus`, applied at both fetch and load
    time; the committed `sets.lock.json`'s `arguana` entry now pins 1,401 test
    queries/qrels rows and records `qrels_reconciled_dropped: 5`.
  - **Finding B (D-SLM4689)** -- `ndcg_at_k_own` and the independent `pytrec_eval` scorer
    (R1) disagreed by 5.49e-4 on NFCorpus (graded relevance), ~500x the 1e-6 replication
    threshold. Root cause: an exact cosine-score tie in a query's top-k, where
    `ndcg_at_k_own` preserves `cosine_topk`'s own deterministic ascending-corpus-id
    tie-break but `pytrec_eval` received a plain `{docid: score}` mapping and re-sorted
    ties by its own internal convention. Fixed in `ndcg_at_k_pytrec` by scoring
    rank-preserving synthetic scores (strictly decreasing by position) instead of the raw
    tied scores, so `pytrec_eval`'s sort cannot disagree with the order already decided.
    Verified against the persisted NFCorpus run file: delta is now exactly 0.0.
- **Second execution** (`Claude/Mendeleev/u-k1-commissioning-execution2-2026-08-25.md`,
  D-SLM4694) found Finding D: the ranker never excluded a query's own id from its own
  ranked results, depressing ArguAna's must-accept reading 15.3x past the governing
  tolerance. Fixed in two rounds (`Claude/Brunel/u-k1-fix2-2026-08-25.md`,
  `u-k1-fix2b-2026-08-25.md`, D-SLM4699-4703) by extracting the self-exclusion convention
  into one shared helper (`eval/k1/self_exclusion.py`) called by both rankers.
- **Third execution** (`Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md`,
  D-SLM4707, 2026-08-25) verified Finding D fixed at source in both call sites and
  re-executed all three constructions end to end: **all three fire correctly on all four
  sets** (SciFact, NFCorpus, FiQA-2018, ArguAna). **Overall verdict: COMMISSIONED.**

**SCIDOCS was added to the design's locked-set roster five days later** (TE-39,
D-SLM4705/D-SLM4686) and required its own commissioning pass, executed independently of the
four-set pass above and in two rounds:

- **TE-41** (`Claude/Mendeleev/te41-scidocs-commissioning-2026-08-30.md`, D-SLM5338,
  2026-08-30) ran all three constructions against SCIDOCS. Must-accept fired; must-reject 1
  fired, with a Note carried forward (see below); must-reject 2 -- the qrels-permutation join
  attack -- did **not** fire, mechanistically traced to SCIDOCS's own query list carrying
  topical clustering that the construction's fixed half-length positional shift does not
  escape on this specific set, not to a code-level join defect. **Overall verdict: NOT
  COMMISSIONED.** TE-41 named the remedy (a permutation guaranteeing topical, not merely
  positional, separation) but did not build it.
- **TE-46** (`Claude/Mendeleev/te46-scidocs-mustreject2-remedy-2026-08-30.md`, D-SLM5363,
  2026-08-30), independent of TE-41's own authoring seat, independently re-verified all of
  TE-41's readings from source, then built and executed the remedy: a content-distance-aware
  derangement, assigning each query the least topically similar donor query available under a
  global optimal (Hungarian) assignment, computed under two independent lexical-distance
  definitions (word and character TF-IDF). Both fire: the broken-join reading collapses to
  within resolving power of chance under both definitions, while the correct-join reading
  reproduces the published anchor exactly. **Overall verdict: COMMISSIONED**, superseding
  TE-41's NOT COMMISSIONED.

**A Note that survives SCIDOCS's COMMISSIONED status, carried forward across both passes
rather than dropped now that the status is favorable: SCIDOCS's must-reject-1 construction
fires by a narrow margin.** Its reading exceeds its own executed resolving power by roughly
3e-05 -- independently measured twice (TE-41, TE-46), both times a genuine boundary case:
corroborated across three seeds' percentile placement within the chance distribution,
non-replicating at two alternate embedding dimensions, and independently backed by an F2
(local BM25 floor) rejection of the same construction at roughly 11x its own resolving power
regardless of how the boundary itself resolves.

**Readings this instrument produces on `eval.k1.COMMISSIONED_SETS`, from the commit each
set's own verdict was filed at forward, are load-bearing.** `eval.k1.COMMISSIONING_DECISIONS`
cites the exact decision ID per set. This currently covers all five sets
`eval.k1.set_roster.ALL_LOCKED_SETS` locks -- a future set the design locks carries no
commissioning of its own until an independent seat runs the constructions against it and logs
the verdict; the commissioning spec's own disposition rule states a construction firing does
not retroactively validate a different, unexecuted configuration. Readings are also subject
to the design's own component re-commissioning rule, a separate condition: any subsequent
change to the loader, ranker, scorer, or guard requires the constructions it touches to be
re-fired, on every set they touch, before a new reading from the changed code is trusted.
This section and `eval.k1.COMMISSIONING_NOTICE` (the code) must read the same status; if they
ever disagree, the code's notice governs and this section is stale.
`eval/k1/tests/test_commissioned_sets_pin.py` checks `eval.k1.COMMISSIONED_SETS` against
`eval.k1.COMMISSIONING_DECISIONS` and, where reachable, against the filed decision-log
entries themselves.

## Running it

```
$env:HF_HOME = 'D:\hf_cache'; $env:HF_HUB_OFFLINE = '1'
py -3.13 -m pytest eval/k1/tests/ -v

py -3.13 -c "
from pathlib import Path
from eval.k1.runner import run_gate
from eval.k1.run_spec import smoke
run_gate(smoke(max_corpus_docs=50), Path('eval/k1/sets.lock.json'), Path('eval/k1/anchors.json'), output_dir=Path('eval/k1/smoke_output'))
"
```

Run 0 (the scout, SciFact + NFCorpus, the full candidate field) and Run 1 (the five-set
protocol -- the four originally-locked sets plus SCIDOCS, design Section 16) are dispatched
separately, after commissioning -- see the build log.

## Known spec gaps (see the build log for full detail)

- **G-1 -- license -- CLOSED, TE-39 (2026-08-30), D-SLM5297.** `sets.lock.json`'s `license`
  field is populated for every locked set (all five, including SCIDOCS) from Linnaeus's
  derived fact sheets; `allow_missing_license` stays unset (the default `False`) on every
  real gate path.
- **G-2 -- R1 contingency.** `pytrec_eval` is confirmed installable and is the primary
  independent scorer; the design's named fallbacks (`ir_measures`, a second
  independently-authored implementation) are not built.
- **G-3 -- BM25 parameters.** `k1=0.9, b=0.4` is BEIR's own standard default, not yet
  confirmed as Linnaeus-derived.
- **G-4 -- BM25 anchor.** No stable BM25 "model" entry exists in `mteb/results`; F2
  compares against the local BM25 run directly rather than a published anchor.
- **G-5 -- anchor fetch transport.** The datasets-server `/filter` endpoint 422s on
  `mteb/results`; the fetch downloads the dataset's parquet files directly and filters with
  `pyarrow`, same pinned revision, different transport.

## Build log

`Claude/Brunel/u-k1-instrument-build-2026-08-25.md` (Wizard project records tree, not this
repository) carries the original build narrative, every spec gap as first filed, and the
executed smoke run's output. It does not carry what changed after it landed; read forward
through `u-k1-fix1-2026-08-25.md`, `u-k1-fix2-2026-08-25.md`, `u-k1-fix2b-2026-08-25.md`
(the commissioning fix rounds), `te39-k1-run1-launch-2026-08-30.md` (SCIDOCS minted, the
roster reduced post-scout, Run 1 launched), `te40-k1-stale-truth-sweep-2026-08-30.md` (this
file's own status text corrected to match the third commissioning execution),
`Claude/Mendeleev/te41-scidocs-commissioning-2026-08-30.md` (SCIDOCS's first commissioning
pass, NOT COMMISSIONED), `Claude/Mendeleev/te46-scidocs-mustreject2-remedy-2026-08-30.md`
(SCIDOCS's remedy construction, built and executed, re-verdicted COMMISSIONED), and
`te47-land-scidocs-commissioned-2026-08-30.md` (SCIDOCS landed into
`eval.k1.COMMISSIONED_SETS`) for the current state.
