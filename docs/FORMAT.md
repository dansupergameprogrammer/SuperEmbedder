# File formats

This page documents the files SuperEmbedder writes and reads that a consumer may need to parse: a bank's
manifest, the certified-builds list, the certification identity file, and the engine-build record. The bank
itself is SuperFAISS's format and is documented there.

<!-- Placeholders in {{DOUBLE_BRACES}} are filled before the release; each carries a comment naming the step
     that produces it. -->

## 1. A bank

`semb bake <corpus> --out <stem>` writes three files, plus a report of skipped documents:

| File | Contents |
|---|---|
| `<stem>.wvbank.json` | The bank header, SuperFAISS `FORMAT.md` §1: `{"schemaVersion": 1, "dims", "count", "metric": "cosine", "dtype": "float32", "ids": [...]}` |
| `<stem>.wvbank.bin` | `count` × `dims` little-endian `binary32` rows, in `ids` order, not normalized |
| `<stem>.semb.json` | The manifest, below |
| `<stem>.skipped.json` | Documents skipped for empty text: a JSON array of `{"id", "reason": "empty_text"}`, `[]` when none. Informational only; no reader uses it |

SuperFAISS reads the first two directly. SuperEmbedder reads all three when it opens a bank for queries.

**The corpus `semb bake` and `semb verify` read.** A `.jsonl` corpus (the extension, in any case) is one
`{"id", "text"}` object per line, and an empty line is skipped; any other corpus is one document per line, with
its zero-based line number as its id. The file is read in binary mode: a line is the bytes up to each LF on every
platform, so a CR before the LF belongs to the line, and a final line without an LF is still a line.

## 2. The manifest, `<stem>.semb.json`

A JSON object. **Readers ignore members they do not recognise.** A manifest whose `schemaVersion` is not 1,
or that carries a `channels` member, is refused (`SEMB_MANIFEST_SCHEMA_UNSUPPORTED`).

### 2.1 Identity

