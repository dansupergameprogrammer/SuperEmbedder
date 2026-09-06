// tests/c14_ps_n_fp_contraction_tripwire_test.cpp -- TE-144 (U1 slice 1):
// C14's own PS-N mirror (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C14:
// "Mirrors PS-1's epilogue specifically; a PS-N mirror is owed at the same
// bar once PS-N's own construction is built" -- PS-N's construction,
// `src/superembedder/ps_n_pool.cpp`, is built today per this slice's own
// ground truth, `Claude/Plans/te140-u1-remainder-sequencing.md` sec 2).
//
// THIS CELL'S TWO HALVES, PARALLELING `c14_fp_contraction_tripwire_test.cpp`
// (PS-1's own cell) EXACTLY, with one addition PS-N's own shape requires.
//
//  (1) THE BUILD-CONFIGURATION ASSERTION is the SAME project-wide check
//      PS-1's cell cites (`cmake/BuildFlags.cmake`'s `semb_assert_precise_fp()`,
//      already discharged, applies to every target in this tree including
//      this one). Not re-authored here.
//
//  (2) THE CONTRACTION CANARY is the IDENTICAL construction PS-1's own
//      cell uses (`CanaryBits()`, below) -- two independent `volatile`
//      reads of the same sentinel value defeat compile-time CSE of the two
//      `a*a` occurrences, so the multiply-add pattern survives to code
//      generation, where `-ffp-contract`'s actual value governs whether it
//      fuses into one FMA (a tiny non-zero residual) or stays two
//      separately-rounded operations (exactly zero under strict
//      evaluation). This construction is STANDALONE and PRODUCT-INDEPENDENT
//      -- it is not a recoding of PS-N's own arithmetic, exactly as PS-1's
//      cell states of its own identical canary; reusing it verbatim rather
//      than inventing a second one keeps this project's one proven
//      contraction detector as the single source of that proof.
//
//  (3) TWO TIES TO THE SHIPPED PS-N PATH, NOT ONE -- THE ADDITION PS-N's
//      OWN SHAPE REQUIRES. PS-1's own tie exploits its POOLING structure:
//      two nonzero, opposite-signed, equal-magnitude terms cancel through
//      REAL `BigUInt` add/subtract arithmetic to an exact zero (its own
//      header comment: "a degenerate two-position pooling ... chosen so
//      the SHIPPED, integer-exact epilogue's own correct answer is
//      provably 0.0f too"). PS-N HAS NO POOLING -- it dequantizes ONE
//      (c, m, e) triple with no accumulation step, so no cancellation
//      construction exists on this path at all; the only way to reach
//      `semb_ps_n_dequantize`'s own `IsZero`-shaped early-out (`c == 0 ||
//      abs_m == 0`) is a TRIVIAL zero input, which -- like the trivial half
//      of PS-1's own construction -- exercises no `BigUInt` multiply/shift/
//      round arithmetic at all.
//
//      TIE A (trivial, matching PS-1's own bar exactly): `c=0` ->
//      `kSembOk`, bits `0x00000000`, tied to the SAME canary reference
//      value the PS-1 cell ties its own trivial case to.
//
//      TIE B (real arithmetic, this cell's own addition, because PS-N's
//      structure makes TIE A alone strictly weaker evidence than PS-1's
//      own cancellation): `c=1, m=16777217 (2^24+1), e=0`. The exact
//      rational is 16777217 -- an ODD integer exactly halfway between the
//      two binary32-representable integers on either side of it,
//      16777216 (`2^24`, mantissa field 0, EVEN) and 16777218 (`2^24+2`,
//      mantissa field 1, ODD). Round-to-nearest-ties-to-even therefore
//      rounds DOWN to 16777216.0f, independently confirmed two ways before
//      this file was authored: (i) tracing
//      `binary32_construct.h`'s own `RoundPositiveRationalToBinary32` by
//      hand (E=24, scale=-1, num=16777217, den=2, q=8388608, rem=1,
//      2*rem==den => exact tie => round up iff q is odd => q=8388608 is
//      even => no round-up => mantissa field = q - 2^23 = 0, biased
//      exponent = 24+127=151=0x97); (ii) decomposing the CLAIMED result bit
//      pattern `0x4B800000` directly against IEEE 754 binary32's own
//      layout (sign 0, exponent field `1001 0111`b = 151 -> unbiased 24,
//      mantissa 0 -> value = 1.0 x 2^24 = 16777216), which agrees with (i)
//      without executing either the product or the rounding header being
//      pinned. This exercises REAL `BigUInt` multiply/shift/round
//      arithmetic through a genuine tie, the shape TIE A cannot reach.
//
//      This design EXCEEDS rather than merely matches PS-1's own bar
//      (real, nontrivial arithmetic tied to a hand-verified value, where
//      PS-1's own tie is real-but-exact-zero) -- stated here because the
//      dispatch that authored this file directs that where a slice's own
//      red-first premise does not hold as literally stated, the deviation
//      is reasoned through and recorded, not silently resolved.
//
// RED-FIRST, STATED PRECISELY RATHER THAN ASSUMED (dispatch sec 3's own
// discipline: "Red means red for the stated reason"). The sub-plan's own
// text (`te140` sec 4, Slice 1) describes this cell's red-first as "must
// fail to link (undefined symbol) before it is written, the same shape
// `w_b_serialization_test.cpp` already uses." THAT PREMISE DOES NOT HOLD
// FOR THIS CELL, VERIFIED BY EXECUTION rather than assumed: unlike W-B's
// `semb_seam_serialize_document` (undefined until TE-63) or PS-1's own
// `semb_wa_pool_run` at ITS OWN authoring time (undefined until TE-63),
// `semb_ps_n_dequantize` is ALREADY compiled into the `superembedder`
// library today -- confirmed by reading `CMakeLists.txt` line 108
// (`src/superembedder/ps_n_pool.cpp` is in `SEMB_LIBRARY_SOURCES`) BEFORE
// this file was authored. A test linking against it therefore links and
// (given the arithmetic is already independently oracled elsewhere --
// `tests/oracle/ps_n_reference.py`, folded into `c12b_row_digest_check.py`'s
// S5/R1.c legs, per `te140` sec 2) is expected to PASS on its first build,
// not fail. This is the SAME shape `c14_fp_contraction_tripwire_test.cpp`
// (PS-1's own sibling) already carries in this tree TODAY, post-TE-63: a
// contraction tripwire is a REGRESSION GUARD over an already-correct,
// already-built primitive, not a feature-coverage gate proving an
// unbuilt one -- its genuine red-to-green transition already happened
// once, at the moment its OWN target was first added to
// `tests/CMakeLists.txt` (before which no such executable existed to run
// at all, confirmed by `git grep -n
// "c14_ps_n_fp_contraction_tripwire" tests/CMakeLists.txt` returning
// nothing prior to this fold). This cell's own mutation-proof (below,
// executed at authoring time and filed in the casebook) is what stands in
// for "fails before it passes" here: this file's own TIE B expected value
// was deliberately set to the WRONG neighbour (`0x4B800002`, one ULP off)
// during authoring and confirmed to FAIL for exactly that reason before
// being corrected to the hand-verified `0x4B800000` above -- so the
// assertion is proven able to catch a wrong value, even though the
// shipped path it grades is not itself expected to supply one.
#include <cstdio>
#include <cstring>

