// tests/w_a_pool_population_test.cpp -- TE-62 (U0 slice B): the W-A
// population reproduced as a cell (`Claude/Plans/SuperEmbedder_Plan.md`
// sec 4.4, sec 8's C37 row) -- 2,592 cases from sec 4.4's own stated
// crossing, driven through the product's `semb_wa_pool_run` and compared
// against `tests/oracle/w_a_population.py`'s independent, exact-rational
// oracle, one case at a time, with every refusal's STATUS checked (never
// only the OK rows).
//
// THE POPULATION IS DERIVED IN EXACTLY ONE PLACE: `tests/oracle/
// w_a_population.py` (Python, sec 4.4's own prose crossing, sec 4.4's own
// named splitmix64 discipline). This file does not reconstruct the
// crossing in C++ -- it asks the oracle to `--emit-cases` (every case's
// inputs AND this oracle's own expected status/bits) and drives the
// product over exactly that population, so the population cannot
// independently drift between a C++ copy and the Python original (the
// same discipline C39 gives the encoder TU: one source, not two files
// agreeing by construction).
//
// THIS CELL'S OWN EXECUTED SPLIT (1,563 ok / 1,029 refused, see
// `tests/oracle/w_a_population.py`'s own `main()`) IS A ROUTED FINDING,
// NOT THE WITHDRAWN PROBE'S 1,968/624 -- documented in full in
// `Claude/Curie/te62-u0b-red-suite-2026-09-02.md`.
//
// RED-UNIMPLEMENTED: `semb_wa_pool_run` is undefined until TE-63 lands
// it; this executable fails to link.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "json_mini.h"
#include "semb_wa_pool_abi_contract.h"
#include "subprocess_util.h"

namespace {

SembWaPoolStatus StatusFromString(const std::string& s) {
  if (s == "SEMB_OK") return kSembOk;
  if (s == "SEMB_INPUT_TOO_SHORT") return kSembInputTooShort;
  if (s == "SEMB_ACCUMULATOR_OVERFLOW") return kSembAccumulatorOverflow;
  if (s == "SEMB_POOLED_SUBNORMAL") return kSembPooledSubnormal;
  if (s == "SEMB_POOLED_OVERFLOW") return kSembPooledOverflow;
  std::fprintf(stderr, "w_a_pool_population_test: unrecognised oracle status '%s'\n", s.c_str());
  std::abort();
}

}  // namespace

int main() {
  const std::string cmd =
      semb_test::PythonExecutable() + " tests/oracle/w_a_population.py --emit-cases";
  std::string stdout_text;
  try {
    stdout_text = semb_test::RunCaptureStdout(cmd);
  } catch (const std::exception& ex) {
    std::fprintf(stderr, "w_a_pool_population_test: could not run the oracle: %s\n", ex.what());
    return 1;
  }
  const json_mini::Value doc = json_mini::Parse(stdout_text);
  const auto& cases = doc["cases"].arr();

  size_t total = 0, mismatches = 0, ok_count = 0, refused_count = 0;
  for (const auto& c : cases) {
    ++total;
    const size_t hidden = static_cast<size_t>(c["hidden"].i());
    const size_t n = static_cast<size_t>(c["n"].i());
    const auto& codes_json = c["codes"].arr();
    const auto& m_json = c["m"].arr();
    const auto& e_json = c["e"].arr();

    std::vector<int8_t> flat_codes(n * hidden);
    for (size_t t = 0; t < n; ++t) {
      const auto& row = codes_json[t].arr();
      for (size_t i = 0; i < hidden; ++i) flat_codes[t * hidden + i] = static_cast<int8_t>(row[i].i());
    }
    std::vector<int64_t> m(n), e(n);
    for (size_t t = 0; t < n; ++t) { m[t] = m_json[t].i(); e[t] = e_json[t].i(); }

    const SembWaPoolStatus expected_status = StatusFromString(c["expected_status"].s());
    if (expected_status == kSembOk) ++ok_count; else ++refused_count;

    std::vector<float> out(hidden, 0.0f);
    const SembWaPoolStatus product_status =
        semb_wa_pool_run(flat_codes.data(), m.data(), e.data(), n, hidden, out.data());

    if (product_status != expected_status) {
      ++mismatches;
      if (mismatches <= 10)
        std::fprintf(stderr, "MISMATCH case %zu: hidden=%zu n=%zu expected=%s product=%d\n",
                     total, hidden, n, c["expected_status"].s().c_str(),
                     static_cast<int>(product_status));
    }
    if (expected_status == kSembOk && product_status == kSembOk) {
      const auto& expect_bits = c["expected_bits_hex"].arr();
      for (size_t i = 0; i < hidden; ++i) {
        uint32_t expect_u = static_cast<uint32_t>(std::stoul(expect_bits[i].s(), nullptr, 16));
        uint32_t got_u;
        std::memcpy(&got_u, &out[i], 4);
        if (got_u != expect_u) {
          ++mismatches;
          if (mismatches <= 10)
            std::fprintf(stderr, "BITS MISMATCH case %zu dim %zu: expected 0x%08x got 0x%08x\n",
                         total, i, expect_u, got_u);
        }
      }
    }
  }

  std::printf("w_a_pool_population_test: %zu cases (%zu ok / %zu refused expected), %zu mismatch(es)\n",
             total, ok_count, refused_count, mismatches);
  return mismatches == 0 ? 0 : 1;
}
