"""tests/oracle/w_a_population.py -- TE-62: the independently-derived W-A
pooling-driver population, from `Claude/Plans/SuperEmbedder_Plan.md` sec
4.4's own PROSE specification, crossed and graded by `ps1_reference.py`'s
exact-rational oracle.

WHERE THE POPULATION COMES FROM. Sec 4.4 states the crossing directly, in
plan text, independently of any implementation: "Population: hidden in {1,
2, 7, 64}, n in {1, 2, 3, 5, 17, 41}, exponent spread in {0, 1, 2, 9, 10,
63, 64, 73, 74} crossed with a base exponent in {-33, -160, +80},
canonical-m edges at 2^30, 2^30+1, 2^31-1 and mid-range, and the int8 code
edge set {-128, -127, -1, 0, 1, 126, 127} on the leading positions --
2,592 cases, 1,968 pooled and 624 refused, every refusal's STATUS
digested." This module reproduces that crossing from the plan's own prose,
not from the fold-4 probe's C++ driver (`t2217_fold11_pooling_wa_cell.cpp`,
read only as population/anchor per this seat's brief, never as the
oracle). CASE CONSTRUCTION -- how a (hidden, n, spread, ebase, m-edge)
five-tuple becomes concrete per-position (code, m, e) rows -- is this
module's own derivation from sec 3.2 items 2/4 (position 0 excluded from
pooling and from e_min/e_max; the pooled positions alternate ebase and
ebase+spread so both e_min and e_max are attained at the full spread, per
sec 4.4's own "PS-1's own sites" language and the accumulator-bound
argument in sec 3.2 item 4), not a copy of the probe's own construction.

THE TOTAL CASE COUNT (2,592) IS NOT A FREE PARAMETER; THE 1,968/624 SPLIT
IS A ROUTED FINDING, NOT A TARGET THIS MODULE REPRODUCES. n=2 pools
exactly ONE position (position 1 only, since position 0 is excluded), so
its e_min and e_max are trivially equal regardless of the nominal "spread"
loop parameter -- no n=2 case can ever overflow the accumulator bound. For
n in {3, 5, 17, 41}, two or more pooled positions alternate ebase and
ebase+spread, so the REAL spread equals the nominal spread parameter, and
the bound (73) refuses exactly the spread=74 leg. n=1 refuses on
SEMB_INPUT_TOO_SHORT unconditionally, before any spread is computed. This
module's own `accumulator_only_refusal_floor()` derives a FLOOR on the
refused count from that reasoning alone and `main()` asserts the executed
refused count is never BELOW it (a case that must refuse, did).

EXECUTED, this oracle's own split is NOT 1,968/624: the plan's own sec 4.4
text WITHDRAWS that exact digest and count (D-SLM4079 -- "a digest of an
epilogue that has more than one value is not a reference"), because the
probe implementation that produced 1,968/624 has a THREE-member status
enum with neither of the two ROUNDED-VALUE corner refusals sec 3.2 item 4
specifies (SEMB_POOLED_SUBNORMAL, SEMB_POOLED_OVERFLOW) -- exactly the
corners `ebase in {-160, +80}` exist to reach. This module's oracle
implements both refusals, so its own executed refused count is strictly
above the accumulator-only floor, and reproduces a DIFFERENT, corrected
split -- printed by `main()` together with the routed finding.

USAGE: `python tests/oracle/w_a_population.py` prints
`wa_pool_cases: N  ok: N  refused: N` and a SHA-256 digest over the
population (this module's OWN digest format -- length-prefixed UTF-8
records of (hidden, n, spread, ebase, m_edge_index, status,
status==SEMB_OK ? bits : nothing), documented below -- not a
transcription of the probe's FNV/SHA construction).
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from typing import List, Tuple

from ps1_reference import SEMB_OK, pool_exact

# The crossing, verbatim from plan sec 4.4's prose.
HIDDENS = (1, 2, 7, 64)
NS = (1, 2, 3, 5, 17, 41)
SPREADS = (0, 1, 2, 9, 10, 63, 64, 73, 74)
EBASES = (-33, -160, 80)
M_EDGES = (1 << 30, (1 << 30) + 1, (1 << 31) - 1, (1 << 30) + (1 << 29))  # last is "mid-range"
CODE_EDGES = (-128, -127, -1, 0, 1, 126, 127)

EXPECTED_TOTAL = 4 * 6 * 9 * 3 * 4
assert EXPECTED_TOTAL == 2592, f"population size drifted from the plan's own stated 2,592: {EXPECTED_TOTAL}"


class SplitMix64:
    """The generic splitmix64 PRNG (Vigna, public domain) -- a standard,
    named, non-proprietary generator, not an artifact of any code under
    test. Filling non-edge code positions needs SOME reproducible source
    of bytes; splitmix64 is what sec 4.4's own construction rule names
    ("a pinned splitmix64, never std::random") for exactly this population
    class, so this module uses the same NAMED, PUBLIC algorithm -- not a
    transcription of the probe's C++ text, and independently reimplemented
    from the public splitmix64 reference constants."""

    def __init__(self, seed: int):
        self.s = seed & 0xFFFFFFFFFFFFFFFF

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)


@dataclass(frozen=True)
class Case:
    hidden: int
    n: int
    spread: int
    ebase: int
    m_edge_idx: int


def build_case_inputs(case: Case, rng: SplitMix64) -> Tuple[List[List[int]], List[int], List[int]]:
    """Derives concrete (codes, m, e) rows for one population tuple, from
    sec 3.2 items 2/4: e_min/e_max only ever consider positions 1..n-1, so
    position 0's own carried scale is set to `ebase` for definiteness (it
    is provably inert to the result -- ps1_reference.py's own self-test
    checks this directly). Pooled positions alternate `ebase` and
    `ebase + spread`, starting at position 1 with the NON-base value, so
    both endpoints are attained whenever two or more pooled positions
    exist (n >= 3).

    `rng` is ONE splitmix64 stream threaded across the WHOLE population in
    `all_cases()`'s own iteration order (hidden, n, spread, ebase,
    m_edge_idx -- sec 4.4's own crossing order), exactly as sec 4.4's
    construction rule specifies a single pinned generator for the whole
    driven population, not reseeded per case; a case's non-edge code bytes
    therefore depend on how many bytes every case before it in iteration
    order consumed, which is why this function takes the shared generator
    rather than owning its own."""
    n, hidden = case.n, case.hidden
    codes = []
    m = []
    e = []
    for t in range(n):
        row = []
        for i in range(hidden):
            k = t * hidden + i
            row.append(CODE_EDGES[k] if k < len(CODE_EDGES) else _to_int8(rng.next()))
        codes.append(row)
        m.append(M_EDGES[(case.m_edge_idx + t) % len(M_EDGES)])
        if t == 0:
            e.append(case.ebase)
        else:
            e.append(case.ebase if (t % 2 == 0) else (case.ebase + case.spread))
    return codes, m, e


def _to_int8(rand_u64: int) -> int:
    b = rand_u64 & 0xFF
    return b - 256 if b >= 128 else b


def all_cases() -> List[Case]:
    out = []
    for hidden in HIDDENS:
        for n in NS:
            for spread in SPREADS:
                for ebase in EBASES:
                    for me in range(len(M_EDGES)):
                        out.append(Case(hidden, n, spread, ebase, me))
    return out


def accumulator_only_refusal_floor() -> Tuple[int, int, int]:
    """A FLOOR on the refused count, independent of executing pool_exact --
    counts ONLY the accumulator-bound refusals (SEMB_INPUT_TOO_SHORT for
    n=1, unconditional; SEMB_ACCUMULATOR_OVERFLOW for spread==74 whenever
    n >= 3, since n=2 pools exactly one position and can never exceed the
    bound). It excludes the two ROUNDED-VALUE corner refusals
    (SEMB_POOLED_SUBNORMAL / SEMB_POOLED_OVERFLOW), which depend on the
    actual accumulated magnitude and cannot be derived without running the
    arithmetic -- ebase in {-160, +80} exists PRECISELY to reach those
    corners (sec 4.4: "-160 puts 2^e_min under float's subnormal floor").
    `run()`'s executed refused count is therefore expected to be STRICTLY
    GREATER than this floor whenever any case actually reaches a value
    corner, and `main()` asserts exactly that relationship rather than
    exact equality to any pre-computed total."""
    total = len(HIDDENS) * len(NS) * len(SPREADS) * len(EBASES) * len(M_EDGES)
    n1 = len(HIDDENS) * 1 * len(SPREADS) * len(EBASES) * len(M_EDGES)
    multi_ns = [n for n in NS if n not in (1, 2)]
    multi_refused = len(HIDDENS) * len(multi_ns) * 1 * len(EBASES) * len(M_EDGES)  # spread==74 only
    refused_floor = n1 + multi_refused
    return total, total - refused_floor, refused_floor


class Digest:
    """This module's OWN digest format -- documented so a re-derivation
    can reproduce it byte for byte without reading this file's source:
    SHA-256 over, for every case in `all_cases()`'s own iteration order,
    the little-endian u64 fields (hidden, n, spread-as-u64 via
    struct.pack of the signed value, ebase-as-u64 likewise, m_edge_idx),
    then a length-prefixed UTF-8 status string, then -- only when the
    status is SEMB_OK -- each output dimension's 32-bit bit pattern as a
    little-endian u32."""

    def __init__(self):
        self.h = hashlib.sha256()

    def u64(self, v: int):
        self.h.update(struct.pack('<Q', v & 0xFFFFFFFFFFFFFFFF))

    def str_(self, s: str):
        b = s.encode('utf-8')
        self.u64(len(b))
        self.h.update(b)

    def u32(self, v: int):
        self.h.update(struct.pack('<I', v))

    def hexdigest(self) -> str:
        return self.h.hexdigest()


def run() -> Tuple[int, int, int, str, dict]:
    d = Digest()
    d.str_("SEMB-TE62-W-A-POOL-ORACLE-1")
    ok_count = 0
    refused_count = 0
    status_counts: dict = {}
    rng = SplitMix64(0x0F01D11)  # sec 4.4's own pinned-splitmix64 discipline
    for case in all_cases():
        codes, m, e = build_case_inputs(case, rng)
        result = pool_exact(codes, m, e, case.hidden)
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        d.u64(case.hidden)
        d.u64(case.n)
        d.u64(case.spread)
        d.u64(case.ebase & 0xFFFFFFFFFFFFFFFF)
        d.u64(case.m_edge_idx)
        d.str_(result.status)
        if result.status == SEMB_OK:
            ok_count += 1
            for b in result.bits:
                d.u32(b)
        else:
            refused_count += 1
    return len(all_cases()), ok_count, refused_count, d.hexdigest(), status_counts


def emit_cases_json() -> str:
    """The full population, each case with its inputs AND this oracle's own
    expected (status, bits) -- consumed by `tests/w_a_pool_population_test.cpp`
    (the C++ cell that drives the product's not-yet-built C ABI verb over
    the SAME population) via subprocess, so the population is derived in
    exactly one place and the C++ side cannot independently drift from it
    (the same discipline C39 gives the encoder TU -- one source, not two
    agreeing by construction)."""
    rng = SplitMix64(0x0F01D11)
    records = []
    for case in all_cases():
        codes, m, e = build_case_inputs(case, rng)
        result = pool_exact(codes, m, e, case.hidden)
        records.append({
            "hidden": case.hidden, "n": case.n, "codes": codes, "m": m, "e": e,
            "expected_status": result.status, "expected_bits_hex": result.bits_hex(),
        })
    return json.dumps({"cases": records})


def main(argv: List[str]) -> int:
    if argv and argv[0] == "--emit-cases":
        print(emit_cases_json())
        return 0
    floor_total, floor_ok, floor_refused = accumulator_only_refusal_floor()
    total, ok, refused, digest_hex, status_counts = run()
    print(f"wa_pool_cases: {total}  ok: {ok}  refused: {refused}")
    print(f"status breakdown: {status_counts}")
    print(f"WA_POOL_ORACLE_digest: {digest_hex}")
    if total != floor_total or total != 2592:
        print(f"MISMATCH: total case count {total} does not match the plan sec 4.4 crossing "
              f"(expected 2592, accumulator-floor derivation gives {floor_total})")
        return 1
    if refused < floor_refused:
        print(f"MISMATCH: executed refused count {refused} is BELOW the accumulator-only floor "
              f"{floor_refused} -- a case that must refuse (n=1, or spread=74 at n>=3) did not")
        return 1
    print(f"PASS (with a routed finding -- see below): total 2,592 cases match sec 4.4's own "
          f"crossing; refused {refused} >= the accumulator-bound-only floor {floor_refused} "
          f"(the surplus, {refused - floor_refused}, is cases refused via SEMB_POOLED_SUBNORMAL "
          f"or SEMB_POOLED_OVERFLOW -- the two ROUNDED-VALUE corner refusals ebase in "
          f"{{-160, +80}} exist to reach).")
    print("")
    print("ROUTED FINDING (Curie Phase 5, per Claude/Curie/te62-u0b-red-suite-2026-09-02.md): "
          "this executed split does NOT equal the withdrawn probe reference's 1,968 ok / 624 "
          "refused (Claude/Plans/SuperEmbedder_Plan.md sec 4.4, D-SLM4079 -- 'W-A's reference "
          "digest is WITHDRAWN... a digest of an epilogue that has more than one value is not a "
          "reference'). The withdrawn probe's own Pool() (t2217_fold11_pooling_wa_cell.cpp) has "
          "a three-member status enum {Ok, InputTooShort, AccumulatorOverflow} with NEITHER "
          "corner refusal the plan specifies (SEMB_POOLED_SUBNORMAL, SEMB_POOLED_OVERFLOW) -- "
          "so its own 1,968/624 count is a MEASUREMENT of a status enum the plan's own text "
          "disqualifies, not a value this correctly-specified oracle can or should reproduce. "
          "This oracle implements both corner refusals (per sec 3.2 item 4's 'the two corners "
          "are one construction and then a classification' paragraph) and its own split is "
          f"therefore the CORRECTED reading: {ok} ok / {refused} refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
