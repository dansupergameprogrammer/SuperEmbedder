"""Pins `eval.k1.COMMISSIONED_SETS` against the filed commissioning verdicts it claims to
carry (TE-47, `Claude/Zelda/Board-SuperEmbedder.md`, Wizard project records tree).

The class this closes: `COMMISSIONED_SETS` is the constant every gate/publishing surface in
this package reads to decide whether a set's readings are load-bearing
(`StandardsDocument.md` 5.4). Nothing before this test stopped a future edit from adding a
set name to that tuple without an independent seat having actually run and filed the three
commissioning constructions against it -- the exact stale-truth class TE-40 (F-1) and TE-41
found the instrument's own notice text in already, twice, on this same set.

Two independent checks, because they close different halves of the same drift:

- `test_commissioned_sets_matches_its_own_citation_table` -- always runs, no dependency on
  anything outside this repository. `COMMISSIONED_SETS` and `COMMISSIONING_DECISIONS` (the
  per-set decision-ID citation, `eval/k1/__init__.py`) must name exactly the same sets. A bare
  edit to one without the other fails here, immediately, in any environment.
- `test_commissioned_sets_agrees_with_the_filed_decision_log_verdict` -- reads
  `Claude/Decisions/DecisionLog.md` in the sibling Wizard records repository and confirms each
  cited decision ID's own entry actually states a COMMISSIONED verdict for that set (not NOT
  COMMISSIONED, not silent). This is the check that catches a citation added in bad faith or
  by mistake -- a decision ID that exists but does not say what the constant claims it says.
  It requires the sibling repository to be locatable (see `_discover_wizard_decision_log`
  below) and skips, rather than fails, when it is not -- a machine or CI checkout that has
  only this repository cannot be expected to have it, and a skip is loud about why.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import pytest

from eval.k1 import COMMISSIONED_SETS, COMMISSIONING_DECISIONS

# Display name each set is referred to by in the Wizard project's decision-log prose --
# distinct from the lowercase keys `COMMISSIONED_SETS`/`COMMISSIONING_DECISIONS` use, which
# match `eval.k1.set_roster`'s own set-name convention.
_SET_DISPLAY_NAMES = {
    "scifact": "SciFact",
    "nfcorpus": "NFCorpus",
    "fiqa": "FiQA-2018",
    "arguana": "ArguAna",
    "scidocs": "SCIDOCS",
}

_ENV_OVERRIDE = "SUPEREMBEDDER_WIZARD_RECORDS"
_DEFAULT_ROOT = Path(r"D:\Wizard")


def _discover_wizard_decision_log() -> Optional[Path]:
    """Locates a `Claude/Decisions/DecisionLog.md` in the sibling Wizard records repository
    that actually carries every decision ID `COMMISSIONING_DECISIONS` cites.

    Checked in order: the `SUPEREMBEDDER_WIZARD_RECORDS` environment variable (a directory
    containing `Claude/`), then `D:\\Wizard`'s main checkout -- the durable home the records
    this ticket files land in once its branch merges to `develop`. A candidate whose file
    exists but is missing a cited decision (the main checkout, before this ticket's branch
    merges) is treated the same as a candidate that does not exist at all -- skipped, not
    read and failed on -- because a stale sibling checkout says nothing about whether
    `COMMISSIONED_SETS` itself has drifted; it is a fact about which branch happens to be
    checked out there. Returns None when no candidate qualifies, so the dependent test can
    skip cleanly rather than fail on a fact unrelated to this repository's own state."""
    candidates = []
    env_value = os.environ.get(_ENV_OVERRIDE)
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(_DEFAULT_ROOT)
    required_ids = set(COMMISSIONING_DECISIONS.values())
    for root in candidates:
        log_path = root / "Claude" / "Decisions" / "DecisionLog.md"
        if not log_path.is_file():
            continue
        text = log_path.read_text(encoding="utf-8")
        if all(decision_id in text for decision_id in required_ids):
            return log_path
    return None


