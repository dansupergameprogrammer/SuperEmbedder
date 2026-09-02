#!/usr/bin/env python3
"""tools/ci/run_configure_matrix.py — the negative-configure test matrix for
§8 C33 (engine provenance integrity), C34 (SuperEmbedder-side provenance,
legs a/b/c/d/f), and C14's build-configuration assertion (multiple legs,
each one construction the assertion must catch). One positive configure is
also run and must succeed.

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
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pin-superslm"))
from pin_superslm import DEFAULT_REMOTE  # noqa: E402 — TE-65 F-17: one constant, not two

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


_COMPILER_ID_CACHE = {}


def detect_compiler_id() -> str:
    """TE-67 N-7: two C14 legs used to hardcode MSVC-specific flag syntax
    and used GENERATOR == "Ninja" as a stand-in for "the compiler is MSVC"
    -- wrong on a matrix this project's own CI runs with the Ninja
    generator on all three OSes, where the REAL compiler on ubuntu/macos is
    GCC/Clang. Reads CMAKE_CXX_COMPILER_ID from a fresh, throwaway probe
    configure's own CMakeFiles/<version>/CMakeCXXCompiler.cmake (not a
    CMakeCache.txt entry -- found by execution when a first read attempt
    came back empty). Cached for the process's lifetime.

    TE-69 (found during this round's own Clang verification, not one of
    the casebook's numbered findings): the prior version read
    REPO_ROOT/build/semb/CMakeCache.txt FIRST, a persistent directory nine
    of this file's OWN developer/CI conventions leave behind from a PRIOR
    run -- if that prior run used a different compiler than the one the
    CURRENT invocation's CXX/CC environment selects (exactly what happens
    switching between an MSVC verification and a Clang one in the same
    working tree without deleting build/semb first), this function reported
    the WRONG compiler while the actual configure used the right one,
    silently mislabeling every leg and, for legs that choose a flag
    spelling from this function's answer, silently choosing the wrong
    flag. There is no directory this function can trust without configuring
    it itself: it always runs its own fresh probe now, which respects
    whatever CXX/CC/CMAKE_CXX_COMPILER the CURRENT process environment
    specifies, the same way every other leg's real configure does."""
    if "id" in _COMPILER_ID_CACHE:
        return _COMPILER_ID_CACHE["id"]

    def _scan_for_id(build_dir: Path) -> str | None:
        # CMAKE_CXX_COMPILER_ID is not a CMakeCache.txt entry -- CMake
        # records it in CMakeFiles/<version>/CMakeCXXCompiler.cmake as a
        # plain set() call (found by execution: CMakeCache.txt has no such
        # key at all).
        for f in build_dir.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"):
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r'\s*set\(CMAKE_CXX_COMPILER_ID\s+"([^"]+)"\)', line)
                if m:
                    return m.group(1)
        return None

    probe_src = SCRATCH / "_compiler_id_probe_src"
    probe_build = SCRATCH / "_compiler_id_probe_build"
    probe_src.mkdir(parents=True, exist_ok=True)
    (probe_src / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.21)\nproject(probe LANGUAGES CXX)\n", encoding="utf-8",
    )
    probe_rc, probe_out = run_cmake_configure(probe_src, probe_build, ENGINE_PREFIX)
    found = _scan_for_id(probe_build)
    if found is None:
        # TE-69 P-8: this used to raise with neither the probe's exit code
        # nor its output -- and this function is first called mid-matrix,
        # after every C33/C34 leg (including two real engine clones and
        # builds), so an unhandled raise here discarded the whole RESULTS
        # report: main()'s json.dumps() never ran and ctest got a traceback
        # instead of a leg table. The message now carries both.
        raise RuntimeError(
            f"could not detect CMAKE_CXX_COMPILER_ID from the probe configure "
            f"(exit {probe_rc}); no CMakeCXXCompiler.cmake with a recognizable "
            f"CMAKE_CXX_COMPILER_ID line was found under {probe_build}. Probe output:\n{probe_out}"
        )
    _COMPILER_ID_CACHE["id"] = found
    return found



def run_cmake_configure(src: Path, build: Path, prefix: Path, extra_defines=None, extra_env=None) -> tuple[int, str]:
    rmtree(build)
    cmd = [
        CMAKE, "-G", GENERATOR, "-S", str(src), "-B", str(build),
        f"-DCMAKE_PREFIX_PATH={prefix}",
    ]
    if GENERATOR == "Ninja" and NINJA:
        cmd.append(f"-DCMAKE_MAKE_PROGRAM={NINJA}")
    for k, v in (extra_defines or {}).items():
        cmd.append(f"-D{k}={v}")
    env = None
    if extra_env:
        env = dict(os.environ)
        env.update(extra_env)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
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


def record_infra_failure(leg: str, expected: str, rc: int, reason: str, output: str) -> None:
    """TE-65 F-6: a leg's OWN baseline setup (a configure or build that is
    supposed to succeed before the real construction is applied) failing is
    not a pass under any reading -- the leg never reached its construction,
    so nothing about `expected` was exercised. The prior code called
    record(..., rc=0, want_fail=False) here, which hardcoded a fabricated
    zero return code regardless of the real (nonzero) one, so
    passed_shape = (0 == 0) was always true and the leg silently read as
    green. This records the REAL rc and an explicit, unconditional
    passed=False, distinguishable in the report from both a normal pass and
    a normal (want_fail) refusal."""
    RESULTS.append({
        "leg": leg,
        "expected": expected,
        "returncode": rc,
        "want_fail": None,
        "found_expected_string": False,
        "passed": False,
        "infra_failure": reason,
        "output_tail": "\n".join(output.splitlines()[-15:]),
    })


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
         DEFAULT_REMOTE, str(clone_dir)],
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
        # TE-67 N-10: the third infra-failure-shaped early return F-6 missed
        # -- fabricated rc=1 regardless of the pin tool's real exit code,
        # and used record()'s default want_fail=True instead of
        # record_infra_failure(). It happened to read red only because
        # want_fail=True ALSO requires the expected string to appear, which
        # a genuine pin-tool failure's own error text is unlikely to
        # contain by coincidence -- the shape F-6 named (a baseline failure
        # is not a pass) was intact here, just not yet triggered by luck.
        record_infra_failure("C33(e) dirty-clone install", "SEMB_ENGINE_INSTALL_DIVERGED",
                              pin_proc.returncode, "pin tool itself failed unexpectedly",
                              pin_proc.stdout + pin_proc.stderr)
        return
    rc, out = run_cmake_configure(src, SCRATCH / "c33e_build", prefix)
    record("C33(e) dirty-clone install", "SEMB_ENGINE_INSTALL_DIVERGED", rc, out)


