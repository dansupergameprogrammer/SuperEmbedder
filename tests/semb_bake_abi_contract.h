// tests/semb_bake_abi_contract.h -- TE-163 (U1 slice 4): the test author's
// own specification of the bake primitive Slice 4 needs so a bank can be
// OPENED at all, per the conductor's own fixed point for this round ("The
// bake primitive is internal, not a verb. The plan's twelve verbs are
// frozen (D-SLM4646) and `semb bake` is Slice 6's CLI. A bank must
// nevertheless be written at this slice for anything to be opened.
// Specify the writer test-side, the way `tests/semb_wb_witness_abi_contract.h`
// specified `semb_wb_digest` before the product had it... The builder owns
// the mechanism, the cell owns the claim.").
//
// NOT ONE OF THE FROZEN TWELVE VERBS (sec 3.1, D-SLM4646). Slice 6's own
// `semb bake <corpus> --out <name>` CLI wraps this primitive; this slice
// needs it only so `semb_bank_open`'s own red suite has a well-formed
// triple to open (and mutate copies of) before Slice 6 exists. Confirmed
// absent: `git grep -n semb_bake_to_path src/ include/` at this branch's
// own base `7af22da` returns nothing -- every test that includes this
// header and calls it fails to LINK until the builder's round adds it.
//
// THE SHAPE, mirroring `semb_wb_witness_abi_contract.h`'s own "specify a
// handle-scoped internal entry, refuse like the rest of the surface"
// precedent:
//
//   semb_status semb_bake_to_path(semb_encoder enc, const semb_document* docs,
//                                  size_t n, const char* path_stem,
//                                  size_t path_stem_len)
//
// WHAT IT WRITES, ATOMICALLY, on SEMB_OK ONLY: exactly three files at
// `<path_stem>.wvbank.json`, `<path_stem>.wvbank.bin`, `<path_stem>.semb.json`
// (sec 3.4's own "Bank: SuperFAISS's .wvbank.json + .wvbank.bin, exactly
// per FORMAT.md sec 1... Manifest (SuperEmbedder's own): <name>.semb.json").
// ATOMICALLY means: on any non-SEMB_OK return, none of the three files
// exists at `path_stem`'s three sibling paths -- not even a partial one --
// whether the refusal fires before any write begins (validation) or after
// some bytes were staged (an engine refusal mid-batch). This round's own
// cell drives one refusal per TE-96 sec 4.2 class through this primitive
// and asserts all three sibling paths remain absent (mkdir'd into an empty
// scratch directory per case, so "absent" is checkable by a directory
// listing rather than a stat against a path that might pre-exist from a
// prior case).
//
// THE THREE FILES' OWN CONTENT:
//
//   <path_stem>.wvbank.json / .wvbank.bin -- FORMAT.md sec 1's interchange
//   pair, byte for byte: `schemaVersion` 1, `dims` = the handle's own
//   `semb_encoder_dims`, `count` = n, `metric` "cosine", `dtype` "float32",
//   `ids` exactly `count` entries in row order (`ids[i]` = `docs[i].id`,
//   TE-96 sec 4.2's own row-order association, "row i <-> docs[i]"), no
//   `channels` table, no SuperEmbedder-specific header field (sec 3.4: "No
//   SuperEmbedder-specific header fields; none are specified as
//   tolerated"). The `.bin` payload is exactly `count * dims * 4`
//   little-endian float32 bytes, row-major, no padding, EQUAL BIT FOR BIT
//   to what a fresh `semb_encode_batch(enc, docs, n, ...)` call on the SAME
//   handle would write to `out_rows` for the same documents in the same
//   order -- this primitive computes the rows through that exact same
//   call (or an internally identical composition; the cell compares
//   against `semb_encode_batch`'s OWN output, not against this primitive's
//   own internal steps, so either implementation choice is graded the
//   same way).
//
//   <path_stem>.semb.json -- sec 3.4's manifest, every field present, none
//   omitted (a field whose producing mechanism lands at a later slice
//   carries the same provisional sentinel the fingerprint already carries
//   for it -- present, never omitted, never fabricated):
//     encoder_fingerprint          -- hex, the untagged SHA-256 over the five
//                                      clear components; distinct from the
//                                      tagged ABI value semb_encode and
//                                      semb_fingerprint_of return
//     model_sha, tokenizer_sha,
//       template_sha256, witness_sha,
//       certification_epoch        -- the five components IN CLEAR (sec 3.4:
//                                      "encoder_fingerprint and all five
//                                      components in clear")
//     certified_builds_path         -- relative path to certified-builds.json
//     provenance (marked, NOT hashed):
//       object_code_sha, engine_object_code_sha, semb_source_sha,
//       engine_tree_sha, engine_path_sha, engine_chunk_budget,
//       witness metadata { corpus_digest, wa_digest, wb_digest (written
//         SEPARATELY, sec 3.4: "W-A and W-B written separately, which is a
//         bisect that names its own suspect"), cpu_tier }
//     labels (each `label:`-prefixed, marked as labels, sec 3.4's table):
//       label:ps_version, label:engine_path_id,
//       label:superslm_tag_commit, label:semb_version
//     count, dims, row_digest, corpus_digest, machine_tier,
//       per_row_token_counts (length `count`, row order)
//   Every field this primitive writes into the manifest is computed from
//   the SAME artifacts/values the pair itself was baked from in this ONE
//   process -- "never a source" (sec 3.4): nothing this primitive writes
//   is read back into any later derivation, and this round's own cell
//   proves it by editing a scratch COPY of an emitted manifest's own
//   fields and confirming a re-bake's freshly-derived values are
//   unmoved (the manifest is compared against, never read from, by
//   anything under this round's own writable scope).
//
// THE C34 (e)/(h) SELF-CHECK, AT BAKE (sec 3.4's label-check table; sec 8
// C34; this round's own conductor fixed point): before writing
// `label:engine_path_id`, this primitive compares it against the linked
// adapter TU's own compiled-in `SEMB_ADAPTER_SELF_ID` constant and refuses
// SEMB_ADAPTER_ID_MISMATCH (writing nothing) on disagreement; before
// writing `label:ps_version`, it compares it against the pooling
// epilogue's own compiled-in `SEMB_PS_VERSION_LABEL` constant and refuses
// SEMB_PS_VERSION_LABEL_MISMATCH (writing nothing) on disagreement. In
// ordinary operation the label written and the compiled-in constant it is
// checked against are the SAME source of truth, so this refusal cannot
// fire on any build this suite can configure by itself -- `tests/
// te163_c34_manifest_honesty_check.py` proves the check is alive (not a
// dead comparison that always agrees with itself) by editing ONE of the
// two constants in a scratch clone's source and rebuilding, per this
// round's own guard-vitality discipline (sec 8 C34, dim 11: "these are
// guard-vitality constructions in C17's shape at smaller scale").
#ifndef SEMB_BAKE_ABI_CONTRACT_H
#define SEMB_BAKE_ABI_CONTRACT_H

#include <cstddef>

extern "C" {

// Bakes `n` documents through `enc` (a live, open handle) and writes the
// bank pair + manifest sidecar to the three sibling paths named by
// `path_stem` (sized UTF-8 span, `path_stem_len` bytes, never
// NUL-terminated -- sec 3.1 property 2 applied to a path, the same
// convention `semb_config`'s own path members already use). Preflight and
// per-document validation are the SAME precedence TE-96 sec 4.2 pins for
// `semb_encode_batch` (this primitive computes the rows through that exact
// validated path) -- every refusal `semb_encode_batch` itself can produce
// propagates unchanged and nothing is written; the two C34 self-check
// refusals above are additional, checked once the rows are computed and
// before any of the three files is written.
semb_status semb_bake_to_path(semb_encoder enc, const semb_document* docs, size_t n,
                               const char* path_stem, size_t path_stem_len);

}  // extern "C"

#endif  // SEMB_BAKE_ABI_CONTRACT_H
