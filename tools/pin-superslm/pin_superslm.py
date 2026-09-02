#!/usr/bin/env python3
"""tools/pin-superslm — clone, build, and install the pinned SuperSLM engine release,
and compute the provenance the two CMake configure guards (see cmake/EngineGuards.cmake,
Claude/Plans/SuperEmbedder_Plan.md §4.1) verify at every configure.

WHAT THIS TOOL DOES, IN ORDER
  1. Reads `tag=` from superslm.lock (the only field a person edits by hand).
  2. Clones the engine at that tag — from the remote by default, or from a local
     path via --source (a documented option; SuperEmbedder never builds
     D:\\SuperSLM in place) — with core.autocrlf=false and core.eol=lf, so the
     digest below is checkout-invariant (§1.3: "every digested source byte is
     checkout-invariant").
  3. Configures and builds ONLY the `superslm` static-library target (Ninja +
     whatever C++ compiler is already on PATH — the caller is responsible for
     having a working compiler environment active, e.g. having run VsDevCmd.bat
     on Windows or simply being on a Unix box with a system compiler).
  4. Derives the engine's own COMPILE closure — every source file the `superslm`
     target actually compiled, plus every header the compiler actually resolved
     for each of those translation units — from Ninja's own dependency database
     (`ninja -t query` / `ninja -t deps`), never curated by this tool (§4.1:
     "each derived from a build object rather than curated here").
  5. Installs the engine (`cmake --install`) to the given prefix and reads
     `install_manifest.txt` for the INSTALL closure — every file the engine's own
     install() rules actually wrote.
  6. For every COMPILE-closure member, checks it against the tag's own git tree
     (`git hash-object` vs `git rev-parse <tag>:<path>`) — the independent
     witness for SEMB_ENGINE_INSTALL_DIVERGED (an uncommitted edit in the clone
     changes what got compiled without changing what the tag says should be
     there).
  7. Computes engine_tree_sha over the union of both closures, path-sorted,
     length-prefixed (§4.1's own formula, with each entry additionally
     namespaced by which closure it came from — see `_digest_members` below for
     the exact byte layout, since the plan's prose formula does not by itself
     disambiguate two same-named members from different closures).
  8. Writes the provenance manifest into
     `<prefix>/share/superslm-provenance/provenance.json`, and snapshots every
     COMPILE-closure member's bytes into
     `<prefix>/share/superslm-provenance/compiled/<path>` so a later `cmake`
     configure can recompute the whole digest from the prefix alone, without
     the clone still existing.
  9. Updates superslm.lock's `commit=` and `tree=` fields to match what was just
     computed (the `tag=` field is the only one a person edits; this tool
     derives the other two — D-SLM3893).

USAGE
  python tools/pin-superslm/pin_superslm.py \\
      --lock superslm.lock --prefix build/_engine_install [--source <path-or-url>] \\
      [--workdir build/_engine_src] [--cmake <path>] [--ninja <path>] [--generator Ninja] \\
      [--keep-workdir]

Exit codes: 0 success; 1 usage/environment error; 2 clone/build/install failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provenance_lib import digest_members  # noqa: E402

DEFAULT_REMOTE = "https://github.com/dansupergameprogrammer/SuperSLM.git"


def log(msg: str) -> None:
    print(f"[pin-superslm] {msg}", flush=True)


def _rmtree_onerror(func, path, exc_info):
    """git packs its object store read-only; a plain shutil.rmtree hits
    PermissionError on Windows the first time it tries to unlink one. Clear
    the read-only bit and retry once — the standard workaround for removing a
    git checkout on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


# TE-73: R-1 was configure_engine's own bare rmtree(build) -- an unguarded
# THIRD delete idiom in a file that already had two ("rmtree()" the local
# helper, and a raw "shutil.rmtree(..., ignore_errors=True)" at final
# cleanup, R-2's own bug). Three consecutive rounds each guarded the ONE
# site a reviewer had just named and left a sibling site, written with a
# different idiom, untouched -- the class StandardsDocument.md Sec4 names:
# a rule enforced by a person remembering every call site is a rule that
# has already failed. This module now has exactly ONE function permitted
# to call a real deletion primitive anywhere in it --
# tests/pin_superslm_delete_ast_check.py asserts this by walking the
# module's own AST, not by grep, so a renamed import cannot dodge it.
_OWNED_PATHS: set[Path] = set()


