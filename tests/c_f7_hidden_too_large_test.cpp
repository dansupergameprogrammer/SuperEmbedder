// tests/c_f7_hidden_too_large_test.cpp -- TE-80: the owed assertion for
// TE-76 review F-7 (Significant), named in the builder's own build log
// (`Claude/Brunel/te79-u0b-product-fixes-2026-09-02.md` sec 9 item 3):
// `semb_encode_document_for_witness` must refuse `kSembEncodeHiddenTooLarge`
// when the real `hidden_size` (known only after the model opens) exceeds
// `kSembWitnessMaxHidden` (64) -- and must refuse BEFORE writing anything
// to `codes_out`/`m_out`/`e_out`/`*hidden_out`.
//
// WHY THIS WAS NOT BUILDABLE UNTIL NOW. The pinned tag's own tiny T-2199
// synthetic fixture (used by every other cell in this suite) has
// `hidden_size=32` -- well under the 64 ceiling, so no existing fixture
// could ever trigger this refusal; the builder's own log named this
// explicitly ("Filed as owed, not built vacuously against a fixture that
// can never trigger it"). `tests/fixtures/
// regenerate_oversized_synthetic_artifact.py` (this seat's own, TE-80)
// generates a SEPARATE synthetic artifact with `hidden_size=128` (twice
// the ceiling) via the same hermetic, never-committed-as-a-blob mechanism
// every other fixture in this suite uses.
//
// COMMISSIONED BEFORE TRUSTED: `codes_out`/`m_out`/`e_out`/`hidden_out`
// are poisoned with a distinctive, otherwise-impossible sentinel pattern
// before the call, so "the refusal fires" and "nothing was written" are
// both verified by inspecting the SAME buffers -- a refusal that fired
// but still wrote through a stale code path would be caught by the
// poison check, not only by the return status.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "semb_seam_abi_contract.h"
#include "subprocess_util.h"

namespace {

const int32_t kTokenIds[] = {3, 17, 42, 5, 90};
const size_t kN = sizeof(kTokenIds) / sizeof(kTokenIds[0]);

std::string EngineSourceArg() {
  const char* env = std::getenv("SEMB_TEST_ENGINE_SOURCE");
  if (env && *env) return std::string(" --source \"") + env + "\"";
  return "";
}

std::string EnsureOversizedArtifact() {
  const std::string path = "build/_scratch/oversized_te80_f7.sslm";
  std::ifstream probe(path, std::ios::binary);
  if (probe.good()) return path;
  const std::string cmd = semb_test::PythonExecutable() +
                           " tests/fixtures/regenerate_oversized_synthetic_artifact.py --lock "
                           "superslm.lock --out " + path + EngineSourceArg();
  semb_test::RunCaptureStdout(cmd);  // throws on failure
  return path;
}

}  // namespace

int main() {
  std::string artifact_path;
  try {
    artifact_path = EnsureOversizedArtifact();
  } catch (const std::exception& ex) {
    std::fprintf(stderr, "F-7: could not regenerate the oversized artifact: %s\n", ex.what());
    return 1;
  }

  // Poisoned before the call: 0xEE codes, -1 scales, hidden_out set to a
  // sentinel no real hidden_size could be (0xDEADBEEF-shaped).
  std::vector<int8_t> codes(kN * kSembWitnessMaxHidden, static_cast<int8_t>(0xEE));
  std::vector<int64_t> m(kN, -1), e(kN, -1);
  size_t hidden_out = 0xDEADBEEFu;

  const SembEncodeStatus st = semb_encode_document_for_witness(
      artifact_path.c_str(), kTokenIds, kN, /*chunk_budget=*/0, codes.data(), m.data(), e.data(),
      &hidden_out);

  int failures = 0;
  if (st != kSembEncodeHiddenTooLarge) {
    std::fprintf(stderr, "F-7 FAIL: expected kSembEncodeHiddenTooLarge, got status %d (the "
                          "oversized fixture's own real hidden_size did not exceed "
                          "kSembWitnessMaxHidden=%zu, or the domain check did not fire)\n",
                 static_cast<int>(st), kSembWitnessMaxHidden);
    ++failures;
  }
  if (hidden_out != 0xDEADBEEFu) {
    std::fprintf(stderr, "F-7 FAIL: *hidden_out was written (0x%zx) before the refusal -- the "
                          "domain check did not fire BEFORE any output write.\n", hidden_out);
    ++failures;
  }
  for (size_t i = 0; i < codes.size(); ++i) {
    if (codes[i] != static_cast<int8_t>(0xEE)) {
      std::fprintf(stderr, "F-7 FAIL: codes_out[%zu] was written before the refusal.\n", i);
      ++failures;
      break;
    }
  }
  for (size_t i = 0; i < kN; ++i) {
    if (m[i] != -1 || e[i] != -1) {
      std::fprintf(stderr, "F-7 FAIL: m_out/e_out[%zu] was written before the refusal.\n", i);
      ++failures;
      break;
    }
  }

  if (failures) {
    std::fprintf(stderr, "F-7: %d check(s) failed.\n", failures);
    return 1;
  }
  std::printf("F-7: semb_encode_document_for_witness refuses kSembEncodeHiddenTooLarge on a "
              "hidden_size=128 artifact, before writing anything.\n");
  return 0;
}
