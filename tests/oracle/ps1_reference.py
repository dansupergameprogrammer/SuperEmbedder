"""tests/oracle/ps1_reference.py -- TE-62 (U0 slice B red suite): the
independent, exact-rational reference oracle for PS-1's pooling epilogue
(`Claude/Plans/SuperEmbedder_Plan.md` sec 3.2, items 1, 2 and 4).

WHAT THIS IS AND WHY IT TAKES NO INPUT FROM THE CODE UNDER TEST.

This module computes the same quantity PS-1 specifies -- the pooled,
binary32-rounded vector and its refusal status -- from the plan's PROSE
specification alone, using `fractions.Fraction` for every intermediate value
and NEVER a Python float operation. It is written independently of, and
without reading, any C++ implementation of the epilogue (the fold-4 probe
tree's `t2217_fold11_pooling_wa_cell.cpp` was read only for its POPULATION
(the parameter crossing sec 4.4 states in prose) and its ANCHOR values, per
this seat's own brief -- its ARITHMETIC was not read before this file was
written, and this file's rounding algorithm is derived from first
principles (IEEE 754-2008 round-to-nearest-ties-to-even over an exact
rational, with gradual underflow) rather than transcribed from any
implementation.

This is C1's oracle (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C1 -- "The
oracle takes no input from the code under test") and the arithmetic half of
the W-A population oracle (`tests/oracle/w_a_population.py`, which imports
this module and supplies the population sec 4.4's prose specifies).

THE SPECIFICATION THIS MODULE IMPLEMENTS (sec 3.2, items 1/2/4; PS-1, the
named fallback under D-SLM4727 -- this module does NOT implement PS-N,
which has no converted artifact to build its epilogue against yet, sec 3.2,
C1').

  Positions 1..n-1 are pooled (position 0 excluded); n < 2 has no poolable
  position and is SEMB_INPUT_TOO_SHORT.

  For each pooled position t, a term contributes `c[t][i] * m[t] * 2^(e[t] -
  e_min)` to dimension i's accumulator, where e_min is the MINIMUM e[t]
  across the POOLED positions only (position 0's carried scale never enters
  e_min/e_max -- this is C3's own population leg, sec 3.2's "alignment
  population is the pooled positions, and it is derived rather than
  chosen").

  The exponent spread e_max - e_min is checked BEFORE any accumulation: a
  spread that would require more than 73 bits of accumulator width is
  refused (this module names that refusal SEMB_ACCUMULATOR_OVERFLOW --
  Claude/Curie/te62-u0b-red-suite-2026-09-02.md records this as a routed
  Coverage-Model gap: sec 3.2 states the refusal exists and describes it as
  "refused by name" but never spells out its exact SEMB_* identifier, so
  this name is Curie's working choice pending planner confirmation, not a
  transcription of an existing status).

  Otherwise S_i = sum over pooled t of c[t][i] * m[t] * 2^(e[t] - e_min), an
  EXACT integer (Python ints are exact; no width limit is imposed here --
  the 73-bit bound above is what the accumulator commits to. This oracle's
  own arithmetic is exact regardless).

  v_i = Fraction(S_i * 2**e_min, P) where P = n - 1 is the number of POOLED
  positions (never n, the templated token count -- item 4's own
  off-by-one warning).

  v_i is rounded to binary32 by ROUND-TO-NEAREST-TIES-TO-EVEN of the EXACT
  rational, under gradual underflow (subnormals are produced, never
  flush-to-zero), and the ROUNDED result is then classified: exact zero is
  SEMB_OK; a non-zero magnitude below 2^-126 is SEMB_POOLED_SUBNORMAL; a
  magnitude that rounds to infinity (>= 2^128 - 2^103, the RNE overflow
  threshold) is SEMB_POOLED_OVERFLOW; anything else is SEMB_OK.

USAGE

  Importable: `pool_exact(codes, m, e, hidden) -> PoolResult`.

  CLI (JSON on stdin, JSON on stdout), for a C++ test to invoke as a
  subprocess without any Python<->C++ binding:
      echo '{"codes": [[...],...], "m": [...], "e": [...], "hidden": N}' \\
          | python tests/oracle/ps1_reference.py
  prints `{"status": "...", "bits_hex": ["0x3f800000", ...] | null}`.

  `python tests/oracle/ps1_reference.py --selftest` runs this file's own
  unit checks (round-trip against Python's IEEE-754 `struct.pack` on exact
  dyadic values it does not double-round, plus hand-derived boundary cases)
  and exits 0 only if every one passes -- this is what makes the oracle
  itself a checked artifact rather than an assumed-correct one.
"""
from __future__ import annotations

