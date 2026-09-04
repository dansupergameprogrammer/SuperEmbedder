"""tests/u1_public_header_parity_check.py -- TE-92: the structural pin that
holds the builder's PUBLIC header for the frozen `semb_*` surface to the
test author's contract header, declaration by declaration.

`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1 freezes the C ABI "enumerated
HERE and nowhere else" (D-SLM4646); tests/semb_public_abi_contract.h is this
suite's concrete pin of the five verbs this slice ships. extern "C" linkage
checks names, never parameter types, so a product header that declared
`semb_encode` with a different parameter list would still link against the
cells and could pass them by accident. This check reads both headers as
text and requires:

  H-1  the product header exists (include/superembedder/semb.h by default);
  H-2  each of the five verbs is declared with the IDENTICAL parameter list
       (whitespace-normalized) and return type;
  H-3  `semb_encoder` is a pointer to an incomplete struct (opaque, not
       copyable as an object): `typedef struct <tag>* semb_encoder;` with no
       `struct <tag> {` definition in the public header;
  H-4  `struct semb_config` and `struct semb_fingerprint` carry exactly the
       contract's members, in order, `struct_size` first (sec 3.1 item 6);
  H-5  every status NAME this slice reaches is an enumerator in the header,
       and SEMB_OK is 0 (the one value the contract pins).

RED-UNIMPLEMENTED at main@1a040a4: the product header does not exist.

Exit codes: 0 all items PASS; 1 any FAIL or the header absent.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "tests" / "semb_public_abi_contract.h"
DEFAULT_HEADER = REPO_ROOT / "include" / "superembedder" / "semb.h"
VERBS = ["semb_encoder_open", "semb_encoder_close", "semb_encoder_dims", "semb_encode", "semb_status_name"]
SLICE_STATUS_NAMES = ["SEMB_OK", "SEMB_NULL_ARGUMENT", "SEMB_STRUCT_SIZE_MISMATCH", "SEMB_INVALID_HANDLE",
                      "SEMB_BUFFER_TOO_SMALL", "SEMB_MISALIGNED_BUFFER", "SEMB_INPUT_EMPTY", "SEMB_ENGINE_REFUSED"]


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*([*,()])\s*", r"\1", s)
    return s


def declaration(text: str, verb: str):
    m = re.search(r"([A-Za-z_][A-Za-z0-9_ ]*?\*?)\s*\b" + verb + r"\s*\((.*?)\)\s*;", text, flags=re.S)
    if not m:
        return None
    return norm(m.group(1)), norm(m.group(2))


def struct_members(text: str, name: str):
    m = re.search(r"struct\s+" + name + r"\s*\{(.*?)\};", text, flags=re.S)
    if not m:
        return None
    members = []
    for decl in m.group(1).split(";"):
        decl = decl.strip()
        if decl:
            members.append(norm(decl))
    return members


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--header", default=str(DEFAULT_HEADER))
    ap.add_argument("--contract", default=str(CONTRACT))
    args = ap.parse_args(argv)
    header = Path(args.header)
    contract = Path(args.contract)
    failures = 0

    def verdict(ok: bool, item: str, observed: str) -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {item}: {observed}")

    if not contract.exists():
        print(f"[FAIL] H-0 the contract header exists: {contract} missing")
        return 1
    ctext = strip_comments(contract.read_text(encoding="utf-8"))
    if not header.exists():
        print(f"[RED-UNIMPLEMENTED] H-1 the public header exists: {header} does not exist -- the frozen "
              f"sec 3.1 surface has not been built; H-2..H-5 are red-unimplemented, not verified")
        return 1
    verdict(True, "H-1 the public header exists", str(header))
    htext = strip_comments(header.read_text(encoding="utf-8"))

    for verb in VERBS:
        cd = declaration(ctext, verb)
        hd = declaration(htext, verb)
        verdict(cd is not None and hd == cd, f"H-2 {verb} declared with the contract's exact signature",
                f"contract={cd} header={hd}")

    m = re.search(r"typedef\s+struct\s+([A-Za-z_][A-Za-z0-9_]*)\s*\*\s*semb_encoder\s*;", htext)
    opaque = bool(m) and not re.search(r"struct\s+" + m.group(1) + r"\s*\{", htext)
    verdict(opaque, "H-3 semb_encoder is a pointer to an incomplete (opaque) struct in the public header",
            f"typedef tag={m.group(1) if m else None}, defined in header={bool(m) and not opaque}")

    for s in ("semb_config", "semb_fingerprint"):
        cm = struct_members(ctext, s)
        hm = struct_members(htext, s)
        verdict(cm is not None and hm == cm and hm[0].startswith("uint32_t struct_size"),
                f"H-4 struct {s} carries exactly the contract's members in order, struct_size first",
                f"contract={cm} header={hm}")

    missing = [n for n in SLICE_STATUS_NAMES if not re.search(r"\b" + n + r"\b", htext)]
    verdict(not missing, "H-5a every status name this slice reaches is an enumerator in the public header",
            "missing: " + (", ".join(missing) if missing else "none"))
    verdict(bool(re.search(r"\bSEMB_OK\s*=\s*0\b", htext)), "H-5b SEMB_OK = 0", "pattern SEMB_OK = 0")

    print(f"\nu1_public_header_parity_check: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
