// tests/c40_chunk_budget_inertness_test.cpp -- TE-62/TE-77 (U0 slice B):
// C40, the chunk budget is inert to the output and live to cost
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C40).
//
// ONE DOCUMENT, FIVE BUDGETS spanning both extremes sec 4.3's own text
// implies -- 1 (the per-position path spelled as a budget), 5, ..., and n
// (one whole-document call) -- with the seam digest (this suite's own
// `semb_seam_serialize_document`, the proven W-B byte layout, tests/
// w_b_serialization_test.cpp) compared across all five.
//
// TE-77 REPAIR (D-SLM6068): the ORIGINAL construction used n=130 with
// budgets {1, 5, 64, 128, n=130}, against the pinned tag's own tiny
// synthetic fixture (`tools/_t2199_s8_synthetic_full_model_fixture.py:51`,
// engine repo `D:\SuperSLM`, read-only to this seat), whose
// `context_cap=64` refuses any call past 64 positions -- including
// budget=0/whole-document, before any chunking is exercised at all. The
// builder reproduced this directly (`semb_witness --chunk-budget 0` on
// the same 130-token sequence: "encode refused (status=1)") and filed it
// as a defect in THIS file, not the fixture (widening `context_cap` is an
// engine-repository change, out of scope for a test-author round in
// `D:\SuperEmbedder`; per the brief, that would be a finding filed, not a
// fixture this seat edits).
//
// THE MAPPING, STATED (TE-77's own brief asks for this explicitly): the
// document shrinks to n=64 -- exactly the fixture's own cap, so the
// per-position (budget=1) and whole-document (budget=n) extremes are
// still both reached -- and the two INTERMEDIATE budgets move from
// {64, 128} (both >= the old n's chunk-forcing range) to {23, 43}, chosen
// so each still forces a GENUINELY DIFFERENT chunk count against the new
// n=64, not a value that happens to collapse to one chunk:
//   budget=1  -> 64 chunks of 1                  (the per-position path)
//   budget=5  -> 13 chunks (12*5 + 4)
//   budget=23 -> 3 chunks (23+23+18)
//   budget=43 -> 2 chunks (43+21)
//   budget=64 -> 1 chunk, the whole document      (budget == n)
// Old {1,5,64,128,130} -> new {1,5,23,43,64}; old budget 64 (a genuine
// multi-chunk split at n=130) and old budget 128 (also multi-chunk) both
// collapse conceptually into the new n=64's own whole-document case, so
// the two new intermediate values (23, 43) are chosen fresh against the
// new cap rather than reusing either old number, which would have
// resolved to one chunk and tested nothing distinct from budget=64.
//
// TE-77's OWN COMMISSIONING (the brief's own "shown able to fail on a
// construction you state"): `SelfTestMismatchDetectionCanFail` corrupts
// one byte of a COPY of one budget's own captured seam bytes and confirms
// the comparison loop below reports it as a divergence, before the real
// five-budget comparison is trusted.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

#include "semb_seam_abi_contract.h"
#include "subprocess_util.h"

