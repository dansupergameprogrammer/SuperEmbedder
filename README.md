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

Requires CMake >= 3.21, a C++20 compiler, Python 3, and Ninja (the CMake
consumption surface needs the Ninja generator for the provenance
re-verification steps below to run; other generators still configure and
build, with those checks skipped and a warning printed).

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