def _own(path: Path) -> None:
    """Record that this run created `path`, or was explicitly authorized
    (by an existing-marker check that already ran, or by an explicit CLI
    override like --fresh-build) to treat it as its own. The ONLY way a
    path becomes eligible for _remove_owned() -- called at the moment
    ownership is established, in the caller's own code, never inferred
    afterward from what merely exists on disk. Every caller below is
    responsible for its own judgment about what counts as "this run's";
    this function only records the answer, and _remove_owned only reads
    it."""
    _OWNED_PATHS.add(path.resolve())


def _remove_owned(path: Path) -> None:
    """TE-73: the ONE function in this module permitted to call a real
    deletion primitive. Refuses unless `path` was explicitly recorded via
    _own() first -- no marker, no heuristic, no "own_this_run" bypass
    parameter (TE-69 P-4's own shape, which TE-71 Q-1 found had been aimed
    at the wrong path and TE-73's R-1 found had a sibling site with no
    guard at all): ownership is now established once, explicitly, by the
    caller, before this function ever runs, and this function's only job
    is to check the ledger and then delete correctly.

    TE-71 R-2, closed here rather than reintroduced: `shutil.rmtree(path,
    onerror=_rmtree_onerror, ignore_errors=True)` silently does nothing to
    a read-only file -- CPython's shutil.rmtree installs a no-op `onexc`
    when `ignore_errors` is true and never consults `onerror` at all (read
    at source, CPython 3.13.6), which is exactly what let 11+ MB of git's
    own read-only pack files survive a "successful" cleanup. This function
    never passes ignore_errors; onerror alone -- the correct idiom the
    module's own retired `rmtree()` helper already used -- runs every
    time, for the reason that helper's own docstring gave: clearing the
    read-only bit and retrying once is the standard fix for a git checkout
    on Windows. A delete through here either removes everything or raises;
    it never reports success while leaving bytes behind."""
    resolved = path.resolve()
    if len(resolved.parts) <= 2:
        raise SystemExit(
            f"SEMB_PIN_REFUSES_TO_DELETE_UNOWNED: refusing to delete {resolved} — too close "
            f"to a filesystem root to safely wipe, regardless of ownership."
        )
    if resolved not in _OWNED_PATHS:
        raise SystemExit(
            f"SEMB_PIN_REFUSES_TO_DELETE_UNOWNED: refusing to delete {resolved} — this run "
            f"did not record creating it. Only a path this run itself created, or was explicitly "
            f"authorized to treat as its own, can be removed."
        )
    if not resolved.exists():
        return
    if resolved.is_dir():
        shutil.rmtree(resolved, onerror=_rmtree_onerror)
    else:
        resolved.unlink()


def run(cmd, cwd=None, check=True, capture=False, env=None):
    log("+ " + " ".join(str(c) for c in cmd))
    kwargs = {"cwd": cwd, "env": env}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
        kwargs["text"] = True
    proc = subprocess.run(cmd, **kwargs)
    if capture:
        sys.stdout.write(proc.stdout)
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(str(c) for c in cmd)}")
    return proc


def parse_lock(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"lock file not found: {path}")
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        fields[k.strip()] = v.strip()
    if "tag" not in fields:
        raise SystemExit(f"{path}: missing required field 'tag='")
    return fields


