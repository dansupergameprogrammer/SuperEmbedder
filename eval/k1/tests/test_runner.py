"""Tests for runner.py's own logic that isn't already covered as a scoring or guard
concern -- the smoke-query selection helper and the qrels-scoping fix, at unit scale (no
GPU, no network). The real end-to-end proof is the executed smoke run filed in the build
log (Claude/Brunel/u-k1-instrument-build-2026-08-25.md)."""
from __future__ import annotations

import json

import pytest

from eval.k1.guards import K1GuardError, check_query_convention_recorded
from eval.k1.runner import (
    _build_qrels_by_query,
    _load_reused_arm_manifests,
    _select_smoke_queries,
    render_human_table,
)


def test_build_qrels_by_query_groups_rows():
    rows = [
        {"query-id": "q1", "corpus-id": "d1", "score": 1.0},
        {"query-id": "q1", "corpus-id": "d2", "score": 0.0},
        {"query-id": "q2", "corpus-id": "d3", "score": 2.0},
    ]
    grouped = _build_qrels_by_query(rows)
    assert grouped == {"q1": {"d1": 1.0, "d2": 0.0}, "q2": {"d3": 2.0}}


def test_select_smoke_queries_keeps_only_queries_with_a_surviving_relevant_doc():
    test_query_ids = ["q1", "q2", "q3"]
    qrels_by_query = {
        "q1": {"d1": 1.0},  # d1 survives truncation -> kept
        "q2": {"d99": 1.0},  # d99 does not survive -> dropped
        "q3": {"d2": 0.0, "d3": 1.0},  # d3 survives and is positively judged -> kept
    }
    truncated_corpus_ids = {"d1", "d2", "d3"}
    kept = _select_smoke_queries(test_query_ids, qrels_by_query, truncated_corpus_ids)
    assert kept == ["q1", "q3"]


def test_select_smoke_queries_drops_a_query_whose_only_relevant_doc_is_score_zero():
    test_query_ids = ["q1"]
    qrels_by_query = {"q1": {"d1": 0.0}}  # judged but not positively relevant
    kept = _select_smoke_queries(test_query_ids, qrels_by_query, {"d1"})
    assert kept == []


# --------------------------------------------------------------------------------------
# _load_reused_arm_manifests (TE-51 review, H-3, Significant): the candidate-reuse path's
# manifest sidecar loader. Before this fix, both manifests were replaced by a two-key
# {"reused_from", "note"} stub with no provenance at all -- design Section 17.6 dimension 7:
# "a packet with neither field is not a K1 reading."
# --------------------------------------------------------------------------------------


def test_load_reused_arm_manifests_refuses_when_the_sidecar_is_missing(tmp_path):
    reuse_dir = tmp_path / "reused_candidate"
    (reuse_dir / "scifact").mkdir(parents=True)
    (reuse_dir / "scifact" / "candidate.trec").write_text("q1 Q0 d1 1 0.9 run\n", encoding="utf-8")
    with pytest.raises(K1GuardError) as exc:
        _load_reused_arm_manifests(str(reuse_dir), "scifact", "candidate", reuse_dir / "scifact" / "candidate.trec")
    assert exc.value.code == "K1_REUSE_MANIFEST_MISSING"


def test_load_reused_arm_manifests_carries_the_source_manifests_forward(tmp_path):
    reuse_dir = tmp_path / "reused_candidate"
    set_dir = reuse_dir / "scifact"
    set_dir.mkdir(parents=True)
    sidecar = {
        "corpus_manifest": {"vectors_sha256": "corpus-sha", "revision": "abc123"},
        "query_manifest": {"vectors_sha256": "query-sha", "query_convention": "an instruction"},
    }
    (set_dir / "candidate.manifest.json").write_text(json.dumps(sidecar), encoding="utf-8")
    reuse_path = set_dir / "candidate.trec"

    corpus_manifest, query_manifest = _load_reused_arm_manifests(
        str(reuse_dir), "scifact", "candidate", reuse_path
    )
    assert corpus_manifest["vectors_sha256"] == "corpus-sha"
    assert corpus_manifest["revision"] == "abc123"
    assert query_manifest["vectors_sha256"] == "query-sha"
    assert query_manifest["query_convention"] == "an instruction"
    # both carry a reuse marker distinguishing them from a real embed
    assert corpus_manifest["reused_from"] == str(reuse_path)
    assert "note" in corpus_manifest and "note" in query_manifest


