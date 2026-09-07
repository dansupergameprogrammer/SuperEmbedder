// tests/w_b_corpus_witness_test.cpp -- TE-145 (U1 slice 2), AMENDED TE-151
// (fix round, item 1): the real W-B witness leg
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b, sec 3.3 row 1 and row 9;
// TE-96 sec 4.5's W-B row). Wires `semb_wb_digest`
// (`tests/semb_wb_witness_abi_contract.h`, TE-145's own accessor, AMENDED
// TE-151 to be HANDLE-SCOPED -- see that header's own comment for why a
// bare accessor cannot be correct for W-B) against an INDEPENDENT,
// test-side recomputation of W-B's own formula -- a FEATURE oracle
// (Curie's own dimension-10 discipline: an achievement claim gets a test
// that executes the definition and asserts the end-state, never a
// self-comparison), built from ALREADY-EXISTING library primitives only:
//
//   1. Tokenize each of the 16 committed W-B documents through the SAME
//      engine call sequence encoder.cpp's own semb_encode/(future)
//      semb_encode_batch use internally (superslm::SslmArtifact +
//      superslm::TokenizerView -- the identical technique TE-144's own C23
//      cell already established for this exact purpose, "the same engine
//      tokenizer surface encoder.cpp calls internally"), then append the
//      SAME resolved end-token id (Encode("<|endoftext|>"), exactly one id)
//      -- the composition PS-N's own entry-point crossing table states for
//      semb_encode_batch: no document frame under PS-N, so batch's own
//      composition is content-tokens-then-terminator, identical to raw's.
//   2. Run each document's real forward through `semb_encode_document_for_witness`
//      (tests/semb_seam_abi_contract.h; ALREADY BUILT, TE-63) to get its
//      per-position {codes, m, e}.
//   3. Serialise each document via `semb_seam_serialize_document` (ALREADY
//      BUILT, TE-63; proven byte-exact by w_b_serialization_test.cpp) and
//      concatenate: u64(document_count) first, then each document's own
//      stream, in committed order (sec 4.4b's own corpus-level formula).
//   4. SHA-256 the whole concatenation with the engine's own portable
//      SHA-256 (superslm::Sha256 -- "the same routine model_sha uses, so the
//      fingerprint contains one hash function and not two", sec 4.4b).
//
// This recomputation takes NO input from `semb_wb_digest`'s own
// implementation -- it calls only primitives that existed before this round
// (semb_encode_document_for_witness, semb_seam_serialize_document,
// superslm::TokenizerView, superslm::Sha256) plus this round's own committed
// corpus data, exactly the independence `StandardsDocument.md` sec 5.4's
// comparison-evidence rule requires of a reference.
//
// RED-UNIMPLEMENTED at this branch's own base c0f52d4, AND at TE-151's own
// tip after the accessor's shape changed: `semb_wb_digest` and
// `semb_encode_batch` are both undeclared in `superembedder`
// (`git grep -n "semb_wb_digest\|semb_encode_batch" src/ include/` returns
// nothing at either base) -- this executable fails to LINK until the
// builder's round adds both, now against the amended two-argument
// `semb_wb_digest(semb_encoder, uint8_t[32])` signature.
//
// THE FOUR PROPERTIES THIS FILE PINS OVER THE HANDLE-SCOPED SHAPE (per
// `tests/semb_wb_witness_abi_contract.h`'s own header comment): (a) the
// achievement cell, `semb_wb_digest(enc, ...)` equals the independent
// recomputation below, over the SAME model and tokenizer `enc` was opened
// on; (b) two calls on ONE handle agree (determinism within a process);
// (c) two handles opened on the SAME artifacts agree (the value is a
// function of the artifacts, not of the handle's own identity or open
// order); (d) a caller's own `semb_encode_batch` calls, with arbitrary
// ids, are INERT to it (TE-96 sec 4.7's must-accept). Plus the three
// calling-convention preconditions the amended shape adds: NULL `enc`,
// a non-live `enc` cookie, and NULL `out_digest`.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --dims <n>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_seam_abi_contract.h"
#include "semb_wb_witness_abi_contract.h"

#include "superslm/artifact.h"
#include "superslm/sha256.h"
#include "superslm/tokenizer.h"

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
bool Is(semb_status s, const char* name) { return s == semb_contract::StatusByName(name); }
bool AllBytesEqual(const uint8_t bytes[32], uint8_t value) {
  for (int i = 0; i < 32; ++i)
    if (bytes[i] != value) return false;
  return true;
}

