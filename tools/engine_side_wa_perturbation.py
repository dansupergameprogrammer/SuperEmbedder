#!/usr/bin/env python3
"""Pin-bump witness constructions for C36(a) and C38.

TE-87 (U0 slice C, sec 4.4d item 4, D-SLM6157) promoted
D-SLM6075's own manual construction for C36(a) --
"an engine arithmetic change confined to a non-inline .cpp, this library
byte-identical, must move witness_sha" (`Claude/Plans/SuperEmbedder_Plan.md`
sec 8, C36 row (a)) -- to a named, re-runnable script. The construction
itself is already proven, executed twice, real, PASS both times (D-SLM6075);
what this script adds is durability, not a new proof.

RECIPE (D-SLM6075's own manual run, executed against the tip's own build
log, `Claude/Brunel/te78-u0b-witness-composition-2026-09-02.md` sec 3, plus
a must-accept step TE-89 adds -- TE-88 review S-8):

  1. Build a BASELINE: clone the pinned engine tag (this repo's own
     superslm.lock, `tag=`) into a scratch directory, install it, and
     build+run a scratch `semb_witness` against it -- an unperturbed
     reading.
  2. Build a SECOND, independently cloned+built+installed BASELINE of the
     SAME pinned tag (TE-89, S-8's own must-accept) and require its
     witness_sha to equal the first baseline's, exactly. Without this,
     `witness_sha_moved: true` in step 4 below is equally consistent with
     "the perturbation moved the digest" and with "any second build moves
     the digest" -- ordinary, undetected nondeterminism -- and the leg
     could never fail on the property it exists to catch. This step
     raises (an infrastructure-shaped failure, not a printed
     witness_sha_moved reading) if the two baselines disagree.
  3. Build a MUTANT: clone the SAME pinned tag into a THIRD scratch
     directory, perturb ONE non-inline arithmetic site --
     `EmbedEntry` in `src/forward/forward_sites.cpp`, D-SLM6075's own
     site -- commit the edit, then force-move the clone's own LOCAL tag
     to the commit carrying it (`git tag -f <tag> HEAD`) so
     `tools/pin-superslm/pin_superslm.py`'s own provenance guard reads
     the clone as clean RELATIVE TO ITSELF. This does not bypass
     SEMB_ENGINE_INSTALL_DIVERGED -- it satisfies the guard's own real
     check (disk matches what the tag resolves to, inside a throwaway
     clone the tracked repo never sees) so the CONSTRUCTION under test
     (does witness_sha move) can be isolated from the guard, which is a
     separate, correctly-firing check on a genuinely dirty clone.
  4. Install the mutant via `pin_superslm.py --reuse-clone`, and
     build+run a scratch `semb_witness` against it -- the mutant
     reading.
  5. Compare the mutant reading against the (now must-accept-commissioned)
     baseline and print the C36(a) verdict.
  6. Clone the same tag into a FOURTH scratch directory and inject a
     `SUPERSLM_C38_INLINE_PERTURBATION` branch into the installed-inline
     `ReadCarriedScale` primitive in `include/superslm/layer_marshal.h`.
     The branch changes only the `embed` carried-scale exponent, and only
     when its compile definition is visible in the translation unit that
     instantiates the inline function. Commit and locally retag this clone
     exactly as for the C36(a) mutant, then install it.
  7. Against that one injected-header install, build three downstream
     variants: no definition, definition private to `superembedder`, and
     definition private to `semb_witness`. The no-definition and
     witness-only readings must equal baseline; the library-definition
     reading must differ. This proves both halves of C38 without requiring
     a test hook in a released SuperSLM tag.

NEVER TOUCHES THE TRACKED, LOCAL SUPERSLM ENGINE CHECKOUT this project
treats as read-only. Every clone, build, and install in this recipe
happens under `--scratch-root`; the engine source is cloned from
`--engine-source` (a git URL or a local path, forwarded to
`pin-superslm`'s own `--source` and to this script's own manual clone for
the mutant -- default is the public remote, matching `pin_superslm.py`'s
own `DEFAULT_REMOTE`). `tools/pin-superslm/pin_superslm.py` is invoked as
a subprocess and never edited by this script.

USAGE
  python tools/engine_side_wa_perturbation.py --scratch-root <dir>
      [--engine-source <path-or-url>] [--cmake <path>] [--ninja <path>]
  python tools/engine_side_wa_perturbation.py --selftest-only

Prints the C36(a) field `witness_sha_moved` and the C38 fields
`c38_injected_branch_inert`, `c38_library_define_moved`, and
`c38_witness_define_inert`. `--selftest-only` cheaply commissions the C38
comparison logic and prints `c38_selftest: PASS`.
Exit code reflects whether the RECIPE completed (0 = the must-accept held
and both readings were taken and compared, whatever the comparison found;
nonzero = an infrastructure failure -- a clone, build, or install step
itself failed, OR the must-accept step failed (two unperturbed baselines
disagreed) -- never a reading of "false").
"""
from __future__ import annotations

