// include/superembedder/pool_abi.h -- TE-63 (U0 slice B): the C ABI verb
// for W-A's pooling driver, PS-1's epilogue (`Claude/Plans/
// SuperEmbedder_Plan.md` sec 3.2 items 1, 2, 4; sec 4.4).
//
// This header's symbol names, enum values and function signatures satisfy
// `tests/semb_wa_pool_abi_contract.h` (Curie's own concrete pin of the
// entry-point shape the plan commits to in prose) exactly -- the two are
// authored independently (the test contract is outside this seat's
// writable scope) and are kept byte-identical in their public shape by
// hand; a divergence would show up as a link failure in the test suite,
// not silently.
#ifndef SEMB_POOL_ABI_H
#define SEMB_POOL_ABI_H

#include <cstddef>
#include <cstdint>

enum SembWaPoolStatus : int32_t {
  kSembOk = 0,
  kSembInputTooShort = 1,
  kSembAccumulatorOverflow = 2,
  kSembPooledSubnormal = 3,
  kSembPooledOverflow = 4,
};

extern "C" {

// PS-1's pooling epilogue. `codes` is n*hidden int8, row-major
// (position-major, dimension minor); `m`/`e` are n carried-scale pairs,
// one per position; `out` receives `hidden` float32 values ONLY when the
// return is kSembOk. Position 0 (index 0) is excluded from pooling by this
// entry point's own wiring.
SembWaPoolStatus semb_wa_pool_run(const int8_t* codes, const int64_t* m,
                                   const int64_t* e, size_t n, size_t hidden,
                                   float* out);

// The exponent spread (e_max - e_min) the guard computes over the POOLED
// positions (1..n-1), without running a full pool. Writes *out_spread only
// when the return is kSembOk or kSembAccumulatorOverflow (n >= 2);
// kSembInputTooShort for n < 2 with *out_spread untouched.
SembWaPoolStatus semb_wa_pooled_spread(const int64_t* e, size_t n,
                                        int64_t* out_spread);

}  // extern "C"

#endif  // SEMB_POOL_ABI_H