struct Args {
  std::string model, tokenizer, corpus;
  unsigned dims = 0;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  a.corpus = "tests/fixtures/wb/wb-corpus.jsonl";
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--dims") { std::string v; next(&v); a.dims = static_cast<unsigned>(std::atoi(v.c_str())); }
    else if (k == "--corpus") next(&a.corpus);
  }
  return a;
}

std::vector<uint8_t> ReadFile(const std::string& path) {
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f) return {};
  const std::streamoff end = f.tellg();
  if (end < 0) return {};
  std::vector<uint8_t> out(static_cast<size_t>(end));
  f.seekg(0, std::ios::beg);
  if (!out.empty() && !f.read(reinterpret_cast<char*>(out.data()), end)) return {};
  return out;
}

// A minimal, dependency-free JSONL reader for {"id": "...", "text": "..."}
// records -- the corpus fixture's own shape, not a general JSON parser.
// Handles the escapes the committed corpus's own text actually uses
// (backslash, quote); anything else is a MISSING PREREQUISITE, named,
// rather than a silent misparse.
struct Record { std::string id, text; };
bool ParseJsonlLine(const std::string& line, Record* out, std::string* why) {
  auto extract = [&](const char* key, std::string* value) -> bool {
    const std::string needle = std::string("\"") + key + "\":";
    size_t p = line.find(needle);
    if (p == std::string::npos) { *why = std::string("missing key ") + key; return false; }
    p += needle.size();
    while (p < line.size() && (line[p] == ' ')) ++p;
    if (p >= line.size() || line[p] != '"') { *why = "value is not a JSON string"; return false; }
    ++p;
    std::string s;
    while (p < line.size() && line[p] != '"') {
      if (line[p] == '\\' && p + 1 < line.size()) {
        char c = line[p + 1];
        if (c == '"' || c == '\\' || c == '/') { s.push_back(c); p += 2; continue; }
        *why = "unsupported escape in fixture text";
        return false;
      }
      s.push_back(line[p]);
      ++p;
    }
    if (p >= line.size()) { *why = "unterminated JSON string"; return false; }
    *value = s;
    return true;
  };
  return extract("id", &out->id) && extract("text", &out->text);
}

std::vector<Record> LoadCorpus(const std::string& path, std::string* why) {
  std::vector<Record> out;
  std::ifstream f(path);
  if (!f) { *why = "cannot open " + path; return out; }
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    Record r;
    if (!ParseJsonlLine(line, &r, why)) return {};
    out.push_back(r);
  }
  return out;
}

void PutU64LE(std::vector<uint8_t>* out, uint64_t v) {
  for (int i = 0; i < 8; ++i) out->push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}

// Independent recomputation of W-B's own corpus digest, per sec 4.4b's
// formula, using ONLY primitives that predate this round (see the file
// header). Returns false with `why` set on any setup failure (an engine
// refusal opening the tokenizer, an absent end token, etc.) -- MISSING
// PREREQUISITE, not a silent wrong digest.
bool ComputeExpectedWbDigest(const std::string& model_path, const std::string& tokenizer_path,
                              const std::vector<Record>& corpus, uint8_t out_digest[32], std::string* why) {
  const std::vector<uint8_t> tokenizer_bytes = ReadFile(tokenizer_path);
  if (tokenizer_bytes.empty()) { *why = "cannot read tokenizer artifact " + tokenizer_path; return false; }
  superslm::SslmArtifact tokenizer_artifact;
  superslm::SslmError artifact_error;
  if (superslm::SslmArtifact::OpenFromMemory(tokenizer_bytes.data(), tokenizer_bytes.size(), tokenizer_artifact,
                                              &artifact_error) != superslm::SslmStatus::Ok) {
    *why = "tokenizer artifact open refused";
    return false;
  }
  superslm::TokenizerView tokenizer;
  std::string tok_err;
  if (!superslm::TokenizerView::Open(tokenizer_artifact, tokenizer, &tok_err)) {
    *why = "TokenizerView::Open refused: " + tok_err;
    return false;
  }
  const std::vector<int32_t> end_ids = tokenizer.Encode("<|endoftext|>");
  if (end_ids.size() != 1) { *why = "the canonical end token does not resolve to exactly one id"; return false; }
  const int32_t end_id = end_ids[0];

  std::vector<uint8_t> stream;
  PutU64LE(&stream, static_cast<uint64_t>(corpus.size()));
  for (const Record& r : corpus) {
    std::vector<int32_t> ids = tokenizer.Encode(std::string_view(r.text));
    ids.push_back(end_id);  // PS-N: no document frame, terminator appended once (sec 3.1's shared adapter)

    std::vector<int8_t> codes(ids.size() * kSembWitnessMaxHidden);
    std::vector<int64_t> m(ids.size()), e(ids.size());
    size_t hidden = 0;
    const SembEncodeStatus est = semb_encode_document_for_witness(model_path.c_str(), ids.data(), ids.size(), 0,
                                                                    codes.data(), m.data(), e.data(), &hidden);
    if (est != kSembEncodeOk) {
      *why = "semb_encode_document_for_witness refused for " + r.id + " (" + std::to_string(ids.size()) +
             " token ids, status=" + std::to_string(static_cast<int>(est)) + ")";
      return false;
    }

    std::vector<int8_t> flat(ids.size() * hidden);
    for (size_t p = 0; p < ids.size(); ++p)
      for (size_t i = 0; i < hidden; ++i) flat[p * hidden + i] = codes[p * kSembWitnessMaxHidden + i];

    std::vector<uint8_t> doc_buf(16 + ids.size() * (hidden + 16));
    size_t doc_len = 0;
    const SembSerializeStatus sst = semb_seam_serialize_document(flat.data(), m.data(), e.data(), ids.size(),
                                                                    hidden, doc_buf.data(), doc_buf.size(), &doc_len);
    if (sst != kSembSerializeOk) { *why = "semb_seam_serialize_document refused for " + r.id; return false; }
    stream.insert(stream.end(), doc_buf.begin(), doc_buf.begin() + doc_len);
  }
  superslm::Sha256 h;
  h.Update(stream.data(), stream.size());
  h.Final(out_digest);
  return true;
}

