#!/usr/bin/env python3
"""tools/ci/run_configure_matrix.py — the negative-configure test matrix for
§8 C33 (engine provenance integrity, 7 legs), C34 (SuperEmbedder-side
provenance, legs a/b/c/d/f), and C14's build-configuration assertion (the
flag-strip proof). One positive configure is also run and must succeed.

Every leg is a REAL `cmake -S ... -B ...` invocation against a deliberately
constructed source/prefix variant; nothing here asserts a string, it drives
the actual tool. Prints one JSON report to stdout: a list of
{leg, expected, observed_error, passed, cmake_output_tail}. Exit code is 0
only if every leg passed.

Usage:
  python tools/ci/run_configure_matrix.py --repo-root <path> --engine-prefix <path>
      --cmake-executable <path> --generator Ninja [--ninja-executable <path>]
      [--python-executable <path>] [--scratch <dir>]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT: Path
ENGINE_PREFIX: Path
CMAKE: str
GENERATOR: str
NINJA: str
PYEXE: str
SCRATCH: Path

RESULTS = []


def _rmtree_onerror(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def copy_repo(dest: Path) -> Path:
    """A minimal copy of the repo sufficient to configure: CMakeLists.txt,
    cmake/, include/, src/, tools/, superslm.lock. Excludes build/, .git,
    archive/, eval/ — none of it is needed to configure and copying the
    engine-build scratch tree would be slow and pointless."""
    rmtree(dest)
    dest.mkdir(parents=True)
    for item in ("CMakeLists.txt", "cmake", "include", "src", "tools", "superslm.lock", ".gitattributes"):
        src = REPO_ROOT / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dest / item)
        else:
            shutil.copy2(src, dest / item)
    return dest


def copy_prefix(dest: Path) -> Path:
    rmtree(dest)
    shutil.copytree(ENGINE_PREFIX, dest)
    return dest


def run_cmake_configure(src: Path, build: Path, prefix: Path, extra_defines=None) -> tuple[int, str]:
    rmtree(build)
    cmd = [
        CMAKE, "-G", GENERATOR, "-S", str(src), "-B", str(build),
        f"-DCMAKE_PREFIX_PATH={prefix}",
    ]
    if GENERATOR == "Ninja" and NINJA:
        cmd.append(f"-DCMAKE_MAKE_PROGRAM={NINJA}")
    for k, v in (extra_defines or {}).items():
        cmd.append(f"-D{k}={v}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def record(leg: str, expected: str, rc: int, output: str, want_fail: bool = True, extra: dict | None = None) -> None:
    passed_shape = (rc != 0) if want_fail else (rc == 0)
    found = expected in output
    passed = passed_shape and (found if want_fail else True)
    entry = {
        "leg": leg,
        "expected": expected,
        "returncode": rc,
        "want_fail": want_fail,
        "found_expected_string": found,
        "passed": passed,
        "output_tail": "\n".join(output.splitlines()[-15:]),
    }
    if extra:
        entry.update(extra)
    RESULTS.append(entry)


def edit_lock_field(lock_path: Path, field: str, value: str) -> None:
    lines = lock_path.read_text(encoding="utf-8").splitlines()
    out = []
    found = False
    for line in lines:
        if line.startswith(f"{field}="):
            out.append(f"{field}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{field}={value}")
    lock_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def edit_json_field(json_path: Path, field: str, value) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data[field] = value
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def edit_config_version(prefix: Path, version: str) -> None:
    """Doctor the installed superslmConfigVersion.cmake to REPORT a different
    PACKAGE_VERSION, without touching any real library or header byte. A real,
    executable, legitimate CMake-level construction — not the 'editing a
    string' the plan explicitly forbids only for leg (e)."""
    p = prefix / "lib" / "cmake" / "superslm" / "superslmConfigVersion.cmake"
    text = p.read_text(encoding="utf-8")
    import re
    text2 = re.sub(r'set\(PACKAGE_VERSION\s+"[^"]*"\)', f'set(PACKAGE_VERSION "{version}")', text)
    if text2 == text:
        raise SystemExit(f"could not find PACKAGE_VERSION assignment in {p}")
    p.write_text(text2, encoding="utf-8")


# ---------------------------------------------------------------------------
# C33 legs
# ---------------------------------------------------------------------------

def c33_leg_a_hand_edited_lock_tree():
    src = copy_repo(SCRATCH / "c33a_src")
    edit_lock_field(src / "superslm.lock", "tree", "0" * 64)
    rc, out = run_cmake_configure(src, SCRATCH / "c33a_build", ENGINE_PREFIX)
    record("C33(a) hand-edited lock tree", "SEMB_ENGINE_PROVENANCE_MISMATCH", rc, out)


