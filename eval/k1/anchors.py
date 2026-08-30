"""Component 5 -- anchors.json and its fetch step.

Design reference: te33-k1-gate-design-2026-08-25.md Section 4.1, Section 6.2 row 5.

Fetches published nDCG@10 for the reference encoder (``BAAI/bge-small-en-v1.5``) from the
MTEB results dataset (``mteb/results``, dataset sha
``fbfca6f624278ab416ede77e17cd91466113178c``) -- the same primary source the design itself
used (Section 14). Every value is committed with its source (the parquet file path within
the pinned dataset revision), fetch date, dataset sha and result revision, never hand-typed
(design's own worked demonstration, Section 4.2: a transcribed anchor for ArguAna would have
been wrong by roughly half).

Fetch method: the Hugging Face datasets-server ``/filter`` endpoint the design's own Section
14 names returns HTTP 422 ("Parameter 'where' contains errors or invalid symbols") on this
dataset regardless of query shape -- confirmed this session across several WHERE-clause
forms, including a single-column filter with no special characters. ``mteb/results`` is
8.8M rows across 4 parquet files (298 MB total); this module downloads those 4 files via
``huggingface_hub.hf_hub_download`` (content-addressed under ``HF_HOME``, not re-downloaded
on a second run) and filters with ``pyarrow.dataset`` predicate pushdown, which is the same
primary source and the same pinned revision, reached by a different transport. Filed as
build-log spec gap G-5.

The published BM25 nDCG@10 anchor is NOT fetched by this module: design Section 4.2 states
it must be "pinned into anchors.json by a fetch step at instrument-build time", but no
canonical per-task BM25 nDCG@10 entry exists in mteb/results under a stable model name (BM25
is not a benchmarked "model" in that dataset the way trained encoders are -- see build log
spec gap G-4). The local BM25 run is F2's actual comparison; the anchor's absence is filed
as a spec gap rather than filled with a transcription.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Dict, Optional, Union

MTEB_RESULTS_DATASET = "mteb/results"
MTEB_RESULTS_DATASET_SHA = "fbfca6f624278ab416ede77e17cd91466113178c"
REFERENCE_MODEL_NAME = "BAAI/bge-small-en-v1.5"
REFERENCE_MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"

# task id -> (mteb task name as stored in mteb/results, expected published value from the
# design's Section 4.1 table, used only to cross-check the fetch reproduces it). "scidocs"
# added TE-40 review, F-6: the design's Section 16 amendment names SCIDOCS's published
# anchor (0.20518) explicitly; before this fix, mint_anchors.py's default run fetched only
# these four, so re-running it against the five-entry anchors.json committed by
# tools/mint_scidocs.py silently dropped SCIDOCS's anchor on write (`write_anchors`
# overwrites the file whole, no merge).
TASKS = {
    "scifact": "SciFact",
    "nfcorpus": "NFCorpus",
    "fiqa": "FiQA2018",
    "arguana": "ArguAna",
    "scidocs": "SCIDOCS",
}
DESIGN_EXPECTED_NDCG10 = {
    "scifact": 0.71273,
    "nfcorpus": 0.34264,
    "fiqa": 0.40343,
    "arguana": 0.60348,
    "scidocs": 0.20518,
}


@dataclass
class AnchorEntry:
    metric: str
    task: str
    model_name: str
    model_revision: str
    ndcg_at_10: float
    source_url: str
    fetch_date: str
    dataset_sha: str


def _download_results_parquet_paths() -> list[str]:
    """Downloads (or reuses the cached copy of) mteb/results' 4 parquet files at the pinned
    revision, and returns their local paths."""
    from huggingface_hub import hf_hub_download

    return [
        hf_hub_download(
            MTEB_RESULTS_DATASET,
            f"data/train-0000{i}-of-00004.parquet",
            repo_type="dataset",
            revision=MTEB_RESULTS_DATASET_SHA,
        )
        for i in range(4)
    ]


def mint_anchors(tasks: Optional[Dict[str, str]] = None) -> Dict[str, AnchorEntry]:
    """Fetches the published nDCG@10 for the reference encoder on every requested MTEB
    task, from mteb/results' own rows, via pyarrow predicate pushdown over the pinned
    parquet files (see module docstring for why not the datasets-server /filter endpoint)."""
    import pyarrow.dataset as pa_dataset

    tasks = tasks or TASKS
    paths = _download_results_parquet_paths()
    ds = pa_dataset.dataset(paths, format="parquet")
    table = ds.to_table(
        filter=(pa_dataset.field("model_name") == REFERENCE_MODEL_NAME)
        & (pa_dataset.field("task_name").isin(list(tasks.values())))
        & (pa_dataset.field("split") == "test")
    )
    rows = table.to_pylist()
    by_task = {r["task_name"]: r for r in rows}
    fetch_date = datetime.date.today().isoformat()
    anchors = {}
    for key, mteb_task_name in tasks.items():
        if mteb_task_name not in by_task:
            raise RuntimeError(
                f"no mteb/results row found for model={REFERENCE_MODEL_NAME} "
                f"task={mteb_task_name} split=test"
            )
        row = by_task[mteb_task_name]
        anchors[key] = AnchorEntry(
            metric="ndcg_at_10",  # mteb/results' "score" column IS the task's headline
                                   # metric; for BEIR retrieval tasks that headline is
                                   # nDCG@10 (confirmed against the design's own Section 4.1
                                   # table -- see the reproduction check below).
            task=mteb_task_name,
            model_name=REFERENCE_MODEL_NAME,
            model_revision=row.get("model_revision") or "external",
            ndcg_at_10=float(row["score"]),
            source_url=(
                f"https://huggingface.co/datasets/{MTEB_RESULTS_DATASET}/blob/"
                f"{MTEB_RESULTS_DATASET_SHA}/data/train-0000X-of-00004.parquet"
            ),
            fetch_date=fetch_date,
            dataset_sha=MTEB_RESULTS_DATASET_SHA,
        )
    return anchors


def write_anchors(anchors: Dict[str, Union[AnchorEntry, dict]], path: Path, bm25_note: str) -> None:
    """Writes ``anchors.json`` whole. ``anchors`` maps a set name to either a freshly-minted
    ``AnchorEntry`` or a plain dict (an existing entry read back from a prior write, carried
    forward unchanged) -- ``mint_anchors.py``'s tool merges a fresh fetch into the existing
    file the same way ``mint_sets_lock.py`` does (TE-40 review, F-6), so re-running this tool
    over a subset of ``TASKS`` never silently drops the anchors it was not asked to refresh."""
    payload = {
        "schema_version": 1,
        "reference": {key: (asdict(a) if is_dataclass(a) else a) for key, a in anchors.items()},
        "bm25": {"note": bm25_note},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_anchors(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
