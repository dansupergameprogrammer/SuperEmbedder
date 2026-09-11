// tests/semb_query_abi_contract.h -- TE-194 (U1 slice 5): the test author's
// concrete pin of the query path's four frozen `semb_*` verbs, against the
// signatures `Claude/Plans/SuperEmbedder_Plan.md` sec 3.1 states ("The C
// ABI, frozen -- enumerated HERE and nowhere else", D-SLM4646):
//
//   semb_status semb_query_open(semb_encoder enc, semb_bank bank, semb_query* out)
//   semb_status semb_query_encode(semb_query q, const char* utf8, size_t utf8_len,
//                                 float* out_vector, size_t out_capacity_bytes,
//                                 size_t* out_required_bytes)
//   semb_status semb_query_close(semb_query q)
//   semb_status semb_fingerprint_of(semb_encoder enc, semb_fingerprint* out)
//
// Like `tests/semb_bank_abi_contract.h` (TE-163) this is the suite's OWN
// header, not a copy of a product header -- none of the four verbs, nor the
// `semb_query` type, exists anywhere in `superembedder` at this branch's own
// base `21b1735` (confirmed: `git grep -n "semb_query_open\|semb_query_encode\|
// semb_query_close\|semb_fingerprint_of\|semb_query_opaque" src/ include/`
// returns nothing), so every test that includes this header and calls any of
// the four fails to LINK until the builder's round adds them
// (`Claude/Bach/briefs/te194-slice5-red.md`: "Red at 21b1735: undefined at
// link"). A TU that needs this header together with the five raw-slice verbs
// and the bank pair includes `semb_public_abi_contract.h` FIRST, then
// `semb_bank_abi_contract.h`, then this header -- exactly the layering
// `semb_bank_abi_contract.h`'s own header comment already establishes for
// itself relative to `semb_public_abi_contract.h`.
//
// THE HANDLE (sec 3.1 item 5; "one thread at a time. Concurrent use returns
// SEMB_HANDLE_IN_USE"): opaque, library-owned, not copyable, released only
// by `semb_query_close`; a double close returns SEMB_INVALID_HANDLE. A
// distinct opaque tag from semb_encoder/semb_bank -- the three handle kinds
// are never interchangeable, and nothing in this contract declares a cast
// between them.
//
// THE CHECKED PATH IS A TYPE, NOT AN ARGUMENT (sec 3.1): `semb_query_open`
// compares the encoder's five derived fields against the bank's OWN
// expected fingerprint (the value `semb_bank_open` already read out of the
// manifest, per `semb_bank_abi_contract.h`) and refuses here, or hands back
// a handle; `semb_query_encode` cannot emit against an uncompared bank
// because the handle does not exist unless the comparison passed. The
// refusal precedence's own field-mismatch outcome is `SEMB_FINGERPRINT_MISMATCH`
// (sec 3.3's C8/C17 cells; this suite's own te194_query_test.cpp cells 1/2).
//
// `semb_query_encode` -- "the shipping per-query call" (sec 3.1): applies
// the compiled-in `query_prefix_bytes` literal (sec 2.1, sec 3.3's
// `template_sha256` field) at whatever join/order/special-token/truncation-
// ordering rule the implementation performs (sec 3.3's entry-point crossing
// table); this suite's own cell computes the crossing-table's rule
// independently (join, order, special tokens, truncation ordering) and
// asserts the emitted vector equals `semb_encode`'s own output on the
// explicitly-prefixed text -- never a re-derivation of the implementation's
// own steps (Curie.md's own "grounded in the statistic's definition, not a
// recode of the implementation's steps").
//
// CONCURRENCY AND CROSS-HANDLE LIFETIME (sec 3.1, D-SLM4647, D-SLM4664):
//   - `semb_query`: one thread at a time; concurrent use -> SEMB_HANDLE_IN_USE,
//     detected by an in-use flag, freeing nothing.
//   - `semb_bank`: tracks a reference count of live `semb_query` handles
//     opened against it. `semb_query_open` increments it on every successful
//     open; `semb_query_close` decrements it; `semb_bank_close` while that
//     count is nonzero -> SEMB_BANK_IN_USE, freeing nothing -- the caller
//     closes its outstanding query handles and retries.
//   - Open and close are never concurrent with any other call on the same
//     handle.
//
// REFUSAL SHAPE (sec 3.1's frozen-property table, applied to this verb set;
// sec 8 C8's fingerprint-mismatch-at-open cell; sec 8 C26's teardown-during-
// flight races):
//   enc == NULL || bank == NULL || out == NULL (open)         -> SEMB_NULL_ARGUMENT
//   enc or bank names no live handle                          -> SEMB_INVALID_HANDLE
//   the encoder's five derived fields disagree with the
//     bank's own expected fingerprint                          -> SEMB_FINGERPRINT_MISMATCH, *out == NULL
//   a second concurrent semb_query_open/close/encode call on
//     the same live semb_query handle                          -> SEMB_HANDLE_IN_USE, nothing freed
//   semb_bank_close with a live query handle open against it   -> SEMB_BANK_IN_USE, nothing freed
//   q == NULL (encode/close)                                   -> SEMB_NULL_ARGUMENT
//   q names no live handle                                     -> SEMB_INVALID_HANDLE
//   out_capacity_bytes too small (encode)                      -> SEMB_BUFFER_TOO_SMALL, *out_required_bytes written, out_vector untouched
//   every refused open writes NULL to non-NULL `out`, mirroring
//     sec 3.1's own "every refused open writes NULL to non-NULL out" rule
#ifndef SEMB_QUERY_ABI_CONTRACT_H
#define SEMB_QUERY_ABI_CONTRACT_H

