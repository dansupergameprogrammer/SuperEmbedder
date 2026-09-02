// tests/c3_accumulator_bound_test.cpp -- TE-62 (U0 slice B): C3, the
// accumulator bound, the spread computation, and the alignment population
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C3; sec 3.2 item 4).
//
// THREE CONSTRUCTIONS, each able to fail for its own reason:
//
//  (1) OVERFLOW-REFUSED-BY-NAME. A spread of 74 (one more than the
//      73-bit bound sec 3.2 item 4 derives) must refuse
//      SEMB_ACCUMULATOR_OVERFLOW, never silently wrap the accumulator.
//      Spread 73 itself (AT the bound) must NOT refuse.
//
//  (2) SPREAD COMPUTED OVERFLOW-SAFE AND CHECKED BEFORE ANY SHIFT. Sec 3.2:
//      "e_max - e_min is a difference of two int64_t values computed in a
//      width in which it cannot overflow, then compared against the
//      stated bound; only then is any alignment shift performed... able
//      to fail, because the committed reference casts that difference to
//      unsigned and relies on the bound holding." This cell constructs
//      e_min/e_max at the far ends of int64_t's own range (e_min near
//      INT64_MIN, e_max near INT64_MAX) -- a value whose TRUE spread is
//      astronomically larger than 73 and whose NAIVE unsigned difference
//      wraps to a SMALL number. A correct guard refuses
//      SEMB_ACCUMULATOR_OVERFLOW here; an implementation that casts the
//      difference to `unsigned` before comparing reads a wrapped, small
//      "spread" and incorrectly proceeds to shift by a width no real
//      platform can perform, which this cell's own product-side crash/
//      wrong-refusal is the observable failure of.
//
//  (3) THE ALIGNMENT POPULATION LEG. Position 0's carried scale is varied
//      OUTSIDE the pooled range (1..n-1) in both directions (far below
//      e_min, far above e_max) and the cell asserts BOTH the emitted
//      vector AND the spread `semb_wa_pooled_spread` reads are unchanged
//      -- able to fail, because an implementation that aligns across the
//      WHOLE sequence (including position 0) emits the same vectors but
//      refuses at a DIFFERENT spread, invisible to every digest-equality
//      cell in this plan (sec 3.2's own text).
//
// RED-UNIMPLEMENTED: semb_wa_pool_run / semb_wa_pooled_spread
// (tests/semb_wa_pool_abi_contract.h) are undefined until TE-63 lands
// them; this executable fails to link.
#include <cstdint>
#include <cstdio>
#include <limits>
#include <vector>

#include "semb_wa_pool_abi_contract.h"

