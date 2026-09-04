"""tests/oracle/ps_n_reference.py -- the independent, exact-rational reference
oracle for PS-N's single-position dequantize construction
(`Claude/Plans/SuperEmbedder_Plan.md` sec 3.2, "PS-N's arithmetic"; sec 8,
C1' -- "the library's PS-N vector -- the selected position's {codes, m, e}
dequantized by item 4's integer-exact construction, emitted RAW -- equals an
independent Python exact-rational reference for that SAME position, bit for
bit").

WHAT THIS IS. PS-N pools nothing: it selects one position's `{codes, m, e}`
(the document's last token, post-final-norm, sec 3.2) and dequantizes it.
Each emitted element is the binary32 nearest the EXACT rational
`v_i = c_i * m * 2^e`, round-to-nearest-ties-to-even applied once, under
gradual underflow, then classified over the ROUNDED result: a non-zero
result below 2^-126 is SEMB_POOLED_SUBNORMAL, a result that rounds to
infinity is SEMB_POOLED_OVERFLOW, and an exact zero is the ordinary value
+0.0 (sec 3.2 item 4's own corner discipline, unchanged by the scheme
switch -- "PS-N needs only item 4's existing integer-exact construction ...
applied to one (c, m, e) triple instead of a pooled sum").

WHAT THIS TAKES NO INPUT FROM. This module reuses `tests/oracle/
ps1_reference.py`'s `round_to_binary32`/`classify_rounded` -- the rounding
rule derived there from IEEE 754-2008 first principles over `fractions.
Fraction`, never from any C++ implementation -- and composes them over a
single triple rather than a pooled sum. No value here is produced by the
code under test; the instrument's dump (`semb_c12b_row_digest
--dump-selected`) supplies the INPUT triple and the EMITTED bits, and this
module recomputes the bits from the triple alone.

The selection itself (WHICH position, and the final-norm applied to it) is
the engine's arithmetic and is not re-derived here -- that is C12b's own
per-row seam digest and the engine's own reference chain; this oracle
grades exactly the dequantize step, C1''s own claim.

USAGE
  python tests/oracle/ps_n_reference.py --selftest
  python tests/oracle/ps_n_reference.py --check <dump.tsv>
    dump.tsv rows: <label>\\t<status>\\t<m>\\t<e>\\t<c0,c1,...>\\t<bits0,bits1,... as 8-hex>
    (bits column empty when status != SEMB_OK)

Exit codes: 0 every row agrees; 1 disagreement or usage; 2 self-test failure.
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path
from typing import Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ps1_reference import (  # noqa: E402
    SEMB_OK,
    SEMB_POOLED_OVERFLOW,
    SEMB_POOLED_SUBNORMAL,
    classify_rounded,
    round_to_binary32,
)

SEMB_E_MIN_DOMAIN_EXCEEDED = "SEMB_E_MIN_DOMAIN_EXCEEDED"
# Mirrors the product's own |e| domain (include/superembedder/pool_abi.h,
# kSembWaPoolMaxAbsEMin): refused BEFORE any shift, so the oracle's own
# Fraction(2)**e never materialises a multi-million-bit value either.
E_DOMAIN = 1_000_000


def dequantize_exact(codes: Sequence[int], m: int, e: int) -> Tuple[str, Tuple[int, ...]]:
    """(status, bits) for one selected position. bits is one 32-bit pattern
    per dimension when status == SEMB_OK, else empty."""
    if e > E_DOMAIN or e < -E_DOMAIN:
        return (SEMB_E_MIN_DOMAIN_EXCEEDED, ())
    scale = Fraction(2) ** e  # exact for negative e too (Fraction(1, 2**-e))
    out = []
    for c in codes:
        if not (-128 <= c <= 127):
            raise ValueError(f"code {c} outside int8")
        r = Fraction(c * m) * scale
        kind, bits = round_to_binary32(r)
        status, bits2 = classify_rounded(kind, bits)
        if status != SEMB_OK:
            return (status, ())
        out.append(bits2)
    return (SEMB_OK, tuple(out))


def _selftest() -> int:
    fails = 0

    def check(label, codes, m, e, expect_status, expect_bits):
        nonlocal fails
        st, bits = dequantize_exact(codes, m, e)
        ok = st == expect_status and (expect_bits is None or list(bits) == expect_bits)
        print(f"{'ok  ' if ok else 'FAIL'} {label}: status={st} bits={[f'0x{b:08x}' for b in bits]}")
        if not ok:
            fails += 1

    check("1.0 exactly (c=1, m=2^30, e=-30)", [1], 1 << 30, -30, SEMB_OK, [0x3F800000])
    check("-1.5 exactly", [-3], 1 << 30, -31, SEMB_OK, [0xBFC00000])
    check("exact zero code -> +0.0", [0], 1 << 30, -30, SEMB_OK, [0x00000000])
    check("1 + 2^-30 rounds down to 1.0 (RNE)", [1], (1 << 30) + 1, -30, SEMB_OK, [0x3F800000])
    # 1 + 2^-24 is exactly half an ulp above 1.0 (ulp at 1.0 is 2^-23): ties to EVEN -> 1.0.
    check("tie at half-ulp above 1.0 -> even (1.0)", [1], (1 << 30) + (1 << 6), -30, SEMB_OK, [0x3F800000])
    # 1 + 3*2^-24 ties to the ODD neighbour's other side: 1 + 2^-23 + 2^-24 -> rounds up to 1 + 2^-22.
    check("tie at 1 + 3*2^-24 -> even (1 + 2^-22)", [1], (1 << 30) + (3 << 6), -30, SEMB_OK, [0x3F800002])
    check("subnormal refused (2^-130)", [1], 1 << 30, -160, SEMB_POOLED_SUBNORMAL, None)
    check("overflow refused (~2^137)", [127], (1 << 31) - 1, 100, SEMB_POOLED_OVERFLOW, None)
    check("e domain refused", [1], 1 << 30, 2 ** 32, SEMB_E_MIN_DOMAIN_EXCEEDED, None)
    check("mixed row", [1, -1, 0, 127], 1 << 30, -30, SEMB_OK,
          [0x3F800000, 0xBF800000, 0x00000000, 0x42FE0000])
    # A refusal on ONE element refuses the whole position (matches the product's own rule).
    # 64*2^30*2^-157 = 2^-121 (normal); 1*2^30*2^-157 = 2^-127 (subnormal): one element refuses the row.
    check("one subnormal element refuses the row", [64, 1], 1 << 30, -157, SEMB_POOLED_SUBNORMAL, None)
    check("the same row one bit up is accepted (2^-120, 2^-126)", [64, 1], 1 << 30, -156, SEMB_OK,
          [0x03800000, 0x00800000])
    print("selftest:", "PASS" if fails == 0 else f"FAIL ({fails})")
    return 0 if fails == 0 else 2


def check_dump(path: Path) -> int:
    rows = 0
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 6:
            print(f"MALFORMED: {line[:80]}")
            bad += 1
            continue
        label, status, m_s, e_s, codes_s, bits_s = parts
        codes = [int(x) for x in codes_s.split(",")] if codes_s else []
        emitted = [int(x, 16) for x in bits_s.split(",")] if bits_s else []
        exp_status, exp_bits = dequantize_exact(codes, int(m_s), int(e_s))
        rows += 1
        if exp_status != status or list(exp_bits) != emitted:
            bad += 1
            print(f"DISAGREE {label}: product status={status} bits[:4]={[f'0x{b:08x}' for b in emitted[:4]]} "
                  f"oracle status={exp_status} bits[:4]={[f'0x{b:08x}' for b in exp_bits[:4]]}")
    print(f"ps_n_reference: {rows} rows checked, {bad} disagree")
    return 0 if rows > 0 and bad == 0 else 1


def main(argv):
    if argv == ["--selftest"]:
        return _selftest()
    if len(argv) == 2 and argv[0] == "--check":
        return check_dump(Path(argv[1]))
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