import json
import struct
import sys
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Sequence, Tuple

SEMB_OK = "SEMB_OK"
SEMB_INPUT_TOO_SHORT = "SEMB_INPUT_TOO_SHORT"
# Working name, not yet a confirmed plan identifier -- see module docstring
# and the test-design record's "Coverage Model gaps" section.
SEMB_ACCUMULATOR_OVERFLOW = "SEMB_ACCUMULATOR_OVERFLOW"
SEMB_POOLED_SUBNORMAL = "SEMB_POOLED_SUBNORMAL"
SEMB_POOLED_OVERFLOW = "SEMB_POOLED_OVERFLOW"

# sec 3.2 item 4's accumulator bound: "int64 holds a cross-position exponent
# spread <= 9 bits and 128-bit accumulation holds <= 73 bits" -- the
# reference implementation uses 128-bit accumulation, so 73 is the bound a
# spread is checked against before any alignment shift.
ACCUMULATOR_SPREAD_BITS = 73

# binary32 layout constants (IEEE 754-2008), from first principles -- not
# read off any implementation.
_MANTISSA_BITS = 23
_EXP_BIAS = 127
_MIN_NORMAL_EXP = -126  # smallest exponent of a NORMAL binary32 (2^-126)
_MAX_NORMAL_EXP = 127   # largest exponent of a NORMAL binary32


@dataclass(frozen=True)
class PoolResult:
    status: str
    # One entry per dimension when status == SEMB_OK; empty otherwise.
    bits: Tuple[int, ...]  # each a 32-bit unsigned int, the binary32 bit pattern

    def bits_hex(self) -> Optional[List[str]]:
        if self.status != SEMB_OK:
            return None
        return [f"0x{b:08x}" for b in self.bits]


