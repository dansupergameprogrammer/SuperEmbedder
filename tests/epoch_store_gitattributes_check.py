"""tests/epoch_store_gitattributes_check.py -- TE-162 (U1 slice 3): the
sub-plan's own cell 5, "the .gitattributes pin". The dispatch's own fixed
points (D-SLM6377): "The repository's `.gitattributes` is `* -text`, so the
binary member is checkout-invariant; assert that attribute in a cell rather
than assuming it."

TWO LEGS:
  (a) POSITIVE, against `--repo-root` (the real product repository):
      `git check-attr text epoch-store/live/x/vectors.f32` must report
      "unset" -- the path need not exist on disk; `git check-attr`
      evaluates a hypothetical path against the repository's own
      `.gitattributes` rules, exactly as it would for a real committed
      file at that path.
  (b) NEGATIVE, mutation-proof (Curie's own "a check must be shown able to
      fail" discipline): a scratch git repository this script builds with
      NO `* -text` rule covering `epoch-store/` must report something OTHER
      than "unset" for the identical path -- proving leg (a) can actually
      fail, not merely pass by construction on every repository regardless
      of its own `.gitattributes`.

RED-FIRST: leg (a) is independent of whether `epoch-store/` itself exists
(`git check-attr` needs no file on disk) -- it is expected GREEN today,
since the product repository's root `.gitattributes` already carries
`* -text` (confirmed this round, `git show HEAD:.gitattributes`) and that
rule covers every path under the repository, `epoch-store/` included, by
construction. This cell's own red-first claim is narrower than the other
four: it is not gated on the store existing, and is authored now so the
builder inherits a working assertion rather than having to invent one.

USAGE: epoch_store_gitattributes_check.py --repo-root <dir> --scratch-dir <dir> [--git <git-exe>]
Exit codes: 0 both legs PASS; 1 either FAILs.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROBE_PATH = "epoch-store/live/x/vectors.f32"


def check_attr(repo: Path, git: str, path: str) -> str:
    proc = subprocess.run([git, "-C", str(repo), "check-attr", "text", path], capture_output=True, text=True)
    return proc.stdout.strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", required=True)
    p.add_argument("--scratch-dir", required=True)
    p.add_argument("--git", default="git")
    args = p.parse_args()

    failures = 0

    # ---- (a) positive: the real product repository. ----
    repo_root = Path(args.repo_root)
    out = check_attr(repo_root, args.git, PROBE_PATH)
    expected = f"{PROBE_PATH}: text: unset"
    ok = out == expected
    print(f"[{'PASS' if ok else 'FAIL'}] (5a) {PROBE_PATH} reports 'text: unset' in the product repository", out)
    if not ok:
        failures += 1

    # ---- (b) negative, mutation-proof: a scratch repo with NO covering
    # `* -text` rule must NOT report "unset" for the identical path. ----
    scratch = Path(args.scratch_dir) / "no-gitattributes-repo"
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.git, "init", "-q"], cwd=str(scratch), check=True)
    subprocess.run([args.git, "config", "user.email", "epoch-store-gitattributes-check@test"], cwd=str(scratch), check=True)
    subprocess.run([args.git, "config", "user.name", "epoch_store_gitattributes_check"], cwd=str(scratch), check=True)
    (scratch / "README.txt").write_text("no .gitattributes covering epoch-store/ here\n", encoding="utf-8")
    subprocess.run([args.git, "add", "-A"], cwd=str(scratch), check=True)
    subprocess.run([args.git, "commit", "-q", "-m", "scratch repo with no -text rule"], cwd=str(scratch), check=True)

    neg_out = check_attr(scratch, args.git, PROBE_PATH)
    neg_ok = neg_out != expected
    print(f"[{'PASS' if neg_ok else 'FAIL'}] (5b, mutation-proof) a repository with no covering '* -text' rule "
          f"does NOT report 'unset' for {PROBE_PATH}", neg_out)
    if not neg_ok:
        failures += 1

    print(f"\nepoch_store_gitattributes_check: 2 cell(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
