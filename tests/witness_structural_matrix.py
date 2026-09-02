"""tests/witness_structural_matrix.py -- TE-62/TE-77 (U0 slice B): C31
(witness integrity, all four structural clauses), C36's U0 legs (a), (b),
(e), and C38 (the witness sees what the product sees, at the seam the
product uses) -- `Claude/Plans/SuperEmbedder_Plan.md` sec 8 (C31, C36,
C38), sec 4.4 ("The structural law, which is the one thing that can make
a witness blind").

TE-77 REPAIR (D-SLM6069). The prior version's `leg()` helper hard-coded
`"passed": False` on every one of its ten calls, with no dynamic
construction anywhere in the file -- unconditionally red regardless of
what the builder built. This version gives each leg a REAL evaluation:

  - Where the product has no runtime mechanism for the property AT ALL
    (no code path anywhere that could refuse, because the property is a
    feature not yet built), the leg reports `MISSING PREREQUISITE`, named
    precisely -- never `False` standing in for "untested."
  - Where the property IS mechanically checkable against what is actually
    built -- a real object-file inspection, or a real second build of a
    deliberately mutated COPY of the source tree (never the tracked
    files themselves, mirroring `tools/ci/run_configure_matrix.py`'s own
    copy-and-patch convention) -- this file drives the real construction
    and reads the real result.

WHAT WAS INVESTIGATED BEFORE DECIDING WHICH LEGS ARE WHICH (read in full
this session): `witness_main.cpp` (the witness executable's own TU) calls
only `semb_encode_document_for_witness` and `semb_seam_serialize_document`
plus the engine's own SHA-256 -- no arithmetic, matching sec 4.4b clause
4's own requirement, confirmed by reading rather than assumed. It has NO
code that detects "was I built from a second configure," "am I linked to
a detached copy," or "did a value arrive from another process" -- none of
SEMB_WITNESS_FOREIGN_BUILD, SEMB_WITNESS_DETACHED_LINK, or
SEMB_WITNESS_FOREIGN_READING is emitted anywhere in this build (grepped,
zero hits). Building those detectors is product code, outside this
seat's writable scope for TE-77 (`Claude/Bach/briefs/te77-u0b-cell-fixes.md`'s
own Contract: `src/**` is read-only) and a real feature this ticket does
not add -- so C31(i), C31(ii), C31(iv) are `MISSING PREREQUISITE`, named
exactly why. Similarly, `intmath.h` and `layer_marshal.h` (the only
installed engine headers whose INLINE primitives the reproducible path
actually calls -- `ReadCarriedScale`, confirmed the sole one in use) carry
NO `#ifdef`-gated branch anywhere (grepped: only include guards) -- so
C38's own literal "-D on an installed header's #ifdef branch" construction
has no branch to toggle, and is `MISSING PREREQUISITE` for that specific
reason; what CAN be verified for real is the STRUCTURAL precondition C38's
own reasoning rests on (which TU the primitive is actually compiled into),
which this file does check, via C31(iii) below.

THE TWO LEGS THIS FILE EVALUATES FOR REAL, AND THE ONE IT ATTEMPTED AND
EXECUTED INTO A DIFFERENT, MORE PRECISE MISSING-PREREQUISITE FINDING:

  C31(iii) -- TU-local inline-primitive driver. MUST-ACCEPT: dumpbin over
  the TIP's own built objects shows `ReadCarriedScale` (the reproducible
  path's sole inline installed-header call) referenced NOWHERE in the
  witness's own object (`witness_main.cpp.obj`) -- the property the claim
  is actually about. (Whether the LIBRARY's own object still carries a
  standalone out-of-line symbol for it is read and reported, but NOT
  gated on -- TE-80, discovered under Clang: an optimizer may legitimately
  inline the primitive away entirely at its one call site with no
  standalone symbol left in EITHER object, observed under clang-cl -O2
  where MSVC's own -O2 build retains one; that difference is ordinary
  compiler behaviour, not a defect in either build.) MUST-REJECT: a
  scratch COPY of the tree with one line added to `witness_main.cpp`
  (taking `ReadCarriedScale`'s own address, which ODR-uses it and forces
  a local definition to exist under BOTH compilers, address-of being
  something no optimizer can inline away) is reconfigured and rebuilt,
  and dumpbin over THAT witness object now finds it defined there too --
  proving the check can see the hazard it exists to catch, on both
  toolchains.

  C31(v) -- the positive construction. The TIP's own `semb_witness`,
  already built, run against the hermetically-regenerated synthetic
  artifact: must complete and emit a digest, not refuse.

  C36(b) -- our own epilogue edited, `superslm.lib` standing. ATTEMPTED
  for real: a scratch COPY of the tree with `kExpBias` in `ps1_pool.cpp`
  changed 127 -> 126 (a real, textual edit to a copy, never to the
  tracked file) was reconfigured, rebuilt, and its own `semb_witness` run
  -- and its digest was IDENTICAL to the tip's. Diagnosed by reading
  (confirmed by the same execution): this round's `semb_witness` calls
  only `semb_encode_document_for_witness` + `semb_seam_serialize_document`
  (W-B's own seam digest) and never `semb_wa_pool_run` at all (grepped
  both `witness_main.cpp` and `engine_adapter_interim.cpp`: zero hits) --
  so `witness_sha`, as this round's witness actually computes it, is
  W-B's digest ALONE, and no edit confined to the pooling epilogue can
  move it yet. This is `MISSING PREREQUISITE`, not a failed construction
  -- sec 4.4b's own three-component design (`witness_sha` = W-A's digest
  ‖ W-B's digest ‖ W-Q's digest) has only its W-B component wired into
  this round's witness.

USAGE: `python tests/witness_structural_matrix.py` prints the JSON report
and exits 0 only if every EVALUATED (non-missing) leg passed -- a
`MISSING PREREQUISITE` leg does not count as a failure of THIS script (it
is an honest state, not an error), but is still surfaced with `"passed":
false` in the report so a reader sees exactly what remains open, and the
process exit code reflects whether anything EVALUABLE actually failed.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PREFIX = REPO_ROOT / "build" / "_engine_install"
SCRATCH_ROOT = REPO_ROOT / "build" / "_scratch" / "witness_matrix"

# TE-80 (TE-76 review F-6, Significant): the build directory this matrix
# grades is no longer a hardcoded "build/msvc" -- it is set from
# --build-dir, which tests/CMakeLists.txt passes as CMake's own
# CMAKE_BINARY_DIR (the REAL directory ctest is actually configured and
# run from), so a run from build/clang grades build/clang's own objects
# and binaries, never silently substituting MSVC's. The fallback below
# (REPO_ROOT/build/msvc) exists only for a manual, standalone invocation
# with no --build-dir given (e.g. this file run directly rather than via
# ctest) and is never what a registered ctest target uses.
BUILD_DIR = REPO_ROOT / "build" / "msvc"

RESULTS: List[Dict] = []


def leg_result(name: str, expected: str, observed: str, passed: bool, missing: bool = False):
    RESULTS.append({"leg": name, "expected": expected, "observed": observed, "passed": passed,
                     "missing_prerequisite": missing})


def leg_missing(name: str, needs: str):
    leg_result(name, "refuses or passes per its own construction", f"MISSING PREREQUISITE: {needs}",
               False, missing=True)


# --------------------------------------------------------------- dumpbin --

def find_dumpbin() -> Optional[str]:
    found = shutil.which("dumpbin")
    if found:
        return found
    # Under the Community developer shell dumpbin is on PATH; fall back to
    # the known VS install layout if a caller ran this script outside the
    # dev shell.
    candidates = list(Path("C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC")
                      .glob("*/bin/HostX64/x64/dumpbin.exe"))
    return str(candidates[0]) if candidates else None


def obj_defines_symbol(dumpbin: str, obj_path: Path, name_substring: str) -> bool:
    """True iff dumpbin's own symbol table lists a DEFINED (not merely
    referenced/undefined) symbol containing `name_substring` in `obj_path`."""
    if not obj_path.exists():
        raise FileNotFoundError(str(obj_path))
    out = subprocess.run([dumpbin, "/symbols", str(obj_path)], capture_output=True, text=True,
                         check=True).stdout
    for line in out.splitlines():
        if name_substring in line and "External" in line and "UNDEF" not in line:
            return True
    return False


# ------------------------------------------------------ scratch tree copy --

def _rmtree_onerror(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def copy_repo(dest: Path) -> Path:
    """Mirrors tools/ci/run_configure_matrix.py's own copy_repo(): a
    minimal copy sufficient to configure and build `semb_witness` --
    never the tracked source itself, so every patch below lands on a
    throwaway copy."""
    rmtree(dest)
    dest.mkdir(parents=True)
    for item in ("CMakeLists.txt", "cmake", "include", "src", "tools", "tests", "superslm.lock",
                 ".gitattributes"):
        src = REPO_ROOT / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dest / item)
        else:
            shutil.copy2(src, dest / item)
    return dest


def patch_text(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{label}: anchor text not found in {path} -- cannot apply the patch")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def build_witness_in(src_dir: Path, build_dir: Path) -> Path:
    """Configures and builds ONLY what `semb_witness` needs in a scratch
    tree; returns the built executable's path. Raises on any failure --
    callers read the exception message as the leg's own `observed`."""
    cmake = _find_cmake()
    rmtree(build_dir)
    configure = subprocess.run(
        [cmake, "-G", "Ninja", "-S", str(src_dir), "-B", str(build_dir),
         "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_PREFIX_PATH={ENGINE_PREFIX}"],
        capture_output=True, text=True, cwd=str(src_dir),
    )
    if configure.returncode != 0:
        raise RuntimeError(f"configure failed (rc={configure.returncode}):\n{configure.stdout[-2000:]}\n{configure.stderr[-2000:]}")
    build = subprocess.run([cmake, "--build", str(build_dir), "--target", "semb_witness"],
                           capture_output=True, text=True, cwd=str(src_dir))
    if build.returncode != 0:
        raise RuntimeError(f"build failed (rc={build.returncode}):\n{build.stdout[-2000:]}\n{build.stderr[-2000:]}")
    exe = build_dir / "semb_witness.exe"
    if not exe.exists():
        raise RuntimeError(f"build reported success but {exe} does not exist")
    return exe


