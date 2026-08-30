"""Tests for ``eval/k1/tools/rescore_packet.py`` (TE-40 code review,
`Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project records tree). This tool
is what will correct the packet Run 1 emits, so these pins run against the real, committed
smoke fixture and its persisted TREC run files (StandardsDocument.md 5.4's real-workload
rule), not a hand-built one -- the same fixture and technique Poirot's review executed
manually (Sections 4.4-4.7 of the casebook above) are formalized here as permanent pins.

Skipped, not mocked, when the local HF cache does not carry the fixture's sets (SciFact,
SCIDOCS) -- matches `test_sets_lock_join_integrity.py`'s own skip convention.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from eval.k1.gate import evaluate_gate
from eval.k1.sets_lock import SET_REGISTRY, read_sets_lock
from eval.k1.tools.rescore_packet import RescoreRefusalError, rescore_packet

K1_DIR = Path(__file__).resolve().parents[1]
SMOKE_OUTPUT = K1_DIR / "smoke_output"
SMOKE_PACKET_NAME = "smoke-scifact-scidocs-50.json"
LOCK_PATH = K1_DIR / "sets.lock.json"


def _dataset_cache_has(repo_id: str) -> bool:
    hf_home = os.environ.get("HF_HOME", "")
    cache_name = repo_id.replace("/", "___")
    return bool(hf_home) and os.path.isdir(os.path.join(hf_home, "datasets", cache_name))


def _skip_unless_cached():
    if not os.environ.get("HF_HOME"):
        pytest.skip("no HF_HOME set")
    for name in ("scifact", "scidocs"):
        if not _dataset_cache_has(SET_REGISTRY[name]):
            pytest.skip(f"{name}: no local HF cache entry for {SET_REGISTRY[name]}")
    if not SMOKE_OUTPUT.exists():
        pytest.skip("eval/k1/smoke_output fixture not present in this checkout")


@pytest.fixture
def smoke_copy(tmp_path):
    """A fresh copy of the real committed smoke fixture (packet JSON + its persisted TREC run
    files), so every test mutates its own scratch copy and the real fixture in the repo is
    never touched."""
    _skip_unless_cached()
    dest = tmp_path / "smoke_output"
    shutil.copytree(SMOKE_OUTPUT, dest)
    return dest / SMOKE_PACKET_NAME


# --------------------------------------------------------------------------------------
# Baseline: reproduces the real fixture exactly (the byte-for-byte-reproduction precedent
# the commissioning executions established) -- everything below perturbs from this baseline.
# --------------------------------------------------------------------------------------


def test_rescore_reproduces_the_real_fixtures_stored_readings_exactly(smoke_copy, tmp_path):
    out = tmp_path / "out.json"
    diff = rescore_packet(smoke_copy, output_path=out)
    assert diff["reading_deltas"] == []
    assert diff["trec_files_missing"] == []
    written = json.loads(out.read_text(encoding="utf-8"))
    for set_result in written["sets"].values():
        for model_result in set_result["models"].values():
            assert "recall_at_10" in model_result
            assert "mrr_at_10" in model_result
            assert model_result["recall_at_10"] == pytest.approx(model_result.get("recall_at_10", 0.0))


def test_rescore_drops_the_legacy_quarantine_notice_key(smoke_copy, tmp_path):
    """The module's own behavior (unchanged by F-10's fix -- see the docstring pin below for
    what F-10 actually changed): a packet carrying the legacy `quarantine_notice` key has it
    dropped, not refreshed in place, on rescore."""
    data = json.loads(smoke_copy.read_text(encoding="utf-8"))
    data["quarantine_notice"] = "a superseded status string from an old packet"
    smoke_copy.write_text(json.dumps(data), encoding="utf-8")

    out = tmp_path / "out.json"
    rescore_packet(smoke_copy, output_path=out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "quarantine_notice" not in written
    assert "commissioning_notice" in written


def test_module_docstring_no_longer_claims_the_legacy_key_is_refreshed(smoke_copy):
    """F-10 (Minor) itself: the docstring claimed step 3 'refreshes commissioning_notice (and
    the legacy quarantine_notice key, if the original packet carried it)' -- which, read
    plainly, claims quarantine_notice is refreshed (updated in place) alongside
    commissioning_notice. The code has always dropped it instead (see the test above, whose
    behavior is unchanged by this fix). The docstring is the half that was wrong; it must now
    say 'drops', not 'refreshes', for that key."""
    import eval.k1.tools.rescore_packet as mod

    assert "drops" in mod.__doc__
    assert "quarantine_notice" in mod.__doc__
    # the old phrasing implied the key was refreshed like commissioning_notice -- must be gone
    assert "Refreshes ``commissioning_notice`` (and the legacy" not in mod.__doc__


# --------------------------------------------------------------------------------------
# F-2 (Significant) -- rescore refreshes ndcg_at_10 but left every derived field stale.
# --------------------------------------------------------------------------------------


def test_rescore_refreshes_r1_and_r2_delta_fields_not_only_the_headline_ndcg(smoke_copy, tmp_path):
    """Simulates a packet produced by an older, low-reading scorer (every stored ndcg_at_10
    and ndcg_at_10_r1_independent reduced by 0.05, exactly Poirot's review Section 4.5
    construction). Before the fix, r1_agreement_delta and r2_delta_vs_anchor were left at
    their stale stored values -- a packet whose replication-agreement field asserted
    floating-point-noise agreement across a real 0.05 disagreement its own ndcg refresh had
    just introduced. After the fix, both are recomputed from the same refreshed reading."""
    data = json.loads(smoke_copy.read_text(encoding="utf-8"))
    for set_result in data["sets"].values():
        for model_result in set_result["models"].values():
            if "ndcg_at_10" in model_result:
                model_result["ndcg_at_10"] -= 0.05
            if "ndcg_at_10_r1_independent" in model_result:
                model_result["ndcg_at_10_r1_independent"] -= 0.05
                model_result["r1_agreement_delta"] = 1e-17  # stale, falsely near-zero
            if "r2_delta_vs_anchor" in model_result:
                model_result["r2_delta_vs_anchor"] = abs(
                    model_result["ndcg_at_10"] - model_result["published_anchor_ndcg_at_10"]
                )
    smoke_copy.write_text(json.dumps(data), encoding="utf-8")

    out = tmp_path / "out.json"
    diff = rescore_packet(smoke_copy, output_path=out)
    assert len(diff["reading_deltas"]) > 0  # the perturbation IS detected as a real change

    written = json.loads(out.read_text(encoding="utf-8"))
    for set_result in written["sets"].values():
        for model_result in set_result["models"].values():
            if "r1_agreement_delta" in model_result:
                # recomputed ndcg_at_10 and recomputed r1 come from the SAME real ranking,
                # so they must agree to floating-point noise again -- not the stale value.
                assert model_result["r1_agreement_delta"] < 1e-6, model_result
            if "r2_delta_vs_anchor" in model_result:
                expected = abs(model_result["ndcg_at_10"] - model_result["published_anchor_ndcg_at_10"])
                assert model_result["r2_delta_vs_anchor"] == pytest.approx(expected)


def test_rescore_deletes_r1_fields_when_the_independent_scorer_cannot_be_recomputed(smoke_copy, tmp_path, monkeypatch):
    """F-2's stated fallback: the two R1 success fields are removed, not carried forward
    stale, when R1 genuinely cannot be recomputed. TE-44 review G-2, direction two: the
    removal is no longer silent -- the producing path's own convention for this exact
    condition (``r1_independent_scorer_error``, runner.py:191) is written in their place, and
    the deletion is recorded into ``rescore_report`` (via the returned diff), the artifact
    F-12 exists specifically so a reader can see what a rescore changed."""
    import eval.k1.tools.rescore_packet as mod

    def _raise(*a, **kw):
        raise ImportError("pytrec_eval not installed (simulated)")

    monkeypatch.setattr("eval.k1.rank_score.ndcg_at_k_pytrec", _raise)
    out = tmp_path / "out.json"
    diff = rescore_packet(smoke_copy, output_path=out)
    written = json.loads(out.read_text(encoding="utf-8"))

    deletions_seen = 0
    for set_name, set_result in written["sets"].items():
        for model_name, model_result in set_result["models"].items():
            assert "ndcg_at_10_r1_independent" not in model_result
            assert "r1_agreement_delta" not in model_result
            if "bm25" in model_name:
                continue  # bm25 never carries R1 -- nothing to delete or record
            assert model_result["r1_independent_scorer_error"] == "pytrec_eval not installed (simulated)"
            deletions_seen += 1

    assert deletions_seen > 0, "the fixture must exercise at least one model that carried R1"
    assert len(diff["r1_deletions"]) == deletions_seen
    for entry in diff["r1_deletions"]:
        assert "ndcg_at_10_r1_independent" in entry["removed_fields"]
        assert "r1_agreement_delta" in entry["removed_fields"]
    assert written["rescore_report"]["r1_deletions"] == diff["r1_deletions"]


def test_rescore_corrects_a_stale_r1_scorer_error_when_the_scorer_is_actually_available(smoke_copy, tmp_path):
    """TE-44 review G-2, direction one: a packet produced where ``pytrec_eval`` was
    unavailable carries ``r1_independent_scorer_error`` and neither success field. Before the
    fix, the rescore's R1 branch was keyed on the success fields alone, so this packet never
    entered it -- the stale error string survived a rescore run on a machine (this one, per
    the TE-44 casebook's own verification log) where the scorer is actually importable. After
    the fix, the branch is entered on either field, the scorer runs, and the stale error is
    replaced by a real reading."""
    data = json.loads(smoke_copy.read_text(encoding="utf-8"))
    mutated = False
    for set_result in data["sets"].values():
        for model_result in set_result["models"].values():
            if "ndcg_at_10_r1_independent" in model_result:
                del model_result["ndcg_at_10_r1_independent"]
                del model_result["r1_agreement_delta"]
                model_result["r1_independent_scorer_error"] = "No module named 'pytrec_eval'"
                mutated = True
    assert mutated, "the fixture must carry at least one model with R1 fields to mutate"
    smoke_copy.write_text(json.dumps(data), encoding="utf-8")

    out = tmp_path / "out.json"
    rescore_packet(smoke_copy, output_path=out)
    written = json.loads(out.read_text(encoding="utf-8"))
    corrected = 0
    for set_result in written["sets"].values():
        for model_result in set_result["models"].values():
            if "ndcg_at_10_r1_independent" in model_result:
                assert "r1_independent_scorer_error" not in model_result
                assert isinstance(model_result["r1_agreement_delta"], float)
                corrected += 1
    assert corrected > 0, "at least one stale-error model must be corrected to a real reading"


# --------------------------------------------------------------------------------------
# F-3 (Significant) -- exits 0 and writes a "corrected" packet having recomputed nothing.
# --------------------------------------------------------------------------------------


def test_rescore_refuses_rather_than_writes_when_run_files_are_missing(tmp_path):
    """A packet copied without its run_files/ directory -- the ordinary operator error of a
    --out/path slip, or a packet moved away from its run's own output directory."""
    packet_only = tmp_path / SMOKE_PACKET_NAME
    _skip_unless_cached()
    packet_only.write_text((SMOKE_OUTPUT / SMOKE_PACKET_NAME).read_text(encoding="utf-8"), encoding="utf-8")

    out = tmp_path / "out.json"
    with pytest.raises(RescoreRefusalError) as exc:
        rescore_packet(packet_only, output_path=out)
    assert "TREC run file" in str(exc.value)
    assert not out.exists(), "a refused rescore must not write a packet"


def test_rescore_notice_only_mode_succeeds_without_run_files_and_says_so(tmp_path):
    packet_only = tmp_path / SMOKE_PACKET_NAME
    _skip_unless_cached()
    packet_only.write_text((SMOKE_OUTPUT / SMOKE_PACKET_NAME).read_text(encoding="utf-8"), encoding="utf-8")

    out = tmp_path / "out.json"
    diff = rescore_packet(packet_only, output_path=out, notice_only=True)
    assert diff["notice_only"] is True
    assert diff["reading_deltas"] == []
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["rescore_report"]["notice_only"] is True


# --------------------------------------------------------------------------------------
# F-4 (Significant) -- the license guard is disabled on a gate path.
# --------------------------------------------------------------------------------------


def test_rescore_refuses_a_set_with_no_derived_license(smoke_copy, tmp_path):
    """`load_set`'s own docstring: allow_missing_license is never set on the real gate path.
    Rescore recomputes gate_verdict, so it is a gate path -- a locked set with a blanked
    license must refuse (K1GuardError), not silently proceed under the mechanism-check flag."""
    from eval.k1.guards import K1GuardError

    lock_payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock_payload["sets"]["scifact"]["license"] = None
    lock_payload["sets"]["scifact"]["license_derived"] = False
    no_license_lock = tmp_path / "sets.lock.no-license.json"
    no_license_lock.write_text(json.dumps(lock_payload), encoding="utf-8")

    out = tmp_path / "out.json"
    with pytest.raises(K1GuardError) as exc:
        rescore_packet(smoke_copy, sets_lock_path=no_license_lock, output_path=out)
    assert exc.value.code == "K1_LICENSE_MISSING"
    assert not out.exists()


# --------------------------------------------------------------------------------------
# F-11 (Minor) -- a qrels cache that caches nothing; N full loads per set.
# --------------------------------------------------------------------------------------


def test_rescore_loads_each_sets_qrels_at_most_once_regardless_of_model_count(smoke_copy, tmp_path, monkeypatch):
    import eval.k1.tools.rescore_packet as mod

    calls = []
    orig = mod.load_set

    def counting(name, *a, **kw):
        calls.append(name)
        return orig(name, *a, **kw)

    monkeypatch.setattr(mod, "load_set", counting)
    rescore_packet(smoke_copy, output_path=tmp_path / "out.json")

    # The fixture carries 2 sets (scifact, scidocs), 3 models each -- 6 (set, model) pairs.
    # A real cache loads qrels once per set; the pre-fix bug loaded once per pair.
    assert sorted(calls) == sorted(set(calls)), f"load_set called more than once per set: {calls}"
    assert len(calls) == 2, calls


# --------------------------------------------------------------------------------------
# F-12 (Minor) -- the diff report is printed, never persisted beside the packet it explains.
# --------------------------------------------------------------------------------------


def test_rescore_report_is_persisted_into_the_written_packet(smoke_copy, tmp_path):
    out = tmp_path / "out.json"
    diff = rescore_packet(smoke_copy, output_path=out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "rescore_report" in written
    assert written["rescore_report"]["run_id"] == diff["run_id"]
    assert written["rescore_report"]["gate_verdict_passed"] == diff["gate_verdict_passed"]


# --------------------------------------------------------------------------------------
# F-13 (Minor) -- the never-overwritten original can be overwritten via --out.
# --------------------------------------------------------------------------------------


def test_rescore_refuses_when_out_equals_the_input_packet_path(smoke_copy):
    original_bytes = smoke_copy.read_bytes()
    with pytest.raises(RescoreRefusalError) as exc:
        rescore_packet(smoke_copy, output_path=smoke_copy)
    assert "must not equal the input packet path" in str(exc.value)
    assert smoke_copy.read_bytes() == original_bytes, "the original packet must be untouched"


# --------------------------------------------------------------------------------------
# F-1 propagation -- the rescored gate_verdict carries the uncommissioned-set fact.
# --------------------------------------------------------------------------------------


def test_rescored_gate_verdict_names_scidocs_as_uncommissioned(smoke_copy, tmp_path):
    out = tmp_path / "out.json"
    rescore_packet(smoke_copy, output_path=out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["gate_verdict"]["uncommissioned_required_sets"] == ["scidocs"]
