# SuperEmbedder

A deterministic text encoder: the same text produces bit-identical embedding
vectors on every certified platform. It is the front half of a cross-device
vector-search guarantee — [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss)
is bit-identical from the bank onward; SuperEmbedder makes the path bit-identical
from the raw text in.

**Status: the U1 public raw-text encoder slice is real and pinned to SuperSLM
v1.5.0.** `include/superembedder/semb.h` exposes the frozen C ABI for
encoder open/close, dimension discovery, raw UTF-8 encoding, and status names.
Open reads the model and tokenizer artifacts exactly once, retains their bytes,
validates the vocabulary join, and preallocates the declared workspace pool.
Open derives the appended end token from the tokenizer artifact by resolving
`<|endoftext|>`; `semb_config` carries no token id. Encode tokenizes the caller's sized
span unchanged, appends that artifact-pinned token exactly once, runs the
C12b-proven PS-N path, and returns caller-owned aligned float32 bytes.

The token-id seam remains available internally for the witness and C12b cells;
it is no longer the public header. The `semb` CLI bakes a corpus into a
`.wvbank` bank (`semb bake`), encodes queries against a bank (`semb query`),
re-encodes a bank's corpus and compares it with the bank (`semb verify`), and
prints a bank's manifest (`semb inspect`). A document longer than the model's
context is refused by name (`SEMB_CONTEXT_CAP_EXCEEDED`), never truncated; a
query is cut to the context after its instruction prefix is applied.

The encoder fingerprint, returned by `semb_encode` and `semb_fingerprint_of`, is
the SHA-256 over five length-prefixed components: the model artifact's bytes,
the tokenizer artifact's bytes, the template literals the composition applies,
the executed witness (W-A, W-B and W-Q), and the certification epoch — the
SHA-256 of `docs/certified-builds.json` as the build compiled it in. Every bank
manifest records the same value as `encoder_fingerprint`, and opening a query
against a bank baked by a different encoder is refused with
`SEMB_FINGERPRINT_MISMATCH`. Banks baked before the certification epoch was
derived from that document record a placeholder epoch in their manifests
(`certification_epoch` is
`fbfde55166495bb2bcbd63a3688a0b7e091fc0b301ad916a3603c835ba46a30c`), so their
`encoder_fingerprint` differs from the current encoder's. Opening a query
against one is refused with `SEMB_FINGERPRINT_MISMATCH`, and such banks must be
re-baked.

The certified set is interim: the MSVC 19.33 and clang-cl 18.1.8 builds on one
AVX2 host, which bake the 239-document corpus to identical bytes (evidence in
`docs/certification/interim/`). `python tools/check_certified_builds.py --root .`
checks the committed certification package. The release set (AVX-512, AVX2 and
SSE2) is certified before the 1.0 tag.

## Relationship to the sibling projects

| Project | Role |
|---|---|
| [SuperSLM](https://github.com/dansupergameprogrammer/SuperSLM) | The integer-only transformer forward SuperEmbedder runs on. SuperEmbedder is a client of it, never a fork of it. |
| [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss) | The consumer of the banks SuperEmbedder produces and the query vectors it emits (`.wvbank` sidecar format). |

The three are developed as separate, linked repositories.

## Build

Requires CMake >= 3.21, a C++20 compiler, Python 3, and Ninja. The Ninja
generator is a hard requirement, not merely a recommendation: configure
refuses (`SEMB_SOURCE_DRIFT_CHECK_UNAVAILABLE`) on any other generator or
when no `ninja` executable is resolvable, rather than silently building
without the provenance re-verification steps below.

```sh
# 1. Pin and install the engine this checkout builds against. superslm.lock's
#    tag= is the only field a person edits; this tool derives commit= and
#    tree= from the tag it clones and builds.
python tools/pin-superslm/pin_superslm.py \
    --lock superslm.lock --prefix build/_engine_install

# 2. Configure and build.
cmake -G Ninja -S . -B build/semb -DCMAKE_PREFIX_PATH="$PWD/build/_engine_install"
cmake --build build/semb

# 3. Run the CLI stub and the negative-configure / build-flag test matrix.
./build/semb/semb
ctest --test-dir build/semb --output-on-failure
```

On Windows, run the above from a Developer Command Prompt (or after
`VsDevCmd.bat`) so `cl.exe` and `dxc.exe` (required by the engine's own
Windows configure) are resolvable.

## Pin bump procedure

Whenever `superslm.lock`'s `tag=` is bumped to a new pinned SuperSLM
release, two constructions must be re-run before the bump lands — both
need a fresh engine clone and a fresh engine build, which is exactly what
makes them unsuitable as per-push CI legs (`Claude/Plans/SuperEmbedder_Plan.md`
sec 4.4d item 4; D-SLM6161 holds hosted CI scarce):

- **`tools/engine_side_wa_perturbation.py`** (sec 8 C36(a) and C38,
  D-SLM6157/D-SLM6191) — builds two independent unperturbed baselines, a
  mutant with one non-inline engine arithmetic site perturbed, and a fourth
  scratch engine whose installed `ReadCarriedScale` header carries C38's
  compile-time branch. It asserts the baselines agree, the non-inline mutant
  moves `witness_sha`, the injected branch is inert by default, a library-only
  definition moves `witness_sha`, and a witness-only definition is inert. The
  released SuperSLM tag is never edited; both mutations live only in throwaway
  clones under the requested scratch root. Run:
  `python tools/engine_side_wa_perturbation.py --scratch-root <scratch dir>`.
  `tests/witness_structural_matrix.py` checks the durable C36(a)/C38 script
  contract and commissions C38's verdict logic via `--selftest-only`; it does
  not repeat the clone/build recipe under every `ctest` run.
- **C35's two-installation construction** (`tests/c35_two_installation_harness.py`;
  `Claude/Plans/SuperEmbedder_Plan.md` sec 8, C35) — two independent
  SuperEmbedder installations, each built against its own `tools/pin-superslm`
  engine prefix; the 239-document corpus is baked on one and queried from the
  other. Its 1.0 legs: an identical rebuild and an MSVC-against-clang-cl pair
  must accept; an edited epilogue, an edited non-inline engine `.cpp`, a
  one-byte certification-document edit and a bank baked by the provisional
  build must each be refused with `SEMB_FINGERPRINT_MISMATCH`. It runs in
  phases from a Visual Studio developer shell, never in CI; the phase order is
  in the script's docstring.
