// tests/w_b_serialization_test.cpp -- TE-62 (U0 slice B): W-B's
// serialisation, pinned byte-for-byte against sec 4.4b's stated layout
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b, "THE SEAM
// SERIALISATION").
//
// THE ORACLE HERE IS A DIRECT TRANSCRIPTION OF THE SPEC'S OWN BYTE
// LAYOUT, computed by hand in this file (`ExpectedBytes`, below) --
// little-endian throughout: `u64(n) || u64(hidden_size) || for p in
// 0..n-1: codes[p][0..hidden-1] (raw int8) || u64((uint64)m[p]) ||
// u64((uint64)e[p])`, position 0 INCLUDED, every code bit and both scale
// fields included. `ExpectedBytes` takes no input from the product; it is
// pure struct-packing arithmetic against the plan's own prose.
//
// TWO CASES: an ordinary small document (n=3, hidden=2, mixed-sign codes
// and scales) and a construction that would catch a "position 0
// excluded" bug specifically -- the spec is explicit that W-B digests
// EVERY position "position 0 included" (unlike PS-1's own pooling, which
// excludes it) -- so this cell's second case gives position 0 a
// DISTINCTIVE, otherwise-unused code/scale pattern and asserts those
// exact bytes appear at the START of the stream.
//
// RED-UNIMPLEMENTED: `semb_seam_serialize_document` is undefined until
// TE-63 lands it; this executable fails to link.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "semb_seam_abi_contract.h"

namespace {

void PutU64LE(std::vector<uint8_t>* out, uint64_t v) {
  for (int i = 0; i < 8; ++i) out->push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}

// Pure transcription of sec 4.4b's per-document layout -- the expected
// bytes, computed independently of any product call.
std::vector<uint8_t> ExpectedBytes(const std::vector<std::vector<int8_t>>& codes,
                                    const std::vector<int64_t>& m, const std::vector<int64_t>& e,
                                    size_t hidden) {
  std::vector<uint8_t> out;
  const size_t n = codes.size();
  PutU64LE(&out, static_cast<uint64_t>(n));
  PutU64LE(&out, static_cast<uint64_t>(hidden));
  for (size_t p = 0; p < n; ++p) {
    for (size_t i = 0; i < hidden; ++i) out.push_back(static_cast<uint8_t>(codes[p][i]));
    PutU64LE(&out, static_cast<uint64_t>(m[p]));
    PutU64LE(&out, static_cast<uint64_t>(e[p]));
  }
  return out;
}

int g_failures = 0;

void RunCase(const char* label, const std::vector<std::vector<int8_t>>& codes,
             const std::vector<int64_t>& m, const std::vector<int64_t>& e, size_t hidden) {
  const size_t n = codes.size();
  const std::vector<uint8_t> expected = ExpectedBytes(codes, m, e, hidden);

  std::vector<int8_t> flat(n * hidden);
  for (size_t p = 0; p < n; ++p)
    for (size_t i = 0; i < hidden; ++i) flat[p * hidden + i] = codes[p][i];

  std::vector<uint8_t> product_buf(expected.size() + 64, 0xEE);  // poison beyond the expected length
  size_t product_len = 0;
  const SembSerializeStatus st = semb_seam_serialize_document(
      flat.data(), m.data(), e.data(), n, hidden, product_buf.data(), product_buf.size(),
      &product_len);

  if (st != kSembSerializeOk) {
    std::fprintf(stderr, "W-B [%s] FAIL: serialize returned status %d, expected kSembSerializeOk\n",
                 label, static_cast<int>(st));
    ++g_failures;
    return;
  }
  if (product_len != expected.size()) {
    std::fprintf(stderr, "W-B [%s] FAIL: length %zu != expected %zu\n", label, product_len,
                 expected.size());
    ++g_failures;
    return;
  }
  if (std::memcmp(product_buf.data(), expected.data(), expected.size()) != 0) {
    std::fprintf(stderr, "W-B [%s] FAIL: byte layout diverges from sec 4.4b's own spec\n", label);
    ++g_failures;
  }
}

}  // namespace

int main() {
  // Case 1: ordinary small document, n=3 (position 0 through 2), hidden=2,
  // mixed-sign codes and 64-bit scale fields exercising the full 8-byte
  // little-endian width (not just small values that would hide a
  // byte-order bug).
  RunCase("ordinary", {{-128, 127}, {0, -1}, {5, -5}},
          {1 << 30, (1 << 30) + 1, (1LL << 40) + 7}, {-33, 0, 1234567890123LL}, 2);

  // Case 2: position 0's own bytes must appear, verbatim, at the START of
  // the per-document payload (immediately after the two u64 header
  // fields) -- a distinctive code/scale pattern at position 0 that no
  // other position shares, so a bug that skips position 0 (PS-1's own
  // pooling convention, wrongly carried into the serialisation) is
  // caught by a byte-for-byte mismatch at a known offset, not merely a
  // length mismatch.
  RunCase("position-0-included", {{99, -99, 42}, {1, 1, 1}},
          {0x1122334455667788LL, 1 << 30}, {77, -77}, 3);

  if (g_failures) {
    std::fprintf(stderr, "W-B: %d case(s) failed.\n", g_failures);
    return 1;
  }
  std::printf("W-B: byte layout matches sec 4.4b on both cases.\n");
  return 0;
}
