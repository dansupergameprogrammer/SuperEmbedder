"""Fixture for tests/pin_superslm_delete_ast_check.py -- TE-75 S-1.

Every construction below is a deletion-primitive call that the check must
flag. Each is exactly one dodge the reviewer's own casebook named
(`Claude/Poirot/0d432d1-te74-u0a-scaffold-confirmation5.md`, Z-3), plus one
this seat added (a direct, un-aliased `from` import used bare -- the same
resolution path the aliased dodges exercise, checked with no alias in the
way, since S-1's fix resolves through the import map regardless of whether
an `asname` is present at all).

This file is never imported or executed -- `tests/pin_superslm_delete_ast_check.py`
only parses it with `ast.parse`. It intentionally contains no
`_remove_owned` function, so every call below is, correctly, outside one.
"""
from __future__ import annotations

# --- Reviewer's dodge 1 (Z-3): a renamed FUNCTION import from shutil -----
from shutil import rmtree as x


def dodge_1_aliased_shutil_rmtree(p):
    x(p)


# --- Reviewer's dodge 2 (Z-3): a renamed FUNCTION import from os ---------
from os import remove as nuke_file


def dodge_2_aliased_os_remove(p):
    nuke_file(p)


# --- Reviewer's dodge 3 (Z-3): os.removedirs, absent from the old set ----
import os


def dodge_3_os_removedirs(p):
    os.removedirs(p)


# --- This seat's own addition: a DIRECT (unaliased) `from` import used ---
# --- bare -- the same resolution path as dodge 1/2, exercised with no  ---
# --- `asname` present at all, confirming the fix resolves through the  ---
# --- import map for the un-renamed case too, not only the renamed one. ---
from os import unlink


def dodge_4_direct_from_import_bare_call(p):
    unlink(p)


# --- Already caught before this round (kept here as a population member,
# --- confirming the fix does not regress what already worked): a renamed
# --- MODULE import.
import shutil as sh


def already_caught_module_alias(p):
    sh.rmtree(p)


# --- Already caught before this round: a plain pathlib Path method call.
import pathlib


def already_caught_path_unlink(p):
    pathlib.Path(p).unlink()
