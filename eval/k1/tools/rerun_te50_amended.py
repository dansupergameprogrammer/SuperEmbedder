#!/usr/bin/env python3
"""TE-50 -- re-executes the K1 gate against the amended design of record
(``Claude/Vitruvius/te33-k1-gate-design-2026-08-25.md`` Section 17, TE-49 amendment, Wizard
project records tree), over the same five sets Run 1 covered.

**What this script does, concretely.** Per the ticket brief, three things changed and one did
not:

1. **The candidate's ranking is REUSED, not re-embedded.** Run 1's own persisted TREC run
   files for ``qwen3-embedding-0.6b`` (``D:\\SuperEmbedder\\eval\\k1\\run1_output\\run_files\\
   run1-full\\<set>\\qwen3-embedding-0.6b.trec``) are copied into this run's own output
   directory and read back by ``runner.run_gate`` (``embed_runner.ModelSpec.reuse_trec_run_dir``)
   -- five hours of GPU time already spent, not spent again.
2. **The reference is RE-EMBEDDED**, under its now-corrected query convention (design Section
   4.5: ``bge-small-en-v1.5``'s own model-card retrieval instruction, not bare).
3. **BM25 is REBUILT**, under the now-corrected standard analyzer (design Section 4.2:
   stopwords removed, Porter-stemmed).
4. **Everything else is unchanged**: the same five sets, the same qrels, the same guards, the
   same aggregation rule (Section 4.3), R1 (the independent scorer) and R2 (the published-
   anchor check) both still run.

Writes only into its own output directory -- never back into
``D:\\SuperEmbedder\\eval\\k1\\run1_output\\`` (Run 1's own output is evidence and stays
byte-identical; this ticket copies OUT of it, never writes into it).

Usage:
    py -3.13 eval/k1/tools/rerun_te50_amended.py --output-dir <path> [--run1-output D:\\SuperEmbedder\\eval\\k1\\run1_output]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1.embed_runner import BARE_QUERY_CONVENTION
from eval.k1.run_spec import QWEN3_EMB_QUERY_PROMPT, run1_amended_rerun
from eval.k1.runner import run_gate

K1_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SETS_LOCK_PATH = K1_DIR / "sets.lock.json"
DEFAULT_ANCHORS_PATH = K1_DIR / "anchors.json"
CANDIDATE_MODEL_NAME = "qwen3-embedding-0.6b"
FIVE_SETS = ["scifact", "nfcorpus", "fiqa", "arguana", "scidocs"]
RUN1_PACKET_NAME = "run1-full.json"


def _candidate_manifests_from_run1_packet(run1_packet: dict, set_name: str) -> tuple:
    """TE-51 review, H-3: the reused arm's real provenance, read from the packet that actually
    produced it, rather than a two-key stub. Run 1's own packet predates the TE-49 amendment and
    carries NO ``query_convention`` field at all (verified,
    ``Claude/Poirot/b16ac70-te51-k1-instrument-confirmation.md`` H-1's own discriminator) -- but
    this candidate's actual query-side instruction has not changed since (design Section 17,
    TE-49, amended the REFERENCE's convention and the BM25 analyzer, not the candidate's query
    embedding), so the value it would have recorded is backfilled here from the model's own
    static spec (``run_spec.QWEN3_EMB_QUERY_PROMPT``) rather than left missing. This is the ONLY
    backfill this tool performs -- a source packet that lacks other provenance fields is carried
    forward exactly as thin as it arrived, and ``runner.run_gate``'s own
    ``check_query_convention_recorded`` call (TE-51 H-5) is what refuses a genuinely incomplete
    sidecar rather than this tool papering over one."""
    model_result = run1_packet["sets"][set_name]["models"][CANDIDATE_MODEL_NAME]
    corpus_manifest = dict(model_result.get("corpus_manifest", {}))
    query_manifest = dict(model_result.get("query_manifest", {}))
    if not query_manifest.get("query_convention"):
        query_manifest["query_convention"] = QWEN3_EMB_QUERY_PROMPT or BARE_QUERY_CONVENTION
    return corpus_manifest, query_manifest


def copy_candidate_rankings(run1_output_dir: Path, dest_dir: Path) -> None:
    """Copies Run 1's own persisted candidate TREC run files, one per set, into
    ``dest_dir/<set_name>/qwen3-embedding-0.6b.trec`` -- the layout
    ``embed_runner.ModelSpec.reuse_trec_run_dir`` expects. Refuses (``FileNotFoundError``)
    if any of the five is missing, so a partial reuse never silently proceeds as though the
    candidate had been evaluated on every set.

    **TE-51 review, H-3:** also writes a ``dest_dir/<set_name>/qwen3-embedding-0.6b.manifest.json``
    sidecar per set, carrying the reused arm's real provenance -- read from Run 1's own packet
    (``run1_output_dir/run1-full.json``, read-only; never written) -- so ``runner.run_gate``'s
    reuse path is not left assembling a packet with no `query_convention` for the arm being
    graded. Refuses (``FileNotFoundError``) if Run 1's own packet is not present, since there is
    then nothing to source the sidecar from."""
    run1_packet_path = run1_output_dir / RUN1_PACKET_NAME
    if not run1_packet_path.exists():
        raise FileNotFoundError(
            f"Run 1's own packet ({run1_packet_path}) is not present -- cannot carry the "
            f"reused candidate arm's provenance forward without it (TE-51 H-3)"
        )
    run1_packet = json.loads(run1_packet_path.read_text(encoding="utf-8"))

    missing = []
    for set_name in FIVE_SETS:
        src = run1_output_dir / "run_files" / "run1-full" / set_name / f"{CANDIDATE_MODEL_NAME}.trec"
        if not src.exists():
            missing.append(str(src))
            continue
        dst = dest_dir / set_name / f"{CANDIDATE_MODEL_NAME}.trec"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

        corpus_manifest, query_manifest = _candidate_manifests_from_run1_packet(run1_packet, set_name)
        manifest_path = dst.parent / f"{CANDIDATE_MODEL_NAME}.manifest.json"
        manifest_path.write_text(
            json.dumps({"corpus_manifest": corpus_manifest, "query_manifest": query_manifest},
                       indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if missing:
        raise FileNotFoundError(
            f"Run 1's own candidate TREC run file is missing for {len(missing)} set(s), "
            f"cannot reuse a partial candidate roster: {missing}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                         help="This run's own output directory (never Run 1's).")
    parser.add_argument("--run1-output", type=Path,
                         default=Path(r"D:\SuperEmbedder\eval\k1\run1_output"),
                         help="Run 1's output directory, read-only -- candidate TREC files "
                              "are copied OUT of here, nothing is written into it.")
    parser.add_argument("--sets-lock", type=Path, default=DEFAULT_SETS_LOCK_PATH)
    parser.add_argument("--anchors", type=Path, default=DEFAULT_ANCHORS_PATH)
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    reused_candidate_dir = output_dir / "reused_candidate"

    print(f"[rerun_te50_amended] copying Run 1's candidate rankings from {args.run1_output} "
          f"into {reused_candidate_dir} (read-only source, write-only destination)")
    copy_candidate_rankings(args.run1_output, reused_candidate_dir)

    run_spec = run1_amended_rerun(candidate_reuse_dir=str(reused_candidate_dir))
    print(f"[rerun_te50_amended] run_id={run_spec.run_id} sets={run_spec.set_names} "
          f"models={[m.name for m in run_spec.models]}")

    packet = run_gate(
        run_spec,
        sets_lock_path=args.sets_lock,
        anchors_path=args.anchors,
        output_dir=output_dir,
    )

    gate_verdict = packet["gate_verdict"]
    print(f"[rerun_te50_amended] DONE. gate_verdict.passed={gate_verdict['passed']}")
    print(f"[rerun_te50_amended] reason: {gate_verdict['reason']}")
    print(f"[rerun_te50_amended] packet written to {output_dir / (run_spec.run_id + '.json')}")


if __name__ == "__main__":
    main()