| Member | Type | Meaning |
|---|---|---|
| `schemaVersion` | integer | `1` |
| `encoder_fingerprint` | hex string, 64 | The encoder fingerprint ([DETERMINISM.md](DETERMINISM.md#what-the-fingerprint-covers)). A query handle refuses a bank whose value differs from its encoder's (`SEMB_FINGERPRINT_MISMATCH`). **This is the value a companion fingerprint asset copies** when a consumer ships a fingerprint in place of the float bank; `semb_fingerprint_of`, `semb_encode` and `semb_encode_query` return the same value from an open encoder, and comparing the two is the consumer's check |
| `model_sha` | hex string, 64 | Fingerprint field 1 |
| `tokenizer_sha` | hex string, 64 | Fingerprint field 2 |
| `template_sha256` | hex string, 64 | Fingerprint field 3 |
| `witness_sha` | hex string, 64 | Fingerprint field 4 |
| `certification_epoch` | hex string, 64 | Fingerprint field 5 |

### 2.2 The rows

| Member | Type | Meaning |
|---|---|---|
| `count` | integer | Number of rows; at most 10,000,000 for SuperEmbedder's reader |
| `dims` | integer | Elements per row; at most 131,072 for SuperEmbedder's reader. 1,024 for the shipped model |
| `metric` | string | `"cosine"` |
| `dtype` | string | `"float32"` |
| `row_digest` | hex string, 64 | SHA-256 of `<stem>.wvbank.bin`'s bytes. A bank whose rows do not match is refused (`SEMB_BANK_DIGEST_MISMATCH`) |
| `corpus_digest` | hex string, 64 | SHA-256 over the baked documents: the row count as a little-endian `u64`, then for each row its id and its text, each as a little-endian `u64` byte length followed by the bytes. `semb verify` compares a corpus against it (`SEMB_CORPUS_DIGEST_MISMATCH`) |
| `token_id_digest` | hex string, 64 | SHA-256 over every row's token ids before the end token: per row, the id count as a little-endian `u64`, then each id as a little-endian `u32` |
| `per_row_token_counts` | array of integers | Each row's token count, before the end token is appended |
| `machine_tier` | string | **The CPU tier the build dispatched to** when it baked: `sse2`, `avx2`, `avx512`, or `scalar` on a target without x86-64 SIMD |

### 2.3 Certification

| Member | Type | Meaning |
|---|---|---|
| `certification_identity_path` | string | `docs/certification-identity.json`, the repository path of the identity file the build compiled in |
| `certified_builds_path` | string | `docs/certified-builds.json`, the repository path of the list the build compiled in |
| `certified_builds_sha256` | hex string, 64 | SHA-256 of that list's bytes. A record of **which list** the bank was baked under; not a fingerprint input |
| `certified_cell` | string | The cell id the build resolved to on the baking host (for example `msvc19.33-auto@avx2`), or `"uncertified"`. A record of **which cell**; not a fingerprint input |
| `build_descriptor` | object | The build's cell descriptor: `os`, `isa`, `toolchain`, `stdlib`, `configuration`, `buildSystem`, `dispatch`, `compileFlags`, `engineFlags`, with the meanings in §3.2 |
| `engine_build_record` | string | The build record the **linked** engine reported when the encoder opened (§5.2) |

### 2.4 Provenance

`provenance` is an object of labels. No member of it is a fingerprint input or decides a verdict.

| Member | Meaning |
|---|---|
| `artifact_sha` | SHA-256 of the model file |
| `engine_tree_sha` | Digest of the engine's source tree as pinned |
| `engine_path_sha` | Digest of the CPU engine adapter's source |
| `engine_chunk_budget` | The engine's pinned chunk budget |
| `object_code_sha`, `engine_object_code_sha`, `semb_source_sha` | Reserved labels; `"NOT-COMPUTED"` in 1.0 |
| `witness` | `{corpus_digest, wa_digest, wb_digest, cpu_tier}`: the witness digests the encoder computed at open, and the tier it ran on |

Top-level labels, also informational:

| Member | Meaning |
|---|---|
| `label:ps_version` | `"PS-N"`, the pooling scheme ([POOLING.md](POOLING.md)). A bank whose label differs from the build's is refused (`SEMB_PS_VERSION_LABEL_MISMATCH`) |
| `label:engine_path_id` | `"interim"`, the CPU engine adapter the build links. It stays `"interim"` on a GPU bake, because it names the adapter that computes the witness in every process. A bank whose label differs is refused (`SEMB_ADAPTER_ID_MISMATCH`) |
| `label:superslm_tag_commit` | The engine tag and commit |
| `label:semb_version` | The SuperEmbedder version |
| `device` | `"cpu"` or `"gpu"`: which forward emitted the rows |
| `gpu_adapter_index` | GPU bakes only: the value of `SSLM_GPU_ADAPTER_INDEX` at open, or `"default"` |
| `gpu_vendor_id`, `gpu_device_id`, `gpu_adapter_name`, `gpu_driver_version` | GPU bakes only: the adapter as the operating system reports it, or `"unknown"` where it could not be read |

## 3. `certified-builds.json`

The published certified set, at `docs/certified-builds.json`. It is **read, not digested**: adding cells to
it does not move the certification epoch.

### 3.1 Top level

```json
{
  "schemaVersion": 1,
  "release": "1.0.0",
  "builds": [ ... ],
  "pairwiseProofs": [ ... ],
  "gpuVerifications": [ ... ]
}
```

### 3.2 `builds[]`: cells

Each entry is one **cell**: one build, running at one CPU tier. Its `id` is `<member>@<tier>`, for example
`clangcl18.1.8-auto@avx512`. An auto-dispatching build is certified per tier, so the same binary is one cell on
an AVX2 host and another on an AVX-512 host.

| Member | Meaning |
|---|---|
| `id` | `<member>@<tier>` |
| `os`, `isa`, `objectFormat` | Target operating system, instruction-set architecture and object format |
| `toolchain` | The exact compiler build, formatted from the compiler's own predefined macros (for example the full MSVC build number). A compiler with the same major version and a different build number is a different toolchain |
| `stdlib` | The C++ standard library, formatted from its own macros by the same rule |
| `configuration` | The build configuration (for example `Release`) |
| `buildSystem` | The build system that produced it |
| `dispatch` | `auto`, or the forced tier |
| `compileFlags` | SHA-256 of the product's compile-flag record (§3.5) |
| `engineFlags` | SHA-256 of the engine's compile-flag record (§3.5) |
| `cpuTier` | The one tier this cell is certified at: `sse2`, `avx2` or `avx512` |
| `artifact` | The model and tokenizer files and their SHA-256 |
| `host` | The machine the cell's runs executed on |
| `evidence` | Repository path of the cell's run records |

At encoder open, a build looks for the one entry whose descriptor fields equal its own and whose `cpuTier`
equals the tier it dispatched to. One match makes it that cell. No match makes it uncertified.

### 3.3 `pairwiseProofs[]`

Every pair of cells has one entry, and a list missing a pair is refused at configure
(`SEMB_CERTIFIED_BUILDS_UNPROVEN`).

| Member | Meaning |
|---|---|
| `a`, `b` | The two cell ids |
| `runIds` | The run ids of the two runs compared |
| `rowDigest` | The shared digest of both cells' per-row digests of the proof corpus |
| `tokenIdDigest` | The shared digest of both cells' token ids for the proof corpus |

### 3.4 `gpuVerifications[]`

GPUs on which a GPU process of a certified build reproduced its cell's certified rows. **An entry is not a
cell**, and the cell matcher never reads this array. Each entry names the GPU's vendor, device, adapter name
and driver, the `builds[]` cell its process resolved to, and the run ids of its evidence.
{{GPU_VERIFICATION_ENTRY_KEYS}}
<!-- filled by: U2-3 item 15 as built — the exact member names of a gpuVerifications entry, read at source -->

### 3.5 The compile-flag record

`compileFlags` and `engineFlags` digest the argument vectors the compiler received for each translation unit
of the recorded targets, taken from the build's own `compile_commands.json`:

1. Each command is split by the platform's own rules (the Microsoft C runtime's on Windows, POSIX shell rules
   elsewhere).
2. The compiler path, the output arguments and the source argument are dropped.
3. **Arguments proven, on that compiler family, unable to change code are dropped**, and every other argument
   is kept. The list is per family because the evidence is. For example `/W3` and `/Zi` are dropped on MSVC
   and `-g` on GCC; clang-cl keeps `/Zi` and `/Z7`, which change its code generation.
4. An include option written as two arguments becomes one.
5. Every location the build does not choose becomes a token — `<src>`, `<build>` or `<engine>` — so the same
   configuration gives the same record from any directory. A kept argument that still carries an absolute path
   is listed beside the record, and a cell whose record lists one is not certified.

So **a build with any flag beyond its cell's recorded set is uncertified**, and the build refuses to configure
while `CL`, `_CL_` or `CCC_OVERRIDE_OPTIONS` is set (`SEMB_BUILD_AMBIENT_COMPILER_INPUT`; the engine pin tool
refuses them as `SEMB_PIN_AMBIENT_COMPILER_INPUT`), because each injects arguments no compile line shows.

## 4. `certification-identity.json`

The certification identity, at `docs/certification-identity.json`. **The certification epoch digests this
file, not the list:** a certified cell's `certification_epoch` is the SHA-256 of this file's exact bytes.

```json
{
  "schemaVersion": 1,
  "product": "superembedder",
  "line": 1,
  "enginePin": {
    "tag": "{{ENGINE_PIN_TAG}}",
    "commit": "{{ENGINE_PIN_COMMIT}}",
    "engine_tree_sha": "{{ENGINE_TREE_SHA}}"
  },
  "proofCorpus": {
    "path": "tests/fixtures/c12b/corpus-239.jsonl",
    "sha256": "{{PROOF_CORPUS_SHA256}}",
    "rows": 239,
    "corpusDigest": "{{PROOF_CORPUS_DIGEST}}",
    "tokenIdDigest": "{{PROOF_CORPUS_TOKEN_ID_DIGEST}}"
  }
}
```
<!-- filled by: the v1.8.0 pin step (enginePin) and the identity writer tool at that pin (proofCorpus digests);
     copy the committed file's values verbatim -->

**Canonical form.** ASCII; LF line endings; two-space indentation; members in exactly the order above; one
trailing LF. The file is written only by the repository's writer tool, and the release check regenerates it
from the tree and refuses a file that differs by a byte.

**What is deliberately absent**: a release label, the list's bytes, cells, proofs, run ids, dates, hosts and
evidence paths. None of them may move the epoch.

**`line`** increases when a cell is withdrawn, or a proof is withdrawn or corrected. A new engine pin or a new
proof corpus also changes the file. Each of those starts a new certification line, and banks baked on the old
line must be re-baked.

**The extension rule.** A later list on the same line may **add** cells and their pairwise proofs, and the
epoch stays. It may not remove a cell or rewrite a published one under an unchanged identity file; the release
check refuses a list that does.

## 5. The engine build

### 5.1 `sslm_build_identity`

Every engine SuperEmbedder links carries a function, `sslm_build_identity`, returning the address of a
constant object that records how that engine was compiled. The engine pin tool supplies it when the engine
release does not. Its members:

| Member | Meaning |
|---|---|
| `struct_size`, `schema_version` | Size and version of the object |
| compiler and standard-library macro values | The predefined macros the engine's kernels were compiled under |
| `forced_tier` | The tier the engine was forced to, or none for auto dispatch |
| `compiled_isa` | The instruction-set extensions the compile enabled |
| `required_isa` | The extensions the host must have to run the engine |
| `build_record` | The build record (§5.2) |

### 5.2 The build record

`sslm-build-record-v1:` followed by the lowercase hex SHA-256 of the canonical JSON of

```text
{schema, tag, commit, clean, compiler {id, version, frontend}, flagsSha}
```

where `flagsSha` is the engine's compile-flag record digest (§3.5, the `engineFlags` value). Every input is
content, so one configuration gives one record from any directory and any difference gives another. The pin
tool writes it into the engine install's `provenance.json` as `engine_build.buildRecord`, beside the engine's
compiler, `toolchain`, `stdlib`, `dispatch`, `flags`, `flagsSha` and the installed library's SHA-256. Configure
compiles it into the product, and the bake manifest records what the linked engine reported as
`engine_build_record` (§2.3).

### 5.3 The check at open

Before an encoder or a bank opens — before any artifact byte is read and before any engine code runs — the
library checks the engine it is linked against, in this order:

1. the identity object is unreadable, or too small → `SEMB_ENGINE_BUILD_UNRECORDED`;
2. `required_isa` holds an extension this host cannot run → `SEMB_CPU_TIER_UNSUPPORTED`;
3. a compiler or standard-library macro value differs from the product's own → `SEMB_ENGINE_TOOLCHAIN_MISMATCH`;
4. `build_record` is empty → `SEMB_ENGINE_BUILD_UNRECORDED`;
5. `build_record` differs from the one configure verified → `SEMB_ENGINE_LINK_MISMATCH`.

The host check comes first so that an engine that would fault is refused rather than run. An application
must therefore link the engine the installed library was configured against; any other is refused at open.

## 6. What the checks do not catch

These are outside the threat model, which is accidental and stale mismatch
([DETERMINISM.md](DETERMINISM.md#the-threat-model)):

- **Fabricated evidence.** A list whose evidence files were fabricated passes every structural check.
- **A forged toolchain.** A compiler binary that is not the compiler it reports — a wrapper that changes the
  arguments it passes on, for example — records the reported compiler's identity.
- **A forged record or identity object** in an engine library.
- **Code the engine runs before `main`.** Static initializers in the engine's C interface run before any check.
  Only an engine compiled with a global `/arch` above the host's tier can fault there, and no cell certifies one.
- **Two engine libraries on one link line.** An application that names two can take the identity object from
  one and kernels from the other. Link one engine.
- **Symbol interposition on a shared, standalone engine on Linux**, where the dynamic linker binds each symbol
  separately. 1.0 never loads the engine that way: it is linked privately and statically into SuperEmbedder's
  shared library on every platform.
- **A static link of SuperEmbedder into your application** keeps whichever copy of shared inline and template
  code your link keeps. It is certified only where every translation unit of yours that instantiates a shared
  function is compiled with the cell's options. The installed library is shared for this reason.
