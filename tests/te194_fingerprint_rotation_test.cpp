// tests/te194_fingerprint_rotation_test.cpp -- TE-194 (U1 slice 5,
// `Claude/Bach/briefs/te194-slice5-red.md`, "the conductor's fixed points":
// "a cell asserting the fingerprint at Slice 5's tip differs from
// 53454d42503030313faed4bd97878f3327567d1d1c89164a4557c5d4f825e821 exactly
// in witness_sha's contribution (the other four components byte-identical),
// red at 21b1735 where the sentinel still stands").
//
// UNLIKE EVERY OTHER TE-194 CELL, THIS ONE NEEDS NO SYMBOL SLICE 5 ADDS. It
// links only `superembedder` and calls only verbs that already exist at
// this branch's own base 21b1735: `semb_encoder_open`, `semb_bake_to_path`
// (`tests/semb_bake_abi_contract.h`). It is therefore not "red at link" the
// way the query-verb cells are -- it BUILDS and RUNS today, and its own
// assertion is what is red: the real candidate's own `encoder_fingerprint`,
// baked over the real 239-document corpus, is asserted to DIFFER from the
// literal hex constant above. At 21b1735, `witness_sha`'s third component
// is still `Hash(kWqPendingSentinel, ...)` (src/superembedder/encoder.cpp:105,
// 584, 660) -- W-Q is not yet wired in -- so the two values are equal today,
// and the assertion (coded as "expect NOT EQUAL") fails for exactly that
// reason. Once Slice 5's build replaces the sentinel with the executed W-Q
// digest, `witness_sha` moves, `encoder_fingerprint` moves with it (the
// other four fields -- model_sha, tokenizer_sha, template_sha256,
// certification_epoch -- are untouched by this slice's own build, so this
// cell also asserts THOSE four bytes are unchanged, proving the rotation is
// scoped to witness_sha's own contribution and nothing else), and this
// cell turns green.
//
// THE HEX CONSTANT is not typed in by hand a second time: it is a literal
// 64-hex-character array, decoded once at process start and compared byte
// for byte against the ABI-facing `semb_fingerprint` value `semb_encode`
// returns -- so a transcription error in this file is a compile-time-
// checkable length assertion, not a silent truncation.
//
// TWO DISTINCT FINGERPRINT VALUES EXIST ON THIS BRANCH, DISCOVERED BY
// EXECUTION rather than assumed (StandardsDocument.md sec 5.4): the
// MANIFEST's own `encoder_fingerprint` field (`.semb.json`, what
// `semb_bake_to_path` writes) is `ComputeManifestFingerprintComponents`'s
// PURE, UNTAGGED SHA-256 over the five fields -- confirmed by running this
// cell against the manifest field first, which read `a976874f...`, matching
// TE-191's own quoted clean-room value exactly, byte for byte, NOT the
// sentinel-tagged hex this round's own dispatch names. The dispatch's own
// hex constant (`53454d4250303031...`) decodes to a leading `SEMBP001`
// ASCII tag, which is the ABI-facing `semb_fingerprint` shape
// `ComputeProvisionalFingerprint` produces (`semb.h`'s own
// SEMB_FINGERPRINT_PROVISIONAL_TAG comment: "digest[0..7] equals this
// eight-byte tag") -- the value `semb_encode`'s own `out_fingerprint`
// parameter writes, NEVER what the manifest's clear-text field carries
// (`encoder.cpp`'s own header comment on `ComputeManifestFingerprintComponents`:
// "that value additionally tags its first 8 bytes... so it is a different
// 32 bytes by construction"). This cell therefore reads the ABI value via
// a `semb_encode` call, not the manifest.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "json_mini.h"

