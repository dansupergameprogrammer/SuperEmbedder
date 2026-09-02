"""Fixture for tests/pin_superslm_delete_ast_check.py -- TE-75 M-4.

Nothing in this file is a filesystem-deletion call, and the check must
report zero violations against it. `xs.remove(x)` on a list is the
reviewer's own construction (M-4): before this round's fix, ANY `.remove()`
call was flagged as "Path-style deletion method", which would have failed
this ordinary, unrelated line. `os.path.exists` is a normal os.path read,
included to confirm attribute access into `os` that is not one of the four
flagged names is left alone.
"""
from __future__ import annotations

import os


def uses_list_remove():
    xs = [1, 2, 3]
    xs.remove(2)
    return xs


def reads_os_path(p):
    return os.path.exists(p)
