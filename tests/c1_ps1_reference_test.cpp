// tests/c1_ps1_reference_test.cpp -- TE-62/TE-77 (U0 slice B): C1, PS-1
// reference equality (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C1).
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
// TE-77 REPAIR 1 (D-SLM6067): the oracle was invoked through a bash
// here-string (`... <<< "$request"`), which Windows `_popen` hands to
// `cmd.exe` -- a shell that does not understand `<<<` and errors before
// the oracle, let alone the product, ever runs. `RunOracle`, below,
// writes the request to a scratch file and redirects it with plain `<`,
// which both `cmd.exe` and a POSIX shell accept identically -- this is
// the whole fix, confined to this file (`tests/subprocess_util.h`'s own
// `RunCaptureStdout(command)` is unchanged and is outside this seat's
// writable scope for TE-77).
//
// TE-77 REPAIR 2 (D-SLM6067's own sibling note): the product's status was
// previously PRINTED, never COMPARED against the oracle's -- a cell that
// cannot fail regardless of what the product returns. `AssertMatches`,
// below, is commissioned BEFORE it is trusted: `SelfTestComparisonCanFail`
// feeds it two constructed, known-DIFFERENT statuses and confirms it
// reports a mismatch, then two known-SAME statuses and confirms it does
// not -- the construction TE-77's own brief asks each repaired cell to be
// shown able to fail on.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
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

// TE-77 repair 1: a plain `<` redirection from a scratch file, portable
// across cmd.exe (Windows `_popen`) and a POSIX shell alike -- unlike
// bash's own `<<<`, which only cmd.exe's absence of support turned into a
// silent-until-now defect (D-SLM6067).
std::string RunOracle(const std::string& request_json) {
  const std::string scratch_path = "build/_scratch/c1_oracle_request.json";
  std::filesystem::create_directories("build/_scratch");
  {
    std::ofstream f(scratch_path, std::ios::binary | std::ios::trunc);
    if (!f) throw std::runtime_error("C1: could not open " + scratch_path + " for writing");
    f << request_json;
  }
  const std::string cmd =
      semb_test::PythonExecutable() + " tests/oracle/ps1_reference.py < " + scratch_path;
  std::string out = semb_test::RunCaptureStdout(cmd);
  std::remove(scratch_path.c_str());
  return out;
}

SembWaPoolStatus StatusFromString(const std::string& s) {
  if (s == "SEMB_OK") return kSembOk;
  if (s == "SEMB_INPUT_TOO_SHORT") return kSembInputTooShort;
  if (s == "SEMB_ACCUMULATOR_OVERFLOW") return kSembAccumulatorOverflow;
  if (s == "SEMB_POOLED_SUBNORMAL") return kSembPooledSubnormal;
  if (s == "SEMB_POOLED_OVERFLOW") return kSembPooledOverflow;
  std::fprintf(stderr, "C1: unrecognised oracle status '%s'\n", s.c_str());
  std::abort();
}

// TE-77 repair 2: the comparison this cell grades on. Returns true (a
// PASS) only when the product's status matches the oracle's, and, for
// SEMB_OK, every emitted bit matches too.
bool AssertMatches(const std::string& label, SembWaPoolStatus expected, SembWaPoolStatus got,
                    const std::vector<float>& got_bits, const json_mini::Value* oracle_json) {
  if (expected != got) {
    std::fprintf(stderr, "C1 [%s] MISMATCH: oracle status=%d product status=%d\n", label.c_str(),
                 static_cast<int>(expected), static_cast<int>(got));
    return false;
  }
  if (expected == kSembOk && oracle_json != nullptr) {
    const auto& expect_bits = (*oracle_json)["bits_hex"].arr();
    if (expect_bits.size() != got_bits.size()) {
      std::fprintf(stderr, "C1 [%s] MISMATCH: %zu expected dims, %zu emitted\n", label.c_str(),
                   expect_bits.size(), got_bits.size());
      return false;
    }
    for (size_t i = 0; i < got_bits.size(); ++i) {
      uint32_t expect_u = static_cast<uint32_t>(std::stoul(expect_bits[i].s(), nullptr, 16));
      uint32_t got_u;
      std::memcpy(&got_u, &got_bits[i], 4);
      if (got_u != expect_u) {
        std::fprintf(stderr, "C1 [%s] MISMATCH dim %zu: expected 0x%08x got 0x%08x\n",
                     label.c_str(), i, expect_u, got_u);
        return false;
      }
    }
  }
  return true;
}

