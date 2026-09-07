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
  H-5  the status enum: (a) every one of the contract's N names is an
       enumerator (N read from the contract's own X-macro, never restated
       here -- TE-145 grew it from 18 to 22); (b) each carries its EXPLICIT
       contract ordinal, in the contract's order, 0..N-1, and
       SEMB_STATUS_NEXT_FREE is the last enumerator with no explicit value
       (P-5); (c) the enum carries no other enumerator -- the retired
       SEMB_INVALID_ARGUMENT in particular is absent everywhere in the header
       (P-4);
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

# TE-159 item 4 (S-4, D-SLM6353's sibling finding): the batch struct contract
# and the seam ceiling mirror, both hand-synced duplicates the TE-148 review
# found unpinned by any cell (S-3, S-4).
BATCH_CONTRACT = REPO_ROOT / "tests" / "semb_batch_abi_contract.h"
SEAM_HEADER = REPO_ROOT / "include" / "superembedder" / "seam_abi.h"
SEAM_CONTRACT = REPO_ROOT / "tests" / "semb_seam_abi_contract.h"
CEILING_NAME = "kSembWitnessMaxHidden"


def ceiling_value(text: str, name: str):
    """The integer literal a `constexpr size_t <name> = N;` declaration
    carries, or None if no such declaration is found."""
    m = re.search(r"constexpr\s+size_t\s+" + re.escape(name) + r"\s*=\s*(\d+)\s*;", text)
    return int(m.group(1)) if m else None


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
    # TE-145: the count is READ from the contract's own X-macro, never
    # restated as a literal here -- the contract header's own comment states
    # the append-only law this script must track, not re-fix, on every append.
    n_statuses = len(contract_list) if contract_list else 0
    if not contract_list:
        print(f"[FAIL] H-0 the contract header's SEMB_CONTRACT_STATUS_LIST parses to at least one entry: got {contract_list}")
        return 1
    # H-0b (TE-159 item 6, M-3): the count itself stays UNPINNED by a literal
    # (deliberate, TE-145's own design -- restating N here as a hardcoded
    # number is exactly the decaying-literal shape this file's own docstring
    # rejects), but the contract's OWN internal structure is now checked:
    # its ordinals are the contiguous set 0..N-1 with no gap and no
    # duplicate. This is what "lost pin" actually named -- not the count's
    # absolute value, but that nothing verified the parsed list was even
    # internally well-formed before it became every other check's baseline.
    ordinals = sorted(v for _, v in contract_list)
    if ordinals != list(range(n_statuses)):
        print(f"[FAIL] H-0b the contract's own ordinals are exactly 0..{n_statuses - 1} with no gap or "
              f"duplicate: got {ordinals}")
        return 1
    print(f"[PASS] H-0b the contract's own {n_statuses} ordinals are exactly 0..{n_statuses - 1}, no gap or duplicate")
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

    # H-4d (TE-159 item 4, S-3, TE-96 sec 4.7's own named obligation): the
    # product's semb_document (include/superembedder/semb.h) and the test
    # author's own pin (tests/semb_batch_abi_contract.h) are two INDEPENDENT
    # struct definitions -- extern "C" linkage checks names, never layout,
    # so nothing before this check compared them. Reordering a member in
    # either copy left the whole suite green (S-3's own reproduction);
    # mutation-proved: flipping id/id_len in a scratch copy of either file
    # turns this line red (see this round's own build record).
    if not BATCH_CONTRACT.exists():
        verdict(False, "H-4d the batch contract header exists", f"{BATCH_CONTRACT} missing")
    else:
        batch_ctext = strip_comments(BATCH_CONTRACT.read_text(encoding="utf-8"))
        bm = struct_members(batch_ctext, "semb_document")
        hm2 = struct_members(htext, "semb_document")
        verdict(bm is not None and hm2 is not None and hm2 == bm and hm2[0].startswith("uint32_t struct_size"),
                "H-4d struct semb_document carries exactly the batch contract's five members in order, "
                "struct_size first (TE-96 sec 4.7)",
                f"contract={bm} header={hm2}")

    contract_names = [n for n, _ in contract_list]
    missing = [n for n in contract_names if not re.search(r"\b" + n + r"\b", htext)]
    verdict(not missing, f"H-5a every one of the contract's {n_statuses} status names is an enumerator in the public header",
            "missing: " + (", ".join(missing) if missing else "none"))
    body = header_enum_body(htext)
    if body is None:
        verdict(False, "H-5b the header declares `typedef enum semb_status { ... } semb_status;`", "not found")
    else:
        pairs, shape = header_status_pairs(htext, body)
        verdict(pairs == contract_list,
                f"H-5b the enum carries the contract's {n_statuses} names with EXPLICIT ordinals 0-{n_statuses - 1} in the contract's order (P-5)",
                f"shape={shape}; header={pairs}" if pairs != contract_list else f"shape={shape}; {n_statuses} of {n_statuses} agree")
        # The sentinel is the last enumerator and carries no explicit value.
        idents = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", body)
        macro_names = set(re.findall(r"#define\s+([A-Za-z_][A-Za-z0-9_]*)", htext))
        semb_idents = [i for i in idents if i.startswith("SEMB_") and i not in macro_names and i != "X"]
        last_semb = semb_idents[-1] if semb_idents else None
        sentinel_explicit = bool(re.search(r"\b" + SENTINEL + r"\s*=", body))
        verdict(last_semb == SENTINEL and not sentinel_explicit,
                f"H-5b' SEMB_STATUS_NEXT_FREE is the last enumerator and carries no explicit value (auto-valued {n_statuses})",
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

    # H-7 (TE-159 item 4, S-4, D-SLM6353's sibling): kSembWitnessMaxHidden is
    # a hand-synced duplicate between the product seam header and the test
    # suite's own mirror (tests/semb_seam_abi_contract.h does not include
    # seam_abi.h -- confirmed by reading its own #include list, S-4's own
    # finding). The verb takes no capacity parameter, so the buffer size
    # every mirror-reading cell allocates and the refusal bound the product
    # verb enforces must agree, or a future raise on one side alone
    # overflows the other's buffers silently. Mutation-proved: changing
    # either file's own literal alone turns this line red.
    if not SEAM_HEADER.exists() or not SEAM_CONTRACT.exists():
        verdict(False, "H-7 both seam ceiling files exist",
                f"header={SEAM_HEADER.exists()} contract={SEAM_CONTRACT.exists()}")
    else:
        seam_htext = strip_comments(SEAM_HEADER.read_text(encoding="utf-8"))
        seam_ctext = strip_comments(SEAM_CONTRACT.read_text(encoding="utf-8"))
        header_ceiling = ceiling_value(seam_htext, CEILING_NAME)
        contract_ceiling = ceiling_value(seam_ctext, CEILING_NAME)
        verdict(header_ceiling is not None and header_ceiling == contract_ceiling,
                f"H-7 {CEILING_NAME} agrees between {SEAM_HEADER.name} and {SEAM_CONTRACT.name}",
                f"header={header_ceiling} contract={contract_ceiling}")

    print(f"\nu1_public_header_parity_check: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
