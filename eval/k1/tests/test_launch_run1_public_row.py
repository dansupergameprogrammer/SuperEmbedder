"""Tests for ``eval/k1/tools/launch_run1.py``'s public-row composition (TE-44 confirmation
review, `Claude/Poirot/9aede12-te44-k1-instrument-confirmation.md`, Wizard project records
tree, Finding G-1, Significant).

Before this fix, the launcher composed Run 1's headlined "public row" line directly from
``run_spec.PUBLIC_SETS`` with no intersection against ``eval.k1.COMMISSIONED_SETS`` -- the
commissioning notice printed at the top of the same table says an uncommissioned set is
"never headlined", and the line directly below it headlined one anyway (SCIDOCS, at the time
this was found: executed against the real code, ``PUBLIC_SETS - COMMISSIONED_SETS`` is
``{"scidocs"}`` and the launcher's emitted line read "public row (design Section 16):
scifact, arguana, scidocs"). The fix is unconditional on which sets happen to be commissioned
today: it withholds any design-specified public set absent from ``COMMISSIONED_SETS`` and
names it on its own line, so the next set the design locks is withheld the same way,
automatically, whether or not this particular set (SCIDOCS) is later commissioned.
"""
from __future__ import annotations

import json

import eval.k1.tools.launch_run1 as mod
from eval.k1.tools.launch_run1 import compose_public_row


# --------------------------------------------------------------------------------------
# The extracted, pure composition -- the mechanism G-1's fix introduces.
# --------------------------------------------------------------------------------------


def test_compose_public_row_withholds_a_public_set_absent_from_commissioned_sets():
    commissioned, withheld = compose_public_row(
        public_sets=("scifact", "arguana", "scidocs"),
        commissioned_sets=("scifact", "nfcorpus", "fiqa", "arguana"),
    )
    assert commissioned == ("scifact", "arguana")
    assert withheld == ("scidocs",)


def test_compose_public_row_withholds_nothing_once_every_public_set_is_commissioned():
    """The fix is not scoped to SCIDOCS by name -- it is a structural intersection that
    withholds nothing once the intersection is empty, whatever the roster's membership."""
    commissioned, withheld = compose_public_row(
        public_sets=("scifact", "arguana", "scidocs"),
        commissioned_sets=("scifact", "nfcorpus", "fiqa", "arguana", "scidocs"),
    )
    assert commissioned == ("scifact", "arguana", "scidocs")
    assert withheld == ()


def test_compose_public_row_withholds_a_future_set_the_same_way():
    """The next set the design locks (not SCIDOCS) arrives on this same path -- a roster
    amendment that adds a name to PUBLIC_SETS before COMMISSIONED_SETS grows to match it."""
    commissioned, withheld = compose_public_row(
        public_sets=("scifact", "arguana", "scidocs", "some-future-set"),
        commissioned_sets=("scifact", "nfcorpus", "fiqa", "arguana", "scidocs"),
    )
    assert commissioned == ("scifact", "arguana", "scidocs")
    assert withheld == ("some-future-set",)


def test_compose_public_row_is_order_preserving():
    commissioned, withheld = compose_public_row(
        public_sets=("scidocs", "scifact", "arguana"),
        commissioned_sets=("scifact", "arguana"),
    )
    assert commissioned == ("scifact", "arguana")
    assert withheld == ("scidocs",)


# --------------------------------------------------------------------------------------
# The real ``run_full_gate`` wiring -- only the embedding/ranking boundary (``run_gate``)
# faked, exactly as the mint-tool pins fake only the network boundary.
# --------------------------------------------------------------------------------------


def _fake_run_gate(spec, sets_lock_path, anchors_path, output_dir):
    """Stands in for the real, expensive ``run_gate`` (embeds, ranks, scores every set and
    model): writes the minimal packet shape ``run_full_gate`` reads back and augments, so this
    test exercises the launcher's own composition and rendering code for real."""
    output_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "commissioning_notice": "stub notice",
        "self_exclusion_convention": "stub convention",
        "run_id": spec.run_id,
        "is_gate_reading": spec.is_gate_reading,
        "date": "2026-08-30T00:00:00",
        "sets": {},
    }
    (output_dir / f"{spec.run_id}.json").write_text(json.dumps(packet), encoding="utf-8")


def _stub_r3_report() -> dict:
    return {
        "candidate": "qwen3-embedding-0.6b",
        "same_batch_size": 8,
        "alt_batch_size": 4,
        "sha256_bit_identity": {
            "scifact": {"bit_identical": True},
            "nfcorpus": {"bit_identical": True},
        },
        "ndcg_batch_variation": {
            "scifact": {"delta": 0.0, "tolerance": 1e-4, "within_tolerance": True},
            "nfcorpus": {"delta": 0.0, "tolerance": 1e-4, "within_tolerance": True},
        },
        "r3_holds": True,
    }


def test_run_full_gate_withholds_a_manually_uncommissioned_set_from_the_written_packet_and_table(
    tmp_path, monkeypatch
):
    """TE-47 added SCIDOCS to eval.k1.COMMISSIONED_SETS (D-SLM5363): today's real commissioning
    cell no longer leaves a gap against run_spec.PUBLIC_SETS, so this test can no longer use
    SCIDOCS as a naturally-occurring withheld example -- as the pre-fix version of this test's
    own comment anticipated ("this test's premise changes with it and is not this fix's to
    defend"). It demonstrates the same withholding mechanism generically instead, via
    monkeypatch, matching test_gate.py's sibling fix for the same drift."""
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "run_gate", _fake_run_gate)
    monkeypatch.setattr(mod, "COMMISSIONED_SETS", ("scifact", "nfcorpus", "fiqa", "arguana"))

    json_path = mod.run_full_gate(_stub_r3_report())
    packet = json.loads(json_path.read_text(encoding="utf-8"))

    assert "scidocs" not in packet["public_sets"]
    assert packet["public_sets_withheld_uncommissioned"] == ["scidocs"]

    table = json_path.with_suffix(".txt").read_text(encoding="utf-8")
    public_row_line = next(line for line in table.splitlines() if line.startswith("public row"))
    assert "scidocs" not in public_row_line
    withheld_line = next(line for line in table.splitlines() if line.startswith("withheld from public row"))
    assert "scidocs" in withheld_line


def test_run_full_gate_headlines_every_public_set_once_all_are_commissioned(tmp_path, monkeypatch):
    """Today's real commissioning cell (eval.k1.COMMISSIONED_SETS, post-TE-47): every set in
    run_spec.PUBLIC_SETS is commissioned, so the public row headlines all of them and nothing
    is withheld. This is the mechanism's other side, now the real-world default -- the sibling
    test above exercises the withheld side by monkeypatching a narrower cell."""
    monkeypatch.setattr(mod, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "run_gate", _fake_run_gate)

    json_path = mod.run_full_gate(_stub_r3_report())
    packet = json.loads(json_path.read_text(encoding="utf-8"))

    assert set(packet["public_sets"]) == set(mod.run_spec_mod.PUBLIC_SETS)
    assert packet["public_sets_withheld_uncommissioned"] == []

    table = json_path.with_suffix(".txt").read_text(encoding="utf-8")
    public_row_line = next(line for line in table.splitlines() if line.startswith("public row"))
    assert "scidocs" in public_row_line
    assert not any(line.startswith("withheld from public row") for line in table.splitlines())
