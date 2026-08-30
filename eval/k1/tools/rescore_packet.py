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

1. Loads the packet JSON and locates its TREC run files by the standard convention
   (``<output_dir>/run_files/<run_id>/<set_name>/<model_name>.trec``, exactly what
   ``runner.run_gate`` writes).
2. For every (set, model) pair with a persisted TREC file, reloads that set's real qrels from
   the pinned ``sets.lock`` (never re-embeds, never re-ranks -- the TREC file already IS the
   ranking) and recomputes ``nDCG@10`` and the achieved resolving power with the CURRENTLY
   INSTALLED ``rank_score`` module. This is a genuine recomputation from the persisted
   artifact, not a copy of the packet's own stored number -- if the scorer itself had changed
   since the packet was produced, this step would surface that; here it also serves as a
   byte-for-byte reproduction check (delta 0.0 is the expected, and confirmed, result for a
   packet whose scorer never changed, per the commissioning executions' own precedent).
3. Recomputes ``gate_verdict`` over the refreshed readings with the CURRENTLY INSTALLED
   ``gate.evaluate_gate``.
4. Refreshes ``commissioning_notice`` (and the legacy ``quarantine_notice`` key, if the
   original packet carried it) and ``self_exclusion_convention`` from the CURRENTLY INSTALLED
   ``eval.k1`` package.
5. Re-renders the human-readable table and writes the corrected packet + table to
   ``output_path`` (default: alongside the original, suffixed ``-rescored``) -- the ORIGINAL
   packet is never overwritten, per StandardsDocument.md 6.6 (a correction is new content, not
   a silent edit of the record it corrects).

Returns a diff report: every (set, model) reading whose recomputed nDCG@10 differs from the
original by more than floating-point noise, the old vs. new ``gate_verdict.passed``, and the
old vs. new notice text -- so a reader can see exactly what changed and why without diffing
two multi-hundred-line JSON files by hand.

**Never point this script at the live Run 1 output while Run 1 is still executing**
(`eval/k1/run1_output/`, excluded from this ticket's write scope for exactly this reason).
Demonstrate it on a fixture or a copy; correct the real Run 1 packet only after Run 1 has
landed, as its own dispatch.

Usage:
    py -3.13 eval/k1/tools/rescore_packet.py <packet.json> [--sets-lock PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1 import COMMISSIONING_NOTICE
from eval.k1.gate import evaluate_gate
from eval.k1.rank_score import achieved_resolving_power, ndcg_at_k_own, read_trec_run
from eval.k1.runner import render_human_table
from eval.k1.self_exclusion import SELF_EXCLUSION_NOTE
from eval.k1.sets_lock import load_set, read_sets_lock

K1_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SETS_LOCK_PATH = K1_DIR / "sets.lock.json"
FLOAT_NOISE_TOLERANCE = 1e-9  # a rescore delta at or below this is floating-point rounding,
                               # not a real disagreement between the old and new scorer


def _trec_path(output_dir: Path, run_id: str, set_name: str, model_name: str) -> Path:
    return output_dir / "run_files" / run_id / set_name / f"{model_name}.trec"


def _qrels_for_set(sets_lock_path: Path, set_name: str, query_ids: List[str]) -> Dict[str, Dict[str, float]]:
    """Reloads the set's real, pinned qrels (never a persisted artifact of the original run --
    the qrels are the ground truth this instrument compares against, not something a rescore
    should trust a cached copy of) and scopes them to exactly the query ids the TREC file
    actually carries, matching runner.run_gate's own scoping discipline."""
    lock = read_sets_lock(sets_lock_path)
    entry = lock[set_name]
    _corpus, _queries, qrels_rows = load_set(set_name, entry, allow_missing_license=True)
    by_query: Dict[str, Dict[str, float]] = {}
    for row in qrels_rows:
        by_query.setdefault(row["query-id"], {})[row["corpus-id"]] = float(row["score"])
    query_id_set = set(query_ids)
    return {qid: rels for qid, rels in by_query.items() if qid in query_id_set}


def rescore_packet(
    packet_path: Path,
    sets_lock_path: Path = DEFAULT_SETS_LOCK_PATH,
    output_path: Optional[Path] = None,
) -> dict:
    """Recomputes ``packet_path``'s readings, gate verdict, and status notice from its own
    persisted TREC run files, under the currently installed code. Returns a diff report;
    writes the corrected packet + table to ``output_path`` (or ``<stem>-rescored.json/.txt``
    beside the original) without touching the original files."""
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    output_dir = packet_path.parent
    run_id = packet["run_id"]

    diff: dict = {"run_id": run_id, "packet_path": str(packet_path), "reading_deltas": [], "trec_files_missing": []}

    qrels_cache: Dict[str, Dict[str, Dict[str, float]]] = {}
    for set_name, set_result in packet.get("sets", {}).items():
        for model_name, model_result in set_result.get("models", {}).items():
            trec_path = _trec_path(output_dir, run_id, set_name, model_name)
            if not trec_path.exists():
                diff["trec_files_missing"].append(f"{set_name}/{model_name}: {trec_path}")
                continue

            run = read_trec_run(trec_path)
            query_ids = list(run.keys())
            if set_name not in qrels_cache:
                qrels_cache[set_name] = {}
            qrels_by_query = _qrels_for_set(sets_lock_path, set_name, query_ids)

            per_query_ndcg, mean_ndcg = ndcg_at_k_own(qrels_by_query, run, k=10)
            rp = achieved_resolving_power(per_query_ndcg)

            old_ndcg = model_result.get("ndcg_at_10")
            delta = abs(mean_ndcg - old_ndcg) if old_ndcg is not None else None
            if delta is None or delta > FLOAT_NOISE_TOLERANCE:
                diff["reading_deltas"].append({
                    "set": set_name, "model": model_name,
                    "old_ndcg_at_10": old_ndcg, "recomputed_ndcg_at_10": mean_ndcg,
                    "delta": delta,
                })

            model_result["ndcg_at_10"] = mean_ndcg
            model_result["achieved_resolving_power"] = rp
            model_result["rescored_by"] = "eval.k1.tools.rescore_packet (TE-40)"

    old_gate_verdict = packet.get("gate_verdict", {})
    old_passed = old_gate_verdict.get("passed")
    old_notice = packet.get("commissioning_notice", packet.get("quarantine_notice"))

    new_gate_verdict = evaluate_gate(packet)
    from dataclasses import asdict
    packet["gate_verdict"] = asdict(new_gate_verdict)
    packet["commissioning_notice"] = COMMISSIONING_NOTICE
    packet.pop("quarantine_notice", None)  # superseded key name (TE-40); commissioning_notice is current
    packet["self_exclusion_convention"] = SELF_EXCLUSION_NOTE
    packet["rescored_from"] = str(packet_path)
    packet["rescore_tool"] = "eval.k1.tools.rescore_packet (TE-40)"

    diff["gate_verdict_passed"] = {"old": old_passed, "new": new_gate_verdict.passed}
    diff["notice"] = {"changed": old_notice != COMMISSIONING_NOTICE, "old": old_notice, "new": COMMISSIONING_NOTICE}

    if output_path is None:
        output_path = output_dir / f"{packet_path.stem}-rescored.json"
    output_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    table_path = output_path.with_suffix(".txt")
    table_path.write_text(render_human_table(packet), encoding="utf-8")
    diff["written"] = {"packet": str(output_path), "table": str(table_path)}

    return diff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, help="Path to the packet JSON to rescore")
    parser.add_argument("--sets-lock", type=Path, default=DEFAULT_SETS_LOCK_PATH)
    parser.add_argument("--out", type=Path, default=None, help="Output packet path (default: <stem>-rescored.json beside the input)")
    args = parser.parse_args()

    diff = rescore_packet(args.packet, sets_lock_path=args.sets_lock, output_path=args.out)
    print(json.dumps(diff, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
