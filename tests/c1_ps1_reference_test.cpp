// tests/c1_ps1_reference_test.cpp -- TE-62 (U0 slice B): C1, PS-1 reference
// equality (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C1).
//
// GRADES: the library's pooled vector against `tests/oracle/ps1_reference.py`
// -- an independent Python exact-rational oracle (fractions.Fraction, an
// explicit round-to-nearest-ties-to-even to binary32, never a Python float
// operation) that takes NO input from `semb_wa_pool_run` or any other code
// under test. Two case families, per C1's own text:
//
//   SYNTHETIC ARM (the two corner rows) -- constructions that reach
//   SEMB_POOLED_SUBNORMAL and SEMB_POOLED_OVERFLOW by direct (S_i, e_min, P)
//   choice, which sec 3.2 states is where the required corner rows live
//   ("a required row no input of its population can produce is sec 9 dim
//   5's rule landing on a cell").
//
//   DOCUMENT ARM -- cases inside the corpus's own measured regime (sec 3.2:
//   e_min in [-33,-30] at 1.5B / [-35,-32] at 0.5B, spread 3 bits, m
//   canonical, |c| <= 127, P < 2^10) -- a RECORDED READING, not a row that
//   must fire a corner (C1's own text: "the document arm carries sec 3.2's
//   executed margins... as a recorded reading rather than as a row that
//   must fire").
//
// RED-UNIMPLEMENTED: `semb_wa_pool_run` (tests/semb_wa_pool_abi_contract.h)
// is not defined anywhere in `superembedder` yet (TE-63's job). This
// translation unit compiles cleanly; the test EXECUTABLE fails to link.
#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <string>
#include <vector>

#include "json_mini.h"
#include "semb_wa_pool_abi_contract.h"
#include "subprocess_util.h"

namespace {

struct Case {
  std::string label;
  size_t hidden;
  size_t n;
  std::vector<std::vector<int64_t>> codes;  // [n][hidden]
  std::vector<int64_t> m;
  std::vector<int64_t> e;
};

std::string ToJsonRequest(const Case& c) {
  std::ostringstream os;
  os << "{\"hidden\":" << c.hidden << ",\"codes\":[";
  for (size_t t = 0; t < c.n; ++t) {
    if (t) os << ",";
    os << "[";
    for (size_t i = 0; i < c.hidden; ++i) {
      if (i) os << ",";
      os << c.codes[t][i];
    }
    os << "]";
  }
  os << "],\"m\":[";
  for (size_t t = 0; t < c.n; ++t) { if (t) os << ","; os << c.m[t]; }
  os << "],\"e\":[";
  for (size_t t = 0; t < c.n; ++t) { if (t) os << ","; os << c.e[t]; }
  os << "]}";
  return os.str();
}

// --------------------------------------------------------------- cases ----

// SYNTHETIC ARM, corner row 1: SEMB_POOLED_SUBNORMAL. hidden=1, n=3 (one
// pooled term after position 0's exclusion... use n=3 so two pooled
// positions exist and e_min/e_max both come from the pooled set). Chosen
// so the pooled S_i * 2^e_min / P lands strictly between 0 and 2^-126.
Case SubnormalCorner() {
  Case c;
  c.label = "synthetic/subnormal-corner";
  c.hidden = 1;
  c.n = 3;
  c.codes = {{0}, {1}, {0}};  // only position 1 contributes (position 2's code is 0)
  c.m = {1 << 30, 1 << 30, 1 << 30};
  // e_min = -160 (well under the -126 normal floor); P = 2 pooled
  // positions; S_1 = 1 * 2^30 (only position 1 contributes, code 0 at
  // position 2 contributes nothing) -> v = 2^30 * 2^-160 / 2, deep in
  // subnormal territory and non-zero.
  c.e = {0, -160, -160};
  return c;
}

// SYNTHETIC ARM, corner row 2: SEMB_POOLED_OVERFLOW. Large m, large
// positive e_min, maximal code -> magnitude far past the RNE overflow
// threshold (2^128 - 2^103).
Case OverflowCorner() {
  Case c;
  c.label = "synthetic/overflow-corner";
  c.hidden = 1;
  c.n = 3;
  c.codes = {{0}, {127}, {127}};
  c.m = {1 << 30, (1 << 31) - 1, (1 << 31) - 1};
  c.e = {0, 100, 100};  // spread 0 (both pooled positions share e=100) -- no accumulator-bound refusal
  return c;
}

// DOCUMENT ARM: inside sec 3.2's own measured 1.5B regime -- e_min in
// [-33,-30], spread 3 bits, m canonical (2^30 <= m < 2^31), |c| <= 127,
// P < 2^10 (here P = 4). An ordinary case that must resolve SEMB_OK, per
// C1's own text ("a recorded reading rather than as a row that must
// fire" -- this case is NOT expected to hit a corner, and the oracle
// comparison is what proves the epilogue is right in this regime, not a
// refusal expectation).
Case DocumentArmOrdinary() {
  Case c;
  c.label = "document-arm/measured-regime";
  c.hidden = 3;
  c.n = 5;  // P = 4 pooled positions
  c.codes = {
      {0, 0, 0},        // position 0, excluded
      {127, -128, 1},
      {-1, 64, -64},
      {50, -50, 100},
      {-100, 30, -30},
  };
  c.m = {1 << 30, (1 << 30) + 7, (1 << 31) - 100, ((1 << 30) + (1 << 29)), (1 << 30) + 3};
  // e_min = -33, spread 3: positions alternate -33 / -30, matching the
  // measured regime's own reading (sec 3.2's own "3 bits on every leg").
  c.e = {-33, -33, -30, -33, -30};
  return c;
}

std::vector<Case> AllCases() {
  return {SubnormalCorner(), OverflowCorner(), DocumentArmOrdinary()};
}

}  // namespace

int main() {
  const auto cases = AllCases();
  int failures = 0;

  for (const auto& c : cases) {
    // 1. The independent oracle's verdict.
    const std::string request = ToJsonRequest(c);
    const std::string cmd = semb_test::PythonExecutable() +
                             " tests/oracle/ps1_reference.py <<< \"" + request + "\"";
    std::string oracle_stdout;
    try {
      oracle_stdout = semb_test::RunCaptureStdout(cmd);
    } catch (const std::exception& ex) {
      std::fprintf(stderr, "C1 [%s]: oracle subprocess failed: %s\n", c.label.c_str(), ex.what());
      ++failures;
      continue;
    }
    json_mini::Value oracle = json_mini::Parse(oracle_stdout);
    const std::string expected_status = oracle["status"].s();

    // 2. The product's verdict -- semb_wa_pool_run is UNDEFINED until
    // TE-63 lands it; this call is what makes the whole executable fail
    // to link today.
    std::vector<int8_t> flat_codes(c.n * c.hidden);
    for (size_t t = 0; t < c.n; ++t)
      for (size_t i = 0; i < c.hidden; ++i)
        flat_codes[t * c.hidden + i] = static_cast<int8_t>(c.codes[t][i]);
    std::vector<float> out(c.hidden, 0.0f);
    const SembWaPoolStatus product_status =
        semb_wa_pool_run(flat_codes.data(), c.m.data(), c.e.data(), c.n, c.hidden, out.data());

    // (Reached only once semb_wa_pool_run exists -- for now, this line
    // never executes.)
    std::printf("C1 [%s]: oracle=%s product_status=%d\n", c.label.c_str(),
                expected_status.c_str(), static_cast<int>(product_status));
  }

  if (failures) {
    std::fprintf(stderr, "C1: %d case(s) could not even reach the product call.\n", failures);
    return 1;
  }
  return 0;
}