def _entry_text(log_text: str, decision_id: str) -> str:
    """Slices out one decision-log entry's full text, from its own `- **D-...**` bullet to
    the next one (or end of file). Fails loudly, rather than returning an empty match, when
    the cited ID is not present at all -- a dangling citation is exactly the drift this pin
    exists to catch."""
    pattern = re.compile(
        r"^-\s+\*\*" + re.escape(decision_id) + r"\*\*.*?(?=\n-\s+\*\*D-|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(log_text)
    assert match is not None, (
        f"{decision_id} (cited by eval.k1.COMMISSIONING_DECISIONS) is not present in "
        f"the decision log -- the citation is dangling"
    )
    return match.group(0)


def _verdict_sentence(entry_text: str, decision_id: str) -> str:
    """The first sentence of the entry that mentions 'verdict' -- the sentence the entry's own
    disposition is stated in, per this project's decision-log convention of stating the
    outcome as its own clause rather than only in surrounding narrative."""
    for sentence in re.split(r"(?<=[.!?])\s+", entry_text):
        if "verdict" in sentence.lower():
            return sentence
    pytest.fail(f"{decision_id}'s entry has no sentence naming a 'verdict'")


@pytest.fixture(scope="module")
def wizard_decision_log_text() -> str:
    log_path = _discover_wizard_decision_log()
    if log_path is None:
        pytest.skip(
            f"Wizard records repository not found (checked ${_ENV_OVERRIDE} and "
            f"{_DEFAULT_ROOT}) -- set {_ENV_OVERRIDE} to the records tree's root to run this "
            f"check"
        )
    return log_path.read_text(encoding="utf-8")


def test_commissioned_sets_matches_its_own_citation_table():
    """`COMMISSIONED_SETS` and `COMMISSIONING_DECISIONS` must name exactly the same sets --
    every commissioned set carries a decision-ID citation, and every citation corresponds to a
    set actually treated as commissioned. This is the check with no external dependency; it is
    the one that fires on a bare, uncited edit to the tuple in any environment."""
    assert set(COMMISSIONED_SETS) == set(COMMISSIONING_DECISIONS.keys())


def test_commissioning_decisions_covers_every_display_name():
    """Every set this test suite knows how to look up in the decision log is present in the
    citation table's key space (allowing the table to be a subset of the full locked roster --
    only the display-name map needs to be complete, so a newly locked-but-not-yet-commissioned
    set does not silently fall out of this pin's coverage)."""
    assert set(COMMISSIONING_DECISIONS.keys()) <= set(_SET_DISPLAY_NAMES.keys())


@pytest.mark.parametrize("set_name", sorted(_SET_DISPLAY_NAMES))
def test_commissioned_sets_agrees_with_the_filed_decision_log_verdict(
    set_name: str, wizard_decision_log_text: str
):
    decision_id = COMMISSIONING_DECISIONS.get(set_name)
    is_commissioned_in_constant = set_name in COMMISSIONED_SETS

    if decision_id is None:
        assert not is_commissioned_in_constant, (
            f"{set_name} is in eval.k1.COMMISSIONED_SETS but has no citation in "
            f"eval.k1.COMMISSIONING_DECISIONS"
        )
        return

    entry_text = _entry_text(wizard_decision_log_text, decision_id)
    display_name = _SET_DISPLAY_NAMES[set_name]
    assert display_name in entry_text, (
        f"{decision_id}'s entry does not mention {display_name} -- the citation does not "
        f"actually pertain to this set"
    )

    verdict_sentence = _verdict_sentence(entry_text, decision_id)
    filed_as_commissioned = (
        "COMMISSIONED" in verdict_sentence and "NOT COMMISSIONED" not in verdict_sentence
    )
    assert filed_as_commissioned == is_commissioned_in_constant, (
        f"{set_name}: eval.k1.COMMISSIONED_SETS says commissioned="
        f"{is_commissioned_in_constant}, but {decision_id}'s own verdict sentence reads "
        f"{verdict_sentence!r}"
    )
