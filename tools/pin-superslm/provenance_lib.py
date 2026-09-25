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


DIGEST_FORMULA = ("sha256 over path-sorted entries len(path_utf8:8BE) || path || len(bytes:8BE) || bytes; "
                  "path is '<root>:<relpath-posix>' with root in {compiled, installed}; installed members are "
                  "read with CRLF as LF, compiled members as the LF clone holds them")


def member_bytes(root: str, content: bytes) -> bytes:
    """The bytes a member contributes to engine_tree_sha: an installed member
    with CRLF read as LF, a compiled member unchanged (U2-3 item 13, F33)."""
    if root == "installed":
        return content.replace(b"\r\n", b"\n")
    return content


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

    U2-3 item 13 (F33): the digest is platform-free. An INSTALLED member is
    read with CRLF as LF, because CMake writes the generated package files
    (superslmConfig.cmake) in the host's line ending, so the same tag pinned
    on Windows and on Linux used to give two values. A COMPILED member is read
    exactly as the pin tool's clone holds it (core.autocrlf=false, LF on every
    host), so a CR inside a source file still moves the digest.
    """
    entries = sorted(((f"{root}:{relpath}", member_bytes(root, content)) for root, relpath, content in members),
                     key=lambda e: e[0])
    h = hashlib.sha256()
    for path, content in entries:
        path_b = path.encode("utf-8")
        h.update(len(path_b).to_bytes(8, "big"))
        h.update(path_b)
        h.update(len(content).to_bytes(8, "big"))
        h.update(content)
    return h.hexdigest()
