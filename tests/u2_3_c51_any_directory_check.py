"""tests/u2_3_c51_any_directory_check.py -- the any-directory must-accept (`Claude/Plans/te267-u2-release-plan.md`
sec 5 U2-3 item 13's Must-accepts, *TE-298, the adversary's keeper from TE-297 sec 11, widened*; plan of record
sec 8 C51 (d); REL-2 step 1: "the any-directory must-accept on each of the four toolchains"). Apparatus:
tests/u2_3_c51_support.py.

For each member toolchain, the member reports its own cell from any directory. Against a reference (the member
configured from a copy of the source tree against its own clean engine, its cell and epoch read from
`semb --version`; where no committed cell names this build, every source copy carries the same list variant
naming the reference's own cell, as in tests/u2_3_c51_k5_k8_flags_check.py), each layout below must record the
reference's compileFlags and engineFlags, list no residual location (the product's compile-flags.json and the
engine's provenance record), print no SEMB_COMPILE_FLAGS_LOCATION, and open to the same cell and epoch
(`semb --version`, and a bake's manifest on the synthetic pair):

  engine-copy     a byte-identical copy of its engine at a second directory;
  second-tree     a second source copy and build tree (the control);
  other-root      every root (source, build, engine) through paths containing a space, and on Windows on another
                  drive (--other-drive-root, SEMB_C51_OTHER_DRIVE_ROOT; MISSING PREREQUISITE there without one; a
                  POSIX host has one root, so the leg is the spaces);
  engine-in-build the engine installed by the pin tool inside the build tree;
  engine-in-src   the engine installed by the pin tool inside the source tree (the hosted workflow's layout).

ctest registers other-root as its own test (u2_3_c51_any_directory_other_root) so a red there is attributed to
that layout. It was red on Linux at 03047e5: with the source tree under a path containing a space, the GCC
build stopped at SEMB_SOURCE_SET_DRIFT, because tools/semb_source_hash.py split the `-M` rule on every space,
escaped (`\ `) or not. The tool now splits on unescaped whitespace only, and the layout passes.

And every pin this test makes leaves its copy of the committed superslm.lock byte-identical (F33: a GCC pin in the
Ubuntu-24.04 distro must; the rule is platform-free, so every member's is graded).

The MSVC 19.33, clang-cl 18.1.8 and MSVC 19.44 members run on the Windows dev box (`ctest -L c51_runtime` in its
MSVC tree, with SEMB_C51_TOOLCHAINS_FILE naming the other two and SEMB_C51_OTHER_DRIVE_ROOT a directory on
another drive); the GCC 13.3.0 member in the dev box's WSL tree. Off Windows the Windows members report MISSING
PREREQUISITE.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import u2_3_c51_support as c51  # noqa: E402

LAYOUTS = ("engine-copy", "second-tree", "other-root", "engine-in-build", "engine-in-src")


def engine_residual(prefix: Path) -> list:
    prov = json.loads((prefix / "share" / "superslm-provenance" / "provenance.json").read_text("utf-8"))
    return list(prov["engine_build"].get("flags", {}).get("residual", []))


def member(report, product, engines, tc, scratch, args, pins_made):
    tag = tc.name
    clean = engines.get(tc)
    if not clean.ok:
        report.leg("FAIL", f"setup: the {tag} engine pin", f"exit {clean.rc}: {c51.tail(clean.output)}")
        return
    if clean.output != "the tree's own engine prefix":
        pins_made.append((f"{tag} clean pin", clean))
    src = product.copy_source(scratch / f"{tag}-ref-src")
    member_epoch, _ = c51.epochs(src)
    build = scratch / f"{tag}-ref-build"
    rc, out = product.configure(tc, src, build, clean.prefix)
    if rc == 0:
        rc, out = product.build(tc, build)
    if rc != 0:
        report.leg("FAIL", f"reference: {tag} configures and builds", f"exit {rc}: {c51.tail(out)}")
        return
    ref = c51.read_version(build)
    variant = None
    if c51.expected_cell(src, ref)[0] == "uncertified":
        variant = f"c51-local-{tag}@{ref.tier}"
        c51.certify_locally(src, ref, variant)
        rc, out = product.build(tc, build)
        ref = c51.read_version(build) if rc == 0 else ref
    ref_bake, ref_bake_detail = c51.bake_manifest(build, scratch / f"{tag}-ref-bake")
    ok = ref.rc == 0 and ref.check == "SEMB_OK" and ref.cell != "uncertified" and ref.epoch == member_epoch
    report.check(ok, f"reference: {tag} reports its cell and the member epoch"
                     f" ({'a list variant naming its own cell' if variant else 'the committed list'})",
                 f"cell={ref.cell} epoch={ref.epoch[:16]}... digests {ref.digests[0][:16]}.../{ref.digests[1][:16]}...")
    if not ok:
        return

    def source(dest: Path) -> Path:
        s = product.copy_source(dest)
        if variant:
            c51.certify_locally(s, ref, variant)
        return s

    def grade(layout: str, src_dir: Path, build_dir: Path, prefix: Path, fresh: bool = True) -> None:
        if layout.split(" ", 1)[0] not in args.layouts:
            return
        rc, out = product.configure(tc, src_dir, build_dir, prefix, fresh=fresh)
        if rc == 0:
            rc, out = product.build(tc, build_dir)
        if rc != 0:
            report.leg("FAIL", f"any-directory {layout} on {tag}: configures and builds", f"exit {rc}: {c51.tail(out)}")
            return
        v = c51.read_version(build_dir)
        located = "SEMB_COMPILE_FLAGS_LOCATION" in out
        eres = engine_residual(prefix)
        ok = (v.digests == ref.digests and not v.residual_flags and not eres and not located
              and v.check == "SEMB_OK" and v.cell == ref.cell and v.epoch == ref.epoch)
        report.check(ok, f"any-directory {layout} on {tag}: the reference's compileFlags and engineFlags, no residual "
                         f"location, the same cell",
                     f"digests {v.digests[0][:16]}.../{v.digests[1][:16]}... (reference {ref.digests[0][:16]}.../"
                     f"{ref.digests[1][:16]}...); residual product={v.residual_flags} engine={eres} printed={located}; "
                     f"check={v.check} cell={v.cell}")
        manifest, detail = c51.bake_manifest(build_dir, build_dir.parent / f"{build_dir.name}-bake")
        if manifest is None or ref_bake is None:
            report.missing(f"any-directory {layout} on {tag}: opens to the same cell (bake)",
                           detail if manifest is None else ref_bake_detail)
        else:
            report.check(manifest.get("certified_cell") == ref.cell
                         and manifest.get("certification_epoch") == ref.epoch
                         and manifest.get("build_descriptor") == ref_bake.get("build_descriptor"),
                         f"any-directory {layout} on {tag}: opens to the same cell (the bake manifest's cell, epoch "
                         f"and build_descriptor are the reference's)",
                         f"{detail}; certified_cell={manifest.get('certified_cell')}")

    # engine-copy: a byte-identical engine at a second directory.
    copy = scratch / f"{tag}-engine-copy" / "second place"
    c51.matrix.rmtree(copy.parent)
    if "engine-copy" in args.layouts:
        shutil.copytree(clean.prefix, copy)
    grade("engine-copy (a byte-identical engine at a second directory)", src, scratch / f"{tag}-engine-copy-build",
          copy)

    # second-tree: a second source copy and build tree.
    if "second-tree" in args.layouts:
        grade("second-tree (a second source copy and build tree)", source(scratch / f"{tag}-src-2"),
              scratch / f"{tag}-build-2", clean.prefix)

    # other-root: every root through paths with a space, on another drive on Windows.
    if "other-root" not in args.layouts:
        pass
    elif c51.WINDOWS and not args.other_drive_root:
        report.missing(f"any-directory other-root on {tag}", "no --other-drive-root (SEMB_C51_OTHER_DRIVE_ROOT): a "
                       "directory on a drive other than the build tree's")
    else:
        base = Path(args.other_drive_root) if args.other_drive_root else scratch
        root = base / f"c51 any dir {tag}"
        c51.matrix.rmtree(root)
        eng = root / "engine install"
        shutil.copytree(clean.prefix, eng)
        grade(f"other-root (source, build and engine under {root}, with spaces"
              f"{', on another drive' if args.other_drive_root else '; one root on this host'})",
              source(root / "source tree"), root / "build tree", eng)

    # engine-in-build and engine-in-src: real pins into the trees (the build tree configured without wiping it).
    for layout, tree, build_dir, what in (
            ("engine-in-build", scratch / f"{tag}-engine-in-build", None, "the build tree"),
            ("engine-in-src", scratch / f"{tag}-engine-in-src", scratch / f"{tag}-in-src-build", "the source tree")):
        if layout not in args.layouts:
            continue
        src_dir = src
        if build_dir is None:
            c51.matrix.rmtree(tree)
            build_dir = tree
        else:
            src_dir = tree = source(tree)
        pin = c51.run_pin(tc, tree / "engine-install", scratch / f"{tag}-pinwork-{layout}", scratch / f"{tag}-{layout}.lock",
                          engines.source, cmake=args.cmake_executable, ninja=args.ninja_executable)
        pins_made.append((f"{tag} pin inside {what}", pin))
        if not pin.ok:
            report.leg("FAIL", f"any-directory {layout} on {tag}: the pin", f"exit {pin.rc}: {c51.tail(pin.output)}")
            continue
        grade(f"{layout} (the engine installed by the pin tool inside {what})", src_dir, build_dir, pin.prefix,
              fresh=layout == "engine-in-src")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    c51.add_common_arguments(ap)
    ap.add_argument("--other-drive-root", default="")
    ap.add_argument("--layouts", default=",".join(LAYOUTS),
                    help=f"comma-separated subset of {', '.join(LAYOUTS)} (ctest registers other-root on its own)")
    args = ap.parse_args(argv)
    args.layouts = [l for l in args.layouts.split(",") if l]
    if set(args.layouts) - set(LAYOUTS):
        ap.error(f"unknown layout(s) {sorted(set(args.layouts) - set(LAYOUTS))}")
    report, me, others, _, engines, product, scratch = c51.setup(
        args, f"C51 any-directory must-accept ({', '.join(args.layouts)})")
    members = [me] + [t for t in others if t.member]
    pins_made: list = []
    for tc in members:
        member(report, product, engines, tc, scratch, args, pins_made)
    for what, pin in pins_made:
        if pin.ok:
            report.check(pin.lock_unchanged(), f"F33: the {what} leaves its copy of the committed superslm.lock "
                         f"byte-identical", f"{pin.lock_copy}")
    c51.windows_members_note(report, members, "the any-directory must-accept")
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
