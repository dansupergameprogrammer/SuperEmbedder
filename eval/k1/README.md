# U-K1 -- the K1 retrieval-quality gate's instrument

Design of record: `Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md` (Wizard project
records tree). This directory is the instrument only -- the code that loads pinned public
retrieval sets, embeds candidates, ranks and scores them, and emits a result packet. It does
not decide anything; see **Quarantine**, below.

## Quarantine

Per `StandardsDocument.md` 5.4 ("An instrument is commissioned before its verdicts are
load-bearing -- and never by its own maker"): the commissioning constructions -- a
must-accept and two must-reject constructions, design Section 6.4 -- are authored by a seat
independent of this instrument's builder, not by this package. **Until those three
constructions are executed and fire correctly, every reading this instrument produces is
quarantined: recorded, never acted on, never headlined, and not read into any gate
verdict.** Every entry point prints this notice (`eval.k1.QUARANTINE_NOTICE`) before
emitting a result.

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
arithmetic does not lift quarantine -- a `gate_verdict` on a quarantined packet is exactly as
quarantined as the readings it was computed from.

## Commissioning status

An independent seat executed the commissioning constructions once
(`Claude/Mendeleev/u-k1-commissioning-execution-2026-08-25.md`, Wizard project records tree)
and returned **NOT COMMISSIONED**, blocked by two build findings, both fixed in the U-K1 fix
round (`Claude/Brunel/u-k1-fix1-2026-08-25.md`):

- **Finding A (D-SLM4688)** -- 5 of ArguAna's 1,406 test queries' qrels rows referenced a
  corpus-id genuinely absent from the pinned corpus (confirmed against a second, independent
  mirror of the same upstream data -- not a fetch or join defect in this loader). Fixed by
  `sets_lock.reconcile_qrels_to_corpus`, applied at both fetch and load time; the committed
  `sets.lock.json`'s `arguana` entry now pins 1,401 test queries/qrels rows and records
  `qrels_reconciled_dropped: 5`.
- **Finding B (D-SLM4689)** -- `ndcg_at_k_own` and the independent `pytrec_eval` scorer (R1)
  disagreed by 5.49e-4 on NFCorpus (graded relevance), ~500x the 1e-6 replication threshold.
  Root cause: an exact cosine-score tie in a query's top-k, where `ndcg_at_k_own` preserves
  `cosine_topk`'s own deterministic ascending-corpus-id tie-break but `pytrec_eval` received
  a plain `{docid: score}` mapping and re-sorted ties by its own internal convention. Fixed
  in `ndcg_at_k_pytrec` by scoring rank-preserving synthetic scores (strictly decreasing by
  position) instead of the raw tied scores, so `pytrec_eval`'s sort cannot disagree with the
  order already decided. Verified against the persisted NFCorpus run file: delta is now
  exactly 0.0.

**The fix has not yet been verified by re-running the commissioning constructions** -- per
the commissioning spec's own disposition rule, that re-execution is a separate dispatch from
this fix round. Every reading this instrument produces remains quarantined until it fires.

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

Run 0 (the scout, SciFact + NFCorpus, the full candidate field) and Run 1 (the full
four-set protocol) are dispatched separately, after commissioning -- see the build log.

## Known spec gaps (see the build log for full detail)

- **G-1 -- license.** `sets.lock.json`'s `license` field is `null` for all four sets;
  design Section 2.4 routes derivation to the deriver (Linnaeus). The real gate path
  (`allow_missing_license=False`, the default) refuses to run without it.
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
repository) carries the full build narrative, every spec gap, and the executed smoke run's
output.
