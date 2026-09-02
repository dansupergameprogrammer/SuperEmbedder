// tests/c39_seam_digest_test.cpp -- TE-62/TE-80/TE-83 (U0 slice B): C39's
// second half, the seam digest from the timed call against
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
// COMMISSIONED BEFORE TRUSTED (StandardsDocument.md sec 5.4): `DigestsMatch`
// is exercised against a constructed all-`1`s anchor first -- the
// reviewer's own construction -- and must report a mismatch, before the
// real anchor comparison is run. This never touches the fixture file
// (outside this seat's writable scope for the round that added it; the
// all-`1`s anchor is a string constructed in memory and fed to the SAME
// comparison function the real run uses).
//
// SCOPE, STATED PRECISELY: this cell computes ONLY W-B's own seam digest
// -- SHA-256 over `semb_seam_serialize_document`'s output bytes, exactly
// what this file's header has always specified and what C39's own sec 8
// row names ("the seam digest from the timed call"). TE-82 resolved the
// scope conflict TE-80 filed (TE-78 had recomposed the fixture's single
// anchor line to hold the broader, three-component `witness_sha` instead
// of W-B's digest alone): `tests/fixtures/reference-digests.txt` is now a
// NAMED TABLE, `c39_seam_digest` and `witness_sha` each under its own
// name, and this cell's own computed value matches the `c39_seam_digest`
// row exactly -- confirmed by execution, both toolchains, this round.
//
// TE-83 (TE-81 review N-3, Significant): the header above and the failure
// message below were written by TE-80, correctly, while this cell was
// legitimately red against the pre-TE-82 fixture. TE-82's own writable
// scope was one fixture file and could not scrub them; they survived,
// stale, telling a reader that a mismatch is a known, filed non-defect --
// exactly backwards now that the values agree. Scrubbed in this round:
// a mismatch here means what sec 4.4b says it means -- "a leg whose
// anchor does not reproduce the committed reference is measuring a
// different encoder, engine pin, artifact or corpus" -- and the failure
// message states that, not a resolved finding's own history.
//
// TE-83 (TE-81 review N-4, Minor): `ReadAnchor()` used to read the LAST
// FIELD OF THE FIRST NON-COMMENT LINE, positionally -- it never looked at
// the name a row carried, so the fixture's own move to a named table
// (TE-82) was cosmetic to this reader: swapping the `c39_seam_digest` and
// `witness_sha` rows (names and values both moved together) silently
// made this cell grade W-B's digest against `witness_sha` instead.
// `ReadAnchorByName()`, below, parses and matches the name on every
// non-comment line and is insensitive to row order.
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

// The name this cell's own row carries in the fixture's named table.
const char kAnchorName[] = "c39_seam_digest";

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

// TE-83 (N-4): reads `tests/fixtures/reference-digests.txt` as the named
// table it is (TE-82) and returns the value on the FIRST line whose own
// first field equals `name` -- never a position, so reordering rows (or
// adding a new one above this cell's own) cannot make this reader silently
// pick up a different quantity. Returns "" if `name` appears on no line.
std::string ReadAnchorByName(const std::string& name) {
  std::ifstream ref("tests/fixtures/reference-digests.txt");
  std::string line;
  while (std::getline(ref, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream iss(line);
    std::string field_name, value;
    if (iss >> field_name >> value) {
      if (field_name == name) return value;
    }
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

  const std::string anchor_hex = ReadAnchorByName(kAnchorName);
  if (anchor_hex.empty()) {
    std::fprintf(stderr, "C39: reference-digests.txt has no '%s' row -- nothing to compare "
                          "against.\n", kAnchorName);
    return 1;
  }

  std::printf("C39: encoded %zu-token document, seam bytes length=%zu, computed W-B digest=%s, "
              "fixture '%s' anchor=%s\n",
              kN, len, computed_hex.c_str(), kAnchorName, anchor_hex.c_str());

  if (!DigestsMatch(computed_hex, anchor_hex)) {
    std::fprintf(stderr,
                 "C39: the computed W-B seam digest does NOT match the committed '%s' anchor.\n"
                 "  Per sec 4.4b: a leg whose anchor does not reproduce the committed reference\n"
                 "  is measuring a DIFFERENT encoder, engine pin, artifact or corpus. Check, in\n"
                 "  order: (1) the engine pin (superslm.lock) -- a bump moves the forward and\n"
                 "  therefore the seam; (2) the synthetic artifact\n"
                 "  (build/_scratch/synthetic_te62_c39.sslm) -- stale or regenerated from a\n"
                 "  different pinned tag; (3) this cell's own committed document (kTokenIds) or\n"
                 "  chunk_budget -- either changed without the anchor being recomputed; (4) the\n"
                 "  adapter (src/superembedder/engine_adapter_interim.cpp) -- an edit to the\n"
                 "  forward composition. This is the project's only pinned oracle for the\n"
                 "  encoder (sec 8 C39); a mismatch here is never expected and never benign.\n",
                 kAnchorName);
    return 1;
  }
  std::printf("C39: computed digest matches the committed '%s' anchor.\n", kAnchorName);
  return 0;
}