def c33_leg_e2_added_file_no_edit(pin_tool: Path, lock_path_template: Path):
    """TE-67 N-1 (Critical), corrected for TE-69 P-2. The reviewer's second,
    edit-free construction: a clone carrying an UNTRACKED file inside the
    compile closure. git_clean_check() records no tag_content_sha256 for a
    path the tag has no content for; the fix under test is that a
    null/missing tag_content_sha256 is itself a refusal, not a skip.

    TE-69 P-2: to get newhdr.h into the REAL compile closure at all, an
    EXISTING tracked file (src/sha256.cpp) must be edited to #include it --
    there is no way to add a file to what the compiler actually reads
    without something referencing it. That edit trips the PRE-EXISTING
    mismatch path (src/sha256.cpp's own tag_content_sha256 no longer
    matches its on-disk bytes) all by itself, so a leg that only asserts
    "configure refused, naming SEMB_ENGINE_INSTALL_DIVERGED" cannot tell
    the added-file mechanism apart from the already-fixed modified-file one
    -- reverting N-1's fix and re-running this leg still refuses (through
    sha256.cpp's own mismatch), and the leg read green. The prior
    docstring's isolation claim was checked only against git_clean_check()
    called STANDALONE on a two-member closure, never against what
    verify_provenance.py -- the actual decision path -- reports for the
    REAL install this leg builds.

    The fix: call verify_provenance.py directly against the prefix
    pin_superslm.py actually wrote, and require newhdr.h SPECIFICALLY in
    its own dirty_members list -- the identity of what was caught, not
    merely that something was. This is what discriminates "the added-file
    mechanism fired" from "some other, already-covered mechanism fired
    coincidentally"."""
    clone_dir = SCRATCH / "c33e2_clone"
    rmtree(clone_dir)
    tag = None
    for line in lock_path_template.read_text(encoding="utf-8").splitlines():
        if line.startswith("tag="):
            tag = line.split("=", 1)[1]
    assert tag, "could not read tag from superslm.lock"
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.longpaths=true",
         "--branch", tag, "--single-branch",
         DEFAULT_REMOTE, str(clone_dir)],
        check=True, capture_output=True, text=True,
    )
    (clone_dir / "newhdr.h").write_text("#pragma once\n#define SEMB_N1_LEG_MARKER 1\n", encoding="utf-8")
    (clone_dir / "src" / "sha256.cpp").write_text(
        '#include "../newhdr.h"\n' + (clone_dir / "src" / "sha256.cpp").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # This edit ALSO makes src/sha256.cpp itself mismatch its tag content --
    # by construction (see docstring), not something this leg can avoid.
    # git_clean_check() run standalone on the isolated two-member closure
    # confirms newhdr.h carries no tag content (it does not exist at the
    # tag); it does NOT establish that verify_provenance.py's own
    # dirty_members will name newhdr.h specifically once sha256.cpp's own
    # edit is also present in the real closure -- that is what the
    # post-pin check below establishes instead.
    sys.path.insert(0, str(pin_tool.parent))
    import importlib
    if "pin_superslm" in sys.modules:
        importlib.reload(sys.modules["pin_superslm"])
    import pin_superslm as _pin_mod
    isolated_closure = {(clone_dir / "src" / "sha256.cpp").resolve(), (clone_dir / "newhdr.h").resolve()}
    _clean, _dirty, _tag_sha = _pin_mod.git_clean_check(clone_dir, tag, isolated_closure)
    assert "newhdr.h" not in _tag_sha, "isolation check failed: newhdr.h unexpectedly has tag content"

    src = copy_repo(SCRATCH / "c33e2_src")
    prefix = SCRATCH / "c33e2_prefix"
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
        record_infra_failure("C33(e2) added-file no-edit install", "SEMB_ENGINE_INSTALL_DIVERGED",
                              pin_proc.returncode, "pin tool itself failed unexpectedly",
                              pin_proc.stdout + pin_proc.stderr)
        return

    # TE-69 P-2's own fix: verify_provenance.py, called directly against the
    # real prefix the tool just wrote -- the actual decision path
    # cmake/EngineGuards.cmake invokes -- must name newhdr.h in its OWN
    # dirty_members. This is what a reverted N-1 fix cannot satisfy even
    # though configure still refuses (see docstring): the reverted code
    # reads `clean`/`dirty_paths` (a different, coarser field) or nothing
    # at all for newhdr.h specifically, so it does not appear here.
    verify_script = pin_tool.parent / "verify_provenance.py"
    verify_proc = subprocess.run([PYEXE, str(verify_script), str(prefix)], capture_output=True, text=True)
    try:
        verify_result = json.loads(verify_proc.stdout)
    except json.JSONDecodeError:
        verify_result = {}
    newhdr_named = "newhdr.h" in verify_result.get("dirty_members", [])

    rc, out = run_cmake_configure(src, SCRATCH / "c33e2_build", prefix)
    expected = "SEMB_ENGINE_INSTALL_DIVERGED"
    configure_refused_by_name = rc != 0 and expected in out
    passed = newhdr_named and configure_refused_by_name
    RESULTS.append({
        "leg": "C33(e2) added-file no-edit install",
        "expected": expected,
        "returncode": rc,
        "want_fail": True,
        "found_expected_string": configure_refused_by_name,
        "passed": passed,
        "output_tail": "\n".join(out.splitlines()[-15:])
                        + f"\nverify_provenance dirty_members={verify_result.get('dirty_members')}"
                        + f" newhdr_named={newhdr_named}",
    })


def c33_leg_e3_deleted_manifest_field(pin_tool: Path, lock_path_template: Path):
    """TE-67 N-1 (Critical). The hand-edit half: delete the tag_content_sha256
    key from one compiled member's manifest entry (not merely null it) and
    confirm the deep check still refuses -- a missing key must be read the
    same as a null value, not skipped."""
    src = copy_repo(SCRATCH / "c33e3_src")
    prefix = copy_prefix(SCRATCH / "c33e3_prefix")
    prov_path = prefix / "share" / "superslm-provenance" / "provenance.json"
    data = json.loads(prov_path.read_text(encoding="utf-8"))
    compiled = [m for m in data["members_index"] if m["root"] == "compiled"]
    assert compiled, "no compiled members in provenance.json to attack"
    target = compiled[0]
    assert "tag_content_sha256" in target, "fixture prefix predates TE-67 N-1's field"
    del target["tag_content_sha256"]
    prov_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rc, out = run_cmake_configure(src, SCRATCH / "c33e3_build", prefix)
    record("C33(e3) deleted manifest field", "SEMB_ENGINE_INSTALL_DIVERGED", rc, out)


def c33_leg_g_unowned_workdir_refused(pin_tool: Path, lock_path_template: Path):
    """TE-69 P-3, a permanent leg for N-11's own (pre-clone) construction --
    distinct from P-4's leg (e2/e3's --reuse-clone path never creates
    workdir/src at all). Here workdir/src pre-exists with a file the tool
    did not create and carries no ".git" marker; clone_engine() must refuse
    to wipe it (SEMB_PIN_UNSAFE_WORKDIR) before it ever calls `git clone`,
    and the caller's file must still be there afterward. No network access:
    the refusal fires at clone_engine()'s own first check, before the `git
    clone` subprocess is built."""
    workdir = SCRATCH / "c33g_workdir"
    rmtree(workdir)
    (workdir / "src").mkdir(parents=True)
    keepme = workdir / "src" / "keepme.txt"
    keepme.write_text("N-11: not this tool's own clone\n", encoding="utf-8")

    lock = SCRATCH / "c33g_lock" / "superslm.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(lock_path_template.read_text(encoding="utf-8"), encoding="utf-8")
    prefix = SCRATCH / "c33g_prefix"
    rmtree(prefix)

    pin_cmd = [
        PYEXE, str(pin_tool),
        "--lock", str(lock),
        "--prefix", str(prefix),
        "--workdir", str(workdir),
        "--cmake", CMAKE,
        "--ninja", NINJA,
        "--generator", GENERATOR,
    ]
    pin_proc = subprocess.run(pin_cmd, capture_output=True, text=True)
    out = pin_proc.stdout + pin_proc.stderr
    survived = keepme.exists() and keepme.read_text(encoding="utf-8").startswith("N-11")
    passed = pin_proc.returncode != 0 and "SEMB_PIN_UNSAFE_WORKDIR" in out and survived
    RESULTS.append({
        "leg": "C33(g) unowned --workdir/src refused before clone (N-11)",
        "expected": "SEMB_PIN_UNSAFE_WORKDIR",
        "returncode": pin_proc.returncode,
        "want_fail": True,
        "found_expected_string": "SEMB_PIN_UNSAFE_WORKDIR" in out,
        "passed": passed,
        "output_tail": "\n".join(out.splitlines()[-10:]) + f"\nkeepme_survived={survived}",
    })


def c33_leg_f_label_mismatch():
    src = copy_repo(SCRATCH / "c33f_src")
    prefix = copy_prefix(SCRATCH / "c33f_prefix")
    edit_json_field(prefix / "share" / "superslm-provenance" / "provenance.json", "tag", "v1.3.1-bogus")
    rc, out = run_cmake_configure(src, SCRATCH / "c33f_build", prefix)
    record("C33(f) lock/provenance label mismatch", "SEMB_PIN_LABEL_MISMATCH", rc, out)


def c33_leg_h_final_cleanup_preserves_user_files(pin_tool: Path, lock_path_template: Path):
    """TE-71 Q-1 (Critical). The final-cleanup rmtree site -- distinct from
    C33(g)'s pre-clone guard (N-11's own site; this one is the site P-4
    touched and Q-1 found broken). A real --reuse-clone run against a
    --workdir that ALREADY holds a file this tool did not create, sitting
    directly in workdir (not under workdir/build or workdir/src) -- the
    exact shape a person pointing --workdir at a directory of their own
    would produce. The tool must delete only what it made this run
    (workdir/build; workdir/src is never created on the --reuse-clone path
    at all) and leave the caller's file and workdir itself standing.
    Requires a real engine clone+configure+build+install, like C33(e)."""
    clone_dir = SCRATCH / "c33h_clone"
    rmtree(clone_dir)
    tag = None
    for line in lock_path_template.read_text(encoding="utf-8").splitlines():
        if line.startswith("tag="):
            tag = line.split("=", 1)[1]
    assert tag, "could not read tag from superslm.lock"
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.longpaths=true",
         "--branch", tag, "--single-branch",
         DEFAULT_REMOTE, str(clone_dir)],
        check=True, capture_output=True, text=True,
    )

    workdir = SCRATCH / "c33h_workdir"
    rmtree(workdir)
    workdir.mkdir(parents=True)
    keepme = workdir / "keepme.txt"
    keepme.write_text("Q-1: not this tool's own build output\n", encoding="utf-8")

    lock = SCRATCH / "c33h_lock" / "superslm.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(lock_path_template.read_text(encoding="utf-8"), encoding="utf-8")
    prefix = SCRATCH / "c33h_prefix"
    rmtree(prefix)

    pin_cmd = [
        PYEXE, str(pin_tool),
        "--lock", str(lock),
        "--prefix", str(prefix),
        "--workdir", str(workdir),
        "--reuse-clone", str(clone_dir),
        "--cmake", CMAKE,
        "--ninja", NINJA,
        "--generator", GENERATOR,
    ]
    pin_proc = subprocess.run(pin_cmd, capture_output=True, text=True)
    out = pin_proc.stdout + pin_proc.stderr
    keepme_survived = keepme.exists() and keepme.read_text(encoding="utf-8").startswith("Q-1")
    workdir_survived = workdir.exists()
    build_removed = not (workdir / "build").exists()
    src_never_touched = not (workdir / "src").exists()
    passed = (pin_proc.returncode == 0 and keepme_survived and workdir_survived
              and build_removed and src_never_touched)
    RESULTS.append({
        "leg": "C33(h) final cleanup preserves a caller's own --workdir file (Q-1)",
        "expected": "exit 0, caller's file and workdir survive, only workdir/build removed",
        "returncode": pin_proc.returncode,
        "want_fail": False,
        "found_expected_string": keepme_survived and workdir_survived and build_removed and src_never_touched,
        "passed": passed,
        "output_tail": "\n".join(out.splitlines()[-10:])
                        + f"\nkeepme_survived={keepme_survived} workdir_survived={workdir_survived}"
                          f" build_removed={build_removed} src_never_touched={src_never_touched}",
    })


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
        record_infra_failure("C34(c) SEMB_ENGINE_PATH changed", "SEMB_ENGINE_PATH_CHANGED", rc1,
                              "baseline configure (against prefix1) unexpectedly failed", out1)
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
        record_infra_failure("C34(d) source added after digest computed", "SEMB_SOURCE_SET_DRIFT", rc1,
                              "baseline configure unexpectedly failed", out1)
        return
    build_proc = subprocess.run([CMAKE, "--build", str(build)], capture_output=True, text=True)
    if build_proc.returncode != 0:
        record_infra_failure("C34(d) source added after digest computed", "SEMB_SOURCE_SET_DRIFT",
                              build_proc.returncode, "baseline build unexpectedly failed",
                              build_proc.stdout + build_proc.stderr)
        return

    # Add a new header a FRESH configure's preprocessor pass would resolve,
    # then make an ALREADY-COMPILED source #include it, and rebuild WITHOUT
    # reconfiguring. The configure-time covered-set computation runs a
    # python subprocess (execute_process), which CMake's own change-tracking
    # does not watch the way it watches CMakeLists.txt or a
    # file(GLOB CONFIGURE_DEPENDS ...) result, so CMake has no reason to
    # reconfigure on its own — exactly the gap that makes "a source added
    # to the target after the digest was computed" a real, reachable state
    # rather than one CMake's own change-tracking forecloses.
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