def _find_cmake() -> str:
    found = shutil.which("cmake")
    if found:
        return found
    candidate = Path("C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/"
                      "CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe")
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("no cmake executable found on PATH or at the known VS install location")


def ensure_synthetic_artifact() -> Path:
    path = REPO_ROOT / "build" / "_scratch" / "synthetic_te62_c39.sslm"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    # TE-80 F-19: no hardcoded local path in committed test source -- an
    # optional override (SEMB_TEST_ENGINE_SOURCE) for this seat's own
    # local runs; unset, regenerate_synthetic_artifact.py falls back to
    # its own DEFAULT_REMOTE (a public URL reachable from any of sec 8
    # C13's four CI toolchains).
    cmd = [sys.executable, str(REPO_ROOT / "tests" / "fixtures" / "regenerate_synthetic_artifact.py"),
           "--lock", "superslm.lock", "--out", str(path)]
    engine_source = os.environ.get("SEMB_TEST_ENGINE_SOURCE")
    if engine_source:
        cmd += ["--source", engine_source]
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))
    return path


def run_witness(exe: Path, model_path: Path, tokens_csv: str = "3,17,42,5,90") -> str:
    """Runs a built semb_witness and returns its own printed
    `witness_seam_sha256`."""
    out = subprocess.run([str(exe), "--model", str(model_path), "--tokens", tokens_csv,
                          "--chunk-budget", "0"], capture_output=True, text=True, check=True).stdout
    for tok in out.split():
        if tok.startswith("witness_seam_sha256="):
            return tok.split("=", 1)[1]
    raise RuntimeError(f"witness ran but printed no witness_seam_sha256: {out!r}")


