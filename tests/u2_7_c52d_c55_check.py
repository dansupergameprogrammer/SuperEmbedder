"""U2 cloud build: build and run U2-7's C52 (d) and C55's general oracle
(tests/u2_7_c52d_c55_test.cpp), on the synthetic pair here and on the real
artifact on the dev box.

C55's oracle is computed HERE, outside the library under test: the pinned
converter's `TokenizerTables.ref_encode` (cloned at the lock's tag, the same
clone the pair regenerator uses) tokenizes ComposeQuery(text) = kQueryPrefix +
text and kQueryPrefix, and the expected body count is the difference, over
C5's 239 texts (corpus-239), the prefix-merge construction (a text beginning
with a letter, which merges with the prefix's final ':' under the real
pre-tokenizer) and the empty text (0). The synthetic leg uses the synthetic
checkpoint's tables; the real leg needs --real-checkpoint (the real model's
tokenizer.json directory) with --model/--tokenizer, else MISSING PREREQUISITE.

RED TODAY: the executable fails to link; the unresolved names are reported.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = "u2_7_c52d_c55_test"
# The query instruction the product composes (te267 U2-7 item 6's kQueryPrefix),
# stated here independently of the library's source.
QUERY_PREFIX = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
PREFIX_MERGE_TEXT = "What is the capital of France?"
EXPECTED_SYMBOLS = ["semb_encoder_open_memory", "semb_encode_query", "semb_interim_query_token_count",
                    "semb_test_seam_memory_open_arm_park", "semb_test_seam_memory_open_wait_parked",
                    "semb_test_seam_memory_open_release"]


def oracle_tsv(checkpoint: Path, out: Path, workdir: Path) -> int:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))
    base = importlib.import_module("regenerate_tokenizer_pair_fixture")
    tag = base.read_lock_tag(REPO_ROOT / "superslm.lock")
    clone = base.clone_engine_tools(tag, base.DEFAULT_REMOTE, workdir)
    sys.path.insert(0, str(clone / "tools"))
    ct = importlib.import_module("convert_tokenizer")
    tables = ct.TokenizerTables(str(checkpoint))
    texts = [json.loads(ln)["text"] for ln in
             (REPO_ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl").read_text(encoding="utf-8").splitlines()]
    texts += [PREFIX_MERGE_TEXT, ""]
    prefix_len = len(tables.ref_encode(QUERY_PREFIX))
    lines = ["# hex(text)\tlen(ref_encode(prefix+text)) - len(ref_encode(prefix))"]
    for t in texts:
        lines.append(f"{t.encode('utf-8').hex()}\t{len(tables.ref_encode(QUERY_PREFIX + t)) - prefix_len}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    base.rmtree(workdir)
    return len(texts)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    ap.add_argument("--real-checkpoint", default="")
    args = ap.parse_args(argv)
    build = Path(args.build_dir)
    work = build / "_scratch" / "u2_7"
    work.mkdir(parents=True, exist_ok=True)
    b = subprocess.run([args.cmake_executable, "--build", str(build), "--target", TARGET], cwd=REPO_ROOT,
                       capture_output=True, text=True, errors="replace")
    out = b.stdout + b.stderr
    if b.returncode:
        unresolved = [s for s in EXPECTED_SYMBOLS
                      if re.search(r"(unresolved external symbol|undefined symbol:|undefined reference to [`'])\s*_?"
                                   + s + r"\b", out)]
        if unresolved:
            print(f"[RED-UNIMPLEMENTED] {TARGET} fails to link, naming: {unresolved}")
            print("[FAIL] C52 (d) and C55 (general oracle) cannot run until U2-7 items 1, 2, 6 and the C52 (d) "
                  "seam exist")
        else:
            print(f"[FAIL] {TARGET} build failed\n{out[-3000:]}")
        return 1
    exe = next((p for p in (build / TARGET, build / "tests" / TARGET) if p.exists()), None)
    if exe is None:
        print(f"[FAIL] {TARGET} absent after build")
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import u2_9_workspace_cells_check as u29  # noqa: E402
    pair = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    u29.ensure_pair(pair)
    fails = 0
    tsv = work / "c55_synthetic_expected.tsv"
    n = oracle_tsv(REPO_ROOT / "tests" / "fixtures" / "tokenizer" / "u1-synthetic-checkpoint", tsv,
                   REPO_ROOT / "build" / "_u2_7_oracle_workdir")
    print(f"C55 synthetic oracle: {n} texts from the pinned converter's ref_encode")
    r = subprocess.run([str(exe), "--model", str(pair / "u1_pair_model.sslm"), "--tokenizer",
                        str(pair / "u1_pair_tokenizer.sslm"), "--expected", str(tsv)],
                       cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", timeout=1800)
    print(r.stdout)
    fails += 1 if r.returncode or "[FAIL]" in r.stdout else 0
    if args.model and args.tokenizer and args.real_checkpoint:
        rtsv = work / "c55_real_expected.tsv"
        oracle_tsv(Path(args.real_checkpoint), rtsv, REPO_ROOT / "build" / "_u2_7_oracle_workdir")
        r = subprocess.run([str(exe), "--model", args.model, "--tokenizer", args.tokenizer, "--expected", str(rtsv)],
                           cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", timeout=3600)
        print(r.stdout)
        fails += 1 if r.returncode or "[FAIL]" in r.stdout else 0
    else:
        print("[MISSING PREREQUISITE] C52 (d) and C55 real legs: need --model, --tokenizer and --real-checkpoint "
              "(the real checkpoint's tokenizer.json directory); owed to the dev box")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