def write_lock(path: Path, fields: dict) -> None:
    lines = [f"{k}={v}" for k, v in fields.items()]
    # TE-65 F-10: newline="\n" forces LF regardless of platform. write_text's
    # default (universal newlines, translating "\n" to os.linesep) means the
    # SAME call emits CRLF on Windows and LF on Linux/macOS -- superslm.lock's
    # committed line endings would depend on which OS last ran this tool.
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def clone_engine(source: str, tag: str, workdir: Path) -> Path:
    """Clone `source` at `tag` into workdir/src. `source` is a git URL or a local
    path (a documented option — see this file's module docstring). Always uses
    core.autocrlf=false / core.eol=lf (§1.3's checkout-invariance requirement)
    and core.longpaths=true (the engine's own tree carries paths that exceed
    Windows' legacy MAX_PATH under a short clone root — verified by execution).
    """
    dest = workdir / "src"
    if dest.exists():
        # TE-67 N-11: --workdir gets the same guard --prefix already has.
        # This runs BEFORE the clone, configure and build even start (the
        # earliest of the three deletion sites in this file), where the
        # --prefix guard could only run after all three had already
        # completed. Marker is ".git" -- a prior run's own clone -- rather
        # than the provenance marker, which does not apply to a scratch
        # clone directory. TE-73: judging (is this safe to claim) and
        # deleting are now two separate steps -- _assert_safe_to_wipe only
        # judges; _own() records the verdict; _remove_owned() is the one
        # function in this module that deletes.
        _assert_safe_to_wipe(dest, markers=(".git",), what="--workdir/src", error_code="SEMB_PIN_UNSAFE_WORKDIR")
        _own(dest)
        _remove_owned(dest)
    workdir.mkdir(parents=True, exist_ok=True)
    _own(dest)  # this run is about to create it fresh via git clone, below
    run([
        "git", "clone",
        "-c", "core.autocrlf=false",
        "-c", "core.eol=lf",
        "-c", "core.longpaths=true",
        "--branch", tag, "--single-branch",
        source, str(dest),
    ])
    return dest


def resolve_commit(clone: Path, tag: str) -> str:
    proc = run(["git", "-C", str(clone), "rev-parse", f"{tag}^{{commit}}"], capture=True)
    return proc.stdout.strip().splitlines()[-1].strip()


def configure_engine(clone: Path, build: Path, cmake: str, ninja: str, generator: str,
                      fresh_build: bool = False) -> None:
    # TE-73 R-1 (Critical): this used to be a bare `if build.exists():
    # rmtree(build)` -- no guard, no marker check, no depth check, the ONE
    # of the tool's three deletion sites its own N-11 comment enumerated
    # that neither F-11, N-11, P-4 nor TE-71's Q-1 ever reached, because
    # each of those rounds guarded the site a reviewer had just named
    # (clone_engine's dest, the final cleanup) and this one sat ten lines
    # away, untouched, through all of them. A pre-existing build/ is no
    # longer assumed to be this run's just because this run is about to
    # configure into it: refused by name unless the caller passes
    # --fresh-build, matching the design's own refuse-by-default posture
    # for every other unowned path (SEMB_PIN_UNSAFE_WORKDIR,
    # SEMB_PIN_UNSAFE_PREFIX). markers=() means _assert_safe_to_wipe's
    # marker branch can never pass here -- there is no legitimate marker
    # for "an old CMake build directory", unlike a git clone (".git") or a
    # prior install ("share/superslm-provenance") -- so a NON-EMPTY
    # pre-existing build/ is always refused without --fresh-build; an
    # EMPTY one (e.g. left by an interrupted prior run) passes through,
    # since there is nothing in it to lose.
    if build.exists():
        if not fresh_build:
            _assert_safe_to_wipe(build, markers=(), what="--workdir/build",
                                  error_code="SEMB_PIN_UNSAFE_BUILD_DIR")
        _own(build)
        _remove_owned(build)
    build.mkdir(parents=True, exist_ok=True)
    _own(build)  # this run just created it (or was explicitly authorized to replace it)
    cmd = [
        cmake, "-G", generator,
        "-S", str(clone), "-B", str(build),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ]
    if generator == "Ninja" and ninja:
        cmd.append(f"-DCMAKE_MAKE_PROGRAM={ninja}")
    run(cmd)


def build_engine_library(build: Path, cmake: str, target: str = "superslm") -> None:
    run([cmake, "--build", str(build), "--target", target])


