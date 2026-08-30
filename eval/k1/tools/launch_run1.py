#!/usr/bin/env python3
"""Launches K1 Run 1 (design Section 1, `te33-k1-gate-design-2026-08-25.md`) together with
R3 (design Section 5) -- TE-39 stage (e).

**Why this script exists.** R1 (the independent scorer) is built into the instrument
(``RunSpec.r1_independent_scorer``, wired into every ``run_gate`` call). R3 ("the number does
not move with the harness") is not: the design specifies it as a procedure over two runs of
the same instrument, not a component the instrument computes internally. This script composes
that procedure -- two full runs of the ratified candidate (Qwen3-Embedding-0.6B) at the same
batch size on SciFact and NFCorpus, required bit-identical by SHA-256 over the emitted TREC
run file; one further run at a different batch size, required to agree within 1e-4 on
nDCG@10 -- and then launches the full five-set Run 1 sweep. R3 is not required for Run 1 to
launch and does not gate it: both run, in one detached process, and the R3 report is folded
into Run 1's packet as an additional field so a reader sees both without cross-referencing
two artifacts.

**This job outlives any interactive tool call.** It is meant to be started via PowerShell
``Start-Process`` with its stdout/stderr redirected to files, not run inline. See the build
log (``Claude/Brunel/`` in the Wizard project's records tree, TE-39) for the exact launch
command, the PID it was started under, and the output paths.

Run with ``-u`` (unbuffered) so a tailed log file shows progress as it happens:

    py -3.13 -u eval/k1/tools/launch_run1.py

Writes, under ``eval/k1/run1_output/``:

- ``r3/`` -- R3's three run packets, their TREC run files, and ``r3_replication_report.json``.
- ``run1-full.json`` / ``run1-full.txt`` -- Run 1's own packet and human-readable table
  (``runner.run_gate``'s normal output), augmented in place with ``public_sets``,
  ``internal_diagnostic_sets`` (design Section 16 -- both groups still gate F1/F2; this is
  legibility only) and ``r3_replication`` (this script's own R3 report).
- ``run_files/run1-full/<set>/<model>.trec`` -- Run 1's own ranking files (``runner.py``'s
  normal per-model, per-set output).
- ``TE39_RUN1_COMPLETE.json`` on success, or ``TE39_RUN1_FAILED.json`` (with the traceback)
  on an unhandled exception -- the artifact-based completion signal. **A vanished process is
  not a clean exit**: check one of these two files (or the run1-full.json packet itself),
  never the absence of a PID.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.k1 import run_spec as run_spec_mod
from eval.k1.run_spec import RunSpec
from eval.k1.runner import render_human_table, run_gate

K1_DIR = Path(__file__).resolve().parents[1]
SETS_LOCK_PATH = K1_DIR / "sets.lock.json"
ANCHORS_PATH = K1_DIR / "anchors.json"
OUTPUT_ROOT = K1_DIR / "run1_output"
R3_OUTPUT_DIR = OUTPUT_ROOT / "r3"

R3_SETS = ["scifact", "nfcorpus"]  # design Section 5, R3: "R3 runs on SciFact and NFCorpus
                                    # only ... arithmetic stability is a property of the
                                    # harness and does not vary by set"
NDCG_AGREEMENT_TOLERANCE = 1e-4  # design Section 5, R3's batch-varied requirement


def _log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trec_path(run_id: str, set_name: str, model_name: str) -> Path:
    return R3_OUTPUT_DIR / "run_files" / run_id / set_name / f"{model_name}.trec"


def run_r3() -> dict:
    """Composes R3 (design Section 5): two full runs of the candidate at the same batch size
    on SciFact and NFCorpus, required bit-identical; one further run at a different batch
    size, required to agree within 1e-4 on nDCG@10. Returns the consolidated report and also
    writes it to ``r3/r3_replication_report.json``."""
    candidate = run_spec_mod.QWEN3_EMB_0_6B
    same_batch = candidate.batch_size
    alt_batch = max(1, same_batch // 2)
    if alt_batch == same_batch:
        alt_batch = same_batch * 2
    alt_candidate = dataclasses.replace(
        candidate, name=f"{candidate.name}-batch{alt_batch}", batch_size=alt_batch
    )

    run_id_a = "r3-batch8-run-a" if same_batch == 8 else f"r3-batch{same_batch}-run-a"
    run_id_b = "r3-batch8-run-b" if same_batch == 8 else f"r3-batch{same_batch}-run-b"
    run_id_c = f"r3-batch{alt_batch}-run-c"

    common = dict(
        set_names=list(R3_SETS), is_gate_reading=False, include_bm25=False,
        r1_independent_scorer=False, allow_missing_license=False,
    )

    _log(f"R3 run A: candidate at batch={same_batch}, run_id={run_id_a}")
    spec_a = RunSpec(run_id=run_id_a, models=[candidate], **common)
    packet_a = run_gate(spec_a, SETS_LOCK_PATH, ANCHORS_PATH, output_dir=R3_OUTPUT_DIR)

    _log(f"R3 run B: candidate at batch={same_batch}, run_id={run_id_b} (second full run, same config)")
    spec_b = RunSpec(run_id=run_id_b, models=[candidate], **common)
    packet_b = run_gate(spec_b, SETS_LOCK_PATH, ANCHORS_PATH, output_dir=R3_OUTPUT_DIR)

    _log(f"R3 run C: candidate at batch={alt_batch} (different batch size), run_id={run_id_c}")
    spec_c = RunSpec(run_id=run_id_c, models=[alt_candidate], **common)
    packet_c = run_gate(spec_c, SETS_LOCK_PATH, ANCHORS_PATH, output_dir=R3_OUTPUT_DIR)

    sha256_report: dict = {}
    for set_name in R3_SETS:
        path_a = _trec_path(run_id_a, set_name, candidate.name)
        path_b = _trec_path(run_id_b, set_name, candidate.name)
        sha_a = _sha256_of_file(path_a)
        sha_b = _sha256_of_file(path_b)
        sha256_report[set_name] = {
            "run_a_file": str(path_a), "run_a_sha256": sha_a,
            "run_b_file": str(path_b), "run_b_sha256": sha_b,
            "bit_identical": sha_a == sha_b,
        }
        _log(f"R3 SHA-256 [{set_name}]: {'BIT-IDENTICAL' if sha_a == sha_b else 'DIVERGED'} "
             f"({sha_a[:12]}... vs {sha_b[:12]}...)")

    ndcg_delta_report: dict = {}
    for set_name in R3_SETS:
        ndcg_a = packet_a["sets"][set_name]["models"][candidate.name]["ndcg_at_10"]
        ndcg_c = packet_c["sets"][set_name]["models"][alt_candidate.name]["ndcg_at_10"]
        delta = abs(ndcg_a - ndcg_c)
        ndcg_delta_report[set_name] = {
            "run_a_ndcg_at_10": ndcg_a, "run_c_ndcg_at_10": ndcg_c,
            "delta": delta, "within_tolerance": delta <= NDCG_AGREEMENT_TOLERANCE,
            "tolerance": NDCG_AGREEMENT_TOLERANCE,
        }
        _log(f"R3 batch-variation delta [{set_name}]: {delta:.8f} "
             f"({'within' if delta <= NDCG_AGREEMENT_TOLERANCE else 'EXCEEDS'} "
             f"{NDCG_AGREEMENT_TOLERANCE})")

    report = {
        "candidate": candidate.name,
        "same_batch_size": same_batch,
        "alt_batch_size": alt_batch,
        "run_ids": {"run_a": run_id_a, "run_b": run_id_b, "run_c": run_id_c},
        "sha256_bit_identity": sha256_report,
        "ndcg_batch_variation": ndcg_delta_report,
        "r3_holds": (
            all(v["bit_identical"] for v in sha256_report.values())
            and all(v["within_tolerance"] for v in ndcg_delta_report.values())
        ),
    }
    R3_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = R3_OUTPUT_DIR / "r3_replication_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    _log(f"R3 report written: {report_path} (r3_holds={report['r3_holds']})")
    return report


def run_full_gate(r3_report: dict) -> Path:
    """Runs Run 1's full five-set sweep and augments its packet, in place, with the
    public/internal-diagnostic set split (design Section 16) and the R3 report -- so a reader
    of ``run1-full.json`` sees both without cross-referencing a second artifact."""
    spec = run_spec_mod.run1_full()
    _log(f"Run 1: sets={spec.set_names} models={[m.name for m in spec.models]} "
         f"include_bm25={spec.include_bm25}")
    run_gate(spec, SETS_LOCK_PATH, ANCHORS_PATH, output_dir=OUTPUT_ROOT)

    json_path = OUTPUT_ROOT / f"{spec.run_id}.json"
    packet = json.loads(json_path.read_text(encoding="utf-8"))
    packet["public_sets"] = list(run_spec_mod.PUBLIC_SETS)
    packet["internal_diagnostic_sets"] = list(run_spec_mod.INTERNAL_DIAGNOSTIC_SETS)
    packet["r3_replication"] = r3_report
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")

    table = render_human_table(packet)
    table += (
        f"\npublic row (design Section 16): {', '.join(packet['public_sets'])}\n"
        f"internal diagnostics (still gate F1/F2 internally, not surfaced publicly): "
        f"{', '.join(packet['internal_diagnostic_sets'])}\n"
        f"\nR3 (design Section 5) -- composed by this launcher, not the instrument itself:\n"
        f"  candidate: {r3_report['candidate']}, same_batch={r3_report['same_batch_size']}, "
        f"alt_batch={r3_report['alt_batch_size']}\n"
    )
    for set_name in R3_SETS:
        sha = r3_report["sha256_bit_identity"][set_name]
        ndcg = r3_report["ndcg_batch_variation"][set_name]
        table += (
            f"  [{set_name}] bit-identical (same batch, two runs): {sha['bit_identical']}; "
            f"batch-varied nDCG delta: {ndcg['delta']:.8f} "
            f"(within {ndcg['tolerance']}: {ndcg['within_tolerance']})\n"
        )
    table += f"  R3 holds overall: {r3_report['r3_holds']}\n"
    table_path = OUTPUT_ROOT / f"{spec.run_id}.txt"
    table_path.write_text(table, encoding="utf-8")

    _log(f"Run 1 packet augmented and rewritten: {json_path}")
    return json_path


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    _log(f"TE-39 K1 Run 1 + R3 launch starting. Output root: {OUTPUT_ROOT}")

    try:
        r3_report = run_r3()
        run1_json_path = run_full_gate(r3_report)
        finished = datetime.now()
        completion = {
            "status": "COMPLETE",
            "started": started.isoformat(timespec="seconds"),
            "finished": finished.isoformat(timespec="seconds"),
            "wall_clock_seconds": (finished - started).total_seconds(),
            "r3_holds": r3_report["r3_holds"],
            "run1_packet": str(run1_json_path),
            "r3_report": str(R3_OUTPUT_DIR / "r3_replication_report.json"),
        }
        (OUTPUT_ROOT / "TE39_RUN1_COMPLETE.json").write_text(
            json.dumps(completion, indent=2, sort_keys=True), encoding="utf-8"
        )
        _log(f"DONE. wall_clock={completion['wall_clock_seconds']:.1f}s "
             f"r3_holds={r3_report['r3_holds']}")
    except Exception:
        finished = datetime.now()
        failure = {
            "status": "FAILED",
            "started": started.isoformat(timespec="seconds"),
            "finished": finished.isoformat(timespec="seconds"),
            "wall_clock_seconds": (finished - started).total_seconds(),
            "traceback": traceback.format_exc(),
        }
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        (OUTPUT_ROOT / "TE39_RUN1_FAILED.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True), encoding="utf-8"
        )
        _log("FAILED -- see TE39_RUN1_FAILED.json for the traceback")
        raise


if __name__ == "__main__":
    main()