namespace {

std::string EngineSourceArg() {
  // TE-80 F-19: no hardcoded local path in committed test source -- an
  // optional override for this seat's own local runs, defaulting to
  // regenerate_synthetic_artifact.py's own DEFAULT_REMOTE (a public URL
  // reachable from any of sec 8 C13's four CI toolchains) when unset.
  const char* env = std::getenv("SEMB_TEST_ENGINE_SOURCE");
  if (env && *env) return std::string(" --source \"") + env + "\"";
  return "";
}

std::string EnsureSyntheticArtifact() {
  const std::string path = "build/_scratch/synthetic_te62_c40.sslm";
  std::ifstream probe(path, std::ios::binary);
  if (probe.good()) return path;
  const std::string cmd = semb_test::PythonExecutable() +
                           " tests/fixtures/regenerate_synthetic_artifact.py --lock "
                           "superslm.lock --out " + path + EngineSourceArg();
  semb_test::RunCaptureStdout(cmd);
  return path;
}

std::vector<int32_t> MakeTokens(size_t n) {
  std::vector<int32_t> t(n);
  for (size_t i = 0; i < n; ++i) t[i] = static_cast<int32_t>((i * 7 + 3) % 127);  // stays in-vocab (128)
  return t;
}

// Returns true iff every seam-bytes vector after the first is
// byte-identical to the first. Factored out of main() so the
// commissioning self-test below and the real comparison call the exact
// same logic.
bool AllIdentical(const std::vector<std::vector<uint8_t>>& seam_bytes_per_budget,
                   const size_t* budgets, std::string* out_message) {
  for (size_t i = 1; i < seam_bytes_per_budget.size(); ++i) {
    if (seam_bytes_per_budget[i] != seam_bytes_per_budget[0]) {
      if (out_message)
        *out_message = "budget " + std::to_string(budgets[i]) + "'s seam bytes diverge from "
                       "budget " + std::to_string(budgets[0]) + "'s";
      return false;
    }
  }
  return true;
}

// TE-77's own commissioning: constructs a POPULATION OF FIVE identical
// seam-byte vectors, corrupts one byte of the LAST one, and confirms
// AllIdentical reports the divergence -- never touching the product.
bool SelfTestMismatchDetectionCanFail() {
  const std::vector<uint8_t> base = {0x01, 0x02, 0x03, 0x04, 0x05};
  std::vector<std::vector<uint8_t>> identical(5, base);
  const size_t fake_budgets[] = {1, 5, 23, 43, 64};
  std::string msg;
  if (!AllIdentical(identical, fake_budgets, &msg)) {
    std::fprintf(stderr, "C40 SELFTEST FAIL: five genuinely identical vectors were reported as "
                          "diverging (%s) -- the comparison is too strict.\n", msg.c_str());
    return false;
  }
  std::vector<std::vector<uint8_t>> corrupted = identical;
  corrupted[4][2] ^= 0xFF;  // one bit-flip in the last budget's own copy
  msg.clear();
  if (AllIdentical(corrupted, fake_budgets, &msg)) {
    std::fprintf(stderr, "C40 SELFTEST FAIL: a single corrupted byte in budget 64's own seam "
                          "bytes was NOT detected -- the comparison cannot fail, which is the "
                          "same defect as no comparison at all.\n");
    return false;
  }
  std::printf("C40: mismatch-detection self-test passed (%s) -- commissioned before grading "
              "the real five budgets below.\n", msg.c_str());
  return true;
}

}  // namespace

int main() {
  if (!SelfTestMismatchDetectionCanFail()) return 1;

  std::string artifact_path;
  try {
    artifact_path = EnsureSyntheticArtifact();
  } catch (const std::exception& ex) {
    std::fprintf(stderr, "C40: could not regenerate the synthetic artifact: %s\n", ex.what());
    return 1;
  }

  // TE-80: this cell's own n=64 run, at budget=64 (one whole-document
  // call), is also the exact buffer-size boundary TE-76 review F-8
  // named (witness_main.cpp's prior `n*hidden+4096` allocation ran out
  // above n=255; TE-79 sized it exactly instead) -- no separate cell is
  // owed for F-8; this run already covers the corrected formula at the
  // fixture's own ceiling.
  // TE-77 repair: n shrinks to the fixture's own context_cap (64); the
  // budget mapping is stated in full in this file's own header comment.
  const size_t n = 64;
  const std::vector<int32_t> tokens = MakeTokens(n);
  const size_t budgets[] = {1, 5, 23, 43, n};

  std::vector<std::vector<uint8_t>> seam_bytes_per_budget;
  for (size_t budget : budgets) {
    std::vector<int8_t> codes(n * 64);
    std::vector<int64_t> m(n), e(n);
    size_t hidden_out = 0;
    const SembEncodeStatus st = semb_encode_document_for_witness(
        artifact_path.c_str(), tokens.data(), n, budget, codes.data(), m.data(), e.data(),
        &hidden_out);
    if (st != kSembEncodeOk) {
      std::fprintf(stderr, "C40: budget=%zu encode returned status %d\n", budget,
                   static_cast<int>(st));
      return 1;
    }
    std::vector<uint8_t> buf(n * hidden_out + 4096);
    size_t len = 0;
    const SembSerializeStatus sst = semb_seam_serialize_document(
        codes.data(), m.data(), e.data(), n, hidden_out, buf.data(), buf.size(), &len);
    if (sst != kSembSerializeOk) {
      std::fprintf(stderr, "C40: budget=%zu serialize returned status %d\n", budget,
                   static_cast<int>(sst));
      return 1;
    }
    buf.resize(len);
    seam_bytes_per_budget.push_back(std::move(buf));
  }

  std::string message;
  if (!AllIdentical(seam_bytes_per_budget, budgets, &message)) {
    std::fprintf(stderr, "C40 FAIL: %s -- the chunk budget is NOT inert.\n", message.c_str());
    return 1;
  }
  std::printf("C40: all 5 budgets {1,5,23,43,%zu} (context_cap-fitted, see this file's own "
              "header comment for the mapping from the original {1,5,64,128,130}) emit an "
              "identical seam digest.\n", n);
  return 0;
}
