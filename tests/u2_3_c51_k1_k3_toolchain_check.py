"""tests/u2_3_c51_k1_k3_toolchain_check.py -- C51 (d)'s engine-compiler legs (`Claude/Plans/te267-u2-release-plan.md`
sec 5 U2-3 item 13, must-rejects (k-1)...(k-3) and the first two Must-accepts of *TE-292*; plan of record sec 8
C51 (d); REL-2 step 1). Apparatus: tests/u2_3_c51_support.py.

  (k-1)        the mixed build, the adversary's construction (TE-288): the product configured against an engine
               another compiler built refuses SEMB_ENGINE_TOOLCHAIN_MISMATCH at configure and generates no build
               system, so no build of that pair can report a cell. Every ordered off-diagonal (product, engine)
               pair over the toolchains present. On the dev box: the six pairs over MSVC 19.33, clang-cl 18.1.8 and
               MSVC 19.44. Off Windows: GCC against a clang-18 engine and the reverse (clang-18 compiles against
               the same libstdc++, so only the compiler differs: REL-2 step 1's GCC column).
  (k-2)        a re-pin under a configured build: the product configured against its own compiler's engine, the
               prefix re-pinned in place by the pin tool under the other compiler, then `cmake --build`: configure
               re-runs and refuses SEMB_ENGINE_TOOLCHAIN_MISMATCH before any link.
  (k-3)        a copied engine: the same, with the prefix's files replaced by a copy of the other compiler's prefix
               whose timestamps are older than the build's (so the build system does not re-run configure): the
               every-build step refuses SEMB_ENGINE_CHANGED_SINCE_CONFIGURE before any compile or link.
  own-engine   must-accept: each member toolchain, configured and built against the engine the pin tool built with its
               own compiler, configures, opens (a bake on the synthetic pair) and reports the cell the compiled
               list gives its descriptor and tier (SEMB_OK from the linked-engine check; the cell and epoch equal
               this script's own matcher over the list, and the bake manifest's). The dev box's MSVC 19.33 and
               clang-cl 18.1.8 builds report their committed cells; a build no cell names reports `uncertified`.
  cmake-3.31   must-accept: the tree's own member configured and built under a second CMake (--second-cmake; the
               plan's: BuildTools' CMake 3.31 against 3.24) records the same compileFlags and engineFlags and
               reports the same cell. MISSING PREREQUISITE without a second CMake.

The Windows-compiler legs are the dev box's: there, configure the MSVC 19.33 tree with SEMB_C51_TOOLCHAINS_FILE
naming clang-cl 18.1.8 and MSVC 19.44 (tests/u2_3_c51_support.py's format) and SEMB_C51_SECOND_CMAKE, and run
`ctest -L c51_runtime`. Off Windows those rows report MISSING PREREQUISITE and the test passes on the rest.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import u2_3_c51_support as c51  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    c51.add_common_arguments(ap)
    ap.add_argument("--second-cmake", default="")
    args = ap.parse_args(argv)
    report, me, others, how, engines, product, scratch = c51.setup(args, "C51 (k-1)...(k-3)")
    toolchains = [me] + others

    pins = {t.name: engines.get(t) for t in toolchains}
    for t in toolchains:
        p = pins[t.name]
        if not p.ok:
            report.leg("FAIL", f"setup: the {t.name} engine pin", f"exit {p.rc}: {c51.tail(p.output)}")
    good = [t for t in toolchains if pins[t.name].ok]

    src = product.copy_source(scratch / "src")

    # (k-1): every ordered off-diagonal pair.
    if len(good) < 2:
        report.missing("(k-1) a product configured against another compiler's engine",
                       f"one toolchain only ({how})")
    for prod in good:
        for eng in good:
            if prod is eng:
                continue
            build = scratch / f"k1-{prod.name}-on-{eng.name}"
            rc, out = product.configure(prod, src, build, pins[eng.name].prefix)
            generated = (build / "build.ninja").exists() or any(build.glob("*.sln"))
            report.check(rc != 0 and "SEMB_ENGINE_TOOLCHAIN_MISMATCH" in out and not generated,
                         f"(k-1) the {prod.name} product against a {eng.name} engine refuses "
                         f"SEMB_ENGINE_TOOLCHAIN_MISMATCH at configure, generating no build system",
                         f"exit {rc}, build system generated={generated}: {c51.tail(out, 4)}")
    c51.windows_members_note(report, good, "(k-1)'s six off-diagonal pairs")

    # The own-engine must-accept.
    member_epoch, uncertified_epoch = c51.epochs(src)
    reference = None
    # Members only: a compiler found on PATH for the cross legs is not a release member, and the product is not
    # specified to build under it.
    for t in [t for t in good if t is me or t.member]:
        build = scratch / f"own-{t.name}"
        rc, out = product.configure(t, src, build, pins[t.name].prefix)
        if rc == 0:
            rc, out = product.build(t, build)
        if rc != 0:
            report.leg("FAIL", f"own-engine must-accept: {t.name} configures and builds against its own engine",
                       f"exit {rc}: {c51.tail(out)}")
            continue
        v = c51.read_version(build)
        want_cell, want_epoch = c51.expected_cell(src, v)
        manifest, detail = c51.bake_manifest(build, scratch / f"own-{t.name}-bake")
        ok = (v.rc == 0 and v.check == "SEMB_OK" and v.cell == want_cell and v.epoch == want_epoch
              and want_epoch in (member_epoch, uncertified_epoch))
        report.check(ok, f"own-engine must-accept: {t.name} on its own compiler's engine reports its cell",
                     f"check={v.check} cell={v.cell} epoch={v.epoch[:16]}... (the list gives {want_cell} "
                     f"{want_epoch[:16]}...)")
        if manifest is None:
            report.missing(f"own-engine must-accept: {t.name} opens (bake manifest)", detail)
        else:
            report.check(manifest.get("certified_cell") == v.cell and manifest.get("certification_epoch") == v.epoch,
                         f"own-engine must-accept: {t.name} opens, and its bake manifest records the same cell "
                         f"and epoch", f"{detail}; certified_cell={manifest.get('certified_cell')} "
                                       f"certification_epoch={str(manifest.get('certification_epoch'))[:16]}...")
        if t is me:
            reference = v
    c51.windows_members_note(report, good, "the own-engine must-accept")

    # The second-CMake must-accept.
    second = args.second_cmake
    if not second:
        report.missing("cmake-3.31 must-accept: one member under two CMake versions records one compileFlags and "
                       "engineFlags", "no --second-cmake (SEMB_C51_SECOND_CMAKE; the dev box's BuildTools CMake 3.31)")
    elif reference is None:
        report.leg("FAIL", "cmake-3.31 must-accept", "the reference build under the tree's own CMake did not build")
    else:
        build = scratch / "cmake2"
        rc, out = product.configure(me, src, build, pins[me.name].prefix, cmake=second)
        if rc == 0:
            rc, out = product.build(me, build, cmake=second)
        v = c51.read_version(build) if rc == 0 else None
        report.check(v is not None and v.digests == reference.digests and v.cell == reference.cell
                     and v.epoch == reference.epoch,
                     f"cmake-3.31 must-accept: {me.name} under {second} records the same compileFlags and "
                     f"engineFlags and reports the same cell",
                     f"exit {rc}; {v.digests if v else None} vs {reference.digests}; cell "
                     f"{v.cell if v else None} vs {reference.cell}" if rc == 0 else f"exit {rc}: {c51.tail(out)}")

    # (k-2) and (k-3): the tree's own product against its own engine, then the other compiler's engine put in place.
    other = next((t for t in good if t is not me), None)
    if other is None:
        report.missing("(k-2) a re-pin under a configured build refuses before any link", f"one toolchain ({how})")
        report.missing("(k-3) a copied engine refuses SEMB_ENGINE_CHANGED_SINCE_CONFIGURE before any link",
                       f"one toolchain ({how})")
        return report.exit_code()

    prefix2 = scratch / "k2-prefix"
    c51.matrix.rmtree(prefix2)
    shutil.copytree(pins[me.name].prefix, prefix2)
    build2 = scratch / "k2-build"
    rc, out = product.configure(me, src, build2, prefix2)
    if rc != 0:
        report.leg("FAIL", "(k-2) setup: the product configures against a copy of its own engine",
                   f"exit {rc}: {c51.tail(out)}")
    else:
        repin = c51.run_pin(other, prefix2, scratch / "k2-pinwork", scratch / "k2.lock", engines.source,
                            cmake=args.cmake_executable, ninja=args.ninja_executable)
        if not repin.ok:
            report.leg("FAIL", f"(k-2) setup: re-pin the prefix in place under {other.name}",
                       f"exit {repin.rc}: {c51.tail(repin.output)}")
        else:
            rc, out = product.build(me, build2)
            report.check(rc != 0 and "SEMB_ENGINE_TOOLCHAIN_MISMATCH" in out and not c51.linked(build2),
                         f"(k-2) {me.name} product configured, its prefix re-pinned under {other.name}, then "
                         f"`cmake --build`: configure re-runs and refuses SEMB_ENGINE_TOOLCHAIN_MISMATCH before any "
                         f"link", f"exit {rc}; re-ran configure={'Re-running CMake' in out}; linked "
                                  f"{[p.name for p in c51.linked(build2)]}: {c51.tail(out, 4)}")

    prefix3 = scratch / "k3-prefix"
    c51.matrix.rmtree(prefix3)
    shutil.copytree(pins[me.name].prefix, prefix3)
    build3 = scratch / "k3-build"
    rc, out = product.configure(me, src, build3, prefix3)
    if rc != 0:
        report.leg("FAIL", "(k-3) setup: the product configures against a copy of its own engine",
                   f"exit {rc}: {c51.tail(out)}")
    else:
        # Older than every file configure wrote: the build system sees nothing newer than its last configure.
        old = time.time() - 2 * 86400
        c51.matrix.rmtree(prefix3)
        shutil.copytree(pins[other.name].prefix, prefix3)
        for root, dirs, files in os.walk(prefix3):
            for n in dirs + files:
                os.utime(os.path.join(root, n), (old, old))
        os.utime(prefix3, (old, old))
        rc, out = product.build(me, build3)
        report.check(rc != 0 and "SEMB_ENGINE_CHANGED_SINCE_CONFIGURE" in out
                     and "SEMB_ENGINE_TOOLCHAIN_MISMATCH" not in out and not c51.linked(build3)
                     and not c51.objects_under(build3),
                     f"(k-3) {me.name} product configured, its prefix replaced by an older-stamped copy of the "
                     f"{other.name} engine: the every-build step refuses SEMB_ENGINE_CHANGED_SINCE_CONFIGURE before "
                     f"any compile or link", f"exit {rc}; re-ran configure={'Re-running CMake' in out}; objects "
                     f"{len(c51.objects_under(build3))}; linked {[p.name for p in c51.linked(build3)]}: "
                     f"{c51.tail(out, 4)}")
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
