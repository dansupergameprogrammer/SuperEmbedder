"""The top-level orchestrator: loader -> embed -> score -> report, one code path for the
smoke run, Run 0 (scout), Run 1 (full protocol) and TE-50's amended re-run -- run identity is
entirely determined by the ``RunSpec`` passed in (``run_spec.py``).

Design reference: te33-k1-gate-design-2026-08-25.md Section 10.1 (packet fields), Section 4.4
(paired resolving power, TE-49 amendment). This module assembles the packet's readings,
guards and replication fields it can produce from a single-machine single-pass run; R4
(cross-machine) and the full commissioning constructions are explicitly out of this module's
scope (see module docstring in ``eval/k1/__init__.py`` and the build log).

**Candidate reuse (TE-50, D-SLM5390's re-run).** A ``ModelSpec`` whose
``reuse_trec_run_dir`` is set is not embedded or ranked -- its TREC run is read back from
``<reuse_trec_run_dir>/<set_name>/<model_name>.trec`` instead, so an already-computed,
already-costed ranking (Run 1's candidate) can be scored under this module's current scoring
and gate logic without paying to re-embed it. See ``embed_runner.ModelSpec`` and
``run_spec.run1_amended_rerun``. **TE-51 review, H-3/H-4:** the same directory must also carry
a ``<set_name>/<model_name>.manifest.json`` sidecar (the reused arm's real provenance, written
by the caller -- see ``tools/rerun_te50_amended.py::copy_candidate_rankings``); this module
refuses (``K1GuardError``) a reuse directory missing that sidecar, and separately refuses a
reused ranking that does not cover every query the run is scoring.

**Paired resolving power (design Section 4.4, TE-49 amendment, D-SLM5385).** For every
candidate model (a model that is neither the reference nor bm25), this module computes and
records ``f1_paired_resolving_power`` (``rank_score.paired_resolving_power(cand, ref)``) and
``f2_paired_resolving_power`` (``rank_score.paired_resolving_power(cand, bm25)``) alongside
its marginal ``achieved_resolving_power`` -- the two paired figures are what ``gate.py``'s
F1/F2 rules act on; the marginal figure remains diagnostic and R2's own tolerance quantity.

Every entry point prints ``eval.k1.COMMISSIONING_NOTICE`` before returning a packet.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from eval.k1 import COMMISSIONING_NOTICE
from eval.k1.bm25_baseline import BM25_ANALYZER, bm25_topk, build_bm25_index
from eval.k1.embed_runner import embed_corpus, embed_queries
from eval.k1.gate import BM25_MODEL_NAME, GateVerdict, REFERENCE_SUFFIX, evaluate_gate
from eval.k1.guards import (
    K1GuardError,
    check_query_convention_recorded,
    check_reused_run_covers_population,
    check_unpinned_revision,
    validate_qrels_join,
)
from eval.k1.rank_score import (
    achieved_resolving_power,
    cosine_topk,
    executed_chance_level,
    mrr_at_k,
    ndcg_at_k_own,
    paired_resolving_power,
    read_trec_run,
    recall_at_k,
    write_trec_run,
)
from eval.k1.self_exclusion import SELF_EXCLUSION_NOTE
from eval.k1.run_spec import RunSpec
from eval.k1.sets_lock import SetLockEntry, load_set, read_sets_lock

TOP_K_POOL = 100  # depth of the run file kept per query (deep enough for recall@10/MRR@10
                   # diagnostics beyond rank 10; the deciding metric only reads the top 10)


def _build_qrels_by_query(qrels_rows: List[dict]) -> Dict[str, Dict[str, float]]:
    by_query: Dict[str, Dict[str, float]] = {}
    for row in qrels_rows:
        by_query.setdefault(row["query-id"], {})[row["corpus-id"]] = float(row["score"])
    return by_query


def _load_reused_arm_manifests(
    reuse_dir: str, set_name: str, model_name: str, reuse_path: Path
) -> Tuple[dict, dict]:
    """Loads the manifest sidecar for a candidate-reuse model (TE-50,
    ``embed_runner.ModelSpec.reuse_trec_run_dir``) and returns ``(corpus_manifest_dict,
    query_manifest_dict)`` -- TE-51 review, H-3. Before this, the reuse path replaced BOTH
    manifests with a two-key ``{"reused_from", "note"}`` stub, so the packet could not be
    checked at all (design Section 17.6 dimension 7: "a packet with neither field is not a K1
    reading"). The sidecar (``<reuse_dir>/<set_name>/<model_name>.manifest.json``) is written by
    the caller that populated ``reuse_dir`` -- see
    ``tools/rerun_te50_amended.py::copy_candidate_rankings``, which sources it from the run
    that actually produced the ranking being reused, backfilling only what that source predates
    (e.g. ``query_convention``, a field newer than Run 1's own packet) from the model's own
    static spec.

    Deliberately does NOT invent or backfill anything itself: a sidecar that is missing, or
    whose ``query_manifest`` genuinely carries no ``query_convention``, is carried through
    exactly as thin as it arrived -- ``runner.run_gate``'s own
    ``check_query_convention_recorded`` call (TE-51 H-5) is what refuses it, at the point the
    packet is assembled. Papering over a missing field here would make that guard unreachable
    again, on a different path, the same defect H-5 already found once.

    Raises ``K1GuardError`` (``K1_REUSE_MANIFEST_MISSING``) if the sidecar itself is absent."""
    manifest_path = Path(reuse_dir) / set_name / f"{model_name}.manifest.json"
    if not manifest_path.exists():
        raise K1GuardError(
            "K1_REUSE_MANIFEST_MISSING",
            f"[{set_name}] '{model_name}' reuses a TREC run from {reuse_dir} but carries no "
            f"manifest sidecar ({manifest_path}) -- the reused arm's provenance "
            f"(corpus_manifest, query_manifest) cannot be carried forward without it "
            f"(TE-51 H-3; design Section 17.6 dimension 7)",
        )
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    reuse_note = {
        "note": "TE-50: ranking reused from a prior run per the ticket brief; not re-embedded",
        "reused_from": str(reuse_path),
    }
    corpus_manifest_dict = {**source.get("corpus_manifest", {}), **reuse_note}
    query_manifest_dict = {**source.get("query_manifest", {}), **reuse_note}
    return corpus_manifest_dict, query_manifest_dict


def _select_smoke_queries(
    test_query_ids: List[str], qrels_by_query: Dict[str, Dict[str, float]], corpus_ids: set
) -> List[str]:
    """For a truncated corpus (smoke run only): keeps only the test queries with at least
    one positively-judged document inside the truncated corpus, so the zero-qrels guard
    passes on a genuine, non-degenerate subset rather than being bypassed. Queries with no
    surviving relevant document are a correct and expected consequence of truncating the
    corpus, not a defect -- they are simply excluded from this slice, the same way a
    real corpus revision that dropped a document would exclude the queries that only had
    that document judged relevant."""
    kept = []
    for qid in test_query_ids:
        rels = qrels_by_query.get(qid, {})
        if any(score > 0 and docid in corpus_ids for docid, score in rels.items()):
            kept.append(qid)
    return kept


def run_gate(
    run_spec: RunSpec,
    sets_lock_path: Path,
    anchors_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> dict:
    print(COMMISSIONING_NOTICE)
    lock = read_sets_lock(sets_lock_path)
    anchors = json.loads(anchors_path.read_text(encoding="utf-8")) if anchors_path and anchors_path.exists() else None

    packet: dict = {
        "commissioning_notice": COMMISSIONING_NOTICE,
        "self_exclusion_convention": SELF_EXCLUSION_NOTE,
        "run_id": run_spec.run_id,
        "is_gate_reading": run_spec.is_gate_reading,
        "date": datetime.now().isoformat(timespec="seconds"),
        "sets": {},
    }

    for set_name in run_spec.set_names:
        lock_entry: SetLockEntry = lock[set_name]
        corpus, queries, qrels_rows = load_set(
            set_name, lock_entry,
            max_corpus_docs=run_spec.max_corpus_docs,
            allow_missing_license=run_spec.allow_missing_license,
        )
        corpus_ids = {row["_id"] for row in corpus}
        qrels_by_query = _build_qrels_by_query(qrels_rows)
        test_query_ids = sorted({row["query-id"] for row in qrels_rows})

        if run_spec.max_corpus_docs is not None:
            test_query_ids = _select_smoke_queries(test_query_ids, qrels_by_query, corpus_ids)

        # THE ZERO-QRELS GUARD (component 4) -- runs before any scoring path is reached.
        guard_report = validate_qrels_join(set_name, test_query_ids, qrels_by_query, corpus_ids)

        # Scope every scoring call to exactly the query population being evaluated. On an
        # untruncated run this is a no-op (qrels_by_query's keys already equal
        # test_query_ids, both being the full test split). On a truncated (smoke) run,
        # qrels_by_query still carries every test-split query's qrels -- passing it
        # unscoped would average nDCG over queries that were never embedded or ranked,
        # silently diluting the mean by the same "aggregate over the wrong population"
        # mechanism guards.py exists to catch at the join level. Caught at the bench: an
        # early smoke run without this line reported nDCG@10 = 0.01 identically across
        # every model (3 correctly-scored queries averaged over the full 300-query
        # denominator) -- see the build log.
        qrels_by_query = {qid: qrels_by_query[qid] for qid in test_query_ids}

        queries_used = [q for q in queries if q["_id"] in set(test_query_ids)]

        set_result: dict = {
            "hf_repo": lock_entry.hf_repo,
            "revision": lock_entry.revision,
            "corpus_docs_used": len(corpus),
            "test_queries_used": len(test_query_ids),
            "guard": asdict(guard_report),
            "models": {},
        }

        chance = executed_chance_level(
            qrels_by_query, test_query_ids, list(corpus_ids), k=run_spec.k,
            trials=run_spec.chance_trials, seed=run_spec.seed,
        )
        set_result["executed_chance"] = {"mean": chance.mean, "std": chance.std, "trials": chance.trials}

        # Per-query nDCG, by model name, for THIS set only -- populated below as each model
        # (including bm25) is scored, then consumed after the model loop to compute the
        # paired resolving powers (design Section 4.4, TE-49 amendment): F1 pairs a
        # candidate against the reference's per-query dict, F2 against bm25's.
        per_query_ndcg_by_model: Dict[str, Dict[str, float]] = {}
        reference_model_name: Optional[str] = None

        if run_spec.include_bm25:
            bm25_index, bm25_corpus_ids = build_bm25_index(
                corpus, lock_entry.bm25_k1, lock_entry.bm25_b, set_name=set_name
            )
            bm25_run = bm25_topk(bm25_index, bm25_corpus_ids, queries_used, k=TOP_K_POOL)
            if output_dir is not None:
                run_files_dir = output_dir / "run_files" / run_spec.run_id / set_name
                run_files_dir.mkdir(parents=True, exist_ok=True)
                write_trec_run(bm25_run, run_files_dir / "bm25.trec", run_name="u-k1-bm25")
            per_q_ndcg, mean_ndcg = ndcg_at_k_own(qrels_by_query, bm25_run, k=run_spec.k)
            _per_q_recall, mean_recall = recall_at_k(qrels_by_query, bm25_run, k=run_spec.k)
            _per_q_mrr, mean_mrr = mrr_at_k(qrels_by_query, bm25_run, k=run_spec.k)
            per_query_ndcg_by_model[BM25_MODEL_NAME] = per_q_ndcg
            set_result["models"][BM25_MODEL_NAME] = {
                "ndcg_at_10": mean_ndcg,
                "recall_at_10": mean_recall,
                "mrr_at_10": mean_mrr,
                "achieved_resolving_power": achieved_resolving_power(per_q_ndcg),
                "bm25_k1": lock_entry.bm25_k1,
                "bm25_b": lock_entry.bm25_b,
                "bm25_params_derived": lock_entry.bm25_params_derived,
                "bm25_analyzer": BM25_ANALYZER,
            }

        for model_spec in run_spec.models:
            reuse_dir = getattr(model_spec, "reuse_trec_run_dir", None)
            if reuse_dir:
                # TE-50 (D-SLM5390's re-run): this model's ranking is read back rather than
                # re-embedded -- see runner.py's module docstring and
                # run_spec.run1_amended_rerun. TE-51 review, H-3: the reused arm's provenance
                # (corpus_manifest, query_manifest) is carried forward from a manifest sidecar
                # the caller writes alongside the .trec file (see
                # tools/rerun_te50_amended.py::copy_candidate_rankings) -- a two-key
                # {"reused_from", "note"} stub used to stand in for both manifests, which
                # design Section 17.6 dimension 7 does not accept ("a packet with neither field
                # is not a K1 reading"). check_unpinned_revision also runs here (H-3: it was
                # skipped on this path, same as check_query_convention_recorded below) -- the
                # revision is known statically from model_spec, not something re-embedding
                # alone would have checked.
                check_unpinned_revision(model_spec.hf_repo, model_spec.revision)
                reuse_path = Path(reuse_dir) / set_name / f"{model_spec.name}.trec"
                corpus_manifest_dict, query_manifest_dict = _load_reused_arm_manifests(
                    reuse_dir, set_name, model_spec.name, reuse_path
                )
                run = read_trec_run(reuse_path)
                # TE-51 review, H-4: a reused ranking must cover every query this run is
                # scoring -- ndcg_at_k_own scores an absent query 0.0 rather than excluding it,
                # so a short reused run file silently depresses the reading instead of failing.
                check_reused_run_covers_population(set_name, model_spec.name, test_query_ids, list(run.keys()))
                if output_dir is not None:
                    run_files_dir = output_dir / "run_files" / run_spec.run_id / set_name
                    run_files_dir.mkdir(parents=True, exist_ok=True)
                    write_trec_run(run, run_files_dir / f"{model_spec.name}.trec", run_name=f"u-k1-{model_spec.name}")
            else:
                corpus_vecs, corpus_vec_ids, corpus_manifest = embed_corpus(
                    model_spec, corpus, device=run_spec.device
                )
                query_vecs, query_vec_ids, query_manifest = embed_queries(
                    model_spec, queries_used, device=run_spec.device
                )
                run = cosine_topk(query_vecs, query_vec_ids, corpus_vecs, corpus_vec_ids, k=TOP_K_POOL)
                corpus_manifest_dict = asdict(corpus_manifest)
                query_manifest_dict = asdict(query_manifest)

                if output_dir is not None:
                    run_files_dir = output_dir / "run_files" / run_spec.run_id / set_name
                    run_files_dir.mkdir(parents=True, exist_ok=True)
                    write_trec_run(run, run_files_dir / f"{model_spec.name}.trec", run_name=f"u-k1-{model_spec.name}")

            # TE-51 review, H-5: the packet-assembly point -- the one place a model result's
            # query-side convention is genuinely knowable and, on the reuse path, genuinely
            # producible as missing (H-3's stub carried none at all). Runs for both branches
            # above; on the real-embed branch this can never fire (embed_texts always records
            # either the model's own prompt or the literal "bare"), which is expected -- the
            # guard's job is to be ABLE to fire on the path that can actually produce the
            # defect, not to fire on every path.
            check_query_convention_recorded(model_spec.name, query_manifest_dict.get("query_convention"))

            per_q_ndcg, mean_ndcg = ndcg_at_k_own(qrels_by_query, run, k=run_spec.k)
            _per_q_recall, mean_recall = recall_at_k(qrels_by_query, run, k=run_spec.k)
            _per_q_mrr, mean_mrr = mrr_at_k(qrels_by_query, run, k=run_spec.k)
            rp = achieved_resolving_power(per_q_ndcg)
            per_query_ndcg_by_model[model_spec.name] = per_q_ndcg
            if model_spec.name.endswith(REFERENCE_SUFFIX):
                reference_model_name = model_spec.name

            model_result = {
                "ndcg_at_10": mean_ndcg,
                "recall_at_10": mean_recall,
                "mrr_at_10": mean_mrr,
                "achieved_resolving_power": rp,
                "corpus_manifest": corpus_manifest_dict,
                "query_manifest": query_manifest_dict,
            }

            if run_spec.r1_independent_scorer:
                try:
                    from eval.k1.rank_score import ndcg_at_k_pytrec

                    _per_q_r1, mean_r1 = ndcg_at_k_pytrec(qrels_by_query, run, k=run_spec.k)
                    model_result["ndcg_at_10_r1_independent"] = mean_r1
                    model_result["r1_agreement_delta"] = abs(mean_ndcg - mean_r1)
                except ImportError as e:
                    model_result["r1_independent_scorer_error"] = str(e)

            if anchors and set_name in anchors.get("reference", {}) and model_spec.name.endswith(REFERENCE_SUFFIX):
                anchor = anchors["reference"][set_name]
                model_result["published_anchor_ndcg_at_10"] = anchor["ndcg_at_10"]
                model_result["r2_delta_vs_anchor"] = abs(mean_ndcg - anchor["ndcg_at_10"])

            set_result["models"][model_spec.name] = model_result

        # Paired resolving power (design Section 4.4, TE-49 amendment, D-SLM5385): computed
        # per candidate model, against the reference's and bm25's per-query nDCG@10 dicts
        # from THIS SAME set -- never a different run, never a stored constant. A model with
        # no reference or no bm25 reading in this set (see gate.py's own skip handling) is
        # left without one of the two fields, which evaluate_gate treats as a skip rather
        # than a guess.
        for model_name, model_result in set_result["models"].items():
            if model_name == BM25_MODEL_NAME or model_name.endswith(REFERENCE_SUFFIX):
                continue
            cand_per_q = per_query_ndcg_by_model.get(model_name)
            if cand_per_q is None:
                continue
            if reference_model_name is not None:
                model_result["f1_paired_resolving_power"] = paired_resolving_power(
                    cand_per_q, per_query_ndcg_by_model[reference_model_name]
                )
            if BM25_MODEL_NAME in per_query_ndcg_by_model:
                model_result["f2_paired_resolving_power"] = paired_resolving_power(
                    cand_per_q, per_query_ndcg_by_model[BM25_MODEL_NAME]
                )

        packet["sets"][set_name] = set_result

    # The verdict stage (design Section 4, U-K1 fix round Finding C). Computes the F1/F2
    # floor-gate arithmetic over this packet's own readings. Its standing is exactly the
    # standing of the instrument that produced the readings it was computed from -- see
    # eval.k1.COMMISSIONING_NOTICE for the current status, the ONE place that status is
    # asserted (design Section 6.3).
    gate_verdict: GateVerdict = evaluate_gate(packet)
    packet["gate_verdict"] = asdict(gate_verdict)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{run_spec.run_id}.json"
        json_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
        table_path = output_dir / f"{run_spec.run_id}.txt"
        table_path.write_text(render_human_table(packet), encoding="utf-8")

    return packet


def render_human_table(packet: dict) -> str:
    lines = [
        packet.get("commissioning_notice", packet.get("quarantine_notice", COMMISSIONING_NOTICE)),
        "",
        packet.get("self_exclusion_convention", SELF_EXCLUSION_NOTE),
        "",
        f"Run: {packet['run_id']}  ({packet['date']})",
        "",
    ]
    for set_name, set_result in packet["sets"].items():
        lines.append(f"== {set_name} ==  corpus={set_result['corpus_docs_used']} "
                     f"test_queries={set_result['test_queries_used']}")
        chance = set_result["executed_chance"]
        lines.append(f"  executed chance nDCG@10: {chance['mean']:.4f} (std {chance['std']:.4f}, "
                     f"{chance['trials']} trials)")
        # TE-51 review, H-8: the RP column used to be headed "ach.RP" and print
        # achieved_resolving_power -- the MARGINAL dispersion -- while the verdict notes below
        # quote the PAIRED resolving power the gate has acted on since the TE-49 amendment
        # (design Section 4.4): three numbers, one label. Design Section 6.5 requires all three
        # dispersions reported beside every score; this table now shows all three, the marginal
        # one relabeled so it is not mistaken for what the gate acts on. bm25/reference rows
        # carry no paired RP of their own (they are the floors, not the candidates being
        # graded) and print "nan" for those two columns -- TE-53 review, J-4 (Minor): this
        # comment previously said "blank"; the actual printed value (below, via
        # ``m.get(..., float('nan'))``) is the literal string "nan", which is deliberately
        # better than a fabricated 0.0 -- a reader can tell a missing value from a zero one.
        header = (
            f"  {'model':<32}{'nDCG@10':>10}{'recall@10':>12}{'MRR@10':>10}"
            f"{'marg.RP':>10}{'f1.RP':>10}{'f2.RP':>10}"
        )
        lines.append(header)
        for name, m in set_result["models"].items():
            lines.append(
                f"  {name:<32}{m['ndcg_at_10']:>10.4f}{m['recall_at_10']:>12.4f}"
                f"{m['mrr_at_10']:>10.4f}{m.get('achieved_resolving_power', float('nan')):>10.4f}"
                f"{m.get('f1_paired_resolving_power', float('nan')):>10.4f}"
                f"{m.get('f2_paired_resolving_power', float('nan')):>10.4f}"
            )
        lines.append("")

    gate_verdict = packet.get("gate_verdict")
    if gate_verdict is not None:
        # No status claim is restated here -- the notice printed at the top of this table
        # (eval.k1.COMMISSIONING_NOTICE) is this packet's one standing statement of the
        # instrument's status, and this verdict's own standing is exactly that status's.
        lines.append("== gate verdict (F1/F2, design Section 4) ==")
        lines.append(f"  overall: {'PASS' if gate_verdict['passed'] else 'FAIL/INCOMPLETE'} -- {gate_verdict['reason']}")
        for set_name, by_model in gate_verdict["per_set"].items():
            for model_name, verdict in by_model.items():
                lines.append(f"  [{set_name}] {model_name}: {'PASS' if verdict['passed'] else 'FAIL'}")
                lines.append(f"    {verdict['f1']['note']}")
                lines.append(f"    {verdict['f2']['note']}")
        for skip in gate_verdict.get("skips", []):
            lines.append(f"  SKIPPED: {skip}")
        lines.append("")
    return "\n".join(lines)