def _assert_safe_to_wipe(path: Path, markers: tuple[str, ...], what: str, error_code: str = "SEMB_PIN_UNSAFE_PREFIX") -> None:
    """Judges whether `path` is safe to claim as this run's own -- raises if
    not, returns silently if so. TE-65 F-11 added this for --prefix; TE-67
    N-11 generalized it to --workdir. TE-73: this function no longer
    deletes anything itself (it never did, but used to be paired one-to-one
    with an adjacent rmtree call at each site, which is what let R-1's
    sibling site go unguarded -- a fourth call site simply never got a
    pairing). It is now purely a judgment: raise, or don't. The caller
    decides what "safe" means for its own site by the `markers` it passes
    (empty markers = never safe on a non-empty path, configure_engine's own
    choice for --workdir/build), calls _own() on a pass, and
    _remove_owned() does the actual deletion -- the one function in this
    module permitted to.

    (1) A path resolving to two or fewer components (a drive root, or one
        level below it, e.g. a home directory) is refused outright,
        regardless of contents.
    (2) An EXISTING, non-empty path carrying none of `markers` (each a
        relative path checked for existence under `path`) is refused,
        because this tool did not create it and has no basis for deciding
        it is safe to erase."""
    resolved = path.resolve()
    if len(resolved.parts) <= 2:
        raise SystemExit(
            f"{error_code}: refusing to wipe {what} at {resolved} — too close to a filesystem "
            f"root to safely wipe and recreate. Pass a path at least two directories deep (e.g. "
            f"build/_engine_install, not C:\\ or a home directory)."
        )
    if resolved.exists():
        has_marker = any((resolved / m).exists() for m in markers)
        if not has_marker and any(resolved.iterdir()):
            raise SystemExit(
                f"{error_code}: refusing to wipe {what} at {resolved} — it already exists, is "
                f"non-empty, and carries none of this tool's own markers ({', '.join(markers)}). "
                f"Point it at an empty directory or one this tool already owns."
            )


def install_engine(build: Path, cmake: str, prefix: Path) -> None:
    _assert_safe_to_wipe(prefix, markers=("share/superslm-provenance",), what="--prefix")
    if prefix.exists():
        # TE-73: same split as clone_engine's -- _assert_safe_to_wipe above
        # already judged this prefix safe to claim (empty, or carrying this
        # tool's own marker from a prior successful install, which is the
        # normal re-pin lifecycle this tool exists to support); _own() +
        # _remove_owned() do the actual deletion, through the one function
        # in the module allowed to.
        _own(prefix)
        _remove_owned(prefix)
    prefix.mkdir(parents=True, exist_ok=True)
    _own(prefix)  # this run just created it (or reclaimed it, per the marker check above)
    run([cmake, "--install", str(build), "--prefix", str(prefix)])


def ninja_query(build: Path, ninja: str, target: str) -> str:
    proc = run([ninja, "-t", "query", target], cwd=build, capture=True)
    return proc.stdout


def ninja_deps(build: Path, ninja: str, obj: str) -> list[str]:
    proc = run([ninja, "-t", "deps", obj], cwd=build, capture=True, check=False)
    # TE-65 F-14: this used to be swallowed (check=False, no inspection of
    # the result at all) -- a missing or stale deps database silently reads
    # as "this object has no headers", indistinguishable from a genuine
    # header-free translation unit, which would narrow engine_tree_sha to
    # the source files alone with no error anywhere. Two distinct failure
    # shapes were found by execution and both are checked: an unknown
    # target exits nonzero ("ninja: error: unknown target ..."); a present-
    # but-undeps'd target (reproduced by deleting .ninja_deps and re-
    # querying a real, previously-built object) exits ZERO and prints
    # "<obj>: deps not found" instead of the normal "#deps N, deps mtime
    # ... (VALID)" header -- a return-code check alone does not catch this
    # second shape, so the output is inspected too.
    if proc.returncode != 0:
        raise SystemExit(
            f"SEMB_ENGINE_DEPS_UNAVAILABLE: 'ninja -t deps {obj}' exited {proc.returncode} in {build}; "
            f"the dependency database the engine's compile closure is derived from is missing or "
            f"stale. stdout:\n{proc.stdout}"
        )
    if "deps not found" in proc.stdout:
        raise SystemExit(
            f"SEMB_ENGINE_DEPS_UNAVAILABLE: 'ninja -t deps {obj}' in {build} reports 'deps not "
            f"found' (exit 0) -- the object exists but carries no recorded dependency entry, "
            f"typically a missing or deleted .ninja_deps. Rebuild from clean rather than trusting "
            f"an empty header list."
        )
    headers = []
    for line in proc.stdout.splitlines():
        line = line.rstrip("\n")
        if line.startswith("    "):
            headers.append(line.strip())
    return headers


