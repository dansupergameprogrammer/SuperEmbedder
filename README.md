# SuperEmbedder

A deterministic text encoder: the same text produces bit-identical embedding
vectors on every certified platform. It is the front half of a cross-device
vector-search guarantee — [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss)
is bit-identical from the bank onward; SuperEmbedder makes the path bit-identical
from the raw text in.

**Status: U0 scaffold landed 2026-09-01 (TE-61).** The repository builds: the
engine pin, the two configure guards, the build-flag assertion, and CI exist.
The encoder itself — the pooling epilogue, the interim TU, the witness
drivers — is not yet built (TE-63). See [Build](#build) below.

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

- **`tools/engine_side_wa_perturbation.py`** (sec 8 C36(a), D-SLM6157,
  D-SLM6191) — clones the newly-pinned tag twice (an unperturbed baseline
  pair, and a mutant with one non-inline engine arithmetic site
  perturbed), builds and installs each, and asserts `witness_sha` agrees
  between the two unperturbed baselines and differs for the mutant. Run:
  `python tools/engine_side_wa_perturbation.py --scratch-root <scratch dir>`.
  `tests/witness_structural_matrix.py`'s own C36(a) leg checks only that
  this script exists and that its argparse/output contract matches what
  this suite depends on — it does not run the recipe under `ctest`.
- **C35's own two-installation construction** (`Claude/Plans/SuperEmbedder_Plan.md`
  sec 8, C35) — two independent SuperEmbedder installations, each built
  against its own `tools/pin-superslm` run, exercising the thirteen
  configurations sec 8 names. **Not yet built** (§5's readiness table
  routes it to U1/U2); this section is where its own runnable script is
  named once it lands, alongside the perturbation script above.
