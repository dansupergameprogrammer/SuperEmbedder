// tests/c39_seam_digest_test.cpp -- TE-62/TE-80 (U0 slice B): C39's second
// half, the seam digest from the timed call against
// `tests/fixtures/reference-digests.txt`
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C39). The grep-able
// singleton half is `tests/c39_singleton_check.py`.
//
// TE-80 REPAIR (TE-76 review F-1, Critical): the prior version encoded the
// document, serialised the seam into `buf`/`len`, then DISCARDED BOTH and
// checked only that the fixture had a non-comment line -- no SHA-256 call
// anywhere in this file, so it passed against ANY anchor, including a
// deliberately wrong one (reproduced by the reviewer: replacing the
// anchor with all-`1`s still printed a clean PASS). This version computes
// the digest for real: `superslm::Sha256` (the engine's own portable
// SHA-256, sec 4.4b's "the same routine model_sha uses, so the
// fingerprint contains one hash function and not two") over
// `semb_seam_serialize_document`'s own output bytes -- exactly what this
// file's OWN header comment always claimed it computed -- compared
// byte-for-byte (as lowercase hex, `superslm::ToHex`'s own format)
// against the anchor read from `tests/fixtures/reference-digests.txt`.
//
// COMMISSIONED BEFORE TRUSTED (StandardsDocument.md sec 5.4): `Compare()`
// is exercised against a constructed all-`1`s anchor first -- the
// reviewer's own construction -- and must report a mismatch, before the
// real anchor comparison is run. This never touches the fixture file
// (outside this seat's writable scope, `Claude/Bach/briefs/
// te80-u0b-test-fixes.md`'s own Contract: "tests/fixtures/** except
// reference-digests.txt, which is the builder's"); the all-`1`s anchor is
// a string constructed in memory and fed to the SAME comparison function
// the real run uses.
//
// SCOPE, STATED PRECISELY (per this seat's own brief: "State whether the
// committed anchor... is the value the corrected cell computes; if not,
// the builder's recomposition is the finding, filed, not an anchor you
// edit"): this cell computes ONLY W-B's own seam digest -- SHA-256 over
// `semb_seam_serialize_document`'s output bytes, exactly what this file's
// header has always specified and what C39's own sec 8 row names ("the
// seam digest from the timed call"). TE-78 (`witness_sha` composition,
// D-SLM6072/D-SLM6073) recomposed `tests/fixtures/reference-digests.txt`'s
// anchor to hold the FULL three-component `witness_sha`
// (SHA-256(W-A digest || W-B digest || W-Q placeholder digest)) instead
// of W-B's digest alone -- a DIFFERENT, broader quantity this cell was
// never asked to compute. Executed this session (this file's own printed
// output, and this seat's own test-design record,
// `Claude/Curie/te80-u0b-test-fixes-2026-09-02.md`, states the exact
// digests): the two values do not agree. This is filed as a finding for
// the anchor's own owner (the builder), not resolved by widening this
// cell's own scope to match whatever the fixture currently holds, nor by
// editing the fixture.
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "semb_seam_abi_contract.h"
#include "semb_wa_pool_abi_contract.h"
#include "subprocess_util.h"
#include "superslm/sha256.h"

namespace {

// A tiny, deterministic token sequence -- no tokenizer dependency needed
// here (C39 grades the FORWARD + SEAM SHAPE, not tokenization, which is
// C23's cell); token ids are chosen inside the synthetic fixture's own
// small vocab (128 entries). TE-80 F-13: the fixture's own real
// hidden_size is 32 (`_t2199_s8_synthetic_full_model_fixture.py`'s
// `build_config()`, verified by the reviewer's own execution:
// `semb_witness` prints `hidden=32`); the allocation below uses
// `kSembWitnessMaxHidden` (64, seam_abi.h's documented ceiling this verb
// enforces before writing anything) rather than a re-transcription of
// the fixture's own value, so it stays correct even if the fixture's
// hidden_size changes within the ceiling.
const int32_t kTokenIds[] = {3, 17, 42, 5, 90};
const size_t kN = sizeof(kTokenIds) / sizeof(kTokenIds[0]);

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
  const std::string path = "build/_scratch/synthetic_te62_c39.sslm";
  std::ifstream probe(path, std::ios::binary);
  if (probe.good()) return path;
  const std::string cmd = semb_test::PythonExecutable() +
                           " tests/fixtures/regenerate_synthetic_artifact.py --lock "
                           "superslm.lock --out " + path + EngineSourceArg();
  semb_test::RunCaptureStdout(cmd);  // throws on failure
  return path;
}