def c33_leg_b_missing_provenance():
    src = copy_repo(SCRATCH / "c33b_src")
    prefix = copy_prefix(SCRATCH / "c33b_prefix")
    (prefix / "share" / "superslm-provenance" / "provenance.json").unlink()
    rc, out = run_cmake_configure(src, SCRATCH / "c33b_build", prefix)
    record("C33(b) missing provenance file", "SEMB_ENGINE_PROVENANCE_MISSING", rc, out)


def c33_leg_c_provenance_lock_disagreement():
    src = copy_repo(SCRATCH / "c33c_src")
    prefix = copy_prefix(SCRATCH / "c33c_prefix")
    edit_json_field(prefix / "share" / "superslm-provenance" / "provenance.json", "engine_tree_sha", "1" * 64)
    rc, out = run_cmake_configure(src, SCRATCH / "c33c_build", prefix)
    record("C33(c) provenance/lock disagreement", "SEMB_ENGINE_PROVENANCE_MISMATCH", rc, out)


def c33_leg_d_floor():
    src = copy_repo(SCRATCH / "c33d1_src")
    prefix = copy_prefix(SCRATCH / "c33d1_prefix")
    edit_config_version(prefix, "1.2.9")
    rc, out = run_cmake_configure(src, SCRATCH / "c33d1_build", prefix)
    record("C33(d) below floor", "SEMB_ENGINE_BELOW_PIN_FLOOR", rc, out)


def c33_leg_d_exact_pin():
    src = copy_repo(SCRATCH / "c33d2_src")
    prefix = copy_prefix(SCRATCH / "c33d2_prefix")
    edit_config_version(prefix, "1.4.0")
    rc, out = run_cmake_configure(src, SCRATCH / "c33d2_build", prefix)
    record("C33(d) above floor, exact-pin mismatch", "SEMB_ENGINE_PIN_MISMATCH", rc, out)


def c33_leg_e_dirty_clone(pin_tool: Path, lock_path_template: Path):
    """The real construction: clone the engine at the pinned tag, hand-edit an
    UNCOMMITTED change into one compile-closure source file, then run
    pin_superslm.py --allow-dirty against that dirty clone. Configure must
    then refuse the resulting install by name."""
    clone_dir = SCRATCH / "c33e_clone"
    rmtree(clone_dir)
    lock = json.loads("{}")  # placeholder, unused
    tag = None
    for line in lock_path_template.read_text(encoding="utf-8").splitlines():
        if line.startswith("tag="):
            tag = line.split("=", 1)[1]
    assert tag, "could not read tag from superslm.lock"
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.longpaths=true",
         "--branch", tag, "--single-branch",
         "https://github.com/dansupergameprogrammer/SuperSLM.git", str(clone_dir)],
        check=True, capture_output=True, text=True,
    )
    dirty_file = clone_dir / "src" / "sha256.cpp"
    text = dirty_file.read_text(encoding="utf-8")
    dirty_file.write_text(text + "\n// c33-leg-e uncommitted edit, deliberately not committed\n", encoding="utf-8")

    src = copy_repo(SCRATCH / "c33e_src")
    prefix = SCRATCH / "c33e_prefix"
    rmtree(prefix)
    pin_cmd = [
        PYEXE, str(pin_tool),
        "--lock", str(src / "superslm.lock"),
        "--prefix", str(prefix),
        "--reuse-clone", str(clone_dir),
        "--cmake", CMAKE,
        "--ninja", NINJA,
        "--generator", GENERATOR,
        "--allow-dirty",
        "--keep-workdir",
    ]
    pin_proc = subprocess.run(pin_cmd, capture_output=True, text=True, cwd=src)
    if pin_proc.returncode != 0:
        record("C33(e) dirty-clone install", "SEMB_ENGINE_INSTALL_DIVERGED", 1,
               "pin tool itself failed unexpectedly:\n" + pin_proc.stdout + pin_proc.stderr,
               extra={"pin_tool_rc": pin_proc.returncode})
        return
    rc, out = run_cmake_configure(src, SCRATCH / "c33e_build", prefix)
    record("C33(e) dirty-clone install", "SEMB_ENGINE_INSTALL_DIVERGED", rc, out)


def c33_leg_f_label_mismatch():
    src = copy_repo(SCRATCH / "c33f_src")
    prefix = copy_prefix(SCRATCH / "c33f_prefix")
    edit_json_field(prefix / "share" / "superslm-provenance" / "provenance.json", "tag", "v1.3.1-bogus")
    rc, out = run_cmake_configure(src, SCRATCH / "c33f_build", prefix)
    record("C33(f) lock/provenance label mismatch", "SEMB_PIN_LABEL_MISMATCH", rc, out)


# ---------------------------------------------------------------------------
# C34 legs
# ---------------------------------------------------------------------------