def c34_leg_g_preprocess_failure_raises():
    """TE-69 P-3, a permanent leg for N-5. A second library source whose
    only #include is reachable through CMAKE_BINARY_DIR/generated -- an
    include directory the real target has (via the generated header) but
    the provenance call is not given, matching what src/main.cpp needs but
    src/version.cpp's own SOURCES declaration does not cover. The compiler
    resolves one real header (superembedder/version.h) before failing to
    resolve the second, reproducing the reviewer's own "some output, then a
    fatal error" shape rather than an immediate failure.

    TE-71 Q-3: N-5's own repair is inside _msvc_closure only --
    _gcc_clang_closure has raised on any nonzero preprocessor exit since
    37bef58 (TE-65 F-1), unrelated to N-5, and _resolve_closure dispatches
    to _msvc_closure only when compiler_id == "MSVC". Reverting N-5's own
    condition therefore has no effect on this leg under GCC/Clang -- it was
    never exercising N-5 there, and was silently green on two of three CI
    runners regardless of whether N-5's own fix existed.

    This leg is honestly two pins, one per governing mechanism, not one:
    under MSVC it discriminates N-5's own condition (verified TE-69:
    reverting `if proc.returncode != 0:` to `if proc.returncode != 0 and
    not headers:` in _msvc_closure -> red). Under GCC/Clang it discriminates
    F-1's own raise instead -- the mechanism that ACTUALLY governs this
    leg's result on those compilers -- verified this round: disabling
    _gcc_clang_closure's raise (`if proc.returncode != 0:` -> `if False:`)
    makes this leg fail under Clang 18.1.8 too, though on a different
    expected string (SEMB_SOURCE_NOT_IN_OWN_CLOSURE, N-6's own check, fires
    because the now-unraised failure yields an empty closure for a source
    that visibly names #includes -- still a real, verified failure of the
    leg, not a silent pass). Neither mechanism can be broken without this
    leg going red on its own compiler; no single revert makes it red on
    all three, because no single commit covers all three compilers'
    closure functions."""
    src = copy_repo(SCRATCH / "c34g_src")
    (src / "src" / "uses_gen.cpp").write_text(
        '#include "superembedder/version.h"\n#include "semb_engine_pin.h"\nint semb_uses_gen() { return 0; }\n',
        encoding="utf-8",
    )
    cmakelists = src / "CMakeLists.txt"
    text = cmakelists.read_text(encoding="utf-8")
    old_sources = 'SOURCES src/version.cpp\n\tINCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include"'
    new_sources = 'SOURCES src/version.cpp src/uses_gen.cpp\n\tINCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include"'
    assert text.count(old_sources) == 1, f"anchor not found or not unique: {text.count(old_sources)}"
    text = text.replace(old_sources, new_sources, 1)
    text = text.replace(
        "add_library(superembedder STATIC src/version.cpp)",
        "add_library(superembedder STATIC src/version.cpp src/uses_gen.cpp)",
        1,
    )
    cmakelists.write_text(text, encoding="utf-8")
    rc, out = run_cmake_configure(src, SCRATCH / "c34g_build", ENGINE_PREFIX)
    record("C34(g) preprocess failure raises, not truncates (N-5)", "SEMB_SOURCE_PREPROCESS_FAILED", rc, out)


