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
    if proc.returncode != 0 and not headers:
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


def _resolve_closure(compiler_id: str, compiler: str, source: Path, include_dirs: list[str], std: str) -> list[Path]:
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
    per_source_closure: dict[str, set[Path]] = {}
    for s in args.source:
        src_path = (root / s).resolve()
        closure = _resolve_closure(args.compiler_id, args.compiler, src_path, args.include_dir, args.std)
        resolved = set()
        for h in closure:
            try:
                resolved.add(h.resolve())
            except OSError:
                continue
        resolved.add(src_path)  # the source itself is always a member of its own closure
        per_source_closure[s] = resolved
        covered |= resolved

    # Sec4.4's stated subset property: every declared SOURCE is a member of
    # the covered set the preprocessor actually resolved for it. A source
    # that fails this (e.g. one the preprocessor silently skipped) is a
    # configuration defect, not a normal state.
    for s, closure in per_source_closure.items():
        if (root / s).resolve() not in closure:
            print(json.dumps({"error": "SEMB_SOURCE_NOT_IN_OWN_CLOSURE", "source": s}))
            return 1

    members = []
    file_list = []
    out_of_root = []
    for p in sorted(covered):
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


def _ninja_deps(build: Path, ninja: str, obj: str) -> list[str]:
    proc = subprocess.run([ninja, "-t", "deps", obj], cwd=build, capture_output=True, text=True)
    if proc.returncode != 0:
        # F-14 (TE-65): a missing/broken deps database must not be read as
        # "zero headers" -- that reading is indistinguishable from a
        # genuinely header-free translation unit and would silently narrow
        # engine_tree_sha to the source files alone. Fail loudly instead.
        raise SystemExit(
            f"SEMB_SOURCE_DEPS_UNAVAILABLE: 'ninja -t deps {obj}' exited {proc.returncode}; "
            f"the dependency database this closure is derived from is missing or stale. "
            f"stderr:\n{proc.stderr}"
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

    phony_out = _ninja_query(build, args.ninja, args.target)
    lib_targets = _parse_query_inputs(phony_out)
    if not lib_targets:
        print(json.dumps({"error": "SEMB_SOURCE_TARGET_NOT_FOUND", "target": args.target}))
        return 1
    lib_out = _ninja_query(build, args.ninja, lib_targets[0])
    obj_files = _parse_query_inputs(lib_out)
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

    members = []
    out_of_root = []
    for p in sorted(real_files):
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
    result = {
        "configure_time_semb_source_sha": sidecar["semb_source_sha"],
        "recomputed_semb_source_sha": recomputed,
        "agrees": recomputed == sidecar["semb_source_sha"],
        "real_file_count": len(members),
        "configure_time_file_count": len(sidecar["covered_files"]),
        "out_of_root_files_excluded": out_of_root,
    }
    print(json.dumps(result))
    return 0 if result["agrees"] else 2


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
    c.add_argument("--out-header", required=True)
    c.add_argument("--out-json", required=True)
    c.set_defaults(func=cmd_configure)

    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    v.add_argument("--build", required=True)
    v.add_argument("--ninja", default="ninja")
    v.add_argument("--target", required=True)
    v.add_argument("--sidecar", required=True)
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
