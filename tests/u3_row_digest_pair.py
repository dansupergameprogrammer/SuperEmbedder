"""U3 red suite: C10's pairwise row-digest instrument (te266 sec 4.5 C10 (a) and
(e), P:4151, P:4162-4163). The test author's.

C10 (a) compares a GPU and a CPU bake of the 239-document corpus through their
`row-digests.tsv` (the interim certification format, sec 4.1a: `<label>\\t<sha256>`
per row, LF-terminated; tools/check_certified_builds.py reads the same shape).
This instrument derives that file from a bank and compares two of them:

  derive   --bank <stem> --out <tsv>
           per row, SHA-256 of the row's little-endian binary32 bytes in
           <stem>.wvbank.bin, labelled by <stem>.wvbank.json's ids, in order
           (docs/FORMAT.md sec 1); refuses a bin whose size is not count x dims x 4.
  compare  --a <tsv> --b <tsv>
           ACCEPTED only when both are well-formed, carry the same labels in the
           same order, and every row digest is equal; otherwise REFUSED naming
           the first differing rows. Exit 0 / 1.
  selftest the instrument's commissioning (StandardsDocument sec 5.4), portable:
           must-accept   two banks with identical rows -> ACCEPTED;
           (e) 3         a one-byte edit of one row file (the tsv) -> REFUSED;
           must-reject   one bank row differing in one float bit -> REFUSED
                         (the derive path, not only the tsv path, is alive);
           must-reject   a row missing / reordered -> REFUSED.

C10 (e) 2 feeds this instrument the tsv pair u3_gpu_cells_test --cell c10e2
writes, which must be REFUSED; tests/u3_gpu_real_check.py runs (a) through it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

LINE = re.compile(rb"^([^\t\n]+)\t([0-9a-f]{64})$")


class Refused(Exception):
    pass


def derive(stem: str) -> bytes:
    header = json.loads(Path(stem + ".wvbank.json").read_text(encoding="utf-8"))
    count, dims, ids = int(header["count"]), int(header["dims"]), header["ids"]
    data = Path(stem + ".wvbank.bin").read_bytes()
    if len(ids) != count or len(data) != count * dims * 4:
        raise Refused(f"bank {stem}: count {count}, ids {len(ids)}, bin {len(data)} bytes, want {count * dims * 4}")
    out = bytearray()
    for i, rid in enumerate(ids):
        row = data[i * dims * 4:(i + 1) * dims * 4]
        out += str(rid).encode("utf-8") + b"\t" + hashlib.sha256(row).hexdigest().encode() + b"\n"
    return bytes(out)


def parse(data: bytes, name: str) -> list[tuple[bytes, bytes]]:
    if not data.endswith(b"\n"):
        raise Refused(f"{name}: not LF-terminated")
    rows = []
    for n, line in enumerate(data[:-1].split(b"\n"), start=1):
        m = LINE.match(line)
        if not m:
            raise Refused(f"{name}: line {n} is not '<label>\\t<sha256>'")
        rows.append((m.group(1), m.group(2)))
    return rows


def compare(a: bytes, b: bytes, name_a: str = "a", name_b: str = "b") -> str:
    ra, rb = parse(a, name_a), parse(b, name_b)
    if [x[0] for x in ra] != [x[0] for x in rb]:
        raise Refused(f"the labels differ ({len(ra)} rows against {len(rb)}, or reordered)")
    diff = [ra[i][0].decode(errors="replace") for i in range(len(ra)) if ra[i][1] != rb[i][1]]
    if diff:
        raise Refused(f"{len(diff)} of {len(ra)} rows differ; first: {', '.join(diff[:5])}")
    return f"{len(ra)}/{len(ra)} rows identical"


def write_bank(stem: Path, ids: list[str], rows: list[list[float]]) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    Path(str(stem) + ".wvbank.json").write_text(json.dumps(
        {"schemaVersion": 1, "dims": len(rows[0]), "count": len(rows), "metric": "cosine", "dtype": "float32",
         "ids": ids}), encoding="utf-8")
    Path(str(stem) + ".wvbank.bin").write_bytes(b"".join(struct.pack(f"<{len(r)}f", *r) for r in rows))


def selftest() -> int:
    ok = True

    def verdict(passed: bool, cell: str, observed: str) -> None:
        nonlocal ok
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {cell}: {observed}")

    def expect(refuse: bool, cell: str, fn) -> None:
        try:
            got = fn()
            verdict(not refuse, cell, f"ACCEPTED ({got})")
        except Refused as ex:
            verdict(refuse, cell, f"REFUSED ({ex})")

    with tempfile.TemporaryDirectory(prefix="u3_rowpair_") as tmp:
        t = Path(tmp)
        ids = [f"doc-{i:03d}" for i in range(12)]
        rows = [[(i * 7 + j) / 13.0 for j in range(16)] for i in range(12)]
        write_bank(t / "gpu", ids, rows)
        write_bank(t / "cpu", ids, rows)
        a, b = derive(str(t / "gpu")), derive(str(t / "cpu"))
        expect(False, "instrument must-accept: identical banks", lambda: compare(a, b))
        edited = bytearray(a)
        pos = edited.index(b"\t") + 1 + 10  # one hex digit of row 0's digest
        edited[pos] = ord("0") if edited[pos] != ord("0") else ord("1")
        expect(True, "C10 (e) 3: a one-byte edit of one row file is refused (P:4163)",
               lambda: compare(bytes(edited), b))
        bent = [r[:] for r in rows]
        bits = struct.unpack("<I", struct.pack("<f", bent[5][3]))[0] ^ 1
        bent[5][3] = struct.unpack("<f", struct.pack("<I", bits))[0]
        write_bank(t / "gpu_bit", ids, bent)
        expect(True, "instrument must-reject: one float bit in one bank row",
               lambda: compare(derive(str(t / "gpu_bit")), b))
        write_bank(t / "short", ids[:-1], rows[:-1])
        expect(True, "instrument must-reject: a row missing", lambda: compare(derive(str(t / "short")), b))
        write_bank(t / "swapped", [ids[1], ids[0], *ids[2:]], [rows[1], rows[0], *rows[2:]])
        expect(True, "instrument must-reject: two rows reordered", lambda: compare(derive(str(t / "swapped")), b))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("derive")
    d.add_argument("--bank", required=True)
    d.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    c.add_argument("--expect-refused", action="store_true", help="C10 (e) 2: the pair must be REFUSED")
    sub.add_parser("selftest")
    args = ap.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "derive":
        try:
            Path(args.out).write_bytes(derive(args.bank))
        except (Refused, OSError, ValueError, KeyError) as ex:
            print(f"REFUSED derive: {ex}")
            return 1
        print(f"wrote {args.out}")
        return 0
    try:
        got = compare(Path(args.a).read_bytes(), Path(args.b).read_bytes(), args.a, args.b)
        print(f"ACCEPTED {got}")
        refused = False
    except (Refused, OSError) as ex:
        print(f"REFUSED {ex}")
        refused = True
    if args.expect_refused:
        print(f"[{'PASS' if refused else 'FAIL'}] C10 (e) 2: the perturbed pair is "
              f"{'refused' if refused else 'ACCEPTED -- the instrument or the perturbation is dead'}")
        return 0 if refused else 1
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
