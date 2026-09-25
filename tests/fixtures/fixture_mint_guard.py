"""tests/fixtures/fixture_mint_guard.py -- what lets two fixture mints run at once.

ctest -j runs several tests at once, and many of them mint a fixture on
first use through one of the regenerators in this directory. Two things
used to be shared between those concurrent mints:

  1. The scratch clone of the pinned engine. Every regenerator cloned into
     one fixed directory (for example build/_u1_pair_fixture_workdir) and
     deleted it first, so a second mint deleted the first one's clone in the
     middle of its run ("could not set 'core.repositoryformatversion'",
     SEMB_FIXTURE_CLONE_FAILED). private_workdir() gives each process its own
     directory unless the caller names one.

  2. The output. Two tests that need the same pair (build/_scratch/u2_9_min_pair,
     build/_scratch/te222_c17_pair, ...) both see it absent, both mint it, and
     the later mint truncates and rewrites files the earlier test is already
     reading. hold_output_lock() serializes mints of the same output with an
     OS lock that is released when the process exits (also when a ctest
     timeout kills it, so a killed mint never leaves a stale lock), and
     minted_since() lets a mint that waited on the lock see that the run it
     waited for has just written the output, and reuse it instead of
     rewriting it. The inputs are identical (same lock, same generator, same
     output path), so the output is too.

Harness plumbing only: no fixture byte depends on anything here.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, Optional


def private_workdir(requested: Optional[str], stem: str) -> Path:
    """The caller's --workdir when one was given, else a fresh build/<stem>.* directory."""
    if requested:
        return Path(requested)
    parent = Path("build")
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=stem + ".", dir=str(parent)))


def hold_output_lock(target: Path) -> BinaryIO:
    """Block until this process holds the mint lock for `target`; hold it until exit.

    The returned file object owns the lock: keep a reference to it for the
    rest of the mint. The OS drops the lock when the process ends."""
    lock_path = target.parent / (target.name + ".mint.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    if os.name == "nt":
        import msvcrt
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # retries for ~10 s, then raises
                break
            except OSError:
                continue
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def minted_since(target: Path, started: float) -> bool:
    """True when `target` was written at or after `started` (a time.time() reading)."""
    try:
        return target.stat().st_mtime >= started
    except FileNotFoundError:
        return False


def now() -> float:
    return time.time()
