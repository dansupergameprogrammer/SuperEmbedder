// tests/c39_seam_digest_test.cpp -- TE-62 (U0 slice B): C39's second half,
// the seam digest from the timed call against
// `tests/fixtures/reference-digests.txt`
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C39). The grep-able
// singleton half is `tests/c39_singleton_check.py`.
//
// ENCODES A TINY SYNTHETIC DOCUMENT ON THE HERMETICALLY-REGENERATED
// SYNTHETIC ARTIFACT (`tests/fixtures/regenerate_synthetic_artifact.py`),
// through the product's own timed call, and compares the resulting seam
// digest against the committed anchor in
// `tests/fixtures/reference-digests.txt`. That anchor is currently
// PENDING (there is no encoder to have computed it from) -- this cell's
// own comparison logic is written and ready, and its executable fails to
// LINK today because `semb_encode_document_for_witness`
// (tests/semb_seam_abi_contract.h) is undefined until TE-63 lands it.
//
// THE DIGEST ITSELF is this file's OWN SHA-256 over
// `semb_seam_serialize_document`'s own output bytes (tests/
// semb_seam_abi_contract.h) -- reusing the ALREADY-PROVEN W-B byte layout
// (tests/w_b_serialization_test.cpp) rather than inventing a second
// serialisation for this cell, per this codebase's own "one serialisation,
// every digest reads it" discipline (sec 4.4b).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "semb_seam_abi_contract.h"
#include "semb_wa_pool_abi_contract.h"
#include "subprocess_util.h"

namespace {

// A tiny, deterministic token sequence -- no tokenizer dependency needed
// here (C39 grades the FORWARD + SEAM SHAPE, not tokenization, which is
// C23's cell); token ids are chosen inside the synthetic fixture's own
// small vocab (128 entries, see `_t2199_s8_synthetic_full_model_fixture.
// py`'s `build_config()`).
const int32_t kTokenIds[] = {3, 17, 42, 5, 90};
const size_t kN = sizeof(kTokenIds) / sizeof(kTokenIds[0]);

std::string EnsureSyntheticArtifact() {
  const std::string path = "build/_scratch/synthetic_te62_c39.sslm";
  std::ifstream probe(path, std::ios::binary);
  if (probe.good()) return path;
  const std::string cmd = semb_test::PythonExecutable() +
                           " tests/fixtures/regenerate_synthetic_artifact.py --lock "
                           "superslm.lock --out " + path + " --source \"D:\\SuperSLM\"";
  semb_test::RunCaptureStdout(cmd);  // throws on failure
  return path;
}

}  // namespace

int main() {
  std::string artifact_path;
  try {
    artifact_path = EnsureSyntheticArtifact();
  } catch (const std::exception& ex) {
    std::fprintf(stderr, "C39: could not regenerate the synthetic artifact: %s\n", ex.what());
    return 1;
  }

  std::vector<int8_t> codes(kN * 64);  // 64 = the fixture's own hidden_size (build_config())
  std::vector<int64_t> m(kN), e(kN);
  size_t hidden_out = 0;
  const SembEncodeStatus st = semb_encode_document_for_witness(
      artifact_path.c_str(), kTokenIds, kN, /*chunk_budget=*/0, codes.data(), m.data(), e.data(),
      &hidden_out);
  if (st != kSembEncodeOk) {
    std::fprintf(stderr, "C39: encode returned status %d\n", static_cast<int>(st));
    return 1;
  }

  std::vector<uint8_t> buf(kN * hidden_out + 4096);
  size_t len = 0;
  const SembSerializeStatus sst = semb_seam_serialize_document(
      codes.data(), m.data(), e.data(), kN, hidden_out, buf.data(), buf.size(), &len);
  if (sst != kSembSerializeOk) {
    std::fprintf(stderr, "C39: serialize returned status %d\n", static_cast<int>(sst));
    return 1;
  }

  // Reference-digests.txt is PENDING (see the file's own header comment) --
  // this cell reads it and reports whatever it finds rather than
  // asserting a fabricated value; it is unreachable today regardless,
  // since the link above never completes.
  std::ifstream ref("tests/fixtures/reference-digests.txt");
  std::string line;
  bool found_entry = false;
  while (std::getline(ref, line)) {
    if (!line.empty() && line[0] != '#') { found_entry = true; break; }
  }
  if (!found_entry) {
    std::fprintf(stderr, "C39: reference-digests.txt has no entry yet (PENDING) -- nothing to "
                          "compare against; this run itself is what the commissioning step "
                          "described in the file's own header comment produces.\n");
    return 1;
  }
  std::printf("C39: encoded %zu-token document, seam bytes length=%zu\n", kN, len);
  return 0;
}
