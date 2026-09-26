"""U2 cloud build, U2-9's C62: drive the adversary's must-reject constructions (te267 U2-9, C62, P:2803-2805).

Builds `u2_9_c62_must_reject_test` (it links `superembedder_testseam`, which is EXCLUDE_FROM_ALL), then:

  --mode mechanism   mints the minimal cap-5,000 synthetic pair into the build's own scratch and runs the
                     forced construction's hooks around the public API (every platform; the GCC proof).
  --mode forced|held runs one C62 process with the construction's hooks on the real artifact (Windows;
                     77 = SKIPPED (platform) or MISSING PREREQUISITE elsewhere). See the executable's header.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = "u2_9_c62_must_reject_test"


def find_exe(build_dir: Path) -> Path | None:
    for base in (build_dir, build_dir / "tests"):
        for name in (TARGET + ".exe", TARGET):
            if (base / name).is_file():
                return base / name
    hits = [h for h in build_dir.rglob(TARGET + "*") if h.is_file() and h.suffix in ("", ".exe")]
    return hits[0] if hits else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--config", default="")
    ap.add_argument("--mode", required=True, choices=("mechanism", "forced", "held"))
    ap.add_argument("--mc", default="1")
    ap.add_argument("--leg", default="long")
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    ap.add_argument("--short", default="")
    ap.add_argument("--long", default="")
    a = ap.parse_args(argv)
    build_dir = Path(a.build_dir)
    cmd = [a.cmake_executable, "--build", str(build_dir), "--target", TARGET]
    if a.config:
        cmd += ["--config", a.config]
    b = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    if b.returncode:
        print(f"[FAIL] {TARGET} build failed")
        print((b.stdout + b.stderr)[-3000:])
        return 1
    exe = find_exe(build_dir)
    if exe is None:
        print(f"[FAIL] {TARGET} is absent after a successful build")
        return 1
    if a.mode == "mechanism":
        pair = build_dir / "_scratch" / "u2_9_c62_min_pair"
        model, tok = pair / "u1_pair_model.sslm", pair / "u1_pair_tokenizer.sslm"
        if not (model.exists() and tok.exists()):
            m = subprocess.run([sys.executable, str(REPO_ROOT / "tests" / "fixtures" /
                                                    "regenerate_u2_9_minimal_cap5000_pair_fixture.py"),
                                "--lock", "superslm.lock", "--out-dir", str(pair)],
                               cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", timeout=900)
            if m.returncode:
                print("[FAIL] the minimal cap-5,000 pair could not be minted")
                print((m.stdout + m.stderr)[-3000:])
                return 1
        run = [str(exe), "--mechanism", "1", "--model", str(model), "--tokenizer", str(tok)]
    else:
        scratch = build_dir / "_scratch" / "u2_9_c62_must_reject"
        scratch.mkdir(parents=True, exist_ok=True)
        log = scratch / f"{a.mode}-mc{a.mc}-{a.leg}.log"
        run = [str(exe), "--construction", a.mode, "--mc", a.mc, "--leg", a.leg, "--long", a.long,
               "--log", str(log)]
        if a.short:
            run += ["--short", a.short]
        if a.model and a.tokenizer:
            run += ["--model", a.model, "--tokenizer", a.tokenizer]
    r = subprocess.run(run, cwd=REPO_ROOT, capture_output=True, text=True, errors="replace", timeout=3600)
    print(r.stdout)
    if r.stderr.strip():
        print(r.stderr[-3000:])
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
