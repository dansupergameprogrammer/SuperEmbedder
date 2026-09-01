"""Tests for ``eval/k1/tools/rerun_te50_amended.py``'s ``copy_candidate_rankings`` -- the
part of TE-50's re-run tool that can be exercised without GPU/network (the reference
re-embed and BM25 rebuild are proven by the real re-run itself, filed in the build log)."""
from __future__ import annotations

import json

import pytest

from eval.k1.run_spec import QWEN3_EMB_QUERY_PROMPT
from eval.k1.tools.rerun_te50_amended import (
    CANDIDATE_MODEL_NAME,
    FIVE_SETS,
    RUN1_PACKET_NAME,
    copy_candidate_rankings,
)


def _make_run1_output(tmp_path, sets=FIVE_SETS, with_query_convention=False, write_packet=True):
    run1_dir = tmp_path / "run1_output"
    packet = {"sets": {}}
    for set_name in sets:
        set_dir = run1_dir / "run_files" / "run1-full" / set_name
        set_dir.mkdir(parents=True)
        (set_dir / f"{CANDIDATE_MODEL_NAME}.trec").write_text(
            f"q1 Q0 d1 1 0.900000 u-k1-{CANDIDATE_MODEL_NAME}\n", encoding="utf-8"
        )
        # Run 1's own real packet predates the TE-49 amendment and carries NO
        # query_convention field at all (TE-51 H-1's own discriminator) -- with_query_convention
        # defaults to matching that real shape; only test_backfills_... below exercises it.
        query_manifest = {"vectors_sha256": "abcd1234", "revision": "deadbeef"}
        if with_query_convention:
            query_manifest["query_convention"] = "some-recorded-instruction"
        packet["sets"][set_name] = {
            "models": {
                CANDIDATE_MODEL_NAME: {
                    "corpus_manifest": {"vectors_sha256": "corpus-abcd1234"},
                    "query_manifest": query_manifest,
                }
            }
        }
    if write_packet:
        run1_dir.mkdir(parents=True, exist_ok=True)
        (run1_dir / RUN1_PACKET_NAME).write_text(json.dumps(packet), encoding="utf-8")
    return run1_dir


def test_copies_every_sets_candidate_trec_file(tmp_path):
    run1_dir = _make_run1_output(tmp_path)
    dest = tmp_path / "reused_candidate"
    copy_candidate_rankings(run1_dir, dest)
    for set_name in FIVE_SETS:
        copied = dest / set_name / f"{CANDIDATE_MODEL_NAME}.trec"
        assert copied.exists()
        assert copied.read_text(encoding="utf-8") == (run1_dir / "run_files" / "run1-full" / set_name / f"{CANDIDATE_MODEL_NAME}.trec").read_text(encoding="utf-8")


def test_refuses_on_a_missing_sets_candidate_file(tmp_path):
    run1_dir = _make_run1_output(tmp_path, sets=[s for s in FIVE_SETS if s != "scidocs"])
    dest = tmp_path / "reused_candidate"
    with pytest.raises(FileNotFoundError) as exc:
        copy_candidate_rankings(run1_dir, dest)
    assert "scidocs" in str(exc.value)


def test_never_writes_into_the_source_directory(tmp_path):
    """The ticket's own constraint: Run 1's output is evidence and stays byte-identical --
    this copies OUT of run1_output, never modifies it."""
    run1_dir = _make_run1_output(tmp_path)
    before = {
        p: p.read_bytes()
        for p in (run1_dir / "run_files" / "run1-full").rglob("*.trec")
    }
    before_packet = (run1_dir / RUN1_PACKET_NAME).read_bytes()
    dest = tmp_path / "reused_candidate"
    copy_candidate_rankings(run1_dir, dest)
    after = {
        p: p.read_bytes()
        for p in (run1_dir / "run_files" / "run1-full").rglob("*.trec")
    }
    assert before == after
    assert (run1_dir / RUN1_PACKET_NAME).read_bytes() == before_packet


# --------------------------------------------------------------------------------------
# TE-51 review, H-3 (Significant) -- the reuse path carried a two-key stub with no
# provenance at all. copy_candidate_rankings now writes a manifest sidecar per set, sourced
# from Run 1's own packet, so runner.run_gate's reuse branch has real provenance to carry
# forward instead.
# --------------------------------------------------------------------------------------


def test_writes_a_manifest_sidecar_carrying_forward_the_source_provenance(tmp_path):
    run1_dir = _make_run1_output(tmp_path, with_query_convention=True)
    dest = tmp_path / "reused_candidate"
    copy_candidate_rankings(run1_dir, dest)
    for set_name in FIVE_SETS:
        manifest = json.loads(
            (dest / set_name / f"{CANDIDATE_MODEL_NAME}.manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["query_manifest"]["query_convention"] == "some-recorded-instruction"
        assert manifest["query_manifest"]["vectors_sha256"] == "abcd1234"
        assert manifest["corpus_manifest"]["vectors_sha256"] == "corpus-abcd1234"


def test_backfills_query_convention_when_the_source_packet_predates_the_field(tmp_path):
    """Run 1's own real packet predates the TE-49 amendment and carries no query_convention
    at all (verified, TE-51 H-1's discriminator) -- the candidate's actual query-side
    instruction has not changed since (only the reference's did, design Section 17), so this
    backfills the value from the model's own static spec rather than leaving the reused arm
    with a hole the amendment's own contract clause (Section 17.6 dimension 7) forbids."""
    run1_dir = _make_run1_output(tmp_path, with_query_convention=False)
    dest = tmp_path / "reused_candidate"
    copy_candidate_rankings(run1_dir, dest)
    for set_name in FIVE_SETS:
        manifest = json.loads(
            (dest / set_name / f"{CANDIDATE_MODEL_NAME}.manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["query_manifest"]["query_convention"] == QWEN3_EMB_QUERY_PROMPT


def test_refuses_when_run1_packet_is_missing(tmp_path):
    run1_dir = _make_run1_output(tmp_path, write_packet=False)
    dest = tmp_path / "reused_candidate"
    with pytest.raises(FileNotFoundError) as exc:
        copy_candidate_rankings(run1_dir, dest)
    assert RUN1_PACKET_NAME in str(exc.value)
