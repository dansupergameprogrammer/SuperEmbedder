// src/superembedder/ps1_pool.cpp -- TE-63 (U0 slice B): PS-1's pooling
// epilogue, W-A's own primitive-tier entry point (`Claude/Plans/
// SuperEmbedder_Plan.md` sec 3.2 items 1, 2, 4; sec 4.4: "The pooling
// driver is an ENTRY POINT... pool({codes, m, e} over n positions) ->
// hidden float32, plus its refusals").
//
// INTEGER-EXACT END TO END, per sec 3.2 item 4's own specification: the
// pooled sum S_i is exact wide-integer accumulation (BigUInt, unbounded --
// generalizing the withdrawn fold-round-11 probe's fixed 128-bit I128 to
// whatever width the caller's spread/positions actually need); the emitted
// binary32 bit pattern is CONSTRUCTED from the exact rational
// v_i = S_i * 2^e_min / P by integer sign/exponent/significand arithmetic,
// with round-to-nearest-ties-to-even applied ONCE to the exact quotient.
// No floating-point operation appears anywhere on this path -- no ldexp,
// no scalbnf, no float divide, matching item 4's own prohibition (the
// withdrawn probe cell's `ldexp`+float-divide construction is exactly what
// D-SLM4079 withdrew it for: it depends on the ambient FP environment).
//
// Independently authored against the plan's prose and against
// `tests/oracle/ps1_reference.py`'s own documented algorithm (its module
// docstring, read as the specification's restatement -- this file's own
// arithmetic was derived from sec 3.2 item 4 directly, then checked for
// agreement against the oracle's documented rounding rule, never against
// its Python source line by line).
#include "superembedder/pool_abi.h"

#include <cstdint>
#include <cstring>
#include <vector>

#include "big_uint.h"

