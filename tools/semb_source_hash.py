#!/usr/bin/env python3
"""tools/semb_source_hash.py — computes semb_source_sha (Claude/Plans/
SuperEmbedder_Plan.md Sec4.4, Sec8 C34), the digest over every file the
compiler reads to build the `superembedder` library target — its
translation units and their transitive include closure — and verifies it
two ways:

  configure  — compute the digest from a PREPROCESSOR-RESOLVED closure: for
               each declared source, the real compiler (the one CMake
               resolved) is invoked in preprocess/syntax-check-only mode
               with the target's real include directories and standard, and
               its own reported include list is the covered set. This is
               not a directory glob: a public header nothing includes is
               correctly absent, and a private header beside a source that
               source #includes is correctly present, because both are
               decided by the same preprocessor that will actually compile
               the target, not by which directory a file happens to sit in.
               Also asserts each declared SOURCE is a member of its own
               resolved closure (Sec4.4's stated subset property).
  verify     — re-derive the REAL compiled closure from Ninja's own
               dependency database (tools/pin-superslm/pin_superslm.py's
               engine-side technique) and recompute the digest from THAT,
               then compare to the configure-time value recorded in the
               sidecar JSON. Used as a POST-BUILD step; a genuine
               discrepancy is SEMB_SOURCE_SET_DRIFT. Because configure-time
               is now itself derived from real preprocessing rather than an
               approximation, the two readings are expected to agree in the
               ordinary case, and a mismatch is evidence of actual drift
               (e.g. a source recompiled outside the tracked build graph)
               rather than an artifact of two different discovery methods.

Both subcommands share the digest formula in provenance_lib.digest_members so
the two readings cannot drift apart independently of the real inputs.

TE-89 (TE-88 review S-3, S-4): `verify`'s own disagreement branch prints a
caller-supplied named status (`--status-name`, default SEMB_SOURCE_SET_DRIFT)
as both a JSON field and a bare grep-able line -- sec 4.4d requires the drift
to fail "by name," and a JSON field alone is not one. On disagreement it also
deletes the target's own real build output (resolved from the same `ninja -t
query` this subcommand already runs) so a drifted artifact does not survive a
failed post-build re-verification for a later `ctest` re-run, manual
invocation, or copy-out step to pick up.

FIX ROUND (TE-65, F-1): the prior `configure` computed its covered set as
`SOURCES union rglob(HEADER_ROOTS)` and demanded byte-for-byte agreement with
the real compiled closure at verify time. That is not what Sec4.4 specifies
("the covered set is the compiler's") and it failed in both directions on a
correct tree: a public header nothing includes was wrongly counted in (the
glob does not know it is unused), and a private header beside a source that
source DOES include was wrongly left out (the header lived outside every
globbed root). Both are executed in the TE-65 fix log's red-then-green
section, reproducing the reviewer's own two constructions.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pin-superslm"))
from provenance_lib import digest_members  # noqa: E402

_INCLUDE_NOTE_RE = re.compile(r"^\s*Note:\s+including file:\s*(.+?)\s*$")


def _msvc_closure(compiler: str, source: Path, include_dirs: list[str], std: str) -> list[Path]:
    """Invoke MSVC in syntax-check-only mode (/Zs -- no codegen, still fully
    preprocesses and parses) with /showIncludes, and return every header path
    it names. /showIncludes writes 'Note: including file:  <path>' lines
    (indentation encodes nesting depth, ignored here -- every depth is part
    of the transitive closure)."""
    cmd = [compiler, "/nologo", "/c", "/Zs", "/showIncludes", f"/std:{std}", "/EHsc", "/W0"]
    for d in include_dirs:
        cmd.append(f"/I{d}")
    cmd.append(str(source))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(source.parent))
    headers = []
    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        m = _INCLUDE_NOTE_RE.match(line)
        if m:
            headers.append(Path(m.group(1)))
    if proc.returncode != 0:
        # TE-67 N-5: raising only when BOTH the compiler failed AND zero
        # headers were parsed let a failure partway through a translation
        # unit (some /showIncludes lines already emitted, then a fatal
        # error) fall through with a TRUNCATED closure silently accepted as
        # complete. Any nonzero exit means this call's own output cannot be
        # trusted, whether or not it produced partial output first.
        raise SystemExit(
            f"SEMB_SOURCE_PREPROCESS_FAILED: {compiler} could not preprocess {source} "
            f"(exit {proc.returncode}). stdout/stderr:\n{proc.stdout}\n{proc.stderr}"
        )
    return headers


def _gcc_clang_closure(compiler: str, source: Path, include_dirs: list[str], std: str) -> list[Path]:
    """`-M` emits a Makefile dependency rule listing the source and every
    header the preprocessor resolved for it; strip the 'target:' prefix and
    line-continuation backslashes."""
    cmd = [compiler, "-M", f"-std={std}"]
    for d in include_dirs:
        cmd.append(f"-I{d}")
    cmd.append(str(source))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(source.parent))
    if proc.returncode != 0:
        raise SystemExit(
            f"SEMB_SOURCE_PREPROCESS_FAILED: {compiler} could not preprocess {source} "
            f"(exit {proc.returncode}). stderr:\n{proc.stderr}"
        )
    text = proc.stdout.replace("\\\n", " ")
    parts = text.split(":", 1)
    if len(parts) != 2:
        return []
    tokens = parts[1].split()
    return [Path(t) for t in tokens]


def _resolve_closure(compiler_id: str, compiler: str, source: Path, include_dirs: list[str], std: str,
                      force_empty: bool = False) -> list[Path]:
    # TE-69 P-3, corrected TE-71 Q-6: force_empty is a test-only escape
    # hatch (never set in normal use) that makes this function return an
    # empty closure regardless of what the real compiler resolves --
    # letting N-6's own subset assertion be driven to its must-reject
    # through a REAL `cmake -S -B` configure (a permanent matrix leg) rather
    # than only a standalone Python-level monkeypatch, which is how N-6 was
    # verified in TE-67 and again in TE-69 but never wired in.
    #
    # Q-6: this used to be an environment variable
    # (SEMB_TEST_FORCE_EMPTY_CLOSURE), read via os.environ.get -- claimed to
    # match SEMB_TEST_SKIP_FP_DIRECTIVE's pattern in cmake/BuildFlags.cmake,
    # but did not, on the two axes that make that hatch safe:
    # SEMB_TEST_SKIP_FP_DIRECTIVE is a `-D` CACHE VARIABLE, so it lands in
    # CMakeCache.txt and stays readable in the build directory forever, and
    # its active branch prints message(STATUS "SEMB TEST: ..."). The old
    # env-var hook was ambient process state, inherited by every child
    # process, announced nowhere, and recorded in no build artifact -- a
    # configure run under it was indistinguishable afterward from one that
    # was not. Now a genuine CLI flag (cmd_configure's --force-empty-closure
    # below), fed from a real CMake cache variable
    # (cmake/SourceProvenance.cmake's own SEMB_TEST_FORCE_EMPTY_CLOSURE,
    # which prints the identical message(STATUS ...) shape
    # SEMB_TEST_SKIP_FP_DIRECTIVE does) -- so a configure run under this
    # hatch now IS distinguishable afterward, from CMakeCache.txt and from
    # the configure log, exactly as the sibling hatch is.
    if force_empty:
        return []
    if compiler_id == "MSVC":
        return _msvc_closure(compiler, source, include_dirs, std)
    return _gcc_clang_closure(compiler, source, include_dirs, std)


def cmd_configure(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    missing = [s for s in args.source if not (root / s).exists()]
    if missing:
        print(json.dumps({"error": "SEMB_SOURCE_FILE_MISSING", "missing": missing}))
        return 1

    covered: set[Path] = set()
    per_source_resolver_output: dict[str, set[Path]] = {}
    per_source_text: dict[str, str] = {}
    for s in args.source:
        src_path = (root / s).resolve()
        closure = _resolve_closure(args.compiler_id, args.compiler, src_path, args.include_dir, args.std,
                                    force_empty=args.force_empty_closure)
        resolved = set()
        for h in closure:
            try:
                resolved.add(h.resolve())
            except OSError:
                continue
        # TE-67 N-6, first half: the resolver's OWN raw output is kept
        # separate from the covered set that gets digested. The prior code
        # added src_path to `resolved` unconditionally BEFORE the subset
        # assertion below tested it, so the check tested a set it had just
        # inserted the source into -- unable to fail on any input.
        per_source_resolver_output[s] = resolved
        try:
            per_source_text[s] = src_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            per_source_text[s] = ""
        covered |= resolved
        covered.add(src_path)  # the source itself is always digested

    # TE-67 N-6, second half: what this assertion tests is corrected, not
    # only how it is wired. MSVC's own /showIncludes NEVER lists the source
    # file being compiled -- only the headers it pulls in -- so "the source
    # path is a member of the resolver's raw output" is false on every
    # correct MSVC run, not only a broken one; that framing cannot be the
    # check. What Sec4.4's subset property can mean, checkably: a source
    # whose own text visibly names at least one #include must not come back
    # from a real, zero-exit compiler run with an EMPTY closure -- two
    # independent producers (the compiler's own preprocessor, and a plain
    # text scan of the source neither producer wrote) disagreeing is real
    # signal, not a re-statement of one producer's output. Reproduced: a
    # resolver hardcoded to return [] against this project's real sources
    # (which do have #include lines) is caught; a genuinely header-free
    # source with an empty resolver result is accepted, because both
    # producers agree there is nothing to find.
    _include_re = re.compile(r'^\s*#\s*include\b', re.MULTILINE)
    for s, resolver_output in per_source_resolver_output.items():
        text_says_includes = bool(_include_re.search(per_source_text.get(s, "")))
        if text_says_includes and not resolver_output:
            print(json.dumps({
                "error": "SEMB_SOURCE_NOT_IN_OWN_CLOSURE",
                "source": s,
                "reason": "source text contains #include directives but the compiler's own resolved "
                          "closure for it is empty",
            }))
            return 1

    # TE-67 N-8: a file under the build directory used to be classified by
    # whether CMAKE_BINARY_DIR happened to be NESTED inside the source root
    # -- in scope and digested when -B pointed inside root (this project's
    # own documented "-B build/semb"), silently excluded when -B pointed
    # anywhere else, for byte-identical source and an identical configure-
    # time digest either way. Build-directory content (generated headers
    # included) is now excluded from the covered set UNCONDITIONALLY, by
    # checking against build_dir before the root-relative classification,
    # so membership no longer depends on where the caller happened to point
    # -B. No source under `root` this project ships today lives under
    # build_dir, so this narrows nothing real; it removes the layout
    # dependence the reviewer's X-5 measured.
    build_dir = Path(args.build_dir).resolve() if getattr(args, "build_dir", None) else None

    members = []
    file_list = []
    out_of_root = []
    for p in sorted(covered):
        if build_dir is not None:
            try:
                p.relative_to(build_dir)
                out_of_root.append(str(p))  # a build-directory file, excluded regardless of -B's placement
                continue
            except ValueError:
                pass
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            out_of_root.append(str(p))
            continue
        members.append(("source", rel, p.read_bytes()))
        file_list.append(rel)
    # TE-65 F-8: SEMB_ENGINE_PATH is recorded in the sidecar below for the
    # separate SEMB_ENGINE_PATH_CHANGED cache-variable check
    # (cmake/SourceProvenance.cmake leg (c)), but is NOT fed into the digest
    # itself. semb_source_sha is meant to be as path-invariant as
    # engine_tree_sha (Sec4.4: "repository-relative forward-slash paths so
    # the digest is platform-invariant") -- identical source at a different
    # engine install path used to yield a different digest, which the two
    # digests disagreed about whether a local path is part of an identity.

    digest = digest_members(members)

    header = (
        "// Generated by tools/semb_source_hash.py at configure time. Do not edit.\n"
        "#pragma once\n"
        f'#define SEMB_SOURCE_SHA "{digest}"\n'
    )
    Path(args.out_header).write_text(header, encoding="utf-8", newline="\n")

    sidecar = {
        "semb_source_sha": digest,
        "engine_path": args.engine_path,
        "covered_files": file_list,
        "out_of_root_files_excluded": out_of_root,
    }
    Path(args.out_json).write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps({"semb_source_sha": digest, "covered_count": len(file_list)}))
    return 0


def _ninja_query(build: Path, ninja: str, target: str) -> str:
    proc = subprocess.run([ninja, "-t", "query", target], cwd=build, capture_output=True, text=True)
    return proc.stdout


def _parse_query_inputs(text: str) -> list[str]:
    # TE-87 (sec 8 C31(i)): `ninja -t query` marks an IMPLICIT input with a
    # leading "| " on the same line (e.g. "| superembedder.lib" for a link
    # step's linked libraries) and an ORDER-ONLY input with "|| " -- proven
    # absent from this project's own STATIC-LIBRARY archive-step queries
    # (the only shape this function was exercised against before this
    # target), and present the moment a target that LINKS OTHER LIBRARIES
    # (an executable, semb_witness) is queried the same way. An order-only
    # input is not a real content dependency and stays skipped; an
    # IMPLICIT input is a genuine input and is kept, with the marker
    # stripped so the caller sees the real path rather than "| <path>".
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
            if item.startswith("| "):
                item = item[2:].strip()
            out.append(item)
    return out


def _ninja_deps(build: Path, ninja: str, obj: str) -> list[str]:
    proc = subprocess.run([ninja, "-t", "deps", obj], cwd=build, capture_output=True, text=True)
    # F-14 (TE-65): a missing/broken deps database must not be read as
    # "zero headers" -- that reading is indistinguishable from a genuinely
    # header-free translation unit and would silently narrow
    # semb_source_sha to the source files alone. Two failure shapes,
    # confirmed by execution against the twin engine-side function
    # (tools/pin-superslm/pin_superslm.py's ninja_deps): an unknown target
    # exits nonzero; a present-but-undeps'd target (e.g. a deleted
    # .ninja_deps) exits ZERO and prints "<obj>: deps not found" instead of
    # the normal "#deps N, ..." header -- a return-code check alone misses
    # this second shape.
    if proc.returncode != 0:
        raise SystemExit(
            f"SEMB_SOURCE_DEPS_UNAVAILABLE: 'ninja -t deps {obj}' exited {proc.returncode}; "
            f"the dependency database this closure is derived from is missing or stale. "
            f"stderr:\n{proc.stderr}"
        )
    if "deps not found" in proc.stdout:
        raise SystemExit(
            f"SEMB_SOURCE_DEPS_UNAVAILABLE: 'ninja -t deps {obj}' reports 'deps not found' (exit "
            f"0) -- the object exists but carries no recorded dependency entry, typically a "
            f"missing or deleted .ninja_deps. Rebuild from clean rather than trusting an empty "
            f"header list."
        )
    headers = []
    for line in proc.stdout.splitlines():
        if line.startswith("    "):
            headers.append(line.strip())
    return headers


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    build = Path(args.build).resolve()
    sidecar_path = Path(args.sidecar)
    if not sidecar_path.exists():
        print(json.dumps({"error": "SEMB_SOURCE_SIDECAR_MISSING", "path": str(sidecar_path)}))
        return 1
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

    _OBJECT_SUFFIXES = (".obj", ".o")

    # TE-89 (TE-88 review C-1, found by real execution under WSL Ubuntu/
    # GCC 13.4: the two-query design below assumed CMake's own Ninja
    # generator ALWAYS wraps a target behind a "phony" alias pointing at a
    # differently-named real output file (true for a STATIC LIBRARY target,
    # whose bare name "superembedder" differs from its real archive name
    # "libsuperembedder.a"/"superembedder.lib"). On Linux, an EXECUTABLE
    # target whose bare CMake name and real output file are the IDENTICAL
    # string ("semb_witness", no platform suffix) gets no phony alias at
    # all -- `ninja -t query semb_witness` returns the LINK STEP's own
    # inputs directly, and the second query this code used to always run
    # would instead query the first (misidentified) input -- the witness's
    # own COMPILE step's object file -- and find no further objects,
    # reporting SEMB_SOURCE_NO_OBJECTS on a perfectly healthy build.
    phony_out = _ninja_query(build, args.ninja, args.target)
    first_level = _parse_query_inputs(phony_out)
    if not first_level:
        print(json.dumps({"error": "SEMB_SOURCE_TARGET_NOT_FOUND", "target": args.target}))
        return 1
    if any(s.endswith(_OBJECT_SUFFIXES) for s in first_level):
        # The target's own bare name IS the real link-step build edge
        # already -- no phony alias exists to hop through.
        target_output = (build / args.target).resolve()
        link_inputs = first_level
    else:
        # The target name is a phony alias for a DIFFERENTLY-named real
        # file (a static library's own archive name, or a Windows
        # executable's own ".exe"-suffixed name) -- resolve the real file
        # (also the artifact S-4's own stale-artifact deletion below
        # deletes on disagreement), then query ITS OWN inputs.
        target_output = (build / first_level[0]).resolve()
        link_inputs = _parse_query_inputs(_ninja_query(build, args.ninja, first_level[0]))
    # TE-87: a target that LINKS (an executable, e.g. semb_witness) lists
    # its linked LIBRARIES among its own "input:" block, not only its own
    # compiled object files (a target that only ARCHIVES, e.g.
    # superembedder, does not). A .lib/.a is not a translation unit --
    # `ninja -t deps` has no header-dependency entry for it, and its OWN
    # source closure is that library's own producer's own concern (already
    # covered independently by ITS OWN semb_compute_source_provenance()
    # call, where one exists) -- so only genuine compiled-object entries
    # are kept here.
    obj_files = [s for s in link_inputs if s.endswith(_OBJECT_SUFFIXES)]
    if not obj_files:
        print(json.dumps({"error": "SEMB_SOURCE_NO_OBJECTS", "target": args.target}))
        return 1

    real_files: set[Path] = set()
    for obj in obj_files:
        obj_out = _ninja_query(build, args.ninja, obj)
        srcs = [s for s in _parse_query_inputs(obj_out) if not s.startswith("cmake_object_order_depends")]
        for s in srcs:
            real_files.add((build / s).resolve())
        for h in _ninja_deps(build, args.ninja, obj):
            real_files.add((build / h).resolve())

    # TE-67 N-8: the same build-directory exclusion cmd_configure now
    # applies, using the -B path this subcommand already receives as
    # `build`, so the post-build closure is classified the identical way
    # regardless of where -B pointed.
    members = []
    out_of_root = []
    for p in sorted(real_files):
        try:
            p.relative_to(build)
            out_of_root.append(str(p))
            continue
        except ValueError:
            pass
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            out_of_root.append(str(p))
            continue
        members.append(("source", rel, p.read_bytes()))
    # TE-65 F-8: SEMB_ENGINE_PATH is deliberately not fed into the digest
    # (see the matching comment in cmd_configure) -- semb_source_sha is
    # path-invariant, matching engine_tree_sha's own stated invariant.

    recomputed = digest_members(members)
    agrees = recomputed == sidecar["semb_source_sha"]
    result = {
        "configure_time_semb_source_sha": sidecar["semb_source_sha"],
        "recomputed_semb_source_sha": recomputed,
        "agrees": agrees,
        # TE-89 (TE-88 review S-3): §4.4d requires the drift to fail the
        # build "by name" -- a JSON field alone ("agrees": false) is not a
        # name a consumer can grep for the way every other refusal in this
        # project is (SEMB_SOURCE_SET_DRIFT, SEMB_PIN_UNSAFE_BUILD_DIR,
        # ...). `status` carries the caller-supplied name on disagreement,
        # None on agreement -- and the SAME name is also printed as a bare
        # line below so a caller need not parse JSON to find it.
        "status": None if agrees else args.status_name,
        "real_file_count": len(members),
        "configure_time_file_count": len(sidecar["covered_files"]),
        "out_of_root_files_excluded": out_of_root,
    }
    if not agrees:
        # TE-89 (TE-88 review S-4): §4.4d item 1's own "before any
        # executable exists to misbehave" -- this verify step runs
        # POST_BUILD, after the drifted target has already been linked, so
        # "the build failed" and "the drifted output still exists on disk"
        # were both true at once. A subsequent ctest re-run, a manual
        # invocation, or a copy-out step reads the drifted artifact and has
        # no way to know it is drifted. Deleting the target's own real
        # output on disagreement closes that window: only a build that
        # re-links, and therefore re-verifies, leaves an artifact behind.
        try:
            if target_output.exists():
                target_output.unlink()
                result["stale_artifact_removed"] = True
            else:
                result["stale_artifact_removed"] = False
        except OSError as ex:
            result["stale_artifact_removed"] = False
            result["stale_artifact_removal_error"] = str(ex)
        result["stale_artifact_path"] = str(target_output)
    print(json.dumps(result))
    if not agrees:
        # A bare, grep-able status line -- CMake's add_custom_command()
        # COMMENT and this project's own build logs are read as text, not
        # parsed as JSON, and every other named SEMB_* refusal in this
        # project is findable this way.
        print(args.status_name)
    return 0 if agrees else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    c = sub.add_parser("configure")
    c.add_argument("--root", required=True)
    c.add_argument("--source", action="append", default=[], help="a declared library source, relative to --root")
    c.add_argument("--include-dir", action="append", default=[],
                    help="an include directory the real target will use (matches target_include_directories)")
    c.add_argument("--compiler", required=True, help="CMAKE_CXX_COMPILER")
    c.add_argument("--compiler-id", required=True, choices=["MSVC", "GNU", "Clang", "AppleClang"],
                    help="CMAKE_CXX_COMPILER_ID")
    c.add_argument("--std", default="c++20")
    c.add_argument("--engine-path", required=True)
    c.add_argument("--build-dir", default=None,
                    help="CMAKE_BINARY_DIR -- excluded from the covered set unconditionally (TE-67 N-8), "
                         "regardless of whether it sits inside or outside --root")
    c.add_argument("--out-header", required=True)
    c.add_argument("--out-json", required=True)
    c.add_argument("--force-empty-closure", action="store_true",
                    help="TE-71 Q-6: test-only escape hatch, fed from a real CMake cache variable "
                         "(cmake/SourceProvenance.cmake) -- never set in normal use. Makes "
                         "_resolve_closure() return an empty closure regardless of what the real "
                         "compiler resolves, driving N-6's own must-reject through a real configure.")
    c.set_defaults(func=cmd_configure)

    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    v.add_argument("--build", required=True)
    v.add_argument("--ninja", default="ninja")
    v.add_argument("--target", required=True)
    v.add_argument("--sidecar", required=True)
    v.add_argument("--status-name", default="SEMB_SOURCE_SET_DRIFT",
                    help="TE-89 (TE-88 review S-3): the named SEMB_* status printed and put in the "
                         "result JSON's own 'status' field on disagreement -- SEMB_SOURCE_SET_DRIFT "
                         "for the superembedder library (C34, the default, unchanged), "
                         "SEMB_WITNESS_FOREIGN_BUILD for the semb_witness executable (C31(i), sec "
                         "4.4d item 1).")
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
