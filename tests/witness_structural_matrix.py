"""tests/witness_structural_matrix.py -- TE-62/TE-77 (U0 slice B), extended
TE-86 (U0 slice C): C31 (witness integrity, all four structural clauses),
C36's U0 legs (a), (b), (e), and C38 (the witness sees what the product
sees, at the seam the product uses) -- `Claude/Plans/SuperEmbedder_Plan.md`
sec 8 (C31, C36, C38), sec 4.4 ("The structural law, which is the one thing
that can make a witness blind"), sec 4.4d (U0 slice C, the four buildable
constructions TE-85 dispositioned, D-SLM6155-D-SLM6160).

TE-86 (D-SLM6155-D-SLM6160, `Claude/Bach/briefs/te86-u0c-red-suite.md`):
four of the seven `MISSING PREREQUISITE` legs TE-77 left are now REAL,
evaluated constructions -- C31(i), C31(ii), C36(a) (each a genuine
FAIL at this tip, for the reason the leg names, never a silent pass and
never a bare "untested" placeholder) and C31(iv)/C36(e) (green at the tip
by design, both delegated to `tests/witness_no_foreign_reading_check.py`,
which this file imports rather than re-implements -- sec 8's own framing:
one property, two cell names). Only C38's two legs remain `MISSING
PREREQUISITE` -- deferred to a named SuperSLM ticket (D-SLM6158), out of
this slice's scope.

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
    """Runs a built semb_witness and returns its own printed `witness_sha`
    -- the honestly-named field (TE-83, TE-81 review N-5: F-18's own
    deferral -- "outside this seat's writable scope to rename" -- expired
    the moment this file's own writable scope covered it; witness_main.cpp
    has printed BOTH `witness_seam_sha256=` (kept for any external reader
    still parsing it) and the honestly-named `witness_sha=` since TE-78,
    and this reader now parses the latter)."""
    out = subprocess.run([str(exe), "--model", str(model_path), "--tokens", tokens_csv,
                          "--chunk-budget", "0"], capture_output=True, text=True, check=True).stdout
    for tok in out.split():
        if tok.startswith("witness_sha="):
            return tok.split("=", 1)[1]
    raise RuntimeError(f"witness ran but printed no witness_sha: {out!r}")


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
        leg_result(name, "the tip's own semb_witness completes and prints witness_sha",
                  f"witness_sha={digest}", passed)
    except Exception as ex:  # noqa: BLE001
        leg_result(name, "the tip's own semb_witness completes and prints witness_sha",
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
    # into witness_sha, so this construction CAN now be evaluated for
    # real. Once the mutant is built and run successfully, the outcome
    # is a real PASS or FAIL, decided by _c36b_verdict (commissioned
    # separately, before this function is ever called -- see main()).
    #
    # TE-83 (TE-81 review N-1, Significant): the PRIOR version wrapped
    # copy_repo/patch_text/build_witness_in/run_witness in ONE try block
    # and reported ANY exception -- from ANY of them -- as
    # MISSING_PREREQUISITE. That conflated two categorically different
    # conditions: "the scratch build genuinely could not be configured,
    # built or run" (a real inability to attempt the construction) and
    # "patch_text's own anchor text was not found in ps1_pool.cpp" (the
    # MUTATION WAS NEVER APPLIED -- the leg then risked grading an
    # UNMUTATED tree against itself and calling that MISSING rather than
    # the dangerous silent non-event it is). Executed, TE-81's own
    # reproduction: refactoring `constexpr int kExpBias = 127;` to
    # `constexpr int32_t kExpBias = 127;` -- semantically identical, a
    # plausible future edit unrelated to the property under test --
    # defeated the anchor match and the matrix exited 0. `eval_c31_iii`,
    # above, uses the identical patch_text mechanism for its own
    # must-reject and reports ANY exception there (including a failed
    # patch_text) as an evaluated FAIL -- this function now matches it:
    # a failed MUTATION is its own try block, caught separately, and
    # reported as FAIL, never MISSING_PREREQUISITE. Only a genuine
    # configure/build/run failure, in the SECOND try block below, stays
    # MISSING_PREREQUISITE.
    name = "C36(b) our own epilogue edited, superslm.lib standing, must refuse (witness_sha must move)"
    exe = BUILD_DIR / "semb_witness.exe"
    if not exe.exists():
        leg_missing(name, f"{exe} does not exist -- build it first")
        return

    try:
        artifact = ensure_synthetic_artifact()
        tip_digest = run_witness(exe, artifact)
    except Exception as ex:  # noqa: BLE001 -- genuinely could not establish the tip's own baseline
        leg_missing(name, f"could not run the tip's own semb_witness to establish a baseline: {ex}")
        return

    scratch = SCRATCH_ROOT / "c36b_epilogue_edit"
    try:
        copy_repo(scratch)
        patch_text(
            scratch / "src" / "superembedder" / "ps1_pool.cpp",
            "constexpr int kExpBias = 127;",
            "constexpr int kExpBias = 126;",
            "C36(b) epilogue edit",
        )
    except Exception as ex:  # noqa: BLE001 -- the mutation itself was never applied
        leg_result(name, "the edited-epilogue build's own digest differs from the tip's",
                  f"FAIL: the mutation could not be applied to the scratch copy ({ex}) -- a leg "
                  f"that cannot mutate the epilogue cannot prove witness_sha moves with it, and "
                  f"reporting that as a non-failure would silence the only construction in this "
                  f"suite proving sec 4.4b's own structural law for the pooling epilogue "
                  f"(TE-81 review N-1).", False)
        return

    try:
        mutant_exe = build_witness_in(scratch, scratch / "build")
        mutant_artifact = ensure_synthetic_artifact()  # same input artifact, built engine unaffected
        mutant_digest = run_witness(mutant_exe, mutant_artifact)
    except Exception as ex:  # noqa: BLE001 -- genuinely could not attempt the construction
        leg_missing(name, f"could not attempt the construction (scratch configure/build/run "
                          f"failed): {ex}")
        return

    # The construction was attempted for real and produced a real result
    # -- from here, the outcome is PASS or FAIL, never MISSING_PREREQUISITE.
    passed, message = _c36b_verdict(tip_digest, mutant_digest)
    leg_result(name, "the edited-epilogue build's own digest differs from the tip's", message,
              passed)


# ------------------------------------------------------------ TE-86 legs --

def eval_c31_i():
    # TE-86 (D-SLM6155, sec 4.4d item 1): mirrors
    # tools/ci/run_configure_matrix.py's own c34_leg_d_source_added_after_digest()
    # exactly, applied to the semb_witness TARGET instead of the library.
    # MUST-ACCEPT: a normal, freshly configured-and-built semb_witness --
    # already proven by build_witness_in() succeeding below (the current,
    # unaffected behavior). MUST-REJECT: after that green baseline, add a
    # NEW header the witness's own TU includes and rebuild WITHOUT
    # reconfiguring (CMake's own change-tracking does not watch a new file
    # dropped on disk after configure) -- the post-build source-provenance
    # re-verification (cmake/SourceProvenance.cmake's semb_verify_source_provenance(),
    # already proven for C34 on the `superembedder` library target) must
    # fail the rebuild with the drift status. RED AT THE TIP: the
    # `semb_witness` target carries no `semb_verify_source_provenance()`
    # call at all (confirmed: CMakeLists.txt calls it only for
    # `superembedder`) -- so nothing catches the added header and the
    # rebuild silently SUCCEEDS, an evaluated FAIL, never MISSING
    # PREREQUISITE (the construction WAS attempted for real).
    name = "C31(i) second-configure witness must refuse (SEMB_WITNESS_FOREIGN_BUILD) -- post-build provenance drift"
    scratch = SCRATCH_ROOT / "c31i_source_added_after_digest"
    try:
        copy_repo(scratch)
        build_witness_in(scratch, scratch / "build")  # must-accept: green baseline
    except Exception as ex:  # noqa: BLE001
        leg_result(name, "must-accept: a normal build is unaffected; must-reject: the post-build "
                         "re-verification fails with the drift status after an untracked header is "
                         "added and the tree rebuilds without reconfiguring",
                  f"FAIL: could not even establish the green baseline build: {ex}", False)
        return

    new_header = scratch / "include" / "superembedder" / "added_after_witness_digest.h"
    witness_main = scratch / "src" / "witness" / "witness_main.cpp"
    try:
        new_header.write_text("#pragma once\n#define SEMB_ADDED_AFTER_WITNESS_DIGEST 1\n",
                              encoding="utf-8")
        patch_text(
            witness_main,
            '#include "superembedder/witness_abi.h"',
            '#include "superembedder/witness_abi.h"\n#include "superembedder/added_after_witness_digest.h"',
            "C31(i) source-added-after-digest include",
        )
    except Exception as ex:  # noqa: BLE001 -- the mutation itself was never applied
        leg_result(name, "must-accept: a normal build is unaffected; must-reject: the post-build "
                         "re-verification fails with the drift status after an untracked header is "
                         "added and the tree rebuilds without reconfiguring",
                  f"FAIL: the must-reject mutation could not be applied to the scratch copy ({ex})",
                  False)
        return

    cmake = _find_cmake()
    build_proc2 = subprocess.run([cmake, "--build", str(scratch / "build"), "--target", "semb_witness"],
                                 capture_output=True, text=True)
    out = build_proc2.stdout + build_proc2.stderr
    # Mirrors c34_leg_d's own refinement (TE-71 O-2): the literal condition
    # ("agrees": false, the post-build verifier's own drift signal) is
    # distinct from the rc precondition, so a leg that merely observes a
    # nonzero rc for an unrelated reason cannot masquerade as this leg
    # firing correctly.
    found_expected_string = '"agrees": false' in out
    passed = build_proc2.returncode != 0 and found_expected_string
    if passed:
        observed = (f"rebuild correctly FAILED (rc={build_proc2.returncode}) with a drift status "
                    f"after a header was added post-digest and the TU rebuilt without reconfiguring")
    else:
        observed = (f"FAIL (must-reject not met): the rebuild returned rc={build_proc2.returncode} "
                    f"and 'agrees\": false' present={found_expected_string} after a new header was "
                    f"added to the witness's own TU's include closure and the tree rebuilt WITHOUT "
                    f"reconfiguring -- the semb_witness target carries no post-build "
                    f"semb_verify_source_provenance() call at this tip, so nothing catches the "
                    f"drift and the rebuild silently succeeds. Output tail: {out[-800:]}")
    leg_result(name, "must-accept: a normal build is unaffected; must-reject: the post-build "
                     "re-verification fails with the drift status (\"agrees\": false, rc!=0) after "
                     "an untracked header is added and the tree rebuilds without reconfiguring",
               observed, passed)


def eval_c31_ii():
    # TE-86 (D-SLM6155, sec 4.4d item 2). RED AT THE TIP because no accessor
    # `semb_library_build_generation` exists anywhere in this build (grepped,
    # zero hits, and include/superembedder/witness_abi.h -- the header the
    # builder is to add it to -- carries only semb_wa_digest today). This
    # leg's OWN PROBE calls the accessor by the exact signature sec 4.4d
    # gives (`semb_library_build_generation(char out_token[32])`) from a
    # scratch copy of witness_main.cpp -- the probe's compile succeeds (the
    # declaration alone is enough to compile) but its LINK fails, because no
    # translation unit anywhere defines the symbol. That is reported as an
    # evaluated FAIL naming the missing symbol, never MISSING PREREQUISITE
    # -- the construction WAS attempted for real and produced a real,
    # informative failure.
    #
    # FORWARD PATH (unexecuted today, exercised automatically once the
    # accessor exists): if the probe's build unexpectedly SUCCEEDS, this
    # leg falls through to the real must-accept/must-reject construction
    # sec 4.4d specifies, against the UNPATCHED product -- never
    # reimplementing the library's own in-process token comparison inside
    # this test (that comparison is the builder's own new product code,
    # the plan's own words: "the only new product code among the four
    # items"). "Swaps... without reconfiguring" is executed as a targeted
    # rebuild of ONLY the `semb_witness` target after the on-disk .lib is
    # replaced -- for a STATIC library, an already-linked .exe cannot
    # observe a later file-level swap any other way; a relink (no
    # reconfigure) is the only operation that can pull the swapped-in
    # object code into a new .exe, and is still "without reconfiguring" in
    # the sense sec 4.4d's own C34-mirroring language means (no `cmake -S
    # -B`).
    name = "C31(ii) detached-link witness must refuse (SEMB_WITNESS_DETACHED_LINK)"
    probe_scratch = SCRATCH_ROOT / "c31ii_accessor_probe"
    witness_main_decl_anchor = '#include "superembedder/witness_abi.h"\n\nnamespace {'
    try:
        copy_repo(probe_scratch)
        witness_main = probe_scratch / "src" / "witness" / "witness_main.cpp"
        patch_text(
            witness_main, witness_main_decl_anchor,
            '#include "superembedder/witness_abi.h"\n\n'
            'extern "C" void semb_library_build_generation(char out_token[32]);\n\nnamespace {',
            "C31(ii) accessor probe declaration",
        )
        patch_text(
            witness_main, "int main(int argc, char** argv) {",
            "int main(int argc, char** argv) {\n"
            "  // TE-86 C31(ii) MUST-attempt probe: referencing the not-yet-existing accessor by "
            "sec 4.4d's own signature -- this call alone is enough to force a link-time reference.\n"
            "  char _semb_test_build_gen[32] = {0};\n"
            "  semb_library_build_generation(_semb_test_build_gen);",
            "C31(ii) accessor probe call",
        )
    except Exception as ex:  # noqa: BLE001 -- the probe mutation itself was never applied
        leg_result(name, "must-accept: the unswapped build computes witness_sha as today; "
                         "must-reject: SEMB_WITNESS_DETACHED_LINK before any digest",
                  f"FAIL: the accessor probe's own mutation could not be applied to the scratch "
                  f"copy: {ex}", False)
        return

    try:
        build_witness_in(probe_scratch, probe_scratch / "build")
    except RuntimeError as ex:
        msg = str(ex)
        if "semb_library_build_generation" in msg:
            leg_result(name, "must-accept: the unswapped build computes witness_sha as today; "
                             "must-reject: SEMB_WITNESS_DETACHED_LINK before any digest",
                      f"FAIL: no accessor `semb_library_build_generation` exists yet -- this leg's "
                      f"own probe (declaring the accessor by sec 4.4d's exact signature and calling "
                      f"it from a scratch copy of witness_main.cpp) compiled but failed to LINK, "
                      f"naming the missing symbol. Linker output tail: {msg[-800:]}", False)
        else:
            leg_result(name, "must-accept: the unswapped build computes witness_sha as today; "
                             "must-reject: SEMB_WITNESS_DETACHED_LINK before any digest",
                      f"FAIL: the accessor probe failed to build for a reason OTHER than the "
                      f"missing symbol -- this leg cannot distinguish 'no accessor yet' from an "
                      f"unrelated build break: {msg[-800:]}", False)
        return

    # The accessor now exists (future state, unexecuted at this tip): run
    # the real construction against the UNPATCHED product.
    try:
        g1 = SCRATCH_ROOT / "c31ii_g1"
        g2 = SCRATCH_ROOT / "c31ii_g2"
        copy_repo(g1)
        copy_repo(g2)
        g1_exe = build_witness_in(g1, g1 / "build")  # separate configure -> its own token, G1
        build_witness_in(g2, g2 / "build")  # separate configure -> its own token, G2
        artifact = ensure_synthetic_artifact()

        accept_digest = run_witness(g1_exe, artifact)  # must-accept: unswapped, computes as today

        g1_lib = g1 / "build" / "superembedder.lib"
        g2_lib = g2 / "build" / "superembedder.lib"
        if not g1_lib.exists() or not g2_lib.exists():
            raise RuntimeError(f"expected static lib not found: g1={g1_lib.exists()} g2={g2_lib.exists()}")
        shutil.copy2(g2_lib, g1_lib)  # swap, no reconfigure

        cmake = _find_cmake()
        relink = subprocess.run([cmake, "--build", str(g1 / "build"), "--target", "semb_witness"],
                                capture_output=True, text=True)
        run_proc = subprocess.run([str(g1_exe), "--model", str(artifact), "--tokens", "3,17,42,5,90",
                                   "--chunk-budget", "0"], capture_output=True, text=True)
        out = relink.stdout + relink.stderr + run_proc.stdout + run_proc.stderr
        rejected = "SEMB_WITNESS_DETACHED_LINK" in out and run_proc.returncode != 0
        passed = rejected and len(accept_digest) == 64
        leg_result(name, "must-accept: the unswapped build computes witness_sha as today; "
                         "must-reject: SEMB_WITNESS_DETACHED_LINK before any digest",
                  f"must-accept digest={accept_digest}; must-reject swap+relink+run rc="
                  f"{run_proc.returncode}, SEMB_WITNESS_DETACHED_LINK present={rejected}; "
                  f"output tail: {out[-800:]}", passed)
    except Exception as ex:  # noqa: BLE001
        leg_result(name, "must-accept: the unswapped build computes witness_sha as today; "
                         "must-reject: SEMB_WITNESS_DETACHED_LINK before any digest",
                  f"FAIL: the accessor now links, but the real G1/G2 swap construction could not "
                  f"be completed: {ex}", False)


def eval_c31_iv_and_c36_e(cell_label: str):
    # TE-86 (D-SLM6156, sec 4.4d item 3, sec 8's own framing: C31(iv) and
    # C36(e) name the SAME absence -- one property, two cell names).
    # Delegated to tests/witness_no_foreign_reading_check.py's own
    # run_construction(), never re-implemented here. GREEN AT THE TIP BY
    # DESIGN: the property already holds (witness_main.cpp has no
    # foreign-reading code path, confirmed by reading and now by a check
    # that can fail) -- both its constructions fire now.
    name = f"{cell_label} foreign-process reading must refuse -- structural check, not a runtime status"
    try:
        from witness_no_foreign_reading_check import run_construction
    except ImportError as ex:  # noqa: BLE001
        leg_result(name, "witness_no_foreign_reading_check.run_construction() returns (True, ...)",
                  f"FAIL: could not import tests/witness_no_foreign_reading_check.py: {ex}", False)
        return
    passed, message = run_construction()
    leg_result(name, "MUST-ACCEPT: the tip's own witness_main.cpp has zero foreign-reading hits; "
                     "MUST-REJECT: a scratch copy with one inserted getenv(...) line is flagged",
               message, passed)


def _find_engine_perturbation_script() -> Optional[Path]:
    """C36(a) (D-SLM6157, sec 4.4d item 4): the promoted script's own name
    is TBD by the builder (the plan's own illustrative example:
    tools/engine_side_wa_perturbation.py) -- discovered by CONTENT rather
    than a hardcoded filename, so this check does not false-negative
    against whatever name the builder actually picks. A script under
    tools/ qualifies when its own source names BOTH of D-SLM6075's
    identifying markers: the perturbed site (EmbedEntry in
    forward_sites.cpp)."""
    tools_dir = REPO_ROOT / "tools"
    if not tools_dir.exists():
        return None
    for p in sorted(tools_dir.rglob("*.py")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "EmbedEntry" in text and "forward_sites.cpp" in text:
            return p
    return None


def eval_c36_a():
    # TE-86 (D-SLM6157, sec 4.4d item 4): "your cell is the check that the
    # script exists under tools/, runs its recipe against a scratch clone
    # (never D:\SuperSLM), and reports witness_sha moved." RED AT THE TIP:
    # the script does not exist yet (grepped -- no tools/*.py mentions
    # EmbedEntry + forward_sites.cpp).
    #
    # CONTRACT THIS LEG REQUIRES OF THE SCRIPT (stated here because sec
    # 4.4d leaves the script's own CLI/output undefined beyond its
    # internal recipe -- this is the minimal, documented interface this
    # check needs to grade it as a real oracle rather than by static
    # reading alone; stated again in this seat's own handoff packet):
    # invoked as `python <script> --scratch-root <dir>`, the script must
    # (1) perform its whole clone/perturb/build/compare recipe entirely
    # under <dir> (this check independently greps the script's own source
    # to confirm it never references D:\SuperSLM as a clone target --
    # literal-path safety, not merely trusting --scratch-root is honored),
    # and (2) print a final stdout line matching `^witness_sha_moved:
    # (true|false)$`.
    name = "C36(a) engine arithmetic change confined to a non-inline .cpp must refuse -- promoted script"
    script = _find_engine_perturbation_script()
    if script is None:
        leg_result(name, "a script under tools/ exists, runs D-SLM6075's own recipe against a "
                         "SCRATCH clone (never D:\\SuperSLM), and reports witness_sha_moved: true",
                  "FAIL: no script under tools/ matches D-SLM6075's own recipe markers (EmbedEntry "
                  "+ forward_sites.cpp) -- none exists yet", False)
        return

    script_text = script.read_text(encoding="utf-8", errors="ignore")
    if "D:\\SuperSLM" in script_text or "D:/SuperSLM" in script_text:
        leg_result(name, "the script never references D:\\SuperSLM as a clone target",
                  f"FAIL: {script} literally references D:\\SuperSLM -- this leg refuses to run a "
                  f"script that could target the real engine checkout in place", False)
        return

    scratch_root = SCRATCH_ROOT / "c36a_engine_perturbation"
    rmtree(scratch_root)
    scratch_root.mkdir(parents=True)
    proc = subprocess.run([sys.executable, str(script), "--scratch-root", str(scratch_root)],
                          capture_output=True, text=True, cwd=str(REPO_ROOT))
    out = proc.stdout + proc.stderr
    moved = "witness_sha_moved: true" in out
    passed = proc.returncode == 0 and moved
    leg_result(name, "a script under tools/ exists, runs D-SLM6075's own recipe against a SCRATCH "
                     "clone (never D:\\SuperSLM), and reports witness_sha_moved: true",
               f"rc={proc.returncode}; witness_sha_moved: true present={moved}; output tail: "
               f"{out[-800:]}", passed)


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

    eval_c31_i()
    eval_c31_ii()
    eval_c31_iii()
    eval_c31_iv_and_c36_e("C31(iv)")
    eval_c31_v()
    eval_c36_a()
    if not _selftest_c36b_verdict_can_fail():
        print("witness_structural_matrix: C36(b)'s own decision function failed its "
              "commissioning -- refusing to run the real (expensive) construction against an "
              "unproven decision.", file=sys.stderr)
        sys.exit(1)
    eval_c36_b()
    eval_c31_iv_and_c36_e("C36(e)")
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
