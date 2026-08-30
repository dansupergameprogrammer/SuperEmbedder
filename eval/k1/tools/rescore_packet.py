#!/usr/bin/env python3
"""Recomputes a K1 packet's per-reading scores, aggregate gate verdict, and status notice
from its own persisted TREC run files and the pinned qrels -- under the CURRENTLY INSTALLED
``eval.k1`` code -- without re-embedding, re-ranking, or re-running the sweep.

**Why this exists (TE-40).** A packet produced by an older commit of this instrument can
carry a stale aggregate verdict or a stale status notice even when its underlying rankings
are sound (the packet's `sets[*][*]["ndcg_at_10"]` values, produced by an already-fixed
scorer, were correct all along -- only the code that *interpreted* them, or the text
describing the instrument's *status*, was stale). Re-running the embed/rank sweep to fix that
is wasteful and, for a multi-hour production run, often infeasible on demand. The
commissioning executions already established the pattern this script generalizes: the third
execution rescored SciFact, NFCorpus and FiQA-2018 from the second execution's own persisted
TREC run files under the fixed code, with no re-embedding
(`Claude/Mendeleev/u-k1-commissioning-execution3-2026-08-25.md` Section 3, Wizard project
records tree).

**What this script does, concretely, for one packet:**

1. For every ``(set, model)`` pair with a persisted TREC run file, reloads that set's real
   qrels once per set (never re-embeds, never re-ranks -- the TREC file already IS the
   ranking) and recomputes ``nDCG@10``, ``recall@10``, ``MRR@10``, the achieved resolving
   power, and -- where the original reading carried them -- the R1 independent-scorer
   reading and its agreement delta, and the R2 published-anchor delta, all with the CURRENTLY
   INSTALLED ``rank_score`` module. This is a genuine recomputation of every field the
   original run *derived* from the ranking, not only the headline ``ndcg_at_10`` (TE-40
   review Finding F-2: refreshing the headline alone while leaving its derived fields stale
   produces a packet that contradicts itself -- a replication-agreement field asserting
   floating-point-noise agreement across a real disagreement the headline's own refresh just
   introduced). A field that cannot be recomputed (R1, when ``pytrec_eval`` is not installed)
   is deleted rather than carried forward stale: a missing field is a question, a stale one is
   an answer.
2. Recomputes ``gate_verdict`` over the refreshed readings with the CURRENTLY INSTALLED
   ``gate.evaluate_gate``.
3. Refreshes ``commissioning_notice`` (and drops the superseded ``quarantine_notice`` key, if
   the original packet carried it) and ``self_exclusion_convention`` from the CURRENTLY
   INSTALLED ``eval.k1`` package.
4. Re-renders the human-readable table and writes the corrected packet + table to
   ``output_path`` (default: alongside the original, suffixed ``-rescored``) -- the ORIGINAL
   packet is never overwritten, per StandardsDocument.md 6.6 (a correction is new content, not
   a silent edit of the record it corrects); passing ``--out`` equal to the input path is
   refused rather than honored (TE-40 review Finding F-13). The diff report (below) is
   written into the corrected packet itself, as ``rescore_report`` (TE-40 review Finding
   F-12), not only printed to stdout.

**Refuses rather than silently reporting success (TE-40 review Finding F-3).** If any (set,
model) pair's TREC run file is missing, this script raises ``RescoreRefusalError`` (a non-zero
exit from the CLI) instead of writing a "corrected" packet that recomputed nothing for those
pairs while stamping it with the current notice and a freshly-computed ``gate_verdict`` built
from stale readings. Pass ``--notice-only`` (``notice_only=True``) to refresh only the gate
verdict and status notice from the packet's *own already-stored* readings, without requiring
persisted TREC files -- use this only when you specifically intend to leave the readings
untouched (e.g. after a code change that affects only the verdict/notice text, not the
scorer); the diff report and the output packet both record ``"notice_only": true`` so a reader
can tell the readings were not touched.

Returns a diff report: every (set, model) reading whose recomputed nDCG@10 differs from the
original by more than floating-point noise, the old vs. new ``gate_verdict.passed``, and the
old vs. new notice text -- so a reader can see exactly what changed and why without diffing
two multi-hundred-line JSON files by hand.

**Never point this script at the live Run 1 output while Run 1 is still executing**
(`eval/k1/run1_output/`, excluded from this ticket's write scope for exactly this reason).
Demonstrate it on a fixture or a copy; correct the real Run 1 packet only after Run 1 has
landed, as its own dispatch.

Usage:
    py -3.13 eval/k1/tools/rescore_packet.py <packet.json> [--sets-lock PATH] [--out PATH] [--notice-only]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1 import COMMISSIONING_NOTICE
from eval.k1.gate import evaluate_gate
from eval.k1.rank_score import achieved_resolving_power, mrr_at_k, ndcg_at_k_own, read_trec_run, recall_at_k
from eval.k1.runner import render_human_table
from eval.k1.self_exclusion import SELF_EXCLUSION_NOTE
from eval.k1.sets_lock import load_set, read_sets_lock

K1_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SETS_LOCK_PATH = K1_DIR / "sets.lock.json"
FLOAT_NOISE_TOLERANCE = 1e-9  # a rescore delta at or below this is floating-point rounding,
                               # not a real disagreement between the old and new scorer
RESCORE_TOOL_ID = "eval.k1.tools.rescore_packet"


class RescoreRefusalError(RuntimeError):
    """Raised when ``rescore_packet`` refuses to write a corrected packet -- the message
    names which guard fired. Caught by ``main()`` and reported as a clean, non-zero exit;
    this tool never writes a packet stamped "corrected" while a guard is unsatisfied
    (TE-40 review Findings F-3, F-13)."""


def _trec_path(output_dir: Path, run_id: str, set_name: str, model_name: str) -> Path:
    return output_dir / "run_files" / run_id / set_name / f"{model_name}.trec"


def _full_qrels_for_set(sets_lock_path: Path, set_name: str) -> Dict[str, Dict[str, float]]:
    """Loads the set's real, pinned qrels (never a persisted artifact of the original run --
    the qrels are the ground truth this instrument compares against, not something a rescore
    should trust a cached copy of), for every query in the test split. Called once per set
    name (TE-40 review Finding F-11: the caller caches this across every model scored on the
    same set, rather than reloading the full corpus/queries/qrels per (set, model) pair --
    the qrels do not change between models scored on the same set). ``allow_missing_license``
    is left at its default (``False``): this is a gate path (it recomputes ``gate_verdict``),
    and the real gate path never sets that flag (TE-40 review Finding F-4; `load_set`'s own
    docstring: "the real gate path never sets it")."""
    lock = read_sets_lock(sets_lock_path)
    entry = lock[set_name]
    _corpus, _queries, qrels_rows = load_set(set_name, entry)
    by_query: Dict[str, Dict[str, float]] = {}
    for row in qrels_rows:
        by_query.setdefault(row["query-id"], {})[row["corpus-id"]] = float(row["score"])
    return by_query


def _scope_qrels(full_qrels_by_query: Dict[str, Dict[str, float]], query_ids: List[str]) -> Dict[str, Dict[str, float]]:
    """Scopes an already-loaded set's full qrels to exactly the query ids one TREC file
    actually carries, matching ``runner.run_gate``'s own scoping discipline."""
    query_id_set = set(query_ids)
    return {qid: rels for qid, rels in full_qrels_by_query.items() if qid in query_id_set}


