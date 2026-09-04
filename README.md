# SuperEmbedder

A deterministic text encoder: the same text produces bit-identical embedding
vectors on every certified platform. It is the front half of a cross-device
vector-search guarantee — [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss)
is bit-identical from the bank onward; SuperEmbedder makes the path bit-identical
from the raw text in.

**Status: U0 encoder core is real and pinned to SuperSLM v1.4.0.** The
`superembedder` library opens a real `.sslm` artifact through the interim
engine adapter, encodes token IDs, captures the exact `{codes,m,e}` seam,
applies PS-1 pooling, and serializes the W-B witness. `semb_witness` executes
that path end to end. The `semb` user CLI is still the U0 version/pin stub;
the durable public open/encode/bake/query surface is U1.

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
- **C35's own two-installation construction** (`Claude/Plans/SuperEmbedder_Plan.md`
  sec 8, C35) — two independent SuperEmbedder installations, each built
  against its own `tools/pin-superslm` run, exercising the thirteen
  configurations sec 8 names. **Not yet built** (§5's readiness table
  routes it to U1/U2); this section is where its own runnable script is
  named once it lands, alongside the perturbation script above.
