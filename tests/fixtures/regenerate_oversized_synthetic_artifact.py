"""tests/fixtures/regenerate_oversized_synthetic_artifact.py -- TE-80: the
fixture F-7's owed assertion needs (TE-79 build log sec 9 item 3): a
synthetic `.sslm` artifact whose `hidden_size` EXCEEDS
`kSembWitnessMaxHidden` (64), so `semb_encode_document_for_witness`'s own
domain refusal (`kSembEncodeHiddenTooLarge`, TE-76 review F-7) can be
exercised for real rather than filed as unreachable against the pinned
tag's own tiny T-2199 fixture (whose `hidden_size` is 32, well under the
ceiling -- verified, F-13).

HERMETIC, NEVER COMMITTED AS A BLOB -- the identical discipline
`regenerate_synthetic_artifact.py` already holds (sec 4.4b's own U1 corpus
rule, applied to a generated artifact): clones the pinned engine tag into
a scratch directory and deletes it afterward; the artifact itself is never
checked into this repository.

WHY A SEPARATE SCRIPT RATHER THAN A FLAG ON THE EXISTING ONE. The pinned
tag's own T-2199 generator
(`tools/_t2199_s8_synthetic_full_model_fixture.py`) hardcodes its own
`build_config()` -- `hidden_size=32` is fixed inside the ENGINE
repository's own committed tool, read-only to this seat. This script does
NOT call that function; it imports the SAME underlying, GENERIC machinery
that function itself calls (`reference_pipeline.pipeline.ModelConfig`,
`.fixture_model`; `convert_model.build_sections`; `sslm_format.build_artifact`)
and supplies its OWN config, with `hidden_size=128` -- twice
`kSembWitnessMaxHidden`, so the domain check is exercised well past its
own boundary, not merely one byte over it. Every other field is scaled
proportionally from the T-2199 config (`head_dim=16 * num_attention_heads=8
= hidden_size=128`; `num_key_value_heads=4`, an even GQA group size of 2,
matching the T-2199 config's own 4/2 ratio) so the SAME domain checks
`reference_pipeline` already exercises on the small fixture (RoPE pairwise
rotation, GQA group-size divisibility) are satisfied here too -- this is
not a novel shape, only a scaled one. No `SCHEMA_MASKS`/damped-greedy
section is added (this fixture's only job is to report a large
`hidden_size`, not to exercise Phase D's own gate), matching T-2199's own
simpler `build_plain_artifact_bytes()` path.

USAGE
  python tests/fixtures/regenerate_oversized_synthetic_artifact.py \\
      --lock superslm.lock --out <path>.sslm [--source <path-or-url>]
      [--workdir <scratch dir>]

Exit codes: 0 success; 1 usage/environment error; 2 clone/generation
failure.
"""
from __future__ import annotations

import argparse
import shutil
import stat
import subprocess
import sys
from pathlib import Path

DEFAULT_REMOTE = "https://github.com/dansupergameprogrammer/SuperSLM.git"

# hidden_size = num_attention_heads * head_dim = 8 * 16 = 128, twice
# kSembWitnessMaxHidden (64) -- scaled 4x from the T-2199 fixture's own
# 32/4/2/8 shape, preserving its own GQA group size (2) and every domain
# ratio reference_pipeline's own checks require.
OVERSIZED_HIDDEN = 128


def _rmtree_onerror(func, path, exc_info):
    import os
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def read_lock_tag(lock_path: Path) -> str:
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("tag="):
            return line[len("tag="):]
    raise ValueError(f"{lock_path}: no 'tag=' line found")


def clone_engine_tools(tag: str, source: str, workdir: Path) -> Path:
    rmtree(workdir)
    workdir.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
         "--branch", tag, "--single-branch", source, str(workdir)],
        check=True,
    )
    return workdir


def generate(tools_dir: Path, out_path: Path) -> bytes:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")

    cfg = pipeline.ModelConfig(
        hidden_size=OVERSIZED_HIDDEN,
        num_hidden_layers=8,        # unchanged from T-2199's own config
        num_attention_heads=8,      # 8 * 16 = 128
        num_key_value_heads=4,      # same GQA group size (2) as T-2199 (4/2)
        head_dim=16,
        intermediate_size=256,      # scaled 4x with hidden_size, T-2199's own ratio (64/32=2x... kept simple, 2x hidden)
        vocab_size=128,             # unchanged -- token ids stay in the same small vocab
        rope_theta=10000.0,
        rms_norm_eps=1e-6,
        tie_word_embeddings=True,
        context_cap=64,             # unchanged -- irrelevant to this fixture's own purpose
    )
    model = pipeline.fixture_model(cfg)
    sections, _fold_err = convert_model.build_sections(model)  # no damped-greedy: not this fixture's concern
    data, fingerprint = sslm_format.build_artifact(sections)
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, hidden_size={OVERSIZED_HIDDEN}, "
          f"fingerprint={fingerprint}")
    return data


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="superslm.lock")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=DEFAULT_REMOTE)
    ap.add_argument("--workdir", default="build/_oversized_fixture_workdir")
    args = ap.parse_args(argv)

    lock_path = Path(args.lock)
    if not lock_path.exists():
        print(f"SEMB_FIXTURE_LOCK_MISSING: {lock_path} does not exist.", file=sys.stderr)
        return 1
    tag = read_lock_tag(lock_path)
    print(f"regenerating the oversized-hidden synthetic artifact from pinned tag {tag}")

    workdir = Path(args.workdir)
    try:
        clone = clone_engine_tools(tag, args.source, workdir)
    except subprocess.CalledProcessError as ex:
        print(f"SEMB_FIXTURE_CLONE_FAILED: {ex}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        generate(clone / "tools", out_path)
    except Exception as ex:  # noqa: BLE001 -- reported, not swallowed
        print(f"SEMB_FIXTURE_GENERATION_FAILED: {ex}", file=sys.stderr)
        rmtree(workdir)
        return 2

    rmtree(workdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