import argparse
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REMOTE = "https://github.com/dansupergameprogrammer/SuperSLM.git"


def log(msg: str) -> None:
    # ASCII-sanitized for the identical reason run()'s own output is
    # (see _ascii_safe's docstring, below) -- msg can itself carry a
    # subprocess's own raw text (e.g. an exception message quoting a
    # child's stderr).
    print(f"[engine_side_wa_perturbation] {msg}".encode("ascii", errors="replace").decode("ascii"),
          flush=True)


def _rmtree_onerror(func, path, exc_info):
    # git's own object store is read-only on disk; clear the bit and retry
    # once -- the standard Windows workaround, matching pin_superslm.py's
    # own helper of the same name.
    import os
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def _ascii_safe(s: str) -> str:
    """This script is always invoked as a subprocess -- directly by a
    caller, or via tests/witness_structural_matrix.py's own eval_c36_a(),
    which captures this process's stdout/stderr with `text=True` and no
    explicit `encoding=`, so it decodes with this box's ambient locale
    encoding (cp1252, observed). Every git/cmake/ninja invocation this
    recipe runs can legitimately print a byte outside cp1252's own
    repertoire (five byte values are undefined in cp1252) and, once,
    crashed that caller's own decode with an unhandled UnicodeDecodeError
    (TE-87). Plain ASCII round-trips cleanly through every text encoding,
    so every byte this process EMITS is kept inside it -- the safety net
    applies at the print boundary, not at every individual read."""
    return s.encode("ascii", errors="replace").decode("ascii")


def run(cmd, cwd=None, check=True):
    log("+ " + " ".join(str(c) for c in cmd))
    # decoded as UTF-8 with errors="replace" (never this process's own
    # ambient locale) so a child's own non-ASCII byte cannot crash THIS
    # process's decode either -- only the final _ascii_safe() print is
    # load-bearing for the caller-side crash this fixes, but a decode
    # that cannot itself raise is one fewer failure mode to reason about.
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    stdout = _ascii_safe(proc.stdout or "")
    stderr = _ascii_safe(proc.stderr or "")
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed (rc={proc.returncode}): {' '.join(str(c) for c in cmd)}")
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def _find_cmake() -> str:
    found = shutil.which("cmake")
    if found:
        return found
    candidate = Path("C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/"
                      "CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe")
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("no cmake executable found on PATH or at the known VS install location")


def _find_ninja() -> str:
    found = shutil.which("ninja")
    if found:
        return found
    candidate = Path("C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/"
                      "CommonExtensions/Microsoft/CMake/Ninja/ninja.exe")
    if candidate.exists():
        return str(candidate)
    raise RuntimeError("no ninja executable found on PATH or at the known VS install location")


def read_lock_tag(lock_path: Path) -> str:
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("tag="):
            return line[len("tag="):].strip()
    raise ValueError(f"{lock_path}: no 'tag=' line found")


def write_scratch_lock(path: Path, tag: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # pin_superslm.py's own parse_lock() only requires 'tag=' up front --
    # it computes and writes 'commit=' and 'tree=' itself.
    path.write_text(f"tag={tag}\n", encoding="utf-8", newline="\n")


def pin_engine(*, lock: Path, prefix: Path, workdir: Path, cmake: str, ninja: str,
                source: str | None = None, reuse_clone: Path | None = None) -> None:
    cmd = [sys.executable, str(REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py"),
           "--lock", str(lock), "--prefix", str(prefix), "--workdir", str(workdir),
           "--cmake", cmake, "--ninja", ninja, "--generator", "Ninja"]
    if reuse_clone is not None:
        cmd += ["--reuse-clone", str(reuse_clone)]
    elif source:
        cmd += ["--source", source]
    run(cmd)


def clone_engine_manually(source: str, tag: str, dest: Path) -> None:
    """Mirrors pin_superslm.py's own clone_engine() -- used only for the
    MUTANT path, where the clone must be perturbed BEFORE pin_superslm.py
    ever sees it (pin_superslm.py's own clone+build+install is one atomic
    sequence with no hook to pause in the middle)."""
    rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
         "-c", "core.longpaths=true", "--branch", tag, "--single-branch",
         source, str(dest)])


