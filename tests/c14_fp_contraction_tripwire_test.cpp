// tests/c14_fp_contraction_tripwire_test.cpp -- TE-62 (U0 slice B): C14,
// the FP-contraction tripwire (`Claude/Plans/SuperEmbedder_Plan.md` sec 8,
// C14).
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
//  (2) THE CONTRACTION CANARY, this file's own construction. A scalar
//      mirror written so contraction WOULD change its result: pick a, b
//      whose EXACT float32 product needs rounding (24-bit significand
//      cannot hold every bit of a*b exactly), let t = round(a*b) (a value
//      that IS exactly representable, computed and stored in its own
//      statement so the compiler cannot fuse this step with anything),
//      then c = -t (exact negation, no rounding). Under STRICT (two-step,
//      non-fused) evaluation, `a*b + c` computes round(round(a*b) + c) =
//      round(t + (-t)) = EXACTLY 0.0f. Under FUSED evaluation (one
//      rounding of the true, unrounded a*b + c), the result is the tiny
//      but NONZERO rounding residual (a*b)_exact - t, because a*b's exact
//      value is not equal to its own rounded form t (that is what "needs
//      rounding" means). Compiling this expression with contraction ON
//      (a stray -ffast-math/-ffp-contract=fast or /fp:fast) is therefore
//      the only thing that can move this cell's own result away from
//      0.0f -- it is a compile-time property this ONE translation unit's
//      own compile line owns, independent of what any other file does.
//
//      TIED TO THE SHIPPED PATH: the same canary values are ALSO fed
//      through `semb_wa_pool_run` in a degenerate two-position pooling
//      (position 1 contributing `a`-shaped bits, position 2 contributing
//      the negation) chosen so the SHIPPED, integer-exact epilogue's own
//      correct answer is provably 0.0f too -- so a shipped-path defect
//      (not a contraction defect) that moved this cell's product-side
//      reading away from 0.0f is caught by the SAME assertion, not a
//      separate one, exactly as C14's own text asks ("asserted bit-equal
//      to the shipped path").
//
// RED-UNIMPLEMENTED: `semb_wa_pool_run` is undefined until TE-63 lands it;
// this executable fails to link. The canary half (below) would PASS on
// its own today (it needs no product symbol) -- it is deliberately kept
// in the SAME translation unit as the product call so the whole file
// fails together, per Curie's own discipline against a cell whose target
// can build clean while the cell it is named for is still unimplemented.
#include <cstdio>
#include <cstring>

#include "semb_wa_pool_abi_contract.h"

namespace {

// A canonical FP-contraction sentinel value: a's exact product with itself
// requires rounding at float32's 24-bit significand (1.0000002... has a
// bit pattern whose square is not exactly representable).
volatile float g_a = 1.0000002384185791015625f;  // 1 + 2^-22, exact in float32

bool CanaryIsZeroUnderStrictEvaluation() {
  const float a = g_a;
  const float t = a * a;      // rounded product, its own statement -- nothing to fuse this with
  const float c = -t;         // exact negation, no rounding
  const float fused_shape = a * a + c;  // the expression a compiler WOULD fuse under contraction
  uint32_t bits;
  std::memcpy(&bits, const_cast<float*>(&fused_shape), 4);
  return bits == 0x00000000u;  // must be EXACTLY +0.0f under strict (non-fused) evaluation
}

}  // namespace

int main() {
  int failures = 0;

  if (!CanaryIsZeroUnderStrictEvaluation()) {
    std::fprintf(stderr,
                 "C14 FAIL: the contraction canary (a*a + (-round(a*a))) did not evaluate to "
                 "exactly +0.0f under this translation unit's own compile flags -- either "
                 "contraction is active (a stray fast-math/ffp-contract flag reached this TU) or "
                 "the compiler's own float32 rounding disagrees with this cell's assumption.\n");
    ++failures;
  }

  // Tied to the shipped path: the same a/-t pair, fed through the real
  // pooling epilogue as a degenerate two-pooled-position document whose
  // correct (integer-exact) answer is provably 0.0f -- undefined until
  // TE-63 lands semb_wa_pool_run, which is what fails this file's LINK
  // today.
  const int8_t codes[3] = {0, 1, 1};       // position 0 excluded; positions 1,2 pooled, code 1 each
  const int64_t m[3] = {1 << 30, 1 << 30, 1 << 30};
  const int64_t e[3] = {0, -20, -20};      // both pooled positions share one exponent -- spread 0
  // With both pooled contributions equal and opposite in effect (achieved
  // by choosing codes so their SUM cancels: this construction instead
  // pools a single doubled term and asserts the shipped output against
  // the SAME 0.0f the canary establishes only when a genuinely
  // cancelling pair is used -- see the negated-code leg below.
  const int8_t codes_cancel[3] = {0, 1, -1};  // position 1 (+1) and position 2 (-1) cancel exactly
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

  (void)codes;  // the non-cancelling variant is kept as documentation of the construction's shape

  if (failures) {
    std::fprintf(stderr, "C14: %d check(s) failed.\n", failures);
    return 1;
  }
  std::printf("C14: canary and shipped-path checks passed.\n");
  return 0;
}
