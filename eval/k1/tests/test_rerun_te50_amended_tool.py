"""Tests for ``eval/k1/tools/rerun_te50_amended.py``'s ``copy_candidate_rankings`` -- the
part of TE-50's re-run tool that can be exercised without GPU/network (the reference
re-embed and BM25 rebuild are proven by the real re-run itself, filed in the build log)."""
from __future__ import annotations

import pytest

from eval.k1.tools.rerun_te50_amended import (
    CANDIDATE_MODEL_NAME,
    FIVE_SETS,
    copy_candidate_rankings,
)


def _make_run1_output(tmp_path, sets=FIVE_SETS):
    run1_dir = tmp_path / "run1_output"
    for set_name in sets:
        set_dir = run1_dir / "run_files" / "run1-full" / set_name
        set_dir.mkdir(parents=True)
        (set_dir / f"{CANDIDATE_MODEL_NAME}.trec").write_text(
            f"q1 Q0 d1 1 0.900000 u-k1-{CANDIDATE_MODEL_NAME}\n", encoding="utf-8"
        )
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
    dest = tmp_path / "reused_candidate"
    copy_candidate_rankings(run1_dir, dest)
    after = {
        p: p.read_bytes()
        for p in (run1_dir / "run_files" / "run1-full").rglob("*.trec")
    }
    assert before == after