def test_load_reused_arm_manifests_does_not_invent_a_missing_query_convention(tmp_path):
    """H-3's own remedy does NOT backfill anything itself -- the tool that builds the sidecar
    (tools/rerun_te50_amended.py) is responsible for that. A sidecar whose source genuinely
    lacks query_convention is carried through exactly as thin as it arrived, so
    check_query_convention_recorded (H-5) still has a real, reachable input to refuse -- if
    this function silently invented a value here, that guard would be unreachable again, on a
    different path."""
    reuse_dir = tmp_path / "reused_candidate"
    set_dir = reuse_dir / "scifact"
    set_dir.mkdir(parents=True)
    sidecar = {"corpus_manifest": {}, "query_manifest": {"vectors_sha256": "query-sha"}}  # no query_convention
    (set_dir / "candidate.manifest.json").write_text(json.dumps(sidecar), encoding="utf-8")
    reuse_path = set_dir / "candidate.trec"

    _corpus_manifest, query_manifest = _load_reused_arm_manifests(
        str(reuse_dir), "scifact", "candidate", reuse_path
    )
    assert query_manifest.get("query_convention") is None

    # TE-51 H-5's own reachable firing case: the exact same function used on the production
    # path, with the exact real value this loader just returned.
    with pytest.raises(K1GuardError) as exc:
        check_query_convention_recorded("candidate", query_manifest.get("query_convention"))
    assert exc.value.code == "K1_QUERY_CONVENTION_UNRECORDED"


# --------------------------------------------------------------------------------------
# render_human_table (TE-51 review, H-8, Minor): the RP column was headed "ach.RP" and
# printed the MARGINAL resolving power, while the verdict notes beneath it quote the PAIRED
# resolving power the gate has acted on since the TE-49 amendment -- three numbers, one label.
# --------------------------------------------------------------------------------------


def _packet_for_table():
    return {
        "commissioning_notice": "notice", "self_exclusion_convention": "note",
        "run_id": "unit", "date": "2026-01-01T00:00:00",
        "sets": {
            "scifact": {
                "corpus_docs_used": 10, "test_queries_used": 5,
                "executed_chance": {"mean": 0.1, "std": 0.01, "trials": 10},
                "models": {
                    "candidate": {
                        "ndcg_at_10": 0.70, "recall_at_10": 0.80, "mrr_at_10": 0.60,
                        "achieved_resolving_power": 0.05,
                        "f1_paired_resolving_power": 0.02,
                        "f2_paired_resolving_power": 0.03,
                    },
                },
            },
        },
    }


def test_render_human_table_shows_all_three_resolving_powers_distinctly_labeled():
    table = render_human_table(_packet_for_table())
    assert "marg.RP" in table
    assert "f1.RP" in table
    assert "f2.RP" in table
    assert "ach.RP" not in table
    candidate_lines = [l for l in table.splitlines() if l.strip().startswith("candidate")]
    assert len(candidate_lines) == 1
    # the row prints the marginal (0.05), f1 paired (0.02) and f2 paired (0.03) RPs, in that
    # order, as three DIFFERENT numbers -- not the marginal figure repeated under new labels.
    assert "0.0500" in candidate_lines[0]
    assert "0.0200" in candidate_lines[0]
    assert "0.0300" in candidate_lines[0]


def test_render_human_table_nan_paired_rp_for_bm25_and_reference_rows():
    """TE-53 review, J-4 (Minor): this test's own name and the code comment beside its call
    site previously said "blank" -- the table prints the literal string "nan", not an empty
    field, which is the better behaviour (a reader can tell a missing value from a zero one).
    bm25 and the reference are the floors, not candidates being graded -- they carry no paired
    resolving power of their own, and the table must not silently print 0.0 for a field that
    was never computed."""
    packet = _packet_for_table()
    packet["sets"]["scifact"]["models"]["bm25"] = {
        "ndcg_at_10": 0.50, "recall_at_10": 0.60, "mrr_at_10": 0.40,
        "achieved_resolving_power": 0.03,
    }
    table = render_human_table(packet)
    bm25_line = [l for l in table.splitlines() if l.strip().startswith("bm25")][0]
    assert "nan" in bm25_line.lower()


# --------------------------------------------------------------------------------------
# H-9 (Minor, TE-51 review): the reference/bm25 arm-identification rule must be ONE constant
# pair, imported wherever it is used -- not spelled as a literal in each caller.
# --------------------------------------------------------------------------------------


def test_runner_and_rescore_packet_import_the_same_arm_constants_as_gate():
    import eval.k1.gate as gate_mod
    import eval.k1.runner as runner_mod
    import eval.k1.tools.rescore_packet as rescore_mod

    assert runner_mod.REFERENCE_SUFFIX is gate_mod.REFERENCE_SUFFIX
    assert runner_mod.BM25_MODEL_NAME is gate_mod.BM25_MODEL_NAME
    assert rescore_mod.REFERENCE_SUFFIX is gate_mod.REFERENCE_SUFFIX
    assert rescore_mod.BM25_MODEL_NAME is gate_mod.BM25_MODEL_NAME
