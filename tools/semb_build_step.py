#!/usr/bin/env python3
"""tools/semb_build_step.py -- the step every build of the product runs before any product translation unit
compiles (plan U2-3 item 13).

  1. Refuses SEMB_BUILD_AMBIENT_COMPILER_INPUT <variable> when CL, _CL_ or CCC_OVERRIDE_OPTIONS is set: they
     reach the compiler without appearing on any compile line, so no flag record could describe the objects.
     The step refuses rather than marks the build uncertified, because a mark written once cannot follow the
     objects a later incremental build recompiles under a changed environment.
  2. Refuses SEMB_ENGINE_CHANGED_SINCE_CONFIGURE when the engine prefix configure verified (the one
     find_package resolved) no longer holds the provenance.json configure read, or its library no longer has
     the SHA-256 the engine-build record names -- before any product compile or link.
  3. Writes the product's compile-flag record (tools/compile_flags.py over the build's own
     compile_commands.json, for the targets the release ships and the witness builds, less the two GPU adapter
     translation units) as compile-flags.json, and the header semb_compile_flags.h that compiles its digest in
     as compileFlags. Both are rewritten only when they change. A build with no compile_commands.json (the
     Visual Studio generators) records `unrecorded`, which matches no cell. Every residual location is printed
     as SEMB_COMPILE_FLAGS_LOCATION <argument>.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile_flags  # noqa: E402

AMBIENT_COMPILER_INPUTS = ("CL", "_CL_", "CCC_OVERRIDE_OPTIONS")
# te266 sec 4.2: the GPU-enabled build is the CPU-only build's cell, so neither adapter TU enters compileFlags.
EXCLUDED_SOURCES = ("engine_adapter_gpu.cpp", "engine_adapter_gpu_off.cpp")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_if_changed(path: Path, text: str) -> None:
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    import os

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--source-dir", type=Path, required=True)
    ap.add_argument("--engine-prefix", type=Path, required=True)
    ap.add_argument("--provenance-sha256", required=True)
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--library-sha256", required=True)
    ap.add_argument("--compiler-id", required=True)
    ap.add_argument("--frontend", default="")
    ap.add_argument("--target", action="append", required=True)
    ap.add_argument("--header", type=Path, required=True)
    args = ap.parse_args(argv)

    for name in AMBIENT_COMPILER_INPUTS:
        if name in os.environ:
            print(f"SEMB_BUILD_AMBIENT_COMPILER_INPUT {name}: this variable reaches the compiler without appearing on "
                  f"any compile line, so this build's compile-flag record could not describe its objects. Unset it "
                  f"and build again.", file=sys.stderr)
            return 1

    provenance = args.engine_prefix / "share" / "superslm-provenance" / "provenance.json"
    changed = []
    if not provenance.is_file() or sha256_file(provenance) != args.provenance_sha256:
        changed.append(f"{provenance} is not the provenance.json configure verified")
    if not args.library.is_file() or sha256_file(args.library) != args.library_sha256:
        changed.append(f"{args.library} is not the library the engine-build record names "
                       f"(librarySha256 {args.library_sha256})")
    if changed:
        print("SEMB_ENGINE_CHANGED_SINCE_CONFIGURE: " + "; ".join(changed) + ". Configure again against the "
              "engine this build should link.", file=sys.stderr)
        return 1

    commands = args.build_dir / "compile_commands.json"
    record_path = args.header.parent / "compile-flags.json"
    if commands.is_file():
        family = compile_flags.family_of(args.compiler_id, args.frontend)
        windows = os.name == "nt"
        roots = [(str(args.source_dir), "<src>"), (str(args.build_dir), "<build>"),
                 (str(args.engine_prefix), "<engine>")]
        entries = json.loads(commands.read_text(encoding="utf-8"))
        rec, residual = compile_flags.record(entries, family, roots, args.target, list(EXCLUDED_SOURCES), windows)
        digest = compile_flags.digest(rec) if rec else "unrecorded"
        for arg in residual:
            print(f"SEMB_COMPILE_FLAGS_LOCATION {arg}")
        doc = {"schemaVersion": 1, "family": family, "sha256": digest, "residual": residual, "record": rec}
        write_if_changed(record_path, json.dumps(doc, sort_keys=True, indent=1) + "\n")
    else:
        digest = "unrecorded"
        write_if_changed(record_path, json.dumps({"schemaVersion": 1, "sha256": digest}, indent=1) + "\n")
    write_if_changed(args.header,
                     "// Generated on every build by tools/semb_build_step.py. Do not edit.\n"
                     "// compileFlags: the digest of this build's compile-flag record (compile-flags.json beside "
                     "this file).\n"
                     "#pragma once\n"
                     f'#define SEMB_COMPILE_FLAGS_SHA "{digest}"\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
