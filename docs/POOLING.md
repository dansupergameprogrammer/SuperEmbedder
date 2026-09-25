# Pooling: PS-N

This page is normative. It specifies how SuperEmbedder turns a text into the vector it emits. An
implementation that follows it produces the same bytes; one that departs from it anywhere is a different
encoder. The scheme is labelled `PS-N`, and every bank manifest records that label as `label:ps_version`.

## 1. Composition

Composition turns the caller's text into the token sequence the engine runs.

**A document** is tokenized exactly as given. There is no document frame: no prefix, no suffix, no
instruction. The text must be valid UTF-8 and non-empty; empty text is refused (`SEMB_INPUT_EMPTY`).

**A query** is the fixed prefix below, followed immediately by the caller's text, with nothing between them:

```text
Instruct: Given a web search query, retrieve relevant passages that answer the query
Query:
```

The prefix is those exact bytes: the first line, one LF (`0x0A`), then `Query:` with no trailing space or
newline. The query entry points (`semb_query_encode`, `semb_encode_query`, `semb query`) apply it; the
document entry points (`semb_encode`, `semb_encode_batch`, `semb bake`) never do. A caller must not add it
to a query itself.

**Tokenization** uses the tokenizer artifact the encoder was opened with, with Unicode 15.1.0 tables. A
special-token literal that appears in the text (for example `<|endoftext|>`) is encoded as that special
token, not as its characters. This matches the reference tokenizer's default.

**The end token.** After tokenization, the id of `<|endoftext|>` is appended exactly once. The id is resolved
when the encoder opens, from the tokenizer artifact's own vocabulary (for the shipped tokenizer it is
151643); it is not configurable. A tokenizer that does not carry `<|endoftext|>` is refused at open
(`SEMB_TEMPLATE_TOKEN_ABSENT`).

**Length.** Let *n* be the number of ids after the end token is appended, and *cap* the model's context
(32,768 for the shipped model).

- A **document** whose *n* exceeds *cap* is refused (`SEMB_CONTEXT_CAP_EXCEEDED`). It is never truncated.
- A **query** is truncated, by design, to *cap* − 1 content ids before the end token is appended, and the
  call returns `SEMB_OK`. The composed length reported before truncation can therefore exceed *cap*; that is
  not a disagreement.
- A document of a single token is valid.

## 2. The forward

The composed ids run through the engine's integer forward. For every position, the engine's final
normalization emits the hidden state as a triple:

- `codes`: *d* signed 8-bit integers, where *d* is the model's hidden size (1,024 for the shipped model);
- `m`: a signed 64-bit integer mantissa, shared by the row;
- `e`: a signed 64-bit integer exponent, shared by the row.

Element *i* of that row has the exact value `codes[i] · m · 2^e`.

## 3. Selection

PS-N selects **one** position: the **last** one, which is the appended end token. No positions are averaged
or combined, so there is no accumulator, no exponent alignment across positions, and no division.

## 4. Dequantization

The selected triple is turned into *d* IEEE-754 `binary32` values, one per element, entirely in integer
arithmetic:

1. **Domain.** If |`e`| > 1,000,000 the encode is refused before any shift is performed.
2. **Zero.** If `codes[i]` = 0 or `m` = 0, element *i* is `+0.0f` (bit pattern `0x00000000`).
3. **Otherwise**, element *i* is the exact rational *r* = `codes[i]` · `m` · 2^`e`, with sign
   negative exactly when `codes[i]` and `m` have opposite signs. Its `binary32` bit pattern is constructed
   from *r* in integer code:
   - find the binary exponent *E* with 2^*E* ≤ |*r*| < 2^(*E*+1) by exact comparison;
   - scale |*r*| to a 24-bit integer significand (narrower below 2^−126, gradual underflow) and apply
     **round-to-nearest, ties-to-even once**, to the exact remainder;
   - if rounding carries the significand to 2^24, halve it and increment *E*.
4. **Corners, judged on the rounded result:**
   - rounded to zero: the signed zero with *r*'s sign;
   - rounded to a non-zero value below 2^−126 (a subnormal): the encode is refused
     (`SEMB_POOLED_SUBNORMAL`);
   - rounded beyond the largest finite `binary32`: the encode is refused (`SEMB_POOLED_OVERFLOW`);
   - otherwise the normal value.

No floating-point instruction computes any element: the bit pattern is assembled from integers and copied
into the caller's buffer. This is why the output does not depend on the calling thread's rounding mode,
flush-to-zero state or exception masks.

## 5. Output

The vector is the *d* elements in order, as native `binary32`, **not normalized**. Its L2 norm is whatever
the model produced. Cosine search over it must normalize; SuperFAISS does so when a bank is declared
`"metric": "cosine"`, which every SuperEmbedder bank is.

## 6. Identity

The query prefix, the (empty) document frame and the end-token literal are digested into the encoder
fingerprint's `template_sha256` field, so a change to any of them changes the fingerprint. See
[DETERMINISM.md](DETERMINISM.md#what-the-fingerprint-covers).
