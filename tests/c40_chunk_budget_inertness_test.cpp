// tests/c40_chunk_budget_inertness_test.cpp -- TE-62 (U0 slice B): C40, the
// chunk budget is inert to the output and live to cost
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C40).
//
// ONE DOCUMENT, FIVE BUDGETS spanning both extremes sec 4.3's own text
// implies -- 1 (the per-position path spelled as a budget), 5, 64, 128,
// and n (one whole-document call) -- with the seam digest (this suite's
// own `semb_seam_serialize_document`, the proven W-B byte layout,
// tests/w_b_serialization_test.cpp) compared across all five. The
// document is chosen with n = 130 tokens specifically so budget 128
// forces a TWO-chunk call (128 + 2) and budget 64 forces a THREE-chunk
// call (64+64+2), exercising a genuine chunk boundary at more than one
// place rather than merely varying a parameter that happens to always
// resolve to one chunk.
//
// RED-UNIMPLEMENTED: `semb_encode_document_for_witness` is undefined
// until TE-63 lands it; this executable fails to link.
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "semb_seam_abi_contract.h"
#include "subprocess_util.h"

namespace {

std::string EnsureSyntheticArtifact() {
  const std::string path = "build/_scratch/synthetic_te62_c40.sslm";
  std::ifstream probe(path, std::ios::binary);
  if (probe.good()) return path;
  const std::string cmd = semb_test::PythonExecutable() +
                           " tests/fixtures/regenerate_synthetic_artifact.py --lock "
                           "superslm.lock --out " + path + " --source \"D:\\SuperSLM\"";
  semb_test::RunCaptureStdout(cmd);
  return path;
}

std::vector<int32_t> MakeTokens(size_t n) {
  std::vector<int32_t> t(n);
  for (size_t i = 0; i < n; ++i) t[i] = static_cast<int32_t>((i * 7 + 3) % 127);  // stays in-vocab (128)
  return t;
}

}  // namespace

int main() {
  std::string artifact_path;
  try {
    artifact_path = EnsureSyntheticArtifact();
  } catch (const std::exception& ex) {
    std::fprintf(stderr, "C40: could not regenerate the synthetic artifact: %s\n", ex.what());
    return 1;
  }

  const size_t n = 130;
  const std::vector<int32_t> tokens = MakeTokens(n);
  const size_t budgets[] = {1, 5, 64, 128, n};

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

  int mismatches = 0;
  for (size_t i = 1; i < seam_bytes_per_budget.size(); ++i) {
    if (seam_bytes_per_budget[i] != seam_bytes_per_budget[0]) {
      std::fprintf(stderr, "C40 FAIL: budget %zu's seam bytes diverge from budget %zu's\n",
                   budgets[i], budgets[0]);
      ++mismatches;
    }
  }
  if (mismatches) {
    std::fprintf(stderr, "C40: %d budget(s) diverged -- the chunk budget is NOT inert.\n",
                 mismatches);
    return 1;
  }
  std::printf("C40: all 5 budgets {1,5,64,128,%zu} emit an identical seam digest.\n", n);
  return 0;
}
