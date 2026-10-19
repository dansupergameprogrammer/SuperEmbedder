"""tests/u2_3_c51_k9_tree_digest_check.py -- (k-9), the tree digest still sees content (`Claude/Plans/te267-u2-release-
plan.md` sec 5 U2-3 item 13, *TE-298, F33*; REL-2 step 1). Apparatus: tests/u2_3_c51_support.py.

engine_tree_sha reads an installed member with CRLF as LF, so one tag pinned on Windows and on Linux gives one
value (F33). (k-9) is the guard that this rule normalizes line endings only where it says so:

  control       the product configures against a byte copy of the tree's clean engine prefix (a refusal below is
                the edit's, not the copy's).
  (k-9) header  one byte of one installed engine header (include/superslm/*.h under the prefix) edited after the
                pin: configure refuses SEMB_ENGINE_INSTALL_DIVERGED.
  (k-9) CR      a CR inserted before one LF of one compiled member (src/matmul.cpp, the kernel TU) in the pin tool's
                clone: the pin tool (--reuse-clone; --allow-dirty, since the edit is not the tag's) records another
                engine_tree_sha than the same clone pinned unedited, which records the committed lock's tree=.
                An implementation that normalizes compiled members gives one value for both, and fails.

Runs under the tree's own compiler on every host; the dev box runs it in its MSVC tree and in WSL.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import u2_3_c51_support as c51  # noqa: E402

KERNEL = "src/matmul.cpp"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    c51.add_common_arguments(ap)
    args = ap.parse_args(argv)
    report, me, _, _, engines, product, scratch = c51.setup(args, "C51 (k-9)")
    clean = engines.get(me)
    if not clean.ok:
        report.leg("FAIL", f"setup: the {me.name} engine pin", f"exit {clean.rc}: {c51.tail(clean.output)}")
        return report.exit_code()
    src = product.copy_source(scratch / "src")

    prefix = scratch / "prefix-copy"
    c51.matrix.rmtree(prefix)
    shutil.copytree(clean.prefix, prefix)
    rc, out = product.configure(me, src, scratch / "control-build", prefix)
    report.check(rc == 0, "(k-9) control: the product configures against a byte copy of its clean engine prefix",
                 f"exit {rc}: {c51.tail(out, 2)}")

    headers = sorted((prefix / "include" / "superslm").glob("*.h"))
    if not headers:
        report.leg("FAIL", "(k-9) header setup", f"no installed header under {prefix / 'include' / 'superslm'}")
    else:
        target = headers[0]
        data = bytearray(target.read_bytes())
        i = next(k for k, b in enumerate(data) if chr(b).isalpha())
        data[i] = ord("X") if data[i] != ord("X") else ord("Y")
        target.write_bytes(bytes(data))
        rc, out = product.configure(me, src, scratch / "k9-header-build", prefix)
        report.check(rc != 0 and "SEMB_ENGINE_INSTALL_DIVERGED" in out,
                     f"(k-9) one byte of the installed header {target.relative_to(prefix).as_posix()} edited after "
                     f"the pin: configure refuses SEMB_ENGINE_INSTALL_DIVERGED", f"exit {rc}: {c51.tail(out, 3)}")

    # The CR half: one clone, pinned as the tag holds it and then with one CR before one LF of the kernel TU.
    lock = c51.LOCK.read_text(encoding="utf-8")
    tag = next(l.split("=", 1)[1] for l in lock.splitlines() if l.startswith("tag="))
    tree = next(l.split("=", 1)[1] for l in lock.splitlines() if l.startswith("tree="))
    clone = scratch / "clone"
    c51.matrix.rmtree(clone)
    proc = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "clone", "--quiet", "--branch", tag,
                           engines.source, str(clone)], capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        report.missing("(k-9) a CR in a compiled member moves engine_tree_sha",
                       f"the engine source {engines.source} could not be cloned at {tag}: {c51.tail(proc.stderr, 2)}")
        return report.exit_code()
    trees = {}
    for name, edit in (("as-tagged", False), ("cr-in-kernel", True)):
        if edit:
            path = clone / KERNEL
            data = path.read_bytes()
            at = data.index(b"\n")
            path.write_bytes(data[:at] + b"\r" + data[at:])
        pin = c51.run_pin(me, scratch / f"k9-{name}-prefix", scratch / f"k9-{name}-work", scratch / f"k9-{name}.lock",
                          engines.source, extra_args=("--reuse-clone", str(clone)) + (("--allow-dirty",) if edit else ()),
                          cmake=args.cmake_executable, ninja=args.ninja_executable)
        if not pin.ok:
            report.leg("FAIL", f"(k-9) setup: pin the {name} clone", f"exit {pin.rc}: {c51.tail(pin.output)}")
            return report.exit_code()
        trees[name] = pin.provenance()["engine_tree_sha"]
    report.check(trees["as-tagged"] == tree, "(k-9) control: the clone pinned as the tag holds it records the "
                 "committed lock's tree=", f"{trees['as-tagged']} vs {tree}")
    report.check(trees["cr-in-kernel"] != trees["as-tagged"],
                 f"(k-9) a CR inserted before one LF of the compiled member {KERNEL} in the pin tool's clone gives "
                 f"another engine_tree_sha (compiled members are read as they are)",
                 f"{trees['cr-in-kernel']} vs {trees['as-tagged']}")
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
