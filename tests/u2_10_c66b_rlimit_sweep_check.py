"""U2 cloud build: build and run U2-10's C66 (b), the RLIMIT_AS sweep (GCC
leg), on the minimal-geometry cap-5,000 pair. See the executable's header."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = "u2_10_c66b_rlimit_sweep_test"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import u2_9_workspace_cells_check as u29  # noqa: E402
    pair_dir = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    try:
        u29.ensure_pair(pair_dir)
    except Exception as ex:  # noqa: BLE001
        print(f"[FAIL] minimal cap-5,000 pair could not be minted: {ex}")
        return 1
    b = subprocess.run([args.cmake_executable, "--build", str(build_dir), "--target", TARGET], cwd=REPO_ROOT,
                       capture_output=True, text=True, errors="replace")
    if b.returncode:
        print(f"[FAIL] {TARGET} build failed\n{(b.stdout + b.stderr)[-3000:]}")
        return 1
    exe = build_dir / "tests" / TARGET
    # glibc caches exited threads' stacks and reuses them without a new mapping,
    # so under RLIMIT_AS a thread start after a warm-up never maps a stack and
    # the limit cannot reach it. The cache is turned off, so every start maps
    # its stack under the limit (a harness choice, stated as a build-time item).
    env = dict(os.environ)
    env["GLIBC_TUNABLES"] = "glibc.pthread.stack_cache_size=0"
    run = subprocess.run([str(exe), "--model", str(pair_dir / "u1_pair_model.sslm"),
                          "--tokenizer", str(pair_dir / "u1_pair_tokenizer.sslm")],
                         cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", timeout=1800, env=env)
    print(run.stdout)
    return 1 if run.returncode or "[FAIL]" in run.stdout else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
