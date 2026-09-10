"""Build and run TE-221 S-1's mechanism-pair ownership cells."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import u1_raw_text_cells_check as u1raw  # noqa: E402


def find_exe(build_dir: Path) -> Path | None:
    for candidate in (build_dir / "tests" / "te222_query_ownership_test.exe",
                      build_dir / "tests" / "te222_query_ownership_test"):
        if candidate.exists():
            return candidate
    hits = list(build_dir.rglob("te222_query_ownership_test.exe"))
    return hits[0] if hits else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--cmake-executable", required=True)
    args = parser.parse_args(argv)
    build_dir = Path(args.build_dir)
    pair_dir = REPO_ROOT / "build" / "_scratch" / "u1_pair"
    u1raw.ensure_pair(pair_dir)
    build = subprocess.run([args.cmake_executable, "--build", str(build_dir), "--target",
                            "te222_query_ownership_test"], cwd=REPO_ROOT, capture_output=True,
                           text=True, errors="replace")
    if build.returncode:
        print("[FAIL] TE-221 S-1 ownership target build failed")
        print((build.stdout + build.stderr)[-3000:])
        return 1
    exe = find_exe(build_dir)
    if exe is None:
        print("[FAIL] TE-221 S-1 ownership target is absent after a successful build")
        return 1
    scratch = build_dir / "_scratch" / "te222_query_ownership"
    scratch.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([str(exe), "--model", str(pair_dir / "u1_pair_model.sslm"),
                          "--tokenizer", str(pair_dir / "u1_pair_tokenizer.sslm"),
                          "--scratch", str(scratch)], cwd=REPO_ROOT, text=True,
                         errors="replace", capture_output=True, timeout=900)
    print(run.stdout)
    return 1 if run.returncode or "[FAIL]" in run.stdout else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
