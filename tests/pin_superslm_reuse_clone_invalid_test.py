"""tests/pin_superslm_reuse_clone_invalid_test.py -- TE-86 (F3, routed by
`Claude/Mendeleev/te84-u0-coverage-audit-2026-09-02.md` Finding F3, sec 3
of that case file): TE-74's own population sweep of tools/pin-superslm
left one bare cell -- `--reuse-clone` pointed at a directory that is not
a valid clone (missing entirely, or present but not at the pinned
tag/commit) had no leg.

This file constructs both members, for real, against the real
`tools/pin-superslm/pin_superslm.py` (read-only to this seat -- invoked
as a subprocess, never edited), and PINS whatever its own current
behavior actually is (`StandardsDocument.md` sec 5.4: exactness verified
by execution, never by construction) -- per this seat's own brief, if
either input produced a silent success, that would be a finding for the
builder rather than something this check papers over. Neither does:

BOTH LEGS OBSERVED THIS SESSION (real runs, quoted in this seat's own
record): `resolve_commit()`'s own `git -C <clone> rev-parse
<tag>^{commit}` fails for both a missing directory (git: "cannot change
to ... No such file or directory") and a present-but-wrong-tag directory
(git: "unknown revision or path not in the working tree"), and `run()`'s
own generic `SystemExit(f"command failed ({rc}): {cmd}")` wraps BOTH
identically -- loud, non-zero-exit, but not a NAMED SEMB_* refusal the
way every other pin_superslm.py failure mode is (SEMB_PIN_UNSAFE_BUILD_DIR,
SEMB_ENGINE_INSTALL_DIVERGED, ...). Pinned as current behavior; Note
severity, not a G0-blocking gap -- it fails loudly and is simply unnamed,
matching Mendeleev's own F3 disposition.

Usage: `python tests/pin_superslm_reuse_clone_invalid_test.py` runs both
legs and exits 0 only if both observed behaviors match what this file
pins.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIN_SCRIPT = REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py"
SCRATCH = REPO_ROOT / "build" / "_scratch" / "pin_reuse_clone_invalid_test"


def _rmtree_onerror(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def _pinned_tag() -> str:
    lock = REPO_ROOT / "superslm.lock"
    for line in lock.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("tag="):
            return line.split("=", 1)[1]
    raise RuntimeError(f"no tag= line found in {lock}")


def _run_pin(reuse_clone: Path, prefix: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIN_SCRIPT), "--lock", "superslm.lock", "--prefix", str(prefix),
         "--reuse-clone", str(reuse_clone)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def _assert_pinned_current_behavior(proc: subprocess.CompletedProcess, tag: str) -> tuple[bool, str]:
    """The behavior this file pins, both legs: a non-zero exit, the
    generic (unnamed) `command failed` wrapper, and the real git rev-parse
    invocation naming the pinned tag -- never a silent success, and never
    (today) a named SEMB_* refusal."""
    combined = proc.stdout + proc.stderr
    expected_fragment = f"rev-parse {tag}^{{commit}}"
    silent_success = proc.returncode == 0
    ok = (not silent_success) and "command failed" in combined and expected_fragment in combined
    if silent_success:
        detail = (f"SILENT SUCCESS -- rc=0 for an invalid --reuse-clone input. This is a finding "
                  f"for the builder, not pinnable as correct behavior. Output tail: {combined[-600:]}")
    else:
        detail = (f"rc={proc.returncode}; 'command failed' present={'command failed' in combined}; "
                  f"'{expected_fragment}' present={expected_fragment in combined}; output tail: "
                  f"{combined[-600:]}")
    return ok, detail


def leg_missing_directory(tag: str) -> tuple[bool, str]:
    target = SCRATCH / "does_not_exist"
    _rmtree(target)  # confirmed absent; never created by this leg
    proc = _run_pin(target, SCRATCH / "prefix_missing")
    return _assert_pinned_current_behavior(proc, tag)


def leg_wrong_tag_directory(tag: str) -> tuple[bool, str]:
    target = SCRATCH / "wrong_tag_repo"
    _rmtree(target)
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(target), check=True)
    subprocess.run(["git", "config", "user.email", "te86@example.invalid"], cwd=str(target), check=True)
    subprocess.run(["git", "config", "user.name", "TE-86"], cwd=str(target), check=True)
    (target / "unrelated.txt").write_text(
        "TE-86 F3 scratch repo -- a real git repository that never carries the pinned SuperSLM tag.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "unrelated.txt"], cwd=str(target), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "unrelated commit, no pinned tag present"],
                   cwd=str(target), check=True)
    proc = _run_pin(target, SCRATCH / "prefix_wrongtag")
    return _assert_pinned_current_behavior(proc, tag)


def main(argv: list[str]) -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tag = _pinned_tag()
    legs = [
        ("--reuse-clone against a MISSING directory", leg_missing_directory),
        ("--reuse-clone against a PRESENT directory at the wrong tag/commit", leg_wrong_tag_directory),
    ]
    all_passed = True
    for label, fn in legs:
        passed, message = fn(tag)
        all_passed = all_passed and passed
        print(f"{'PASS' if passed else 'FAIL'}: {label}: {message}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
