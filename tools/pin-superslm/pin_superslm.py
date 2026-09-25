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
  8b. (U2-3 item 13) Writes `engine_build` into provenance.json, outside
     engine_tree_sha: the compiler CMake recorded, the `toolchain`, `stdlib`
     and `dispatch` strings the product's descriptor header gives when
     preprocessed with src/matmul.cpp's own compile command, the engine's
     compile-flag record and its digest `flagsSha` (tools/compile_flags.py),
     the installed library's SHA-256, and the build record
     `sslm-build-record-v1:<sha256>` over {schema, tag, commit, clean,
     compiler, flagsSha}. Refuses SEMB_PIN_AMBIENT_COMPILER_INPUT <variable>
     when CL, _CL_ or CCC_OVERRIDE_OPTIONS is set, because they reach the
     compiler without appearing on any compile line.
  9. Updates superslm.lock's `commit=` and `tree=` fields to match what was just
     computed (the `tag=` field is the only one a person edits; this tool
     derives the other two — D-SLM3893).

USAGE
  python tools/pin-superslm/pin_superslm.py \\
      --lock superslm.lock --prefix build/_engine_install [--source <path-or-url>] \\
      [--workdir build/_engine_src] [--cmake <path>] [--ninja <path>] [--generator Ninja] \\
      [--keep-workdir] [--fresh-build] [--force-tier {sse2,avx2,avx512}]

  --force-tier: (U2-3 item 5) configure the engine with SUPERSLM_FORCE_<TIER>_MATMUL,
      delivered through CXXFLAGS so it reaches every `superslm` translation unit
      and its compile-flag record; install it to its own --prefix. Only the
      `superslm` target is built, never the engine's superslm_<tier>_forced test
      seams.

  --fresh-build: authorize wiping a PRE-EXISTING --workdir/build this run did not
      create (TE-73 R-1 / TE-75 S-4). Without it, a non-empty leftover build
      directory refuses by name (SEMB_PIN_UNSAFE_BUILD_DIR) rather than being
      silently deleted -- the ordinary way this directory is left behind is an
      earlier run raising before it reached its own cleanup step (an interrupted
      run, a failed engine build, a refused dirty clone), not misuse; pass this
      flag to reclaim it, or point --workdir at an empty or different directory
      if the leftover was not this tool's own.

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
from provenance_lib import DIGEST_FORMULA, digest_members  # noqa: E402

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


def _validate_reuse_clone(clone: Path, tag: str) -> None:
    """TE-87 (sec 4.4d's own Note, D-SLM6164/Mendeleev F3): `--reuse-clone`
    (test-only: skips the normal clone step and uses an existing checkout
    directly) used to reach `resolve_commit()`'s own `git rev-parse
    <tag>^{commit}` call for BOTH a missing directory and a present
    directory that does not carry the pinned tag, and fell through to
    `run()`'s own generic `SystemExit(f"command failed ({rc}): {cmd}")` --
    loud and non-zero-exit, but not a NAMED refusal the way every other
    failure mode in this tool is. This validates three conditions
    directly, before `resolve_commit()` ever runs, and refuses by name for
    each: a missing directory (SEMB_PIN_REUSE_CLONE_NOT_FOUND), an
    existing directory that is not a git repository at all (TE-89, TE-88
    review M-3: SEMB_PIN_REUSE_CLONE_NOT_A_REPO), and a real checkout that
    does not carry the pinned tag (SEMB_PIN_REUSE_CLONE_TAG_MISMATCH)."""
    if not clone.exists() or not clone.is_dir():
        raise SystemExit(
            f"SEMB_PIN_REUSE_CLONE_NOT_FOUND: --reuse-clone points at {clone}, which does not "
            f"exist as a directory. --reuse-clone skips the normal clone step and requires an "
            f"existing checkout already in place -- point it at a real checkout, or omit the flag "
            f"to let this tool clone one."
        )
    # TE-89 (TE-88 review M-3): `git rev-parse <tag>^{commit}` also exits
    # nonzero for "this directory is not a git repository at all," which
    # the check below used to fold into SEMB_PIN_REUSE_CLONE_TAG_MISMATCH
    # -- a real checkout that merely lacks the pinned tag, and an existing
    # directory that was never a git repository, are different conditions,
    # and the named status is what a consumer keys on (the raw git stderr
    # is included either way, but nothing forces a caller to read it).
    #
    # `git -C <clone> rev-parse --git-dir` is NOT the right probe here --
    # executed, found by the leg this fix itself pins
    # (tests/pin_superslm_reuse_clone_invalid_test.py's own
    # leg_not_a_git_repo_directory): git's own directory-discovery walks
    # UP the tree looking for an ENCLOSING repository, so it succeeds for
    # any plain, never-`git init`'d subdirectory nested inside one -- which
    # `<clone>` always is here, since --reuse-clone's own scratch
    # directories live under this project's own checkout. A direct check
    # for `<clone>/.git` (a normal, non-bare `git clone` always creates one
    # at its own root, whether a directory or -- for a worktree -- a file)
    # tests `<clone>` ITSELF rather than any ancestor.
    if not (clone / ".git").exists():
        raise SystemExit(
            f"SEMB_PIN_REUSE_CLONE_NOT_A_REPO: --reuse-clone points at {clone}, which exists but "
            f"has no .git of its own (not a git repository) -- --reuse-clone requires an existing "
            f"checkout, not merely an existing directory."
        )
    proc = subprocess.run(["git", "-C", str(clone), "rev-parse", f"{tag}^{{commit}}"],
                           capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"SEMB_PIN_REUSE_CLONE_TAG_MISMATCH: --reuse-clone points at {clone}, but the pinned "
            f"tag '{tag}' does not resolve to a commit there (git: {proc.stderr.strip()}). "
            f"--reuse-clone requires an existing checkout that already carries the pinned tag, "
            f"whether as the current branch tip or a local tag pointing at it."
        )


