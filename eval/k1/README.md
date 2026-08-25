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