def c34_leg_j_empty_resolver_refused():
    """TE-69 P-3, a permanent leg for N-6. SEMB_TEST_FORCE_EMPTY_CLOSURE
    drives the real cmd_configure() through a real `cmake -S -B` to its own
    must-reject: a resolver reporting nothing at all against this project's
    real, #include-bearing src/version.cpp.

    TE-71 Q-8: this leg claimed letter "h", which the plan's own C34 row
    (Claude/Plans/SuperEmbedder_Plan.md Sec8) already allocates to a
    different, specified leg -- SEMB_PS_VERSION_LABEL against ps_version,
    one of the two manifest-honesty legs (not yet buildable, gated on
    TE-63). Renamed to "j", a letter the plan does not use for C34 (the
    plan's own C34 letters are a-f and h; the code's are a-d, f-g, i, now
    j -- "e" is a historical gap on the code side, matching the plan's own
    reservation of it for a different not-yet-built leg too)."""
    src = copy_repo(SCRATCH / "c34j_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c34j_build", ENGINE_PREFIX,
                                   extra_env={"SEMB_TEST_FORCE_EMPTY_CLOSURE": "1"})
    record("C34(j) empty resolver refused (N-6)", "SEMB_SOURCE_NOT_IN_OWN_CLOSURE", rc, out)