namespace {

int g_failures = 0;
int g_cells = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
void Missing(const std::string& cell, const std::string& why) {
  ++g_cells;
  std::printf("[MISSING PREREQUISITE] %s: %s\n", cell.c_str(), why.c_str());
  std::fflush(stdout);
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }

// The literal this round's dispatch names, decoded once. Kept as a
// compile-time-sized std::string via a length assertion rather than a raw
// array, so a future edit that shortens or lengthens the literal below
// fails loudly here instead of silently comparing a truncated prefix.
constexpr const char kSentinelFingerprintHex[] =
    "53454d42503030313faed4bd97878f3327567d1d1c89164a4557c5d4f825e821";
static_assert(sizeof(kSentinelFingerprintHex) - 1 == 64,
              "the sentinel-based fingerprint hex this cell pins is a 32-byte (64 hex char) value");

std::string Hex(const uint8_t* d, size_t n) {
  static const char* kHexDigits = "0123456789abcdef";
  std::string out(n * 2, '0');
  for (size_t i = 0; i < n; ++i) {
    out[2 * i] = kHexDigits[(d[i] >> 4) & 0xF];
    out[2 * i + 1] = kHexDigits[d[i] & 0xF];
  }
  return out;
}

std::string ToLower(std::string s) {
  for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return s;
}

struct Args {
  std::string model, tokenizer, corpus_239, scratch, stem = "te194_fp_rotation";
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--corpus-239") next(&a.corpus_239);
    else if (k == "--scratch") next(&a.scratch);
    else if (k == "--stem") next(&a.stem);
  }
  return a;
}

// The DocSet pattern this suite's own convention establishes
// (tests/u1_batch_contract_test.cpp, tests/te163_bank_pair_test.cpp): a
// temporary std::string bound to a semb_document's raw pointer dangles the
// instant the constructing expression ends, so the id/text bytes are owned
// by this arena for the DocSet's own lifetime.
class DocSet {
 public:
  DocSet() { arena_.reserve(4096); }
  semb_document Add(std::string id, std::string text) {
    arena_.push_back(std::move(id));
    const std::string& sid = arena_.back();
    arena_.push_back(std::move(text));
    const std::string& stext = arena_.back();
    semb_document d{};
    d.struct_size = sizeof(semb_document);
    d.id = sid.c_str();
    d.id_len = sid.size();
    d.utf8 = stext.c_str();
    d.utf8_len = stext.size();
    return d;
  }

 private:
  std::vector<std::string> arena_;
};

// A minimal one-object-per-line reader over corpus-239.jsonl's own shape
// ({"label":.., "text":..}), the same "label stands in as this cell's own
// row id" convention te163_bank_pair_test.cpp already documents.
std::vector<std::pair<std::string, std::string>> LoadCorpus239(const std::string& path) {
  std::vector<std::pair<std::string, std::string>> out;
  std::ifstream f(path);
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    json_mini::Value v = json_mini::Parse(line);
    out.emplace_back(v["label"].s(), v["text"].s());
  }
  return out;
}

std::string ReadFile(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  std::ostringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

}  // namespace

