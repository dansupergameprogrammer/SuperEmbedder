// include/superembedder/wb_digest_abi.h -- TE-147 (U1 slice 2 build): the
// product-side declaration of W-B's own diagnostic accessor, in the same
// PURPOSE `include/superembedder/witness_abi.h` serves for W-A
// (`void semb_wa_digest(uint8_t out_digest[32]);`) -- but declared in a
// SEPARATE header rather than added to witness_abi.h, because witness_abi.h
// is included by translation units that ALSO include the test suite's own
// contract headers (`tests/semb_public_abi_contract.h`), which declare
// their OWN `semb_status`/`semb_encoder` types independently of this
// product header. Adding a declaration that needs those types to
// witness_abi.h would pull `superembedder/semb.h`'s own real typedefs into
// those translation units too, producing a duplicate-definition conflict
// with the test contract's own types (confirmed:
// `tests/c41_environment_invariance_test.cpp` includes both
// `semb_public_abi_contract.h` and `superembedder/witness_abi.h` in one
// TU). This header is included only where the real product types are
// already in scope (src/superembedder/encoder.cpp, after
// `superembedder/semb.h`), never by a TU that also carries the test
// suite's own duplicate contract types.
//
// Like `semb_wa_digest`, this verb is WITNESS/BUILD MACHINERY -- sec 3.1's
// twelve frozen verbs do not include it, and it reaches no consumer beyond
// this project's own test matrix.
#ifndef SEMB_WB_DIGEST_ABI_H
#define SEMB_WB_DIGEST_ABI_H

#include <cstdint>

#include "superembedder/semb.h"  // semb_status, semb_encoder -- this verb's own types

extern "C" {

// W-B's own digest for the artifacts `enc` was opened on (TE-147; the
// contract of record is `tests/semb_wb_witness_abi_contract.h`, AMENDED
// TE-151 to this handle-scoped shape). SHA-256 over the committed
// sixteen-document corpus's seam serialisation -- u64(document_count)
// first, then each document's own semb_seam_serialize_document stream in
// committed order -- each document tokenized through `enc`'s OWN
// tokenizer with `enc`'s OWN resolved end-token id appended
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b). Unlike W-A, W-B is NOT
// model-independent, so this accessor is handle-scoped rather than bare:
//
//   enc == NULL                  -> SEMB_NULL_ARGUMENT, out_digest untouched
//   enc names no live handle     -> SEMB_INVALID_HANDLE, out_digest untouched
//   out_digest == NULL           -> SEMB_NULL_ARGUMENT
//   else                         -> the 32 bytes written, SEMB_OK
//
// The same value this accessor returns for a live `enc` is what
// `ComputeProvisionalFingerprint` (src/superembedder/encoder.cpp) folds
// into that handle's own `witness_sha`, in place of the literal
// `kWbPendingSentinel` it hashed before this round.
semb_status semb_wb_digest(semb_encoder enc, uint8_t out_digest[32]);

}  // extern "C"

#endif  // SEMB_WB_DIGEST_ABI_H
