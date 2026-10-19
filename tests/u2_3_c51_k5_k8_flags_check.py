"""tests/u2_3_c51_k5_k8_flags_check.py -- C51 (d)'s flag legs (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3
item 13, must-rejects (k-5), (k-6) and (k-8); plan of record sec 8 C51 (d); REL-2 step 1). Apparatus:
tests/u2_3_c51_support.py.

  (k-5) pin     the pin tool with CL, _CL_ or CCC_OVERRIDE_OPTIONS set refuses
                SEMB_PIN_AMBIENT_COMPILER_INPUT naming the variable, and writes no prefix.
  (k-5) build   the product's build with the same variable set refuses SEMB_BUILD_AMBIENT_COMPILER_INPUT naming
                it, before any product compile (no object under the library's or the CLI's object directory). The
                plan names CL; the other two are refused by the same step and are graded too. The same build
                directory then builds with none set (the control): it is the reference below.
  reference     the member, clean: its cell. Where no committed cell names this build (any Linux build: the
                interim list holds two Windows cells), the source copy carries a list variant that also lists the
                reference's own cell, with a pair to each committed cell (tests/u2_3_c51_support.py
                `certify_locally`), so a leg that must move a build out of a cell is read moving it; the reference
                must then report that cell and the member epoch, in `semb --version` and in its bake manifest.
  (k-6) engine  the member against an engine pinned under CXXFLAGS=<flag> (/arch:AVX2 on the MSVC frontend,
                -mavx2 on GCC): another engineFlags, and the uncertified epoch in `semb --version` and in the bake
                manifest (the synthetic pair).
  (k-6) product the product configured with -DCMAKE_CXX_FLAGS=<flag>: another compileFlags, and the uncertified
                epoch, the same two ways. It is configured in the reference's own source and build directories,
                so it is also (k-8)'s product half: one added flag at unchanged places.
  (k-8) engine  the engine pinned twice into one work directory and one prefix, once clean and once with the
                added flag, the product's build directory unchanged between them: the clean pin records the
                reference's engineFlags (a pin at another place), the flagged one another, which is the (k-6)
                engine's (the same flag at another place), and the build resolves uncertified.
                (`cmake --build` alone: configure re-runs on the re-pinned provenance.)

The flagged engine compiles AVX2 encodings throughout, so the legs that open it need an AVX2 host; on a host whose
dispatched tier is below avx2 they report MISSING PREREQUISITE. The MSVC 19.33, clang-cl 18.1.8 and MSVC 19.44
members of (k-6) and (k-8) run on the Windows dev box (`ctest -L c51_runtime` in its MSVC tree, with
SEMB_C51_TOOLCHAINS_FILE naming the other two); off Windows they report MISSING PREREQUISITE.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import u2_3_c51_support as c51  # noqa: E402

AMBIENT = ("CL", "_CL_", "CCC_OVERRIDE_OPTIONS")


def built_version(report, product, tc, src, build, prefix, what, defines=None, fresh=True):
    rc, out = product.configure(tc, src, build, prefix, defines=defines, fresh=fresh)
    if rc == 0:
        rc, out = product.build(tc, build)
    if rc != 0:
        report.leg("FAIL", f"{what}: configures and builds", f"exit {rc}: {c51.tail(out)}")
        return None
    return c51.read_version(build)


def grade_uncertified(report, name, v, ref, field_index, uncertified_epoch, bake_dir, build):
    moved = v.digests[field_index] != ref.digests[field_index]
    kept = v.digests[1 - field_index] == ref.digests[1 - field_index]
    which = ("compileFlags", "engineFlags")[field_index]
    report.check(v.rc == 0 and v.check == "SEMB_OK" and moved and kept and v.cell == "uncertified"
                 and v.epoch == uncertified_epoch,
                 f"{name}: another {which}, and `semb --version` reports the uncertified epoch",
                 f"{which} {v.digests[field_index][:16]}... vs the reference's {ref.digests[field_index][:16]}...; "
                 f"other digest unchanged={kept}; check={v.check} cell={v.cell} epoch={v.epoch[:16]}...")
    manifest, detail = c51.bake_manifest(build, bake_dir)
    if manifest is None:
        report.missing(f"{name}: the bake manifest", detail)
    else:
        report.check(manifest.get("certified_cell") == "uncertified"
                     and manifest.get("certification_epoch") == uncertified_epoch,
                     f"{name}: the bake manifest records the uncertified epoch",
                     f"{detail}; certified_cell={manifest.get('certified_cell')} "
                     f"certification_epoch={str(manifest.get('certification_epoch'))[:16]}...")


def member_legs(report, product, engines, tc, scratch, args, run_k5):
    tag = tc.name
    clean = engines.get(tc)
    if not clean.ok:
        report.leg("FAIL", f"setup: the {tag} engine pin", f"exit {clean.rc}: {c51.tail(clean.output)}")
        return
    src = product.copy_source(scratch / f"{tag}-src")
    member_epoch, uncertified_epoch = c51.epochs(src)
    build = scratch / f"{tag}-build"
    rc, out = product.configure(tc, src, build, clean.prefix)
    if rc != 0:
        report.leg("FAIL", f"setup: {tag} configures against its own engine", f"exit {rc}: {c51.tail(out)}")
        return

    if run_k5:
        for name in AMBIENT:
            rc, out = product.build(tc, build, extra_env={name: tc.avx2_flag})
            objs = c51.objects_under(build)
            report.check(rc != 0 and f"SEMB_BUILD_AMBIENT_COMPILER_INPUT {name}" in out and not objs
                         and not c51.linked(build),
                         f"(k-5) build: the {tag} product's build with {name} set refuses "
                         f"SEMB_BUILD_AMBIENT_COMPILER_INPUT {name} before any product compile",
                         f"exit {rc}; objects {len(objs)}; {c51.tail(out, 2)}")

    rc, out = product.build(tc, build)
    if rc != 0:
        report.leg("FAIL", f"reference: {tag}, clean, builds (the (k-5) control)", f"exit {rc}: {c51.tail(out)}")
        return
    ref = c51.read_version(build)
    want_cell, _ = c51.expected_cell(src, ref)
    listed = "the committed list"
    if want_cell == "uncertified":
        c51.certify_locally(src, ref, f"c51-local-{tag}@{ref.tier}")
        rc, out = product.build(tc, build)
        if rc != 0:
            report.leg("FAIL", f"reference: {tag} rebuilds against the list variant", f"exit {rc}: {c51.tail(out)}")
            return
        ref = c51.read_version(build)
        listed = "a list variant naming its own cell"
    report.check(ref.rc == 0 and ref.check == "SEMB_OK" and ref.cell != "uncertified" and ref.epoch == member_epoch,
                 f"reference: {tag}, clean, reports its cell and the member epoch ({listed})",
                 f"cell={ref.cell} epoch={ref.epoch[:16]}... tier={ref.tier} digests "
                 f"{ref.digests[0][:16]}.../{ref.digests[1][:16]}...")
    if ref.cell == "uncertified":
        return
    manifest, detail = c51.bake_manifest(build, scratch / f"{tag}-ref-bake")
    if manifest is None:
        report.missing(f"reference: {tag}'s bake manifest", detail)
    else:
        report.check(manifest.get("certified_cell") == ref.cell and manifest.get("certification_epoch") == member_epoch,
                     f"reference: {tag}'s bake manifest records its cell and the member epoch",
                     f"{detail}; certified_cell={manifest.get('certified_cell')}")
    if ref.tier not in ("avx2", "avx512"):
        for leg in ("(k-6) engine", "(k-6)/(k-8) product", "(k-8) engine"):
            report.missing(f"{leg} on {tag}", f"this host dispatches {ref.tier}; the flagged builds need AVX2")
        return

    flag = tc.avx2_flag
    # (k-6) engine: an engine pinned under CXXFLAGS=<flag>, at its own prefix.
    flagged = engines.get(tc, "cxxflags-avx2", cxxflags=flag)
    if not flagged.ok:
        report.leg("FAIL", f"(k-6) engine setup: pin {tag} under CXXFLAGS={flag}",
                   f"exit {flagged.rc}: {c51.tail(flagged.output)}")
    else:
        b6 = scratch / f"{tag}-k6-engine-build"
        v = built_version(report, product, tc, src, b6, flagged.prefix, f"(k-6) engine on {tag}")
        if v:
            grade_uncertified(report, f"(k-6) {tag} against an engine pinned under CXXFLAGS={flag}", v, ref, 1,
                              uncertified_epoch, scratch / f"{tag}-k6-engine-bake", b6)

    # (k-6) product, which is also (k-8)'s product half: the reference's own directories, one added flag.
    v = built_version(report, product, tc, src, build, clean.prefix, f"(k-6)/(k-8) product on {tag}",
                      defines={"CMAKE_CXX_FLAGS": flag}, fresh=False)
    if v:
        grade_uncertified(report, f"(k-6)/(k-8) {tag} product configured with -DCMAKE_CXX_FLAGS={flag} in the "
                          f"reference's own source and build directories", v, ref, 0, uncertified_epoch,
                          scratch / f"{tag}-k6-product-bake", build)

    # (k-8) engine: one work directory, one prefix, pinned clean then with the flag; one product build directory.
    prefix8, work8, b8 = scratch / f"{tag}-k8-prefix", scratch / f"{tag}-k8-pinwork", scratch / f"{tag}-k8-build"
    c51.matrix.rmtree(prefix8)
    c51.matrix.rmtree(work8)
    p1 = c51.run_pin(tc, prefix8, work8, scratch / f"{tag}-k8.lock", engines.source, cmake=args.cmake_executable,
                     ninja=args.ninja_executable)
    if not p1.ok:
        report.leg("FAIL", f"(k-8) engine setup: the clean pin of {tag}", f"exit {p1.rc}: {c51.tail(p1.output)}")
        return
    v1 = built_version(report, product, tc, src, b8, prefix8, f"(k-8) engine, clean, on {tag}")
    if not v1:
        return
    report.check(v1.digests == ref.digests and v1.cell == ref.cell,
                 f"(k-8) {tag} against its engine pinned clean at another work directory and prefix records the "
                 f"reference's compileFlags and engineFlags and reports its cell",
                 f"{v1.digests[1][:16]}... vs {ref.digests[1][:16]}...; cell {v1.cell}")
    p2 = c51.run_pin(tc, prefix8, work8, scratch / f"{tag}-k8.lock", engines.source, cmake=args.cmake_executable,
                     ninja=args.ninja_executable, extra_env={"CXXFLAGS": flag})
    if not p2.ok:
        report.leg("FAIL", f"(k-8) engine setup: the {flag} re-pin of {tag} into the same work directory and prefix",
                   f"exit {p2.rc}: {c51.tail(p2.output)}")
        return
    rc, out = product.build(tc, b8)
    if rc != 0:
        report.leg("FAIL", f"(k-8) engine: {tag}'s build after the re-pin", f"exit {rc}: {c51.tail(out)}")
        return
    v2 = c51.read_version(b8)
    grade_uncertified(report, f"(k-8) {tag} engine re-pinned with {flag} into the same work directory and prefix, "
                      f"the product's build directory unchanged", v2, ref, 1, uncertified_epoch,
                      scratch / f"{tag}-k8-bake", b8)
    if flagged.ok:
        report.check(v2.digests[1] == flagged.provenance()["engine_build"]["flagsSha"],
                     f"(k-8) {tag}: the flagged engine's engineFlags is the (k-6) engine's, pinned at another place",
                     f"{v2.digests[1][:16]}... vs {flagged.provenance()['engine_build']['flagsSha'][:16]}...")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    c51.add_common_arguments(ap)
    args = ap.parse_args(argv)
    report, me, others, how, engines, product, scratch = c51.setup(args, "C51 (k-5) (k-6) (k-8)")

    # (k-5) pin: the refusal precedes any clone, so it is graded once, under the tree's own toolchain.
    for i, name in enumerate(AMBIENT):
        prefix = scratch / f"k5-pin-prefix-{i}"
        c51.matrix.rmtree(prefix)
        pin = c51.run_pin(me, prefix, scratch / "k5-pinwork", scratch / "k5.lock", engines.source,
                          extra_env={name: me.avx2_flag}, cmake=args.cmake_executable, ninja=args.ninja_executable)
        report.check(pin.rc != 0 and f"SEMB_PIN_AMBIENT_COMPILER_INPUT {name}" in pin.output and not prefix.exists(),
                     f"(k-5) pin: the pin tool with {name} set refuses SEMB_PIN_AMBIENT_COMPILER_INPUT {name} and "
                     f"writes no prefix", f"exit {pin.rc}; prefix exists={prefix.exists()}: {c51.tail(pin.output, 2)}")

    members = [me] + [t for t in others if t.member]
    for tc in members:
        member_legs(report, product, engines, tc, scratch, args, run_k5=tc is me)
    c51.windows_members_note(report, members, "(k-6) and (k-8)")
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
