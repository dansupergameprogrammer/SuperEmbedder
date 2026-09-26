"""U2 cloud build, U2-9's C62: the adversary's must-reject (a) (te267 sec 5 U2-9, C62, P:2800-2802).

"A real open, large on the decided quantity, through the production data path. The pin-step build's
open reads 3,031.5 / 3,036.0 MiB at mc 1 [M], over each bound by ~2,390 MiB. Only that build's open
runs."

The pin-step build is the last build before U2-9 (P:2648): the SuperSLM v1.8.0 pin step as merged into
the U2 line (PIN_STEP_COMMIT, the second parent of the pin-step merge). This driver

  1. exports that commit's tree with `git archive` into the build's scratch (no worktree is registered),
     copies in THIS build's superslm.lock (the same engine the U2 tip links), and configures and builds
     its shipped `superembedder` static library with this build's generator, compilers, configuration
     and engine prefix;
  2. configures tests/c62_pin_step/ standalone, which compiles C62's own process (this tree's
     u2_9_c62_reader.cpp, u2_9_c62_process.cpp, u2_9_c62_resident_memory_test.cpp, unchanged) against
     the pin step's public header and links the pin step's library;
  3. runs it at --mc 1 and --mc 4 on the real model and tokenizer, one process each (P:2722), and
     requires C62 (a) to REFUSE the open on both counters in both processes.

Exit 0: both processes refused (a) on both counters. 1: a refusal did not fire, or the build failed.
77: SKIPPED (platform) off Windows (C62 is Windows only, P:2845), or MISSING PREREQUISITE without the
real model and tokenizer. --build-anyway builds steps 1-2 off Windows too (GCC proof of the mechanics),
then still exits 77 because C62's readings are Windows only.
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import io
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The pin step (SuperSLM v1.8.0) as merged into the U2 line at a26c5dc: its second parent.
PIN_STEP_COMMIT = "c9ff3dc"
SKIP = 77


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)


def fail(msg: str, proc: subprocess.CompletedProcess | None = None) -> int:
    print(f"[FAIL] C62 must-reject (a): {msg}")
    if proc is not None:
        print((proc.stdout + proc.stderr)[-4000:])
    return 1


def find_library(build: Path, config: str) -> Path | None:
    names = ("superembedder.lib", "libsuperembedder.a")
    for base in (build / config, build):
        for n in names:
            if (base / n).is_file():
                return base / n
    hits = [p for n in names for p in build.rglob(n)]
    return hits[0] if hits else None


def find_exe(build: Path, config: str) -> Path | None:
    for base in (build / config, build):
        for n in ("u2_9_c62_pin_step_process.exe", "u2_9_c62_pin_step_process"):
            if (base / n).is_file():
                return base / n
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--generator", required=True)
    ap.add_argument("--generator-platform", default="")
    ap.add_argument("--generator-toolset", default="")
    ap.add_argument("--c-compiler", default="")
    ap.add_argument("--cxx-compiler", default="")
    ap.add_argument("--config", default="Release")
    ap.add_argument("--prefix-path", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    ap.add_argument("--short", required=True)
    ap.add_argument("--long", required=True)
    ap.add_argument("--build-anyway", action="store_true")
    a = ap.parse_args(argv)

    windows = platform.system() == "Windows"
    if not windows and not a.build_anyway:
        print("SKIPPED (platform): C62 reads GetProcessMemoryInfo and QueryWorkingSetEx; it is Windows only "
              "(te267 U2-9, P:2845)")
        return SKIP
    if windows and (not a.model or not a.tokenizer):
        print("MISSING PREREQUISITE: C62's must-reject (a) needs the real model and tokenizer "
              "(configure with SEMB_C12B_MODEL and SEMB_U1_TOKENIZER). No verdict.")
        return SKIP

    scratch = Path(a.build_dir) / "_scratch" / "u2_9_c62_pin_step"
    src, build, link = scratch / "src", scratch / "build", scratch / "link"
    if scratch.exists():
        shutil.rmtree(scratch)
    src.mkdir(parents=True)
    # 1. The pin step's tree, exported (never a worktree), with this build's lock.
    arch = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "--format=tar", PIN_STEP_COMMIT],
                          capture_output=True, timeout=600)
    if arch.returncode:
        return fail(f"git archive {PIN_STEP_COMMIT} failed: {arch.stderr.decode(errors='replace')}")
    with tarfile.open(fileobj=io.BytesIO(arch.stdout)) as t:
        if sys.version_info >= (3, 12):
            t.extractall(src, filter="data")
        else:
            t.extractall(src)
    shutil.copyfile(REPO_ROOT / "superslm.lock", src / "superslm.lock")
    gen = ["-G", a.generator]
    if a.generator_platform:
        gen += ["-A", a.generator_platform]
    if a.generator_toolset:
        gen += ["-T", a.generator_toolset]
    common = gen + [f"-DCMAKE_BUILD_TYPE={a.config}", f"-DCMAKE_PREFIX_PATH={a.prefix_path}"]
    if a.c_compiler:
        common.append(f"-DCMAKE_C_COMPILER={a.c_compiler}")
    if a.cxx_compiler:
        common.append(f"-DCMAKE_CXX_COMPILER={a.cxx_compiler}")
    p = run([a.cmake_executable, "-S", str(src), "-B", str(build), *common,
             f"-DPython3_EXECUTABLE={a.python}"])
    if p.returncode:
        return fail(f"the pin step ({PIN_STEP_COMMIT}) did not configure", p)
    p = run([a.cmake_executable, "--build", str(build), "--config", a.config, "--target", "superembedder"])
    if p.returncode:
        return fail(f"the pin step's superembedder did not build", p)
    lib = find_library(build, a.config)
    if lib is None:
        return fail("the pin step's superembedder library is absent after a successful build")
    # 2. C62's process against the pin step's header and library.
    p = run([a.cmake_executable, "-S", str(REPO_ROOT / "tests" / "c62_pin_step"), "-B", str(link), *common,
             f"-DSEMB_PIN_STEP_SOURCE_DIR={src}", f"-DSEMB_PIN_STEP_LIBRARY={lib}"])
    if p.returncode:
        return fail("tests/c62_pin_step did not configure", p)
    p = run([a.cmake_executable, "--build", str(link), "--config", a.config])
    if p.returncode:
        return fail("C62's process did not build against the pin step", p)
    exe = find_exe(link, a.config)
    if exe is None:
        return fail("C62's pin-step process is absent after a successful build")
    print(f"built: C62's process on the pin step ({PIN_STEP_COMMIT}): {exe}")
    if not windows:
        print("SKIPPED (platform): built; C62's readings are Windows only (te267 U2-9, P:2845)")
        return SKIP

    # 3. One process per max_concurrency; (a) must be refused on both counters.
    failures = 0
    for mc in (1, 4):
        cmd = [str(exe), "--mc", str(mc), "--model", a.model, "--tokenizer", a.tokenizer, "--long", a.long]
        if mc == 1:
            cmd += ["--short", a.short]
        p = run(cmd, timeout=3600)
        print(p.stdout)
        if p.stderr.strip():
            print(p.stderr[-3000:])
        for counter in ("working set", "private bytes"):
            pat = re.compile(rf"^\[FAIL\] C62 \(a\) mc={mc} {counter}: after open", re.M)
            ok = bool(pat.search(p.stdout))
            print(f"[{'PASS' if ok else 'FAIL'}] must-reject (a) mc={mc} {counter}: C62 refuses the pin step's open")
            failures += 0 if ok else 1
        if p.returncode != 1:
            print(f"[FAIL] must-reject (a) mc={mc}: C62's process exited {p.returncode}, expected 1 (FAIL)")
            failures += 1
    print(f"C62 must-reject (a): {'every refusal fired' if not failures else f'{failures} refusal(s) missing'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