def round_to_binary32(r: Fraction) -> Tuple[str, int]:
    """Round the exact rational `r` to the nearest binary32, ties to even,
    under gradual underflow. Returns (kind, bits) where kind is one of
    "zero", "normal", "subnormal", "infinity" and bits is the 32-bit IEEE
    754 pattern (for "infinity", the correctly-signed +-inf pattern).

    Pure integer/Fraction arithmetic throughout -- no float() call, no
    struct.pack of a computed float, anywhere in this function. This is
    the sole place PS-1's rounding rule (item 4: "round-to-nearest-ties-
    to-even applied once, to the exact quotient... no floating-point
    operation appears anywhere on this path") is realized independently of
    any implementation of it.
    """
    if r == 0:
        return ("zero", 0)
    sign_bit = 1 if r < 0 else 0
    m = -r if r < 0 else r  # exact Fraction, > 0

    # Find the integer E such that 2**E <= m < 2**(E+1), by exact
    # comparison against Fraction(2)**E -- no log(), no float division.
    E = 0
    two = Fraction(2)
    if m >= 1:
        while m >= two ** (E + 1):
            E += 1
    else:
        E = -1
        while m < two ** E:
            E -= 1
    assert two ** E <= m < two ** (E + 1)

    if E >= _MIN_NORMAL_EXP:
        exp_field = E
        scale = _MANTISSA_BITS - E  # may be negative for large E
    else:
        # Subnormal range: the exponent is pinned at the minimum normal
        # exponent and the significand loses the bits E is short by --
        # gradual underflow, not flush-to-zero.
        exp_field = _MIN_NORMAL_EXP
        scale = _MANTISSA_BITS - _MIN_NORMAL_EXP  # = 149

    scaled = m * (two ** scale) if scale >= 0 else m / (two ** (-scale))
    # scaled is an exact Fraction >= 0; round to nearest integer, ties to
    # even, using only integer division and remainder comparison.
    num, den = scaled.numerator, scaled.denominator
    q, rem = divmod(num, den)
    twice_rem = 2 * rem
    if twice_rem > den or (twice_rem == den and (q % 2 == 1)):
        q += 1

    if E >= _MIN_NORMAL_EXP:
        if q == (1 << (_MANTISSA_BITS + 1)):
            # Carry out of the significand: bump the exponent, halve back
            # into range (the classic RNE renormalization step).
            q >>= 1
            exp_field += 1
        if exp_field > _MAX_NORMAL_EXP:
            bits = (sign_bit << 31) | (0xFF << 23)  # +-infinity
            return ("infinity", bits)
        biased = exp_field + _EXP_BIAS
        mantissa = q - (1 << _MANTISSA_BITS)
        bits = (sign_bit << 31) | (biased << 23) | mantissa
        return ("normal", bits)
    else:
        if q == (1 << _MANTISSA_BITS):
            # Rounded up across the subnormal/normal boundary: this IS
            # exactly the smallest normal (2^-126), not a subnormal.
            bits = (sign_bit << 31) | (1 << 23) | 0
            return ("normal", bits)
        if q == 0:
            return ("zero", sign_bit << 31)
        bits = (sign_bit << 31) | (0 << 23) | q
        return ("subnormal", bits)


def classify_rounded(kind: str, bits: int) -> Tuple[str, Optional[int]]:
    """kind/bits from round_to_binary32 -> (status, bits-or-None), per sec
    3.2 item 4's "the two corners are one construction and then a
    classification" paragraph -- both triggers are over the ROUNDED
    result."""
    if kind == "zero":
        return (SEMB_OK, bits)
    if kind == "subnormal":
        return (SEMB_POOLED_SUBNORMAL, None)
    if kind == "infinity":
        return (SEMB_POOLED_OVERFLOW, None)
    assert kind == "normal"
    return (SEMB_OK, bits)


def pool_exact(codes: Sequence[Sequence[int]], m: Sequence[int], e: Sequence[int],
               hidden: int) -> PoolResult:
    """codes[t][i] for t in 0..n-1, i in 0..hidden-1; m[t], e[t] the carried
    scale per position. Implements sec 3.2 items 1, 2 and 4 for PS-1."""
    n = len(codes)
    assert len(m) == n and len(e) == n, "codes/m/e length mismatch"
    for row in codes:
        assert len(row) == hidden, "a position's code row does not match `hidden`"

    if n < 2:
        return PoolResult(SEMB_INPUT_TOO_SHORT, ())

    first = 1  # position 0 excluded from pooling (item 2)
    pooled_e = e[first:]
    e_min = min(pooled_e)
    e_max = max(pooled_e)
    if (e_max - e_min) > ACCUMULATOR_SPREAD_BITS:
        return PoolResult(SEMB_ACCUMULATOR_OVERFLOW, ())

    P = n - first  # the POOLED count, never n (item 4's off-by-one warning)
    S = [0] * hidden  # exact Python ints -- unbounded, no wraparound possible
    for t in range(first, n):
        mt = m[t]
        shift = e[t] - e_min
        assert shift >= 0
        row = codes[t]
        for i in range(hidden):
            c = row[i]
            if c != 0:
                S[i] += c * mt * (1 << shift)

    out_bits: List[int] = []
    for i in range(hidden):
        # v_i = (S_i * 2^e_min) / P, exact -- Fraction handles a negative
        # e_min (a right-shift) and a positive one (a left-shift) uniformly
        # via its own integer-power support.
        v_i = Fraction(S[i]) * (Fraction(2) ** e_min) / P
        kind, bits = round_to_binary32(v_i)
        status, rounded_bits = classify_rounded(kind, bits)
        if status != SEMB_OK:
            return PoolResult(status, ())
        out_bits.append(rounded_bits)  # type: ignore[arg-type]

    return PoolResult(SEMB_OK, tuple(out_bits))


