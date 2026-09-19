"""tests/te163_c34_manifest_honesty_check.py -- TE-163 (U1 slice 4), cell 4:
C34 legs (e) and (h) (Claude/Plans/SuperEmbedder_Plan.md sec 3.4's label
table, sec 8 C34; Claude/Bach/briefs/te163-slice4-red.md's own fixed point).

THE CLAIM: at bake, `semb_bake_to_path` compares the `label:engine_path_id`
value it is about to write against the linked adapter TU's own compiled-in
`SEMB_ADAPTER_SELF_ID` constant (leg e) and `label:ps_version` against the
pooling epilogue's own compiled-in `SEMB_PS_VERSION_LABEL` constant (leg h),
refusing SEMB_ADAPTER_ID_MISMATCH / SEMB_PS_VERSION_LABEL_MISMATCH and
writing nothing on disagreement. In ordinary operation the label written and
the constant it is checked against are the SAME source of truth, so this
guard cannot fire on any build this suite configures by itself -- exactly
C17's own shape at smaller scale (sec 8 C34, dim 11: "these are
guard-vitality constructions in C17's shape at smaller scale"). The ONLY way
to prove the guard is alive rather than a comparison that always agrees with
itself is to edit ONE of the two constants in a scratch clone's own source
and rebuild -- this driver does exactly that, per leg, then restores and
rebuilds to confirm the healthy build still writes.

RED AT 7af22da, BY CONSTRUCTION: neither `semb_bake_to_path` nor either
compiled-in constant exists yet (confirmed: `git grep -n
"SEMB_ADAPTER_SELF_ID\\|SEMB_PS_VERSION_LABEL\\|semb_bake_to_path" src/
include/` returns nothing at this branch's own base). This driver's OWN
first step is locating each constant's own compiled-in declaration site by
NAME, in the TU this round's own contract header names for it
(tests/semb_bake_abi_contract.h: "the linked adapter TU's own... the pooling
epilogue's own TU"); when a constant is absent, the leg reports
RED-UNIMPLEMENTED by name and the (expensive) scratch-clone-and-rebuild
machinery below is never reached for that leg -- this is the CORRECT
red-first behaviour, not a shortcut: a mutation proof against a mechanism
that does not exist would prove nothing.

WHEN BOTH LEGS ARE BUILDABLE (a future run, unmodified from this file):
each leg clones the repository's tracked source tree to a scratch directory
(a plain recursive copy, excluding .git and any build/ directory -- the
same "clone into a throwaway tree" shape tools/engine_side_wa_perturbation.py
already uses for C38, at the file-copy grain rather than git-clone, since
this project has no dedicated scratch-clone helper for this repository
itself), edits the named constant's own literal in the copy, reconfigures
and builds ONLY the `superembedder` static library plus
`te163_bank_pair_test` in that scratch tree against the SAME engine prefix,
runs the built test binary's own good-triple bake (a smaller, targeted
invocation -- see run_bake_probe() below, not the full suite), and asserts
the named refusal fires and nothing is written; then restores the original
constant, rebuilds, and asserts the SAME bake now succeeds and writes.

THE PAIR IT BAKES WITH is the real candidate artifact and its converter-
emitted tokenizer (--model, --tokenizer; SEMB_C12B_MODEL and
SEMB_U1_TOKENIZER at configure). ctest registers this cell only when both
are configured. Invoked directly with either empty, both legs report
MISSING PREREQUISITE and nothing is cloned or built.

Exit codes: 0 every evaluated leg PASS, MISSING PREREQUISITE, or
RED-UNIMPLEMENTED (a red-first result is not a driver failure -- see
u1_batch_contract_check.py's own convention); 1 any FAIL.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


class Table:
    def __init__(self) -> None:
        self.hard_failed = False

    def add(self, leg: str, state: str, observed: str) -> None:
        if state == "FAIL":
            self.hard_failed = True
        print(f"[{state}] {leg}: {observed}")
        sys.stdout.flush()


# The two legs this cell proves, and where their own compiled-in constant is
# specified to live (this round's own tests/semb_bake_abi_contract.h: "the
# linked adapter TU's own SEMB_ADAPTER_SELF_ID"; "the pooling epilogue's own
# TU" -- PS-N is the ratified scheme, D-SLM4726, so ps_n_pool.cpp is tried
# first; ps1_pool.cpp (PS-1's own epilogue, D-SLM4727's named fallback) is
# the fallback search location, named explicitly rather than guessed).
LEGS = [
    {
        "name": "leg (e): engine_path_id vs SEMB_ADAPTER_SELF_ID",
        "constant": "SEMB_ADAPTER_SELF_ID",
        "candidate_files": ["src/superembedder/engine_adapter_interim.cpp"],
        "expected_status": "SEMB_ADAPTER_ID_MISMATCH",
    },
    {
        "name": "leg (h): ps_version vs SEMB_PS_VERSION_LABEL",
        "constant": "SEMB_PS_VERSION_LABEL",
        "candidate_files": ["src/superembedder/ps_n_pool.cpp", "src/superembedder/ps1_pool.cpp"],
        "expected_status": "SEMB_PS_VERSION_LABEL_MISMATCH",
    },
]


def find_constant(repo_root: Path, leg: dict) -> Tuple[Optional[Path], Optional[re.Match]]:
    pattern = re.compile(r'\b' + re.escape(leg["constant"]) + r'\s*(?:\[\s*\]|\[\s*\d*\s*\])?\s*=\s*"([^"]*)"')
    for rel in leg["candidate_files"]:
        p = repo_root / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        m = pattern.search(text)
        if m:
            return p, m
    return None, None


def bake_symbol_present(repo_root: Path) -> bool:
    proc = subprocess.run(["git", "grep", "-n", "semb_bake_to_path", "src", "include"],
                          cwd=repo_root, capture_output=True, text=True)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def run_mutation_leg(table: Table, repo_root: Path, engine_prefix: str, cmake: str, cxx: str,
                      python_exe: str, model: str, tokenizer: str, leg: dict) -> None:
    src_path, match = find_constant(repo_root, leg)
    if src_path is None:
        table.add(leg["name"], "RED-UNIMPLEMENTED",
                   f"{leg['constant']} is not compiled in anywhere under "
                   f"{'/'.join(leg['candidate_files'])} -- the builder has not landed this constant yet")
        return
    if not bake_symbol_present(repo_root):
        table.add(leg["name"], "RED-UNIMPLEMENTED",
                   f"{leg['constant']} is defined ({src_path}), but semb_bake_to_path does not exist yet -- "
                   f"there is no bake to mutate-test against")
        return

    original_value = match.group(1)
    tampered_value = original_value + "-TAMPERED-TE163"

    with tempfile.TemporaryDirectory(prefix="te163_c34_") as tmp:
        clone_dir = Path(tmp) / "clone"
        # A plain recursive copy of the tracked source tree, excluding .git
        # and any build output -- this repository carries no dedicated
        # scratch-clone helper of its own (unlike SuperSLM's engine, which
        # tools/engine_side_wa_perturbation.py clones via git); a file copy
        # is sufficient because the mutation is a single source literal, not
        # a commit this project needs to retag.
        def _ignore(_dir: str, names: List[str]) -> List[str]:
            return [n for n in names if n in (".git", "build") or n.startswith(".venv")]
        shutil.copytree(repo_root, clone_dir, ignore=_ignore)

        def build_and_bake(expect_status: Optional[str], phase: str) -> None:
            build_dir = clone_dir / "build" / "scratch"
            configure_cmd = [cmake, "-S", str(clone_dir), "-B", str(build_dir), "-G", "Ninja",
                              "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_CXX_COMPILER={cxx}",
                              f"-DCMAKE_PREFIX_PATH={engine_prefix}", f"-DPython3_EXECUTABLE={python_exe}"]
            if model:
                configure_cmd.append(f"-DSEMB_C12B_MODEL={model}")
            if tokenizer:
                configure_cmd.append(f"-DSEMB_U1_TOKENIZER={tokenizer}")
            cfg = subprocess.run(configure_cmd, cwd=clone_dir, capture_output=True, text=True, timeout=480)
            if cfg.returncode != 0:
                table.add(f"{leg['name']} {phase} configure", "FAIL", (cfg.stdout + cfg.stderr)[-2000:])
                return
            bld = subprocess.run([cmake, "--build", str(build_dir), "--target", "te163_bank_pair_test"],
                                 cwd=clone_dir, capture_output=True, text=True, timeout=1800)
            if bld.returncode != 0:
                table.add(f"{leg['name']} {phase} build", "FAIL", (bld.stdout + bld.stderr)[-2000:])
                return
            exe_candidates = list(build_dir.rglob("te163_bank_pair_test.exe"))
            if not exe_candidates:
                table.add(f"{leg['name']} {phase} build", "FAIL", "te163_bank_pair_test.exe not found after build")
                return
            # A minimal, targeted probe -- the good-triple bake alone, not the
            # full suite -- via the SAME binary's own --scratch/--wb-corpus
            # CLI, reused rather than a second harness invented for this cell.
            scratch = build_dir / "_scratch" / "c34_probe"
            scratch.mkdir(parents=True, exist_ok=True)
            probe_args = [str(exe_candidates[0]), "--model", model, "--tokenizer", tokenizer,
                          "--dims", "1024", "--scratch", str(scratch),
                          "--wb-corpus", str(clone_dir / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl")]
            proc = subprocess.run(probe_args, cwd=clone_dir, capture_output=True, text=True, timeout=1800)
            out = proc.stdout
            bake_line = next((l for l in out.splitlines() if "bake the WB fixture" in l), "")
            if expect_status is None:
                # The restored (healthy) build: the bake must succeed, [PASS].
                ok = bake_line.startswith("[PASS]")
            else:
                # The mutated build: the bake must refuse BY NAME, [FAIL]
                # with the expected status quoted (a wrong-but-non-SEMB_OK
                # status is not this leg's own claim -- it must be the named
                # refusal, not merely "not SEMB_OK").
                ok = bake_line.startswith("[FAIL]") and expect_status in bake_line
            table.add(f"{leg['name']} {phase} bake result", "PASS" if ok else "FAIL", bake_line.strip() or out[-500:])

        # Mutate.
        text = src_path.read_text(encoding="utf-8")
        mutated_full = str(clone_dir / src_path.relative_to(repo_root))
        mutated_text = text.replace(f'"{original_value}"', f'"{tampered_value}"', 1)
        Path(mutated_full).write_text(mutated_text, encoding="utf-8")
        build_and_bake(leg["expected_status"], "mutated")

        # Restore (the clone's own copy; the tracked repository is never
        # touched by this driver).
        Path(mutated_full).write_text(text, encoding="utf-8")
        build_and_bake(None, "restored")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--engine-prefix", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--cxx-compiler", required=True)
    ap.add_argument("--python-executable", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args(argv)
    repo_root = Path(args.repo_root)
    table = Table()

    if not args.model or not args.tokenizer:
        for leg in LEGS:
            table.add(leg["name"], "MISSING PREREQUISITE",
                      "requires --model and --tokenizer naming the real candidate artifact and its "
                      "converter-emitted tokenizer (SEMB_C12B_MODEL, SEMB_U1_TOKENIZER)")
        print("\nte163_c34_manifest_honesty_check: no hard FAIL (MISSING PREREQUISITE)")
        return 0

    for leg in LEGS:
        run_mutation_leg(table, repo_root, args.engine_prefix, args.cmake_executable, args.cxx_compiler,
                          args.python_executable, args.model, args.tokenizer, leg)

    print(f"\nte163_c34_manifest_honesty_check: {'FAILED' if table.hard_failed else 'no hard FAIL (RED-UNIMPLEMENTED/MISSING PREREQUISITE are red-first, not driver failures)'}")
    return 1 if table.hard_failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