def _parse_query_inputs(text: str) -> list[str]:
    """Parse `ninja -t query` output's "input:" block into the list of direct
    input paths (skips the rule-name line and any `||` order-only marker)."""
    lines = text.splitlines()
    out = []
    in_input = False
    for line in lines:
        if line.strip().startswith("input:"):
            in_input = True
            continue
        if line.strip().startswith("outputs:"):
            break
        if in_input:
            item = line.strip()
            if item in ("", "phony") or item.startswith("||"):
                continue
            out.append(item)
    return out


def derive_compile_closure(clone: Path, build: Path, ninja: str) -> set[Path]:
    """Return the set of absolute paths the `superslm` target actually compiled
    (its .cpp sources) plus every header the compiler actually resolved for
    each of them, all read from Ninja's own build graph and deps database —
    never curated by this tool."""
    phony_out = ninja_query(build, ninja, "superslm")
    lib_targets = _parse_query_inputs(phony_out)
    if not lib_targets:
        raise SystemExit("could not resolve the 'superslm' target's linked output from ninja -t query")
    lib_file = lib_targets[0]

    lib_out = ninja_query(build, ninja, lib_file)
    obj_files = _parse_query_inputs(lib_out)
    if not obj_files:
        raise SystemExit(f"could not resolve {lib_file}'s object-file inputs from ninja -t query")

    closure: set[Path] = set()
    for obj in obj_files:
        obj_out = ninja_query(build, ninja, obj)
        srcs = [s for s in _parse_query_inputs(obj_out) if not s.startswith("cmake_object_order_depends")]
        for s in srcs:
            closure.add((build / s).resolve())
        for h in ninja_deps(build, ninja, obj):
            closure.add((build / h).resolve())
    # Every path above is resolved relative to the BUILD directory (ninja's own
    # working directory); normalize to real files under the clone.
    resolved = set()
    for p in closure:
        try:
            resolved.add(p.resolve())
        except OSError:
            continue
    return resolved


# Compiled-binary suffixes are excluded from the digested install closure.
# FINDING (this session, executed): the linked static library is NOT
# byte-reproducible across two independent clone+configure+build+install runs
# of the IDENTICAL pinned commit — two runs produced `superslm.lib` archives
# differing at the byte level (MSVC's archiver embeds a per-member timestamp;
# every other installed and compiled file — 71 of 72 members — was
# byte-identical across the same two runs). Digesting the linked binary would
# therefore make engine_tree_sha itself non-reproducible for the identical
# pin, which breaks the guard this digest exists to serve (a re-run against
# an unchanged pin must reproduce the same tree). §4.1 states the digest is
# "provenance, not a hash input" — proof of WHICH SOURCE, not a fingerprint
# of compiled bytes; that second job belongs to witness_sha (§4.4), which
# proves compiled-arithmetic identity by RUNNING the code, the only layer
# that can meaningfully absorb a non-deterministic archiver. So the installed
# closure here covers headers and CMake package files only.
_EXCLUDED_INSTALL_SUFFIXES = {".lib", ".a", ".so", ".dylib", ".dll", ".exe", ".obj", ".o", ".pdb"}

