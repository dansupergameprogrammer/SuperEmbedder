"""TE-93 driver: build and run batch contract cells on synthetic and real pairs."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import u1_raw_text_cells_check as raw

ROOT = Path(__file__).resolve().parent.parent


def run(exe: Path, arguments: list[str], label: str, table: raw.Table) -> None:
    proc = subprocess.run([str(exe), *arguments], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    print(proc.stdout)
    if proc.stderr.strip():
        print(proc.stderr)
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    table.add(label, "PASS" if proc.returncode == 0 and passed and not failed else "FAIL",
              f"exit {proc.returncode}; {passed} PASS, {failed} FAIL")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--cmake-executable", default="cmake")
    parser.add_argument("--model", default=os.environ.get("SEMB_C12B_MODEL", ""))
    parser.add_argument("--tokenizer", default=os.environ.get("SEMB_U1_TOKENIZER", ""))
    args = parser.parse_args(argv)
    build_dir = Path(args.build_dir)
    table = raw.Table()

    try:
        pair_dir = ROOT / "build" / "_scratch" / "u1_pair"
        pair = raw.ensure_pair(pair_dir)
    except Exception as exc:  # noqa: BLE001
        table.add("F0 synthetic pair", "FAIL", f"{type(exc).__name__}: {exc}")
        return 1
    table.add("F0 synthetic pair", "PASS", str(pair_dir))

    proc = subprocess.run([args.cmake_executable, "--build", str(build_dir),
                           "--target", "u1_batch_contract_test"], cwd=ROOT,
                          capture_output=True, text=True)
    if proc.returncode:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-30:])
        state = "RED-UNIMPLEMENTED" if "semb_encode_batch" in tail else "FAIL"
        table.add("B0 build batch contract", state, tail)
        return 1
    exe = raw.find_exe(build_dir, "u1_batch_contract_test")
    if not exe:
        table.add("B1 locate batch contract", "FAIL", str(build_dir))
        return 1
    table.add("B0 build batch contract", "PASS", str(exe))

    common = ["--model", str(pair_dir / "u1_pair_model.sslm"),
              "--tokenizer", str(pair_dir / "u1_pair_tokenizer.sslm"),
              "--append-id", str(pair["appended_token_id"]), "--dims", "32",
              "--context-cap", "64"]
    run(exe, common, "M1 batch contract on synthetic pair", table)

    if not args.model or not args.tokenizer:
        table.add("R1 batch contract on Qwen3-Embedding-0.6B", "MISSING PREREQUISITE",
                  "needs SEMB_C12B_MODEL and SEMB_U1_TOKENIZER")
    else:
        manifest = json.loads(raw.TOKENIZER_MANIFEST.read_text(encoding="utf-8"))["artifact"]
        tokenizer = Path(args.tokenizer)
        if (not Path(args.model).exists() or not tokenizer.exists() or
                raw.sha256_file(tokenizer) != manifest["sha256"] or
                tokenizer.stat().st_size != manifest["bytes"]):
            table.add("R1 batch contract on Qwen3-Embedding-0.6B", "FAIL",
                      "model/tokenizer absent or tokenizer differs from committed manifest")
        else:
            run(exe, ["--model", args.model, "--tokenizer", args.tokenizer,
                      "--append-id", str(raw.CANDIDATE_APPEND_ID), "--dims",
                      str(raw.CANDIDATE_DIMS)],
                "R1 batch contract on Qwen3-Embedding-0.6B", table)

    print("\nu1_batch_cells_check summary:")
    for label, state, _ in table.rows:
        print(f"  {state:22s} {label}")
    return 1 if table.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
