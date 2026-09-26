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
// THE PROPERTIES THIS FILE PINS OVER THE HANDLE-SCOPED SHAPE, AMENDED
// TE-160 (S-7). The contract header's own comment names four: (a) the
// achievement cell, (b) determinism across two calls on one handle, (c)
// cross-handle agreement, (d) id-inertness. TE-148's review (S-7) found
// (b) and the original (d) cannot fail as built: `semb_wb_digest`
// (`src/superembedder/encoder.cpp`) is a `memcpy` from `handle->wb_digest`,
// a field written ONCE at open, so (b) compared that stored value against
// itself across two calls on the SAME handle, and the original (d) read the
// SAME stored bytes before and after a caller's own `semb_encode_batch`
// calls that never touch it -- neither construction can go red under any
// behaviour of the product. This file's own disposition, per S-7:
//
//   (a) LIVE, unchanged -- the achievement cell: `semb_wb_digest(enc, ...)`
//       equals the independent recomputation below, over the SAME model
//       and tokenizer `enc` was opened on.
//   (b) RETIRED (TE-160/S-7) rather than left green and grading nothing --
//       StandardsDocument.md sec 5.4's "a test exercises the real workload
//       ... or it is a smoke test wearing a proof's name, and repetition
//       does not upgrade it": a construction that cannot fail is not a
//       weaker determinism test, it is not a test.
//   (c) LIVE, unchanged -- cross-handle agreement: two handles opened on
//       the SAME artifacts agree, so the value is a function of the
//       artifacts, not of the handle's own identity or open order.
//   (d) REPLACED (TE-160/S-7) with a construction that CAN fail, TE-96 sec
//       4.7's own text: "ids are inert -- permuting the ids over a fixed
//       text set leaves every row byte-identical." Fixed texts at fixed
//       row positions, two DIFFERENT id assignments across those same
//       positions, every emitted ROW asserted byte-identical. This grades
//       the BATCH PATH's own row output (`semb_encode_batch`), never the
//       cached `wb_digest` field the retired (d) read -- the guard-vitality
//       mutation TE-96 sec 4.5's own W-B row names for this claim ("fold
//       the id into the tokenizer input") moves a ROW's bytes, never the
//       cached digest, so only a row-level construction can see it.
//       Mutation-proved (this file's own section, below).
//
// The suite therefore carries THREE live properties over the handle-scoped
// shape (a, c, and the row-level id-inertness), down from the four the
// contract header's own comment names -- stated here so a future reader
// does not recount four live cells that were never four. Plus the three
// calling-convention preconditions the amended shape adds: NULL `enc`, a
// non-live `enc` cookie, and NULL `out_digest`.
//
// TE-160/S-2 adds a further, independent achievement cell in this same
// file (below the id-inertness block): the emitted `semb_fingerprint`
// equals the five-field composition recomputed independently from
// `Claude/Plans/SuperEmbedder_Plan.md` sec 3.3/sec 4.4b and TE-148 review's
// own sec 6 F-4 derivation -- see that section's own header comment.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --dims <n>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bank_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_query_abi_contract.h"
#include "semb_seam_abi_contract.h"
#include "semb_wb_witness_abi_contract.h"
#include "json_mini.h"
#include "support/semb_epoch_oracle.h"

// TE-155 item 1 (D-SLM6341): the independent recomputation below needs
// context_cap to apply the SAME per-document cut
// src/superembedder/encoder.cpp's own ComputeWbDigest applies, discovered
// independently of that function (a SEPARATE semb_interim_encoder_open on
// the identical artifact, below) rather than assumed or hardcoded. This
// header predates this round (TE-63) and declares no symbol any other
// included header here already declares (confirmed: SembInterimEncoder,
// SembInterimGeometry, SembInterimStatus, semb_interim_encoder_open/
// _geometry/_close are all new names; SembWaPoolStatus, which it also
// declares via pool_abi.h, is not declared anywhere else this file
// includes).
#include "superembedder/encoder_interim_abi.h"

#include "superembedder/witness_abi.h"  // semb_wa_digest -- zero real-ABI-type dependency (see its
                                          // own header comment), safe alongside the contract headers
                                          // above (TE-160/S-2's fingerprint pin).

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

// TE-192 item 5 (TE-187 bare cell 1, D-SLM6406/D-SLM6457): an independent
// reimplementation of the CORRECTED per-document cut rule -- the longest
// UTF-8-boundary text prefix whose COMPOSED sequence (`frame` then the
// prefix, matching `encoder.cpp`'s own `ComposeDocumentInput` concatenation
// order) tokenizes to at most `max_content_ids` ids. Authored independently
// of `CutWbDocumentText` (never reads that function's own source), grounded
// directly in D-SLM6457's own stated bound rather than a recode of the
// product's walk -- the walk SHAPE is the only sane way to answer "longest
// prefix such that a real tokenizer call agrees," since BPE merges near a
// boundary are not predictable from byte length alone. `frame` is empty by
// default, matching `kDocumentFrame`'s real, current compiled-in value
// (PS-N, D-SLM4726) -- passing a non-empty `frame` exercises the corrected
// rule's OWN sensitivity to a document frame, the corner D-SLM6406 found
// unaccounted.
std::string_view CutToComposedBudget(const superslm::TokenizerView& tokenizer, std::string_view frame,
                                      std::string_view text, size_t max_content_ids) {
  const std::string frame_str(frame);
  if (tokenizer.Encode(frame_str + std::string(text)).size() <= max_content_ids) return text;
  size_t best = 0;  // the empty prefix always tokenizes frame+"" to Encode(frame).size() ids.
  size_t i = 0;
  while (i < text.size()) {
    const uint8_t lead = static_cast<uint8_t>(text[i]);
    size_t width = 1;
    if ((lead & 0xE0) == 0xC0) width = 2;
    else if ((lead & 0xF0) == 0xE0) width = 3;
    else if ((lead & 0xF8) == 0xF0) width = 4;
    const size_t next = (i + width < text.size()) ? i + width : text.size();
    if (tokenizer.Encode(frame_str + std::string(text.substr(0, next))).size() > max_content_ids) break;
    best = next;
    i = next;
  }
  return text.substr(0, best);
}

