"""tests/fixtures/regenerate_synthetic_artifact.py -- TE-62 (U0 slice B):
regenerates the tiny synthetic `.sslm` artifact C39/C40's seam-digest cells
build against, from the PINNED engine clone's own T-2199 Phase D S8
generator (`tools/_t2199_s8_synthetic_full_model_fixture.py`), at the exact
tag `superslm.lock` names.

HERMETIC, NEVER COMMITTED AS A BLOB -- matching the discipline sec 4.4b's
own W-B corpus is held to at U1 ("committed as data... with a SHA-256
manifest") applied here to a GENERATED artifact instead: this script
clones the pinned engine tag into a scratch directory (the same mechanism
`tools/pin-superslm/pin_superslm.py` already uses for the engine build
itself -- `git clone -c core.autocrlf=false -c core.eol=lf --branch <tag>
--single-branch`), runs the generator UNMODIFIED from that clone, and
deletes the clone afterward. Two runs on the same pinned tag must produce
byte-identical output (`--verify-determinism` re-runs the generator twice
and compares) -- the artifact itself is never checked into this repository.

WHY THIS SCRIPT EXISTS RATHER THAN A COMMITTED FIXTURE. The generator
(`tools/reference_pipeline/pipeline.py`'s `fixture_model` plus
`convert_model.build_sections`) lives in the ENGINE repository, at the
version this project's `superslm.lock` pins -- reading it out at pin time
keeps the fixture and the pinned engine version from drifting apart the
way a committed binary would the moment the pin moves.

USAGE
  python tests/fixtures/regenerate_synthetic_artifact.py \\
      --lock superslm.lock --out <path>.sslm [--source <path-or-url>]
      [--workdir <scratch dir>] [--verify-determinism]

Exit codes: 0 success; 1 usage/environment error; 2 clone/generation
failure; 3 determinism check failed.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

DEFAULT_REMOTE = "https://github.com/dansupergameprogrammer/SuperSLM.git"


def _rmtree_onerror(func, path, exc_info):
    import os
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def read_lock_tag(lock_path: Path) -> str:
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("tag="):
            return line[len("tag="):]
    raise ValueError(f"{lock_path}: no 'tag=' line found")


def clone_engine_tools(tag: str, source: str, workdir: Path) -> Path:
    rmtree(workdir)
    workdir.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
         "--branch", tag, "--single-branch", source, str(workdir)],
        check=True,
    )
    return workdir


def generate(tools_dir: Path, out_path: Path) -> bytes:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    # Imported here, not at module scope: this module must be importable
    # (and its own --help usable) even when no engine clone exists yet.
    import importlib
    for mod in ("convert_model", "pipeline", "sslm_convert_schema", "sslm_format",
                "t2132_build_g5_fixture", "_t2199_s8_synthetic_full_model_fixture"):
        importlib.import_module(mod)
    fixture = sys.modules["_t2199_s8_synthetic_full_model_fixture"]
    data, fingerprint, fold_err = fixture.build_artifact_bytes()
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, fingerprint={fingerprint}, "
          f"fold_approximation_error={fold_err}")
    return data


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="superslm.lock")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=DEFAULT_REMOTE)
    ap.add_argument("--workdir", default="build/_synthetic_fixture_workdir")
    ap.add_argument("--verify-determinism", action="store_true")
    args = ap.parse_args(argv)

    lock_path = Path(args.lock)
    if not lock_path.exists():
        print(f"SEMB_FIXTURE_LOCK_MISSING: {lock_path} does not exist.", file=sys.stderr)
        return 1
    tag = read_lock_tag(lock_path)
    print(f"regenerating the synthetic artifact from pinned tag {tag}")

    workdir = Path(args.workdir)
    try:
        clone = clone_engine_tools(tag, args.source, workdir)
    except subprocess.CalledProcessError as ex:
        print(f"SEMB_FIXTURE_CLONE_FAILED: {ex}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data1 = generate(clone / "tools", out_path)
    except Exception as ex:  # noqa: BLE001 -- reported, not swallowed
        print(f"SEMB_FIXTURE_GENERATION_FAILED: {ex}", file=sys.stderr)
        rmtree(workdir)
        return 2

    if args.verify_determinism:
        # TE-80 (TE-76 review F-12, Significant): the prior version called
        # generate() a SECOND TIME IN THIS SAME PROCESS -- every module was
        # already imported, and per-process state (PYTHONHASHSEED, set/dict
        # iteration order, interned module globals) is fixed for the life of
        # a process, which is exactly the dominant nondeterminism class for a
        # Python artifact generator and exactly what an in-process second call
        # cannot see. This now spawns a GENUINELY SEPARATE process -- a fresh
        # `python this_script.py` invocation, its own interpreter, its own
        # clone, its own workdir -- and compares the file it writes to disk,
        # never a value passed back in memory.
        out_path2 = out_path.with_suffix(out_path.suffix + '.verify')
        workdir2 = workdir.parent / (workdir.name + '_verify2')
        verify_cmd = [sys.executable, str(Path(__file__).resolve()),
                      '--lock', args.lock, '--out', str(out_path2),
                      '--source', args.source, '--workdir', str(workdir2)]
        subprocess.run(verify_cmd, check=True)
        data2 = out_path2.read_bytes()
        h1, h2 = hashlib.sha256(data1).hexdigest(), hashlib.sha256(data2).hexdigest()
        out_path2.unlink(missing_ok=True)
        if h1 != h2:
            print(f'SEMB_FIXTURE_NOT_DETERMINISTIC: {h1} != {h2} across two independent '
                  f'process invocations of the same pinned generator.', file=sys.stderr)
            rmtree(workdir)
            return 3
        print(f'determinism verified: two independent PROCESSES both hash to {h1}')

    rmtree(workdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
