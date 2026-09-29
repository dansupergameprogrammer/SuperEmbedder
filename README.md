# SuperEmbedder

A deterministic text encoder: the same text produces bit-identical embedding
vectors on every certified platform. It is the front half of a cross-device
vector-search guarantee — [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss)
is bit-identical from the bank onward; SuperEmbedder makes the path bit-identical
from the raw text in.

**Status: the U1 public raw-text encoder slice is real and pinned to SuperSLM
v1.8.0.** `include/superembedder/semb.h` exposes the frozen C ABI for
encoder open/close, dimension discovery, raw UTF-8 encoding, and status names.
Open reads the model and tokenizer artifacts exactly once, keeps the
tokenizer's bytes, hands the model to the engine and releases its own copy,
validates the vocabulary join, and returns holding no workspace, so it reserves
nothing in proportion to `max_concurrency`; each encode's workspace is sized to
its document.
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
`semb bake` and `semb verify` read a corpus, and `semb query --stdin` reads
queries, one line at a time; a line is the bytes up to each LF on every
platform, so a CR before the LF is text, and a final line without an LF is
still a line.
`semb bake` and `semb verify` skip a document only when empty text (the
library's own `SEMB_INPUT_EMPTY` refusal, unchanged for every other caller)
is its sole defect; a document with an empty, NUL-containing, or invalid-UTF-8
id is still refused by name, never silently skipped, whether or not its text
is also empty. A skip that would collide with another document's id (kept or
also skipped) refuses `SEMB_DOCUMENT_ID_DUPLICATE`, unless some other
document in the batch has its own defect the library would refuse for first,
in which case that refusal is reported instead. Both commands report each
skipped id on stderr, the id printed as an escaped JSON string
(`skipped "<id>": SEMB_INPUT_EMPTY`), and `semb bake` writes a
`<stem>.skipped.json` sidecar next to the bank on every successful bake (a
JSON array of `{"id", "reason"}`, `[]` when nothing was skipped, so a clean
re-bake never leaves a stale sidecar from an earlier one). If the sidecar
write itself fails, `semb bake` exits 1 from `semb bake skipped-sidecar`
even though the bank is valid and was written first; any sidecar left by a
previous bake at that stem is also removed (best effort) rather than left
to describe the wrong bake, unless the sidecar path is a directory, which
is left untouched. The sidecar is
informational only: `semb verify`'s corpus-identity verdict comes entirely
from its existing row/corpus digest comparison, so a bank moved or copied as
its three files (no sidecar), or one whose sidecar is stale, is verified
correctly either way.
The linked engine also writes one line of its own to stderr each time an
encoder is opened, through the library or any `semb` verb that opens one:
`preflight: <n>/<layers> layers carry a non-degenerate (per-output-channel)
WSC1 fold tensor ...`. It is expected, it is not an error, and it is not
silenced in this release. It shares the stream with the skip reports above,
so a consumer parsing stderr tells them apart by prefix: a skip report starts
with `skipped "`, the engine's line with `preflight: `.

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

`semb_encoder_open_memory` opens an encoder from model and tokenizer bytes
already in memory. It copies both spans before it reads them and then runs the
open `semb_encoder_open` runs, so the same bytes give the same fingerprint by
either verb, and the caller may release its spans once the call returns.
`semb_encode_query` is the query form of `semb_encode`: it applies the
instruction prefix `semb_query_encode` applies, through the same composition,
and returns the fingerprint the vector was emitted under, with no bank. It
checks nothing against a bank; a consumer that ships a fingerprint in place of
the float bank compares the returned value with the manifest's
`encoder_fingerprint` itself ([docs/FORMAT.md](docs/FORMAT.md)).

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

### Installing the library

`cmake --install build/semb --prefix <dir>` installs the shared library
(`semb.dll` with its import library `semb.lib` on Windows, `libsemb.so` on
Linux, `libsemb.dylib` on macOS), the public headers `semb.h` and
`version.h`, the `semb` CLI, and a CMake package. A consumer links it with

```cmake
find_package(superembedder CONFIG REQUIRED)
target_link_libraries(app PRIVATE superembedder::superembedder)
```

The package's version file accepts a request for the same major version only.
The library exports exactly the verbs `semb.h` declares and nothing else: the
export list is generated from the header when the build is configured, and
the build fails with `SEMB_EXPORT_LIST_MISMATCH` if the linked library's
exports differ from it. The engine is linked into the library privately, so an
application needs no engine of its own to use it. On Linux the engine must be
position-independent to enter a shared library; the pin tool builds it that
way off Windows, so an engine pinned before this release has to be pinned again.

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

## Using a bank with SuperFAISS

A bank `semb bake` writes is a SuperFAISS `.wvbank` sidecar pair
(`<stem>.wvbank.json` and `<stem>.wvbank.bin`: schemaVersion 1, `float32`,
`cosine`, ids in corpus order), read by SuperFAISS's reference reader
(`tools/wvbank.py read_bank`) or your own importer. Import it the way
SuperFAISS's `docs/INTEGRATION.md` section 4 says: `ValidateSourceRows`, then
`NormalizeRows` (the bank is `cosine`; SuperEmbedder does not normalize its
rows), then `QuantizeRowsInt8` or `PadRowsFloat32`, then `ValidateBankData` at
load.

To query it, take the vector `semb query` emits for your text (`--raw` gives
the `dims × 4` float32 bytes, the default `VECTOR_HEX=` line the same bytes in
hex) and:

1. **Pad it to the bank's `paddedDims`** — `PaddedDims(dims, quantization)`,
   the dimension rounded up to a 16-byte row — with zero lanes, in a 16-byte
   aligned buffer. For a 1024-dimension bank this adds no lanes in either
   quantization.
2. **Pass it as emitted: do not normalize it.** A `cosine` bank's rows are
   unit-normed at bake, and SuperFAISS scores a `cosine` query as a plain dot
   product against them, checking only that the query is finite, has zero pad
   lanes and is not all zeros. A query's length multiplies every one of its
   scores by the same positive factor, so it does not change the ranking the
   scores define; the scores read as cosines only for a unit-length query.
   In `CrossDevice` mode SuperFAISS quantizes the float32 bytes it is given,
   so a query you normalize yourself is a different int8 query from the
   emitted one. Its hits need not be bit-identical to hits from the emitted
   vector on another machine.

The round-trip harness (`tests/superfaiss_roundtrip/`) runs exactly these
steps against SuperFAISS v3.4.3, the release `superfaiss.lock` pins. Over the
239-document proof corpus it checks that SuperFAISS's float32 top-10 equals an
independent float64 cosine top-10, and that `semb query --top 10`, an exact
diagnostic scan and not the search engine, equals the same list; it also
grades SuperFAISS's `CrossDevice` int8 ranking on class-match@1.
