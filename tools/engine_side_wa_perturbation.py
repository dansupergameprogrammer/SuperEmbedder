#!/usr/bin/env python3
"""tools/engine_side_wa_perturbation.py -- TE-87 (U0 slice C, sec 4.4d item 4,
D-SLM6157): promotes D-SLM6075's own manual construction for C36(a) --
"an engine arithmetic change confined to a non-inline .cpp, this library
byte-identical, must move witness_sha" (`Claude/Plans/SuperEmbedder_Plan.md`
sec 8, C36 row (a)) -- to a named, re-runnable script. The construction
itself is already proven, executed twice, real, PASS both times (D-SLM6075);
what this script adds is durability, not a new proof.

RECIPE (unchanged from D-SLM6075's own manual run, both executed this
session against the tip's own build log,
`Claude/Brunel/te78-u0b-witness-composition-2026-09-02.md` sec 3):

  1. Build a BASELINE: clone the pinned engine tag (this repo's own
     superslm.lock, `tag=`) into a scratch directory, install it, and
     build+run a scratch `semb_witness` against it -- an unperturbed
     reading.
  2. Build a MUTANT: clone the SAME pinned tag into a SECOND scratch
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
  3. Install the mutant via `pin_superslm.py --reuse-clone`, and
     build+run a scratch `semb_witness` against it -- the mutant
     reading.
  4. Compare the two `witness_sha` values and print the verdict.

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

Prints, as its final stdout line: `witness_sha_moved: true` (the expected,
correct reading -- the engine-side edit is visible to witness_sha) or
`witness_sha_moved: false` (a real product defect: the edit is invisible).
Exit code reflects whether the RECIPE completed (0 = both readings were
taken and compared, whatever the comparison found; nonzero = an
infrastructure failure -- a clone, build, or install step itself failed,
never a reading of "false").
"""
from __future__ import annotations

import argparse
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


def generate_synthetic_artifact(*, lock: Path, out_path: Path, workdir: Path,
                                 source: str | None) -> None:
    cmd = [sys.executable,
           str(REPO_ROOT / "tests" / "fixtures" / "regenerate_synthetic_artifact.py"),
           "--lock", str(lock), "--out", str(out_path), "--workdir", str(workdir)]
    if source:
        cmd += ["--source", source]
    run(cmd)


def build_witness(*, prefix: Path, lock: Path, build_dir: Path, cmake: str, ninja: str) -> Path:
    rmtree(build_dir)
    run([cmake, "-G", "Ninja", "-S", str(REPO_ROOT), "-B", str(build_dir),
         "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_MAKE_PROGRAM={ninja}",
         f"-DCMAKE_PREFIX_PATH={prefix}", f"-DSEMB_ENGINE_LOCK_FILE={lock}"])
    run([cmake, "--build", str(build_dir), "--target", "semb_witness"])
    exe = build_dir / "semb_witness.exe"
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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scratch-root", required=True, type=Path,
                     help="every clone, build, and install this script performs lives entirely "
                          "under this directory -- it is created if it does not exist.")
    ap.add_argument("--engine-source", default=None,
                     help="git URL or local path to clone the pinned engine from (forwarded to "
                          "pin-superslm's own --source and to this script's own manual clone for "
                          "the mutant); default is the public remote, matching pin_superslm.py's "
                          "own DEFAULT_REMOTE.")
    ap.add_argument("--cmake", default=None, help="defaults to PATH, then the known VS install location")
    ap.add_argument("--ninja", default=None, help="defaults to PATH, then the known VS install location")
    args = ap.parse_args(argv)

    scratch_root: Path = args.scratch_root.resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    engine_source = args.engine_source or DEFAULT_REMOTE
    cmake = args.cmake or _find_cmake()
    ninja = args.ninja or _find_ninja()

    tracked_lock = REPO_ROOT / "superslm.lock"
    tag = read_lock_tag(tracked_lock)
    log(f"pinned tag (from {tracked_lock}): {tag}")

    baseline_dir = scratch_root / "baseline"
    mutant_dir = scratch_root / "mutant"
    rmtree(baseline_dir)
    rmtree(mutant_dir)

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
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as ex:
        log(f"FAILED: {ex}")
        raise SystemExit(2)
