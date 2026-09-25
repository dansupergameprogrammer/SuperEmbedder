"""U2 cloud build: build and run U2-9's seam-observable cells and C66 (a).

Mints the minimal-geometry cap-5,000 pair (tests/fixtures/
regenerate_u2_9_minimal_cap5000_pair_fixture.py) into build/_scratch/
u2_9_min_pair when absent, builds `u2_9_workspace_cells_test` (links
`superembedder_testseam`), and runs it. Red on today's pool: see the
executable's header for which cells are red and which are pins.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
TARGET = "u2_9_workspace_cells_test"


def ensure_pair(pair_dir: Path) -> None:
    if (pair_dir / "u1_pair_model.sslm").exists() and (pair_dir / "u1_pair_tokenizer.sslm").exists():
        return
    subprocess.run([sys.executable, str(FIXTURES / "regenerate_u2_9_minimal_cap5000_pair_fixture.py"),
                    "--lock", "superslm.lock", "--out-dir", str(pair_dir)],
                   cwd=REPO_ROOT, check=True, timeout=900)


def find_exe(build_dir: Path) -> Path | None:
    for name in (TARGET + ".exe", TARGET):
        cand = build_dir / "tests" / name
        if cand.exists():
            return cand
    hits = list(build_dir.rglob(TARGET + "*"))
    hits = [h for h in hits if h.is_file() and h.suffix in ("", ".exe")]
    return hits[0] if hits else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--real-model", default="")
    ap.add_argument("--cells", default="")
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    pair_dir = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    try:
        ensure_pair(pair_dir)
    except Exception as ex:  # noqa: BLE001
        print(f"[FAIL] U2-9 minimal cap-5,000 pair could not be minted: {type(ex).__name__}: {ex}")
        return 1
    build = subprocess.run([args.cmake_executable, "--build", str(build_dir), "--target", TARGET],
                           cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    if build.returncode:
        print(f"[FAIL] {TARGET} build failed")
        print((build.stdout + build.stderr)[-3000:])
        return 1
    exe = find_exe(build_dir)
    if exe is None:
        print(f"[FAIL] {TARGET} is absent after a successful build")
        return 1
    scratch = build_dir / "_scratch" / "u2_9_workspace_cells"
    scratch.mkdir(parents=True, exist_ok=True)
    cmd = [str(exe), "--model", str(pair_dir / "u1_pair_model.sslm"),
           "--tokenizer", str(pair_dir / "u1_pair_tokenizer.sslm"), "--scratch", str(scratch)]
    if args.real_model:
        cmd += ["--real-model", args.real_model]
    if args.cells:
        cmd += ["--cells", args.cells]
    run = subprocess.run(cmd, cwd=REPO_ROOT, text=True, errors="replace", capture_output=True, timeout=1800)
    print(run.stdout)
    if run.stderr.strip():
        print(run.stderr[-3000:])
    return 1 if run.returncode or "[FAIL]" in run.stdout else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