// Independent recomputation of W-B's own corpus digest, per sec 4.4b's
// formula, using ONLY primitives that predate this round (see the file
// header) plus CutToComposedBudget, above (TE-172 realized the bare rule from
// D-SLM6390 item 2's own words, not from the product's implementation).
// Returns false with `why` set on any setup failure (an engine refusal
// opening the tokenizer, an absent end token, etc.) -- MISSING
// PREREQUISITE, not a silent wrong digest. `out_cut_count`, when non-NULL,
// receives the number of the 16 documents whose own tokenized COMPOSED
// content (frame + text) exceeded context_cap-1 ids and was therefore cut
// before the end token was appended (TE-155 item 1, D-SLM6341; corrected
// TE-192 item 5, D-SLM6406/D-SLM6457, to budget the composed sequence
// rather than the bare text alone) -- 0 when every document fits.
// `document_frame` defaults to "", matching the real, currently-shipped
// `kDocumentFrame` (PS-N) -- this default reproduces the achievement
// cell's own prior behavior exactly, since the composed and bare budgets
// are numerically identical whenever the frame is empty; passing a
// non-empty frame is this round's own divergence construction, below.
bool ComputeExpectedWbDigest(const std::string& model_path, const std::string& tokenizer_path,
                              const std::vector<Record>& corpus, uint8_t out_digest[32], std::string* why,
                              size_t* out_cut_count = nullptr, std::string_view document_frame = "") {
  if (out_cut_count) *out_cut_count = 0;
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

  // TE-155 item 1 (D-SLM6341): discover context_cap independently of
  // ComputeWbDigest's own implementation -- a SEPARATE
  // semb_interim_encoder_open/geometry query against the identical model
  // artifact (encoder_interim_abi.h predates this round, TE-63), closed
  // immediately after the geometry read since this recomputation still
  // drives the actual forward through semb_encode_document_for_witness
  // (its own, separate open) exactly as it did before this round.
  SembInterimEncoder* cap_probe = nullptr;
  const char* cap_probe_status = nullptr;
  if (semb_interim_encoder_open(model_path.c_str(), end_id, &cap_probe, &cap_probe_status) != kSembInterimOk) {
    *why = "semb_interim_encoder_open refused while discovering context_cap";
    return false;
  }
  SembInterimGeometry geometry{};
  geometry.struct_size = sizeof(geometry);
  const SembInterimStatus geometry_status = semb_interim_encoder_geometry(cap_probe, &geometry);
  semb_interim_encoder_close(cap_probe);
  if (geometry_status != kSembInterimOk) { *why = "semb_interim_encoder_geometry refused"; return false; }
  const size_t max_content_ids =
      geometry.context_cap > 0 ? static_cast<size_t>(geometry.context_cap) - 1 : 0;

  std::vector<uint8_t> stream;
  PutU64LE(&stream, static_cast<uint64_t>(corpus.size()));
  for (const Record& r : corpus) {
    // TE-192 item 5 (D-SLM6406/D-SLM6457): the cut is budgeted against the
    // COMPOSED sequence (document_frame + text), matching
    // ComposeDocumentInput's own concatenation order -- CutToComposedBudget
    // finds the longest UTF-8-boundary text prefix whose composed tokenized
    // length is at most max_content_ids, and the ids fed forward are the
    // SAME composed sequence (frame + kept prefix), never the bare text
    // alone. Reduces to the prior bare-text behavior exactly when
    // document_frame is empty (the real, currently-shipped default).
    const std::string_view kept_text = CutToComposedBudget(tokenizer, document_frame, r.text, max_content_ids);
    if (kept_text.size() < r.text.size() && out_cut_count) ++*out_cut_count;
    std::vector<int32_t> ids = tokenizer.Encode(std::string(document_frame) + std::string(kept_text));
    ids.push_back(end_id);  // the terminator, appended once (sec 3.1's shared adapter)

    // TE-155 item 1 (found by execution, not by construction,
    // StandardsDocument.md sec 5.4): `codes` is over-provisioned at
    // kSembWitnessMaxHidden per position because the real hidden_size is
    // an OUT parameter, not known until semb_encode_document_for_witness
    // returns -- but that verb (src/superembedder/engine_adapter_interim.cpp's
    // semb::Encode) writes each position CONTIGUOUSLY at its own REAL
    // hidden_size stride (`codes_out + p * hidden`), never at
    // kSembWitnessMaxHidden's stride, exactly as
    // tests/c39_seam_digest_test.cpp's own identical construction assumes
    // (it passes codes.data() straight through with no restride) and as
    // src/superembedder/seam_serialize.cpp's own semb_seam_serialize_document
    // reads (`codes[p * hidden + i]`). A PRIOR version of this function
    // restrided into a SECOND buffer under the assumption that positions
    // were spaced kSembWitnessMaxHidden apart -- correct only by
    // coincidence when hidden_size == kSembWitnessMaxHidden (true of every
    // artifact this achievement cell had executed against before this
    // round, since the real candidate's hidden_size is exactly 1024) and
    // silently WRONG whenever they differ (this round's mechanism pair,
    // hidden 32): every position past 0 read past where the engine
    // actually wrote and returned zero-initialised vector padding.
    // Executed and confirmed: at hidden=32, `codes[63*32+i]` (correct)
    // reads the engine's real last-position output; `codes[63*1024+i]`
    // (the retired restride) reads unwritten padding. Fixed by passing
    // `codes.data()` directly, matching c39's own established pattern --
    // no second buffer, no restride.
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

    std::vector<uint8_t> doc_buf(16 + ids.size() * (hidden + 16));
    size_t doc_len = 0;
    const SembSerializeStatus sst = semb_seam_serialize_document(codes.data(), m.data(), e.data(), ids.size(),
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

// The product's encoder-scoped W-Q witness digest accessor (TE-224 M-1,
// include/superembedder/wq_digest_abi.h), declared in this TU's own
// contract types for the (fingerprint) cell below, at file scope because
// MSVC rejects a function-local linkage specification (C2598, executed
// against TE-228): including the product header in this TU would pull
// superembedder/semb.h's own typedefs over this suite's independent
// semb_public_abi_contract.h types -- the duplicate-definition conflict
// include/superembedder/wb_digest_abi.h's own header comment names
// (executed against TE-228: four redefinition errors) -- and the
// declaration's own types are layout-identical across both typedef sets,
// the same convention tests/semb_wb_witness_abi_contract.h establishes
// for semb_wb_digest.
extern "C" semb_status semb_wq_digest(semb_encoder enc, uint8_t out_digest[32]);

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
    // TE-155 item 1 (D-SLM6341): the mutation is PREPENDED, not appended.
    // The cap-cut keeps each document's LEADING max_content_ids ids, so a
    // mutation appended at the end would land entirely inside the CUT
    // portion whenever the leg's own context_cap is small enough that
    // document 5 already saturates it (the mechanism pair's 64-token cap,
    // confirmed by execution: an appended " (mutated)" suffix left this
    // cell's own digest UNCHANGED against that leg, since the corpus's own
    // 16 documents each tokenize to well over 63 ids there and every
    // appended byte was cut away before reaching the forward). Prepending
    // shifts the whole document's own tokenization from position 0, so the
    // mutation is visible within the kept prefix regardless of which leg
    // (real or mechanism) this binary is running against.
    mutated_corpus[5].text = "(mutated) " + mutated_corpus[5].text;
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

  // ---- TE-192 item 5 (TE-187 bare cell 1, D-SLM6406/D-SLM6457): the
  // framed-text cut divergence. A non-empty hypothesis frame ("FRAME ",
  // the same construction TE-184/N-8 exercises against the source fix,
  // D-SLM6452) against the real tokenizer, at whichever context_cap this
  // leg's own artifact carries -- asserts the composed-budget cut point
  // (this file's own corrected CutToComposedBudget) differs from the
  // bare-text cut point (the pre-TE-184 rule, realized here as
  // CutToComposedBudget called with an EMPTY frame, which is exactly what
  // the retired algorithm computed) on at least one committed document,
  // and that the bare rule's own cut point, once the frame is actually
  // prepended, VIOLATES the composed budget -- the corner D-SLM6406 found
  // unaccounted, and the must-reject this bare cell names: the pre-TE-184
  // implementation fails this construction because its own cut point is
  // provably over budget once a frame is real. ----
  {
    const std::vector<uint8_t> tokenizer_bytes = ReadFile(a.tokenizer);
    superslm::SslmArtifact tokenizer_artifact;
    superslm::SslmError artifact_error;
    std::string why_setup;
    bool setup_ok = !tokenizer_bytes.empty() &&
                     superslm::SslmArtifact::OpenFromMemory(tokenizer_bytes.data(), tokenizer_bytes.size(),
                                                              tokenizer_artifact, &artifact_error) ==
                         superslm::SslmStatus::Ok;
    superslm::TokenizerView tokenizer;
    std::string tok_err;
    if (setup_ok) setup_ok = superslm::TokenizerView::Open(tokenizer_artifact, tokenizer, &tok_err);
    if (!setup_ok) {
      Missing("(framed-cut-divergence) the composed-budget cut point differs from the bare-text cut point "
              "at a non-empty frame, and the bare rule's own cut violates the composed budget",
              "cannot open the tokenizer artifact for an independent frame/cap probe");
    } else {
      const std::vector<int32_t> end_ids2 = tokenizer.Encode("<|endoftext|>");
      SembInterimEncoder* cap_probe2 = nullptr;
      const char* cap_probe2_status = nullptr;
      SembInterimGeometry geometry2{};
      geometry2.struct_size = sizeof(geometry2);
      bool cap_ok = end_ids2.size() == 1 &&
                    semb_interim_encoder_open(a.model.c_str(), end_ids2[0], &cap_probe2, &cap_probe2_status) ==
                        kSembInterimOk;
      if (cap_ok) {
        cap_ok = semb_interim_encoder_geometry(cap_probe2, &geometry2) == kSembInterimOk;
        semb_interim_encoder_close(cap_probe2);
      }
      if (!cap_ok) {
        Missing("(framed-cut-divergence) the composed-budget cut point differs from the bare-text cut point "
                "at a non-empty frame, and the bare rule's own cut violates the composed budget",
                "cannot discover context_cap for an independent frame/cap probe");
      } else {
        const size_t max_content_ids =
            geometry2.context_cap > 0 ? static_cast<size_t>(geometry2.context_cap) - 1 : 0;
        constexpr std::string_view kHypothesisFrame = "FRAME ";
        bool found_divergence = false;
        std::string divergence_detail;
        for (const Record& r : corpus) {
          const std::string_view bare_cut = CutToComposedBudget(tokenizer, "", r.text, max_content_ids);
          const std::string_view composed_cut = CutToComposedBudget(tokenizer, kHypothesisFrame, r.text, max_content_ids);
          if (bare_cut == composed_cut) continue;  // this document does not reach the divergence corner
          const size_t bare_cut_with_frame_len =
              tokenizer.Encode(std::string(kHypothesisFrame) + std::string(bare_cut)).size();
          const size_t composed_cut_with_frame_len =
              tokenizer.Encode(std::string(kHypothesisFrame) + std::string(composed_cut)).size();
          found_divergence = true;
          divergence_detail = "doc=" + r.id + " bare_cut_len=" + std::to_string(bare_cut.size()) +
                               " composed_cut_len=" + std::to_string(composed_cut.size()) +
                               " bare_cut_with_frame_ids=" + std::to_string(bare_cut_with_frame_len) +
                               " composed_cut_with_frame_ids=" + std::to_string(composed_cut_with_frame_len) +
                               " max_content_ids=" + std::to_string(max_content_ids);
          Verdict(bare_cut_with_frame_len > max_content_ids,
                  "(framed-cut-divergence) the bare-text (pre-TE-184) cut point, once the frame is prepended, "
                  "EXCEEDS the composed budget -- exactly the defect D-SLM6406 found",
                  divergence_detail);
          Verdict(composed_cut_with_frame_len <= max_content_ids,
                  "(framed-cut-divergence) the composed-budget cut point (this file's own corrected oracle) "
                  "stays within the composed budget once the frame is prepended",
                  divergence_detail);
          break;  // one documented corner is sufficient; the loop exists to find one on whichever leg runs
        }
        if (!found_divergence) {
          Missing("(framed-cut-divergence) the composed-budget cut point differs from the bare-text cut point "
                  "at a non-empty frame, and the bare rule's own cut violates the composed budget",
                  "no committed document reaches this leg's own context_cap (" + std::to_string(geometry2.context_cap) +
                      ") even with the hypothesis frame prepended -- expected on the real candidate (cap 32,768), "
                      "reachable on the mechanism pair (cap 64)");
        }
      }
    }
  }

  // ---- Mutation-proof of THIS FILE'S OWN cut rule (TE-172, N-7): the
  // recomputation's cut must be the RULED rule (D-SLM6390 item 2 -- the
  // longest UTF-8-boundary byte prefix whose tokenized length is at most
  // context_cap-1, found through the tokenizer), not the RETIRED one
  // (tokenize the whole document, then resize() the id array). The two
  // rules coincide over EVERY (tokenizer, cap) pair this suite's own
  // achievement cell otherwise drives -- the real candidate never cuts at
  // cap 32768, and the mechanism pair's near-byte-level tokenizer
  // coincides with both rules at every budget 1-200 (0 of 200, executed
  // and confirmed this round) -- so neither existing leg can make cell (a)
  // fail on this claim; a wrong cut rule would pass it silently, which is
  // exactly how this diff shipped with the retired rule still in place.
  //
  // Driven instead at a (tokenizer, cap) pair this round's own execution
  // found the two rules DO diverge on (Claude/Poirot's own casebook, N-7
  // sec 6 F-5, reproduced independently this round): the REAL Qwen3
  // tokenizer, committed document "wb-03" ("Fresh bread, two coppers a
  // loaf, and the miller wants his due before the week turns again."),
  // max_content_ids = 1 (a context_cap of 2) -- the FIRST divergent budget
  // of the 23 (of 200 swept, 1-200) the real tokenizer diverges on; the
  // mechanism tokenizer diverges on NONE of the 200, so this cell only
  // runs on the real leg (a.dims == 1024, this suite's own established
  // real-leg signal, tests/u1_workspace_seam_test.cpp's precedent) --
  // running it against the mechanism tokenizer would be vacuous, since
  // both rules already agree there.
  //
  // Both rules' outputs are PINNED to values this round's own execution
  // established against the real tokenizer artifact (a scratch probe
  // reproducing both rules over the committed corpus, D:\te172_scratch,
  // never committed) rather than recomputed a third way here -- a third
  // implementation could share the same bug as the first two, and pinning
  // is the mutation-proof: reverting CutToComposedBudget (empty frame) to the
  // retired rule makes `ruled` produce the RETIRED value instead, and this
  // cell goes red. ----
  if (a.dims == 1024) {
    const std::vector<uint8_t> tokenizer_bytes = ReadFile(a.tokenizer);
    superslm::SslmArtifact tokenizer_artifact;
    superslm::SslmError artifact_error;
    bool ok = !tokenizer_bytes.empty() && superslm::SslmArtifact::OpenFromMemory(
                                               tokenizer_bytes.data(), tokenizer_bytes.size(), tokenizer_artifact,
                                               &artifact_error) == superslm::SslmStatus::Ok;
    superslm::TokenizerView tokenizer;
    std::string tok_err;
    if (ok) ok = superslm::TokenizerView::Open(tokenizer_artifact, tokenizer, &tok_err);
    if (!ok) {
      Missing("(cut-rule) the ruled cut (D-SLM6390 item 2) diverges from the retired one at a "
              "(tokenizer, cap) pair this round's own execution found",
              "cannot open the real tokenizer artifact independently of ComputeExpectedWbDigest");
    } else if (corpus.size() <= 3 || corpus[3].id != "wb-03") {
      Missing("(cut-rule) the ruled cut (D-SLM6390 item 2) diverges from the retired one at a "
              "(tokenizer, cap) pair this round's own execution found",
              "corpus[3] is not the committed document wb-03 this cell's pinned values are against -- "
              "the fixture's own document order changed");
    } else {
      constexpr size_t kMaxContentIds = 1;  // context_cap 2 -- the first divergent budget (F-5)
      const std::string_view text(corpus[3].text);
      const std::vector<int32_t> ruled =
          tokenizer.Encode(CutToComposedBudget(tokenizer, "", text, kMaxContentIds));
      // The RETIRED rule, reproduced independently right here (not via the
      // shared helper), so a mutation to the helper alone cannot make both
      // sides move together and vacuously agree.
      std::vector<int32_t> retired = tokenizer.Encode(text);
      if (retired.size() > kMaxContentIds) retired.resize(kMaxContentIds);

      auto ids_to_string = [](const std::vector<int32_t>& ids) {
        std::string s;
        for (int32_t id : ids) s += std::to_string(id) + " ";
        return s;
      };
      const std::vector<int32_t> kExpectedRuled = {36731};
      const std::vector<int32_t> kExpectedRetired = {55653};
      Verdict(ruled == kExpectedRuled,
              "(cut-rule) wb-03 cut to max_content_ids=1 under the ruled rule (D-SLM6390 item 2, this "
              "file's own CutToComposedBudget (empty frame)) equals the value this round's own execution "
              "established against the real tokenizer",
              "ruled=(" + ids_to_string(ruled) + ")");
      Verdict(retired == kExpectedRetired,
              "(cut-rule) (control) wb-03 cut to max_content_ids=1 under the RETIRED rule equals the "
              "value this round's own execution established -- confirms the two rules genuinely diverge "
              "here, so the cell above can actually fail rather than passing by construction",
              "retired=(" + ids_to_string(retired) + ")");
    }
  } else {
    Missing("(cut-rule) the ruled cut (D-SLM6390 item 2) diverges from the retired one at a "
            "(tokenizer, cap) pair this round's own execution found",
            "mechanism tokenizer: 0 of 200 budgets 1-200 differ between the two rules (executed this "
            "round) -- no divergent pair exists at this scale to drive");
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
    size_t cut_count = 0;
    if (!ComputeExpectedWbDigest(a.model, a.tokenizer, corpus, expected, &why_expected, &cut_count)) {
      Missing("W-B semb_wb_digest(enc, ...) equals the independent corpus-witness recomputation", why_expected);
    } else {
      // ---- Cap-cut witness (D-SLM6341, D-SLM6390 item 2, TE-172 N-7):
      // report how many of the 16 committed documents needed a SHORTER
      // prefix than their own full text -- i.e., whose full tokenization
      // would have exceeded context_cap-1 ids -- before the end token was
      // appended. Reported rather than asserted against a fixed count,
      // since this SAME binary runs against both the real candidate
      // (context_cap 32768 -- 0 documents expected to cut, since all 16
      // are short prose) and the mechanism pair (context_cap 64 -- every
      // document expected to cut, since the near-byte-level tokenizer
      // produces well over 64 ids for an 83-108 character document) with
      // no flag telling it which; the two invocations' own quoted output
      // is where the "0 on real, > 0 on mechanism" rule (D-SLM6341) is
      // witnessed, per this suite's own driver
      // (tests/u1_batch_contract_check.py) running this executable once
      // per leg. ----
      Verdict(true,
              "(cap-cut) documents cut to a prefix whose tokenized length is at most context_cap-1 content "
              "ids before the end token was appended (D-SLM6341, D-SLM6390 item 2: semb_encoder_open never "
              "refuses on account of the witness corpus)",
              std::to_string(cut_count) + " of " + std::to_string(corpus.size()) + " document(s) cut");

      semb_encoder enc1 = Open(a);
      if (enc1) {
        uint8_t actual[32];
        const semb_status sa = semb_wb_digest(enc1, actual);
        Verdict(Is(sa, "SEMB_OK") && std::memcmp(expected, actual, 32) == 0,
                "(a) W-B semb_wb_digest(enc, ...) equals the independent recomputation of sec 4.4b's own "
                "formula over the committed 16-document corpus, for a handle opened on the same model and "
                "tokenizer (achievement claim: the wiring reads the REAL corpus, not kWbPendingSentinel)",
                std::string(Name(sa)) + " expected=" + Hex(expected) + " actual=" + Hex(actual));

        // (b) RETIRED, TE-160/S-7 (this file's own header comment carries
        // the full account). `semb_wb_digest` is a memcpy from a field
        // written once at open, so two calls on one handle comparing that
        // field against itself cannot fail under any product behaviour --
        // removed rather than kept as a green cell that grades nothing.

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

  // ---- (d) Id-inertness over EVERY EMITTED ROW (TE-160/S-7, replacing the
  // retired construction the review's S-7 found dead): TE-96 sec 4.7's own
  // text, "ids are inert -- permuting the ids over a fixed text set leaves
  // every row byte-identical." Three FIXED texts at three FIXED row
  // positions; two batch calls differing ONLY in which id, from the SAME
  // id set, is attached to which position -- the ids are PERMUTED across
  // the fixed positions (a derangement, so every position gets a different
  // id under the second assignment), the texts and their row order are
  // not. Every emitted row is asserted byte-identical between the two
  // calls. This grades the BATCH PATH's own row output (semb_encode_batch),
  // never the cached wb_digest field the retired construction read -- the
  // guard-vitality mutation TE-96 sec 4.5's own W-B row names for this
  // claim ("fold the id into the tokenizer input") moves a ROW's bytes, so
  // this construction, unlike the retired one, can see it (mutation-proof
  // executed and filed in this round's own casebook). ----
  {
    semb_encoder enc = Open(a);
    if (enc) {
      const std::vector<std::string> texts = {
          "the first row's own fixed text",
          "the second row's own fixed text",
          "the third row's own fixed text",
      };
      const std::vector<std::string> ids = {"row-alpha", "row-beta", "row-gamma"};
      const std::vector<size_t> permuted_order = {1, 2, 0};  // a derangement: ids[1],ids[2],ids[0]

      auto bake = [&](const std::vector<std::string>& row_ids, std::vector<std::vector<uint8_t>>* out_rows,
                      semb_status* out_status) {
        std::vector<semb_document> docs;
        for (size_t i = 0; i < texts.size(); ++i) {
          semb_document d{};
          d.struct_size = sizeof(semb_document);
          d.id = row_ids[i].c_str();
          d.id_len = row_ids[i].size();
          d.utf8 = texts[i].c_str();
          d.utf8_len = texts[i].size();
          docs.push_back(d);
        }
        const size_t required = texts.size() * static_cast<size_t>(a.dims) * sizeof(float);
        std::vector<uint8_t> buf(required + 64, 0xA5);
        auto p = reinterpret_cast<uintptr_t>(buf.data());
        float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
        size_t req = 0xBAD5EED;
        *out_status = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
        out_rows->clear();
        if (*out_status == SEMB_OK) {
          for (size_t i = 0; i < texts.size(); ++i) {
            auto b = reinterpret_cast<uint8_t*>(aligned) + i * static_cast<size_t>(a.dims) * sizeof(float);
            out_rows->emplace_back(b, b + static_cast<size_t>(a.dims) * sizeof(float));
          }
        }
      };

      std::vector<std::vector<uint8_t>> rows_a, rows_b;
      semb_status s_a = -1000, s_b = -1000;
      bake(ids, &rows_a, &s_a);
      std::vector<std::string> ids_permuted(texts.size());
      for (size_t i = 0; i < texts.size(); ++i) ids_permuted[i] = ids[permuted_order[i]];
      bake(ids_permuted, &rows_b, &s_b);

      bool ok = Is(s_a, "SEMB_OK") && Is(s_b, "SEMB_OK") && rows_a.size() == texts.size() &&
                rows_b.size() == texts.size();
      std::string detail = "s_a=" + std::string(Name(s_a)) + " s_b=" + std::string(Name(s_b));
      if (ok) {
        for (size_t i = 0; i < texts.size(); ++i) {
          if (rows_a[i] != rows_b[i]) { ok = false; detail += " row" + std::to_string(i) + "-mismatch"; }
        }
      }
      Verdict(ok,
              "(d) row-level id-inertness (TE-96 sec 4.7 must-accept, TE-160/S-7): permuting which id "
              "(of a fixed id set) is attached to which of three FIXED texts at three FIXED row "
              "positions leaves every emitted row byte-identical between the two calls",
              detail);
      semb_encoder_close(enc);
    }
  }

  // =========================================================================
  // TE-160/S-2: the emitted `semb_fingerprint` pinned against the five-field
  // composition, independently recomputed. TE-148's review (S-2) found no
  // cell anywhere asserts the emitted fingerprint depends on W-B: reverting
  // the fingerprint derivation (then `ComputeProvisionalFingerprint`) to
  // hash the retired `kWbPendingSentinel`
  // left all twelve W-B cells green, because none of them reads the
  // fingerprint at all. This cell closes that gap.
  //
  // The formula, from `Claude/Plans/SuperEmbedder_Plan.md` sec 3.3 (the
  // five length-prefixed fields) and sec 4.4b (`witness_sha = SHA-256(W-A
  // digest || W-B digest || W-Q digest)`, three fixed-width components,
  // "need no length-prefix to stay injective"), and from TE-148 review's
  // own sec 6 F-4 derivation -- the reference this cell is built from, not
  // the product's own composition code:
  //
  //   model_sha            = SHA-256(the model artifact's own file bytes)
  //   tokenizer_sha         = SHA-256(the tokenizer artifact's own file bytes)
  //   template_sha256       = SHA-256(u64_le(0) || u64_le(len(prefix)) || prefix
  //                                   || u64_le(len(end)) || end)
  //                           -- document_frame_bytes is empty under PS-N
  //                           (D-SLM4726); prefix is the compiled-in query
  //                           prefix literal sec 2.1 states verbatim: "Instruct:
  //                           Given a web search query, retrieve relevant
  //                           passages that answer the query\nQuery:"; end is
  //                           the compiled-in end-token literal sec 3.2 states,
  //                           "<|endoftext|>" (D-8, adopted D-SLM7185; U1
  //                           Slice 7 step 3)
  //   witness_sha           = SHA-256(wa_digest || wb_digest || wq_digest)
  //                           -- wa_digest is semb_wa_digest()'s own output;
  //                           wb_digest is semb_wb_digest(enc, ...)'s own
  //                           output (the same accessor property (a), above,
  //                           pins); wq_digest is semb_wq_digest(enc, ...)'s
  //                           own output (TE-224 M-1, the encoder-scoped
  //                           diagnostic accessor, declared in-cell in this
  //                           TU's own contract types) -- W-Q's leg folds
  //                           from the product's own accessor exactly the
  //                           way W-B's does (TE-228)
  //   certification_epoch   = the identity file's digest in the verdict's
  //                           form (U2-3 items 1 and 9, te267 P:1003-1006,
  //                           P:1156-1158; D-SLM7309): SHA-256 of
  //                           docs/certification-identity.json's exact bytes,
  //                           read by this cell from the repository file, for
  //                           a certified cell, else SHA-256("SEMB-UNCERTIFIED"
  //                           || NUL || those bytes). The form is the verdict
  //                           a one-document bake by the SAME encoder reports
  //                           as its manifest's certified_cell; the verdict
  //                           itself is graded independently of the product
  //                           by tests/te264_fingerprint_final_check.py's
  //                           epoch cell (tests/support/semb_epoch_oracle.h)
  //
  //   fingerprint = SHA-256(u64_le(32)||model_sha || u64_le(32)||tokenizer_sha
  //                          || u64_le(32)||template_sha256 || u64_le(32)||witness_sha
  //                          || u64_le(32)||certification_epoch)
  //
  // the full 32-byte digest over the five length-prefixed fields, no tag and
  // no truncation (sec 3.3; `SEMBP001` retired at U1 Slice 7 step 5). The
  // expected value takes no input from the product beyond the three witness
  // accessor digests and the verdict its own bake reports: the literals are
  // typed from the plan and the identity file is read from the repository. It was RED by
  // design until U1 Slice 7's steps 3, 4 and 5 all landed (TE-264). The
  // mutation-proof below (this round's own casebook) is what confirms the
  // cell is actually sensitive to W-B's own fold rather than passing by
  // construction of a wrong formula.
  // =========================================================================
  {
    // W-Q's leg comes from the product's encoder-scoped accessor below,
    // declared in this TU's own contract types -- the same standing the W-B
    // leg has through semb_wb_digest in this same composition (TE-228).
    // sec 2.1's own literal, verbatim (confirmed against the plan, not
    // against src/superembedder/query.cpp's own kQueryPrefix).
    constexpr char kQueryPrefix[] =
        "Instruct: Given a web search query, retrieve relevant passages that answer the "
        "query\nQuery:";
    // sec 3.2's compiled-in end-token literal (D-8's third template field).
    constexpr char kEndToken[] = "<|endoftext|>";
    const std::vector<uint8_t> cert_doc = ReadFile(semb_epoch_oracle::kIdentityPath);

    auto sha256 = [](const void* data, size_t n, uint8_t out[32]) {
      superslm::Sha256 h;
      h.Update(reinterpret_cast<const uint8_t*>(data), n);
      h.Final(out);
    };
    auto update_field = [](std::vector<uint8_t>* buf, const uint8_t field[32]) {
      PutU64LE(buf, 32);
      buf->insert(buf->end(), field, field + 32);
    };

    const std::vector<uint8_t> model_bytes = ReadFile(a.model);
    const std::vector<uint8_t> tokenizer_bytes = ReadFile(a.tokenizer);
    if (model_bytes.empty() || tokenizer_bytes.empty() || cert_doc.empty()) {
      Verdict(false, "(fingerprint) semb_fingerprint equals the independently-recomputed five-field composition",
              cert_doc.empty() ? "docs/certification-identity.json is absent or empty in the repository (U2-3 "
                                 "item 9 writes it); the certification_epoch field cannot be recomputed"
                               : "cannot read model/tokenizer artifact bytes");
    } else {
      uint8_t model_sha[32], tokenizer_sha[32];
      sha256(model_bytes.data(), model_bytes.size(), model_sha);
      sha256(tokenizer_bytes.data(), tokenizer_bytes.size(), tokenizer_sha);

      uint8_t template_sha256[32];
      {
        std::vector<uint8_t> buf;
        PutU64LE(&buf, 0);  // document_frame_bytes: empty under PS-N (D-SLM4726)
        PutU64LE(&buf, sizeof(kQueryPrefix) - 1);
        buf.insert(buf.end(), kQueryPrefix, kQueryPrefix + sizeof(kQueryPrefix) - 1);
        PutU64LE(&buf, sizeof(kEndToken) - 1);
        buf.insert(buf.end(), kEndToken, kEndToken + sizeof(kEndToken) - 1);
        sha256(buf.data(), buf.size(), template_sha256);
      }

      semb_encoder enc = Open(a);
      if (enc) {
        uint8_t wa[32];
        semb_wa_digest(wa);
        uint8_t wb[32];
        const semb_status swb = semb_wb_digest(enc, wb);
        uint8_t wq[32]{};
        const semb_status swq = semb_wq_digest(enc, wq);
        uint8_t expected[32]{}, actual[32]{};
        bool composed = false;
        std::string wq_why;
        // The verdict this encoder reports: one document baked by the same
        // handle into a scratch stem, its manifest's certified_cell read.
        std::string cell;
        {
          const std::filesystem::path dir =
              std::filesystem::temp_directory_path() /
              ("w_b_corpus_witness_test_verdict_" +
               std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
          std::error_code ec;
          std::filesystem::create_directories(dir, ec);
          const std::string stem = (dir / "verdict").string();
          const char doc_id[] = "verdict-0";
          const char doc_text[] = "the verdict probe document";
          semb_document doc{};
          doc.struct_size = sizeof(doc);
          doc.id = doc_id;
          doc.id_len = sizeof(doc_id) - 1;
          doc.utf8 = doc_text;
          doc.utf8_len = sizeof(doc_text) - 1;
          const semb_status sb = semb_bake_to_path(enc, &doc, 1, stem.c_str(), stem.size());
          if (Is(sb, "SEMB_OK")) {
            const std::vector<uint8_t> m = ReadFile(stem + ".semb.json");
            cell = semb_epoch_oracle::CertifiedCellOf(std::string(m.begin(), m.end()));
          }
          wq_why = "bake=" + std::string(Name(sb)) + " certified_cell=" + (cell.empty() ? "<none>" : cell);
          std::filesystem::remove_all(dir, ec);
        }
        if (Is(swq, "SEMB_OK") && Is(swb, "SEMB_OK") && !cell.empty()) {
          uint8_t witness_sha[32], certification_epoch[32];
          std::vector<uint8_t> witness;
          witness.insert(witness.end(), wa, wa + 32);
          witness.insert(witness.end(), wb, wb + 32);
          witness.insert(witness.end(), wq, wq + 32);
          sha256(witness.data(), witness.size(), witness_sha);
          semb_epoch_oracle::EpochFor(cell, std::string(cert_doc.begin(), cert_doc.end()), certification_epoch);

          std::vector<uint8_t> composition;
          update_field(&composition, model_sha);
          update_field(&composition, tokenizer_sha);
          update_field(&composition, template_sha256);
          update_field(&composition, witness_sha);
          update_field(&composition, certification_epoch);
          sha256(composition.data(), composition.size(), expected);

          std::vector<uint8_t> storage(static_cast<size_t>(a.dims) * sizeof(float) + 16);
          float* vector = reinterpret_cast<float*>(
              (reinterpret_cast<uintptr_t>(storage.data()) + 15) & ~uintptr_t(15));
          size_t required = 0;
          semb_fingerprint fp{};
          fp.struct_size = sizeof(fp);
          const char probe[] = "five-field fingerprint probe";
          const semb_status se = semb_encode(enc, probe, sizeof(probe) - 1, vector,
                                             static_cast<size_t>(a.dims) * sizeof(float),
                                             &required, &fp);
          std::memcpy(actual, fp.digest, sizeof(actual));
          composed = Is(se, "SEMB_OK") &&
                     std::memcmp(expected, actual, sizeof(expected)) == 0;
          wq_why += " raw=" + std::string(Name(se)) + " expected=" + Hex(expected) +
                    " actual=" + Hex(actual);
        } else {
          wq_why += " wq=" + std::string(Name(swq)) + " wb=" + std::string(Name(swb));
        }
        Verdict(composed, "(fingerprint) semb_fingerprint equals the independently-recomputed five-field composition",
                wq_why);
        semb_encoder_close(enc);
      } else {
        Verdict(false, "(fingerprint) semb_fingerprint equals the independently-recomputed five-field composition",
                "encoder open failed");
      }
    }
  }

  std::printf("\nw_b_corpus_witness_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
