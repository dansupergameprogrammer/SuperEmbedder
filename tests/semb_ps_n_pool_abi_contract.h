// tests/semb_ps_n_pool_abi_contract.h -- TE-144 (U1 slice 1): the test
// author's own concrete pin of PS-N's dequantize entry point
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.2 item 4, applied to one
// (c, m, e) triple instead of a pooled sum; sec 8, C14: "a PS-N mirror is
// owed at the same bar once PS-N's own construction is built").
//
// THIS FILE DECLARES A CONTRACT, NOT AN IMPLEMENTATION -- the identical
// convention `tests/semb_wa_pool_abi_contract.h` already carries for PS-1's
// `semb_wa_pool_run` (Curie's own authority per
// `~/.claude/personas/Implement/Curie/Curie.md` Phase 2/5: turning a
// modeled dimension into an assertable cell, kept in sync with
// `include/superembedder/encoder_interim_abi.h`'s own declaration by hand,
// TE-79 F-15's own standing caution that `extern "C"` linkage checks names,
// never parameter types).
//
// UNLIKE PS-1's OWN CONTRACT AT AUTHORING TIME, `semb_ps_n_dequantize` IS
// ALREADY BUILT (`src/superembedder/ps_n_pool.cpp`, compiled into the
// `superembedder` library today, per this slice's own ground truth --
// `Claude/Plans/te140-u1-remainder-sequencing.md` sec 2). This header's
// existence does not gate a link the way `semb_wa_pool_abi_contract.h`
// once did for `semb_wa_pool_run`; the new construction this cell brings is
// the CONTRACTION-SENSITIVITY MIRROR AND TIE `tests/
// c14_ps_n_fp_contraction_tripwire_test.cpp` builds against it, not the
// dequantize symbol itself. See that file's own header comment for the
// full disposition of this cell's red-first state.
#ifndef SEMB_PS_N_POOL_ABI_CONTRACT_H
#define SEMB_PS_N_POOL_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>

enum SembWaPoolStatus : int32_t {
  kSembOk = 0,
  kSembInputTooShort = 1,
  kSembAccumulatorOverflow = 2,
  kSembPooledSubnormal = 3,
  kSembPooledOverflow = 4,
  kSembEMinDomainExceeded = 5,
};

// Mirrors include/superembedder/pool_abi.h's kSembWaPoolMaxAbsEMin exactly
// (the same constant PS-1's own contract pins, sec 3.2 item 4's single
// shared domain check).
constexpr int64_t kSembWaPoolMaxAbsEMin = 1000000;

extern "C" {

// PS-N's dequantize (sec 3.2 item 4, applied to one triple): each emitted
// element is the binary32 nearest the EXACT rational `c_i * m * 2^e`,
// round-to-nearest-ties-to-even applied once in integer code, classified
// over the ROUNDED result. `out` receives `hidden` float32 values ONLY on
// kSembOk. No floating-point operation is performed on this path.
SembWaPoolStatus semb_ps_n_dequantize(const int8_t* codes, int64_t m, int64_t e, size_t hidden,
                                       float* out);

}  // extern "C"

#endif  // SEMB_PS_N_POOL_ABI_CONTRACT_H
