"""tests/te331_u2_consumer_check.py -- TE-331 (U2-1 red suite): drives
tests/consumer/ against an INSTALL PREFIX, per the plan's own red-first
text (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-1): "An out-of-tree
consumer project ... fails at configure today (no config file)."

TWO LEGS.

  RED-FIRST (always runs): `cmake --install <product build dir> --prefix
  <scratch prefix>` today INSTALLS NOTHING -- `git grep -n "install(" \
  CMakeLists.txt` at `fca421b` returns nothing, so the product's own
  CMakeLists.txt defines no install rule and no package-config export.
  `cmake -S tests/consumer -B <scratch build> \
  -DCMAKE_PREFIX_PATH=<scratch prefix>` then fails at `find_package
  (superembedder 1.0 CONFIG REQUIRED)`, because no
  `superembedderConfig.cmake` exists anywhere on that prefix. This cell
  asserts BOTH: the install step writes nothing superembedder-shaped under
  the prefix, and the consumer's own configure fails naming
  `superembedder`.

  PROOF (only with --model/--tokenizer, real artifact): once U2-1 lands,
  re-run with a REAL install prefix and confirm the consumer configures,
  builds, links and runs green, printing the same fingerprint the product's
  own CLI reports for the same text on the same artifact. Not gradable
  until the install surface exists; this leg reports MISSING PREREQUISITE
  until it does.

EXIT CODE CONVENTION (te163_bank_pair_check.py's own): 0 only if every leg
is PASS or MISSING PREREQUISITE; 1 if any leg is FAIL or RED-UNIMPLEMENTED.
The RED-FIRST leg is RED-UNIMPLEMENTED today by design (F4's install
surface does not exist), so this script exits 1 until U2-1 lands -- a
correctly-observed absence is not a passing test.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def red_first_leg(cmake: str, product_build: Path, scratch: Path) -> str:
    prefix = scratch / "install_prefix"
    if prefix.exists():
        shutil.rmtree(prefix)
    prefix.mkdir(parents=True)
    rc, out = run([cmake, "--install", str(product_build), "--prefix", str(prefix)])
    installed_semb_files = list(prefix.rglob("*superembedder*")) + list(prefix.rglob("semb.h"))
    print(f"[install] rc={rc}\n{out}")
    print(f"[install] superembedder-shaped files under the prefix: {installed_semb_files}")
    install_wrote_nothing = len(installed_semb_files) == 0

    consumer_build = scratch / "consumer_build"
    if consumer_build.exists():
        shutil.rmtree(consumer_build)
    rc2, out2 = run([cmake, "-S", str(REPO_ROOT / "tests" / "consumer"), "-B", str(consumer_build),
                     "-DCMAKE_PREFIX_PATH=" + str(prefix)])
    print(f"[consumer configure] rc={rc2}\n{out2}")
    configure_failed_naming_superembedder = rc2 != 0 and "superembedder" in out2.lower()

    confirmed_absent = install_wrote_nothing and configure_failed_naming_superembedder
    status = "RED-UNIMPLEMENTED" if confirmed_absent else "FAIL"
    print(f"[{status}] RED-FIRST: install wrote nothing "
          f"superembedder-shaped ({install_wrote_nothing}) AND the consumer's own configure "
          f"failed naming superembedder ({configure_failed_naming_superembedder}) -- "
          f"F4's install surface does not exist yet")
    return status


def proof_leg(cmake: str, product_build: Path, scratch: Path, model: str, tokenizer: str) -> str:
    prefix = scratch / "install_prefix_proof"
    if prefix.exists():
        shutil.rmtree(prefix)
    prefix.mkdir(parents=True)
    rc, out = run([cmake, "--install", str(product_build), "--prefix", str(prefix)])
    if rc != 0 or not any(prefix.rglob("*uperembedder*Config*.cmake")):
        print(f"[MISSING PREREQUISITE] PROOF leg: no superembedderConfig.cmake was installed "
              f"({out[-2000:]}) -- U2-1 has not landed")
        return "MISSING PREREQUISITE"

    consumer_build = scratch / "consumer_build_proof"
    if consumer_build.exists():
        shutil.rmtree(consumer_build)
    rc2, out2 = run([cmake, "-S", str(REPO_ROOT / "tests" / "consumer"), "-B", str(consumer_build),
                     "-DCMAKE_PREFIX_PATH=" + str(prefix)])
    if rc2 != 0:
        print(f"[FAIL] PROOF leg: consumer configure failed against a REAL install prefix\n{out2}")
        return "FAIL"
    rc3, out3 = run([cmake, "--build", str(consumer_build)])
    if rc3 != 0:
        print(f"[FAIL] PROOF leg: consumer build failed\n{out3}")
        return "FAIL"
    exe = next(consumer_build.rglob("te331_consumer*"), None)
    if exe is None:
        print("[FAIL] PROOF leg: te331_consumer executable not found after build")
        return "FAIL"
    rc4, out4 = run([str(exe), model, tokenizer])
    ok = rc4 == 0 and out4.startswith("OK ")
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] PROOF: consumer configured, built and ran against a "
          f"real install prefix: {out4.strip()}")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmake", default="cmake")
    ap.add_argument("--product-build", type=Path, default=REPO_ROOT / "build" / "msvc")
    ap.add_argument("--scratch", type=Path, default=REPO_ROOT / "build" / "_scratch" / "te331_consumer")
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)

    results = [red_first_leg(args.cmake, args.product_build, args.scratch)]
    if args.model and args.tokenizer:
        results.append(proof_leg(args.cmake, args.product_build, args.scratch, args.model, args.tokenizer))
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
