// src/witness/witness_main.cpp -- TE-63 (U0 slice B): the witness
// executable (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b, "the
// structural law": "1. The witness is a target of the build being
// fingerprinted... 4. The witness's own translation unit contains no
// arithmetic on the reproducible path -- it is a loop and a serialiser").
//
// This TU calls the library's own exported C ABI verbs
// (semb_encode_document_for_witness, semb_seam_serialize_document) and
// digests their output with the engine's own portable SHA-256
// (superslm/sha256.h, sec 4.4b: "the same routine model_sha uses, so the
// fingerprint contains one hash function and not two"). It performs no
// arithmetic of its own on the reproducible path -- clause 4's own
// requirement, and the reason W-A's driver (ps1_pool.cpp) and the
// interim adapter (engine_adapter_interim.cpp) live in the LIBRARY rather
// than here (C38: an `inline` engine primitive called from this TU would
// compile under the WITNESS's own invocation, not the library's, and a
// definition on the library target would move nothing).
//
// WHAT THIS ROUND BUILDS AND WHAT IT DOES NOT. The brief's item 5 asks
// for this executable as "a target of the same build, linking the real
// library" so that C31's four structural clauses and C38's construction
// "go green." The full C31 matrix (a second-configure build, a
// detached-link build, a TU-local driver variant, a foreign-process
// reading) is a set of independent CMake configure/build/link
// CONSTRUCTIONS this executable's own existence does not perform by
// itself -- `tests/witness_structural_matrix.py` (outside this seat's
// writable scope) is where those constructions would be driven and
// graded, and its own code (read in full before this file was written)
// unconditionally reports every leg `MISSING PREREQUISITE` / `passed:
// false` with no dynamic invocation of anything, so building this
// executable does not and cannot move any of its ten legs to a real
// reading -- filed as a routed finding in this seat's build log rather
// than resolved by editing a file outside this seat's writable scope.
// What this executable DOES demonstrate, real and executable today: a
// target of this build linking the real `superembedder` library and the
// real installed `superslm` library, calling the library's own entry
// points for the seam and the digest, with zero arithmetic in its own
// translation unit.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "superembedder/seam_abi.h"
#include "superslm/sha256.h"

namespace {

void PrintUsage(const char* argv0) {
  std::fprintf(stderr,
                "usage: %s --model <path.sslm> --tokens <comma-separated token ids> "
                "[--chunk-budget N]\n",
                argv0);
}

std::vector<int32_t> ParseTokens(const std::string& csv) {
  std::vector<int32_t> out;
  size_t start = 0;
  while (start <= csv.size()) {
    size_t comma = csv.find(',', start);
    if (comma == std::string::npos) comma = csv.size();
    if (comma > start) out.push_back(std::atoi(csv.substr(start, comma - start).c_str()));
    start = comma + 1;
  }
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  std::string model_path;
  std::string tokens_csv;
  size_t chunk_budget = 0;

  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--model" && i + 1 < argc) {
      model_path = argv[++i];
    } else if (a == "--tokens" && i + 1 < argc) {
      tokens_csv = argv[++i];
    } else if (a == "--chunk-budget" && i + 1 < argc) {
      chunk_budget = static_cast<size_t>(std::atoll(argv[++i]));
    } else {
      PrintUsage(argv[0]);
      return 2;
    }
  }
  if (model_path.empty() || tokens_csv.empty()) {
    PrintUsage(argv[0]);
    return 2;
  }

  const std::vector<int32_t> tokens = ParseTokens(tokens_csv);
  const size_t n = tokens.size();
  if (n == 0) {
    std::fprintf(stderr, "witness: --tokens produced an empty sequence\n");
    return 1;
  }

  // Hidden size is not known until the model is open, inside the library's
  // own entry point -- this TU allocates generously (the fixture's own
  // vocab/hidden bounds are small) and lets the library report the real
  // value via hidden_out.
  constexpr size_t kMaxHidden = 4096;
  std::vector<int8_t> codes(n * kMaxHidden);
  std::vector<int64_t> m(n), e(n);
  size_t hidden = 0;

  const SembEncodeStatus st = semb_encode_document_for_witness(
      model_path.c_str(), tokens.data(), n, chunk_budget, codes.data(), m.data(), e.data(),
      &hidden);
  if (st != kSembEncodeOk) {
    std::fprintf(stderr, "witness: encode refused (status=%d)\n", static_cast<int>(st));
    return 1;
  }

  std::vector<uint8_t> buf(n * hidden + 4096);
  size_t len = 0;
  const SembSerializeStatus sst = semb_seam_serialize_document(codes.data(), m.data(), e.data(), n,
                                                                 hidden, buf.data(), buf.size(),
                                                                 &len);
  if (sst != kSembSerializeOk) {
    std::fprintf(stderr, "witness: serialize returned status %d\n", static_cast<int>(sst));
    return 1;
  }

  superslm::Sha256 h;
  h.Update(buf.data(), len);
  uint8_t digest[32];
  h.Final(digest);

  std::printf("witness: n=%zu hidden=%zu seam_bytes=%zu witness_seam_sha256=%s\n", n, hidden, len,
              superslm::ToHex(digest).c_str());
  return 0;
}
