#!/usr/bin/env python3
"""tests/c23_token_id_determinism_check.py -- TE-144 (U1 slice 1): the ctest
driver for C23 (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C23:
"SHA-256 over count-prefixed token-id sequences for the 239 documents ...
asserted equal across every {machine, tier, toolchain} cell, compared before
the row digest").

WHAT THIS DRIVES. tests/c23_token_id_determinism_test.cpp is one standalone
instrument (independent of the `superembedder` library -- it links the
engine's own tokenizer surface directly, the same call
`src/superembedder/encoder.cpp` makes internally). This driver compiles that
SAME source file under every toolchain this host can reach, runs each
resulting binary against the fixed mechanism corpus (24 documents,
tests/fixtures/tokenizer/u1-mechanism-corpus.jsonl, its own golden ids at
build/_scratch/u1_pair/u1_mechanism_expected_ids.tsv -- an independent
Python HF-side reference, `convert_tokenizer.TokenizerTables.ref_encode`,
never this project's own C++ code) and asserts every reachable toolchain's
printed TOKEN_DIGEST is byte-identical AND that every document's own ids
match the golden reference (the achievement half; cross-toolchain equality
is the determinism half).

THE {machine, tier, toolchain} CROSSING, enumerated rather than silently
narrowed to what happens to be configured:

  machine  -- 1 reachable (this host). A second machine is not available to
              this session; UNREACHABLE, filed, not exercised.
  tier     -- 1 reachable: whichever SIMD dispatch tier this host's own
              CPUID+XGETBV probe selects at runtime (`Claude/Plans/
              SuperEmbedder_Plan.md` sec 2.2 row 5: "the tier is selected by
              a cached CPUID+XGETBV probe at run time"). SuperSLM does not
              expose a forced-tier consumer build option this project's own
              CMake surface can select without a from-scratch engine
              rebuild per tier -- OUT OF SCOPE for this slice's test-design
              pass (this slice adds no new library surface, and forcing an
              engine SIMD tier is engine-side scope, not a test-authoring
              task). UNREACHABLE for every tier but the host's own; filed,
              not silently dropped.
  toolchain -- up to 3 this project certifies (MSVC, clang-cl, WSL GCC).
              MSVC and clang-cl are REACHABLE and BOTH EXERCISED by this
              driver whenever their compiler paths are configured (always
              true for MSVC's own `${CMAKE_CXX_COMPILER}`; clang-cl via
              --secondary-cxx-compiler, wired from SEMB_TEST_SECOND_TOOLCHAIN_CXX).
              WSL GCC: WSL is present on this host (confirmed:
              `wsl -l -v` lists an installed distribution) but building the
              engine and this project's own sources for a Linux/GCC target
              from inside this test-authoring pass is out of scope --
              UNREACHABLE IN THIS SESSION, filed as reachable-in-principle
              but not exercised, never silently dropped.

PRODUCT LEG. The real 239-document corpus (tests/fixtures/c12b/corpus-239.jsonl)
against the real, converter-emitted Qwen3-Embedding-0.6B tokenizer artifact,
gated on the SAME --tokenizer flag (wired from the existing SEMB_U1_TOKENIZER
cache variable tests/CMakeLists.txt already defines for this reason) every
other real-artifact leg in this suite uses. Reports MISSING PREREQUISITE
(non-failing) when absent, exactly like every sibling real-artifact cell.

RED-FIRST: before this file and c23_token_id_determinism_test.cpp existed,
`grep -rln "TokenizerView" tests/` and `grep -rn "count-prefixed" tests/`
both returned nothing in this suite -- no prior test computed a token-id
digest, over any corpus, in any shape, on any toolchain. Confirmed at
authoring time and re-stated in the filed casebook
(`Claude/Curie/te144-slice1-red-test-design.md`).

Exit codes: 0 every reachable leg PASS (mechanism digest equality across
every reachable toolchain, golden-reference agreement on every document);
1 any FAIL or a mismatch.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))
from u1_raw_text_cells_check import ensure_pair  # noqa: E402 -- reuse the one fixture-freshness check

MECHANISM_CORPUS = REPO_ROOT / "tests" / "fixtures" / "tokenizer" / "u1-mechanism-corpus.jsonl"
REAL_CORPUS = REPO_ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"
INSTRUMENT_SRC = REPO_ROOT / "tests" / "c23_token_id_determinism_test.cpp"


def compiler_version_line(compiler: str) -> str:
    is_clang = "clang" in Path(compiler).name.lower()
    argv = [compiler, "--version"] if is_clang else [compiler]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        text = (proc.stdout or "") + (proc.stderr or "")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if is_clang or "Compiler Version" in line:
                return line
    except Exception as exc:  # noqa: BLE001 -- diagnostic only, never fatal to the leg
        return f"<version probe failed: {exc}>"
    return "<no version output>"


def compile_instrument(compiler: str, engine_prefix: Path, out_dir: Path, tag: str) -> "tuple[bool, Path, str]":
    out_dir.mkdir(parents=True, exist_ok=True)
    obj = out_dir / f"c23_{tag}.obj"
    exe = out_dir / f"c23_{tag}.exe"
    cmd = [
        compiler, "/nologo", "/std:c++20", "/EHsc", "/fp:precise", "/W4", "/MD",
        f"/I{engine_prefix / 'include'}",
        str(INSTRUMENT_SRC),
        f"/Fo{obj}",
        f"/Fe{exe}",
        "/link", str(engine_prefix / "lib" / "superslm.lib"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    ok = proc.returncode == 0 and exe.exists()
    log = (proc.stdout or "") + (proc.stderr or "")
    return ok, exe, log


def run_instrument(exe: Path, tokenizer: Path, corpus: Path, golden: "Path | None") -> "tuple[bool, str, str]":
    cmd = [str(exe), "--tokenizer", str(tokenizer), "--corpus", str(corpus)]
    if golden is not None:
        cmd += ["--golden", str(golden)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    digest = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("TOKEN_DIGEST="):
            digest = line.split("=", 1)[1].strip()
    ok = proc.returncode == 0 and digest != ""
    log = (proc.stdout or "") + (proc.stderr or "")
    return ok, digest, log


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--engine-prefix", required=True)
    ap.add_argument("--primary-cxx-compiler", required=True)
    ap.add_argument("--secondary-cxx-compiler", default="")
    ap.add_argument("--tokenizer", default="", help="the real, converter-emitted tokenizer .sslm (SEMB_U1_TOKENIZER)")
    args = ap.parse_args(argv)

    build_dir = Path(args.build_dir)
    engine_prefix = Path(args.engine_prefix)
    scratch = build_dir / "_c23_scratch"
    pair_dir = REPO_ROOT / "build" / "_scratch" / "u1_pair"

    failures = 0
    rows = []  # (leg-name, status, detail)

    def verdict(name: str, status: str, detail: str = "") -> None:
        nonlocal failures
        rows.append((name, status, detail))
        if status == "FAIL":
            failures += 1

    # --- MECHANISM: ensure the synthetic pair + its golden ids exist ---
    try:
        ensure_pair(pair_dir)
    except Exception as exc:  # noqa: BLE001
        verdict("mechanism fixture", "FAIL", f"could not regenerate the u1_pair fixture: {exc}")
        print_report(rows)
        return 1
    mech_tokenizer = pair_dir / "u1_pair_tokenizer.sslm"
    mech_golden = pair_dir / "u1_mechanism_expected_ids.tsv"

    toolchains = [("primary", args.primary_cxx_compiler)]
    if args.secondary_cxx_compiler:
        toolchains.append(("secondary", args.secondary_cxx_compiler))
    else:
        verdict("toolchain: clang-cl", "UNREACHABLE",
                "SEMB_TEST_SECOND_TOOLCHAIN_CXX not configured on this build -- filed, not exercised")
    verdict("toolchain: WSL GCC", "UNREACHABLE",
            "WSL present on this host but a from-scratch Linux engine+product build is out of this "
            "slice's test-authoring scope -- filed, not exercised")
    verdict("machine", "UNREACHABLE (1 of N)", "only this host is available to this session")
    verdict("tier", "UNREACHABLE (1 of N)",
            "SuperSLM selects its SIMD tier via a runtime CPUID+XGETBV probe with no consumer-side "
            "forced-tier build option; forcing a second tier needs an engine-side rebuild, out of this "
            "slice's scope")

    digests = {}
    for tag, compiler in toolchains:
        version = compiler_version_line(compiler)
        ok, exe, log = compile_instrument(compiler, engine_prefix, scratch, tag)
        if not ok:
            verdict(f"toolchain {tag} ({version}): compile", "FAIL", log[-2000:])
            continue
        ok, digest, log = run_instrument(exe, mech_tokenizer, MECHANISM_CORPUS, mech_golden)
        if not ok:
            verdict(f"toolchain {tag} ({version}): mechanism run + golden agreement", "FAIL", log[-2000:])
            continue
        digests[tag] = (version, digest)
        verdict(f"toolchain {tag} ({version}): mechanism run + golden agreement", "PASS", f"digest={digest}")

    if len(digests) >= 2:
        vals = list(digests.values())
        all_equal = all(v[1] == vals[0][1] for v in vals)
        detail = "; ".join(f"{tag}={info[0]} -> {info[1]}" for tag, info in digests.items())
        verdict("cross-toolchain digest equality", "PASS" if all_equal else "FAIL", detail)
    else:
        verdict("cross-toolchain digest equality", "SKIPPED (fewer than 2 toolchains ran)", "")

    # --- PRODUCT: the real 239-document corpus against the real tokenizer ---
    if args.tokenizer and Path(args.tokenizer).exists() and REAL_CORPUS.exists():
        primary_compiler = args.primary_cxx_compiler
        ok, exe, log = compile_instrument(primary_compiler, engine_prefix, scratch, "product")
        if not ok:
            verdict("product: real 239-doc corpus", "FAIL", log[-2000:])
        else:
            ok, digest, log = run_instrument(exe, Path(args.tokenizer), REAL_CORPUS, None)
            verdict("product: real 239-doc corpus", "PASS" if ok else "FAIL", f"digest={digest}\n{log[-1000:]}")
    else:
        verdict("product: real 239-doc corpus", "MISSING PREREQUISITE",
                "SEMB_U1_TOKENIZER not configured or tests/fixtures/c12b/corpus-239.jsonl absent")

    print_report(rows)
    return 1 if failures else 0


def print_report(rows) -> None:
    print("C23 token-id determinism -- {machine, tier, toolchain} crossing report:")
    for name, status, detail in rows:
        print(f"  {status:28s} {name}")
        if detail:
            for line in str(detail).splitlines()[:20]:
                print(f"      {line}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