#include <cstddef>

// sec 3.1 item 5: library-owned, opaque, not copyable, released only by
// semb_query_close; a double close returns SEMB_INVALID_HANDLE. A distinct
// opaque tag from semb_encoder_opaque/semb_bank_opaque.
struct semb_query_opaque;
typedef struct semb_query_opaque* semb_query;

static_assert(sizeof(semb_query) == sizeof(void*), "semb_query is an opaque pointer handle");

extern "C" {

// sec 3.1: compares enc's five derived fingerprint fields against bank's
// OWN expected fingerprint (read at semb_bank_open, never re-read from
// disk here -- TE-191's F4 accessor, bank_internal_abi.h, is what makes
// this claim checkable test-side); refuses here with
// SEMB_FINGERPRINT_MISMATCH or hands back a live handle. On success,
// increments bank's own live-query-handle reference count (D-SLM4664).
semb_status semb_query_open(semb_encoder enc, semb_bank bank, semb_query* out);

// sec 3.1: "the shipping per-query call." Applies query_prefix_bytes at
// the entry point's own composition (sec 3.3's crossing table, W-Q's own
// leg); out_capacity_bytes too small -> SEMB_BUFFER_TOO_SMALL with
// *out_required_bytes written and out_vector untouched (sec 3.1 property 3,
// applied here as it is to semb_encode/semb_encode_batch).
semb_status semb_query_encode(semb_query q, const char* utf8, size_t utf8_len,
                              float* out_vector, size_t out_capacity_bytes,
                              size_t* out_required_bytes);

// Releases the handle; decrements its bank's own live-query-handle
// reference count (D-SLM4664). A call in flight on this handle ->
// SEMB_HANDLE_IN_USE, nothing freed (sec 3.1's close-during-flight policy,
// D-SLM4647, applied here as it already is to semb_encoder_close).
semb_status semb_query_close(semb_query q);

// sec 3.1: "reads the handle's own fingerprint, for a caller doing its own
// comparison." Never a source for a derived field (sec 3.3's
// producer-identity rule); this suite's own C8 well-formed-value leg
// (te194_query_test.cpp cell 2) is what this accessor exists to serve.
semb_status semb_fingerprint_of(semb_encoder enc, semb_fingerprint* out);

}  // extern "C"

#endif  // SEMB_QUERY_ABI_CONTRACT_H
