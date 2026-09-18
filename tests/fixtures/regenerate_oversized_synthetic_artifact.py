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
own boundary, not merely one byte over it. Every other field is derived
from `hidden_size` (`num_attention_heads = hidden_size / head_dim` with
`head_dim=128`, the only head width the pinned engine admits for a QK-norm
(fused-K) artifact; `num_key_value_heads` half of that, an even GQA group
size of 2, matching the T-2199 config's own 4/2 ratio) so the SAME domain checks
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

# TE-147 (U1 slice 2 build): kSembWitnessMaxHidden rose from 64 to 1024
# (the real candidate's own hidden_size, seam_abi.h's own comment) -- this
# default rises with it, twice the NEW ceiling (2048), the same "well past
# its own boundary, not merely one byte over it" margin the original 128
# value held against the retired 64 ceiling. hidden_size = num_attention_heads
# * head_dim = 16 * 128 = 2048; the GQA group size (2) and every other
# domain ratio reference_pipeline's own checks require are unchanged.
OVERSIZED_HIDDEN = 2048


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


def generate(tools_dir: Path, out_path: Path, hidden_size: int = OVERSIZED_HIDDEN) -> bytes:
    sys.path.insert(0, str(tools_dir))
    sys.path.insert(0, str(tools_dir / "reference_pipeline"))
    import importlib
    convert_model = importlib.import_module("convert_model")
    pipeline = importlib.import_module("pipeline")
    sslm_format = importlib.import_module("sslm_format")

    # TE-83 (TE-81 review N-7, N-8): generalised from a single hardcoded
    # 128-only config to any `hidden_size` a caller names, so this same
    # generator can also produce the AT-THE-BOUND fixture (hidden_size ==
    # kSembWitnessMaxHidden exactly) that seam_hidden_capacity_test.cpp's
    # own must-accept needs -- its sibling, c3_accumulator_bound_test.cpp's
    # F-2 cell, already tests exactly that boundary shape by name, and
    # this fixture generator did not. `head_dim=128` fixed (the only head
    # width the pinned engine admits for a QK-norm artifact); every other
    # dimension DERIVED from `hidden_size` by one plain rule each, stated
    # here rather than as a self-contradicting trailing comment (N-8: the
    # prior comment read "scaled 4x with hidden_size, T-2199's own ratio
    # (64/32=2x... kept simple, 2x hidden)" -- two different ratios in one
    # parenthetical, trailing off mid-reasoning):
    #   num_attention_heads = hidden_size // head_dim   (so their product
    #     is exactly hidden_size)
    #   num_key_value_heads = num_attention_heads // 2  (the SAME GQA
    #     group size, 2, T-2199's own 4/2 config uses)
    #   intermediate_size   = 2 * hidden_size            (one plain rule,
    #     not a ratio borrowed from a different config's own numbers)
    # Both sizes seam_hidden_capacity_test.cpp requests (OVERSIZED_HIDDEN
    # and kSembWitnessMaxHidden) divide by head_dim into an even head count.
    head_dim = 128
    if hidden_size % head_dim != 0:
        raise ValueError(f"hidden_size={hidden_size} is not a multiple of head_dim={head_dim}")
    num_attention_heads = hidden_size // head_dim
    if num_attention_heads % 2 != 0:
        raise ValueError(f"num_attention_heads={num_attention_heads} (hidden_size="
                         f"{hidden_size} / head_dim={head_dim}) is not even -- cannot halve "
                         f"for num_key_value_heads at the GQA group size this fixture uses")
    num_key_value_heads = num_attention_heads // 2

    cfg = pipeline.ModelConfig(
        hidden_size=hidden_size,
        num_hidden_layers=8,        # unchanged from T-2199's own config
        num_attention_heads=num_attention_heads,
        num_key_value_heads=num_key_value_heads,
        head_dim=head_dim,
        intermediate_size=2 * hidden_size,
        vocab_size=128,             # unchanged -- token ids stay in the same small vocab
        rope_theta=10000.0,
        rms_norm_eps=1e-6,
        tie_word_embeddings=True,
        context_cap=64,             # unchanged -- irrelevant to this fixture's own purpose
    )
    model = pipeline.fixture_model(cfg)
    sections, _fold_err = convert_model.build_sections(model)  # no damped-greedy: not this fixture's concern
    data, fingerprint = sslm_format.build_artifact(
        sections, flags=convert_model.artifact_flags_for_model(model))
    out_path.write_bytes(data)
    print(f"wrote {out_path}: {len(data)} bytes, hidden_size={hidden_size}, "
          f"fingerprint={fingerprint}")
    return data


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="superslm.lock")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=DEFAULT_REMOTE)
    ap.add_argument("--workdir", default="build/_oversized_fixture_workdir")
    ap.add_argument("--hidden-size", type=int, default=OVERSIZED_HIDDEN,
                     help="TE-83 (N-7): defaults to the over-the-ceiling value "
                          f"({OVERSIZED_HIDDEN}); pass --hidden-size 1024 (TE-147: the "
                          "current kSembWitnessMaxHidden) for the AT-THE-BOUND fixture instead.")
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
        generate(clone / "tools", out_path, hidden_size=args.hidden_size)
    except Exception as ex:  # noqa: BLE001 -- reported, not swallowed
        print(f"SEMB_FIXTURE_GENERATION_FAILED: {ex}", file=sys.stderr)
        rmtree(workdir)
        return 2

    rmtree(workdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
