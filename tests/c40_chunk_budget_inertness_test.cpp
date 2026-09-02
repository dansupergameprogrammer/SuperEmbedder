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


// TE-83 (N-2): the boundary TE-76 review F-8 actually named -- n=256,
// where the OLD formula (`n*hidden+4096`) falls 16 bytes short of
// `seam_serialize.cpp`'s own real requirement (`16 + n*(hidden+16)`).
// This fixture's own context_cap=64 cannot reach n=256 through a real
// encode call, so this check drives `semb_seam_serialize_document`
// directly on SYNTHETIC codes/m/e -- the same construction
// `w_b_serialization_test.cpp` already uses for byte-layout checks,
// applied here to the ALLOCATION boundary instead. MUST-REJECT: the
// old formula's own buffer size must be reported too small. MUST-
// ACCEPT: the query-derived size (the same pattern now used in the
// real per-budget loop above) must succeed.
bool CheckBufferSizingAtOverflowBoundary() {
  const size_t n = 256;
  const size_t hidden = 32;  // the real fixture's own hidden_size (F-13)
  std::vector<int8_t> codes(n * hidden, 0x11);
  std::vector<int64_t> m(n, 1 << 30), e(n, -20);

  // MUST-REJECT: the OLD formula, shown red.
  const size_t old_formula_size = n * hidden + 4096;
  std::vector<uint8_t> old_buf(old_formula_size);
  size_t old_len = 0;
  const SembSerializeStatus old_st = semb_seam_serialize_document(
      codes.data(), m.data(), e.data(), n, hidden, old_buf.data(), old_buf.size(), &old_len);
  if (old_st != kSembSerializeBufferTooSmall) {
    std::fprintf(stderr, "C40 FAIL: the OLD formula (n*hidden+4096=%zu) did NOT report "
                          "kSembSerializeBufferTooSmall at n=256 (status=%d, out_len=%zu) -- "
                          "the boundary this check exists to prove is not where expected.\n",
                 old_formula_size, static_cast<int>(old_st), old_len);
    return false;
  }
  const size_t real_needed = 16 + n * (hidden + 16);
  if (old_len != real_needed) {
    std::fprintf(stderr, "C40 FAIL: the query's own reported required size (%zu) does not "
                          "match seam_serialize.cpp's own formula (%zu) -- the two have "
                          "drifted apart.\n", old_len, real_needed);
    return false;
  }

  // MUST-ACCEPT: the query-derived size, sized exactly.
  std::vector<uint8_t> real_buf(old_len);
  size_t real_len = 0;
  const SembSerializeStatus real_st = semb_seam_serialize_document(
      codes.data(), m.data(), e.data(), n, hidden, real_buf.data(), real_buf.size(),
      &real_len);
  if (real_st != kSembSerializeOk) {
    std::fprintf(stderr, "C40 FAIL: the query-derived buffer size (%zu bytes) did NOT "
                          "succeed at n=256 (status=%d) -- the fix itself is broken.\n",
                 old_len, static_cast<int>(real_st));
    return false;
  }
  std::printf("C40: buffer-sizing boundary check passed -- old formula (%zu bytes) refused "
              "kSembSerializeBufferTooSmall at n=256 (needed %zu), query-derived sizing "
              "succeeds.\n", old_formula_size, real_needed);
  return true;
}
}  // namespace

int main() {
  if (!SelfTestMismatchDetectionCanFail()) return 1;
  if (!CheckBufferSizingAtOverflowBoundary()) return 1;

  std::string artifact_path;
  try {
    artifact_path = EnsureSyntheticArtifact();
  } catch (const std::exception& ex) {
    std::fprintf(stderr, "C40: could not regenerate the synthetic artifact: %s\n", ex.what());
    return 1;
  }

  // TE-83 (TE-81 review N-2, Significant): this cell's OWN buffer
  // allocation, below, previously used `n * hidden_out + 4096` --
  // VERBATIM the heuristic TE-76 review F-8 condemned (16 bytes short
  // at n=256) -- while a comment here and D-SLM6088 item 4 falsely
  // claimed this run "already covers the corrected formula." It does
  // not: the correction (`16 + n*(hidden+16)`, seam_serialize.cpp:25)
  // lives in witness_main.cpp and c39_seam_digest_test.cpp; this file
  // never used it. Fixed below by querying the ABI's own required
  // size (semb_seam_serialize_document's own documented contract: a
  // call with an undersized buffer reports the exact byte count
  // needed via *out_len, before touching out_buf at all) rather than
  // re-transcribing the formula a third time. CheckBufferSizingAt
  // OverflowBoundary(), below, exercises n=256 -- the boundary F-8
  // actually named, which this fixture's own context_cap=64 cannot
  // reach through a real encode call -- against synthetic codes/m/e,
  // the same construction w_b_serialization_test.cpp already uses,
  // proving the OLD formula fails there (shown red) and the QUERY-
  // based sizing succeeds. D-SLM6088 item 4 is superseded by a new
  // decision entry, not edited.
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
    // TE-83 (N-2): sized by the ABI's own required-size query --
    // call once with no buffer to learn the exact byte count via
    // *out_len (semb_seam_serialize_document's own documented
    // contract: kSembSerializeBufferTooSmall reports the size
    // needed before touching out_buf at all), then allocate exactly
    // that. Never a re-transcription of the formula.
    size_t required_len = 0;
    const SembSerializeStatus query_st = semb_seam_serialize_document(
        codes.data(), m.data(), e.data(), n, hidden_out, nullptr, 0, &required_len);
    if (query_st != kSembSerializeBufferTooSmall) {
      std::fprintf(stderr, "C40: budget=%zu the required-size query did not report "
                            "kSembSerializeBufferTooSmall (status=%d) -- the query contract "
                            "itself did not hold.\n", budget, static_cast<int>(query_st));
      return 1;
    }
    std::vector<uint8_t> buf(required_len);
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