def perturb_embed_entry(clone: Path, tag: str) -> None:
    """D-SLM6075's own site and edit: XOR the low bit of EmbedEntry's
    widened value -- a real, non-inline arithmetic change reaching every
    embedded position, always within int8's own legal range. Commits the
    edit, then force-moves the clone's own LOCAL tag to the commit
    carrying it, so pin_superslm.py's own provenance guard (git_clean_check)
    reads the clone as clean relative to itself.

    newline="" on BOTH read and write (TE-87, found by real execution):
    the engine's own source tree is checked out LF-only (this clone's own
    core.eol=lf). Path.write_text() with no explicit `newline=` argument
    translates every '\\n' in the string to os.linesep on write --
    os.linesep is '\\r\\n' on Windows -- which silently reintroduced CRLF
    into an LF file. git's OWN clean filter then normalizes it back to LF
    at commit time (the "CRLF will be replaced by LF" warning), so the
    COMMITTED BLOB is correctly LF -- but the WORKING-TREE file this
    function leaves on disk stays CRLF, unnoticed by pin_superslm.py's own
    git_clean_check (which re-applies the SAME clean filter before
    hashing, so a CRLF working copy and an LF blob still agree there) and
    caught only by verify_provenance.py's later RAW byte-for-byte snapshot
    comparison (SEMB_ENGINE_INSTALL_DIVERGED) at SuperEmbedder's own
    configure time -- a real, reproducible construction failure, not a
    flaky one. newline="" disables all translation on both sides, so the
    string's own '\\n' characters are read and written byte-for-byte."""
    target = clone / "src" / "forward" / "forward_sites.cpp"
    if not target.exists():
        raise RuntimeError(f"expected engine source file not found: {target}")
    # pathlib.Path.read_text() gained a `newline=` argument only in Python
    # 3.13; this box runs 3.12 (found by real execution: TypeError,
    # "unexpected keyword argument 'newline'"). io.open() has supported it
    # since Python 3, so it is used directly instead of Path's own
    # convenience wrapper.
    with open(target, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    old = "\t\twide[i] = static_cast<int64_t>(row[i]);\n"
    new = "\t\twide[i] = static_cast<int64_t>(static_cast<int8_t>(row[i] ^ 1));  " \
          "// engine_side_wa_perturbation.py -- real, non-inline arithmetic perturbation\n"
    if old not in text:
        raise RuntimeError(
            f"EmbedEntry's own anchor line not found in {target} -- the engine source has moved; "
            f"this script's perturbation site needs updating"
        )
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old, new, 1))

    run(["git", "-C", str(clone), "-c", "user.email=semb-scratch@localhost",
         "-c", "user.name=SuperEmbedder scratch perturbation",
         "commit", "-am", "scratch perturbation for C36(a): XOR the low bit in EmbedEntry"])
    run(["git", "-C", str(clone), "tag", "-f", tag, "HEAD"])


def perturb_inline_read_carried_scale(clone: Path, tag: str) -> None:
    """Injects C38's scratch-only branch into the real installed inline site.

    The tracked engine checkout and released tag remain untouched. As with
    perturb_embed_entry(), newline translation is disabled so the committed
    blob and installed provenance snapshot are byte-identical on Windows.
    """
    target = clone / "include" / "superslm" / "layer_marshal.h"
    if not target.exists():
        raise RuntimeError(f"expected installed engine header not found: {target}")
    with open(target, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    old = (
        "\treturn superslm::CarriedScale{superslm::SslmKeyedConstants::Value(*e, 0),\n"
        "\t                               superslm::SslmKeyedConstants::Value(*e, 1)};\n"
    )
    new = (
        "\tconst int64_t carried_m = superslm::SslmKeyedConstants::Value(*e, 0);\n"
        "\tint64_t carried_e = superslm::SslmKeyedConstants::Value(*e, 1);\n"
        "#if defined(SUPERSLM_C38_INLINE_PERTURBATION)\n"
        "\t// Scratch-only C38 construction: a visible, material change at the real inline site.\n"
        "\tif (name == \"embed\") ++carried_e;\n"
        "#endif\n"
        "\treturn superslm::CarriedScale{carried_m, carried_e};\n"
    )
    if old not in text:
        raise RuntimeError(
            f"ReadCarriedScale's return anchor was not found in {target} -- the pinned engine "
            "header has moved; C38's scratch injection needs updating"
        )
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace(old, new, 1))

    run(["git", "-C", str(clone), "-c", "user.email=semb-scratch@localhost",
         "-c", "user.name=SuperEmbedder scratch perturbation", "commit", "-am",
         "scratch perturbation for C38: gate ReadCarriedScale embed exponent"])
    run(["git", "-C", str(clone), "tag", "-f", tag, "HEAD"])