def c34_leg_i_build_dir_placement_invariant():
    """TE-69 P-3, a permanent leg for N-8. The g-leg's own generated-header-
    reaching source, configured at two different -B locations (nested
    inside the source root, and a sibling outside it) -- must produce an
    IDENTICAL semb_source_sha and an identical covered_count at both, and
    the post-build re-verification must agree at both. TE-71 Q-2: the
    in-root placement used to be a SIBLING of the source root under
    SCRATCH, not nested inside it -- both configures were out-of-root, so
    N-8's exclusion caught the generated header at both placements and the
    leg passed with the exclusion removed. build_in is now genuinely inside
    the source root, at src/build/semb."""
    src = copy_repo(SCRATCH / "c34i_src")
    (src / "src" / "uses_gen.cpp").write_text(
        '#include "superembedder/version.h"\n#include "semb_engine_pin.h"\nint semb_uses_gen() { return 0; }\n',
        encoding="utf-8",
    )
    cmakelists = src / "CMakeLists.txt"
    text = cmakelists.read_text(encoding="utf-8")
    old_sources = 'SOURCES src/version.cpp\n\tINCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include"'
    new_sources = 'SOURCES src/version.cpp src/uses_gen.cpp\n\tINCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include" "${CMAKE_BINARY_DIR}/generated"'
    assert text.count(old_sources) == 1, f"anchor not found or not unique: {text.count(old_sources)}"
    text = text.replace(old_sources, new_sources, 1)
    text = text.replace(
        "add_library(superembedder STATIC src/version.cpp)",
        "add_library(superembedder STATIC src/version.cpp src/uses_gen.cpp)",
        1,
    )
    cmakelists.write_text(text, encoding="utf-8")

    # TE-71 Q-2: build_in used to be SCRATCH/"c34i_build_in" -- a SIBLING of
    # `src` under SCRATCH, not nested inside it, despite the docstring and
    # this comment both saying "nested". Both configures were therefore
    # out-of-root, N-8's own exclusion caught the generated header at BOTH
    # placements, and the leg passed with N-8's fix removed (Q-2, executed:
    # reverting `if build_dir is not None:` to `if False and build_dir is
    # not None:` still passed). build_in is now genuinely inside `src`, at
    # the project's own documented "-B build/semb" layout relative to the
    # source root -- the placement the exclusion's in-root branch has to
    # reach for the leg to discriminate at all.
    build_in = src / "build" / "semb"
    rc_in, out_in = run_cmake_configure(src, build_in, ENGINE_PREFIX)
    # TE-71 Q-9: this used to be SCRATCH.parent/"c34i_build_out_of_root" --
    # under the default scratch that is the system temp directory, and
    # under an explicit --scratch it is that path's OWN parent (a drive
    # root, for the short paths leg (e)'s own LNK1181 warning recommends).
    # F-12's cleanup covers SCRATCH only, so this directory was left behind
    # on any failing run or any exception before this function's own
    # rmtree, and its fixed name collided across two matrix runs sharing a
    # scratch parent. Still a sibling of `src` (out-of-root is the point of
    # this half of the leg), now placed inside SCRATCH -- F-12 owns it, and
    # SCRATCH's own name is unique per run (tempfile.mkdtemp, or the
    # caller's explicit --scratch, either way a real leaf directory, not a
    # shared parent).
    build_out = SCRATCH / "c34i_build_out_of_root"  # a sibling of src, inside SCRATCH
    rc_out, out_out = run_cmake_configure(src, build_out, ENGINE_PREFIX)

    def extract(build_dir: Path):
        sidecar = build_dir / "generated" / "semb_source_provenance.json"
        if not sidecar.exists():
            return None
        return json.loads(sidecar.read_text(encoding="utf-8"))["semb_source_sha"]

    sha_in = extract(build_in) if rc_in == 0 else None
    sha_out = extract(build_out) if rc_out == 0 else None
    passed = rc_in == 0 and rc_out == 0 and sha_in is not None and sha_in == sha_out
    RESULTS.append({
        "leg": "C34(i) semb_source_sha invariant to -B placement (N-8)",
        "expected": "identical semb_source_sha regardless of -B location",
        "returncode": [rc_in, rc_out],
        "want_fail": False,
        "found_expected_string": passed,
        "passed": passed,
        "output_tail": f"in-root={sha_in} out-of-root={sha_out}",
    })
    rmtree(build_out)


