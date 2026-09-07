// tests/semb_wb_witness_abi_contract.h -- TE-145 (U1 slice 2): the test
// author's own pin of a diagnostic accessor for W-B's corpus digest, in the
// same shape `include/superembedder/witness_abi.h` already exposes for W-A
// (`void semb_wa_digest(uint8_t out_digest[32]);`, TE-78, already compiled
// into the library and already called by both `src/superembedder/encoder.cpp`
// and `src/witness/witness_main.cpp`).
//
// WHY THIS ACCESSOR IS NEEDED, STATED RATHER THAN ASSUMED. `witness_sha`
// (one of `encoder_fingerprint`'s five fields) is SHA-256 over
// `W-A digest || W-B digest || W-Q digest` (`Claude/Plans/SuperEmbedder_Plan.md`
// sec 4.4b) and is itself only reachable through the OPAQUE, top-level
// `encoder_fingerprint` a caller receives from `semb_encode`/`semb_encode_batch`
// -- there is no public accessor that decomposes a fingerprint back into its
// five fields, let alone `witness_sha`'s own three sub-components. A cell
// that wants to assert "wb_sha is the real corpus witness, not
// `kWbPendingSentinel`" therefore needs SOME way to observe W-B's own 32-byte
// value directly, exactly the problem W-A already solved for itself with
// `semb_wa_digest`. This header specifies the identical shape for W-B: a
// diagnostic, non-ABI-frozen C symbol (sec 3.1's twelve-verb freeze,
// D-SLM4646, does not cover it, the same way it does not cover
// `semb_wa_digest`, `semb_seam_serialize_document` or
// `semb_encode_document_for_witness` -- none of the four is in the frozen
// twelve) that the WITNESS EXECUTABLE and `ComputeProvisionalFingerprint`
// (`src/superembedder/encoder.cpp`) both call, so a test calling it observes
// the SAME value the library actually hashed into `witness_sha`, not a
// second, independently-implemented copy of the corpus-witness computation
// that could silently drift from what `semb_encoder_open` really does.
//
// Per this seat's own brief ("where a cell needs a library entry the
// product does not yet expose, specify it in a test-side contract header and
// name it in the handoff -- the builder owns the mechanism, the cell owns
// the claim"): `semb_wb_digest` is not defined anywhere in `superembedder`
// yet (confirmed: `git grep -n semb_wb_digest src/ include/` at this
// branch's own base `c0f52d4` returns nothing). Every test that includes
// this header and calls it fails to LINK until the builder's round adds it,
// wiring it to drive `semb_encode_document_for_witness` +
// `semb_seam_serialize_document` (both ALREADY built, TE-63) over the
// sixteen committed W-B documents (`tests/fixtures/wb/wb-corpus.jsonl`,
// this same round) exactly the way `semb_wa_digest` already drives W-A's
// own population, and to replace `kWbPendingSentinel` in
// `ComputeProvisionalFingerprint` with this same value.
#ifndef SEMB_WB_WITNESS_ABI_CONTRACT_H
#define SEMB_WB_WITNESS_ABI_CONTRACT_H

#include <cstdint>

extern "C" {

// Writes W-B's own 32-byte digest -- SHA-256 over the committed sixteen-
// document corpus's seam serialisation, `u64(document_count)` first, then
// each document's own `semb_seam_serialize_document` stream in committed
// order (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b's own per-document
// layout, wrapped exactly as that section's prose states: "across the
// corpus, u64(document_count) then each document's stream in committed
// order"). Computed in the calling process, freshly, on every call
// (D-SLM3978: no cache, the digest is re-executed, never read from a stored
// value) -- the same "computed by the process that is about to emit
// vectors, in that process" rule sec 4.4b states for the whole witness.
void semb_wb_digest(uint8_t out_digest[32]);

}  // extern "C"

#endif  // SEMB_WB_WITNESS_ABI_CONTRACT_H
