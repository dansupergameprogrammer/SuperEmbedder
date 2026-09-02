// tests/c14_fp_contraction_tripwire_test.cpp -- TE-62/TE-80 (U0 slice B):
// C14, the FP-contraction tripwire (`Claude/Plans/SuperEmbedder_Plan.md`
// sec 8, C14).
//
// THIS CELL'S TWO HALVES.
//
//  (1) THE BUILD-CONFIGURATION ASSERTION -- "fails the build when sec 1.3's
//      flags are absent" -- is ALREADY DISCHARGED by
//      `cmake/BuildFlags.cmake`'s `semb_assert_precise_fp()`, exercised by
//      `tools/ci/run_configure_matrix.py`'s own C14 legs (slice A, already
//      landed and green). This cell does not re-author that half; it is
//      cited here, not reproduced, per the records standard against
//      duplicating an existing mechanism.
//
//  (2) THE CONTRACTION CANARY. TE-80 REPAIR (TE-76 review F-3,
//      Significant): the prior canary computed `t = a*a` in its own
//      statement, then reused the SAME `a` a second time inside
//      `a*a + c` -- and because nothing separates the two `a*a`
//      occurrences, an optimizing compiler recognises them as the SAME
//      value (common-subexpression elimination, a compile-time algebraic
//      fold, unrelated to any `-ffp-contract` setting) and rewrites the
//      whole expression to `t + (-t)` = `t - t`, which IEEE 754 makes
//      EXACTLY zero for ANY finite `t` regardless of rounding -- so the
//      canary read `+0.0f` under every flag combination the reviewer
//      tried, including `-mfma -ffp-contract=fast`, where the emitted
//      code was `vmulss` then `vsubss %xmm0,%xmm0,%xmm0`: no multiply-add
//      pattern ever reached code generation for `-ffp-contract` to act
//      on. The reviewer's own control, an EXPLICIT `fmaf(a, a, -round(a*a))`
//      (`0x29800000`, non-zero), proved the underlying arithmetic premise
//      sound; the defect was purely that the canary's own SOURCE let the
//      optimizer erase the multiply-add before the flag could matter.
//
//      THE FIX: `a` is read from the `volatile` global TWICE, once for
//      each `a*a` occurrence (`a1` and `a2`, below). Because `g_a` is
//      `volatile`, the compiler must treat each read as a distinct,
//      independently-observable event and is FORBIDDEN from assuming
//      `a2 == a1` -- the abstract machine model for `volatile` explicitly
//      permits the value to differ between accesses (as if some external
//      agent could have changed it), even though nothing in this program
//      does. This defeats CSE at its root: the compiler cannot prove
//      `a2*a2` and `a1*a1` are the same product, so it cannot fold
//      `a2*a2 + c` (where `c` was derived from `a1*a1`) down to a bare
//      subtraction of two provably-equal values -- the multiply-add
//      pattern survives to code generation, where `-ffp-contract`'s
//      actual value governs whether it becomes one FMA instruction (the
//      UNROUNDED product minus `t`, a tiny non-zero residual) or two
//      separately-rounded operations (`round(a2*a2)` = `t` again, since
//      IEEE multiply is deterministic, so `t + (-t)` = exactly zero
//      under strict evaluation). At RUNTIME the two reads still return
//      the identical bit pattern (nothing writes `g_a` between them), so
//      the arithmetic result is exactly what the header above describes
//      -- only the COMPILER's ability to reason about it at compile time
//      changes.
//
//      TIED TO THE SHIPPED PATH: the same canary values are ALSO fed
//      through `semb_wa_pool_run` in a degenerate two-position pooling
//      (position 1 contributing `a`-shaped bits, position 2 contributing
//      the negation) chosen so the SHIPPED, integer-exact epilogue's own
//      correct answer is provably 0.0f too -- so a shipped-path defect
//      (not a contraction defect) that moved this cell's product-side
//      reading away from 0.0f is caught by the SAME assertion, not a
//      separate one. This half is intentionally NOT the primary
//      contraction signal: `semb_wa_pool_run` performs no floating-point
//      operation at all (sec 3.2 item 4's own "no floating-point
//      operation appears anywhere on this path"), so its cancelling-pool
//      leg is an exact-zero case by integer construction
//      (`ps1_pool.cpp`'s `IsZero()` short-circuit) that no contraction
//      flag could ever have moved -- it remains here as a bit-equality
//      check between the canary's own reference value and the shipped
//      epilogue's, not as a second contraction-detecting construction.
//
//  TE-83 (TE-81 review N-10, Observation): STATED, NOT INFERRED -- what a
//      GREEN result here does and does not prove. RED means what the
//      failure message below says: "contraction is active (a stray
//      fast-math/ffp-contract/fp:fast flag reached this TU)" -- true, and
//      the only claim the message makes. The CONVERSE does not hold, and
//      is not claimed: a GREEN result does not mean no fast-math flag
//      reached this TU, only that this TU's build did not produce a
//      fused multiply-add for THIS canary's specific expression shape.
//      Executed (TE-81 review sec 6.2): under `-ffast-math` WITHOUT
//      `-mfma`, the repaired canary reads exactly `0x00000000` (green) --
//      the compiler has fast-math's other license (`-fno-signed-zeros`,
//      `-freciprocal-math`, associative reassociation) but no FMA-capable
//      target to fold `a2*a2 + c` into a single instruction, so nothing
//      here observes it. This is the residual the prior review's own
//      prediction named for sec 8's C13 toolchains (one of which may
//      build for a non-FMA target): a green C14 on such a toolchain
//      proves "no contraction reached this expression," never "no
//      fast-math flag reached this translation unit" -- a strictly
//      narrower claim than the cell's name might suggest to a reader who
//      has not read this far.
//
// RED-UNIMPLEMENTED: `semb_wa_pool_run` is undefined until TE-63 lands it;
// this executable fails to link.
#include <cstdio>
#include <cstring>