std::string Hex(const uint8_t d[32]) { return superslm::ToHex(d); }

semb_encoder Open(const Args& a) {
  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = a.model.data();
  c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data();
  c.tokenizer_path_len = a.tokenizer.size();
  c.max_concurrency = 1;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&c, &enc);
  if (!Is(s, "SEMB_OK") || !enc) { Verdict(false, "(setup) open", Name(s)); return nullptr; }
  return enc;
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0) {
    std::fprintf(stderr, "usage: %s --model <.sslm> --tokenizer <.sslm> --dims <n> [--corpus <jsonl>]\n", argv[0]);
    return 2;
  }

  std::string why;
  const std::vector<Record> corpus = LoadCorpus(a.corpus, &why);
  if (corpus.size() != 16) {
    Missing("(setup) the committed W-B corpus loads as exactly 16 documents", why.empty() ? "unknown parse failure" : why);
    std::printf("\nw_b_corpus_witness_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
    return g_failures ? 1 : 0;
  }
  Verdict(true, "(setup) the committed W-B corpus loads as exactly 16 documents", a.corpus);

  // ---- Compiled-in corpus pin (TE-147, this seat's own brief item 3: "the
  // compiled-in corpus pinned equal by a cell -- the suite's own manifest
  // digest is the anchor; if no cell compares them today, add one"). No
  // cell existed for this before this round. Two things are checked, and
  // together they close the loop from committed fixture to compiled-in
  // library data:
  //  (1) this cell, mechanically: the fixture file's OWN bytes hash to the
  //      value its own manifest declares -- catches the fixture drifting
  //      from its manifest (an edit to the jsonl with no matching manifest
  //      update);
  //  (2) the achievement cell below (property a), already executed: it
  //      recomputes W-B from THIS SAME fixture's own text and asserts
  //      equality against semb_wb_digest's real output, which is driven by
  //      src/superembedder/wb_corpus.cpp's own COMPILED-IN text -- a byte
  //      difference between the compiled-in corpus and this fixture would
  //      make that digest comparison fail (SHA-256 collision resistance),
  //      so property (a) is the executable pin between (1) and the
  //      compiled-in data; nothing here duplicates that forward pass. ----
  {
    const std::vector<uint8_t> raw = ReadFile(a.corpus);
    if (raw.empty()) {
      Missing("(compiled-in-corpus-pin) the fixture file's own bytes hash to its manifest's declared sha256",
              "cannot read " + a.corpus + " as raw bytes");
    } else {
      uint8_t digest[32];
      superslm::Sha256 h;
      h.Update(raw.data(), raw.size());
      h.Final(digest);
      const std::string actual_hex = Hex(digest);

      const std::string manifest_path = a.corpus.substr(0, a.corpus.find_last_of('/')) + "/wb-corpus.manifest.json";
      std::ifstream mf(manifest_path);
      std::string manifest_text((std::istreambuf_iterator<char>(mf)), std::istreambuf_iterator<char>());
      const std::string needle = "\"sha256\": \"";
      const size_t pos = manifest_text.find(needle);
      if (!mf || pos == std::string::npos) {
        Missing("(compiled-in-corpus-pin) the fixture file's own bytes hash to its manifest's declared sha256",
                "cannot read/parse " + manifest_path);
      } else {
        const std::string declared_hex = manifest_text.substr(pos + needle.size(), 64);
        Verdict(declared_hex == actual_hex,
                "(compiled-in-corpus-pin) " + a.corpus + "'s own bytes hash to the sha256 its manifest declares",
                "declared=" + declared_hex + " actual=" + actual_hex);
      }
    }
  }

  // ---- Preconditions the amended handle-scoped shape adds (TE-151 item 1;
  // `tests/semb_wb_witness_abi_contract.h`'s own header states these three
  // dispositions as fact, "out_digest untouched" included -- checked here,
  // not merely described, per this suite's own sentinel-fill convention,
  // e.g. `tests/u1_raw_text_contract_test.cpp` K-02b/K-02d). The precedence
  // pattern (NULL enc checked before a live-handle requirement, a closed
  // cookie distinct from NULL) matches the rest of this surface, e.g.
  // `tests/u1_batch_contract_test.cpp`'s own step1/step2 split. ----
  {
    uint8_t out[32];
    std::memset(out, 0xA5, sizeof(out));
    const semb_status s1 = semb_wb_digest(nullptr, out);
    Verdict(Is(s1, "SEMB_NULL_ARGUMENT") && AllBytesEqual(out, 0xA5),
            "(precondition) enc == NULL -> SEMB_NULL_ARGUMENT, out_digest untouched", Name(s1));

    semb_encoder closed = Open(a);
    if (closed) {
      semb_encoder_close(closed);
      std::memset(out, 0xA5, sizeof(out));
      const semb_status s2 = semb_wb_digest(closed, out);
      Verdict(Is(s2, "SEMB_INVALID_HANDLE") && AllBytesEqual(out, 0xA5),
              "(precondition) a closed (non-live) cookie -> SEMB_INVALID_HANDLE, out_digest untouched",
              Name(s2));
    }

    semb_encoder live = Open(a);
    if (live) {
      const semb_status s3 = semb_wb_digest(live, nullptr);
      Verdict(Is(s3, "SEMB_NULL_ARGUMENT"), "(precondition) out_digest == NULL -> SEMB_NULL_ARGUMENT", Name(s3));
      semb_encoder_close(live);
    }
  }

  // ---- Mutation-proof of THIS FILE'S OWN oracle (Curie's "pin the
  // documented claim" discipline): the recomputation must actually be
  // sensitive to corpus content, or the comparison below is vacuous. ----
  {
    uint8_t correct[32], mutated[32];
    std::string why1, why2;
    const bool ok1 = ComputeExpectedWbDigest(a.model, a.tokenizer, corpus, correct, &why1);
    std::vector<Record> mutated_corpus = corpus;
    mutated_corpus[5].text += " (mutated)";
    const bool ok2 = ComputeExpectedWbDigest(a.model, a.tokenizer, mutated_corpus, mutated, &why2);
    if (ok1 && ok2) {
      Verdict(std::memcmp(correct, mutated, 32) != 0,
              "(mutation-proof) this file's own recomputation is SENSITIVE to corpus content "
              "(a mutated document 5 produces a different digest than the committed corpus)",
              "correct=" + Hex(correct) + " mutated=" + Hex(mutated));
    } else {
      Missing("(mutation-proof) this file's own recomputation is sensitive to corpus content",
              "setup: " + why1 + " / " + why2);
    }
  }

  // ---- The achievement cell (property a): semb_wb_digest(enc, ...) equals
  // the independent recomputation over the committed corpus, for a handle
  // opened on the same model and tokenizer the recomputation reads.
  // Property (b), determinism, is two calls on this SAME handle; property
  // (c), cross-handle agreement, opens a SECOND handle on the identical
  // artifacts and compares. All three share one setup, since all three
  // need the achievement value to compare against. ----
  {
    uint8_t expected[32];
    std::string why_expected;
    if (!ComputeExpectedWbDigest(a.model, a.tokenizer, corpus, expected, &why_expected)) {
      Missing("W-B semb_wb_digest(enc, ...) equals the independent corpus-witness recomputation", why_expected);
    } else {
      semb_encoder enc1 = Open(a);
      if (enc1) {
        uint8_t actual[32];
        const semb_status sa = semb_wb_digest(enc1, actual);
        Verdict(Is(sa, "SEMB_OK") && std::memcmp(expected, actual, 32) == 0,
                "(a) W-B semb_wb_digest(enc, ...) equals the independent recomputation of sec 4.4b's own "
                "formula over the committed 16-document corpus, for a handle opened on the same model and "
                "tokenizer (achievement claim: the wiring reads the REAL corpus, not kWbPendingSentinel)",
                std::string(Name(sa)) + " expected=" + Hex(expected) + " actual=" + Hex(actual));

        // (b) Determinism: two calls on ONE handle agree (D-SLM3978: no
        // cache, but re-execution must be stable within one process, since
        // the corpus and the artifact are both fixed).
        uint8_t again[32];
        const semb_status sb = semb_wb_digest(enc1, again);
        Verdict(Is(sb, "SEMB_OK") && std::memcmp(actual, again, 32) == 0,
                "(b) W-B semb_wb_digest is deterministic across two calls on ONE handle",
                std::string(Name(sb)) + " " + Hex(again));

        // (c) Cross-handle agreement: a SECOND handle opened on the
        // identical artifacts computes the identical value -- the digest
        // is a function of the artifacts, not of the handle's own
        // identity, open order, or any per-handle state.
        semb_encoder enc2 = Open(a);
        if (enc2) {
          uint8_t second_handle[32];
          const semb_status sc = semb_wb_digest(enc2, second_handle);
          Verdict(Is(sc, "SEMB_OK") && std::memcmp(actual, second_handle, 32) == 0,
                  "(c) W-B semb_wb_digest agrees across TWO handles independently opened on the same "
                  "model and tokenizer",
                  std::string(Name(sc)) + " " + Hex(second_handle));
          semb_encoder_close(enc2);
        }
        semb_encoder_close(enc1);
      }
    }
  }

  // ---- (d) Id-inertness (TE-96 sec 4.7 must-accept): a CALLER's own
  // semb_encode_batch calls, with arbitrary/permuted ids on UNRELATED
  // documents, never perturb the internal, compiled-in W-B corpus digest --
  // the caller's batch calls and the fixed witness corpus are independent.
  // Both readings are taken on the SAME handle, matching the shape every
  // other call this file makes to the accessor. ----
  {
    semb_encoder enc = Open(a);
    if (enc) {
      uint8_t before[32];
      const semb_status sd0 = semb_wb_digest(enc, before);
      Verdict(Is(sd0, "SEMB_OK"), "(d, setup) semb_wb_digest(enc, ...) before the caller's batch calls", Name(sd0));

      std::vector<std::pair<std::string, std::string>> perm1 = {{"zeta", "unrelated document one"},
                                                                  {"alpha", "unrelated document two"}};
      std::vector<std::pair<std::string, std::string>> perm2 = {{"alpha-2", "unrelated document two"},
                                                                  {"zeta-2", "unrelated document one"}};
      for (auto* perm : {&perm1, &perm2}) {
        std::vector<semb_document> docs;
        for (auto& [id, text] : *perm) {
          semb_document d{};
          d.struct_size = sizeof(semb_document);
          d.id = id.c_str();
          d.id_len = id.size();
          d.utf8 = text.c_str();
          d.utf8_len = text.size();
          docs.push_back(d);
        }
        std::vector<uint8_t> buf(perm->size() * static_cast<size_t>(a.dims) * sizeof(float) + 64, 0xA5);
        auto p = reinterpret_cast<uintptr_t>(buf.data());
        float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
        size_t req = 0xBAD5EED;
        semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
      }

      uint8_t after[32];
      const semb_status sd1 = semb_wb_digest(enc, after);
      Verdict(Is(sd1, "SEMB_OK") && std::memcmp(before, after, 32) == 0,
              "(d) W-B-inertness ids are inert: two caller batch calls with different id permutations on "
              "unrelated documents leave the internal committed-corpus witness digest UNCHANGED "
              "(TE-96 sec 4.7 must-accept)",
              std::string(Name(sd1)) + " before=" + Hex(before) + " after=" + Hex(after));
      semb_encoder_close(enc);
    }
  }

  std::printf("\nw_b_corpus_witness_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