namespace {

int g_failures = 0;

void Check(bool cond, const char* what) {
  if (!cond) {
    std::fprintf(stderr, "C3 FAIL: %s\n", what);
    ++g_failures;
  }
}

// (1) Overflow refused by name; the bound itself (73) is accepted.
void CheckBoundIsRefusedByName() {
  // spread 74: two pooled positions (n=3, positions 1 and 2), e differing
  // by 74. Codes chosen non-zero so the accumulator genuinely has work to
  // do (a zero accumulator would trivially "succeed" for the wrong
  // reason).
  const int8_t codes74[3] = {0, 5, 5};
  const int64_t m74[3] = {1 << 30, 1 << 30, 1 << 30};
  const int64_t e74[3] = {0, 0, 74};
  float out[1];
  const SembWaPoolStatus st74 = semb_wa_pool_run(codes74, m74, e74, 3, 1, out);
  Check(st74 == kSembAccumulatorOverflow, "spread 74 did not refuse kSembAccumulatorOverflow");

  const int64_t e73[3] = {0, 0, 73};
  const SembWaPoolStatus st73 = semb_wa_pool_run(codes74, m74, e73, 3, 1, out);
  Check(st73 != kSembAccumulatorOverflow, "spread 73 (AT the bound) incorrectly refused");
}

// (2) The overflow-safe, checked-before-shift construction: e_min near
// INT64_MIN, e_max near INT64_MAX. A naive `(unsigned)(e_max - e_min)`
// wraps; a correct guard must refuse regardless.
void CheckSpreadIsOverflowSafeBeforeShift() {
  const int64_t huge_min = std::numeric_limits<int64_t>::min() + 10;
  const int64_t huge_max = std::numeric_limits<int64_t>::max() - 10;
  const int8_t codes[3] = {0, 3, 3};
  const int64_t m[3] = {1 << 30, 1 << 30, 1 << 30};
  const int64_t e[3] = {0, huge_min, huge_max};  // pooled positions 1,2 span the full int64_t range
  float out[1];
  const SembWaPoolStatus st = semb_wa_pool_run(codes, m, e, 3, 1, out);
  Check(st == kSembAccumulatorOverflow,
        "an astronomically large true spread across int64_t's own range did not refuse -- a "
        "naive unsigned cast of (e_max - e_min) would wrap to a small value here");

  int64_t spread = -1;
  const SembWaPoolStatus spread_st = semb_wa_pooled_spread(e, 3, &spread);
  Check(spread_st == kSembAccumulatorOverflow,
        "semb_wa_pooled_spread did not itself refuse on the same overflow-adjacent input");
}

// (3) The alignment population leg: position 0's own scale, varied
// outside the pooled range in both directions, must change neither the
// emitted vector nor the spread the guard reads.
void CheckPosition0IsInertToAlignment() {
  const size_t hidden = 2;
  const size_t n = 5;  // positions 1..4 pooled
  const int8_t codes[n * hidden] = {
      /*pos0*/ 0, 0,
      /*pos1*/ 10, -10,
      /*pos2*/ 20, -5,
      /*pos3*/ -30, 15,
      /*pos4*/ 5, 25,
  };
  const int64_t m[n] = {1 << 30, (1 << 30) + 1, 1 << 30, (1 << 30) + 5, 1 << 30};
  // Pooled positions 1..4 span exponents -30..-27 (spread 3, inside the
  // corpus's own measured regime, sec 3.2). Position 0's own exponent is
  // varied far below and far above that band.
  const int64_t e_low[n] = {-500, -30, -29, -28, -27};
  const int64_t e_high[n] = {500, -30, -29, -28, -27};

  float out_low[hidden], out_high[hidden];
  const SembWaPoolStatus st_low = semb_wa_pool_run(codes, m, e_low, n, hidden, out_low);
  const SembWaPoolStatus st_high = semb_wa_pool_run(codes, m, e_high, n, hidden, out_high);
  Check(st_low == kSembOk && st_high == kSembOk,
        "position-0-outside-pooled-range case did not resolve SEMB_OK on either side");
  for (size_t i = 0; i < hidden; ++i)
    Check(out_low[i] == out_high[i],
          "the emitted vector moved when only position 0's OWN (excluded) scale changed");

  int64_t spread_low = -1, spread_high = -1;
  semb_wa_pooled_spread(e_low, n, &spread_low);
  semb_wa_pooled_spread(e_high, n, &spread_high);
  Check(spread_low == spread_high && spread_low == 3,
        "the guard-read spread moved with position 0's own (excluded) scale, or was not the "
        "expected pooled-only spread of 3 -- an implementation aligning across the WHOLE "
        "sequence would refuse at a DIFFERENT spread here, invisible to every digest-equality "
        "cell in this plan");
}

}  // namespace

int main() {
  CheckBoundIsRefusedByName();
  CheckSpreadIsOverflowSafeBeforeShift();
  CheckPosition0IsInertToAlignment();
  if (g_failures) {
    std::fprintf(stderr, "C3: %d check(s) failed.\n", g_failures);
    return 1;
  }
  std::printf("C3: all checks passed.\n");
  return 0;
}
