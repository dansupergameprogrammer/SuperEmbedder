"""tests/u1_public_header_parity_check.py -- TE-92, re-entered at TE-94
(D-SLM6314 resolution, P-1..P-5): the structural pin that holds the
builder's PUBLIC header for the frozen `semb_*` surface to the test author's
contract header, declaration by declaration and ordinal by ordinal.

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
       contract's members, in order, `struct_size` first (sec 3.1 item 6;
       P-1: six config members, no appended-token member; P-2: two
       fingerprint members);
  H-5  the status enum: (a) every one of the contract's 18 names is an
       enumerator; (b) each carries its EXPLICIT contract ordinal, in the
       contract's order, 0-17, and SEMB_STATUS_NEXT_FREE is the last
       enumerator with no explicit value (P-5); (c) the enum carries no other
       enumerator -- the retired SEMB_INVALID_ARGUMENT in particular is absent
       everywhere in the header (P-4);
  H-6  the header is C99-shaped by inspection: no C++-only token outside the
       `#ifdef __cplusplus` guard (the compiled strict-C cell K-16,
       tests/u1_public_header_strict_c_check.py, is the executed proof; this
       is the cheap text pin beside it).

THE CONTRACT'S STATUS LIST IS READ FROM THE CONTRACT HEADER'S OWN X-MACRO
(`SEMB_CONTRACT_STATUS_LIST`), never restated here: one generated source.

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
SENTINEL = "SEMB_STATUS_NEXT_FREE"
RETIRED = ["SEMB_INVALID_ARGUMENT"]
CPP_ONLY_TOKENS = ["class", "namespace", "template", "nullptr", "bool", "constexpr", "static_assert", "::", "&&"]


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
    body = m.group(1)
    # The contract's diagnostic-only member is conditional; strip the
    # conditional block so the DEFAULT layout is what is compared.
    body = re.sub(r"#ifdef\s+SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER.*?#endif", " ", body, flags=re.S)
    members = []
    for decl in body.split(";"):
        decl = decl.strip()
        if decl and not decl.startswith("#"):
            members.append(norm(decl))
    return members


def contract_status_list(ctext: str):
    """The ordered (name, ordinal) list from the contract's X-macro."""
    m = re.search(r"#define\s+SEMB_CONTRACT_STATUS_LIST\(X\)(.*?)\n\s*\n", ctext, flags=re.S)
    if not m:
        return None
    pairs = re.findall(r"X\(\s*(SEMB_[A-Z0-9_]+)\s*,\s*(\d+)\s*\)", m.group(1))
    return [(name, int(value)) for name, value in pairs]


def header_enum_body(htext: str):
    m = re.search(r"typedef\s+enum\s+semb_status\s*\{(.*?)\}\s*semb_status\s*;", htext, flags=re.S)
    return m.group(1) if m else None


def header_status_pairs(htext: str, enum_body: str):
    """(name, ordinal) pairs the header's enum carries, in order, under
    either of the two shapes the resolution admits: explicit `NAME = N,`
    enumerators, or an X-macro list `X(NAME, N)` the enum expands."""
    direct = re.findall(r"\b(SEMB_[A-Z0-9_]+)\s*=\s*(\d+)\b", enum_body)
    if direct:
        return [(n, int(v)) for n, v in direct], "explicit enumerators"
    xm = re.search(r"#define\s+(SEMB_[A-Z0-9_]+)\(X\)((?:[^\n]*\\\n)*[^\n]*)", htext)
    if xm and xm.group(1) in enum_body:
        pairs = re.findall(r"X\(\s*(SEMB_[A-Z0-9_]+)\s*,\s*(\d+)\s*\)", xm.group(2))
        return [(n, int(v)) for n, v in pairs], f"X-macro {xm.group(1)}"
    return [], "no explicit ordinals found"


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
    contract_list = contract_status_list(ctext)
    if not contract_list or len(contract_list) != 18:
        print(f"[FAIL] H-0 the contract header's SEMB_CONTRACT_STATUS_LIST parses to 18 entries: got {contract_list}")
        return 1
    if not header.exists():
        print(f"[RED-UNIMPLEMENTED] H-1 the public header exists: {header} does not exist -- the frozen "
              f"sec 3.1 surface has not been built; H-2..H-6 are red-unimplemented, not verified")
        return 1
    verdict(True, "H-1 the public header exists", str(header))
    raw = header.read_text(encoding="utf-8")
    htext = strip_comments(raw)

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
    verdict(not re.search(r"\bappended_token_id\b", htext),
            "H-4c the public header carries no appended_token_id member anywhere (P-1)",
            "absent" if not re.search(r"\bappended_token_id\b", htext) else "PRESENT")

    contract_names = [n for n, _ in contract_list]
    missing = [n for n in contract_names if not re.search(r"\b" + n + r"\b", htext)]
    verdict(not missing, "H-5a every one of the contract's 18 status names is an enumerator in the public header",
            "missing: " + (", ".join(missing) if missing else "none"))
    body = header_enum_body(htext)
    if body is None:
        verdict(False, "H-5b the header declares `typedef enum semb_status { ... } semb_status;`", "not found")
    else:
        pairs, shape = header_status_pairs(htext, body)
        verdict(pairs == contract_list,
                "H-5b the enum carries the contract's 18 names with EXPLICIT ordinals 0-17 in the contract's order (P-5)",
                f"shape={shape}; header={pairs}" if pairs != contract_list else f"shape={shape}; 18 of 18 agree")
        # The sentinel is the last enumerator and carries no explicit value.
        idents = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", body)
        macro_names = set(re.findall(r"#define\s+([A-Za-z_][A-Za-z0-9_]*)", htext))
        semb_idents = [i for i in idents if i.startswith("SEMB_") and i not in macro_names and i != "X"]
        last_semb = semb_idents[-1] if semb_idents else None
        sentinel_explicit = bool(re.search(r"\b" + SENTINEL + r"\s*=", body))
        verdict(last_semb == SENTINEL and not sentinel_explicit,
                "H-5b' SEMB_STATUS_NEXT_FREE is the last enumerator and carries no explicit value (auto-valued 18)",
                f"last={last_semb} explicit_value={sentinel_explicit}")
        extras = sorted(set(semb_idents) - set(contract_names) - {SENTINEL})
        verdict(not extras, "H-5c the enum carries no enumerator outside the contract's list (P-5: append when a verb lands, never ahead of it)",
                "extra: " + (", ".join(extras) if extras else "none"))
    retired_present = [n for n in RETIRED if re.search(r"\b" + n + r"\b", htext)]
    verdict(not retired_present, "H-5d the retired name SEMB_INVALID_ARGUMENT appears nowhere in the public header (P-4)",
            "present: " + (", ".join(retired_present) if retired_present else "none"))

    # H-6: outside the __cplusplus guard, no C++-only token. The guard blocks are
    # `#ifdef __cplusplus ... #endif`; strip them and scan what remains.
    outside = re.sub(r"#ifdef\s+__cplusplus.*?#endif", " ", htext, flags=re.S)
    hits = [t for t in CPP_ONLY_TOKENS if re.search(r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])", outside)]
    verdict(not hits, "H-6 no C++-only token outside the __cplusplus guard (the compiled proof is K-16)",
            "hits: " + (", ".join(hits) if hits else "none"))

    print(f"\nu1_public_header_parity_check: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
