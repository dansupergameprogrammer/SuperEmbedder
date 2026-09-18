"""U1 Slice 7 step 2's structural red test (TE-264; D-SLM7197, D-SLM7205).

`Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.7 step 2 routes the raw
entry through the batch composition: `semb_encode`'s body calls
`ComposeBatch` as a batch of one, and neither calls the tokenizer's `Encode`
on the caller's span nor calls `semb_interim_encode_ps_n`.  Argument
validation and the output copy stay raw-specific, so this check reads only
the three properties the plan names and nothing else about the body.

Cells, each on `semb_encode`'s definition in `src/superembedder/encoder.cpp`
with comments and string/character literals removed first:

  S2-a  the body calls `ComposeBatch(...)` and that call's third argument (the
        document count, `ComposeBatch(h, texts, n, ...)`) is the integer
        literal one;
  S2-b  the body calls no `Encode(` member (`.Encode(` or `->Encode(`) -- the
        tokenizer's own entry point, which the batch composition calls for it;
  S2-c  the body does not name `semb_interim_encode_ps_n`.

Scope, stated rather than implied: this reads the body of `semb_encode` only.
A helper the body calls that itself tokenizes the caller's span or calls the
single-document interim function is outside the text read here; the
behavioural half of step 2 is `tests/u1_raw_text_cells_check.py`'s parity
cells and the raw-equals-batch cell (`tests/te264_raw_equals_batch_test.cpp`).

Vitality: before reading the product, the same predicate is run over four
constructed bodies -- one that satisfies all three cells (must accept) and
three that each break exactly one (must reject on that cell alone).  A
predicate that accepts everything, or refuses everything, fails here before
the product is read.

Exit codes: 0 every cell PASS; 1 any FAIL.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODER = REPO_ROOT / "src" / "superembedder" / "encoder.cpp"

ONE_LITERAL = re.compile(r"^(?:1|1u|1U|1ull|1ULL|1ul|1UL|size_t\{1\}|size_t\(1\)|static_cast<size_t>\(1\))$")


def strip_comments_and_literals(text: str) -> str:
    """Removes // and /* */ comments and the contents of string and character
    literals, keeping the quotes, so a name inside a comment or a message
    string is not read as a call."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
            continue
        if c in "\"'":
            quote = c
            out.append(quote)
            i += 1
            while i < n and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
            out.append(quote)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def function_body(text: str, name: str) -> str | None:
    """The brace-matched body of the one DEFINITION of `name` (a
    declaration ending in `;` is skipped).  None when absent."""
    for m in re.finditer(r"\bsemb_status\s+" + re.escape(name) + r"\s*\(", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        rest = text[i:]
        stripped = rest.lstrip()
        if not stripped.startswith("{"):
            continue
        start = i + (len(rest) - len(stripped))
        depth, j = 0, start
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[start:j + 1]
            j += 1
    return None


def call_arguments(body: str, callee: str) -> list[list[str]]:
    """Every call to `callee` in `body`, as its top-level argument list."""
    calls = []
    for m in re.finditer(r"\b" + re.escape(callee) + r"\s*\(", body):
        depth, i, args, cur = 1, m.end(), [], []
        while i < len(body) and depth:
            ch = body[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            if ch == "," and depth == 1:
                args.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
            i += 1
        args.append("".join(cur).strip())
        calls.append(args)
    return calls


def evaluate(body: str) -> dict[str, tuple[bool, str]]:
    calls = call_arguments(body, "ComposeBatch")
    third = [c[2] if len(c) > 2 else "<missing>" for c in calls]
    a_ok = any(ONE_LITERAL.match(re.sub(r"\s+", "", t)) for t in third)
    encode_calls = re.findall(r"(?:\.|->)\s*Encode\s*\(", body)
    interim = re.findall(r"\bsemb_interim_encode_ps_n\b", body)
    return {
        "S2-a": (a_ok, f"ComposeBatch calls={len(calls)}; third arguments={third}"),
        "S2-b": (not encode_calls, f"tokenizer Encode calls in the body={len(encode_calls)}"),
        "S2-c": (not interim, f"semb_interim_encode_ps_n references in the body={len(interim)}"),
    }


# The constructed bodies the predicate is first proven against.  They are
# test-owned text, not product source.
_COMPLIANT = """{
  if (!enc) return SEMB_NULL_ARGUMENT;
  const std::string_view text(utf8, utf8_len);
  const semb_status s = ComposeBatch(lease.get(), &text, 1, staged.data(), required, &need, nullptr, 0, nullptr);
  std::memcpy(out_vector, staged.data(), required);
  return s;
}"""
_BREAKS = {
    "S2-a": _COMPLIANT.replace("&text, 1,", "&text, count,"),
    "S2-b": _COMPLIANT.replace("const semb_status s =", "auto ids = lease.get()->tokenizer.Encode(text);\n  const semb_status s ="),
    "S2-c": _COMPLIANT.replace("std::memcpy(", "semb_interim_encode_ps_n(interim, ids, n, b, v, r, &q, &d, &e);\n  std::memcpy("),
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--encoder-source", type=Path, default=ENCODER)
    args = ap.parse_args(argv)
    failed = False

    def report(ok: bool, cell: str, detail: str) -> None:
        nonlocal failed
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")
        failed |= not ok

    compliant = evaluate(strip_comments_and_literals(_COMPLIANT))
    report(all(ok for ok, _ in compliant.values()), "vitality: the constructed compliant body is accepted",
           "; ".join(f"{k}={'ok' if v[0] else 'refused'}" for k, v in compliant.items()))
    for cell, text in _BREAKS.items():
        verdict = evaluate(strip_comments_and_literals(text))
        only_this = not verdict[cell][0] and all(ok for k, (ok, _) in verdict.items() if k != cell)
        report(only_this, f"vitality: a constructed body breaking {cell} alone is refused on {cell} alone",
               "; ".join(f"{k}={'ok' if v[0] else 'refused'}" for k, v in verdict.items()))

    try:
        source = args.encoder_source.read_text(encoding="utf-8")
    except OSError as exc:
        report(False, "S2 product source", f"cannot read {args.encoder_source}: {exc}")
        return 1
    body = function_body(strip_comments_and_literals(source), "semb_encode")
    if body is None:
        report(False, "S2 product source", f"no definition of semb_encode in {args.encoder_source}")
        return 1
    names = {
        "S2-a": "semb_encode calls ComposeBatch as a batch of one (D-SLM7197, D-SLM7205)",
        "S2-b": "semb_encode does not call the tokenizer's Encode on the caller's span",
        "S2-c": "semb_encode does not call semb_interim_encode_ps_n",
    }
    for cell, (ok, detail) in evaluate(body).items():
        report(ok, f"{cell} {names[cell]}", detail)
    print(f"\nte264_raw_entry_composition_check: {'FAILED' if failed else 'all cells PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
