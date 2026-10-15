# Changelog

All notable changes to SuperEmbedder are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Changes to emitted vector bytes are
always called out. The fingerprint covers the model, tokenizer, composition
literals, executed witnesses and certification epoch; a change to any of these
changes it and requires banks to be re-baked. A code change outside what the
witnesses execute can change output without moving the fingerprint. The certified
set and `semb verify` against the reference bank check for such changes on the
certification corpus.
<!-- REL-4: verify against the committed docs/certified-builds.json and docs/certification/reference-bank/ before tagging -->

## [Unreleased]

## [1.0.0] - {{RELEASE_DATE}}
<!-- filled by: REL-4 step 7 (the tag date) -->

The first release, pinned to SuperSLM `1.8.0`. Release notes: [docs/releases/1.0.0.md](docs/releases/1.0.0.md).

### Added

- A C interface, `superembedder/semb.h`: open an encoder from files
  (`semb_encoder_open`) or from bytes in memory (`semb_encoder_open_memory`);
  encode a document (`semb_encode`), a batch (`semb_encode_batch`) or a query
  (`semb_encode_query`); open a baked bank (`semb_bank_open`) and encode
  queries against it (`semb_query_open`, `semb_query_encode`); read the
  encoder fingerprint (`semb_fingerprint_of`) and status names
  (`semb_status_name`). No call lets a C++ exception escape.
- The `semb` tool: `bake`, `query` (with `--stdin`, `--hex`, `--raw` and
  the diagnostic `--top k`), `verify`, `inspect` and `--version`.
- The PS-N pooling scheme over Qwen3-Embedding-0.6B: the end token's final
  hidden state, each element's `float32` constructed in integer code
  ([docs/POOLING.md](docs/POOLING.md)).
- The encoder fingerprint over the model, the tokenizer, the composition
  literals, an executed witness and the certification epoch, recorded in
  every bank and checked at every query open.
- The certified set: 7 builds, 11 cells, with every pair's proof published in
  `docs/certified-builds.json`; the certification identity in
  `docs/certification-identity.json`; each encoder open decides its own
  build's cell ([docs/DETERMINISM.md](docs/DETERMINISM.md)).
  <!-- REL-4: verify against the committed docs/certified-builds.json and docs/certification/reference-bank/ before tagging -->
- A check at every encoder and bank open that the linked engine is the one the
  build was configured against.
- A GPU path on Windows (Direct3D 12), built with `SEMB_BUILD_GPU=ON` and
  selected with `semb_config.device` or `--device gpu`. Its vectors are the
  CPU's bytes; every GPU open re-proves that against the CPU.
- An installed CMake package, `find_package(superembedder 1.0 CONFIG)`, with
  a shared library exporting only the `semb_*` functions.
- The model and tokenizer as release downloads with their SHA-256.
- A reference bank in `docs/certification/reference-bank/` for checking a
  build with `semb verify`.
  <!-- REL-4: verify against the committed docs/certified-builds.json and docs/certification/reference-bank/ before tagging -->

### Upgrading from a pre-release build

Banks baked by any pre-release build carry a different encoder fingerprint and
are refused (`SEMB_FINGERPRINT_MISMATCH`). Re-bake them with 1.0.0.

[Unreleased]: https://github.com/dansupergameprogrammer/SuperEmbedder/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/dansupergameprogrammer/SuperEmbedder/releases/tag/v1.0.0
