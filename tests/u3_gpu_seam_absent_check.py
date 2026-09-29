"""U3 red suite: C14's clause for te266 sec 4.2's adapter-boundary seam (P:4076:
"None of the seven exists in the shipping superembedder target, and the
build-configuration check C14 asserts that their symbols are absent from it").

Reads the archives' bytes, as K-18 (tests/u1_workspace_seam_absent_check.py)
does. Every U3 seam name is prefixed `semb_test_seam_`, so K-18's own scan
already refuses any of them in the shipped archive; this check names them one
by one and adds the must-accept K-18 cannot give for U3: the names ARE in the
test-seam archive, so their absence from the shipped one is a property of the
gate and not of a missing implementation.

  C14-U3a  the shipped superembedder archive holds none of the U3 seam names.
  C14-U3b  must-accept, every build: superembedder_testseam holds
           semb_test_seam_ps_n_select_count (sec 4.6 row 11's counter, in the
           interim TU).
  C14-U3c  must-accept, SEMB_BUILD_GPU=ON builds: superembedder_testseam holds
           every semb_test_seam_gpu_* name (engine_adapter_gpu.cpp). In an OFF
           build the GPU TU is not compiled: MISSING PREREQUISITE.

RED TODAY: C14-U3b (the counter is a builder item).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

GPU_NAMES = [
    "semb_test_seam_gpu_call_count", "semb_test_seam_gpu_call_log", "semb_test_seam_gpu_call_log_reset",
    "semb_test_seam_gpu_inject", "semb_test_seam_gpu_inject_clear", "semb_test_seam_gpu_lock_violations",
    "semb_test_seam_gpu_occupancy_max", "semb_test_seam_gpu_occupancy_reset", "semb_test_seam_gpu_occupancy_now",
    "semb_test_seam_gpu_context_count", "semb_test_seam_gpu_slot_record_count", "semb_test_seam_gpu_slot_bound",
    "semb_test_seam_gpu_try_lock", "semb_test_seam_gpu_arm_perturb", "semb_test_seam_gpu_perturb_disarm",
    "semb_test_seam_gpu_last_diverged_sequence", "semb_test_seam_gpu_last_read",
]
COUNTER = "semb_test_seam_ps_n_select_count"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--production", required=True)
    ap.add_argument("--testseam", required=True)
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--gpu", default="OFF")
    args = ap.parse_args(argv)
    for target in ("superembedder", "superembedder_testseam"):
        proc = subprocess.run([args.cmake_executable, "--build", args.build_dir, "--target", target],
                              capture_output=True, text=True, errors="replace")
        if proc.returncode:
            print(f"[FAIL] {target} build failed\n{(proc.stdout + proc.stderr)[-2000:]}")
            return 1
    prod = Path(args.production).read_bytes()
    seam = Path(args.testseam).read_bytes()
    failed = False
    present = [n for n in [*GPU_NAMES, COUNTER] if n.encode() in prod]
    print(f"[{'PASS' if not present else 'FAIL'}] C14-U3a the shipped archive holds no U3 seam name (P:4076): "
          + ("none of " + str(len(GPU_NAMES) + 1) if not present else ", ".join(present)))
    failed |= bool(present)
    has = COUNTER.encode() in seam
    print(f"[{'PASS' if has else 'FAIL'}] C14-U3b must-accept: superembedder_testseam holds {COUNTER} "
          f"(P:4221): {'present' if has else 'ABSENT (a builder item, te266 P:4267)'}")
    failed |= not has
    if args.gpu.upper() in ("ON", "TRUE", "1", "YES"):
        missing = [n for n in GPU_NAMES if n.encode() not in seam]
        print(f"[{'PASS' if not missing else 'FAIL'}] C14-U3c must-accept: superembedder_testseam holds every "
              f"semb_test_seam_gpu_* name: " + ("all " + str(len(GPU_NAMES)) if not missing else
                                                "absent: " + ", ".join(missing)))
        failed |= bool(missing)
    else:
        print("[MISSING PREREQUISITE] C14-U3c must-accept: the GPU seam names in superembedder_testseam: "
              "an OFF build compiles no GPU TU; runs in the SEMB_BUILD_GPU=ON tree (the dev box)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
