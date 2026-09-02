// include/superembedder/witness_abi.h -- TE-78: the C ABI verb for W-A's
// own digest (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b: "W-A digests
// the arithmetic primitives on the reproducible path, PS-1's epilogue
// included -- driven over named edge sets crossed with full legal
// parameter ranges... every refusal STATUS digested").
//
// Compiled into the LIBRARY, not the witness executable's own TU (sec
// 4.4's structural law, clause 3): the driver calls semb_wa_pool_run
// (itself library code) over the plan's own population and folds every
// case's PARAMETER TUPLE, status, and (on SEMB_OK) emitted bits into one
// SHA-256, using the engine's own portable SHA-256 routine (sec 4.4b:
// "the same routine model_sha uses, so the fingerprint contains one hash
// function and not two"). TE-79 F-23: the constructed `codes`/`m`/`e`
// arrays themselves are not digested, only the tuple that parameterises
// their construction -- see wa_digest.cpp's own header comment for the
// exact scope this leaves open.
#ifndef SEMB_WITNESS_ABI_H
#define SEMB_WITNESS_ABI_H

#include <cstdint>

extern "C" {

// Writes the 32-byte SHA-256 digest of W-A's own population run to
// out_digest[0..31]. Deterministic: the population, the seed (splitmix64,
// 0x0F01D11, sec 4.4's own named discipline) and the driver are all fixed
// by this function's own source.
void semb_wa_digest(uint8_t out_digest[32]);

}  // extern "C"

#endif  // SEMB_WITNESS_ABI_H
