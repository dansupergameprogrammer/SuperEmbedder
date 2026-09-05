"""TE-93 structural parity pin for semb_document and semb_encode_batch."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = ROOT / "include" / "superembedder" / "semb.h"
CONTRACT = ROOT / "tests" / "semb_batch_abi_contract.h"


def clean(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def norm(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*([*,()])\s*", r"\1", text)


def declaration(text: str, name: str):
    match = re.search(r"([A-Za-z_][A-Za-z0-9_ ]*?\*?)\s*\b" + name +
                      r"\s*\((.*?)\)\s*;", text, flags=re.S)
    return None if not match else (norm(match.group(1)), norm(match.group(2)))


def members(text: str, name: str):
    match = re.search(r"struct\s+" + name + r"\s*\{(.*?)\};", text, flags=re.S)
    return None if not match else [norm(x) for x in match.group(1).split(";") if x.strip()]


def main() -> int:
    product = clean(PRODUCT.read_text(encoding="utf-8"))
    contract = clean(CONTRACT.read_text(encoding="utf-8"))
    checks = [
        (declaration(product, "semb_encode_batch") == declaration(contract, "semb_encode_batch"),
         "HB-1 semb_encode_batch exact signature"),
        (members(product, "semb_document") == members(contract, "semb_document"),
         "HB-2 semb_document exact member order"),
        (bool(re.search(r"\bSEMB_CORPUS_EMPTY\b", product)),
         "HB-3 SEMB_CORPUS_EMPTY is public and named"),
    ]
    for ok, label in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    return 0 if all(ok for ok, _ in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