def rescore_packet(
    packet_path: Path,
    sets_lock_path: Path = DEFAULT_SETS_LOCK_PATH,
    output_path: Optional[Path] = None,
    notice_only: bool = False,
) -> dict:
    """Recomputes ``packet_path``'s readings, gate verdict, and status notice from its own
    persisted TREC run files, under the currently installed code. Returns a diff report (also
    persisted into the written packet as ``rescore_report``); writes the corrected packet +
    table to ``output_path`` (or ``<stem>-rescored.json/.txt`` beside the original) without
    touching the original files. Raises ``RescoreRefusalError`` rather than writing anything
    if ``output_path`` equals ``packet_path``, or if any (set, model) pair's TREC file is
    missing and ``notice_only`` was not requested."""
    packet_path = Path(packet_path)
    output_dir = packet_path.parent
    if output_path is None:
        output_path = output_dir / f"{packet_path.stem}-rescored.json"
    else:
        output_path = Path(output_path)
        if output_path.resolve() == packet_path.resolve():
            raise RescoreRefusalError(
                f"--out ({output_path}) must not equal the input packet path -- the original "
                f"packet is never overwritten (StandardsDocument.md 6.6). Choose a different "
                f"output path."
            )
    table_path = output_path.with_suffix(".txt")

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    run_id = packet["run_id"]

    diff: dict = {
        "run_id": run_id, "packet_path": str(packet_path), "notice_only": notice_only,
        "reading_deltas": [], "trec_files_missing": [], "r1_deletions": [],
    }

    qrels_cache: Dict[str, Dict[str, Dict[str, float]]] = {}
    if not notice_only:
        for set_name, set_result in packet.get("sets", {}).items():
            for model_name, model_result in set_result.get("models", {}).items():
                trec_path = _trec_path(output_dir, run_id, set_name, model_name)
                if not trec_path.exists():
                    diff["trec_files_missing"].append(f"{set_name}/{model_name}: {trec_path}")
                    continue

                run = read_trec_run(trec_path)
                query_ids = list(run.keys())
                if set_name not in qrels_cache:
                    qrels_cache[set_name] = _full_qrels_for_set(sets_lock_path, set_name)
                qrels_by_query = _scope_qrels(qrels_cache[set_name], query_ids)

                per_query_ndcg, mean_ndcg = ndcg_at_k_own(qrels_by_query, run, k=10)
                rp = achieved_resolving_power(per_query_ndcg)
                _per_q_recall, mean_recall = recall_at_k(qrels_by_query, run, k=10)
                _per_q_mrr, mean_mrr = mrr_at_k(qrels_by_query, run, k=10)

                old_ndcg = model_result.get("ndcg_at_10")
                delta = abs(mean_ndcg - old_ndcg) if old_ndcg is not None else None
                if delta is None or delta > FLOAT_NOISE_TOLERANCE:
                    diff["reading_deltas"].append({
                        "set": set_name, "model": model_name,
                        "old_ndcg_at_10": old_ndcg, "recomputed_ndcg_at_10": mean_ndcg,
                        "delta": delta,
                    })

                model_result["ndcg_at_10"] = mean_ndcg
                model_result["recall_at_10"] = mean_recall
                model_result["mrr_at_10"] = mean_mrr
                model_result["achieved_resolving_power"] = rp
                model_result["rescored_by"] = RESCORE_TOOL_ID

                # R1, the independent scorer -- for a model_result that already carries EITHER
                # of the producing path's two mutually-exclusive R1 outcomes
                # (runner.run_gate writes exactly one of the three fields below, never a
                # subset that omits the third: runner.py:186-191 -- success writes
                # "ndcg_at_10_r1_independent" + "r1_agreement_delta"; failure writes
                # "r1_independent_scorer_error"). TE-40 review Finding F-2's remedy keyed this
                # branch on the two success fields alone, so a packet carrying only the error
                # field skipped it -- a stale "scorer unavailable" string could survive a
                # rescore run on a machine where the scorer works (TE-44 review, G-2,
                # direction one). Keying on the union of all three closes that.
                if {"ndcg_at_10_r1_independent", "r1_independent_scorer_error"} & model_result.keys():
                    try:
                        from eval.k1.rank_score import ndcg_at_k_pytrec

                        _per_q_r1, mean_r1 = ndcg_at_k_pytrec(qrels_by_query, run, k=10)
                        model_result["ndcg_at_10_r1_independent"] = mean_r1
                        model_result["r1_agreement_delta"] = abs(mean_ndcg - mean_r1)
                        model_result.pop("r1_independent_scorer_error", None)
                    except ImportError as e:
                        # genuinely cannot be recomputed in this environment. Recorded the
                        # same way the producing path records this exact condition
                        # (runner.py:191, "r1_independent_scorer_error") rather than deleted
                        # with no trace -- and any R1 reading this deletes is appended to the
                        # diff report, so rescore_report (F-12: the record of what a rescore
                        # changed) shows the mutation instead of going silent on R1 entirely
                        # (TE-44 review, G-2, direction two).
                        removed = {
                            field: model_result.pop(field)
                            for field in ("ndcg_at_10_r1_independent", "r1_agreement_delta")
                            if field in model_result
                        }
                        model_result["r1_independent_scorer_error"] = str(e)
                        if removed:
                            diff["r1_deletions"].append({
                                "set": set_name, "model": model_name, "removed_fields": removed,
                            })

                # R2, the published-anchor comparison -- against the anchor value the packet
                # already stored (the anchor itself is not re-fetched by a rescore), only for
                # a model_result that already carried it (the reference model's own row).
                if "published_anchor_ndcg_at_10" in model_result:
                    model_result["r2_delta_vs_anchor"] = abs(
                        mean_ndcg - model_result["published_anchor_ndcg_at_10"]
                    )

    if diff["trec_files_missing"] and not notice_only:
        raise RescoreRefusalError(
            f"{len(diff['trec_files_missing'])} (set, model) pair(s) have no persisted TREC "
            f"run file; their readings cannot be recomputed, so this packet would be marked "
            f"'corrected' while still carrying stale numbers for them. Pass "
            f"notice_only=True (CLI: --notice-only) to refresh only the gate verdict and "
            f"status notice from the packet's own stored readings, or point packet_path at "
            f"the run's own directory (the one containing run_files/). Missing: "
            f"{diff['trec_files_missing']}"
        )

    old_gate_verdict = packet.get("gate_verdict", {})
    old_passed = old_gate_verdict.get("passed")
    old_notice = packet.get("commissioning_notice", packet.get("quarantine_notice"))

    new_gate_verdict = evaluate_gate(packet)
    packet["gate_verdict"] = asdict(new_gate_verdict)
    packet["commissioning_notice"] = COMMISSIONING_NOTICE
    packet.pop("quarantine_notice", None)  # superseded key name (TE-40); commissioning_notice is current
    packet["self_exclusion_convention"] = SELF_EXCLUSION_NOTE
    packet["rescored_from"] = str(packet_path)
    packet["rescore_tool"] = RESCORE_TOOL_ID
    packet["rescore_notice_only"] = notice_only  # TE-44 review, G-3: readable at a glance on
                                                  # the packet, not only nested inside
                                                  # rescore_report.notice_only

    diff["gate_verdict_passed"] = {"old": old_passed, "new": new_gate_verdict.passed}
    diff["notice"] = {"changed": old_notice != COMMISSIONING_NOTICE, "old": old_notice, "new": COMMISSIONING_NOTICE}
    diff["written"] = {"packet": str(output_path), "table": str(table_path)}
    packet["rescore_report"] = diff  # TE-40 review Finding F-12: persisted, not only printed

    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")

    # TE-44 review, G-3: notice_only's whole purpose is to mark a packet's readings as
    # deliberately untouched, and before this the mark existed only nested inside the JSON
    # (rescore_report.notice_only) -- invisible on the human table, the surface this package
    # deliberately prints its commissioning notice on for a reader who does not open the code.
    table = render_human_table(packet)
    if notice_only:
        table += (
            "\nNOTICE-ONLY RESCORE -- readings were NOT recomputed; only the gate verdict and "
            "status notice were refreshed from this packet's own already-stored readings.\n"
        )
    table_path.write_text(table, encoding="utf-8")

    return diff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, help="Path to the packet JSON to rescore")
    parser.add_argument("--sets-lock", type=Path, default=DEFAULT_SETS_LOCK_PATH)
    parser.add_argument("--out", type=Path, default=None, help="Output packet path (default: <stem>-rescored.json beside the input)")
    parser.add_argument(
        "--notice-only", action="store_true",
        help="Refresh only the gate verdict and status notice from the packet's own stored "
             "readings, without requiring persisted TREC run files. Readings are NOT "
             "recomputed in this mode.",
    )
    args = parser.parse_args()

    try:
        diff = rescore_packet(
            args.packet, sets_lock_path=args.sets_lock, output_path=args.out,
            notice_only=args.notice_only,
        )
    except RescoreRefusalError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(diff, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