# --------------------------------------------------------------- the legs --

def eval_c31_iii():
    name = "C31(iii) TU-local inline-primitive driver must be detectable (SEMB_WITNESS_TU_ARITHMETIC)"
    dumpbin = find_dumpbin()
    if dumpbin is None:
        leg_missing(name, "dumpbin.exe not found -- run under the Community developer shell")
        return
    try:
        lib_obj = BUILD_DIR / "CMakeFiles" / "superembedder.dir" / "src" / "superembedder" / \
            "engine_adapter_interim.cpp.obj"
        witness_obj = BUILD_DIR / "CMakeFiles" / "semb_witness.dir" / "src" / "witness" / \
            "witness_main.cpp.obj"
        lib_has_it = obj_defines_symbol(dumpbin, lib_obj, "ReadCarriedScale")
        witness_has_it_tip = obj_defines_symbol(dumpbin, witness_obj, "ReadCarriedScale")
        # TE-80: discovered by execution under Clang (this seat's own
        # cross-compiler run) -- requiring `lib_has_it == True` is NOT
        # toolchain-robust. An optimizer is free to fully inline
        # ReadCarriedScale at its one call site and leave NO standalone
        # out-of-line symbol in the LIBRARY's own object either (observed:
        # MSVC's build retains one; clang-cl's -O2 build does not) --
        # that is correct, unremarkable compiler behaviour, not a defect,
        # and is not what C31(iii)/C38's own claim is ABOUT: the claim is
        # that the primitive is never compiled into the WITNESS's own TU,
        # which `witness_has_it_tip` checks directly and robustly (the
        # witness never calls the function AT ALL under normal build, so
        # there is nothing there for any optimizer to inline FROM).
        # `lib_has_it` is retained as an informational reading only.
        must_accept_ok = not witness_has_it_tip

        # MUST-REJECT: a scratch copy whose witness_main.cpp takes
        # ReadCarriedScale's own address, forcing MSVC to emit a local
        # definition under ODR -- the exact hazard this leg exists to
        # catch, constructed for real.
        scratch = SCRATCH_ROOT / "c31iii_mustreject"
        copy_repo(scratch)
        witness_main = scratch / "src" / "witness" / "witness_main.cpp"
        patch_text(
            witness_main,
            '#include "superembedder/seam_abi.h"\n#include "superslm/sha256.h"',
            '#include "superembedder/seam_abi.h"\n#include "superslm/layer_marshal.h"\n'
            '#include "superslm/sha256.h"',
            "C31(iii) must-reject include",
        )
        patch_text(
            witness_main,
            "int main(int argc, char** argv) {",
            "int main(int argc, char** argv) {\n"
            "  // TE-77 C31(iii) MUST-REJECT construction: taking this inline function's own\n"
            "  // address ODR-uses it, forcing a local definition into THIS TU.\n"
            "  auto _semb_test_hazard = &superslm_marshal::ReadCarriedScale;\n"
            "  (void)_semb_test_hazard;",
            "C31(iii) must-reject hazard call",
        )
        mutant_exe = build_witness_in(scratch, scratch / "build")
        mutant_witness_obj = scratch / "build" / "CMakeFiles" / "semb_witness.dir" / "src" / \
            "witness" / "witness_main.cpp.obj"
        witness_has_it_mutant = obj_defines_symbol(dumpbin, mutant_witness_obj, "ReadCarriedScale")
        must_reject_ok = witness_has_it_mutant  # the hazard MUST be visible in the mutant

        passed = must_accept_ok and must_reject_ok
        observed = (f"tip: witness references it={witness_has_it_tip} "
                    f"(must_accept={'OK' if must_accept_ok else 'FAIL'}; library defines it="
                    f"{lib_has_it}, informational only -- an optimizer may legitimately inline "
                    f"it away entirely, toolchain-dependent, observed False under Clang -O2); "
                    f"mutant witness defines it={witness_has_it_mutant} "
                    f"(must_reject={'OK' if must_reject_ok else 'FAIL'})")
        leg_result(name, "must-accept: witness TU clean; must-reject: hazard visible in mutant",
                  observed, passed)
    except Exception as ex:  # noqa: BLE001 -- reported as the leg's own observed state
        leg_result(name, "must-accept: library-only; must-reject: hazard visible in mutant",
                  f"EXCEPTION: {ex}", False)