#include "semb_wa_pool_abi_contract.h"

namespace {

// A canonical FP-contraction sentinel value: a's exact product with itself
// requires rounding at float32's 24-bit significand (1.0000002... has a
// bit pattern whose square is not exactly representable). `volatile`
// defeats compile-time constant folding of `g_a` itself; the TWO
// independent reads in `CanaryBits()`, below, defeat CSE of the two `a*a`
// occurrences derived from it.
volatile float g_a = 1.0000002384185791015625f;  // 1 + 2^-22, exact in float32

uint32_t CanaryBits() {
  const float a1 = g_a;              // first independent volatile read
  const float t = a1 * a1;           // the rounded product, its own statement
  const float c = -t;                // exact negation, no rounding
  const float a2 = g_a;              // SECOND independent volatile read -- the compiler
                                      // cannot prove a2 == a1, so it cannot fold a2*a2
                                      // against t/c at compile time
  const float fused_shape = a2 * a2 + c;  // the multiply-add a compiler auto-contracts
                                           // under -ffp-contract=fast / -mfma / -ffast-math
                                           // / MSVC's /fp:fast (+ an FMA-capable target)
  uint32_t bits;
  std::memcpy(&bits, &fused_shape, 4);
  return bits;
}

bool CanaryIsZeroUnderStrictEvaluation() { return CanaryBits() == 0x00000000u; }

}  // namespace

int main() {
  int failures = 0;

  if (!CanaryIsZeroUnderStrictEvaluation()) {
    std::fprintf(stderr,
                 "C14 FAIL: the contraction canary (a2*a2 + (-round(a1*a1)), a1 and a2 two "
                 "independent volatile reads of the same value) did not evaluate to exactly "
                 "+0.0f under this translation unit's own compile flags (bits=0x%08x) -- "
                 "contraction is active (a stray fast-math/ffp-contract/fp:fast flag reached "
                 "this TU).\n", CanaryBits());
    ++failures;
  }

  // Tied to the shipped path: the same a/-t pair, fed through the real
  // pooling epilogue as a degenerate two-pooled-position document whose
  // correct (integer-exact) answer is provably 0.0f -- undefined until
  // TE-63 lands semb_wa_pool_run, which is what fails this file's LINK
  // today.
  const int8_t codes_cancel[3] = {0, 1, -1};  // position 1 (+1) and position 2 (-1) cancel exactly
  const int64_t m[3] = {1 << 30, 1 << 30, 1 << 30};
  const int64_t e[3] = {0, -20, -20};      // both pooled positions share one exponent -- spread 0
  float out[1] = {1.0f};  // poisoned so an unwritten `out` cannot masquerade as 0.0f
  const SembWaPoolStatus st =
      semb_wa_pool_run(codes_cancel, m, e, /*n=*/3, /*hidden=*/1, out);
  if (st != kSembOk) {
    std::fprintf(stderr, "C14 FAIL: the degenerate cancelling pool did not resolve SEMB_OK "
                          "(status=%d).\n", static_cast<int>(st));
    ++failures;
  } else {
    uint32_t out_bits;
    std::memcpy(&out_bits, out, 4);
    if (out_bits != 0x00000000u) {
      std::fprintf(stderr, "C14 FAIL: the shipped epilogue's cancelling pool did not emit exactly "
                            "+0.0f (bits=0x%08x) -- disagrees with the canary's own strict-"
                            "evaluation reference.\n", out_bits);
      ++failures;
    }
  }

  if (failures) {
    std::fprintf(stderr, "C14: %d check(s) failed.\n", failures);
    return 1;
  }
  std::printf("C14: canary and shipped-path checks passed.\n");
  return 0;
}
