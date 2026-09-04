#!/usr/bin/env python3
"""tools/c12b/mint_c12b_corpus.py -- mints C12b's ONE fixed input population
(`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C12b: "One instrument, one
corpus, one artifact ... per-row SHA-256 over the emitted {codes, m, e}
seam bytes, row by row"), committed as data with a SHA-256 manifest per
sec 4.4b's own corpus discipline ("committed as data rather than inline
literals, with a SHA-256 manifest, its authorship and date recorded, and
its selection rule stated").

THE CORPUS is the plan's own 239-document retrieval-agreement corpus (sec
2.5's cell: 140 `id` + 99 `ood`), assembled by the SAME selection rule the
archived T-1777 tooling used -- imported from
`archive/superslm-t1777-retrieval-agreement/files/tools/t1777_build_corpus.py`
(the class-proportional, evenly-spaced sample of the shopkeeper spike corpus)
and `t1777_ood_corpus.py` (the 99 original out-of-domain sentences) -- never
re-authored here. The shopkeeper corpus's text itself is read from the
records tree at mint time and COMMITTED into the fixture, so the fixture
is self-contained thereafter.

THE TOKEN IDS are produced by the ratified candidate's own pinned tokenizer
(sec 2.1: HF `Qwen/Qwen3-Embedding-0.6B` @ `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`),
through `transformers.AutoTokenizer`, and cross-checked against the raw
`tokenizers` library over the same `tokenizer.json`. Two sequences are
recorded per document:

  content_ids     -- `tok(text, add_special_tokens=False)`: the document's
                     own content tokens. THIS is what the encoder is handed;
                     SuperEmbedder's own code appends the single fixed end
                     token id (sec 3.2's corrected PS-N position rule,
                     D-SLM4731 superseded: id 151643, `<|endoftext|>`).
  hf_default_ids  -- `tok(text)` (add_special_tokens=True, the model card's
                     own reference call), recorded so the append rule is
                     PROVEN per document rather than assumed: this script
                     refuses to mint unless hf_default_ids == content_ids +
                     [151643] for every one of the 239 documents, and unless
                     the plan's own executed example (`tok("hello world")` ->
                     [14990, 1879, 151643], sec 3.2) reproduces.

WHY TOKEN IDS AND NOT TEXT reach the instrument: no converter-emitted
Qwen3 tokenizer artifact exists on this machine (Track E's output, E0b),
and the Qwen3 `.sslm` this slice runs carries no Tokenizer section (its
proof manifest lists Config/Weights/Biases/RopeTables/WeightScales/
CompositionConstants/KvLandingScales/KvLandingReciprocals/SigmoidLut only).
Removing the tokenizer term from C12b's comparison is the same discipline
sec 4.2's "shared token-id construction" already applies; tokenizer
determinism is C23's own cell, not C12b's.

OUTPUTS (all under --out-dir, default tests/fixtures/c12b):
  corpus-239.jsonl          one record per document: label, domain, class,
                            text, content_ids, hf_default_ids
  corpus-239.tokens.tsv     `<label>\\t<comma-separated content_ids>` -- the
                            instrument's own input format
  corpus-239.manifest.json  provenance + SHA-256 of both files above and of
                            tokenizer.json

Exit codes: 0 minted; 1 usage/environment; 2 a precondition refused
(append rule, plan example, count).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARCHIVE_TOOLS = REPO_ROOT / "archive" / "superslm-t1777-retrieval-agreement" / "files" / "tools"
DEFAULT_SHOPKEEPER = Path(r"D:\Wizard\Claude\Docs\spike\shopkeeper_corpus_v1.jsonl")
CANDIDATE_REPO = "Qwen/Qwen3-Embedding-0.6B"
CANDIDATE_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
DEFAULT_SNAPSHOT = Path(r"D:\hf_cache\hub\models--Qwen--Qwen3-Embedding-0.6B\snapshots") / CANDIDATE_REVISION
APPENDED_TOKEN_ID = 151643  # <|endoftext|>, sec 3.2's corrected PS-N position rule
N_ID = 140
N_OOD = 99


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shopkeeper-corpus", default=str(DEFAULT_SHOPKEEPER))
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT),
                    help="the pinned HF snapshot directory (tokenizer.json, tokenizer_config.json, ...)")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "tests" / "fixtures" / "c12b"))
    args = ap.parse_args(argv)

    shopkeeper = Path(args.shopkeeper_corpus)
    snapshot = Path(args.snapshot)
    if not shopkeeper.exists():
        print(f"SEMB_C12B_CORPUS_SOURCE_MISSING: {shopkeeper}", file=sys.stderr)
        return 1
    if not (snapshot / "tokenizer.json").exists():
        print(f"SEMB_C12B_TOKENIZER_MISSING: {snapshot / 'tokenizer.json'}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(ARCHIVE_TOOLS))
    import t1777_build_corpus  # noqa: E402  (the archived selection rule, imported not re-authored)
    from t1777_ood_corpus import OOD_DOCUMENTS  # noqa: E402

    t1777_build_corpus.SHOPKEEPER_CORPUS = shopkeeper
    id_docs = t1777_build_corpus.sample_id_corpus(N_ID)
    ood_docs = [{"id": f"ood-{i:03d}", "class": "ood", "text": t} for i, t in enumerate(OOD_DOCUMENTS)]
    docs = []
    for d in id_docs:
        docs.append({"label": f"id_{d['id']}", "domain": "id", "class": d["class"], "text": d["text"]})
    for d in ood_docs:
        docs.append({"label": f"ood_{d['id']}", "domain": "ood", "class": d["class"], "text": d["text"]})
    labels = [d["label"] for d in docs]
    if len(set(labels)) != len(labels):
        print("SEMB_C12B_DUPLICATE_LABEL", file=sys.stderr)
        return 2
    n_id = sum(1 for d in docs if d["domain"] == "id")
    n_ood = sum(1 for d in docs if d["domain"] == "ood")
    if (n_id, n_ood) != (N_ID, N_OOD):
        print(f"SEMB_C12B_COUNT_MISMATCH: {n_id} id / {n_ood} ood, expected {N_ID}/{N_OOD}", file=sys.stderr)
        return 2

    import tokenizers  # noqa: E402
    import transformers  # noqa: E402
    tok = transformers.AutoTokenizer.from_pretrained(str(snapshot))
    raw = tokenizers.Tokenizer.from_file(str(snapshot / "tokenizer.json"))

    # The plan's own executed example (sec 3.2) must reproduce before anything is minted.
    probe = tok("hello world")["input_ids"]
    probe_content = tok("hello world", add_special_tokens=False)["input_ids"]
    if probe != [14990, 1879, APPENDED_TOKEN_ID] or probe_content != [14990, 1879]:
        print(f"SEMB_C12B_PLAN_EXAMPLE_REFUSED: tok('hello world') -> {probe}, "
              f"add_special_tokens=False -> {probe_content}", file=sys.stderr)
        return 2

    for d in docs:
        content = tok(d["text"], add_special_tokens=False)["input_ids"]
        default = tok(d["text"])["input_ids"]
        raw_content = raw.encode(d["text"], add_special_tokens=False).ids
        raw_default = raw.encode(d["text"]).ids
        if default != content + [APPENDED_TOKEN_ID]:
            print(f"SEMB_C12B_APPEND_RULE_REFUSED: {d['label']}: default={default[-3:]} "
                  f"content_tail={content[-2:]}", file=sys.stderr)
            return 2
        if raw_content != content or raw_default != default:
            print(f"SEMB_C12B_TOKENIZER_LIBS_DISAGREE: {d['label']}", file=sys.stderr)
            return 2
        if not content:
            print(f"SEMB_C12B_EMPTY_DOCUMENT: {d['label']}", file=sys.stderr)
            return 2
        d["content_ids"] = content
        d["hf_default_ids"] = default

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "corpus-239.jsonl"
    tsv = out_dir / "corpus-239.tokens.tsv"
    with open(jsonl, "w", encoding="utf-8", newline="\n") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(tsv, "w", encoding="utf-8", newline="\n") as f:
        for d in docs:
            f.write(d["label"] + "\t" + ",".join(str(i) for i in d["content_ids"]) + "\n")

    n_tokens = [len(d["content_ids"]) for d in docs]
    manifest = {
        "schema": "semb_c12b_corpus_manifest_v1",
        "minted": _dt.date.today().isoformat(),
        "minted_by": "tools/c12b/mint_c12b_corpus.py (this file; selection rule imported from the archived "
                     "T-1777 generator, never re-authored)",
        "selection_rule": "140 id: class-proportional, evenly-spaced sample of shopkeeper_corpus_v1.jsonl "
                          "(600 records) via t1777_build_corpus.sample_id_corpus(140); 99 ood: "
                          "t1777_ood_corpus.OOD_DOCUMENTS in order",
        "shopkeeper_corpus_sha256": sha256_file(shopkeeper),
        "tokenizer": {
            "repo": CANDIDATE_REPO,
            "revision": CANDIDATE_REVISION,
            "tokenizer_json_sha256": sha256_file(snapshot / "tokenizer.json"),
            "transformers_version": transformers.__version__,
            "tokenizers_version": tokenizers.__version__,
            "appended_token_id": APPENDED_TOKEN_ID,
            "append_rule_proven_per_document": True,
        },
        "documents": len(docs),
        "id": n_id,
        "ood": n_ood,
        "content_tokens_total": sum(n_tokens),
        "content_tokens_min": min(n_tokens),
        "content_tokens_max": max(n_tokens),
        "files": {
            jsonl.name: sha256_file(jsonl),
            tsv.name: sha256_file(tsv),
        },
    }
    with open(out_dir / "corpus-239.manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"minted {len(docs)} documents ({n_id} id, {n_ood} ood), {sum(n_tokens)} content tokens "
          f"(min {min(n_tokens)}, max {max(n_tokens)}) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
