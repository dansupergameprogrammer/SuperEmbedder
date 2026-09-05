"""Pinned real-input prerequisites for public K-06d / K-12 (TE-120).

Generation requires the independently pinned HF tokenizer JSON and tokenizers 0.22.2.
Verification is stdlib-only and checks against the committed recipe receipt.
The foreign artifact is a controlled derivative, never an upstream checkpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENIZER_MANIFEST = ROOT / "tests/fixtures/tokenizer/qwen3-embedding-0.6b-tokenizer.manifest.json"
RECEIPT = Path(__file__).with_name("u1-real-inputs.manifest.json")
MODEL_SHA = "e5212dd2d4772bb6939c3c75dae6f9bf933a0d48de57d1f26f929a1c1e506759"
MODEL_BYTES = 633588308
CAP = 32768
VOCAB = 151669
END = 151643
FOREIGN_SPECIAL = "<|im_end|>"
FILES = ("at-cap.utf8", "over-cap.utf8", "over-cap-invalid.utf8", "at-cap.ids", "over-cap.ids", "foreign-tokenizer.sslm")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError("REAL_INPUT_SETUP: " + message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return {"bytes": path.stat().st_size, "sha256": h.hexdigest()}


def check_sources(model: Path, tokenizer: Path) -> dict:
    manifest = json.loads(TOKENIZER_MANIFEST.read_text(encoding="utf-8"))
    require(identity(model) == {"bytes": MODEL_BYTES, "sha256": MODEL_SHA}, "real model identity differs")
    expected = {k: manifest["artifact"][k] for k in ("bytes", "sha256")}
    require(identity(tokenizer) == expected, "real tokenizer identity differs")
    return manifest


def foreign_artifact(original: bytes) -> bytes:
    """Rebuild only TOK1 and container placement/integrity; retain other sections.

    Format is pinned v2: 64-byte header, 40-byte descriptors. TOK1 has byte IDs,
    vocab offsets/blob, merge triples, then special IDs/offsets/blob. New unused
    rows have empty byte strings; the new final row decodes the changed special.
    """
    require(original[:4] == b"SSLM" and struct.unpack_from("<II", original, 4) == (2, 64), "expected v2 container")
    count = struct.unpack_from("<I", original, 12)[0]
    rows = []
    for i in range(count):
        kind, dtype, offset, size, elements, alignment, reserved = struct.unpack_from("<IIQQQII", original, 64 + 40 * i)
        data = original[offset:offset + size]
        if kind == 20:
            require(data[:4] == b"TOK1", "expected TOK1")
            version, vocab, merges, specials, zero = struct.unpack_from("<IIIII", data, 4)
            require(version == 1 and zero == 0 and vocab <= VOCAB, "TOK1 geometry differs")
            start = 24 + 256 * 4
            offsets = list(struct.unpack_from("<" + "I" * (vocab + 1), data, start))
            cursor = start + 4 * (vocab + 1)
            length = struct.unpack_from("<I", data, cursor)[0]
            blob = data[cursor + 4:cursor + 4 + length]
            tail = bytearray(data[cursor + 4 + length:])
            special_ids = merges * 12
            special_offsets = special_ids + specials * 4
            special_blob_start = special_offsets + (specials + 1) * 4 + 4
            changed = 0
            for j in range(specials):
                lo, hi = struct.unpack_from("<II", tail, special_offsets + j * 4)
                if tail[special_blob_start + lo:special_blob_start + hi] == FOREIGN_SPECIAL.encode():
                    require(struct.unpack_from("<I", tail, special_ids + j * 4)[0] == 151645, "foreign special source identity")
                    struct.pack_into("<I", tail, special_ids + j * 4, VOCAB)
                    changed += 1
            require(changed == 1, "foreign special not unique")
            offsets += [length] * (VOCAB - vocab)
            blob += FOREIGN_SPECIAL.encode()
            offsets.append(len(blob))
            header = bytearray(data[:start])
            struct.pack_into("<I", header, 8, VOCAB + 1)
            data = bytes(header) + struct.pack("<" + "I" * len(offsets), *offsets) + struct.pack("<I", len(blob)) + blob + tail
            elements = len(data)
        rows.append((kind, dtype, data, elements, alignment, reserved))
    result = bytearray(original[:64 + 40 * count])
    result[32:64] = bytes(32)
    for i, (kind, dtype, data, elements, alignment, reserved) in enumerate(rows):
        result.extend(bytes((-len(result)) % alignment))
        offset = len(result)
        result.extend(data)
        struct.pack_into("<IIQQQII", result, 64 + 40 * i, kind, dtype, offset, len(data), elements, alignment, reserved)
    struct.pack_into("<Q", result, 24, len(result))
    result[32:64] = hashlib.sha256(result).digest()
    return bytes(result)


def generate(out: Path, snapshot: Path, model: Path, tokenizer: Path, mint: bool = False) -> dict:
    manifest = check_sources(model, tokenizer)
    import tokenizers
    require(tokenizers.__version__ == "0.22.2", "reference requires tokenizers 0.22.2")
    require(snapshot.name == manifest["checkpoint"]["revision"], "reference revision differs")
    for name, field in (("tokenizer.json", "tokenizer_json_sha256"), ("tokenizer_config.json", "tokenizer_config_json_sha256")):
        require(identity(snapshot / name)["sha256"] == manifest["checkpoint"][field], "reference " + name + " identity differs")
    ref = tokenizers.Tokenizer.from_file(str(snapshot / "tokenizer.json"))
    require(ref.encode("<|endoftext|>", add_special_tokens=False).ids == [END], "reference terminator differs")
    require(ref.encode(FOREIGN_SPECIAL, add_special_tokens=False).ids == [151645], "reference special differs")
    out.mkdir(parents=True, exist_ok=True)
    for name, content in (("at-cap", CAP - 1), ("over-cap", CAP)):
        text = "a" + " a" * (content - 1)
        ids = ref.encode(text, add_special_tokens=False).ids
        require(ids == [64] + [264] * (content - 1), name + " reference IDs differ")
        (out / (name + ".utf8")).write_bytes(text.encode())
        (out / (name + ".ids")).write_bytes(struct.pack("<" + "i" * len(ids), *ids))
    (out / "over-cap-invalid.utf8").write_bytes((out / "over-cap.utf8").read_bytes() + b"\xff")
    (out / "foreign-tokenizer.sslm").write_bytes(foreign_artifact(tokenizer.read_bytes()))
    receipt = {"schema": "semb_real_input_prerequisites_v1", "reference": {"implementation": "Hugging Face tokenizers", "version": tokenizers.__version__, **manifest["checkpoint"]},
               "cap": CAP, "model_vocab": VOCAB, "terminator": END, "foreign_special": FOREIGN_SPECIAL,
               "foreign_special_id": VOCAB, "foreign_provenance": "controlled pinned real-tokenizer derivative; not an upstream checkpoint",
               "content_ids": {"at-cap": {"count": CAP - 1, "first": 64, "remaining": 264}, "over-cap": {"count": CAP, "first": 64, "remaining": 264}},
               "files": {name: identity(out / name) for name in FILES}}
    if mint:
        RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        require(receipt == json.loads(RECEIPT.read_text(encoding="utf-8")), "regenerated fixture receipt differs from committed pin")
    return receipt


def verify(out: Path, model: Path, tokenizer: Path) -> dict:
    check_sources(model, tokenizer)
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    require(set(receipt["files"]) == set(FILES), "receipt file membership differs")
    for name in FILES:
        require(identity(out / name) == receipt["files"][name], name + " identity/size differs")
    for name, count in (("at-cap", CAP - 1), ("over-cap", CAP)):
        require((out / (name + ".utf8")).read_bytes() == b"a" + b" a" * (count - 1), name + " bytes differ")
        ids = (out / (name + ".ids")).read_bytes()
        require(len(ids) == 4 * count and list(struct.unpack("<" + "i" * count, ids)) == [64] + [264] * (count - 1), name + " content positions differ")
    require((out / "over-cap-invalid.utf8").read_bytes() == (out / "over-cap.utf8").read_bytes() + b"\xff", "invalid UTF-8 crossing differs")
    require((out / "foreign-tokenizer.sslm").read_bytes() == foreign_artifact(tokenizer.read_bytes()), "foreign derivative differs")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, help="generate with independently pinned reference; absent means verify only")
    parser.add_argument("--mint", action="store_true", help="author-only initial receipt; ordinary generation never changes the pin")
    args = parser.parse_args()
    try:
        require(not args.mint or args.snapshot is not None, "mint requires reference generation")
        if args.snapshot:
            generate(args.out_dir, args.snapshot, args.model, args.tokenizer, args.mint)
        receipt = verify(args.out_dir, args.model, args.tokenizer)
        print("[PASS] REAL_INPUT_SETUP independent fixture identities: " + json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, ImportError) as exc:
        print("[FAIL] REAL_INPUT_SETUP: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