# ---------------------------------------------------------------------------
# C14 legs (TE-65 F-4/F-5 rewrite: BuildFlags.cmake no longer has a per-target
# registry to strip a flag from -- the directive is directory-wide and the
# assertion enumerates CMake's own BUILDSYSTEM_TARGETS. The legs below match
# the new mechanism's own two must-reject constructions plus F-4's exact
# reproduction as a positive proof.)
# ---------------------------------------------------------------------------

def c14_directive_withheld():
    """The directory-wide directive itself absent -- SEMB_FP_FLAG_ASSERTION's
    own must-reject, proving it can fail at all."""
    src = copy_repo(SCRATCH / "c14a_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c14a_build", ENGINE_PREFIX,
                                   extra_defines={"SEMB_TEST_SKIP_FP_DIRECTIVE": "1"})
    record("C14 directory-wide directive withheld", "SEMB_FP_CONTRACTION_UNGUARDED", rc, out)


def c14_cxx_flags_fastmath():
    """The reviewer's E-8 construction: -DCMAKE_CXX_FLAGS=<the real
    compiler's own fast-math spelling>, which used to be invisible to a
    check that only read target COMPILE_OPTIONS. TE-67 N-7: the forbidden-
    flag spelling is chosen from the ACTUAL compiler in use
    (detect_compiler_id()), not hardcoded to MSVC -- on GCC/Clang this
    passes -ffast-math, matching what cmake/BuildFlags.cmake itself checks
    for on that compiler family."""
    compiler_id = detect_compiler_id()
    forbidden = "/fp:fast" if compiler_id == "MSVC" else "-ffast-math"
    src = copy_repo(SCRATCH / "c14b_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c14b_build", ENGINE_PREFIX,
                                   extra_defines={"CMAKE_CXX_FLAGS": forbidden})
    record(f"C14 CMAKE_CXX_FLAGS carries fast-math ({compiler_id})", "SEMB_FP_FASTMATH_PRESENT", rc, out)


def c14_positive():
    src = copy_repo(SCRATCH / "c14_pos_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c14_pos_build", ENGINE_PREFIX)
    passed = rc == 0 and "C14 build-configuration assertion" in out
    RESULTS.append({
        "leg": "C14 flag present (positive)",
        "expected": "C14 build-configuration assertion: ... carries",
        "returncode": rc,
        "want_fail": False,
        "found_expected_string": passed,
        "passed": passed,
        "output_tail": "\n".join(out.splitlines()[-8:]),
    })