// TE-77's own commissioning: AssertMatches is proven able to fail before
// it is trusted to grade the real cases below (StandardsDocument.md sec
// 5.4 -- "an instrument is commissioned before its verdicts are load-
// bearing"). A must-reject (two constructed, different statuses) and a
// must-accept (two identical statuses, no bits payload) -- both against
// AssertMatches directly, never against the product.
bool SelfTestComparisonCanFail() {
  std::vector<float> no_bits;
  const bool must_reject_result =
      AssertMatches("selftest/must-reject", kSembOk, kSembPooledSubnormal, no_bits, nullptr);
  if (must_reject_result) {
    std::fprintf(stderr, "C1 SELFTEST FAIL: AssertMatches(kSembOk, kSembPooledSubnormal) "
                          "returned true -- the comparison cannot fail, which is the same "
                          "defect the print-only version had (D-SLM6067's sibling note).\n");
    return false;
  }
  const bool must_accept_result =
      AssertMatches("selftest/must-accept", kSembInputTooShort, kSembInputTooShort, no_bits,
                    nullptr);
  if (!must_accept_result) {
    std::fprintf(stderr, "C1 SELFTEST FAIL: AssertMatches(kSembInputTooShort, "
                          "kSembInputTooShort) returned false -- a genuine agreement is being "
                          "reported as a mismatch.\n");
    return false;
  }
  std::printf("C1: comparison self-test passed (must-reject fires, must-accept passes) -- "
              "commissioned before grading the real cases below.\n");
  return true;
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
  c.m = {1 << 30, (int64_t{1} << 31) - 1, (int64_t{1} << 31) - 1};
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
  c.m = {1 << 30, (1 << 30) + 7, (int64_t{1} << 31) - 100, ((1 << 30) + (1 << 29)), (1 << 30) + 3};
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
  if (!SelfTestComparisonCanFail()) return 1;

  const auto cases = AllCases();
  int failures = 0;

  for (const auto& c : cases) {
    // 1. The independent oracle's verdict, via a portable `<` redirect
    // (TE-77 repair 1).
    const std::string request = ToJsonRequest(c);
    std::string oracle_stdout;
    try {
      oracle_stdout = RunOracle(request);
    } catch (const std::exception& ex) {
      std::fprintf(stderr, "C1 [%s]: oracle subprocess failed: %s\n", c.label.c_str(), ex.what());
      ++failures;
      continue;
    }
    json_mini::Value oracle = json_mini::Parse(oracle_stdout);
    const std::string expected_status_str = oracle["status"].s();
    const SembWaPoolStatus expected_status = StatusFromString(expected_status_str);

    // 2. The product's verdict.
    std::vector<int8_t> flat_codes(c.n * c.hidden);
    for (size_t t = 0; t < c.n; ++t)
      for (size_t i = 0; i < c.hidden; ++i)
        flat_codes[t * c.hidden + i] = static_cast<int8_t>(c.codes[t][i]);
    std::vector<float> out(c.hidden, 0.0f);
    const SembWaPoolStatus product_status =
        semb_wa_pool_run(flat_codes.data(), c.m.data(), c.e.data(), c.n, c.hidden, out.data());

    // 3. The comparison this cell exists to make (TE-77 repair 2).
    if (!AssertMatches(c.label, expected_status, product_status, out, &oracle)) {
      ++failures;
      continue;
    }
    std::printf("C1 [%s]: oracle=%s product matches.\n", c.label.c_str(),
                expected_status_str.c_str());
  }

  if (failures) {
    std::fprintf(stderr, "C1: %d case(s) failed.\n", failures);
    return 1;
  }
  std::printf("C1: all cases matched the independent oracle.\n");
  return 0;
}