def configure_engine(clone: Path, build: Path, cmake: str, ninja: str, generator: str,
                      fresh_build: bool = False, force_tier: str | None = None) -> None:
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
    # U2-1 (F40): off Windows the engine is linked into the product's shared
    # library, which a static archive of non-position-independent objects
    # cannot enter (GCC's `ld` refuses the link, "recompile with -fPIC").
    # CMAKE_POSITION_INDEPENDENT_CODE puts -fPIC on the engine's own compile
    # lines, where the flag record reads it, and -- unlike a CMAKE_CXX_FLAGS
    # on this command line -- leaves the CXXFLAGS channel untouched. A PE/COFF
    # DLL needs no such flag, so Windows pins are unchanged.
    if os.name != "nt":
        cmd.append("-DCMAKE_POSITION_INDEPENDENT_CODE=ON")
    if generator == "Ninja" and ninja:
        cmd.append(f"-DCMAKE_MAKE_PROGRAM={ninja}")
    # U2-3 item 5: --force-tier delivers SUPERSLM_FORCE_<T>_MATMUL through the
    # engine build's CMAKE_CXX_FLAGS, the one channel that reaches every
    # `superslm` translation unit without editing the engine. It is passed as
    # CXXFLAGS for this configure, which CMake combines with the toolchain's
    # own default flags to initialize CMAKE_CXX_FLAGS (a -DCMAKE_CXX_FLAGS on
    # the command line would replace those defaults, e.g. MSVC's /EHsc). The
    # macro therefore appears on every recorded compile line, where the
    # engine's flag record reads it.
    env = None
    if force_tier:
        env = dict(os.environ)
        macro = f"-DSUPERSLM_FORCE_{force_tier.upper()}_MATMUL"
        env["CXXFLAGS"] = (env.get("CXXFLAGS", "") + " " + macro).strip()
    run(cmd, env=env)


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
            # TE-75 S-4: markers=() (configure_engine's own call, for
            # --workdir/build -- no legitimate marker exists for "an old
            # CMake build directory" the way ".git" or
            # "share/superslm-provenance" do for the other two callers)
            # used to fall into the marker-list message below, which named
            # an EMPTY parenthetical and prescribed "one this tool already
            # owns" -- unreachable advice, since markers=() means no marker
            # can ever qualify. This is also not a misuse path: every
            # SEMB_PIN_* refusal in this tool raises SystemExit before the
            # cleanup block runs, so an interrupted run, a failed engine
            # build, or the dirty-clone refusal all leave workdir/build
            # populated, and the NEXT default run -- which would have
            # succeeded before this guard existed -- meets this message.
            if not markers:
                raise SystemExit(
                    f"{error_code}: refusing to wipe {what} at {resolved} — it already exists "
                    f"and is non-empty. This is most often this tool's own leftover build state "
                    f"from an earlier run that did not reach its own cleanup step (an interrupted "
                    f"run, a failed engine build, or a refused dirty clone all raise before that "
                    f"point) rather than misuse -- pass --fresh-build to authorize wiping it, or "
                    f"point --workdir at an empty or different directory if this was not this "
                    f"tool's own output."
                )
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
# TE-69 P-10, corrected TE-71 Q-5, corrected again TE-73 R-4: this is a
# MEMBER LIST, not a class exclusion, and is named as one -- the exact
# shape F-7's own finding was about. There is a THIRD generated CMake file
# in the install: superslmConfig.cmake. Read at source, it is deliberately
# NOT excluded and does not belong in this list: its own mechanism
# (CMakePackageConfigHelpers' @PACKAGE_INIT@ block) resolves the install
# prefix RELATIVELY from its own location via
# get_filename_component(PACKAGE_PREFIX_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../" ABSOLUTE)
# -- carrying no absolute path, no toolchain name and no platform-specific
# literal. [Q-5: P-10's own comment here previously attributed a FOUR-call
# _IMPORT_PREFIX chain to this file; that chain is real, but it lives in
# superslmTargets.cmake (get_filename_component(_IMPORT_PREFIX ...), four
# calls, one of the two files this pattern DOES exclude, read at source) --
# a different file from the one this paragraph is about. superslmConfig.cmake
# itself carries zero _IMPORT_PREFIX calls.] [R-4: this paragraph then
# stated the PACKAGE_PREFIX_DIR call above appears "via ONE call" -- read at
# source in the installed prefix, it appears TWICE (lines 6 and 53), because
# the engine's own cmake/superslmConfig.cmake.in at v1.3.0 contains a
# literal "@PACKAGE_INIT@" inside a COMMENT at its own line 24, and
# configure_package_config_file() substitutes every occurrence of that
# token, comment or not, splicing the whole init block in twice. Engine-
# side, not fixable here (filed as an engine finding, not this project's
# code); the count is dropped from this comment rather than corrected a
# third time, since the paragraph's conclusion never depended on it.] It is
# genuinely portable, checked at every repin by being left in
# engine_tree_sha rather than assumed. Excluding it would trade one
# covering check (the digest) for none, and this project's own C33(d) legs
# already double as the version guard's coverage of the sibling file this
# trade would apply to (see the two doctored-superslmConfigVersion.cmake
# legs) -- a trade worth STATING, not implying. The pattern below names
# exactly the two files that need it, not "every
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