def c14_unregistered_target():
    """F-4's exact reproduction: add_library(semb_extra ...) the ordinary way,
    with no incantation of any kind, before semb_assert_precise_fp() runs.
    Positive proof the fix is structural: configure must succeed AND the new
    target's real compile line, read back from compile_commands.json, must
    carry the required flag -- not merely "the assertion did not complain"."""
    src = copy_repo(SCRATCH / "c14d_src")
    extra_cpp = src / "src" / "extra.cpp"
    extra_cpp.write_text("int semb_extra_symbol() { return 0; }\n", encoding="utf-8")
    cmakelists = src / "CMakeLists.txt"
    text = cmakelists.read_text(encoding="utf-8")
    # Anchor on the real call site specifically -- "semb_assert_precise_fp()"
    # alone also appears inside a comment earlier in the file (the include()
    # line), and a bare substring replace landed there first, corrupting the
    # file (found by execution: a CMake parse error, not a green false pass).
    anchor = "\nsemb_assert_precise_fp()\n"
    assert text.count(anchor) == 1, f"expected exactly one real call site, found {text.count(anchor)}"
    text = text.replace(
        anchor,
        '\nadd_library(semb_extra STATIC src/extra.cpp)\n\nsemb_assert_precise_fp()\n',
        1,
    )
    cmakelists.write_text(text, encoding="utf-8")
    build = SCRATCH / "c14d_build"
    # TE-69 P-7: every other leg goes through run_cmake_configure(), which
    # rmtree()s the build directory before configuring; this leg built its
    # own cmake invocation by hand and omitted that. Measured: re-running
    # this leg into a --scratch a PRIOR run (under a different compiler)
    # already populated reads FAIL, because CMake reuses the CACHED
    # compiler from that prior configure while detect_compiler_id() reports
    # the CURRENT one -- the flag check then looks for the wrong compiler's
    # spelling on the wrong compiler's compile line. A reused --scratch is
    # a supported state (F-12's own carve-out keeps scratch on an explicit
    # --scratch), so this leg must not depend on it being fresh.
    rmtree(build)
    cmd = [
        CMAKE, "-G", GENERATOR, "-S", str(src), "-B", str(build),
        f"-DCMAKE_PREFIX_PATH={ENGINE_PREFIX}", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ]
    if GENERATOR == "Ninja" and NINJA:
        cmd.append(f"-DCMAKE_MAKE_PROGRAM={NINJA}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    # TE-67 N-7: the required-flag spelling to look for is chosen from the
    # ACTUAL compiler in use, not from GENERATOR -- GENERATOR is "Ninja" on
    # all three of this project's CI OSes regardless of which compiler that
    # Ninja invocation drives, so using it as a compiler stand-in looked for
    # MSVC's spelling on a GCC compile line and could never find it.
    compiler_id = detect_compiler_id()
    required_flag = "/fp:precise" if compiler_id == "MSVC" else "-ffp-contract=off"
    flag_in_real_command = False
    if proc.returncode == 0:
        cc_path = build / "compile_commands.json"
        if cc_path.exists():
            entries = json.loads(cc_path.read_text(encoding="utf-8"))
            for e in entries:
                if e.get("file", "").replace("\\", "/").endswith("src/extra.cpp"):
                    cmd_line = e.get("command", "") or " ".join(e.get("arguments", []))
                    flag_in_real_command = required_flag in cmd_line
    passed = proc.returncode == 0 and flag_in_real_command
    RESULTS.append({
        "leg": "C14 unregistered target (F-4 reproduction)",
        "expected": "configure succeeds AND semb_extra's real compile_commands.json entry carries the required flag",
        "returncode": proc.returncode,
        "want_fail": False,
        "found_expected_string": flag_in_real_command,
        "passed": passed,
        "output_tail": "\n".join(out.splitlines()[-8:]) + f"\nflag_in_real_command={flag_in_real_command}",
    })


def c14_target_compile_options_cleared():
    """TE-67 N-2. A target's own COMPILE_OPTIONS explicitly set to empty
    removes the directory-wide default from ITS real compile line too
    (measured: get_target_property before any override already shows the
    directory default, confirming CMake initializes it there at target
    creation -- and an explicit set() overwrites that initial value)."""
    src = copy_repo(SCRATCH / "c14e_src")
    cmakelists = src / "CMakeLists.txt"
    text = cmakelists.read_text(encoding="utf-8")
    anchor = "\nsemb_assert_precise_fp()\n"
    assert text.count(anchor) == 1, f"expected exactly one real call site, found {text.count(anchor)}"
    text = text.replace(
        anchor,
        '\nset_target_properties(superembedder PROPERTIES COMPILE_OPTIONS "")\nsemb_assert_precise_fp()\n',
        1,
    )
    cmakelists.write_text(text, encoding="utf-8")
    rc, out = run_cmake_configure(src, SCRATCH / "c14e_build", ENGINE_PREFIX)
    record("C14 target COMPILE_OPTIONS cleared (N-2)", "SEMB_FP_CONTRACTION_UNGUARDED", rc, out)


def c14_subdirectory_target():
    """TE-67 N-3, fixed for TE-69 P-1. BUILDSYSTEM_TARGETS is per-directory;
    a target declared in add_subdirectory() must be reached by the
    recursive walk. TE-69 P-1: this leg used to hardcode /fp:fast (MSVC),
    the exact defect N-7 named, in the same commit that repaired it --
    reproduced under Clang 18.1.8: -ffast-math is the real forbidden flag
    off MSVC, so a target carrying /fp:fast (meaningless to Clang)
    configures clean and the leg recorded a false FAIL. The forbidden-flag
    spelling is now chosen from detect_compiler_id(), matching what
    cmake/BuildFlags.cmake itself checks for on the real compiler in use."""
    compiler_id = detect_compiler_id()
    forbidden = "/fp:fast" if compiler_id == "MSVC" else "-ffast-math"
    src = copy_repo(SCRATCH / "c14f_src")
    tests_dir = src / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "t.cpp").write_text("int semb_tests_symbol() { return 0; }\n", encoding="utf-8")
    (tests_dir / "CMakeLists.txt").write_text(
        f"add_library(semb_tests STATIC t.cpp)\ntarget_compile_options(semb_tests PRIVATE {forbidden})\n",
        encoding="utf-8",
    )
    cmakelists = src / "CMakeLists.txt"
    text = cmakelists.read_text(encoding="utf-8")
    anchor = "\nsemb_assert_precise_fp()\n"
    assert text.count(anchor) == 1, f"expected exactly one real call site, found {text.count(anchor)}"
    text = text.replace(anchor, "\nadd_subdirectory(tests)\nsemb_assert_precise_fp()\n", 1)
    cmakelists.write_text(text, encoding="utf-8")
    rc, out = run_cmake_configure(src, SCRATCH / "c14f_build", ENGINE_PREFIX)
    record(f"C14 subdirectory target with fast-math ({compiler_id})", "SEMB_FP_FASTMATH_PRESENT", rc, out)


def c14_cxx_flags_release_fastmath():
    """TE-67 N-4, fixed for TE-69 P-1. The identical bypass class E-8 named,
    one release-build variable over: -DCMAKE_CXX_FLAGS_RELEASE=<the real
    compiler's own fast-math spelling>. TE-69 P-1: this leg hardcoded
    /fp:fast (MSVC); reproduced under Clang: the variable's own content is
    meaningless to Clang, string(FIND) against -ffast-math never matches,
    and configure exits 0 -- a false FAIL."""
    compiler_id = detect_compiler_id()
    forbidden = "/fp:fast" if compiler_id == "MSVC" else "-ffast-math"
    src = copy_repo(SCRATCH / "c14g_src")
    rc, out = run_cmake_configure(src, SCRATCH / "c14g_build", ENGINE_PREFIX,
                                   extra_defines={"CMAKE_BUILD_TYPE": "Release",
                                                  "CMAKE_CXX_FLAGS_RELEASE": forbidden})
    record(f"C14 CMAKE_CXX_FLAGS_RELEASE carries fast-math ({compiler_id})", "SEMB_FP_FASTMATH_PRESENT", rc, out)


