"""U3 red suite: the dev box's steps, in order, one ctest each, resumable.

The dev box crashes now and then (faulty RAM), so every step is one ctest,
short where the plan allows, and its outcome is written to disk the moment it
ends: build/_u3_logs/devbox/<step>.done holds the ctest exit code and the
time. `--next` runs the first step with no .done file; a crash mid-step leaves
no .done, so the next `--next` re-runs that step, and the step's own driver
resumes inside it where it can (the per-site sweeps read their logs; the real
legs reuse complete banks). Nothing here decides a verdict: each ctest prints
its own [PASS]/[FAIL]/[RED-UNIMPLEMENTED] lines into build/_u3_logs/.

  python tests/u3_devbox_steps.py --build-dir <SEMB_BUILD_GPU=ON tree> --list
  python tests/u3_devbox_steps.py --build-dir <tree> --next        (one step)
  python tests/u3_devbox_steps.py --build-dir <tree> --run <step>  (that step again)
  python tests/u3_devbox_steps.py --build-dir <tree> --status

Commissioning steps (row 5 (d), P:4215) run in a SECOND tree configured
against the engine at v1.7.1 with -DSEMB_U3_COMMISSION_TREE=ON; pass that tree
as --commission-build-dir. They come before any decision-bearing (d) run.
"""
from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

GPU_CELLS = [
    "row1_lifetime", "row1_slots_mc8", "row1_slots_unbounded", "row1_default_release", "row1_hold_600",
    "row3_mc4", "row3_batch16", "row3a_two_handles", "row3b_one_handle", "row4_shapes",
    "row5a_mechanism", "row5b_prefill", "row5b_seqcreate", "row5c_open_lost", "row5c_open_rejected", "row5d_seam",
    "row5f_batch_guard", "row5f_batch_lost", "c10e1", "c10e4_scale", "c10e4_last_wq", "c10e4_wb15", "c10e2",
    "c10i_before_device", "row7_fingerprint", "row11_gpu_triples", "c10d_index_default", "c10d_index_0",
    "c10d_refused_then_corrected_99", "c10d_refused_then_corrected_abc", "c10d_after_success",
    "c10d_refused_after_creation", "c10d_debug_layer", "c10d_b5_srv", "c10d_b5_uav",
]

# (step, tree): tree "main" is --build-dir, "commission" is --commission-build-dir.
STEPS: list[tuple[str, str]] = [
    # The ON tree's own portable cells first: the ABI, the seam's presence and absence, the CPU counter.
    ("u3_abi_check", "main"), ("u3_gpu_seam_absent_check", "main"), ("u3_cpu_seam_check", "main"),
    # Row 5 (a): the CPU oracle's precondition, then the [U] GPU half, before any green count (P:4215, P:4261).
    ("u3_guard_fixture_check", "main"), ("u3_gpu_cell_row5a_guard", "main"),
    # Row 5 (d)'s commissioning against v1.7.1, before its first decision-bearing run (P:4215).
    ("u3_gpu_alloc_d1_commission", "commission"), ("u3_gpu_alloc_d2_commission", "commission"),
    ("u3_gpu_alloc_d4_commission", "commission"),
    # The seam cells, one process each.
    *[(f"u3_gpu_cell_{c}", "main") for c in GPU_CELLS],
    # Row 5 (d) at v1.8.0.
    ("u3_gpu_alloc_count", "main"), ("u3_gpu_alloc_mr_removed", "main"), ("u3_gpu_alloc_d1", "main"),
    ("u3_gpu_alloc_d2", "main"), ("u3_gpu_alloc_d3h", "main"), ("u3_gpu_alloc_d3d", "main"),
    ("u3_gpu_alloc_d4", "main"),
    # J12: C64's GPU leg.
    *[(f"u3_c64_gpu_{r}_{a}", "main") for r in ("semb_encoder_open", "semb_encode", "semb_encode_query",
                                                "semb_encode_batch") for a in ("a", "a2", "b")],
    # The surface: CLI, configure, pin tool, in the ON tree.
    ("u3_cli_device_check", "main"), ("u3_configure_legs_check", "main"), ("u3_pin_tool_gpu_check", "main"),
    ("u3_row_digest_pair_selftest", "main"),
    # C10's real-artifact legs, shortest first; (a) before (b), (i) verify and (e) 2 which read its banks.
    ("u3_gpu_real_e2", "main"), ("u3_gpu_real_a", "main"), ("u3_gpu_real_b", "main"),
    ("u3_gpu_real_i_verify", "main"), ("u3_gpu_real_i_install", "main"), ("u3_gpu_real_g4096", "main"),
    ("u3_gpu_real_h", "main"), ("u3_gpu_real_g8192", "main"), ("u3_gpu_real_gcap", "main"),
    # C11: pilots first (P:4196), then the full readings.
    ("u3_c11_tokps_pilot", "main"), ("u3_c11_query_pilot", "main"), ("u3_c11_device_pilot", "main"),
    ("u3_c11_tokps_full", "main"), ("u3_c11_query_full", "main"), ("u3_c11_device_full", "main"),
]


def done_dir(build: Path) -> Path:
    d = build / "_u3_logs" / "devbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_step(step: str, tree: Path, marks: Path) -> int:
    log = marks / f"{step}.ctest.log"
    cmd = ["ctest", "--test-dir", str(tree), "-R", f"^{step}$", "--output-on-failure", "--output-log", str(log)]
    print("$ " + " ".join(cmd), flush=True)
    rc = subprocess.run(cmd).returncode
    (marks / f"{step}.done").write_text(f"exit={rc} at={datetime.datetime.now().isoformat(timespec='seconds')}\n",
                                        encoding="utf-8")
    return rc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--commission-build-dir", default="")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--next", action="store_true")
    g.add_argument("--run", default="")
    args = ap.parse_args(argv)
    build = Path(args.build_dir).resolve()
    marks = done_dir(build)
    trees = {"main": build, "commission": Path(args.commission_build_dir).resolve() if args.commission_build_dir else None}
    if args.list or args.status:
        for i, (step, tree) in enumerate(STEPS, 1):
            mark = marks / f"{step}.done"
            state = mark.read_text(encoding="utf-8").strip() if mark.is_file() else "pending"
            print(f"{i:3d}. {step:48s} [{tree}] {state if args.status else ''}")
        return 0
    if args.run:
        tree = dict(STEPS).get(args.run)
        if tree is None:
            print(f"unknown step {args.run}")
            return 2
        if trees[tree] is None:
            print(f"{args.run} runs in the commissioning tree: pass --commission-build-dir")
            return 2
        return run_step(args.run, trees[tree], marks)
    for step, tree in STEPS:
        if (marks / f"{step}.done").is_file():
            continue
        if trees[tree] is None:
            print(f"next step {step} runs in the commissioning tree (engine v1.7.1, -DSEMB_U3_COMMISSION_TREE=ON): "
                  f"pass --commission-build-dir, or --run a later step by name")
            return 2
        return run_step(step, trees[tree], marks)
    print("every step has a .done marker; --status lists them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