def generate_synthetic_artifact(*, lock: Path, out_path: Path, workdir: Path,
                                 source: str | None) -> None:
    cmd = [sys.executable,
           str(REPO_ROOT / "tests" / "fixtures" / "regenerate_synthetic_artifact.py"),
           "--lock", str(lock), "--out", str(out_path), "--workdir", str(workdir)]
    if source:
        cmd += ["--source", source]
    run(cmd)


def read_artifact_manifest(build_dir: Path) -> dict:
    """TE-89 (TE-88 review C-1): matches
    tests/witness_structural_matrix.py's own read_artifact_manifest() --
    CMakeLists.txt's own file(GENERATE) call writes
    `<build_dir>/semb_artifact_manifest.json` at configure time from
    $<TARGET_FILE:...>, CMake's own always-correct-for-the-platform
    resolution of a target's real output path. This is what lets
    build_witness() below stop hardcoding "semb_witness.exe" -- a name
    that does not exist on ubuntu-latest/macos-latest, where this script
    also runs (at every pin bump, not only on Windows)."""
    manifest_path = build_dir / "semb_artifact_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            f"artifact manifest not found: {manifest_path} -- this build directory's own configure "
            f"did not generate it (CMakeLists.txt's own file(GENERATE) call, "
            f"semb_artifact_manifest.json)"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def build_witness(*, prefix: Path, lock: Path, build_dir: Path, cmake: str, ninja: str,
                  c38_define_target: str = "") -> Path:
    rmtree(build_dir)
    configure = [cmake, "-G", "Ninja", "-S", str(REPO_ROOT), "-B", str(build_dir),
                 "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_MAKE_PROGRAM={ninja}",
                 f"-DCMAKE_PREFIX_PATH={prefix}", f"-DSEMB_ENGINE_LOCK_FILE={lock}",
                 f"-DPython3_EXECUTABLE={sys.executable}"]
    if c38_define_target:
        configure.append(f"-DSEMB_C38_DEFINE_TARGET={c38_define_target}")
    run(configure)
    manifest = read_artifact_manifest(build_dir)
    exe = Path(manifest["semb_witness"])
    run([cmake, "--build", str(build_dir), "--target", "semb_witness"])
    if not exe.exists():
        raise RuntimeError(f"build reported success but {exe} does not exist")
    return exe


