#!/usr/bin/env python3
"""TE-234 query-path localization on the real Qwen3 embedding artifact.

The full-corpus arm follows the checkpoint README's Transformers recipe:
AutoTokenizer with left padding, AutoModel with its default dtype, last-token
pooling, and L2 normalization. The product arm is sampled at every layer using
SuperSLM's self-checking layer trace and at the actual chunk-batched endpoint
using product_endpoint.cpp. Results are written as JSON for the fact sheet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
from pathlib import Path

import numpy as np


QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query:"
)
SELECTED_ROWS = (0, 1, 7, 14, 21, 28)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64, copy=False)
    b = b.astype(np.float64, copy=False)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def run_sslm_tokenizer(exe: Path, artifact: Path, texts: list[str]) -> list[list[int]]:
    payload = bytearray()
    for text in texts:
        encoded = text.encode("utf-8")
        payload.extend(struct.pack("<Q", len(encoded)))
        payload.extend(encoded)
    proc = subprocess.run(
        [str(exe), str(artifact)],
        input=bytes(payload),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=420,
        check=True,
    )
    rows = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != len(texts):
        raise RuntimeError(
            f"tokenizer probe returned {len(rows)} rows for {len(texts)} inputs: "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    return rows


def load_int8_trace(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("rb") as handle:
        rows, hidden, _fingerprint, capture_mode = struct.unpack("<QQQQ", handle.read(32))
        if capture_mode != 1:
            raise RuntimeError(f"unexpected capture mode {capture_mode}")
        scales = np.empty((rows, 2), dtype=np.int64)
        codes = np.empty((rows, hidden), dtype=np.int8)
        for row in range(rows):
            scales[row] = struct.unpack("<qq", handle.read(16))
            codes[row] = np.frombuffer(handle.read(hidden), dtype=np.int8)
        if handle.read(1):
            raise RuntimeError("trailing bytes in int8 trace")
    values = codes.astype(np.float64)
    values *= (scales[:, 0].astype(np.float64) * np.exp2(scales[:, 1]))[:, None]
    return values, np.column_stack((scales, codes))


def product_sample(
    endpoint_exe: Path,
    trace_exe: Path,
    model_artifact: Path,
    tokenizer_artifact: Path,
    composed: str,
    out_dir: Path,
    stem: str,
) -> tuple[np.ndarray, np.ndarray]:
    vector_path = out_dir / f"{stem}.endpoint.bin"
    endpoint = subprocess.run(
        [
            str(endpoint_exe),
            str(model_artifact),
            str(tokenizer_artifact),
            composed,
            "--dump",
            str(vector_path),
        ],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=420,
        check=True,
    )
    hidden_match = re.search(r"^hidden_size=(\d+)$", endpoint.stdout, re.MULTILINE)
    if not hidden_match:
        raise RuntimeError(f"endpoint did not report hidden_size: {endpoint.stdout}")
    hidden = int(hidden_match.group(1))
    endpoint_vector = np.fromfile(vector_path, dtype=np.float32)
    if endpoint_vector.size != hidden:
        raise RuntimeError(f"endpoint vector width {endpoint_vector.size}, expected {hidden}")

    trace_path = out_dir / f"{stem}.trace.bin"
    # TokenizerView::Encode does not run the HF post-processor. Supplying the
    # special-token literal here yields the same single terminal 151643 that
    # product_endpoint appends after tokenization; corpus-wide equality is
    # checked separately before any hidden-state reading is accepted.
    trace = subprocess.run(
        [
            str(trace_exe),
            str(model_artifact),
            str(tokenizer_artifact),
            composed + "<|endoftext|>",
            "--dump",
            str(trace_path),
        ],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=420,
        check=True,
    )
    if "production and manual-replay paths agree bit-for-bit" not in trace.stdout:
        raise RuntimeError(f"trace self-check evidence missing: {trace.stdout}")
    int8_values, packed = load_int8_trace(trace_path)

    prenorm = (Path(str(vector_path) + ".prenorm.bin")).read_bytes()
    endpoint_m, endpoint_e = struct.unpack("<qq", prenorm[:16])
    endpoint_codes = np.frombuffer(prenorm[16:], dtype=np.int8)
    trace_m, trace_e = (int(packed[-1, 0]), int(packed[-1, 1]))
    trace_codes = packed[-1, 2:].astype(np.int8)
    if endpoint_m != trace_m or endpoint_e != trace_e or not np.array_equal(endpoint_codes, trace_codes):
        raise RuntimeError("per-token trace endpoint differs from product chunk-batched pre-final-norm seam")
    return int8_values, endpoint_vector


def capture_float_stages(model, input_ids, attention_mask) -> tuple[np.ndarray, np.ndarray]:
    import torch

    captured: dict[int, torch.Tensor] = {}

    def hook(index):
        def save(_module, _args, output):
            value = output[0] if isinstance(output, tuple) else output
            captured[index] = value.detach()

        return save

    handles = [model.embed_tokens.register_forward_hook(hook(0))]
    handles += [layer.register_forward_hook(hook(i + 1)) for i, layer in enumerate(model.layers)]
    try:
        with torch.no_grad():
            output = model(input_ids=input_ids, attention_mask=attention_mask)
    finally:
        for handle in handles:
            handle.remove()
    # Samples are unpadded here. Their selected position is the last token.
    stages = np.stack(
        [captured[i][0, -1].float().cpu().numpy() for i in range(len(model.layers) + 1)]
    )
    endpoint = output.last_hidden_state[0, -1].float().cpu().numpy()
    return stages, endpoint


def class_match(query: np.ndarray, documents: np.ndarray, labels: np.ndarray) -> dict[str, object]:
    # Shipping ranking promotes each float32 component to double before its
    # dot/norm accumulation.  Keep the diagnostic's top-1 decisions identical
    # to that contract, including close neighbors.
    query = query.astype(np.float64, copy=False)
    documents = documents.astype(np.float64, copy=False)
    similarity = query @ documents.T
    np.fill_diagonal(similarity, -np.inf)
    nearest = similarity.argmax(axis=1)
    matches = labels[nearest] == labels
    return {
        "matches": int(matches.sum()),
        "total": int(matches.size),
        "rate": float(matches.mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--query-source", type=Path, required=True)
    parser.add_argument("--hf-model", type=Path, required=True)
    parser.add_argument("--model-artifact", type=Path, required=True)
    parser.add_argument("--tokenizer-artifact", type=Path, required=True)
    parser.add_argument("--product-endpoint", type=Path, required=True)
    parser.add_argument("--sslm-tokenizer", type=Path, required=True)
    parser.add_argument("--sslm-trace", type=Path, required=True)
    parser.add_argument("--product-query-vectors", type=Path, required=True)
    parser.add_argument("--product-document-vectors", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line]
    query_source = args.query_source.read_text(encoding="utf-8")
    prefix_definition = re.search(
        r'const char semb::kQueryPrefix\[\]\s*=\s*((?:"(?:\\.|[^"\\])*"\s*)+);',
        query_source,
    )
    if not prefix_definition:
        raise RuntimeError("could not locate kQueryPrefix in product query source")
    source_prefix = "".join(
        json.loads(fragment)
        for fragment in re.findall(r'"(?:\\.|[^"\\])*"', prefix_definition.group(1))
    )
    if source_prefix != QUERY_PREFIX:
        raise RuntimeError(
            f"probe prefix differs from product source: {QUERY_PREFIX!r} != {source_prefix!r}"
        )
    queries = [QUERY_PREFIX + row["text"] for row in rows]
    documents = [row["text"] for row in rows]
    labels = np.asarray([row["class"] for row in rows])

    import torch
    import torch.nn.functional as functional
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(args.hf_model), local_files_only=True, padding_side="left"
    )

    # Stage 1/2: compare every query and every document, including the HF
    # tokenizer's post-processed terminal token and the product's explicit one.
    all_texts = queries + documents
    product_ids = run_sslm_tokenizer(args.sslm_tokenizer, args.tokenizer_artifact, all_texts)
    float_ids = [tokenizer(text)["input_ids"] for text in all_texts]
    token_mismatches = [i for i, (left, right) in enumerate(zip(product_ids, float_ids)) if left != right]
    if token_mismatches:
        raise RuntimeError(f"product/HF token mismatch at rows {token_mismatches[:10]}")

    # Verify the literal-special-token form used by sslm_layer_trace produces
    # one terminal token before tokenize_sslm adds its own product terminator.
    special_probe = run_sslm_tokenizer(
        args.sslm_tokenizer, args.tokenizer_artifact, [all_texts[0] + "<|endoftext|>"]
    )[0]
    if special_probe[:-1] != product_ids[0] or special_probe[-1] != 151643:
        raise RuntimeError("trace special-token composition does not reproduce the product token sequence")

    t0 = time.perf_counter()
    # Deliberately no torch_dtype argument: this is the checkpoint README's
    # AutoModel.from_pretrained call, not a precision chosen by this probe.
    model = AutoModel.from_pretrained(str(args.hf_model), local_files_only=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    load_seconds = time.perf_counter() - t0

    embeddings: list[np.ndarray] = []
    t1 = time.perf_counter()
    for start in range(0, len(all_texts), args.batch_size):
        batch = tokenizer(
            all_texts[start : start + args.batch_size],
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            output = model(**batch)
        left_padding = batch["attention_mask"][:, -1].sum() == batch["attention_mask"].shape[0]
        if left_padding:
            pooled = output.last_hidden_state[:, -1]
        else:
            sequence_lengths = batch["attention_mask"].sum(dim=1) - 1
            pooled = output.last_hidden_state[
                torch.arange(output.last_hidden_state.shape[0], device=device), sequence_lengths
            ]
        normalized = functional.normalize(pooled, p=2, dim=1)
        embeddings.append(normalized.float().cpu().numpy())
    matrix = np.concatenate(embeddings, axis=0).astype(np.float64)
    query_vectors = matrix[: len(rows)]
    document_vectors = matrix[len(rows) :]
    float_seconds = time.perf_counter() - t1

    query_to_document = class_match(query_vectors, document_vectors, labels)
    document_to_document = class_match(document_vectors, document_vectors, labels)

    product_query = np.fromfile(args.product_query_vectors, dtype=np.float32).reshape(len(rows), -1).astype(np.float64)
    product_document = np.fromfile(args.product_document_vectors, dtype=np.float32).reshape(len(rows), -1).astype(np.float64)
    product_query_norm = product_query / np.linalg.norm(product_query, axis=1, keepdims=True)
    product_document_norm = product_document / np.linalg.norm(product_document, axis=1, keepdims=True)
    endpoint_query_cosines = np.sum(product_query_norm * query_vectors, axis=1)
    endpoint_document_cosines = np.sum(product_document_norm * document_vectors, axis=1)
    query_lengths = np.asarray([len(ids) for ids in float_ids[: len(rows)]], dtype=np.float64)
    document_lengths = np.asarray([len(ids) for ids in float_ids[len(rows) :]], dtype=np.float64)
    product_query_to_document = class_match(product_query_norm, product_document_norm, labels)
    product_document_to_document = class_match(product_document_norm, product_document_norm, labels)

    # One ASCII-only specimen per corpus class keeps Windows argv byte transport
    # unambiguous while spanning every class represented by the metric.
    sample_rows: list[tuple[int, dict]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if row["class"] in seen:
            continue
        try:
            row["text"].encode("ascii")
        except UnicodeEncodeError:
            continue
        seen.add(row["class"])
        sample_rows.append((index, row))
    if seen != set(labels.tolist()):
        raise RuntimeError(f"no ASCII specimen for classes {set(labels.tolist()) - seen}")

    stage_results: dict[str, list[dict[str, object]]] = {"query": [], "document": []}
    for kind in ("query", "document"):
        for index, row in sample_rows:
            composed = QUERY_PREFIX + row["text"] if kind == "query" else row["text"]
            encoded = tokenizer(composed, return_tensors="pt").to(device)
            float_stages, float_endpoint = capture_float_stages(
                model, encoded["input_ids"], encoded["attention_mask"]
            )
            int8_stages, product_endpoint = product_sample(
                args.product_endpoint,
                args.sslm_trace,
                args.model_artifact,
                args.tokenizer_artifact,
                composed,
                args.out_dir,
                f"{kind}-{row['label']}",
            )
            if int8_stages.shape != float_stages.shape:
                raise RuntimeError(
                    f"stage shape mismatch for {kind}/{row['label']}: "
                    f"{int8_stages.shape} vs {float_stages.shape}"
                )
            stage_results[kind].append(
                {
                    "label": row["label"],
                    "class": row["class"],
                    "positions": len(float_ids[index if kind == "query" else len(rows) + index]),
                    "cosine_by_row": {
                        str(row_index): cosine(int8_stages[row_index], float_stages[row_index])
                        for row_index in SELECTED_ROWS
                    },
                    "final_norm_cosine": cosine(product_endpoint, float_endpoint),
                    "product_pre_l2_norm": float(np.linalg.norm(product_endpoint.astype(np.float64))),
                    "float_pre_l2_norm": float(np.linalg.norm(float_endpoint.astype(np.float64))),
                    "normalized_endpoint_l2": float(
                        np.linalg.norm(
                            product_endpoint.astype(np.float64) / np.linalg.norm(product_endpoint)
                            - float_endpoint.astype(np.float64) / np.linalg.norm(float_endpoint)
                        )
                    ),
                }
            )

    aggregate: dict[str, dict[str, object]] = {}
    for kind, specimens in stage_results.items():
        aggregate[kind] = {
            "sample_count": len(specimens),
            "rows": {
                str(row_index): {
                    "mean_cosine": float(
                        np.mean([item["cosine_by_row"][str(row_index)] for item in specimens])
                    ),
                    "min_cosine": float(
                        np.min([item["cosine_by_row"][str(row_index)] for item in specimens])
                    ),
                    "max_cosine": float(
                        np.max([item["cosine_by_row"][str(row_index)] for item in specimens])
                    ),
                }
                for row_index in SELECTED_ROWS
            },
            "final_norm": {
                "mean_cosine": float(np.mean([item["final_norm_cosine"] for item in specimens])),
                "min_cosine": float(np.min([item["final_norm_cosine"] for item in specimens])),
                "max_cosine": float(np.max([item["final_norm_cosine"] for item in specimens])),
            },
        }

    class_counts = {str(name): int((labels == name).sum()) for name in sorted(set(labels.tolist()))}
    chance = float(
        sum(count * (count - 1) for count in class_counts.values())
        / (len(rows) * (len(rows) - 1))
    )
    result = {
        "corpus": {
            "path": str(args.corpus),
            "sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
            "texts": len(rows),
            "class_counts": class_counts,
            "empirical_class_chance": chance,
        },
        "composition": {
            "query_prefix": QUERY_PREFIX,
            "product_query_source": str(args.query_source),
            "query_prefix_utf8_hex": QUERY_PREFIX.encode().hex(),
            "query_strings_checked": len(queries),
            "document_strings_checked": len(documents),
        },
        "tokenization": {
            "pairs_checked": len(all_texts),
            "mismatches": len(token_mismatches),
            "terminal_id": 151643,
            "first_query_ids": product_ids[0],
            "first_document_ids": product_ids[len(rows)],
        },
        "float_reference": {
            "device": device,
            "dtype": str(model.dtype),
            "model_load_seconds": load_seconds,
            "embedding_seconds": float_seconds,
            "pooling": "last attended token, then L2 normalize",
            "query_to_document_self_excluding_class_match_at_1": query_to_document,
            "document_to_document_self_excluding_class_match_at_1": document_to_document,
        },
        "product_full_corpus": {
            "query_to_document_self_excluding_class_match_at_1": product_query_to_document,
            "document_to_document_self_excluding_class_match_at_1": product_document_to_document,
            "query_endpoint_cosine_vs_float": {
                "mean": float(endpoint_query_cosines.mean()),
                "median": float(np.median(endpoint_query_cosines)),
                "min": float(endpoint_query_cosines.min()),
                "max": float(endpoint_query_cosines.max()),
                "mean_cosine_defect": float(1.0 - endpoint_query_cosines.mean()),
                "p25": float(np.percentile(endpoint_query_cosines, 25)),
                "p75": float(np.percentile(endpoint_query_cosines, 75)),
                "correlation_with_token_count": float(
                    np.corrcoef(endpoint_query_cosines, query_lengths)[0, 1]
                ),
            },
            "document_endpoint_cosine_vs_float": {
                "mean": float(endpoint_document_cosines.mean()),
                "median": float(np.median(endpoint_document_cosines)),
                "min": float(endpoint_document_cosines.min()),
                "max": float(endpoint_document_cosines.max()),
                "mean_cosine_defect": float(1.0 - endpoint_document_cosines.mean()),
                "p25": float(np.percentile(endpoint_document_cosines, 25)),
                "p75": float(np.percentile(endpoint_document_cosines, 75)),
                "correlation_with_token_count": float(
                    np.corrcoef(endpoint_document_cosines, document_lengths)[0, 1]
                ),
            },
            "same_text_query_document_cosine": {
                "product_median": float(
                    np.median(np.sum(product_query_norm * product_document_norm, axis=1))
                ),
                "float_median": float(np.median(np.sum(query_vectors * document_vectors, axis=1))),
            },
        },
        "stage_samples": stage_results,
        "stage_aggregate": aggregate,
    }
    output_path = args.result if args.result else args.out_dir / "result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"result_written={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