# ---------------------------------------------------------------------------
# U2-3 items 5 and 13: the engine-build record.
# ---------------------------------------------------------------------------
FORCE_TIERS = ("sse2", "avx2", "avx512")

# Variables that change what the compiler does without appearing on any
# compile line (plan sec 2.4), so no flag record can see them.
AMBIENT_COMPILER_INPUTS = ("CL", "_CL_", "CCC_OVERRIDE_OPTIONS")

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import compile_flags  # noqa: E402

DESCRIPTOR_HEADER_DIR = REPO_ROOT / "src" / "superembedder"
KERNEL_TU = "src/matmul.cpp"
_PROBE_TEXT = (
    '#include "semb_build_descriptor.h"\n'
    "SEMB_PROBE_TOOLCHAIN SEMB_DESCRIPTOR_TOOLCHAIN\n"
    "SEMB_PROBE_STDLIB SEMB_DESCRIPTOR_STDLIB\n"
    "SEMB_PROBE_DISPATCH SEMB_DESCRIPTOR_ENGINE_DISPATCH\n"
)


def refuse_ambient_compiler_input() -> None:
    for name in AMBIENT_COMPILER_INPUTS:
        if name in os.environ:
            raise SystemExit(
                f"SEMB_PIN_AMBIENT_COMPILER_INPUT {name}: this variable reaches the compiler without appearing "
                f"on any compile line, so the engine's flag record could not describe the code it built. "
                f"Unset it and pin again."
            )