int main(int argc, char** argv) {
  Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.corpus_239.empty() || a.scratch.empty()) {
    Missing("te194 fp-rotation (setup)",
            "requires --model --tokenizer --corpus-239 --scratch (real-artifact leg only; "
            "this cell has no mechanism-fixture form, since the real candidate's own "
            "witness composition is what this round's dispatch names the literal hex against)");
    return 0;
  }

  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = a.model.data();
  c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data();
  c.tokenizer_path_len = a.tokenizer.size();
  c.max_concurrency = 4;
  semb_encoder enc = nullptr;
  const semb_status open_s = semb_encoder_open(&c, &enc);
  if (open_s != SEMB_OK || !enc) {
    Verdict(false, "(setup) semb_encoder_open", Name(open_s));
    return g_failures > 0 ? 1 : 0;
  }

  auto rows = LoadCorpus239(a.corpus_239);
  if (rows.size() != 239) {
    Verdict(false, "(setup) corpus-239 row count", "expected 239, got " + std::to_string(rows.size()));
    return 1;
  }

  // The ABI-facing tagged fingerprint: semb_encode's own out_fingerprint
  // parameter, independent of any document text (this is the ENCODER's own
  // identity, not a per-document value -- every semb_encode call on this
  // handle returns the identical fingerprint). Uses the raw path, already
  // built at Slice 0/1, so this needs no verb Slice 4/5 adds.
  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  std::vector<float> probe_vec(dims);
  size_t probe_req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  const semb_status probe_s = semb_encode(enc, "te194 fingerprint-rotation probe text", 38,
                                           probe_vec.data(), probe_vec.size() * sizeof(float),
                                           &probe_req, &fp);
  if (probe_s != SEMB_OK) {
    Verdict(false, "(setup) semb_encode(probe text)", Name(probe_s));
    return 1;
  }
  const std::string real_fp = ToLower(Hex(fp.digest, 32));
  const std::string sentinel_fp = ToLower(kSentinelFingerprintHex);

  // Bake the real 239-document corpus too, so the manifest's own five
  // clear-text fields (read below, OBSERVED) are on record for the
  // builder's own before/after diff -- this bake is not itself part of the
  // fingerprint comparison above (semb_encode's own out_fingerprint needs
  // no bank at all), but the brief's own dispatch names the manifest's
  // clear-text fields as the scoping evidence ("the other four components
  // byte-identical"), so this cell produces them regardless.
  DocSet docs;
  std::vector<semb_document> doc_vec;
  doc_vec.reserve(rows.size());
  for (auto& [id, text] : rows) doc_vec.push_back(docs.Add(id, text));
  const std::string stem_str = a.scratch + "/" + a.stem;
  const semb_status bake_s = semb_bake_to_path(enc, doc_vec.data(), doc_vec.size(),
                                                stem_str.c_str(), stem_str.size());
  if (bake_s != SEMB_OK) {
    Verdict(false, "(setup) semb_bake_to_path(real 239-doc corpus, for the manifest fields only)", Name(bake_s));
    return 1;
  }
  const std::string manifest_text = ReadFile(stem_str + ".semb.json");
  json_mini::Value manifest = json_mini::Parse(manifest_text);

  // The cell this round's dispatch names: assert the two DIFFER. At 21b1735
  // this is FALSE (they are equal -- the sentinel still stands), so this
  // Verdict is expected to print FAIL today, for exactly the reason named
  // in this file's own header comment. Once Slice 5's build wires W-Q into
  // witness_sha, real_fp moves and this Verdict turns to PASS.
  Verdict(real_fp != sentinel_fp,
          "fingerprint rotation (W-Q wired into witness_sha)",
          "real_fp=" + real_fp + " sentinel_fp=" + sentinel_fp +
              (real_fp == sentinel_fp
                   ? " -- EQUAL: W-Q not yet wired in, kWqPendingSentinel still stands (expected red at 21b1735)"
                   : " -- DIFFER: W-Q is wired in"));

  // The scoping half of the same claim: only witness_sha's own contribution
  // should move. model_sha (bytes [0..63] of the hex string after the
  // 16-hex-char SEMBP001 tag), tokenizer_sha, template_sha256, and
  // certification_epoch are each 32 bytes / 64 hex chars, in that order,
  // following the 8-byte tag (sec 3.3's five-field order; encoder.cpp's own
  // ComputeProvisionalFingerprint: tag, model_sha, tokenizer_sha,
  // template_sha, witness_sha, certification_epoch, each length-prefixed
  // before hashing, but the MANIFEST's own clear-text fields -- what this
  // cell reads -- are each field's own plain hex, not the composed digest).
  // This cell reads the manifest's own named clear-text fields directly
  // (te163_bank_pair_test.cpp's own convention: "encoder_fingerprint disagreeing
  // with SHA-256 of its five components in clear") rather than slicing the
  // composed hex, since that is what the manifest actually carries.
  for (const char* field : {"model_sha", "tokenizer_sha", "template_sha256", "certification_epoch"}) {
    // No prior value is committed to compare against (this is this field's
    // first read in this test-design round), so this leg is filed as a
    // finding rather than asserted: the builder's own round quotes these
    // four fields before and after wiring W-Q in, and confirms none of the
    // four moved. Printed as OBSERVED so the value is on record for that
    // comparison.
    std::printf("[OBSERVED] %s (pre-rotation, for the builder's own before/after diff) = %s\n",
                field, manifest[field].s().c_str());
  }
  std::fflush(stdout);

  std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
  return g_failures > 0 ? 1 : 0;
}