#include "semb_ps_n_pool_abi_contract.h"

namespace {

// IDENTICAL to c14_fp_contraction_tripwire_test.cpp's own CanaryBits() --
// see this file's header comment, point (2), for why it is reused
// verbatim rather than re-derived.
volatile float g_a = 1.0000002384185791015625f;  // 1 + 2^-22, exact in float32

uint32_t CanaryBits() {
  const float a1 = g_a;
  const float t = a1 * a1;
  const float c = -t;
  const float a2 = g_a;
  const float fused_shape = a2 * a2 + c;
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
                 "C14/PS-N FAIL: the contraction canary did not evaluate to exactly +0.0f under this "
                 "translation unit's own compile flags (bits=0x%08x) -- contraction is active (a stray "
                 "fast-math/ffp-contract/fp:fast flag reached this TU).\n",
                 CanaryBits());
    ++failures;
  }

  // TIE A: the trivial zero input, matching PS-1's own bar exactly.
  {
    const int8_t codes[1] = {0};
    float out[1] = {1.0f};  // poisoned so an unwritten `out` cannot masquerade as 0.0f
    const SembWaPoolStatus st = semb_ps_n_dequantize(codes, /*m=*/1 << 30, /*e=*/0, /*hidden=*/1, out);
    if (st != kSembOk) {
      std::fprintf(stderr, "C14/PS-N FAIL: TIE A (c=0) did not resolve kSembOk (status=%d).\n",
                   static_cast<int>(st));
      ++failures;
    } else {
      uint32_t bits;
      std::memcpy(&bits, out, 4);
      if (bits != 0x00000000u) {
        std::fprintf(stderr,
                     "C14/PS-N FAIL: TIE A (c=0) did not emit exactly +0.0f (bits=0x%08x) -- disagrees "
                     "with the canary's own strict-evaluation reference.\n",
                     bits);
        ++failures;
      }
    }
  }

  // TIE B: c=1, m=2^24+1, e=0 -- a genuine round-to-nearest-ties-to-even
  // case through real BigUInt multiply/shift/round arithmetic, hand-
  // verified two independent ways in this file's own header comment.
  {
    const int8_t codes[1] = {1};
    const int64_t m = (int64_t{1} << 24) + 1;  // 16777217
    float out[1] = {-1.0f};  // poisoned
    const SembWaPoolStatus st = semb_ps_n_dequantize(codes, m, /*e=*/0, /*hidden=*/1, out);
    if (st != kSembOk) {
      std::fprintf(stderr, "C14/PS-N FAIL: TIE B (c=1, m=2^24+1, e=0) did not resolve kSembOk "
                            "(status=%d).\n",
                   static_cast<int>(st));
      ++failures;
    } else {
      uint32_t bits;
      std::memcpy(&bits, out, 4);
      constexpr uint32_t kExpected = 0x4B800000u;  // 16777216.0f -- see header comment for the derivation
      if (bits != kExpected) {
        std::fprintf(stderr,
                     "C14/PS-N FAIL: TIE B (c=1, m=2^24+1, e=0) emitted 0x%08x, expected 0x%08x "
                     "(16777216.0f, the ties-to-even neighbour) -- the shipped path's rounding disagrees "
                     "with the hand-derived reference.\n",
                     bits, kExpected);
        ++failures;
      }
    }
  }

  if (failures) {
    std::fprintf(stderr, "C14/PS-N: %d check(s) failed.\n", failures);
    return 1;
  }
  std::printf("C14/PS-N: canary and both shipped-path ties (trivial zero, real rounding tie) passed.\n");
  return 0;
}