namespace semb {
namespace {

constexpr int kMantissaBits = 23;
constexpr int kExpBias = 127;
constexpr int64_t kMinNormalExp = -126;
constexpr int64_t kMaxNormalExp = 127;
constexpr int64_t kAccumulatorSpreadBits = 73;

// A signed arbitrary-precision integer: a BigUInt magnitude plus a sign.
// `neg` is meaningless when `mag` is zero (both signs denote the same
// value); every accumulation below treats a zero magnitude as sign-free.
struct SignedBig {
  bool neg = false;
  BigUInt mag;
};

SignedBig AddSignedTerm(SignedBig acc, bool term_neg, const BigUInt& term_mag) {
  if (term_mag.IsZero()) return acc;
  if (acc.mag.IsZero()) {
    acc.neg = term_neg;
    acc.mag = term_mag;
    return acc;
  }
  if (acc.neg == term_neg) {
    acc.mag = acc.mag.Add(term_mag);
    return acc;
  }
  if (acc.mag.Compare(term_mag) >= 0) {
    acc.mag = acc.mag.Sub(term_mag);
  } else {
    acc.mag = term_mag.Sub(acc.mag);
    acc.neg = term_neg;
  }
  return acc;
}

// Compares A against D * 2^E for a possibly-negative E, without
// materializing 2^E on its own -- shifts whichever side of the comparison
// avoids a fractional (negative) shift.
int CompareAToDShiftedByE(const BigUInt& A, const BigUInt& D, int64_t E) {
  if (E >= 0) return A.Compare(D.ShiftLeft(static_cast<unsigned>(E)));
  return A.ShiftLeft(static_cast<unsigned>(-E)).Compare(D);
}

struct RoundResult {
  enum Kind { kZero, kNormal, kSubnormal, kInfinity } kind;
  uint32_t bits;
};

// Rounds the exact positive rational A/D (A > 0, D > 0) to the nearest
// binary32, ties to even, under gradual underflow -- mirrors sec 3.2 item
// 4's own specification: find the binary exponent E with 2^E <= A/D <
// 2^(E+1) by exact comparison (never log/float), scale to a 24-bit (or,
// under the subnormal floor, narrower) integer significand with one
// RNE step over the exact remainder, and classify the ROUNDED result
// (never the exact one) against the subnormal/overflow corners -- an
// exactly-zero A is the caller's responsibility to special-case BEFORE
// calling this (there is no "exact zero" rational with A > 0).
RoundResult RoundPositiveRationalToBinary32(bool sign, const BigUInt& A, const BigUInt& D) {
  const unsigned a_len = A.BitLength();
  const unsigned d_len = D.BitLength();
  int64_t E = static_cast<int64_t>(a_len) - static_cast<int64_t>(d_len);
  while (CompareAToDShiftedByE(A, D, E) < 0) --E;
  while (CompareAToDShiftedByE(A, D, E + 1) >= 0) ++E;

  int64_t exp_field;
  int64_t scale;
  if (E >= kMinNormalExp) {
    exp_field = E;
    scale = kMantissaBits - E;
  } else {
    exp_field = kMinNormalExp;
    scale = kMantissaBits - kMinNormalExp;  // 149
  }

  BigUInt num, den;
  if (scale >= 0) {
    num = A.ShiftLeft(static_cast<unsigned>(scale));
    den = D;
  } else {
    num = A;
    den = D.ShiftLeft(static_cast<unsigned>(-scale));
  }
  BigUInt q, rem;
  BigUInt::DivMod(num, den, &q, &rem);

  const BigUInt twice_rem = rem.ShiftLeft(1);
  const int cmp = twice_rem.Compare(den);
  bool round_up = false;
  if (cmp > 0) {
    round_up = true;
  } else if (cmp == 0) {
    round_up = q.GetBit(0);  // ties to even: round up only if q is odd
  }
  if (round_up) q = q.Add(BigUInt(uint64_t{1}));

  const uint32_t sign_bit = sign ? 1u : 0u;
  if (E >= kMinNormalExp) {
    if (q.Compare(BigUInt(uint64_t{1} << (kMantissaBits + 1))) == 0) {
      q = q.ShiftRight(1);
      ++exp_field;
    }
    if (exp_field > kMaxNormalExp) {
      return {RoundResult::kInfinity, (sign_bit << 31) | (0xFFu << 23)};
    }
    const uint32_t biased = static_cast<uint32_t>(exp_field + kExpBias);
    const uint32_t mantissa =
        static_cast<uint32_t>(q.Sub(BigUInt(uint64_t{1} << kMantissaBits)).ToU64());
    return {RoundResult::kNormal, (sign_bit << 31) | (biased << 23) | mantissa};
  }
  if (q.Compare(BigUInt(uint64_t{1} << kMantissaBits)) == 0) {
    // Rounded up across the subnormal/normal boundary: this IS exactly the
    // smallest normal (2^-126).
    return {RoundResult::kNormal, (sign_bit << 31) | (1u << 23)};
  }
  if (q.IsZero()) {
    return {RoundResult::kZero, sign_bit << 31};
  }
  return {RoundResult::kSubnormal, (sign_bit << 31) | static_cast<uint32_t>(q.ToU64())};
}

// The overflow-safe spread computation, checked BEFORE any alignment
// shift, shared by semb_wa_pool_run and semb_wa_pooled_spread. `e_max` and
// `e_min` are cast to uint64_t and subtracted in that width -- their exact
// mathematical difference over int64_t's own range is always in
// [0, 2^64 - 2] (e_max >= e_min by construction), which fits a uint64_t
// exactly, so the unsigned subtraction (well-defined modulo 2^64, never
// UB) recovers the true magnitude with no width in which it can overflow
// -- sec 3.2 item 4's own "computed in a width in which it cannot
// overflow" applied literally, rather than casting an already-computed
// (and, for extreme inputs, already-UB) signed difference.
bool ComputeSpread(const int64_t* e, size_t n, int64_t* out_e_min, uint64_t* out_spread) {
  if (n < 2) return false;
  int64_t e_min = e[1], e_max = e[1];
  for (size_t t = 1; t < n; ++t) {
    if (e[t] < e_min) e_min = e[t];
    if (e[t] > e_max) e_max = e[t];
  }
  const uint64_t spread_u = static_cast<uint64_t>(e_max) - static_cast<uint64_t>(e_min);
  if (out_e_min) *out_e_min = e_min;
  if (out_spread) *out_spread = spread_u;
  return true;
}

}  // namespace
}  // namespace semb

