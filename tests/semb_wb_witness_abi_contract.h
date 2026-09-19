// tests/semb_wb_witness_abi_contract.h -- TE-145 (U1 slice 2), AMENDED
// TE-151 (fix round): the test author's own pin of a diagnostic accessor
// for W-B's corpus digest, in the same PURPOSE `include/superembedder/
// witness_abi.h` already serves for W-A (`void semb_wa_digest(uint8_t
// out_digest[32]);`, TE-78, already compiled into the library and already
// called by both `src/superembedder/encoder.cpp` and
// `src/witness/witness_main.cpp`) -- but NOT the same SHAPE, and the
// reason is stated here rather than assumed (routed at TE-145 sec 13 as
// this seat's own item to close; TE-151 item 1).
//
// WHY A BARE ACCESSOR IS WRONG FOR W-B, WHERE IT IS RIGHT FOR W-A. W-A is
// model-independent: it drives the arithmetic primitives over a fixed
// synthetic population and a compiled-in splitmix64 seed, so a call with
// no argument is well-defined -- there is nothing for it to read. W-B is
// NOT: `Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b defines it as the
// seam serialisation of the sixteen committed documents ENCODED ON THE
// ARTIFACT `model_sha` NAMES, tokenized through THAT ARTIFACT'S OWN
// tokenizer, with THAT ARTIFACT'S OWN resolved end-token id appended --
// and sec 3.1 places its derivation inside `semb_encoder_open`, from the
// bytes that handle read once (sec 3.3's one-read rule). A bare
// `void semb_wb_digest(uint8_t[32])` has no model, no tokenizer and no
// end-token id to compute from; the only ways to give it one without a
// handle argument are exactly the constructions sec 3.3's producer-
// identity rule and sec 4.4b's D-SLM3978 no-cache rule forbid: a
// compiled-in artifact path, a process-global "last opened handle", or a
// second read of a file another field was derived from. This header's
// first version (TE-145) specified the W-A shape verbatim and missed
// this; this round amends it to be HANDLE-SCOPED instead.
//
// THE SHAPE: `semb_status semb_wb_digest(semb_encoder enc, uint8_t
// out_digest[32])`, refusing like the rest of the surface rather than
// inventing a construction sec 3.3 forbids:
//   - `enc == NULL`               -> SEMB_NULL_ARGUMENT
//   - `enc` names no live handle  -> SEMB_INVALID_HANDLE
//   - `out_digest == NULL`        -> SEMB_NULL_ARGUMENT
//   - else: writes the 32 bytes and returns SEMB_OK
//
// STATED AS FACT, THE BUILDER'S OWN OBLIGATION AND THIS HEADER'S OWN
// CLAIM: the same handle-derived value this accessor returns for a given
// live `enc` IS the value `ComputeManifestFingerprintComponents`
// (`src/superembedder/encoder.cpp`) hashes into that handle's own
// `witness_sha`. Whether the builder recomputes it fresh on every call or returns
// the value the handle already derived at `semb_encoder_open` is the
// builder's own mechanism, not this header's concern (D-SLM3978's no-
// cache rule binds the FINGERPRINT derivation, not how many times this
// diagnostic accessor happens to be called against an already-open
// handle) -- what the cells below pin is only the properties any correct
// mechanism must have.
//
// Per this seat's own brief ("where a cell needs a library entry the
// product does not yet expose, specify it in a test-side contract header
// and name it in the handoff -- the builder owns the mechanism, the cell
// owns the claim"): `semb_wb_digest` is not defined anywhere in
// `superembedder` yet under EITHER shape (confirmed: `git grep -n
// semb_wb_digest src/ include/` at this branch's own tip returns
// nothing). Every test that includes this header and calls it fails to
// LINK until the builder's round adds it, wiring it to drive
// `semb_encode_document_for_witness` + `semb_seam_serialize_document`
// (both ALREADY built, TE-63) over the handle's own sixteen committed W-B
// documents (`tests/fixtures/wb/wb-corpus.jsonl`, TE-145) exactly the way
// `semb_wa_digest` already drives W-A's own population, and to fold this
// same value into `witness_sha` (built at TE-147; the fingerprint's one
// derivation is `ComputeManifestFingerprintComponents` since U1 Slice 7).
//
// SYMBOLS THIS HEADER USES BUT DOES NOT DECLARE: `semb_status` and
// `semb_encoder`, exactly the convention `tests/semb_batch_abi_contract.h`
// already establishes ("nothing here redeclares semb_encoder_open/
// _close/_dims/semb_encode/semb_status_name or the semb_status enum") --
// a TU that includes this header includes `tests/semb_public_abi_contract.h`
// FIRST, which owns both types.
#ifndef SEMB_WB_WITNESS_ABI_CONTRACT_H
#define SEMB_WB_WITNESS_ABI_CONTRACT_H

#include <cstdint>

extern "C" {

// Writes W-B's own 32-byte digest for the artifacts `enc` was opened on --
// SHA-256 over the committed sixteen-document corpus's seam serialisation,
// `u64(document_count)` first, then each document's own
// `semb_seam_serialize_document` stream in committed order
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b's own per-document
// layout: "across the corpus, u64(document_count) then each document's
// stream in committed order"), each document tokenized through `enc`'s
// OWN tokenizer with `enc`'s OWN resolved end-token id appended.
//
//   enc == NULL                  -> SEMB_NULL_ARGUMENT, out_digest untouched
//   enc names no live handle     -> SEMB_INVALID_HANDLE, out_digest untouched
//   out_digest == NULL           -> SEMB_NULL_ARGUMENT
//   else                         -> the 32 bytes written, SEMB_OK
semb_status semb_wb_digest(semb_encoder enc, uint8_t out_digest[32]);

}  // extern "C"

#endif  // SEMB_WB_WITNESS_ABI_CONTRACT_H