// Reads the LAST field of the first non-comment, non-blank line of
// tests/fixtures/reference-digests.txt -- the committed anchor, per that
// file's own documented line format ("<artifact-fingerprint>  <digest-
// hex>").
std::string ReadAnchor() {
  std::ifstream ref("tests/fixtures/reference-digests.txt");
  std::string line;
  while (std::getline(ref, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream iss(line);
    std::string field, last;
    while (iss >> field) last = field;
    return last;
  }
  return "";
}

// The comparison this cell exists to make. Returns true iff `computed_hex`
// equals `anchor_hex`, case-insensitively (ToHex's own output is always
// lowercase; the comparison itself does not depend on that).
bool DigestsMatch(const std::string& computed_hex, const std::string& anchor_hex) {
  if (computed_hex.size() != anchor_hex.size()) return false;
  for (size_t i = 0; i < computed_hex.size(); ++i) {
    if (std::tolower(static_cast<unsigned char>(computed_hex[i])) !=
        std::tolower(static_cast<unsigned char>(anchor_hex[i])))
      return false;
  }
  return true;
}

// TE-80's own commissioning: the reviewer's own construction (F-1, sec
// 5.1) -- an anchor of all `1`s -- fed to DigestsMatch directly, never
// via the fixture file. A real digest is 64 lowercase hex characters; an
// all-`1`s string of the same length is never a valid SHA-256 hex digest
// of anything in this population (each nibble would have to be exactly
// 1, probability 16^-64), so this is a genuine, always-applicable
// must-reject, not merely one paired to today's specific bytes.
bool SelfTestAnchorMismatchIsDetected(const std::string& computed_hex) {
  const std::string all_ones(64, '1');
  if (DigestsMatch(computed_hex, all_ones)) {
    std::fprintf(stderr, "C39 SELFTEST FAIL: the computed digest matched an all-1s anchor -- "
                          "DigestsMatch cannot fail, which is F-1's own defect one level "
                          "removed.\n");
    return false;
  }
  std::printf("C39: comparison self-test passed (an all-1s anchor -- the reviewer's own "
              "construction, F-1 sec 5.1 -- is correctly reported as a mismatch) -- "
              "commissioned before grading the real anchor below.\n");
  return true;
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

  std::vector<int8_t> codes(kN * kSembWitnessMaxHidden);
  std::vector<int64_t> m(kN), e(kN);
  size_t hidden_out = 0;
  const SembEncodeStatus st = semb_encode_document_for_witness(
      artifact_path.c_str(), kTokenIds, kN, /*chunk_budget=*/0, codes.data(), m.data(), e.data(),
      &hidden_out);
  if (st != kSembEncodeOk) {
    std::fprintf(stderr, "C39: encode returned status %d\n", static_cast<int>(st));
    return 1;
  }

  std::vector<uint8_t> buf(16 + kN * (hidden_out + 16));
  size_t len = 0;
  const SembSerializeStatus sst = semb_seam_serialize_document(
      codes.data(), m.data(), e.data(), kN, hidden_out, buf.data(), buf.size(), &len);
  if (sst != kSembSerializeOk) {
    std::fprintf(stderr, "C39: serialize returned status %d\n", static_cast<int>(sst));
    return 1;
  }

  // THE DIGEST ITSELF: SHA-256 over the seam bytes, through the engine's
  // own portable routine -- one hash function, sec 4.4b's own discipline.
  uint8_t digest[32];
  superslm::Sha256Hash(buf.data(), len, digest);
  const std::string computed_hex = superslm::ToHex(digest);

  if (!SelfTestAnchorMismatchIsDetected(computed_hex)) return 1;

  const std::string anchor_hex = ReadAnchor();
  if (anchor_hex.empty()) {
    std::fprintf(stderr, "C39: reference-digests.txt has no entry -- nothing to compare "
                          "against.\n");
    return 1;
  }

  std::printf("C39: encoded %zu-token document, seam bytes length=%zu, computed W-B digest=%s, "
              "fixture anchor=%s\n",
              kN, len, computed_hex.c_str(), anchor_hex.c_str());

  if (!DigestsMatch(computed_hex, anchor_hex)) {
    std::fprintf(stderr,
                 "C39: the computed W-B seam digest does NOT match the committed anchor.\n"
                 "  This is a KNOWN, FILED finding (TE-80, this file's own header comment,\n"
                 "  Claude/Curie/te80-u0b-test-fixes-2026-09-02.md): TE-78 recomposed the\n"
                 "  fixture's anchor to hold the FULL witness_sha (W-A||W-B||W-Q), not W-B's\n"
                 "  own seam digest alone -- the quantity this cell has always specified and\n"
                 "  computes. The mismatch is the correct, honest report of that scope gap; it\n"
                 "  is not a defect in this cell's own arithmetic (the digest computation\n"
                 "  itself is exercised and proven able to fail by the self-test above).\n");
    return 1;
  }
  std::printf("C39: computed digest matches the committed anchor.\n");
  return 0;
}