def c14_run_all_legs():
    """TE-69 O-4: renamed from c14_flag_strip -- N-9's prose sweep reworded
    every mention of "flag-strip proof" but left this identifier, the same
    stale-mechanism class one name short of swept. None of the seven legs
    below strips a flag; each constructs one way the C14 assertion could be
    wrong and confirms it is not."""
    c14_directive_withheld()
    c14_cxx_flags_fastmath()
    c14_positive()
    c14_unregistered_target()
    c14_target_compile_options_cleared()
    c14_subdirectory_target()
    c14_cxx_flags_release_fastmath()


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
    ap.add_argument("--keep-scratch", action="store_true",
                     help="do not delete the scratch tree on a fully-passing run (TE-65 F-12: by "
                          "default it is deleted -- leg (e) alone clones+builds the real engine and "
                          "leaves ~100 MB behind per run, never cleaned before this fix)")
    args = ap.parse_args()

    REPO_ROOT = Path(args.repo_root).resolve()
    ENGINE_PREFIX = Path(args.engine_prefix).resolve()
    CMAKE = args.cmake_executable
    GENERATOR = args.generator
    NINJA = args.ninja_executable
    PYEXE = args.python_executable
    SCRATCH = Path(args.scratch).resolve() if args.scratch else Path(tempfile.mkdtemp(prefix="semb_negconf_"))
    SCRATCH.mkdir(parents=True, exist_ok=True)

    # TE-65 F-13: leg (e) builds the real engine under SCRATCH, and MSVC's
    # own compiler-check step (testCXXCompiler.cxx.obj) hit LNK1181 at a
    # ~150-character scratch root on the reviewer's machine, surfacing as a
    # C33 leg failure that pointed at nothing about the artifact -- a defect
    # in the *path*, reported as a defect in the *build*. This does not fix
    # the underlying Windows path-length ceiling (core.longpaths=true
    # already covers what git itself can do about it); it gives an early,
    # legible warning instead of a confusing failure buried inside leg (e)'s
    # own output three subprocess calls later.
    _scratch_len = len(str(SCRATCH))
    if _scratch_len > 100:
        print(f"[run_configure_matrix] WARNING: scratch root is {_scratch_len} characters "
              f"({SCRATCH}). Leg (e) builds the real engine under this path; MSVC's own compiler-"
              f"check step has been observed to fail with LNK1181 past roughly this length even "
              f"with core.longpaths=true. Pass --scratch with a short path (e.g. C:\\semb_scratch) "
              f"if leg (e) fails for no reason connected to the artifact.", flush=True)

    pin_tool = REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py"

    c33_leg_a_hand_edited_lock_tree()
    c33_leg_b_missing_provenance()
    c33_leg_c_provenance_lock_disagreement()
    c33_leg_d_floor()
    c33_leg_d_exact_pin()
    c33_leg_e_dirty_clone(pin_tool, REPO_ROOT / "superslm.lock")
    c33_leg_e2_added_file_no_edit(pin_tool, REPO_ROOT / "superslm.lock")
    c33_leg_e3_deleted_manifest_field(pin_tool, REPO_ROOT / "superslm.lock")
    c33_leg_g_unowned_workdir_refused(pin_tool, REPO_ROOT / "superslm.lock")
    c33_leg_h_final_cleanup_preserves_user_files(pin_tool, REPO_ROOT / "superslm.lock")
    c33_leg_f_label_mismatch()

    c34_leg_a_cache_override()
    c34_leg_b_missing_covered_file()
    c34_leg_c_engine_path_changed()
    c34_leg_d_source_added_after_digest(NINJA)
    c34_leg_f_header_edit_moves_digest()
    c34_leg_g_preprocess_failure_raises()
    c34_leg_j_empty_resolver_refused()
    c34_leg_i_build_dir_placement_invariant()

    c14_run_all_legs()

    all_passed = all(r["passed"] for r in RESULTS)

    # TE-71 Q-4: the leg-count reconciliation has been wrong, in a way that
    # cancelled to the right total, in three consecutive rounds (P-5,
    # D-SLM5984, this casebook's own Q-4) -- every prior instance was a
    # count someone typed by hand from reading main()'s own call list and
    # miscounted. Derived here instead, from RESULTS itself -- the actual
    # population every leg recorded into on this real run -- never from the
    # source. A leg's family is the "C<n>" prefix of its own name (every
    # leg name starts with one, with or without a following "(letter)"):
    # C33(a)... and C34(a)... carry parens, C14's seven do not.
    _family_re = re.compile(r"^(C\d+)")
    family_counts: dict[str, int] = {}
    for _r in RESULTS:
        _m = _family_re.match(_r["leg"])
        _fam = _m.group(1) if _m else "other"
        family_counts[_fam] = family_counts.get(_fam, 0) + 1
    leg_counts = {"total": len(RESULTS), "by_family": dict(sorted(family_counts.items()))}
    print(json.dumps({"all_passed": all_passed, "leg_counts": leg_counts, "results": RESULTS}, indent=2))

    # TE-65 F-12: this used to leave the scratch tree behind unconditionally
    # -- leg (e) alone clones and builds the real engine (~100 MB, measured),
    # and three copies had accumulated in the worktree's build/ before this
    # fix. Cleaned up on a fully-passing run unless --keep-scratch was
    # passed; kept on any failure so the failing construction can be
    # inspected, and kept whenever the caller supplied --scratch explicitly
    # (an explicit path is a signal the caller wants to look at it, e.g. the
    # path-length investigation this same finding's F-13 half exists for).
    if all_passed and not args.keep_scratch and not args.scratch:
        rmtree(SCRATCH)
    else:
        print(f"[run_configure_matrix] scratch tree kept at {SCRATCH}", flush=True)

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