# CMake's install(EXPORT ...) generates a base "<name>Targets.cmake" plus one
# per-config variant "<name>Targets-<config>.cmake" (e.g.
# superslmTargets-release.cmake); every one of these EMBEDS the platform's
# own compiled-library filename via IMPORTED_LOCATION_<CONFIG> (e.g.
# "${_IMPORT_PREFIX}/lib/superslm.lib" on Windows/MSVC vs
# ".../lib/libsuperslm.a" on Linux/macOS) -- read at source,
# superslmTargets-release.cmake at this session's install. TE-65 F-7:
# digesting this file makes engine_tree_sha vary by OS/toolchain for
# byte-identical engine source, which is a legitimate cross-platform
# difference the same way the linked archive itself is (D-SLM5919's own
# reasoning) -- excluded from the digest for the identical reason, not
# because it might be reproducible on the SAME platform.
# TE-67 N-16: superslmConfigVersion.cmake is generated by the identical
# mechanism (write_basic_package_version_file) and bakes CMAKE_SIZEOF_VOID_P
# in as a literal (read at source: "8" on this 64-bit build) -- the same
# class F-7 named for the Targets files, not fully swept there. Inert across
# this project's own three 64-bit CI runners, excluded anyway.
#
# TE-69 P-10, corrected TE-71 Q-5: this is a MEMBER LIST, not a class
# exclusion, and is named as one -- the exact shape F-7's own finding was
# about. There is a THIRD generated CMake file in the install:
# superslmConfig.cmake. Read at source, it is deliberately NOT excluded and
# does not belong in this list: its own mechanism (CMakePackageConfigHelpers'
# @PACKAGE_INIT@ block) resolves the install prefix RELATIVELY from its own
# location via ONE call --
# get_filename_component(PACKAGE_PREFIX_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../" ABSOLUTE)
# -- carrying no absolute path, no toolchain name and no platform-specific
# literal. [Q-5: P-10's own comment here previously attributed a FOUR-call
# _IMPORT_PREFIX chain to this file; that chain is real, but it lives in
# superslmTargets.cmake (get_filename_component(_IMPORT_PREFIX ...), four
# calls, one of the two files this pattern DOES exclude, read at source) --
# a different file from the one this paragraph is about. superslmConfig.cmake
# itself carries zero _IMPORT_PREFIX calls.] It is genuinely portable,
# checked at every repin by being left in engine_tree_sha rather than
# assumed. Excluding it would trade one covering check (the digest) for
# none, and this project's own C33(d) legs already double as the version
# guard's coverage of the sibling file this trade would apply to (see the
# two doctored-superslmConfigVersion.cmake legs) -- a trade worth STATING,
# not implying. The pattern below names exactly the two files that need it,
# not "every
# generated CMake file": a fourth one, if SuperSLM ever adds it, is a new
# member to evaluate on its own merits, not something this regex covers by
# accident.
_EXCLUDED_INSTALL_NAME_RE = re.compile(r"^superslmTargets(-[A-Za-z0-9_]+)?\.cmake$|^superslmConfigVersion\.cmake$")


def derive_install_closure(build: Path, prefix: Path) -> set[Path]:
    manifest = build / "install_manifest.txt"
    if not manifest.exists():
        raise SystemExit(f"install_manifest.txt not found in {build} — did install run?")
    out = set()
    excluded = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        p = Path(line)
        try:
            p = p.resolve()
        except OSError:
            continue
        if p.suffix.lower() in _EXCLUDED_INSTALL_SUFFIXES or _EXCLUDED_INSTALL_NAME_RE.match(p.name):
            excluded.append(p)
            continue
        out.add(p)
    if excluded:
        log(f"install closure excludes {len(excluded)} platform-varying artifact(s) (not source-identity-bearing): "
            + ", ".join(str(e) for e in excluded))
    return out


