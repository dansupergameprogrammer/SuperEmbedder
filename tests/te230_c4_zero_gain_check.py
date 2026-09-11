"""C4 bake-side construction: an all-zero final norm must not write a bank."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIPLE = (".wvbank.json", ".wvbank.bin", ".semb.json")


def call(args: list[str], timeout: int = 480) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def find(build: Path, name: str) -> Path | None:
    choices = [build / "tests" / f"{name}.exe", build / "tests" / name, build / f"{name}.exe", build / name]
    return next((p for p in choices if p.exists()), None)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True, type=Path)
    ap.add_argument("--cmake-executable", required=True)
    args = ap.parse_args(argv)
    pair = ROOT / "build" / "_scratch" / "te230_c4_pair"
    model, tokenizer = pair / "u1_pair_model.sslm", pair / "u1_pair_tokenizer.sslm"
    if not model.exists() or not tokenizer.exists():
        fixture = ROOT / "tests" / "fixtures" / "wq" / "regenerate_c4_zero_final_norm_fixture.py"
        minted = call([sys.executable, str(fixture), "--lock", "superslm.lock", "--out-dir", str(pair)])
        if minted.returncode:
            print(f"[FAIL] C4 fixture: {(minted.stdout + minted.stderr)[-3000:]}")
            return 1
    built = call([args.cmake_executable, "--build", str(args.build_dir), "--target", "semb", "te230_semb_cli_probe"])
    probe, semb = find(args.build_dir, "te230_semb_cli_probe"), find(args.build_dir, "semb")
    if built.returncode or not probe or not semb:
        print(f"[FAIL] C4 apparatus: {(built.stdout + built.stderr)[-1000:]}")
        return 1
    text = "C4's all-zero final norm gain must reach the bake boundary."
    encoded = call([str(probe), "--model", str(model), "--tokenizer", str(tokenizer),
                    "--encode-only", "--text", text])
    zero = encoded.returncode == 0 and "VECTOR_ZERO=true" in encoded.stdout
    print(f"[{'PASS' if zero else 'FAIL'}] C4 zero post-final-norm vector: "
          f"{(encoded.stdout + encoded.stderr)[-500:]!r}")
    scratch = args.build_dir / "_scratch" / "te230_c4"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    corpus = scratch / "zero.jsonl"
    corpus.write_text('{"id":"c4-zero","text":"C4 all-zero pooled vector."}\n', encoding="utf-8")
    stem = scratch / "zero"
    library = call([str(probe), "--model", str(model), "--tokenizer", str(tokenizer),
                    "--stem", str(stem), "--bake-corpus", str(corpus)])
    absent = not any(Path(str(stem) + suffix).exists() for suffix in TRIPLE)
    library_ok = library.returncode != 0 and "SEMB_BANK_ZERO_NORM_ROW" in (library.stdout + library.stderr) and absent
    print(f"[{'PASS' if library_ok else 'FAIL'}] C4 library bake zero row: "
          f"exit={library.returncode}; triple_absent={absent}; output={(library.stdout + library.stderr)[-500:]!r}")
    cli_stem = scratch / "cli-zero"
    cli = call([str(semb), "bake", str(corpus), "--out", str(cli_stem),
                "--model", str(model), "--tokenizer", str(tokenizer)])
    cli_absent = not any(Path(str(cli_stem) + suffix).exists() for suffix in TRIPLE)
    cli_ok = cli.returncode != 0 and "SEMB_BANK_ZERO_NORM_ROW" in (cli.stdout + cli.stderr) and cli_absent
    stub = cli.returncode == 0 and "semb " in cli.stdout
    state = "PASS" if cli_ok else ("RED-UNIMPLEMENTED" if stub else "FAIL")
    print(f"[{state}] C4 CLI bake zero row: exit={cli.returncode}; triple_absent={cli_absent}; "
          f"required=SEMB_BANK_ZERO_NORM_ROW with no file; output={(cli.stdout + cli.stderr)[-300:]!r}")
    return 0 if zero and library_ok and cli_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
