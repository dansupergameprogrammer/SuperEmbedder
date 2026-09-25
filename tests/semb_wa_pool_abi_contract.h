// tests/semb_wa_pool_abi_contract.h -- TE-62 (U0 slice B red suite): the C
// ABI verb this suite assumes the builder exposes for W-A's pooling driver
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4: "The pooling driver is an
// ENTRY POINT... `pool({codes, m, e} over n positions) -> hidden float32`,
// plus its refusals").
//
// THIS FILE DECLARES A CONTRACT, NOT AN IMPLEMENTATION. It is Curie's own
// pin of the entry-point shape the plan already commits to in prose
// (positions, codes, carried scale, hidden float32 out, named refusal
// statuses) -- the plan does not spell out a literal C symbol name or
// signature, so this header is this seat's concrete realization of it
// (Curie's own authority per `~/.claude/personas/Implement/Curie/Curie.md`
// Phase 2/5: turning a modeled dimension into an assertable cell), and it
// is the interface the C ABI verb TE-63 builds is expected to satisfy or
// to explicitly renegotiate. Every test in this suite that needs the
// product's pooling epilogue links against exactly these symbol names;
// none of them is defined anywhere in `superembedder` yet, so every test
// that includes this header fails to LINK until TE-63 adds them --
// red-unimplemented, per this seat's brief ("cells that need the engine's
// headers fail at configure or compile until TE-63 adds the dependency --
// that is the expected red, stated per cell").
//
// STATUS CODES pin sec 3.2's own vocabulary where the plan names one
// (SEMB_INPUT_TOO_SHORT, SEMB_POOLED_SUBNORMAL, SEMB_POOLED_OVERFLOW) and
// this seat's own working name where it does not
// (SEMB_ACCUMULATOR_OVERFLOW for the pre-rounding, accumulator-bound
// refusal sec 3.2 item 4 describes as "refused by name" without spelling
// the name -- see `tests/oracle/ps1_reference.py`'s own module docstring
// and `Claude/Curie/te62-u0b-red-suite-2026-09-02.md`'s Coverage Model
// gaps for this routed finding).
#ifndef SEMB_WA_POOL_ABI_CONTRACT_H
#define SEMB_WA_POOL_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>

enum SembWaPoolStatus : int32_t {
  kSembOk = 0,
  kSembInputTooShort = 1,
  kSembAccumulatorOverflow = 2,
  kSembPooledSubnormal = 3,
  kSembPooledOverflow = 4,
  // TE-80 (TE-76 review F-2, closed by TE-79 in ps1_pool.cpp): the pooled
  // positions' own minimum carried exponent (e_min) domain, refused
  // BEFORE any alignment/scaling shift, in int64_t (a width e_min already
  // lives in, so the check itself cannot overflow). See
  // kSembWaPoolMaxAbsEMin below -- mirrors include/superembedder/pool_abi.h
  // exactly (TE-79 F-15's own standing caution: extern "C" linkage does
  // not check this by itself; kept in sync by hand).
  kSembEMinDomainExceeded = 5,
  // U2 cloud build, U2-10 item 3: the pool's allocation-failure and internal-
  // failure statuses. The plan names them without values; 6 and 7 are the
  // next free values, assumed here (a build-time item for the builder).
  kSembWaPoolAllocationFailed = 6,
  kSembWaPoolInternalFailure = 7,
};

// Mirrors include/superembedder/pool_abi.h's kSembWaPoolMaxAbsEMin
// exactly: the largest |e_min| semb_wa_pool_run accepts before refusing
// kSembEMinDomainExceeded. 1,000,000 -- generous against the measured
// carried range ([-160, 154]) and the width past which any accumulator
// this library can construct (<= 128 bits) already resolves to
// zero/subnormal/infinity regardless.
constexpr int64_t kSembWaPoolMaxAbsEMin = 1000000;

extern "C" {

// PS-1's pooling epilogue (sec 3.2 items 1, 2, 4), as a single entry point
// over one document's already-embedded per-position codes and carried
// scales. `codes` is n*hidden int8, row-major (position-major, dimension
// minor); `m`/`e` are n carried-scale pairs, one per position; `out`
// receives `hidden` float32 values ONLY when the return is kSembOk.
// Position 0 (index 0) is excluded from pooling by the callee, per item 2
// -- the caller passes the FULL n-position sequence, not a pre-trimmed
// one, so this entry point's own wiring (not the caller's) is what the
// cells below are checking.
SembWaPoolStatus semb_wa_pool_run(const int8_t* codes, const int64_t* m,
                                   const int64_t* e, size_t n, size_t hidden,
                                   float* out);

// C3's own construction: returns the exponent spread (e_max - e_min) the
// guard computed over the POOLED positions (1..n-1) for the given inputs,
// without needing a full pool run -- so a test can assert the spread the
// guard reads is unchanged by position 0's own carried scale without
// depending on whether the pool itself accepted or refused. Writes
// *out_spread only when the return is kSembOk or kSembAccumulatorOverflow
// (i.e. whenever n >= 2); returns kSembInputTooShort for n < 2 with
// *out_spread untouched.
SembWaPoolStatus semb_wa_pooled_spread(const int64_t* e, size_t n,
                                        int64_t* out_spread);

}  // extern "C"

#endif  // SEMB_WA_POOL_ABI_CONTRACT_H