def git_clean_check(clone: Path, tag: str, compile_closure: set[Path]) -> tuple[bool, list[str], dict[str, str]]:
    """The independent witness for SEMB_ENGINE_INSTALL_DIVERGED: for every
    compile-closure member that lives inside the clone, compare the blob hash
    of what is ACTUALLY on disk (what got compiled) against the blob hash git
    recorded for that path AT THE TAG. Two producers: git's own content-
    addressed object store (tamper-evident short of rewriting history) and the
    literal bytes the compiler read. A dirty_paths entry means the clone
    carried an uncommitted edit to that file when it was built.

    Also returns tag_content_sha256: for every compiled member, the SHA-256 of
    the content git records for that path AT THE TAG (`git show <tag>:<path>`
    read as raw bytes, never through the working tree) -- independent of
    whatever the clone actually contains. TE-65 F-3: a downstream configure
    recomputes this per member from the bytes on disk right now and compares
    to the RECORDED value here, rather than trusting a single 'clean' boolean
    this same producer also writes -- the fix for a defect the code review
    found (flipping clean:false to true and clearing dirty_paths defeated the
    check entirely, because nothing independently re-derived it)."""
    dirty = []
    tag_content_sha256: dict[str, str] = {}
    for p in sorted(compile_closure):
        try:
            rel = p.relative_to(clone)
        except ValueError:
            continue  # not inside the clone (e.g. a system header) — out of scope for this check
        relposix = PurePosixPath(rel.as_posix()).as_posix()
        actual = run(["git", "-C", str(clone), "hash-object", "--", relposix], capture=True, check=False)
        actual_hash = actual.stdout.strip().splitlines()[-1].strip() if actual.stdout.strip() else None
        tagged = run(["git", "-C", str(clone), "rev-parse", f"{tag}:{relposix}"], capture=True, check=False)
        tagged_hash = tagged.stdout.strip().splitlines()[-1].strip() if tagged.returncode == 0 else None
        if actual_hash is None or tagged_hash is None or actual_hash != tagged_hash:
            dirty.append(relposix)
        show = subprocess.run(
            ["git", "-C", str(clone), "show", f"{tag}:{relposix}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if show.returncode == 0:
            tag_content_sha256[relposix] = hashlib.sha256(show.stdout).hexdigest()
    return (len(dirty) == 0, dirty, tag_content_sha256)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lock", default="superslm.lock", type=Path)
    ap.add_argument("--prefix", required=True, type=Path)
    ap.add_argument("--source", default=DEFAULT_REMOTE,
                     help="git URL or local path to clone the engine from (documented option; "
                          "default is the public remote — this tool never builds a local checkout in place)")
    ap.add_argument("--workdir", default=Path("build/_engine_src_workdir"), type=Path)
    ap.add_argument("--cmake", default="cmake")
    ap.add_argument("--ninja", default="ninja")
    ap.add_argument("--generator", default="Ninja")
    ap.add_argument("--keep-workdir", action="store_true")
    ap.add_argument("--fresh-build", action="store_true",
                     help="TE-73 R-1: authorize wiping a PRE-EXISTING --workdir/build directory this "
                          "run did not create. Without it, configure_engine refuses by name "
                          "(SEMB_PIN_UNSAFE_BUILD_DIR) rather than deleting a build directory it does "
                          "not own -- point --workdir at an empty or different directory instead if "
                          "you did not mean to reuse an old one.")
    ap.add_argument("--reuse-clone", default=None, type=Path,
                     help="skip the clone step and use this existing checkout directly (test-only: "
                          "used to build C33 leg (e) from a clone that already carries an uncommitted "
                          "edit inside the compile closure)")
    ap.add_argument("--allow-dirty", action="store_true",
                     help="do not abort when the clone carries an uncommitted edit inside the compile "
                          "closure — still records clean=false in the provenance manifest so a "
                          "downstream configure refuses it (used to construct C33 leg (e) on purpose)")
    args = ap.parse_args()

    lock = parse_lock(args.lock)
    tag = lock["tag"]
    log(f"pinned tag: {tag}")

    workdir = args.workdir.resolve()
    if args.reuse_clone:
        clone = args.reuse_clone.resolve()
        log(f"reusing existing checkout at {clone} (--reuse-clone)")
        # TE-71 Q-1: this run does NOT create workdir/src on this path --
        # `clone` may not even be under `workdir` at all. Tracked so final
        # cleanup deletes only what this run actually made.
        created_src_this_run = False
    else:
        clone = clone_engine(args.source, tag, workdir)
        created_src_this_run = True
    commit = resolve_commit(clone, tag)
    log(f"resolved commit: {commit}")

    build = workdir / "build"
    configure_engine(clone, build, args.cmake, args.ninja, args.generator, fresh_build=args.fresh_build)
    build_engine_library(build, args.cmake)

    prefix = args.prefix.resolve()
    install_engine(build, args.cmake, prefix)

    compile_closure = derive_compile_closure(clone, build, args.ninja)
    install_closure = derive_install_closure(build, prefix)
    log(f"compile closure: {len(compile_closure)} files; install closure: {len(install_closure)} files")

    clean, dirty_paths, tag_content_sha256 = git_clean_check(clone, tag, compile_closure)
    if not clean:
        log(f"CLONE IS DIRTY relative to {tag} — {len(dirty_paths)} closure file(s) differ from the tag's own tree:")
        for d in dirty_paths:
            log(f"    dirty: {d}")
        if not args.allow_dirty:
            raise SystemExit(
                "refusing to produce a clean-labelled install from a dirty clone; pass --allow-dirty "
                "to install anyway with clean=false recorded (used only to construct the negative-"
                "configure leg that proves SEMB_ENGINE_INSTALL_DIVERGED fires)."
            )

    # Snapshot every compile-closure member into the prefix so a later configure
    # can recompute the digest without the clone.
    snapshot_root = prefix / "share" / "superslm-provenance" / "compiled"
    members = []
    # TE-67 N-1: every compiled member gets an ENTRY in this dict, even when
    # git has no content for that path at the tag (None) -- the prior code
    # only inserted an entry when tag_content_sha256 succeeded, so a file
    # ADDED to the clone (present in the compile closure, absent from the
    # tag) produced a members_index entry with NO tag_content_sha256 KEY AT
    # ALL, indistinguishable on the reading end from a key that was simply
    # never written for an unrelated reason. A verifier using `.get(...) is
    # not None` to decide whether to check a member treated "no key" as
    # "nothing to verify, skip" rather than "cannot be verified against the
    # tag, refuse" -- exactly the added-file leg the review reproduced with
    # no edit at all. Recording None explicitly makes the gap a value the
    # verifier must handle, not an absence it can silently pass over.
    compiled_tag_content_sha256: dict[str, str | None] = {}
    for p in sorted(compile_closure):
        try:
            rel = p.relative_to(clone)
        except ValueError:
            log(f"WARNING: compile-closure member outside the clone, skipped from provenance: {p}")
            continue
        relposix = rel.as_posix()
        content = p.read_bytes()
        dst = snapshot_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
        members.append(("compiled", relposix, content))
        compiled_tag_content_sha256[relposix] = tag_content_sha256.get(relposix)  # None if absent at the tag

    for p in sorted(install_closure):
        try:
            rel = p.relative_to(prefix)
        except ValueError:
            log(f"WARNING: install-closure member outside the prefix, skipped from provenance: {p}")
            continue
        relposix = rel.as_posix()
        if relposix.startswith("share/superslm-provenance/"):
            continue  # never digest our own provenance output
        content = p.read_bytes()
        members.append(("installed", relposix, content))

    engine_tree_sha = digest_members(members)
    log(f"engine_tree_sha: {engine_tree_sha}")

    provenance = {
        "schemaVersion": 1,
        "tag": tag,
        "commit": commit,
        "engine_tree_sha": engine_tree_sha,
        "clean": clean,
        "dirty_paths": dirty_paths,
        "member_count": len(members),
        "digest_formula": "sha256 over path-sorted entries len(path_utf8:8BE) || path || len(bytes:8BE) || bytes; "
                           "path is '<root>:<relpath-posix>' with root in {compiled, installed}",
        # The path INDEX only (no content) — lets verify_provenance.py re-read
        # each member's CURRENT bytes at configure time and recompute the
        # digest, without re-deriving the closure itself (that derivation
        # needs the engine's build graph, which no longer exists once the
        # scratch workdir is removed).
        # TE-65 F-3 / TE-67 N-1: compiled-root members ALWAYS carry the
        # tag_content_sha256 KEY (value null when git has no content for
        # that path at the tag -- an added file), computed from git's OWN
        # tag content, never from the working tree -- a downstream configure
        # re-derives dirtiness per member from this against the CURRENT
        # on-disk bytes, rather than trusting the single `clean` flag above,
        # and a member whose value is null or whose key is missing is
        # refused rather than skipped (see verify_provenance.py).
        "members_index": [
            {"root": root, "path": relpath, **(
                {"tag_content_sha256": compiled_tag_content_sha256.get(relpath)}
                if root == "compiled" else {}
            )}
            for root, relpath, _ in members
        ],
    }
    manifest_path = prefix / "share" / "superslm-provenance" / "provenance.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    log(f"wrote {manifest_path}")

    lock["commit"] = commit
    lock["tree"] = engine_tree_sha
    write_lock(args.lock, lock)
    log(f"updated {args.lock}")

    if not args.keep_workdir:
        # TE-73: build and (when this run created it) src are both already
        # recorded in _OWNED_PATHS by configure_engine() and clone_engine()
        # respectively, at the moment each was created or explicitly
        # reclaimed (--fresh-build). _remove_owned() is the one function
        # permitted to delete anything in this module, and it re-checks the
        # ledger itself -- nothing here re-derives "is this safe" from the
        # directory's own contents, which is what let TE-71's own
        # own_this_run=True bypass and the class it was patching over both
        # exist in the first place. `workdir` itself is never passed to
        # _remove_owned -- it was never recorded as owned, and is left
        # standing regardless of what it held before this run started.
        _remove_owned(build)
        if created_src_this_run:
            _remove_owned(workdir / "src")

    return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