def run_witness(exe: Path, model_path: Path, tokens_csv: str = "3,17,42,5,90") -> str:
    proc = subprocess.run([str(exe), "--model", str(model_path), "--tokens", tokens_csv,
                            "--chunk-budget", "0"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"semb_witness exited {proc.returncode}: {proc.stdout}\n{proc.stderr}")
    for tok in proc.stdout.split():
        if tok.startswith("witness_sha="):
            return tok.split("=", 1)[1]
    raise RuntimeError(f"witness ran but printed no witness_sha: {proc.stdout!r}")


def c38_verdict(*, baseline: str, injected: str, library: str, witness: str) -> tuple[bool, bool, bool]:
    """Returns C38's three independently reportable comparisons."""
    return injected == baseline, library != baseline, witness == baseline


def c38_selftest() -> None:
    """Must-accept and must-reject commissioning for C38's verdict logic."""
    accepted = c38_verdict(baseline="A", injected="A", library="B", witness="A")
    rejected = (
        c38_verdict(baseline="A", injected="B", library="B", witness="A"),
        c38_verdict(baseline="A", injected="A", library="A", witness="A"),
        c38_verdict(baseline="A", injected="A", library="B", witness="B"),
    )
    if accepted != (True, True, True) or any(all(reading) for reading in rejected):
        raise RuntimeError(
            f"C38 verdict self-test failed: accepted={accepted}, rejected={rejected}"
        )
    print("c38_selftest: PASS")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scratch-root", type=Path,
                      help="every clone, build, and install this script performs lives entirely "
                           "under this directory -- it is created if it does not exist.")
    ap.add_argument("--selftest-only", action="store_true",
                    help="commission the C38 comparison logic without cloning or building")
    ap.add_argument("--engine-source", default=None,
                     help="git URL or local path to clone the pinned engine from (forwarded to "
                          "pin-superslm's own --source and to this script's own manual clone for "
                          "the mutant); default is the public remote, matching pin_superslm.py's "
                          "own DEFAULT_REMOTE.")
    ap.add_argument("--cmake", default=None, help="defaults to PATH, then the known VS install location")
    ap.add_argument("--ninja", default=None, help="defaults to PATH, then the known VS install location")
    args = ap.parse_args(argv)

    if args.selftest_only:
        c38_selftest()
        return 0
    if args.scratch_root is None:
        ap.error("--scratch-root is required unless --selftest-only is used")

    scratch_root: Path = args.scratch_root.resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    engine_source = args.engine_source or DEFAULT_REMOTE
    cmake = args.cmake or _find_cmake()
    ninja = args.ninja or _find_ninja()

    tracked_lock = REPO_ROOT / "superslm.lock"
    tag = read_lock_tag(tracked_lock)
    log(f"pinned tag (from {tracked_lock}): {tag}")

    baseline_dir = scratch_root / "baseline"
    baseline2_dir = scratch_root / "baseline2"
    mutant_dir = scratch_root / "mutant"
    inline_mutant_dir = scratch_root / "inline_mutant"
    rmtree(baseline_dir)
    rmtree(baseline2_dir)
    rmtree(mutant_dir)
    rmtree(inline_mutant_dir)

    # -------------------------------------------------------------- baseline --
    log("=== baseline: unperturbed pinned engine ===")
    baseline_lock = baseline_dir / "superslm.lock"
    write_scratch_lock(baseline_lock, tag)
    baseline_prefix = baseline_dir / "engine_install"
    pin_engine(lock=baseline_lock, prefix=baseline_prefix, workdir=baseline_dir / "engine_workdir",
               cmake=cmake, ninja=ninja, source=engine_source)
    baseline_exe = build_witness(prefix=baseline_prefix, lock=baseline_lock,
                                  build_dir=baseline_dir / "semb_build", cmake=cmake, ninja=ninja)

    # ----------------------------------------------------------- synthetic --
    artifact_path = scratch_root / "synthetic_artifact.sslm"
    generate_synthetic_artifact(lock=baseline_lock, out_path=artifact_path,
                                 workdir=scratch_root / "synthetic_workdir", source=engine_source)

    baseline_sha = run_witness(baseline_exe, artifact_path)
    log(f"baseline witness_sha = {baseline_sha}")

    # ------------------------------------------------- baseline2 (must-accept) --
    # TE-89 (TE-88 review S-8): `differ=True` between baseline and mutant
    # decides a GATE cell (C36(a)), and nothing before this round
    # established that two UNPERTURBED builds agree -- without that, a
    # differing mutant reading is equally consistent with "the perturbation
    # moved the digest" (the property this script exists to catch) and
    # with "any second build moves the digest" (ordinary, undetected
    # nondeterminism), and the leg could never fail. A second,
    # independently cloned, built, and installed copy of the SAME pinned
    # tag -- never touched by perturb_embed_entry() -- must reproduce the
    # first baseline's own witness_sha exactly before the mutant reading
    # below is trusted either way.
    log("=== baseline2: a SECOND, independently cloned+built+installed unperturbed pinned engine "
        "(must-accept) ===")
    baseline2_lock = baseline2_dir / "superslm.lock"
    write_scratch_lock(baseline2_lock, tag)
    baseline2_prefix = baseline2_dir / "engine_install"
    pin_engine(lock=baseline2_lock, prefix=baseline2_prefix, workdir=baseline2_dir / "engine_workdir",
               cmake=cmake, ninja=ninja, source=engine_source)
    baseline2_exe = build_witness(prefix=baseline2_prefix, lock=baseline2_lock,
                                   build_dir=baseline2_dir / "semb_build", cmake=cmake, ninja=ninja)
    baseline2_sha = run_witness(baseline2_exe, artifact_path)
    log(f"baseline2 witness_sha = {baseline2_sha}")
    if baseline2_sha != baseline_sha:
        raise RuntimeError(
            f"MUST-ACCEPT FAILED: two independently cloned, built, and installed UNPERTURBED "
            f"copies of the SAME pinned engine tag ({tag}) produced DIFFERENT witness_sha values "
            f"(baseline={baseline_sha}, baseline2={baseline2_sha}). Without this holding, a "
            f"differing mutant reading below is equally consistent with 'the perturbation moved "
            f"the digest' and with 'any second build moves the digest' -- this script's own "
            f"witness_sha_moved verdict cannot be trusted either way until the must-accept holds."
        )
    log("baseline2 == baseline -- must-accept holds; the mutant reading below is now meaningful")

    # ---------------------------------------------------------------- mutant --
    log("=== mutant: EmbedEntry perturbed (D-SLM6075's own site) ===")
    mutant_src = mutant_dir / "engine_src"
    clone_engine_manually(engine_source, tag, mutant_src)
    perturb_embed_entry(mutant_src, tag)

    mutant_lock = mutant_dir / "superslm.lock"
    write_scratch_lock(mutant_lock, tag)
    mutant_prefix = mutant_dir / "engine_install"
    pin_engine(lock=mutant_lock, prefix=mutant_prefix, workdir=mutant_dir / "engine_workdir",
               cmake=cmake, ninja=ninja, reuse_clone=mutant_src)
    mutant_exe = build_witness(prefix=mutant_prefix, lock=mutant_lock,
                                build_dir=mutant_dir / "semb_build", cmake=cmake, ninja=ninja)

    mutant_sha = run_witness(mutant_exe, artifact_path)
    log(f"mutant witness_sha = {mutant_sha}")

    moved = baseline_sha != mutant_sha
    log(f"baseline={baseline_sha}")
    log(f"mutant={mutant_sha}")
    log(f"differ={moved}")
    print(f"witness_sha_moved: {'true' if moved else 'false'}")

    # ------------------------------------------------------ C38 inline mutant --
    log("=== C38: scratch-injected ReadCarriedScale branch ===")
    inline_mutant_src = inline_mutant_dir / "engine_src"
    clone_engine_manually(engine_source, tag, inline_mutant_src)
    perturb_inline_read_carried_scale(inline_mutant_src, tag)

    inline_mutant_lock = inline_mutant_dir / "superslm.lock"
    write_scratch_lock(inline_mutant_lock, tag)
    inline_mutant_prefix = inline_mutant_dir / "engine_install"
    pin_engine(lock=inline_mutant_lock, prefix=inline_mutant_prefix,
               workdir=inline_mutant_dir / "engine_workdir", cmake=cmake, ninja=ninja,
               reuse_clone=inline_mutant_src)

    injected_exe = build_witness(
        prefix=inline_mutant_prefix, lock=inline_mutant_lock,
        build_dir=inline_mutant_dir / "semb_build_inert", cmake=cmake, ninja=ninja)
    library_exe = build_witness(
        prefix=inline_mutant_prefix, lock=inline_mutant_lock,
        build_dir=inline_mutant_dir / "semb_build_library", cmake=cmake, ninja=ninja,
        c38_define_target="library")
    witness_exe = build_witness(
        prefix=inline_mutant_prefix, lock=inline_mutant_lock,
        build_dir=inline_mutant_dir / "semb_build_witness", cmake=cmake, ninja=ninja,
        c38_define_target="witness")

    injected_sha = run_witness(injected_exe, artifact_path)
    library_sha = run_witness(library_exe, artifact_path)
    witness_sha = run_witness(witness_exe, artifact_path)
    injected_inert, library_moved, witness_inert = c38_verdict(
        baseline=baseline_sha, injected=injected_sha, library=library_sha, witness=witness_sha)
    log(f"C38 baseline={baseline_sha}")
    log(f"C38 injected/no-define={injected_sha}")
    log(f"C38 library-define={library_sha}")
    log(f"C38 witness-define={witness_sha}")
    print(f"c38_injected_branch_inert: {'true' if injected_inert else 'false'}")
    print(f"c38_library_define_moved: {'true' if library_moved else 'false'}")
    print(f"c38_witness_define_inert: {'true' if witness_inert else 'false'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as ex:
        log(f"FAILED: {ex}")
        raise SystemExit(2)
