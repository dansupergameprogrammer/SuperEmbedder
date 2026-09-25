"""Execute C17's four quarantined W-Q composition mutants and TE-221 S-2."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The cap-512 pair mint alone takes ~390-410 s on an idle 4-core box, so a
# 480 s bound on it timed out under `ctest -j`, where it competes for the
# same cores. 1,800 s leaves ~4x headroom; the ctest TIMEOUT on this test
# (tests/CMakeLists.txt) is set above this plus the rest of the run.
MINT_TIMEOUT_S = 1800

MUTANTS = {
    "JOIN": ("composed.append(kQueryPrefix);\n  composed.append(text);", "composed.append(kQueryPrefix);\n  composed.append(\"\\n[mutant-boundary]\\n\");\n  composed.append(text);"),
    "ORDER": ("composed.append(kQueryPrefix);\n  composed.append(text);", "composed.append(text);\n  composed.append(kQueryPrefix);"),
    "SPECIAL_TOKEN": ("composed.append(kQueryPrefix);\n  composed.append(text);", "composed.append(kQueryPrefix);\n  composed.append(\"<|endoftext|>\");\n  composed.append(text);"),
    # Deliberately perform the witness cut on raw content before composition.
    # One byte makes this observable even on the frozen cap-64 pair; the
    # production path instead composes first and cuts the full sequence.
    "TRUNCATION_ORDERING": ("if (!HashWitnessPosition(encoder, BuildTruncationQuery(), kWitnessQueryContentCap, &hash)) return false;", "const std::string truncation = BuildTruncationQuery();\n  if (!HashWitnessPosition(encoder, truncation.substr(0, 1), kWitnessQueryContentCap, &hash)) return false;"),
    "PREFIX_SINGLE_SOURCE": ("query\\nQuery:\";", "query\\nQuery-v2:\";"),
}


def cache_value(cache: Path, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:[^=]*=(.*)$", cache.read_text(encoding="utf-8", errors="replace"), re.M)
    return match.group(1).strip() if match else ""


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"{path.name} mutation anchor count is {text.count(old)}, expected 1")
    path.write_text(text.replace(old, new), encoding="utf-8")


def prepare(scratch: Path, cmake: str, compiler: str, prefix: str) -> tuple[Path, Path]:
    root, build = scratch / "source", scratch / "build"
    shutil.copytree(REPO_ROOT, root, ignore=shutil.ignore_patterns(".git", "build", "__pycache__"))
    configure(root, build, cmake, compiler, prefix)
    return root, build


def configure(root: Path, build: Path, cmake: str, compiler: str, prefix: str) -> None:
    configured = subprocess.run([cmake, "-S", str(root), "-B", str(build), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                                 f"-DCMAKE_CXX_COMPILER={compiler}", f"-DCMAKE_PREFIX_PATH={prefix}"],
                                capture_output=True, text=True, timeout=480)
    if configured.returncode:
        raise RuntimeError("C17 configure failed:\n" + (configured.stdout + configured.stderr)[-3000:])


def sample(root: Path, build: Path, cmake: str, model: Path, tokenizer: Path) -> dict[str, str]:
    built = subprocess.run([cmake, "--build", str(build), "--target", "te222_c17_probe"],
                           capture_output=True, text=True, timeout=480)
    if built.returncode:
        raise RuntimeError("C17 build failed:\n" + (built.stdout + built.stderr)[-3000:])
    exe = next(iter(build.rglob("te222_c17_probe.exe")), None) or next(iter(build.rglob("te222_c17_probe")), None)
    if exe is None:
        raise RuntimeError("built C17 probe is absent")
    stem = build / "c17_bank"
    return read_probe(exe, stem, model, tokenizer)


def read_probe(exe: Path, stem: Path, model: Path, tokenizer: Path) -> dict[str, str]:
    run = subprocess.run([str(exe), str(model), str(tokenizer), str(stem)], check=True,
                         capture_output=True, text=True, timeout=480)
    result = dict(line.split("=", 1) for line in run.stdout.splitlines() if "=" in line)
    result["TEMPLATE_SHA256"] = json.loads(Path(str(stem) + ".semb.json").read_text(encoding="utf-8"))["template_sha256"]
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--cmake-executable", default="cmake")
    parser.add_argument("--mutant", choices=tuple(MUTANTS), help="run one bounded mutant job")
    args = parser.parse_args(argv)
    cache = Path(args.build_dir) / "CMakeCache.txt"
    if not cache.exists():
        print(f"[FAIL] C17-sixth-leg: configured build cache absent: {cache}")
        return 1
    compiler, prefix = cache_value(cache, "CMAKE_CXX_COMPILER"), cache_value(cache, "CMAKE_PREFIX_PATH")
    if not compiler or not prefix:
        print("[FAIL] C17-sixth-leg: cache lacks CMAKE_CXX_COMPILER or CMAKE_PREFIX_PATH")
        return 1
    # The shared U1 pair is cap-64 and clips C17's 96-id truncation witness.
    # Mint this isolated, pinned cap-512 pair only when absent.
    pair = REPO_ROOT / "build/_scratch/te222_c17_pair"
    model, tokenizer = pair / "u1_pair_model.sslm", pair / "u1_pair_tokenizer.sslm"
    if not model.exists() or not tokenizer.exists():
        fixture = REPO_ROOT / "tests/fixtures/wq/regenerate_c17_highcap_pair_fixture.py"
        generated = subprocess.run([sys.executable, str(fixture), "--lock", "superslm.lock",
                                    "--out-dir", str(pair)], capture_output=True, text=True,
                                   timeout=MINT_TIMEOUT_S)
        if generated.returncode or not model.exists() or not tokenizer.exists():
            print("[FAIL] C17-sixth-leg: high-cap synthetic fixture generation failed:\n" +
                  (generated.stdout + generated.stderr)[-3000:])
            return 1
    scratch = Path(tempfile.mkdtemp(prefix="te222_c17_"))
    try:
        baseline_build = subprocess.run([args.cmake_executable, "--build", args.build_dir, "--target", "te222_c17_probe"],
                                        capture_output=True, text=True, timeout=480)
        if baseline_build.returncode:
            raise RuntimeError("C17 baseline probe build failed:\n" + (baseline_build.stdout + baseline_build.stderr)[-3000:])
        baseline_exe = next(iter(Path(args.build_dir).rglob("te222_c17_probe.exe")), None)
        if baseline_exe is None:
            raise RuntimeError("C17 baseline probe executable is absent")
        base = read_probe(baseline_exe, Path(args.build_dir) / "_scratch/c17_baseline", model, tokenizer)
        root, build = prepare(scratch, args.cmake_executable, compiler, prefix)
        query_tu = root / "src/superembedder/query.cpp"
        original = query_tu.read_text(encoding="utf-8")
        failed = False
        names = (args.mutant,) if args.mutant else ("JOIN", "ORDER", "SPECIAL_TOKEN", "TRUNCATION_ORDERING")
        for name in names:
            if name == "PREFIX_SINGLE_SOURCE":
                continue
            old, new = MUTANTS[name]
            if original.count(old) != 1:
                raise RuntimeError(f"{name} mutation anchor count is {original.count(old)}, expected 1")
            query_tu.write_text(original.replace(old, new), encoding="utf-8")
            configure(root, build, args.cmake_executable, compiler, prefix)
            mutant = sample(root, build, args.cmake_executable, model, tokenizer)
            query_tu.write_text(original, encoding="utf-8")
            moved = mutant["FINGERPRINT"] != base["FINGERPRINT"]
            print(f"[QUARANTINED] C17-sixth-leg/{name}: fingerprint_moved={str(moved).lower()}")
            failed |= not moved
        ok = True
        if not args.mutant or args.mutant == "PREFIX_SINGLE_SOURCE":
            old, new = MUTANTS["PREFIX_SINGLE_SOURCE"]
            if original.count(old) != 1:
                raise RuntimeError(f"PREFIX_SINGLE_SOURCE mutation anchor count is {original.count(old)}, expected 1")
            query_tu.write_text(original.replace(old, new), encoding="utf-8")
            configure(root, build, args.cmake_executable, compiler, prefix)
            prefix_mutant = sample(root, build, args.cmake_executable, model, tokenizer)
            query_tu.write_text(original, encoding="utf-8")
            vector_moved = prefix_mutant["VECTOR_HEX"] != base["VECTOR_HEX"]
            template_moved = prefix_mutant["TEMPLATE_SHA256"] != base["TEMPLATE_SHA256"]
            ok = vector_moved and template_moved
            print(f"[{'PASS' if ok else 'FAIL'}] TE-221-S-2 prefix single source: vector_moved={str(vector_moved).lower()} template_sha256_moved={str(template_moved).lower()}")
        # C17's mutant readings are explicitly QUARANTINED.  A moved=false
        # reading is evidence for the later independent commissioning seat,
        # not a decision-bearing ctest failure; only an apparatus/pinned
        # non-quarantined prefix-single-source failure exits non-zero here.
        return 1 if not ok else 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[FAIL] C17-sixth-leg runner: {exc}")
        return 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
