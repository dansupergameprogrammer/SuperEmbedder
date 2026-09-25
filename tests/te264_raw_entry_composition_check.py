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

The body under U2-10 (te267 sec 5 U2-10, "The rule"): `semb_encode` is a
boundary, whose definition is a single expression -- a call to one of
`semb::c_boundary`'s templates with a lambda that calls one C++-linkage
function holding the verb's former body. When the definition has exactly that
shape, the body read is the definition's text together with that function's
body (so S2-b and S2-c hold on both, and S2-a is found in the body); any other
definition is read as it stands. Only that one delegation step is followed.

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


# `{ return semb::c_boundary::<Template>([&] { return <Body>(...); }); }`,
# with an optional leading argument before the lambda (the interim family's
# engine-status channel).
BOUNDARY = re.compile(
    r"^\{\s*return\s+(?:::)?semb::c_boundary::\w+\s*\(\s*(?:[^()\[\]{};]*,\s*)?"
    r"\[&\]\s*(?:\(\s*\))?\s*\{\s*return\s+(\w+)\s*\([^;{}]*\)\s*;\s*\}\s*\)\s*;\s*\}$",
    re.S)


def verb_body(text: str, name: str) -> tuple[str | None, str]:
    """The body the S2 cells read for `name`: its definition's body, plus, when
    that definition is a U2-10 boundary, the body of the one function its lambda
    calls.  Returns (body, how it was resolved)."""
    body = function_body(text, name)
    if body is None:
        return None, "no definition"
    m = BOUNDARY.match(body)
    if not m:
        return body, "the definition's own body"
    callee = m.group(1)
    inner = function_body(text, callee)
    if inner is None:
        return None, f"a boundary whose body function {callee} has no definition"
    return body + "\n" + inner, f"the boundary's body function {callee}"


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


# A boundary and its body function, as U2-10 writes them: the compliant pair,
# and pairs whose body function breaks one cell (the delegation must not hide a
# break), plus a boundary whose lambda does the work inline (not the shape, so
# read as it stands: its ComposeBatch call is still found).
_BOUNDARY_TU = """
static semb_status EncodeBody(semb_encoder enc, const char* utf8, size_t utf8_len) BODY
extern "C" semb_status semb_encode(semb_encoder enc, const char* utf8, size_t utf8_len) {
  return semb::c_boundary::Status([&] {
    return EncodeBody(enc, utf8, utf8_len);
  });
}
"""


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

    tu = strip_comments_and_literals(_BOUNDARY_TU.replace("BODY", _COMPLIANT))
    body, how = verb_body(tu, "semb_encode")
    ok = body is not None and all(v for v, _ in evaluate(body).values()) and "EncodeBody" in how
    report(ok, "vitality: a constructed boundary over a compliant body is accepted through its body function", how)
    for cell, text in _BREAKS.items():
        body, how = verb_body(strip_comments_and_literals(_BOUNDARY_TU.replace("BODY", text)), "semb_encode")
        verdict = evaluate(body or "")
        only_this = not verdict[cell][0] and all(ok for k, (ok, _) in verdict.items() if k != cell)
        report(only_this, f"vitality: a constructed boundary whose body function breaks {cell} is refused on {cell}",
               "; ".join(f"{k}={'ok' if v[0] else 'refused'}" for k, v in verdict.items()))
    body, how = verb_body(strip_comments_and_literals(
        _BOUNDARY_TU.replace("BODY", _BREAKS["S2-a"]).replace("return EncodeBody(enc, utf8, utf8_len);",
                                                               "EncodeBody(enc, utf8, utf8_len); return Other();")),
        "semb_encode")
    report(body is not None and "own body" in how and not evaluate(body)["S2-a"][0],
           "vitality: a definition that is not the single-expression boundary is read as it stands (no delegation)",
           how)

    try:
        source = args.encoder_source.read_text(encoding="utf-8")
    except OSError as exc:
        report(False, "S2 product source", f"cannot read {args.encoder_source}: {exc}")
        return 1
    body, how = verb_body(strip_comments_and_literals(source), "semb_encode")
    if body is None:
        report(False, "S2 product source", f"semb_encode in {args.encoder_source}: {how}")
        return 1
    print(f"S2 reads semb_encode through {how}")
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
