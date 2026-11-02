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

Tree A (--build-dir) is the SEMB_BUILD_GPU=ON tree at the checked-in pin. Leave
SEMB_U3_SHADER_TO_REMOVE empty: c10d_refused_after_creation then hides the
staged <u3_gpu_cells_test dir>/shaders/down_proj_gemm_wide_h8.cso, the plan's
construction (te266 P:1496, T-2842 F1) re-aimed at the multi-row prompt's GEMM
(since SuperSLM 1.18 the one-row down_proj_gemm_site.cso runs only for a
one-row tail). Set it only to name another
shader the prefill dispatches; one it never dispatches (attention_score_site.cso
on the pair) leaves every call SSLM_OK and the cell red for the wrong reason.
Tree A also needs -DSEMB_U3_CPU_ENGINE_PREFIX=<a pin install made
WITHOUT --with-gpu> (U2's CPU-only install serves): G10-win configures ON
against it and must be refused SEMB_ENGINE_GPU_MISSING. Without it
u3_configure_legs_check skips (77) on Windows instead of passing.

RE-RUN after the U3 code review's test fixes (C1-C4): delete the .done marker
of each step below (or `--run` it), and for the C64 open steps also delete
build/_u3_logs/c64gpu_semb_encoder_open_<arm>.sweep.log, whose sites were
numbered by the old exhaustive population:
  u3_configure_legs_check            (C1: G10-win's own CPU-only prefix)
  u3_c64_gpu_*                       (C2: warm open-and-close before the close-all
                                      base; semb_encoder_open now sweeps a finite
                                      site plan -- delete every c64gpu_* sweep log)
  u3_fiqa_sets_selftest              (C3: the recorded query digest is required)
  u3_c11_tokps_pilot, u3_c11_tokps_full   (C4: skips when fiqa-long80 is absent)
  u3_gpu_alloc_count, u3_gpu_alloc_d1, u3_gpu_alloc_d3h, u3_gpu_alloc_d3d (and the
                                     d1 commissioning step in tree B): row 5(d) now sweeps
                                     a planned population -- d1 every host allocation
                                     inside an engine call of the encode plus a sample of
                                     U3's frames, d3h/d3d every allocation / creation
                                     inside sslm_gpu_model_map -- instead of every counted
                                     allocation (164,574 / 13,893,260, measured at v1.8.0). Delete
                                     build/_u3_logs/alloc_{d1,d3h,d3d}*.sweep.log first:
                                     their sites were numbered by the old population. The
                                     count step's CLASS lines show where K goes.
  u3_gpu_alloc_d3h                   (again, after the conductor's d3h ruling) d3h now sweeps a
                                     deterministic ~90-site sample of the model map's 1,742 host
                                     allocations (first, last, every Nth, the 4 largest; its
                                     PLAN line prints the rule and N) instead of all of them
                                     (~38.7 h). Its old log's k's belong to the exhaustive plan
                                     and would make the resume skip sampled sites, so
                                     build/_u3_logs/alloc_d3h.sweep.log must go before it runs:
                                     this runner moves it aside by itself (to
                                     alloc_d3h.sweep.log.exhaustive-<time>) when its PLAN line
                                     carries no sample= rule. Delete u3_gpu_alloc_d3h.done if
                                     the step has one, or `--run u3_gpu_alloc_d3h`.

PROGRESS: ctest runs with -V, so each site's BEGIN/SITE (ARM for C64) line reaches the
console as it lands; build/_u3_logs/<step>.sweep.log is synced to disk per line, so
its size in a directory listing grows as the sweep goes and a crash loses nothing
already written. (Earlier binaries only flushed to the OS cache: the box read a C64
sweep log at 0 B for 88 minutes.)

Commissioning steps (row 5 (d), P:4215) run in a SECOND tree (tree B)
configured against the engine at v1.7.1 with -DSEMB_U3_COMMISSION_TREE=ON; pass
that tree as --commission-build-dir. They come before any decision-bearing (d)
run. Tree B cannot configure against the checked-in superslm.lock (it pins
a later engine, so the configure refuses SEMB_ENGINE_PIN_MISMATCH): point EngineGuards'
own override at the v1.7.1 lock the pin tool wrote for the --with-gpu install,
never by editing the checked-in lock:
  cmake -S <repo> -B <tree B> -DSEMB_BUILD_GPU=ON -DSEMB_U3_COMMISSION_TREE=ON
        -DCMAKE_PREFIX_PATH=<v1.7.1 --with-gpu install>
        -DSEMB_ENGINE_LOCK_FILE=<the v1.7.1 lock the pin tool wrote> ...
"""
from __future__ import annotations

import argparse
import datetime
import os
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
    # Row 5 (d) at the checked-in pin.
    ("u3_gpu_alloc_count", "main"), ("u3_gpu_alloc_mr_removed", "main"), ("u3_gpu_alloc_d1", "main"),
    ("u3_gpu_alloc_d2", "main"), ("u3_gpu_alloc_d3h", "main"), ("u3_gpu_alloc_d3d", "main"),
    ("u3_gpu_alloc_d4", "main"),
    # J12: C64's GPU leg.
    *[(f"u3_c64_gpu_{r}_{a}", "main") for r in ("semb_encoder_open", "semb_encode", "semb_encode_query",
                                                "semb_encode_batch") for a in ("a", "a2", "b")],
    # The surface: CLI, configure, pin tool, in the ON tree.
    ("u3_cli_device_check", "main"), ("u3_configure_legs_check", "main"), ("u3_pin_tool_gpu_check", "main"),
    ("u3_row_digest_pair_selftest", "main"), ("u3_fiqa_sets_selftest", "main"),
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


def restore_hidden_shaders(tree: Path) -> None:
    """c10d_refused_after_creation renames one staged .cso to <name>.cso.removed and back. A crash between
    the two leaves every later GPU step without that shader, and the stamped staging will not copy it
    again. Before each step, put back any renamed-away shader whose original is absent (the cell does the
    same at its own start)."""
    for dirpath, _dirs, files in os.walk(tree):
        for f in files:
            if f.endswith(".cso.removed"):
                moved = Path(dirpath) / f
                orig = moved.with_name(f[: -len(".removed")])
                if not orig.exists():
                    moved.rename(orig)
                    print(f"restored {orig} (left renamed by an interrupted c10d_refused_after_creation)")


# Sweep logs a step must not resume from once its population changed: step -> (log under _u3_logs, the
# token the current binary's PLAN line carries). A log whose PLAN lines lack it was numbered by the old
# population and is moved aside before the step runs.
STALE_SWEEP_LOGS: dict[str, tuple[str, str]] = {
    "u3_gpu_alloc_d3h": ("alloc_d3h.sweep.log", "sample="),
}


def set_aside_stale_log(step: str, tree: Path) -> None:
    entry = STALE_SWEEP_LOGS.get(step)
    if entry is None:
        return
    name, token = entry
    log = tree / "_u3_logs" / name
    if not log.is_file():
        return
    plans = [ln for ln in log.read_text(errors="replace").splitlines() if ln.startswith("PLAN ")]
    if plans and all(token in ln for ln in plans):
        return
    aside = log.with_name(f"{name}.exhaustive-{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}")
    log.rename(aside)
    print(f"moved {log} aside to {aside.name}: it was written under the old site population (no '{token}' "
          f"in its PLAN line), and resuming from it would skip planned sites", flush=True)


def run_step(step: str, tree: Path, marks: Path) -> int:
    restore_hidden_shaders(tree)
    set_aside_stale_log(step, tree)
    log = marks / f"{step}.ctest.log"
    cmd = ["ctest", "--test-dir", str(tree), "-R", f"^{step}$", "-V", "--output-on-failure", "--output-log",
           str(log)]
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
            print(f"next step {step} runs in the commissioning tree (engine v1.7.1, -DSEMB_U3_COMMISSION_TREE=ON, "
                  f"-DSEMB_ENGINE_LOCK_FILE=<the v1.7.1 lock>): "
                  f"pass --commission-build-dir, or --run a later step by name")
            return 2
        return run_step(step, trees[tree], marks)
    print("every step has a .done marker; --status lists them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