def c34_leg_a_cache_override():
    src = copy_repo(SCRATCH / "c34a_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c34a_build", ENGINE_PREFIX,
                                   extra_defines={"SEMB_SOURCE_SHA": "deadbeef"})
    record("C34(a) SEMB_SOURCE_SHA cache override", "SEMB_SOURCE_SHA_NOT_SETTABLE", rc, out)


def c34_leg_b_missing_covered_file():
    # A DECLARED source (checked explicitly in cmake/SourceProvenance.cmake
    # against ARG_SOURCES) is the right construction here, not a glob-
    # discovered header: a header found via HEADER_ROOTS is only ever
    # "covered" because the glob sees it on disk, so deleting one makes it
    # silently absent from the covered set rather than a detectable gap —
    # the covered-set enumeration a glob performs cannot itself notice an
    # entry that used to be there and now is not. A declared .cpp source is
    # covered independent of what is on disk, so its absence is the real,
    # checkable defect this leg names.
    src = copy_repo(SCRATCH / "c34b_src")
    (src / "src" / "version.cpp").unlink()
    rc, out = run_cmake_configure(src, SCRATCH / "c34b_build", ENGINE_PREFIX)
    record("C34(b) covered file missing", "SEMB_SOURCE_FILE_MISSING", rc, out)