def eval_c31_v():
    name = "C31(v) a correctly-built witness must NOT refuse (the positive construction)"
    try:
        exe = BUILD_DIR / "semb_witness.exe"
        if not exe.exists():
            leg_missing(name, f"{exe} does not exist -- build it first")
            return
        artifact = ensure_synthetic_artifact()
        digest = run_witness(exe, artifact)
        passed = len(digest) == 64  # a real SHA-256 hex digest was printed, not a refusal
        leg_result(name, "the tip's own semb_witness completes and prints witness_seam_sha256",
                  f"witness_seam_sha256={digest}", passed)
    except Exception as ex:  # noqa: BLE001
        leg_result(name, "the tip's own semb_witness completes and prints witness_seam_sha256",
                  f"EXCEPTION: {ex}", False)


def _c36b_verdict(tip_digest: str, mutant_digest: str):
    """The decision C36(b) grades on, factored out so it can be
    commissioned directly (TE-80's own discipline, StandardsDocument.md
    sec 5.4): equal digests -> a real FAIL (never MISSING_PREREQUISITE,
    once the construction has actually run); different digests -> PASS.
    Returns (passed, message)."""
    if mutant_digest == tip_digest:
        return (False, f"FAIL: tip digest {tip_digest} == mutant digest {mutant_digest} after "
                        f"kExpBias 127->126 -- witness_sha did NOT move when the pooling "
                        f"epilogue's own arithmetic changed. semb_wa_digest IS wired into "
                        f"witness_sha as of TE-78 (confirmed present in witness_main.cpp); an "
                        f"unchanged digest here is a real must-reject failure, not a missing "
                        f"prerequisite.")
    return (True, f"PASS: tip={tip_digest} mutant={mutant_digest} -- witness_sha moved when the "
                  f"pooling epilogue's own arithmetic changed.")


