"""Permanent reconciliation pin between the three independently-maintained lists of "every
locked set" (TE-40 code review, Finding F-5 (Significant),
`Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project records tree):

- ``gate.py::GATE_REQUIRED_SETS`` (read from ``eval.k1.set_roster.ALL_LOCKED_SETS``)
- ``sets_lock.py::SET_REGISTRY``'s keys
- the committed ``sets.lock.json``'s own keys

Before this pin, nothing compared these three. Poirot's review executed both drift
directions by construction (Section 4.7 of the casebook above): the roster growing without a
matching registry/lock entry makes the gate permanently un-passable, reporting it only as a
`reason` string that reads like a normal incomplete run; the registry shrinking without the
roster following leaves the test suite green with the dropped set's coverage silently gone.
This module pins the reconciled state as a standing assertion AND demonstrates, by
monkeypatching each list independently, that the assertion actually fires on both drift
shapes -- proving the pin can fail before trusting that it does not."""
from __future__ import annotations

import pytest

import eval.k1.gate as gate_mod
import eval.k1.sets_lock as sets_lock_mod
from eval.k1.set_roster import ALL_LOCKED_SETS
from eval.k1.sets_lock import SET_REGISTRY, read_sets_lock
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parents[1] / "sets.lock.json"


def _reconciled(gate_required_sets, registry, lock_names):
    assert set(gate_required_sets) == set(registry) == set(lock_names)


def test_roster_registry_and_lock_reconcile_on_real_committed_state():
    lock_names = set(read_sets_lock(LOCK_PATH).keys())
    _reconciled(gate_mod.GATE_REQUIRED_SETS, SET_REGISTRY.keys(), lock_names)
    # ALL_LOCKED_SETS is GATE_REQUIRED_SETS' own source -- pinned equal directly too, so a
    # future edit that reads GATE_REQUIRED_SETS from somewhere else is caught here as well.
    assert set(gate_mod.GATE_REQUIRED_SETS) == set(ALL_LOCKED_SETS)


def test_pin_fires_when_the_roster_grows_without_a_matching_registry_or_lock_entry(monkeypatch):
    """Poirot review Section 4.7(a): GATE_REQUIRED_SETS extended by one name with no lock
    entry. The gate itself degrades silently (permanently un-passable, reported only as a
    reason string); this reconciliation pin must not degrade silently -- it must raise."""
    lock_names = set(read_sets_lock(LOCK_PATH).keys())
    grown = tuple(gate_mod.GATE_REQUIRED_SETS) + ("touche2020",)
    with pytest.raises(AssertionError):
        _reconciled(grown, SET_REGISTRY.keys(), lock_names)


def test_pin_fires_when_the_registry_shrinks_without_the_roster_following(monkeypatch):
    """Poirot review Section 4.7(b): SET_REGISTRY loses an entry the roster still requires.
    The pre-fix suite stayed green (71 passed instead of 72, the dropped set's parametrized
    case silently gone); this reconciliation pin must not stay green -- it must raise."""
    lock_names = set(read_sets_lock(LOCK_PATH).keys())
    shrunk_registry = dict(SET_REGISTRY)
    shrunk_registry.pop("scidocs")
    with pytest.raises(AssertionError):
        _reconciled(gate_mod.GATE_REQUIRED_SETS, shrunk_registry.keys(), lock_names)


def test_pin_fires_when_the_lock_file_falls_behind_the_roster(monkeypatch):
    """The third drift direction the two executed above do not cover directly: the roster and
    the registry agree with each other but the committed sets.lock.json itself has fallen
    behind -- e.g. a set added to SET_REGISTRY and the gate roster but never actually
    fetched/pinned."""
    shrunk_lock_names = set(read_sets_lock(LOCK_PATH).keys())
    shrunk_lock_names.discard("scidocs")
    with pytest.raises(AssertionError):
        _reconciled(gate_mod.GATE_REQUIRED_SETS, SET_REGISTRY.keys(), shrunk_lock_names)