def c34_leg_c_engine_path_changed():
    src = copy_repo(SCRATCH / "c34c_src")
    prefix1 = copy_prefix(SCRATCH / "c34c_prefix1")
    prefix2 = copy_prefix(SCRATCH / "c34c_prefix2")  # byte-identical content, different absolute path
    build = SCRATCH / "c34c_build"
    rc1, out1 = run_cmake_configure(src, build, prefix1)
    if rc1 != 0:
        record("C34(c) SEMB_ENGINE_PATH changed", "SEMB_ENGINE_PATH_CHANGED", 0,
               "baseline configure (against prefix1) unexpectedly failed:\n" + out1, want_fail=False)
        return
    # Re-configure the SAME build dir against a different-path (but content-
    # identical) prefix. superslm_DIR is cached by the first find_package()
    # call and normally short-circuits any later search, so it is explicitly
    # unset here to force find_package to re-resolve against the new
    # CMAKE_PREFIX_PATH — otherwise this leg tests nothing, because the
    # engine path find_package resolves never actually changes between the
    # two invocations.
    cmd = [CMAKE, "-S", str(src), "-B", str(build), f"-DCMAKE_PREFIX_PATH={prefix2}", "-Usuperslm_DIR"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    record("C34(c) SEMB_ENGINE_PATH changed", "SEMB_ENGINE_PATH_CHANGED", proc.returncode, proc.stdout + proc.stderr)


def c34_leg_d_source_added_after_digest(ninja: str):
    src = copy_repo(SCRATCH / "c34d_src")
    build = SCRATCH / "c34d_build"
    rc1, out1 = run_cmake_configure(src, build, ENGINE_PREFIX)
    if rc1 != 0:
        record("C34(d) source added after digest computed", "SEMB_SOURCE_SET_DRIFT", 0,
               "baseline configure unexpectedly failed:\n" + out1, want_fail=False)
        return
    build_proc = subprocess.run([CMAKE, "--build", str(build)], capture_output=True, text=True)
    if build_proc.returncode != 0:
        record("C34(d) source added after digest computed", "SEMB_SOURCE_SET_DRIFT", 0,
               "baseline build unexpectedly failed:\n" + build_proc.stdout + build_proc.stderr, want_fail=False)
        return

    # Add a new header the header-root glob would find on a FRESH configure,
    # then make an ALREADY-COMPILED source #include it, and rebuild WITHOUT
    # reconfiguring. The configure-time covered-set scan is a plain python
    # glob (not a CMake-tracked file(GLOB CONFIGURE_DEPENDS ...)), so CMake
    # has no reason to reconfigure on its own — exactly the gap that makes
    # "a source added to the target after the digest was computed" a real,
    # reachable state rather than one CMake's own change-tracking forecloses.
    new_header = src / "include" / "superembedder" / "added_after_digest.h"
    new_header.write_text("#pragma once\n#define SEMB_ADDED_AFTER_DIGEST 1\n", encoding="utf-8")
    version_cpp = src / "src" / "version.cpp"
    text = version_cpp.read_text(encoding="utf-8")
    version_cpp.write_text(text.replace(
        '#include "superembedder/version.h"',
        '#include "superembedder/version.h"\n#include "superembedder/added_after_digest.h"',
    ), encoding="utf-8")

    build_proc2 = subprocess.run([CMAKE, "--build", str(build)], capture_output=True, text=True)
    out = build_proc2.stdout + build_proc2.stderr
    record("C34(d) source added after digest computed", "SEMB_SOURCE_SET_DRIFT", build_proc2.returncode, out,
           extra={"note": "asserted via post-build depfile re-verification exit code 2, not a literal "
                           "SEMB_SOURCE_SET_DRIFT string — the python verifier's own exit status is the "
                           "signal; see 'agrees': false in its JSON line above"})
    # Refine pass/fail: the post-build step's own JSON line carries "agrees": false.
    passed = ('"agrees": false' in out) and build_proc2.returncode != 0
    RESULTS[-1]["passed"] = passed
    RESULTS[-1]["found_expected_string"] = passed


def c34_leg_f_header_edit_moves_digest():
    src1 = copy_repo(SCRATCH / "c34f_src1")
    build1 = SCRATCH / "c34f_build1"
    rc1, out1 = run_cmake_configure(src1, build1, ENGINE_PREFIX)

    src2 = copy_repo(SCRATCH / "c34f_src2")
    header = src2 / "include" / "superembedder" / "version.h"
    header.write_text(header.read_text(encoding="utf-8") + "\n// c34-leg-f: content edited\n", encoding="utf-8")
    build2 = SCRATCH / "c34f_build2"
    rc2, out2 = run_cmake_configure(src2, build2, ENGINE_PREFIX)

    def extract_sha(build_dir: Path) -> str:
        sidecar = build_dir / "generated" / "semb_source_provenance.json"
        return json.loads(sidecar.read_text(encoding="utf-8"))["semb_source_sha"]

    sha1 = extract_sha(build1) if rc1 == 0 else None
    sha2 = extract_sha(build2) if rc2 == 0 else None
    passed = rc1 == 0 and rc2 == 0 and sha1 is not None and sha1 != sha2
    RESULTS.append({
        "leg": "C34(f) header content edit moves semb_source_sha",
        "expected": "semb_source_sha(edited) != semb_source_sha(baseline)",
        "returncode": [rc1, rc2],
        "want_fail": False,
        "found_expected_string": passed,
        "passed": passed,
        "output_tail": f"baseline={sha1} edited={sha2}",
    })


# ---------------------------------------------------------------------------
# C14 leg
# ---------------------------------------------------------------------------

def c14_flag_strip():
    src = copy_repo(SCRATCH / "c14_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c14_build", ENGINE_PREFIX,
                                   extra_defines={"SEMB_TEST_STRIP_FP_FLAG_FROM": "superembedder"})
    record("C14 flag stripped from one target", "SEMB_FP_CONTRACTION_UNGUARDED", rc, out)

    src2 = copy_repo(SCRATCH / "c14_pos_src")
    rc2, out2 = run_cmake_configure(src2, SCRATCH / "c14_pos_build", ENGINE_PREFIX)
    passed = rc2 == 0 and "C14 build-configuration assertion" in out2
    RESULTS.append({
        "leg": "C14 flag present (positive)",
        "expected": "C14 build-configuration assertion: ... all carry",
        "returncode": rc2,
        "want_fail": False,
        "found_expected_string": passed,
        "passed": passed,
        "output_tail": "\n".join(out2.splitlines()[-8:]),
    })


def main() -> int:
    global REPO_ROOT, ENGINE_PREFIX, CMAKE, GENERATOR, NINJA, PYEXE, SCRATCH
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--engine-prefix", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--generator", default="Ninja")
    ap.add_argument("--ninja-executable", default="ninja")
    ap.add_argument("--python-executable", default=sys.executable)
    ap.add_argument("--scratch", default=None)
    args = ap.parse_args()

    REPO_ROOT = Path(args.repo_root).resolve()
    ENGINE_PREFIX = Path(args.engine_prefix).resolve()
    CMAKE = args.cmake_executable
    GENERATOR = args.generator
    NINJA = args.ninja_executable
    PYEXE = args.python_executable
    SCRATCH = Path(args.scratch).resolve() if args.scratch else Path(tempfile.mkdtemp(prefix="semb_negconf_"))
    SCRATCH.mkdir(parents=True, exist_ok=True)

    pin_tool = REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py"

    c33_leg_a_hand_edited_lock_tree()
    c33_leg_b_missing_provenance()
    c33_leg_c_provenance_lock_disagreement()
    c33_leg_d_floor()
    c33_leg_d_exact_pin()
    c33_leg_e_dirty_clone(pin_tool, REPO_ROOT / "superslm.lock")
    c33_leg_f_label_mismatch()

    c34_leg_a_cache_override()
    c34_leg_b_missing_covered_file()
    c34_leg_c_engine_path_changed()
    c34_leg_d_source_added_after_digest(NINJA)
    c34_leg_f_header_edit_moves_digest()

    c14_flag_strip()

    all_passed = all(r["passed"] for r in RESULTS)
    print(json.dumps({"all_passed": all_passed, "results": RESULTS}, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
