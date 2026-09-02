"""Shared digest logic between pin_superslm.py (which computes provenance at
pin time) and verify_provenance.py (which CMake invokes at every configure to
recompute the same digest fresh from whatever is currently on disk under the
install prefix). Both MUST use the identical formula, or a configure-time
"agrees with the prefix's own bytes" check would be comparing two different
things that happen to share a name — kept in one module specifically so they
cannot drift apart independently.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_members(members: list[tuple[str, str, bytes]]) -> str:
    """§4.1's formula: SHA256 over the path-sorted, length-prefixed sequence
    len(path) || path || len(bytes) || bytes. Each entry's `path` string is
    pre-namespaced by its closure ("compiled:<clone-relative>" or
    "installed:<prefix-relative>") — this tool's own documented choice,
    stated in the build log, since the plan's prose formula does not by
    itself disambiguate two same-named members from different closures.
    Lengths are 8-byte big-endian unsigned integers of the byte count — also
    this tool's own documented choice, since the plan does not fix an
    integer width.

    members: list of (root, relpath_posix, content_bytes)
    """
    entries = sorted(((f"{root}:{relpath}", content) for root, relpath, content in members), key=lambda e: e[0])
    h = hashlib.sha256()
    for path, content in entries:
        path_b = path.encode("utf-8")
        h.update(len(path_b).to_bytes(8, "big"))
        h.update(path_b)
        h.update(len(content).to_bytes(8, "big"))
        h.update(content)
    return h.hexdigest()