# ---------------------------------------------------------------------------
# Self-test -- validates this oracle's own rounding routine independently,
# before it is trusted as a reference for anything else (StandardsDocument
# sec 5.4: "an instrument is commissioned before its verdicts are load-
# bearing"). Every check here is a construction over round_to_binary32
# directly, not over pool_exact, so a defect in the pooling wiring above
# cannot mask a defect in the rounding routine below, or vice versa.
# ---------------------------------------------------------------------------

def _bits_of_float(x: float) -> int:
    return struct.unpack('<I', struct.pack('<f', x))[0]


def _selftest() -> int:
    failures = []

    def check(label: str, r: Fraction, expect_status: str, expect_bits: Optional[int]):
        kind, bits = round_to_binary32(r)
        status, rounded = classify_rounded(kind, bits)
        if status != expect_status or (expect_bits is not None and rounded != expect_bits):
            failures.append(
                f"{label}: r={r} -> status={status} bits={rounded!r}, "
                f"expected status={expect_status} bits={expect_bits!r}")

    # Exact dyadic values: float(Fraction) is exact for these (no
    # double-rounding), so struct.pack('<f', float(r)) is an independent
    # check of THIS module's own hand-rolled rounding for the ordinary
    # (non-corner) case.
    for val in [Fraction(1), Fraction(-1), Fraction(3, 2), Fraction(-5, 4),
                Fraction(0), Fraction(1, 1024), Fraction(1 << 20),
                Fraction(12345, 8), Fraction(-999, 16)]:
        expect = _bits_of_float(float(val))
        expect_status = SEMB_OK
        check(f"dyadic {val}", val, expect_status, expect)

    # Two genuine ties-to-even cases, each verified independently via
    # struct.pack('<f', float(x)) on the exact half-integer value (float()
    # is exact here; no double-rounding). 8388608.5's neighbours are
    # 8388608 (even) and 8388609 (odd) -- ties-to-even rounds DOWN, to the
    # even neighbour. 8388609.5's neighbours are 8388609 (odd) and 8388610
    # (even) -- ties-to-even rounds UP, to the even neighbour. (The prior
    # version's second case, 8388610.5, ALSO rounds down to its own even
    # neighbour 8388610 and was mislabelled '(up)' -- both of the prior
    # cases exercised the round-DOWN branch of the tie rule; no case here
    # exercised round-UP until this correction. TE-76 review F-16.)
    tie_round_down = Fraction(2 * 8388608 + 1, 2)  # 8388608.5
    check("tie-to-even (rounds down, to even neighbour 8388608)", tie_round_down, SEMB_OK,
          0x4B000000)  # 8388608.0
    tie_round_up = Fraction(2 * 8388609 + 1, 2)  # 8388609.5
    check("tie-to-even (rounds up, to even neighbour 8388610)", tie_round_up, SEMB_OK,
          0x4B000002)  # 8388610.0 -- independently confirmed via struct.pack

    # Smallest normal, exactly: 2^-126.
    check("smallest normal", Fraction(1, 2 ** 126), SEMB_OK, 0x00800000)
    # Just below it, but still representable as a subnormal exactly
    # (2^-127 = half the smallest normal, representable as subnormal
    # mantissa 2^22): must be SEMB_OK (subnormals are legal outputs; only
    # the STATUS differs, and 2^-127 rounds to itself exactly, a nonzero
    # subnormal -- which the pooling classifier reports as
    # SEMB_POOLED_SUBNORMAL. round_to_binary32 itself must report kind
    # "subnormal" for it.)
    kind, bits = round_to_binary32(Fraction(1, 2 ** 127))
    if kind != "subnormal":
        failures.append(f"2^-127 should round to a subnormal kind, got {kind}")

    # A rational that is NOT exactly representable and lands strictly
    # between two subnormals close to the smallest normal -- forces a
    # genuine round (not an exact hit), while the module docstring's own
    # boundary is >= smallest-normal in MAGNITUDE for the STATUS decision,
    # taken over the ROUNDED value, not the exact one.
    just_under_smallest_normal = Fraction(1, 2 ** 126) - Fraction(1, 2 ** 150)
    kind, bits = round_to_binary32(just_under_smallest_normal)
    status, _ = classify_rounded(kind, bits)
    if status not in (SEMB_POOLED_SUBNORMAL, SEMB_OK):
        failures.append(f"just-under-smallest-normal misclassified: {status}")

    # Overflow threshold, exact per sec 3.2 item 4: magnitude >=
    # 2^128 - 2^103 rounds to infinity; strictly below (down to the tie
    # point) rounds to the largest finite value 2^128 - 2^104.
    largest_finite = Fraction(2) ** 128 - Fraction(2) ** 104
    check("largest finite", largest_finite, SEMB_OK, 0x7F7FFFFF)
    overflow_threshold = Fraction(2) ** 128 - Fraction(2) ** 103
    kind, bits = round_to_binary32(overflow_threshold)
    if kind != "infinity":
        failures.append(f"overflow threshold {overflow_threshold} did not round to infinity: {kind}")
    just_below_threshold = overflow_threshold - Fraction(1, 2 ** 80)
    kind, bits = round_to_binary32(just_below_threshold)
    if kind != "normal" or bits != 0x7F7FFFFF:
        failures.append(f"just-below-overflow-threshold misrounded: kind={kind} bits={bits:#x}")

    # pool_exact wiring: n=1 refuses; position 0's scale must never affect
    # e_min/e_max (a huge/tiny position-0 scale outside the pooled range
    # must change nothing about the emitted value).
    hidden = 1
    codes_base = [[5], [3], [7]]  # n=3: position 0 (excluded), 1, 2 pooled
    m_base = [1 << 30, 1 << 30, 1 << 30]
    e_base = [-33, -20, -20]  # position 0's exponent is irrelevant
    r1 = pool_exact(codes_base, m_base, e_base, hidden)
    e_base_hi = [500, -20, -20]  # position 0 pushed far outside the pooled range
    r2 = pool_exact(codes_base, m_base, e_base_hi, hidden)
    if r1.status != SEMB_OK or r2.status != SEMB_OK or r1.bits != r2.bits:
        failures.append(f"position-0 scale changed the pooled result: {r1} vs {r2}")

    r_short = pool_exact([[1]], [1 << 30], [-20], 1)
    if r_short.status != SEMB_INPUT_TOO_SHORT:
        failures.append(f"n=1 did not refuse SEMB_INPUT_TOO_SHORT: {r_short}")

    r_overflow_spread = pool_exact([[1], [1], [1]], [1 << 30, 1 << 30, 1 << 30],
                                    [0, 0, 74], 1)
    if r_overflow_spread.status != SEMB_ACCUMULATOR_OVERFLOW:
        failures.append(f"spread 74 did not refuse: {r_overflow_spread}")

    if failures:
        print(f"SELFTEST FAIL: {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("SELFTEST PASS: ps1_reference.py's rounding and pooling wiring "
          "verified against independently-derived boundary and dyadic cases.")
    return 0


def main(argv: List[str]) -> int:
    if argv and argv[0] == "--selftest":
        return _selftest()
    raw = sys.stdin.read()
    req = json.loads(raw)
    result = pool_exact(req["codes"], req["m"], req["e"], req["hidden"])
    print(json.dumps({"status": result.status, "bits_hex": result.bits_hex()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
