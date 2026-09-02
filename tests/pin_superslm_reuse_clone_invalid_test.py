"""tests/pin_superslm_reuse_clone_invalid_test.py -- TE-86 (F3, routed by
`Claude/Mendeleev/te84-u0-coverage-audit-2026-09-02.md` Finding F3, sec 3
of that case file), RE-PINNED TE-87 (`Claude/Plans/SuperEmbedder_Plan.md`
sec 4.4d's own Note): TE-74's own population sweep of tools/pin-superslm
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

BOTH LEGS OBSERVED, TE-86: `resolve_commit()`'s own `git -C <clone>
rev-parse <tag>^{commit}` failed for both a missing directory and a
present-but-wrong-tag directory, and `run()`'s own generic
`SystemExit(f"command failed ({rc}): {cmd}")` wrapped BOTH identically --
loud, non-zero-exit, but not a NAMED SEMB_* refusal the way every other
pin_superslm.py failure mode was (SEMB_PIN_UNSAFE_BUILD_DIR,
SEMB_ENGINE_INSTALL_DIVERGED, ...). Pinned then as current behavior; Note
severity, not a G0-blocking gap.

RE-PINNED, TE-87 (sec 4.4d's own Note: "refuse by name for each"):
`pin_superslm.py` now validates `--reuse-clone` directly, before
`resolve_commit()` ever runs (`_validate_reuse_clone()`), and refuses by
NAME for each of the two members this file constructed at TE-87 --
`SEMB_PIN_REUSE_CLONE_NOT_FOUND` for a missing directory,
`SEMB_PIN_REUSE_CLONE_TAG_MISMATCH` for a present directory that does not
carry the pinned tag. The pin below moved with the behavior it pins, in
the same round that changed the behavior -- the generic `command failed`
wrapper this file pinned at TE-86 no longer appears on either leg.

RE-PINNED AGAIN, TE-89 (TE-88 review M-3): `SEMB_PIN_REUSE_CLONE_TAG_MISMATCH`
also fired for a directory that EXISTS but was never a git repository at
all -- a condition distinct from "a real checkout that lacks the pinned
tag." `_validate_reuse_clone()` now probes `git rev-parse --git-dir`
first and refuses SEMB_PIN_REUSE_CLONE_NOT_A_REPO for that case
specifically; `leg_not_a_git_repo_directory()` below constructs it and
pins the corrected, separate status.

Usage: `python tests/pin_superslm_reuse_clone_invalid_test.py` runs all
three legs and exits 0 only if every observed behavior matches what this
file pins.
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


def _run_pin(reuse_clone: Path, prefix: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PIN_SCRIPT), "--lock", "superslm.lock", "--prefix", str(prefix),
         "--reuse-clone", str(reuse_clone)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def _assert_named_refusal(proc: subprocess.CompletedProcess, expected_status: str) -> tuple[bool, str]:
    """The behavior this file pins, both legs, since TE-87: a non-zero
    exit and the NAMED SEMB_* refusal `expected_status` -- never a silent
    success, and never (since TE-87) the generic, unnamed `command failed`
    wrapper this file pinned at TE-86."""
    combined = proc.stdout + proc.stderr
    silent_success = proc.returncode == 0
    ok = (not silent_success) and expected_status in combined
    if silent_success:
        detail = (f"SILENT SUCCESS -- rc=0 for an invalid --reuse-clone input. This is a finding "
                  f"for the builder, not pinnable as correct behavior. Output tail: {combined[-600:]}")
    else:
        detail = (f"rc={proc.returncode}; '{expected_status}' present={expected_status in combined}; "
                  f"output tail: {combined[-600:]}")
    return ok, detail


def leg_missing_directory() -> tuple[bool, str]:
    target = SCRATCH / "does_not_exist"
    _rmtree(target)  # confirmed absent; never created by this leg
    proc = _run_pin(target, SCRATCH / "prefix_missing")
    return _assert_named_refusal(proc, "SEMB_PIN_REUSE_CLONE_NOT_FOUND")


def leg_not_a_git_repo_directory() -> tuple[bool, str]:
    """TE-89 (TE-88 review M-3): a directory that EXISTS but was never a
    git repository at all -- distinct from leg_wrong_tag_directory()'s own
    directory below, which IS a real git repository, just not one carrying
    the pinned tag. Before TE-89, `_validate_reuse_clone()`'s own `git
    rev-parse <tag>^{commit}` call reported SEMB_PIN_REUSE_CLONE_TAG_MISMATCH
    for both conditions identically; this leg pins the corrected, separate
    status."""
    target = SCRATCH / "not_a_repo"
    _rmtree(target)
    target.mkdir(parents=True)
    (target / "unrelated.txt").write_text(
        "TE-89 M-3 scratch directory -- exists, but is never `git init`'d.\n", encoding="utf-8"
    )
    proc = _run_pin(target, SCRATCH / "prefix_not_a_repo")
    return _assert_named_refusal(proc, "SEMB_PIN_REUSE_CLONE_NOT_A_REPO")


def leg_wrong_tag_directory() -> tuple[bool, str]:
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
    return _assert_named_refusal(proc, "SEMB_PIN_REUSE_CLONE_TAG_MISMATCH")


def main(argv: list[str]) -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    legs = [
        ("--reuse-clone against a MISSING directory", leg_missing_directory),
        ("--reuse-clone against a PRESENT directory that is not a git repository at all",
         leg_not_a_git_repo_directory),
        ("--reuse-clone against a PRESENT directory at the wrong tag/commit", leg_wrong_tag_directory),
    ]
    all_passed = True
    for label, fn in legs:
        passed, message = fn()
        all_passed = all_passed and passed
        print(f"{'PASS' if passed else 'FAIL'}: {label}: {message}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