extern "C" SembWaPoolStatus semb_wa_pool_run(const int8_t* codes, const int64_t* m,
                                              const int64_t* e, size_t n, size_t hidden,
                                              float* out) {
  using semb::AddSignedTerm;
  using semb::BigUInt;
  using semb::ComputeSpread;
  using semb::RoundPositiveRationalToBinary32;
  using semb::RoundResult;
  using semb::SignedBig;

  int64_t e_min = 0;
  uint64_t spread = 0;
  if (!ComputeSpread(e, n, &e_min, &spread)) return kSembInputTooShort;
  if (spread > static_cast<uint64_t>(semb::kAccumulatorSpreadBits)) return kSembAccumulatorOverflow;

  const size_t first = 1;
  const size_t P = n - first;  // the POOLED count, never n

  std::vector<uint32_t> bits(hidden, 0);
  for (size_t i = 0; i < hidden; ++i) {
    SignedBig acc;
    for (size_t t = first; t < n; ++t) {
      const int8_t c = codes[t * hidden + i];
      if (c == 0) continue;
      const int64_t mt = m[t];
      if (mt == 0) continue;
      const unsigned shift = static_cast<unsigned>(e[t] - e_min);
      const bool term_neg = (c < 0) != (mt < 0);
      const uint64_t abs_c =
          c < 0 ? static_cast<uint64_t>(-static_cast<int32_t>(c)) : static_cast<uint64_t>(c);
      // Two's-complement negation via unsigned arithmetic -- safe even for
      // mt == INT64_MIN, where -mt is itself UB in signed arithmetic.
      const uint64_t abs_m =
          mt < 0 ? (~static_cast<uint64_t>(mt) + 1u) : static_cast<uint64_t>(mt);
      const BigUInt term_mag = BigUInt(abs_c).MulU64(abs_m).ShiftLeft(shift);
      acc = AddSignedTerm(acc, term_neg, term_mag);
    }

    if (acc.mag.IsZero()) {
      bits[i] = 0x00000000u;  // exact zero: always +0.0f, no sign carried
      continue;
    }

    BigUInt A, D;
    if (e_min >= 0) {
      A = acc.mag.ShiftLeft(static_cast<unsigned>(e_min));
      D = BigUInt(static_cast<uint64_t>(P));
    } else {
      A = acc.mag;
      D = BigUInt(static_cast<uint64_t>(P)).ShiftLeft(static_cast<unsigned>(-e_min));
    }
    const RoundResult rr = RoundPositiveRationalToBinary32(acc.neg, A, D);
    switch (rr.kind) {
      case RoundResult::kSubnormal:
        return kSembPooledSubnormal;
      case RoundResult::kInfinity:
        return kSembPooledOverflow;
      case RoundResult::kZero:
      case RoundResult::kNormal:
        bits[i] = rr.bits;
        break;
    }
  }

  for (size_t i = 0; i < hidden; ++i) std::memcpy(&out[i], &bits[i], sizeof(float));
  return kSembOk;
}

extern "C" SembWaPoolStatus semb_wa_pooled_spread(const int64_t* e, size_t n,
                                                   int64_t* out_spread) {
  using semb::ComputeSpread;

  int64_t e_min = 0;
  uint64_t spread = 0;
  if (!ComputeSpread(e, n, &e_min, &spread)) return kSembInputTooShort;
  if (spread > static_cast<uint64_t>(semb::kAccumulatorSpreadBits)) {
    if (out_spread) *out_spread = static_cast<int64_t>(spread);
    return kSembAccumulatorOverflow;
  }
  if (out_spread) *out_spread = static_cast<int64_t>(spread);
  return kSembOk;
}
