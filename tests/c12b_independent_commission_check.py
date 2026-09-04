"""Independent must-accept/must-reject commissioning for C12b.

The product builder's wrong-position control is useful but maker-authored.
This integration-review control independently mutates PS-N's real arithmetic
path, rebuilds the actual C12b instrument, and requires the exact-rational
oracle to reject it.  The unmodified instrument must first pass S1-S5.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MUTATION_FROM = "const BigUInt mag = BigUInt(abs_c).MulU64(abs_m);"
MUTATION_TO = "const BigUInt mag = BigUInt(abs_c + 1u).MulU64(abs_m);"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--build-dir", required=True, type=Path)
    ap.add_argument("--engine-prefix", required=True, type=Path)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--ninja-executable", required=True)
    ap.add_argument("--python-executable", required=True)
    ap.add_argument("--cxx-compiler", default="")
    ap.add_argument("--rc-compiler", default="")
    ap.add_argument("--mt-executable", default="")
    args = ap.parse_args(argv)
    args.instrument = str(Path(args.instrument).resolve())
    args.build_dir = args.build_dir.resolve()
    args.engine_prefix = args.engine_prefix.resolve()

    checker = REPO_ROOT / "tests" / "c12b_row_digest_check.py"
    baseline_dir = args.build_dir / "baseline"
    baseline = run(
        [args.python_executable, str(checker), "--instrument", args.instrument,
         "--build-dir", str(baseline_dir)],
        cwd=REPO_ROOT,
    )
    baseline_output = baseline.stdout + baseline.stderr
    if baseline.returncode != 0 or "FAIL" in baseline_output:
        print("FAIL: independent must-accept did not pass")
        print(baseline_output[-4000:])
        return 1

    mutant_src = args.build_dir / "mutant_src"
    mutant_build = args.build_dir / "mutant_build"
    shutil.rmtree(args.build_dir, ignore_errors=True)
    args.build_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REPO_ROOT,
        mutant_src,
        ignore=shutil.ignore_patterns(".git", "build", "__pycache__", "*.pyc"),
    )
    source_fixture = REPO_ROOT / "build" / "_scratch" / "synthetic_te62_c39.sslm"
    if not source_fixture.exists():
        print(f"FAIL: baseline synthetic artifact is missing: {source_fixture}")
        return 1
    mutant_fixture = mutant_src / "build" / "_scratch" / source_fixture.name
    mutant_fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_fixture, mutant_fixture)

    product = mutant_src / "src" / "superembedder" / "ps_n_pool.cpp"
    text = product.read_text(encoding="utf-8")
    if text.count(MUTATION_FROM) != 1:
        print(f"FAIL: mutation anchor count is {text.count(MUTATION_FROM)}, expected 1")
        return 1
    product.write_text(text.replace(MUTATION_FROM, MUTATION_TO, 1), encoding="utf-8", newline="\n")

    configure = [
        args.cmake_executable, "-G", "Ninja", "-S", str(mutant_src), "-B", str(mutant_build),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_MAKE_PROGRAM={args.ninja_executable}",
        f"-DCMAKE_PREFIX_PATH={args.engine_prefix.resolve()}",
        f"-DPython3_EXECUTABLE={args.python_executable}",
    ]
    if args.cxx_compiler:
        configure.append(f"-DCMAKE_CXX_COMPILER={args.cxx_compiler}")
    if args.rc_compiler:
        configure.append(f"-DCMAKE_RC_COMPILER={args.rc_compiler}")
    if args.mt_executable:
        configure.append(f"-DCMAKE_MT={args.mt_executable}")
    configured = run(configure, cwd=mutant_src)
    if configured.returncode != 0:
        print("FAIL: mutant configure failed")
        print((configured.stdout + configured.stderr)[-4000:])
        return 1

    built = run(
        [args.cmake_executable, "--build", str(mutant_build), "--target", "semb_c12b_row_digest"],
        cwd=mutant_src,
    )
    if built.returncode != 0:
        print("FAIL: mutant build failed")
        print((built.stdout + built.stderr)[-4000:])
        return 1

    suffix = ".exe" if os.name == "nt" else ""
    mutant_instrument = mutant_build / f"semb_c12b_row_digest{suffix}"
    rejected = run(
        [args.python_executable, str(mutant_src / "tests" / "c12b_row_digest_check.py"),
         "--instrument", str(mutant_instrument), "--build-dir", str(args.build_dir / "mutant_run")],
        cwd=mutant_src,
        env=os.environ.copy(),
    )
    rejected_output = rejected.stdout + rejected.stderr
    if rejected.returncode == 0 or "[FAIL] S5 C1' oracle" not in rejected_output:
        print("FAIL: arithmetic mutant was not rejected by C12b's exact-rational oracle")
        print(rejected_output[-4000:])
        return 1

    print("c12b_independent_commission_check: PASS (unmodified accepted; PS-N arithmetic mutant rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