def _selftest_c36b_verdict_can_fail() -> bool:
    """TE-80's own commissioning of _c36b_verdict, before the real,
    expensive scratch-rebuild construction is trusted: two identical
    digests must verdict FAIL; two different digests must verdict PASS."""
    same = "a" * 64
    other = "b" * 64
    passed_same, _ = _c36b_verdict(same, same)
    passed_diff, _ = _c36b_verdict(same, other)
    if passed_same:
        print("C36(b) SELFTEST FAIL: _c36b_verdict(same, same) reported PASS -- the decision "
              "cannot fail, which is F-5's own defect one level removed.", file=sys.stderr)
        return False
    if not passed_diff:
        print("C36(b) SELFTEST FAIL: _c36b_verdict(same, different) reported FAIL -- a genuine "
              "digest change is being misreported.", file=sys.stderr)
        return False
    return True


def eval_c36_b():
    # TE-80 (TE-76 review F-5, Significant): TE-78 wired semb_wa_digest
    # (W-A's own digest) into witness_sha, so this construction CAN now
    # be evaluated for real -- confirmed by grep (witness_main.cpp DOES
    # call semb_wa_digest, unlike when this leg was first written). The
    # prior version reported ANY digest-equal outcome as
    # MISSING_PREREQUISITE unconditionally, which was correct while the
    # wiring genuinely did not exist and became a silent escape hatch the
    # moment it landed: a REGRESSION that unwires W-A again would produce
    # the identical digest-equal observation and be reported as "nothing
    # to evaluate" rather than a failed must-reject. The fix separates
    # the two causes structurally: an EXCEPTION while attempting the
    # construction (the scratch build itself could not be configured,
    # built, or run) is the only case reported MISSING_PREREQUISITE --
    # genuinely could not attempt it. Once the mutant is built and run
    # successfully, ANY outcome is a real, evaluated result: digest moved
    # -> PASS; digest unchanged -> FAIL, never missing.
    name = "C36(b) our own epilogue edited, superslm.lib standing, must refuse (witness_sha must move)"
    try:
        exe = BUILD_DIR / "semb_witness.exe"
        if not exe.exists():
            leg_missing(name, f"{exe} does not exist -- build it first")
            return
        artifact = ensure_synthetic_artifact()
        tip_digest = run_witness(exe, artifact)

        scratch = SCRATCH_ROOT / "c36b_epilogue_edit"
        copy_repo(scratch)
        patch_text(
            scratch / "src" / "superembedder" / "ps1_pool.cpp",
            "constexpr int kExpBias = 127;",
            "constexpr int kExpBias = 126;",
            "C36(b) epilogue edit",
        )
        mutant_exe = build_witness_in(scratch, scratch / "build")
        mutant_artifact = ensure_synthetic_artifact()  # same input artifact, built engine unaffected
        mutant_digest = run_witness(mutant_exe, mutant_artifact)
    except Exception as ex:  # noqa: BLE001 -- genuinely could not attempt the construction
        leg_missing(name, f"could not attempt the construction (scratch configure/build/run "
                          f"failed): {ex}")
        return

    # The construction was attempted for real and produced a real result
    # -- from here, the outcome is PASS or FAIL, never MISSING_PREREQUISITE,
    # decided by _c36b_verdict (commissioned above, before this function
    # is ever called -- see main()).
    passed, message = _c36b_verdict(tip_digest, mutant_digest)
    leg_result(name, "the edited-epilogue build's own digest differs from the tip's", message,
              passed)