def compiler_of(build: Path) -> dict:
    """CMAKE_CXX_COMPILER_ID, _VERSION and _FRONTEND_VARIANT as the engine build's own CMake recorded them."""
    found = sorted(build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"))
    if not found:
        raise SystemExit(f"SEMB_PIN_COMPILER_UNREADABLE: no CMakeCXXCompiler.cmake under {build / 'CMakeFiles'}")
    text = found[-1].read_text(encoding="utf-8")

    def field(name: str) -> str:
        m = re.search(rf'set\({name} "([^"]*)"\)', text)
        return m.group(1) if m else ""

    compiler = {"id": field("CMAKE_CXX_COMPILER_ID"), "version": field("CMAKE_CXX_COMPILER_VERSION"),
                "frontend": field("CMAKE_CXX_COMPILER_FRONTEND_VARIANT")}
    if not compiler["id"] or not compiler["version"]:
        raise SystemExit(f"SEMB_PIN_COMPILER_UNREADABLE: {found[-1]} carries no compiler id/version")
    return compiler


def _compile_entries(build: Path) -> list[dict]:
    path = build / "compile_commands.json"
    if not path.is_file():
        raise SystemExit(f"SEMB_PIN_COMPILE_COMMANDS_MISSING: {path} was not written by the engine's configure")
    return json.loads(path.read_text(encoding="utf-8"))


def _literals(text: str) -> str:
    """Concatenates the adjacent string literals the preprocessor left on one line."""
    return "".join(bytes(m, "utf-8").decode("unicode_escape") for m in re.findall(r'"((?:[^"\\]|\\.)*)"', text))


def _kernel_entry(clone: Path, build: Path) -> dict:
    """src/matmul.cpp's own recorded compile command in the engine build (the `superslm` target's)."""
    kernel = (clone / KERNEL_TU).resolve()
    for e in _compile_entries(build):
        if compile_flags._target_of(e) == "superslm" and Path(e["file"]).resolve() == kernel:
            return e
    raise SystemExit(f"SEMB_PIN_KERNEL_COMMAND_MISSING: no compile command for {KERNEL_TU} in the engine build")


def probe_descriptor(clone: Path, build: Path, family: str, windows: bool) -> dict:
    """toolchain, stdlib and dispatch as the engine's kernel TU is compiled: the product's descriptor header,
    preprocessed with src/matmul.cpp's own recorded compile command, in this process's environment (the one
    the engine was just built in)."""
    entry = _kernel_entry(clone, build)
    argv = compile_flags.argv_of(entry, windows)
    probe = build / "semb_descriptor_probe.cpp"
    probe.write_text(_PROBE_TEXT, encoding="utf-8", newline="\n")
    msvc_style = family in ("msvc", "clangcl")
    out, k = [argv[0]], 1
    while k < len(argv):
        a = argv[k]
        if a in ("-o", "-MF", "-MT", "-MQ"):
            k += 2
            continue
        k += 1
        if a in ("-c", "/c", "-MD", "-MMD", "-MP", "/showIncludes", "-showIncludes") or \
                compile_flags.OUTPUT_JOINED.match(a):
            continue
        if Path(a).name == Path(entry["file"]).name and a.replace("\\", "/").endswith(KERNEL_TU):
            continue
        out.append(a)
    out += (["/E", f"/I{DESCRIPTOR_HEADER_DIR}"] if msvc_style else ["-E", f"-I{DESCRIPTOR_HEADER_DIR}"])
    out.append(str(probe))
    proc = subprocess.run(out, cwd=entry.get("directory") or str(build), capture_output=True, text=True,
                          errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"SEMB_PIN_DESCRIPTOR_PROBE_FAILED: preprocessing the descriptor probe with {KERNEL_TU}'s "
                         f"compile command exited {proc.returncode}:\n{proc.stderr[-2000:]}")
    fields = {}
    for key in ("TOOLCHAIN", "STDLIB", "DISPATCH"):
        m = re.search(rf"^\s*SEMB_PROBE_{key}\s+(.*)$", proc.stdout, re.M)
        if not m:
            raise SystemExit(f"SEMB_PIN_DESCRIPTOR_PROBE_FAILED: the preprocessed probe carries no SEMB_PROBE_{key}")
        fields[key.lower()] = _literals(m.group(1))
    return fields


def installed_library(build: Path, prefix: Path) -> Path:
    for line in (build / "install_manifest.txt").read_text(encoding="utf-8").splitlines():
        p = Path(line.strip())
        if p.suffix.lower() in (".a", ".lib") and p.stem.lower() in ("superslm", "libsuperslm"):
            return p
    raise SystemExit(f"SEMB_PIN_LIBRARY_MISSING: the install manifest names no superslm library under {prefix}")


def build_record(tag: str, commit: str, clean: bool, compiler: dict, flags_sha: str) -> str:
    """sslm-build-record-v1: SHA-256 of the canonical JSON of {schema, tag, commit, clean, compiler, flagsSha}.
    Every input is content, so one configuration gives one record from any directory (plan U2-3 item 14)."""
    doc = {"schema": 1, "tag": tag, "commit": commit, "clean": clean,
           "compiler": {"id": compiler["id"], "version": compiler["version"], "frontend": compiler["frontend"]},
           "flagsSha": flags_sha}
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sslm-build-record-v1:" + hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# U2-3 item 14: the linked engine identifies its own build. No engine tag defines sslm_build_identity, so
# after install the tool compiles the verb's one text (src/superembedder/engine_identity/build_identity.cpp)
# with src/matmul.cpp's own recorded compile command, in this process's environment (the one the engine was
# just built in), with the build record on its include path, and appends the object to the installed
# library. It appends only when the library does not define the symbol already. engine_tree_sha excludes
# libraries, so appending moves no tree digest; librarySha256 is taken after the append.
# ---------------------------------------------------------------------------
IDENTITY_SYMBOL = "sslm_build_identity"
IDENTITY_DIR = REPO_ROOT / "src" / "superembedder" / "engine_identity"
IDENTITY_TEXT = IDENTITY_DIR / "build_identity.cpp"


def archive_symbols(library: Path) -> set[str]:
    """The external symbols an ar archive's own symbol index names. Reads the index member directly, so one
    rule serves every archiver: the System V / GNU `/` member (and `/SYM64/`), which is also the first linker
    member of a Microsoft COFF .lib (lib.exe and llvm-lib), and the BSD `__.SYMDEF` member."""
    data = library.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        raise SystemExit(f"SEMB_PIN_LIBRARY_UNREADABLE: {library} is not an ar archive")
    pos, names, seen_index = 8, set(), False
    while pos + 60 <= len(data):
        header = data[pos:pos + 60]
        name = header[:16].decode("latin-1").rstrip()
        size = int(header[48:58].decode("latin-1").strip() or 0)
        body = data[pos + 60:pos + 60 + size]
        if name == "/" and not seen_index:
            # First linker member: u32 BE count, count u32 BE offsets, then count NUL-terminated names.
            count = int.from_bytes(body[:4], "big")
            names.update(n.decode("latin-1") for n in body[4 + 4 * count:].split(b"\0")[:count])
            seen_index = True
        elif name == "/SYM64/" and not seen_index:
            count = int.from_bytes(body[:8], "big")
            names.update(n.decode("latin-1") for n in body[8 + 8 * count:].split(b"\0")[:count])
            seen_index = True
        elif name.startswith("#1/") or name.startswith("__.SYMDEF"):
            extended = int(name[3:]) if name.startswith("#1/") else 0
            real = body[:extended].rstrip(b"\0").decode("latin-1") if extended else name
            if real.startswith("__.SYMDEF") and not seen_index:
                rest = body[extended:]
                ranlib_bytes = int.from_bytes(rest[:4], "little")
                entries = rest[4:4 + ranlib_bytes]
                strtab_at = 4 + ranlib_bytes
                strtab_size = int.from_bytes(rest[strtab_at:strtab_at + 4], "little")
                strtab = rest[strtab_at + 4:strtab_at + 4 + strtab_size]
                for k in range(0, len(entries) - 7, 8):
                    strx = int.from_bytes(entries[k:k + 4], "little")
                    names.add(strtab[strx:strtab.index(b"\0", strx)].decode("latin-1"))
                seen_index = True
        pos += 60 + size
        pos += pos & 1
    if not seen_index:
        raise SystemExit(f"SEMB_PIN_LIBRARY_INDEX_MISSING: {library} carries no archive symbol index")
    return names


def library_defines(library: Path, symbol: str) -> bool:
    names = archive_symbols(library)
    return symbol in names or ("_" + symbol) in names  # Mach-O prefixes C names with an underscore


def _cache_value(build: Path, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}:[A-Z]+=(.*)$",
                  (build / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1).strip() if m else ""


def identity_compile_command(entry: dict, family: str, windows: bool, work: Path, obj: Path) -> list[str]:
    """src/matmul.cpp's recorded command with its source replaced by the verb's text, its outputs by the
    identity object's, and the work directory (which holds superslm_build_record.inc) added to the include
    path. Dependency-file and diagnostic-output arguments are dropped: they write files and change no code
    (plan U2-3 item 13 step 2b)."""
    argv = compile_flags.argv_of(entry, windows)
    msvc_style = family in ("msvc", "clangcl")
    source_name = Path(entry["file"]).name
    out, k, had_fd, had_c, had_dashdash = [argv[0]], 1, False, False, False
    while k < len(argv):
        a = argv[k]
        k += 1
        if msvc_style:
            # On the MSVC frontend -MD/-MT/-MDd/-MTd select the C runtime: they are code options and stay.
            if a in ("/showIncludes", "-showIncludes"):
                continue
            if a == "--":  # clang-cl: every later argument is an input file
                had_dashdash = True
                continue
        else:
            if a in ("-o", "-MF", "-MT", "-MQ"):
                k += 1
                continue
            if a in ("-MD", "-MMD", "-MP"):
                continue
        if compile_flags.OUTPUT_JOINED.match(a):
            had_fd = had_fd or a[1:3].lower() == "fd"
            continue
        if Path(a).name == source_name and a.replace("\\", "/").endswith(KERNEL_TU):
            continue
        had_c = had_c or a in ("-c", "/c")
        out.append(a)
    if not had_c:
        out.append("/c" if msvc_style else "-c")
    if msvc_style:
        out.append(f"/I{work}")
        out.append(f"/Fo{obj}")
        if had_fd:
            out.append(f"/Fd{work / 'sslm_build_identity.pdb'}")
        if had_dashdash:
            out.append("--")
    else:
        out += [f"-I{work}", "-o", str(obj)]
    out.append(str(IDENTITY_TEXT))
    return out


def append_build_identity(clone: Path, build: Path, library: Path, family: str, windows: bool,
                          record: str) -> bool:
    """Compiles the verb with the kernel TU's command and appends it to `library`, when `library` does not
    define it. Returns True when it appended. Refuses when the appended object does not then name the
    symbol in the library's index."""
    if library_defines(library, IDENTITY_SYMBOL):
        log(f"{library.name} defines {IDENTITY_SYMBOL} itself; the pin tool appends no identity object")
        return False
    work = build / "semb_build_identity"
    if work.exists():
        _own(work)  # inside the build directory configure_engine() just claimed for this run
        _remove_owned(work)
    work.mkdir(parents=True)
    (work / "superslm_build_record.inc").write_text(f'#define SUPERSLM_BUILD_RECORD "{record}"\n',
                                                   encoding="utf-8", newline="\n")
    msvc_style = family in ("msvc", "clangcl")
    obj = work / ("sslm_build_identity.obj" if msvc_style else "sslm_build_identity.o")
    entry = _kernel_entry(clone, build)
    cmd = identity_compile_command(entry, family, windows, work, obj)
    log("identity compile: " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=entry.get("directory") or str(build), capture_output=True, text=True,
                          errors="replace")
    if proc.returncode != 0 or not obj.is_file():
        raise SystemExit(f"SEMB_PIN_IDENTITY_COMPILE_FAILED: compiling {IDENTITY_TEXT.name} with {KERNEL_TU}'s "
                         f"compile command exited {proc.returncode}:\n{(proc.stdout + proc.stderr)[-2000:]}")
    archiver = _cache_value(build, "CMAKE_AR")
    if msvc_style:
        # lib.exe (MSVC) or llvm-lib (clang-cl): /OUT: rewrites the archive with the object added.
        archiver = archiver or ("lib.exe" if family == "msvc" else "llvm-lib.exe")
        staged = library.with_name(library.stem + ".identity" + library.suffix)
        cmd = [archiver, "/NOLOGO", f"/OUT:{staged}", str(library), str(obj)]
    else:
        archiver = archiver or "ar"
        staged = None
        cmd = [archiver, "rs", str(library), str(obj)]
    log("identity append: " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"SEMB_PIN_IDENTITY_APPEND_FAILED: {' '.join(cmd)} exited {proc.returncode}:\n"
                         f"{(proc.stdout + proc.stderr)[-2000:]}")
    if staged is not None:
        os.replace(staged, library)
    if not library_defines(library, IDENTITY_SYMBOL):
        raise SystemExit(f"SEMB_PIN_IDENTITY_APPEND_FAILED: {library} does not define {IDENTITY_SYMBOL} after "
                         f"the append")
    log(f"appended {obj.name} to {library}: {IDENTITY_SYMBOL} carries {record}")
    return True


def engine_build_record(clone: Path, build: Path, prefix: Path, tag: str, commit: str, clean: bool,
                        library: Path) -> dict:
    """provenance.json's engine_build object (plan U2-3 item 13). Outside engine_tree_sha, which stays a
    digest of source."""
    compiler = compiler_of(build)
    family = compile_flags.family_of(compiler["id"], compiler["frontend"])
    windows = os.name == "nt"
    probe = probe_descriptor(clone, build, family, windows)
    rec, residual = compile_flags.record(_compile_entries(build), family,
                                         [(str(clone), "<src>"), (str(build), "<build>")],
                                         ["superslm"], [], windows)
    if not rec:
        raise SystemExit("SEMB_PIN_FLAGS_UNRECORDED: the engine build's compile_commands.json names no superslm TU")
    for r in residual:
        log(f"SEMB_COMPILE_FLAGS_LOCATION {r}")
    flags_sha = compile_flags.digest(rec)
    record = build_record(tag, commit, clean, compiler, flags_sha)
    append_build_identity(clone, build, library, family, windows, record)
    return {
        "compiler": compiler,
        "toolchain": probe["toolchain"],
        "stdlib": probe["stdlib"],
        "dispatch": probe["dispatch"],
        "flags": {"family": family, "record": rec, "residual": residual},
        "flagsSha": flags_sha,
        "librarySha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "buildRecord": record,
    }


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
    ap.add_argument("--force-tier", choices=FORCE_TIERS, default=None,
                     help="U2-3 item 5: configure the engine with SUPERSLM_FORCE_<TIER>_MATMUL, so its kernels "
                          "run one tier on every host. Install it to its own --prefix; provenance records the "
                          "tier its kernel compile reports (engine_build.dispatch), and an auto install "
                          "records 'auto'.")
    ap.add_argument("--allow-dirty", action="store_true",
                     help="do not abort when the clone carries an uncommitted edit inside the compile "
                          "closure — still records clean=false in the provenance manifest so a "
                          "downstream configure refuses it (used to construct C33 leg (e) on purpose)")
    args = ap.parse_args()

    refuse_ambient_compiler_input()

    lock = parse_lock(args.lock)
    tag = lock["tag"]
    log(f"pinned tag: {tag}")

    workdir = args.workdir.resolve()
    if args.reuse_clone:
        clone = args.reuse_clone.resolve()
        _validate_reuse_clone(clone, tag)
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
    configure_engine(clone, build, args.cmake, args.ninja, args.generator, fresh_build=args.fresh_build,
                     force_tier=args.force_tier)
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

    engine_build = engine_build_record(clone, build, prefix, tag, commit, clean, installed_library(build, prefix))
    log(f"engine_build: toolchain={engine_build['toolchain']!r} stdlib={engine_build['stdlib']!r} "
        f"dispatch={engine_build['dispatch']} flagsSha={engine_build['flagsSha']}")
    log(f"engine_build.buildRecord: {engine_build['buildRecord']}")
    if args.force_tier and engine_build["dispatch"] != args.force_tier:
        raise SystemExit(
            f"SEMB_PIN_FORCED_TIER_NOT_REPORTED: --force-tier {args.force_tier} was requested, but the engine's "
            f"kernel compile reports dispatch '{engine_build['dispatch']}'."
        )

    provenance = {
        "schemaVersion": 1,
        "engine_build": engine_build,
        "tag": tag,
        "commit": commit,
        "engine_tree_sha": engine_tree_sha,
        "clean": clean,
        "dirty_paths": dirty_paths,
        "member_count": len(members),
        "digest_formula": DIGEST_FORMULA,
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


if __name__ == "__main__":
    raise SystemExit(main())
