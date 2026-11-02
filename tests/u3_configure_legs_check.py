"""U3 red suite: the configure legs (te266 sec 4.5 C10 (i) G10, P:4176; sec 4.6
row 8, P:4218; sec 4.7 step 3's option, P:4263-4275).

The plan places G10 "beside the existing configure legs in
te264_c42_configure_legs_check.py" (P:4176). These legs reuse that file's
apparatus (tools/ci/run_configure_matrix.py's copy_repo and
run_cmake_configure), so each configures exactly as C33's and C42-derive's do;
keeping them in their own file attributes each red to U3.

Legs:
  G10-off    OFF WINDOWS ONLY (constructible here, though the plan could not
             construct it on the dev box and made it a code-review check,
             P:4176): -DSEMB_BUILD_GPU=ON fails configure, and the output names
             SEMB_BUILD_GPU. No token is named (the planner's U3 ruling 2:
             the refusal names the option and says it requires Windows, before
             the SEMB_ENGINE_GPU_MISSING guard); the leg asserts the name.
  G10-off'   must-accept of G10-off: the same copy, the option absent,
             configures (a configure that refuses everything cannot pass).
  G10-win    WINDOWS ONLY: -DSEMB_BUILD_GPU=ON against a CPU-only pin install
             fails and names SEMB_ENGINE_GPU_MISSING (P:4176). The install is
             its own prerequisite, --cpu-engine-prefix (SEMB_U3_CPU_ENGINE_PREFIX:
             a pin install made WITHOUT --with-gpu; the dev box has U2's).
             It is never the tree's own --engine-prefix: a SEMB_BUILD_GPU=ON tree
             configured only against a --with-gpu install, so that prefix
             exports superslm_gpu and the nested configure succeeds (the U3
             code review's C1). A prefix that ships gpu-shaders is refused as
             SETUP, not graded.
  R8-accept  WINDOWS, a --with-gpu install: an ON and an OFF configure give equal
             compileFlags (P:4218 must-accept).
  R8-rej1    every platform: SEMB_BUILD_GPU added as a compile definition on the
             library target moves compileFlags (P:4218 must-reject 1). Computed
             with tools/compile_flags.py's own record() over each configure's
             compile_commands.json, with semb_build_step.py's own targets and
             exclusions.
  (R8's must-reject 2, a flagsSha over superslm and superslm_gpu together,
  is the pin tool's: tests/u3_pin_tool_gpu_check.py.)

RED TODAY: G10-off (the option does not exist: configure succeeds). R8-rej1 is
a must-reject whose construction works today (compileFlags already carries
definitions); it is the vitality half of R8-accept, which the dev box runs.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "ci"))
sys.path.insert(0, str(ROOT / "tools"))
import run_configure_matrix as matrix  # noqa: E402
import compile_flags  # noqa: E402
import semb_build_step  # noqa: E402

FAILED = False
MISSING_ON_WINDOWS = False  # a dev-box leg without its prerequisite: the test skips (77), never passes
TARGETS = ["superembedder", "semb", "semb_witness"]  # semb_build_step's --target list (CMakeLists.txt)


def emit(state: str, leg: str, detail: str) -> None:
    global FAILED
    global MISSING_ON_WINDOWS
    print(f"[{state}] {leg}: {detail}", flush=True)
    FAILED |= state in ("FAIL", "RED-UNIMPLEMENTED")
    MISSING_ON_WINDOWS |= state == "MISSING PREREQUISITE" and platform.system() == "Windows"


def tail(out: str, n: int = 6) -> str:
    return " | ".join(out.strip().splitlines()[-n:])[-600:]


def compile_flags_sha(build: Path, src: Path) -> str:
    entries = json.loads((build / "compile_commands.json").read_text(encoding="utf-8"))
    cache = {}
    for line in (build / "CMakeCache.txt").read_text(errors="replace").splitlines():
        if ":" in line and "=" in line and not line.startswith(("#", "//")):
            k, v = line.split("=", 1)
            cache[k.split(":", 1)[0]] = v
    family = compile_flags.family_of(cache.get("CMAKE_CXX_COMPILER_ID", ""),
                                     cache.get("CMAKE_CXX_COMPILER_FRONTEND_VARIANT", ""))
    roots = [(str(src), "<src>"), (str(build), "<build>"), (str(matrix.ENGINE_PREFIX), "<engine>")]
    rec, _ = compile_flags.record(entries, family, roots, TARGETS, list(semb_build_step.EXCLUDED_SOURCES),
                                  platform.system() == "Windows")
    return compile_flags.digest(rec) if rec else "unrecorded"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--engine-prefix", required=True)
    ap.add_argument("--gpu-engine-prefix", default="", help="a --with-gpu pin install (dev box)")
    ap.add_argument("--cpu-engine-prefix", default="", help="a CPU-only pin install, for G10-win (dev box)")
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--generator", default="Ninja")
    ap.add_argument("--ninja-executable", default="ninja")
    ap.add_argument("--python-executable", default=sys.executable)
    ap.add_argument("--scratch", default=None)
    args = ap.parse_args(argv)
    matrix.REPO_ROOT = Path(args.repo_root).resolve()
    matrix.ENGINE_PREFIX = Path(args.engine_prefix).resolve()
    matrix.CMAKE = args.cmake_executable
    matrix.GENERATOR = args.generator
    matrix.NINJA = args.ninja_executable
    matrix.PYEXE = args.python_executable
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="u3_cfg_"))
    matrix.SCRATCH = scratch
    scratch.mkdir(parents=True, exist_ok=True)
    windows = platform.system() == "Windows"
    try:
        src = matrix.copy_repo(scratch / "src")
        if not windows:
            rc, out = matrix.run_cmake_configure(src, scratch / "on_build", matrix.ENGINE_PREFIX,
                                                 {"SEMB_BUILD_GPU": "ON"})
            emit("PASS" if rc != 0 and "SEMB_BUILD_GPU" in out else "FAIL",
                 "G10-off -DSEMB_BUILD_GPU=ON off Windows fails configure naming SEMB_BUILD_GPU (P:4176)",
                 f"returncode {rc}; {tail(out)}")
            rc, out = matrix.run_cmake_configure(src, scratch / "off_build", matrix.ENGINE_PREFIX)
            emit("PASS" if rc == 0 else "FAIL", "G10-off' must-accept: the same copy without the option configures",
                 f"returncode {rc}")
            off_build = scratch / "off_build"
        else:
            leg = "G10-win -DSEMB_BUILD_GPU=ON against a CPU-only pin install names SEMB_ENGINE_GPU_MISSING (P:4176)"
            cpu = Path(args.cpu_engine_prefix).resolve() if args.cpu_engine_prefix else None
            if not cpu or not cpu.is_dir():
                emit("MISSING PREREQUISITE", leg, "--cpu-engine-prefix (SEMB_U3_CPU_ENGINE_PREFIX): a pin "
                     "install made without --with-gpu")
            elif (cpu / "share" / "superslm" / "gpu-shaders").is_dir():
                emit("FAIL", leg, f"SETUP: {cpu} ships share/superslm/gpu-shaders, so it is a --with-gpu install, "
                     "not the CPU-only one this leg needs")
            else:
                rc, out = matrix.run_cmake_configure(src, scratch / "on_cpu_pin_build", cpu, {"SEMB_BUILD_GPU": "ON"})
                emit("PASS" if rc != 0 and "SEMB_ENGINE_GPU_MISSING" in out else "FAIL", leg,
                     f"returncode {rc}; {tail(out)}")
            rc, out = matrix.run_cmake_configure(src, scratch / "off_build", matrix.ENGINE_PREFIX)
            off_build = scratch / "off_build"
        if windows and args.gpu_engine_prefix and Path(args.gpu_engine_prefix).is_dir():
            gp = Path(args.gpu_engine_prefix).resolve()
            saved = matrix.ENGINE_PREFIX
            matrix.ENGINE_PREFIX = gp
            rc_on, out_on = matrix.run_cmake_configure(src, scratch / "gpu_on", gp, {"SEMB_BUILD_GPU": "ON"})
            rc_off, out_off = matrix.run_cmake_configure(src, scratch / "gpu_off", gp)
            if rc_on or rc_off:
                emit("FAIL", "R8-accept ON and OFF configure against the --with-gpu install",
                     f"ON {rc_on}: {tail(out_on)}; OFF {rc_off}: {tail(out_off)}")
            else:
                a, b = compile_flags_sha(scratch / "gpu_on", src), compile_flags_sha(scratch / "gpu_off", src)
                emit("PASS" if a == b and a != "unrecorded" else "FAIL",
                     "R8-accept an ON and an OFF configure give equal compileFlags (P:4218)", f"ON {a} / OFF {b}")
            matrix.ENGINE_PREFIX = saved
        else:
            emit("MISSING PREREQUISITE", "R8-accept an ON and an OFF configure give equal compileFlags (P:4218)",
                 "Windows with a --with-gpu pin install (--gpu-engine-prefix): the dev box")
        # R8-rej1: a compile definition on the library target moves compileFlags.
        mut = matrix.copy_repo(scratch / "src_mut")
        with open(mut / "CMakeLists.txt", "a", encoding="utf-8") as f:
            f.write("\n# u3_configure_legs_check R8-rej1 construction\n"
                    "target_compile_definitions(superembedder PRIVATE SEMB_BUILD_GPU=1)\n")
        base_src = matrix.copy_repo(scratch / "src_base")
        rc_b, out_b = matrix.run_cmake_configure(base_src, scratch / "rej1_base", matrix.ENGINE_PREFIX)
        rc_m, out_m = matrix.run_cmake_configure(mut, scratch / "rej1_mut", matrix.ENGINE_PREFIX)
        if rc_b or rc_m:
            emit("FAIL", "R8-rej1 setup", f"base {rc_b}: {tail(out_b)}; mutant {rc_m}: {tail(out_m)}")
        else:
            a = compile_flags_sha(scratch / "rej1_base", base_src)
            b = compile_flags_sha(scratch / "rej1_mut", mut)
            emit("PASS" if a != b and "unrecorded" not in (a, b) else "FAIL",
                 "R8-rej1 must-reject: SEMB_BUILD_GPU as a compile definition on the library target moves "
                 "compileFlags (P:4218)", f"base {a} / mutant {b}")
        del off_build
    finally:
        if not args.scratch:
            matrix.rmtree(scratch)
    return 1 if FAILED else (77 if MISSING_ON_WINDOWS else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
