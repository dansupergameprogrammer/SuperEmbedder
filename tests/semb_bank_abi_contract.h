// tests/semb_bank_abi_contract.h -- TE-163 (U1 slice 4): the test author's
// concrete pin of `semb_bank_open`/`semb_bank_close` and the `semb_bank`
// handle, against the frozen signatures `Claude/Plans/SuperEmbedder_Plan.md`
// sec 3.1 states (D-SLM4646, "The C ABI, frozen -- enumerated HERE and
// nowhere else"):
//
//   semb_status semb_bank_open(const char* path, size_t path_len, semb_bank* out)
//   semb_status semb_bank_close(semb_bank bank)
//
// Like `tests/semb_batch_abi_contract.h` and `tests/semb_wb_witness_abi_contract.h`
// this is the suite's OWN header, not a copy of a product header -- neither
// verb, nor the `semb_bank` type, exists anywhere in `superembedder` yet
// (confirmed: `git grep -n "semb_bank_open\|semb_bank_close\|semb_bank"
// src/ include/` at this branch's own base `7af22da` returns nothing), so
// every test that includes this header and calls either verb fails to LINK
// until the builder's round adds it. A TU that needs both this header and
// the five raw-slice verbs includes `semb_public_abi_contract.h` FIRST,
// exactly as existing TUs already combine that header with
// `semb_batch_abi_contract.h` (each contract header owns only the symbols
// IT adds; nothing here redeclares semb_encoder_open/_close/_dims/
// semb_encode/semb_encode_batch/semb_status_name or the semb_status enum).
//
// THE HANDLE (sec 3.1 item 5, sec 3.1's "the semb_bank handle" paragraph):
// opaque, library-owned, not copyable, released only by `semb_bank_close`;
// read-only after open; concurrent use safe (sec 3.1, D-SLM4647: "semb_bank
// -- read-only after open; concurrent use is safe"). `semb_bank_open` OWNS
// the bank's expected fingerprint, read out of the manifest's own
// `encoder_fingerprint` field -- never a source for any DERIVED field, per
// sec 3.3/3.4's "never a source" rule; this slice has no cell that reads it
// back into a derivation, only cells that assert the manifest's OWN
// internal fields stay unmoved after a caller edits a scratch copy of one.
//
// PATH ARGUMENT SHAPE: a sized UTF-8 span, never NUL-terminated (sec 3.1
// property 2, "text inputs are sized UTF-8 spans... never NUL-terminated"),
// applied here to a path exactly as `semb_config`'s own `model_path`/
// `tokenizer_path` members already are. `semb_bank_open` resolves the three
// sibling files -- `<path-without-suffix>.wvbank.json`,
// `<path-without-suffix>.wvbank.bin`, `<path-without-suffix>.semb.json` --
// from ONE path argument naming the shared stem, the same "one path names
// the pair-plus-sidecar" shape `tests/semb_bake_abi_contract.h`'s own
// `semb_bake_to_path` writes under.
//
// REFUSAL SHAPE, from sec 3.1's own frozen-property table applied to this
// verb pair plus sec 8 C18/C34's own named statuses (this suite's own pin;
// the builder's mechanism satisfies it, never a hardcoded enumeration of
// every FORMAT.md importer obligation, most of which carry no status name
// this round and are asserted as a refusal by VALUE rather than by name --
// see this round's own casebook for the routed finding):
//   path == NULL && path_len > 0, or out == NULL           -> SEMB_NULL_ARGUMENT
//   (NULL, 0) path (empty span, whatever path_len implies)  -> SEMB_ARTIFACT_UNREADABLE
//   any of the three sibling files missing or unreadable    -> SEMB_ARTIFACT_UNREADABLE
//   unknown .wvbank.json schemaVersion                      -> SEMB_MANIFEST_SCHEMA_UNSUPPORTED
//   .wvbank.bin length disagreeing with the header's
//     count * dims * 4                                      -> SEMB_BANK_SIZE_MISMATCH
//   the manifest's own artifact SHA(s) disagreeing with a
//     recomputation over the pair's own bytes                -> SEMB_ARTIFACT_SHA_MISMATCH
//   the manifest's encoder_fingerprint disagreeing with the
//     SHA-256 of its own five components in clear (sec 3.3's
//     composition; cell 3, this round's own resolved reading) -> SEMB_FINGERPRINT_MISMATCH
//   every refusal: *out == NULL (when out is non-NULL,
//     mirroring sec 3.1's open precedence table), nothing
//     leaked (this suite's own open/close loop under the
//     aligned leak instrument, reused from TE-159 item 5)
// Every refused open writes NULL to non-NULL `out` (sec 3.1's own "every
// refused open writes NULL to non-NULL out" rule, applied here as it is to
// `semb_encoder_open`).
//
// `semb_bank_close`: NULL -> SEMB_NULL_ARGUMENT; not a live cookie ->
// SEMB_INVALID_HANDLE (a non-NULL value naming no live handle -- sec 3.1
// property 7's own NULL-vs-INVALID_HANDLE distinction, applied here);
// a bank with a nonzero live-`semb_query`-handle reference count ->
// SEMB_BANK_IN_USE, freeing nothing (D-SLM4664) -- NOT this slice's own
// cell (no `semb_query_open` exists yet to raise that count; Slice 5's).
// Close of a never-opened or already-closed handle -> SEMB_INVALID_HANDLE,
// the double-close rule sec 3.1 property 5 already states for every handle
// kind, applied here.
#ifndef SEMB_BANK_ABI_CONTRACT_H
#define SEMB_BANK_ABI_CONTRACT_H

#include <cstddef>

// sec 3.1 item 5: library-owned, opaque, not copyable, released only by
// semb_bank_close; a double close returns SEMB_INVALID_HANDLE. A distinct
// opaque tag from semb_encoder_opaque/semb_query_opaque -- the three handle
// kinds are never interchangeable, and nothing in this contract declares a
// cast between them.
struct semb_bank_opaque;
typedef struct semb_bank_opaque* semb_bank;

static_assert(sizeof(semb_bank) == sizeof(void*), "semb_bank is an opaque pointer handle");

extern "C" {

// sec 3.1: opens and validates a `.wvbank`/`.semb.json` triple named by the
// shared stem `path` (sized UTF-8 span, `path_len` bytes, never
// NUL-terminated); owns the bank's own expected fingerprint, read from the
// manifest. `*out` is set to a live handle only on SEMB_OK; every refusal
// leaves `*out == NULL` (when `out` is non-NULL) and closes/frees anything
// it opened along the way -- no partial handle, no leaked file descriptor
// or buffer on any refusal path (this suite's own open/close loop under
// the aligned leak instrument is the executed proof, not merely the claim).
semb_status semb_bank_open(const char* path, size_t path_len, semb_bank* out);

// Releases the handle. Read-only after open and concurrent-use-safe means
// closing is the only call that ever mutates a semb_bank's own registry
// entry; sec 3.1's "open and close are never concurrent with any other
// call on the same handle" rule applies here exactly as it does to
// semb_encoder.
semb_status semb_bank_close(semb_bank bank);

}  // extern "C"

#endif  // SEMB_BANK_ABI_CONTRACT_H