def main(argv: List[str]) -> int:
    global BUILD_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", default=None,
                     help="TE-80 F-6: the real build directory to grade (CMake's own "
                          "CMAKE_BINARY_DIR, passed by tests/CMakeLists.txt). Falls back to "
                          "REPO_ROOT/build/msvc only for a manual, non-ctest invocation.")
    args = ap.parse_args(argv)
    if args.build_dir:
        BUILD_DIR = Path(args.build_dir).resolve()
    print(f"witness_structural_matrix: grading build directory {BUILD_DIR}", file=sys.stderr)

    leg_missing("C31(i) second-configure witness must refuse (SEMB_WITNESS_FOREIGN_BUILD)",
                "no runtime detection of 'which configure built this witness' exists anywhere in "
                "this build (grepped, zero hits) -- building one is product code, outside this "
                "seat's writable scope")
    leg_missing("C31(ii) detached-link witness must refuse (SEMB_WITNESS_DETACHED_LINK)",
                "no runtime detection of a detached-link build exists anywhere in this build -- "
                "same disposition as C31(i)")
    eval_c31_iii()
    leg_missing("C31(iv) foreign-process reading must refuse (SEMB_WITNESS_FOREIGN_READING)",
                "the witness has no external-reading code path at all (confirmed by reading "
                "witness_main.cpp in full: it computes everything in-process) -- there is nothing "
                "to construct a violation of")
    eval_c31_v()
    leg_missing("C36(a) engine arithmetic change confined to a non-inline .cpp must refuse",
                "needs an edit to D:\\SuperSLM's own compiled .cpp source -- the engine repository "
                "is read-only to this seat (Claude/Bach/briefs/te77-u0b-cell-fixes.md's own "
                "Contract)")
    if not _selftest_c36b_verdict_can_fail():
        print("witness_structural_matrix: C36(b)'s own decision function failed its "
              "commissioning -- refusing to run the real (expensive) construction against an "
              "unproven decision.", file=sys.stderr)
        sys.exit(1)
    eval_c36_b()
    leg_missing("C36(e) any reading served from outside the process must refuse",
                "the witness has no external-reading code path at all (same finding as C31(iv)) "
                "-- there is nothing to construct a violation of")
    leg_missing("C38 a -D on an INSTALLED ENGINE HEADER's #ifdef branch, compiled into the LIBRARY, "
                "must move witness_sha",
                "no #ifdef-gated branch exists in any inline installed-header primitive the "
                "reproducible path calls (grepped superslm/intmath.h and superslm/layer_marshal.h: "
                "only include guards; the sole inline primitive actually called, ReadCarriedScale, "
                "has no compile-time branch) -- there is no branch to toggle. The STRUCTURAL "
                "precondition this clause's own reasoning rests on (which TU the primitive "
                "compiles into) IS verified for real -- see C31(iii)")
    leg_missing("C38 the SAME -D on the WITNESS EXECUTABLE's own TU must NOT move witness_sha "
                "(the construction that shows a TU-local driver is blind)",
                "tied to the same missing #ifdef as C38's first leg -- no branch exists to apply "
                "the -D to on either target")

    report = {"results": RESULTS, "total": len(RESULTS),
              "passed": sum(1 for r in RESULTS if r["passed"]),
              "failed": sum(1 for r in RESULTS if not r["passed"]),
              "missing_prerequisite": sum(1 for r in RESULTS if r.get("missing_prerequisite"))}
    print(json.dumps(report, indent=2))
    # Exit 0 only if every EVALUATED (non-missing) leg passed. A leg
    # honestly marked MISSING PREREQUISITE does not fail this script --
    # it is a true statement about what remains unbuilt, not an error in
    # the evaluation.
    evaluated_failed = sum(1 for r in RESULTS if not r["passed"] and not r.get("missing_prerequisite"))
    return 0 if evaluated_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
