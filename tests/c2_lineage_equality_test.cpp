// tests/c2_lineage_equality_test.cpp -- TE-162 (U1 slice 3): C2, lineage
// equality against the epoch store (`Claude/Plans/SuperEmbedder_Plan.md`
// sec 8, C2: "On the 239 corpus, the skeleton's per-position {codes, m, e}
// are byte-identical to the lineage digest held in C32's store under the
// build's own fingerprint. Not a re-run ... Not a second fixture") and, per
// the dispatch's own cell 4 ("fold into the C2 TU"), the vector member
// against the raw path -- every row of `vectors.f32` equals `semb_encode`
// of the document's text, bit for bit, for the real artifact.
//
// A FEATURE oracle (Curie's own dimension-10 discipline: an achievement
// claim gets a test that executes the definition and asserts the
// end-state), built from the dispatch's own named primitives -- "the seam
// serialisation and the witness call... the lineage oracle's only two
// primitives":
//
//   1. Read each corpus document's own committed content token ids
//      (--tokens), append --terminator-id once (sec 4.4b, sec 3.1's PS-N
//      crossing: no document frame, content-then-terminator).
//   2. semb_encode_document_for_witness(--model, ids, n,
//      /*chunk_budget=*/0, ...) -- the whole-document real forward, per
//      position.
//   3. semb_seam_serialize_document(...) over EVERY position (position 0
//      included, the appended end token included) -> this document's own
//      seam bytes -> SHA-256 -> the value this cell asserts against the
//      store's own lineage.tsv row for the SAME document id, under the
//      fingerprint the LIVE handle emits (semb_fingerprint via
//      semb_encoder_open/semb_encode -- the provisional tag is part of the
//      key today, sub-plan sec 4.3 "D-8 gating": correct, since a later
//      fingerprint composition change is a new append, never a re-mint).
//
// This recomputation takes NO input from whatever entry point minted the
// store's own founding entry (the builder's own job, sub-plan sec 4.3
// "Founding entry": "your cells grade what is minted") and NO input from
// `tests/c12b_row_digest_check.py`'s own instrument, which ALSO emits a
// `seam_sha256` column of the identical definition -- reusing it here
// would be grading the store against the same tool a founder could have
// used to mint it, exactly what sec 8 C2's own "not a re-run" text
// excludes. `semb_encode_document_for_witness` and
// `semb_seam_serialize_document` are the two primitives this file uses,
// per the dispatch's own naming of them as "the lineage oracle's only two
// primitives."
//
// RED AT 310c47d, BY NAME: `epoch-store/` does not exist anywhere in this
// tree (`grep -rniE "epoch_store|EpochStore|lineage"` across `src/`,
// `include/`, `tools/` returns nothing, confirmed this round) -- every
// per-document comparison below reports MISSING PREREQUISITE, named as "no
// live entry under any fingerprint," never a silent skip and never a
// false PASS.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --dims <n> --tokens <tsv>
//   --terminator-id <n> --store-root <dir> [--corpus-jsonl <jsonl>]
// --corpus-jsonl supplies the real artifact's own committed text for cell
// 4's raw-path check (real artifact only, per the dispatch); omitted for
// the synthetic leg, which exercises C2's own lineage claim alone.
// CELL 4 BINDS BY DOCUMENT ID, NEVER BY LIST POSITION (S3, TE-170): the
// text corpus (--corpus-jsonl) and the token corpus (--tokens) are two
// files nothing else binds together, and vectors.f32's own rows are
// written in --tokens order (mint.cpp's RunAssemble), not jsonl order.
// Every id named in --tokens must have a --corpus-jsonl entry -- a missing
// one is a named FAIL, never a silently smaller graded row count -- and
// the row read from vectors.f32 for a given document is located by that
// document's own index in --tokens, never by its index in the jsonl.
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_seam_abi_contract.h"
#include "semb_epoch_store_contract.h"
#include "subprocess_util.h"

#include "superslm/sha256.h"

namespace {

int g_cells = 0;
int g_failures = 0;
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

struct Args {
  std::string model, tokenizer, tokens, store_root, corpus_jsonl;
  unsigned dims = 0;
  long terminator_id = -1;
  bool regen_synthetic = false;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--dims") { std::string v; next(&v); a.dims = static_cast<unsigned>(std::atoi(v.c_str())); }
    else if (k == "--tokens") next(&a.tokens);
    else if (k == "--terminator-id") { std::string v; next(&v); a.terminator_id = std::atol(v.c_str()); }
    else if (k == "--store-root") next(&a.store_root);
    else if (k == "--corpus-jsonl") next(&a.corpus_jsonl);
    else if (k == "--regen-synthetic-pair") a.regen_synthetic = true;
  }
  return a;
}

// FINDING, executed rather than assumed (this round): the dispatch's own
// fixed points name `tests/fixtures/regenerate_synthetic_artifact.py`
// (hidden 32, vocab 128, context_cap 64) as "the synthetic tiny artifact"
// for the epoch store's founding entry. That fixture carries NO real
// tokenizer structure -- confirmed by execution, this round:
// semb_encoder_open(model_path == tokenizer_path == that artifact) returns
// SEMB_ENGINE_REFUSED. The root cause is documented at source, one file
// over: tests/fixtures/regenerate_tokenizer_pair_fixture.py's own header
// comment states it plainly -- "a byte-level BPE tokenizer needs 256 base
// ids before any merge or special, so its ids do not fit a 128-entry
// vocabulary" -- which is exactly why THAT script exists and mints a
// SEPARATE, already-tokenizer-capable pair (vocab 384, hidden 32,
// context_cap 64, <|endoftext|>=262) for every U1 cell that calls
// semb_encoder_open against a synthetic artifact (tests/
// c41_environment_invariance_test.cpp, tests/u1_raw_text_contract_test.cpp).
//
// This test needs semb_encoder_open (the only public way to read the live
// fingerprint this slice; semb_fingerprint_of does not exist until Slice
// 5) alongside semb_encode_document_for_witness (which needs a model but
// no tokenizer) -- so BOTH calls use the SAME already-tokenizer-capable
// pair below, rather than mixing two different underlying models under
// one nominal "fingerprint." ROUTED: the founding-entry recipe the
// dispatch names for the synthetic leg needs the identical correction --
// stated in this round's own handoff, not silently worked around here.
//
// Regenerated (or reused, if already present) at the SAME cache path
// tests/c41_environment_invariance_test.cpp and
// tests/u1_raw_text_cells_check.py's own ensure_pair() already use
// (build/_scratch/u1_pair/), so running this test after (or alongside)
// those costs nothing extra; run alone on a fresh build, it mints the pair
// itself rather than depending on ctest's own unspecified ordering.
struct SyntheticPair { std::string model, tokenizer; };
SyntheticPair EnsureSyntheticPairForC2() {
  const std::string dir = "build/_scratch/u1_pair";
  const std::string model_path = dir + "/u1_pair_model.sslm";
  const std::string tokenizer_path = dir + "/u1_pair_tokenizer.sslm";
  std::ifstream mp(model_path, std::ios::binary), tp(tokenizer_path, std::ios::binary);
  if (mp.good() && tp.good()) return {model_path, tokenizer_path};
  const char* env = std::getenv("SEMB_TEST_ENGINE_SOURCE");
  std::string source_arg;
  if (env && *env) source_arg = std::string(" --source \"") + env + "\"";
  const std::string cmd = semb_test::PythonExecutable() +
                           " tests/fixtures/regenerate_tokenizer_pair_fixture.py --lock "
                           "superslm.lock --out-dir " + dir + source_arg;
  semb_test::RunCaptureStdout(cmd);  // throws on failure
  return {model_path, tokenizer_path};
}

struct DocTokens { std::string id; std::vector<int32_t> ids; };

std::vector<DocTokens> ReadTokensTsv(const std::string& path, long terminator_id, std::string* why) {
  std::vector<DocTokens> out;
  std::ifstream f(path);
  if (!f) { *why = "cannot open " + path; return out; }
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    size_t tab = line.find('\t');
    if (tab == std::string::npos) { *why = "line has no tab: " + line; return {}; }
    DocTokens d;
    d.id = line.substr(0, tab);
    std::string ids_field = line.substr(tab + 1);
    std::stringstream ss(ids_field);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
      if (!tok.empty()) d.ids.push_back(static_cast<int32_t>(std::atol(tok.c_str())));
    }
    d.ids.push_back(static_cast<int32_t>(terminator_id));
    out.push_back(std::move(d));
  }
  return out;
}

bool ExtractJsonString(const std::string& line, const char* key, std::string* value) {
  const std::string needle = std::string("\"") + key + "\":";
  size_t p = line.find(needle);
  if (p == std::string::npos) return false;
  p += needle.size();
  while (p < line.size() && line[p] == ' ') ++p;
  if (p >= line.size() || line[p] != '"') return false;
  ++p;
  std::string s;
  while (p < line.size() && line[p] != '"') {
    if (line[p] == '\\' && p + 1 < line.size()) {
      char c = line[p + 1];
      if (c == '"' || c == '\\' || c == '/') { s.push_back(c); p += 2; continue; }
      return false;
    }
    s.push_back(line[p]);
    ++p;
  }
  if (p >= line.size()) return false;
  *value = s;
  return true;
}

std::vector<std::pair<std::string, std::string>> ReadJsonlTexts(const std::string& path, std::string* why) {
  std::vector<std::pair<std::string, std::string>> out;
  std::ifstream f(path);
  if (!f) { *why = "cannot open " + path; return out; }
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    std::string id, text;
    if (!ExtractJsonString(line, "label", &id) && !ExtractJsonString(line, "id", &id)) {
      *why = "no 'label' or 'id' key: " + line;
      return {};
    }
    if (!ExtractJsonString(line, "text", &text)) { *why = "no 'text' key: " + line; return {}; }
    out.push_back({id, text});
  }
  return out;
}

std::string Hex(const uint8_t d[32]) { return superslm::ToHex(d); }

std::string ToLowerHex64(const uint8_t digest[32]) {
  std::string s = Hex(digest);
  for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return s;
}

// Reads tests/semb_epoch_store_contract.h's own lineage.tsv format: one
// "<id>\t<seam_sha256>\n" line per document, a trailing "all\t...\n" line.
// Returns false with `why` set if the file is absent or malformed --
// MISSING PREREQUISITE, never a silent empty map.
bool ReadLineageTsv(const std::string& path, std::map<std::string, std::string>* out, std::string* why) {
  std::ifstream f(path);
  if (!f) { *why = "cannot open " + path; return false; }
  std::string line;
  bool saw_all = false;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    size_t tab = line.find('\t');
    if (tab == std::string::npos) { *why = "malformed line (no tab): " + line; return false; }
    std::string key = line.substr(0, tab);
    std::string value = line.substr(tab + 1);
    if (key == "all") { saw_all = true; continue; }
    (*out)[key] = value;
  }
  if (!saw_all) { *why = "no trailing 'all' line in " + path; return false; }
  return true;
}

// This TU's own independent recomputation of one document's lineage seam
// digest (sec 4.4b): serialise EVERY position, SHA-256 the stream. Takes
// NO input from the store, from c12b's instrument, or from any founder.
bool ComputeSeamDigest(const std::string& model, const DocTokens& doc, uint8_t out_digest[32], std::string* why) {
  std::vector<int8_t> codes(doc.ids.size() * kSembWitnessMaxHidden);
  std::vector<int64_t> m(doc.ids.size()), e(doc.ids.size());
  size_t hidden = 0;
  const SembEncodeStatus est = semb_encode_document_for_witness(
      model.c_str(), doc.ids.data(), doc.ids.size(), /*chunk_budget=*/0, codes.data(), m.data(), e.data(), &hidden);
  if (est != kSembEncodeOk) {
    *why = "semb_encode_document_for_witness refused (status " + std::to_string(static_cast<int>(est)) + ")";
    return false;
  }
  std::vector<uint8_t> buf(16 + doc.ids.size() * (hidden + 16));
  size_t len = 0;
  const SembSerializeStatus sst =
      semb_seam_serialize_document(codes.data(), m.data(), e.data(), doc.ids.size(), hidden, buf.data(), buf.size(), &len);
  if (sst != kSembSerializeOk) { *why = "semb_seam_serialize_document refused"; return false; }
  superslm::Sha256Hash(buf.data(), len, out_digest);
  return true;
}

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
  if (s != SEMB_OK || !enc) { Verdict(false, "(setup) open", semb_status_name(s)); return nullptr; }
  return enc;
}

}  // namespace

int main(int argc, char** argv) {
  Args a = ParseArgs(argc, argv);
  if (a.regen_synthetic && a.model.empty()) {
    try {
      const SyntheticPair pair = EnsureSyntheticPairForC2();
      a.model = pair.model;
      if (a.tokenizer.empty()) a.tokenizer = pair.tokenizer;
    } catch (const std::exception& ex) {
      std::fprintf(stderr, "c2_lineage_equality_test: could not regenerate the synthetic pair: %s\n", ex.what());
      return 1;
    }
  }
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0 || a.tokens.empty() || a.terminator_id < 0 ||
      a.store_root.empty()) {
    std::fprintf(stderr,
                 "usage: %s --model <.sslm> --tokenizer <.sslm> --dims <n> --tokens <tsv> "
                 "--terminator-id <n> --store-root <dir> [--corpus-jsonl <jsonl>] [--regen-synthetic-pair]\n",
                 argv[0]);
    return 2;
  }

  std::string why;
  const std::vector<DocTokens> docs = ReadTokensTsv(a.tokens, a.terminator_id, &why);
  if (docs.empty()) {
    Missing("(setup) --tokens loads at least one document", why.empty() ? "empty corpus" : why);
    std::printf("\nc2_lineage_equality_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
    return 0;  // setup-only MISSING PREREQUISITE never fails the build.
  }
  Verdict(true, "(setup) corpus loaded", a.tokens + " (" + std::to_string(docs.size()) + " documents)");

  // ---- Mutation-proof of THIS FILE'S OWN oracle (Curie's "pin the
  // documented claim" discipline, matching tests/w_b_corpus_witness_test.cpp's
  // own convention): the recomputation must be SENSITIVE to token content,
  // or every comparison below is vacuous. ----
  {
    uint8_t correct[32], mutated[32];
    std::string why1, why2;
    const bool ok1 = ComputeSeamDigest(a.model, docs[0], correct, &why1);
    DocTokens mutated_doc = docs[0];
    if (!mutated_doc.ids.empty()) mutated_doc.ids[0] = mutated_doc.ids[0] ^ 1;
    const bool ok2 = ComputeSeamDigest(a.model, mutated_doc, mutated, &why2);
    if (ok1 && ok2) {
      Verdict(std::memcmp(correct, mutated, 32) != 0,
              "(mutation-proof) this file's own seam-digest recomputation is SENSITIVE to token content "
              "(flipping document 0's first token id produces a different digest)",
              "correct=" + Hex(correct) + " mutated=" + Hex(mutated));
    } else {
      Missing("(mutation-proof) this file's own seam-digest recomputation is sensitive to token content",
              "setup: " + why1 + " / " + why2);
    }
  }

  // ---- The current build's own live fingerprint (semb_fingerprint via
  // semb_encode's out-parameter -- the only public way to observe it this
  // slice; semb_fingerprint_of does not exist until Slice 5). ----
  std::string fingerprint_hex;
  {
    semb_encoder enc = Open(a);
    if (enc) {
      std::vector<float> throwaway(a.dims, 0.0f);
      size_t required = 0;
      semb_fingerprint fp{};
      fp.struct_size = sizeof(fp);
      const char kProbe[] = "c2_lineage_equality_test fingerprint probe";
      const semb_status es =
          semb_encode(enc, kProbe, sizeof(kProbe) - 1, throwaway.data(), throwaway.size() * sizeof(float), &required, &fp);
      if (es == SEMB_OK) {
        fingerprint_hex = ToLowerHex64(fp.digest);
        Verdict(true, "(setup) live fingerprint read", fingerprint_hex);
      } else {
        Verdict(false, "(setup) live fingerprint read", semb_status_name(es));
      }
      semb_encoder_close(enc);
    }
  }
  if (fingerprint_hex.empty()) {
    Missing("C2 lineage equality (all documents)", "no live fingerprint could be read");
    std::printf("\nc2_lineage_equality_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
    return g_failures ? 1 : 0;
  }

  const std::string lineage_path = a.store_root + "/live/" + fingerprint_hex + "/" + semb_epoch_contract::kLineageFileName;
  std::map<std::string, std::string> lineage_by_id;
  std::string lineage_why;
  const bool have_entry = ReadLineageTsv(lineage_path, &lineage_by_id, &lineage_why);
  // RED-FIRST, BY NAME, and by DESIGN a FAIL rather than a MISSING
  // PREREQUISITE: unlike a real-artifact leg that is legitimately and
  // permanently optional, the epoch store's absence is the unimplemented
  // feature C2 exists to prove exists (Curie's own "red-unimplemented"
  // discipline) -- the founder's own job (sub-plan sec 4.3 "Founding
  // entry"), owed once this ticket's build round lands, not an
  // indefinitely-skippable precondition of this test.
  Verdict(have_entry, "C2 lineage equality: a live entry exists under fingerprint " + fingerprint_hex,
          have_entry ? lineage_path : lineage_why + " (epoch-store/ does not exist at 310c47d; this is the red-first state)");

  // ---- C2 itself: per document, independent seam digest == the store's
  // own lineage.tsv row for the SAME document id. ----
  int c2_checked = 0, c2_mismatches = 0;
  for (const DocTokens& doc : docs) {
    if (!have_entry) {
      Verdict(false, "C2 lineage equality: '" + doc.id + "'", "no live entry to compare against (red-first)");
      ++c2_mismatches;
      continue;
    }
    uint8_t digest[32];
    std::string cwhy;
    if (!ComputeSeamDigest(a.model, doc, digest, &cwhy)) {
      Verdict(false, "C2 lineage equality: '" + doc.id + "'", "independent recomputation failed: " + cwhy);
      ++c2_mismatches;
      continue;
    }
    const std::string computed_hex = Hex(digest);
    auto it = lineage_by_id.find(doc.id);
    if (it == lineage_by_id.end()) {
      Verdict(false, "C2 lineage equality: '" + doc.id + "'", "store's lineage.tsv carries no row for this id");
      ++c2_mismatches;
      continue;
    }
    ++c2_checked;
    const bool match = it->second == computed_hex;
    if (!match) ++c2_mismatches;
    Verdict(match, "C2 lineage equality: '" + doc.id + "'",
            "independent=" + computed_hex + " store=" + it->second);
  }
  std::printf("C2 summary: %d of %zu documents checked, %d mismatch(es)\n", c2_checked, docs.size(), c2_mismatches);

  // ---- Cell 4, folded in: the vector member against the raw path (real
  // artifact only -- present iff --corpus-jsonl was given). Every row of
  // vectors.f32 equals semb_encode(text) bit for bit. ----
  if (!a.corpus_jsonl.empty()) {
    std::string jwhy;
    const std::vector<std::pair<std::string, std::string>> texts = ReadJsonlTexts(a.corpus_jsonl, &jwhy);
    if (texts.empty()) {
      // S7 (TE-174): --corpus-jsonl was explicitly given, so an empty,
      // missing, or unparseable file is a named failure of the real leg,
      // never MISSING PREREQUISITE -- MISSING PREREQUISITE is reserved for
      // the artifact (the live entry, the model) being absent from the
      // host, not for a supplied input the caller failed to provide
      // correctly. tests/epoch_store_emit.cpp refuses the identical two
      // inputs (cannot open; a per-document refusal on an empty corpus);
      // this cell now matches that sibling instead of reporting a state a
      // run can silently exit 0 under.
      Verdict(false, "(cell 4) vectors.f32 rows equal semb_encode(text) bit for bit",
              "--corpus-jsonl was given but " + (jwhy.empty() ? std::string("carries no readable document (empty corpus)") : jwhy) +
              " -- an empty or unreadable corpus is a FAIL, not MISSING PREREQUISITE (S7, TE-174)");
    } else if (!have_entry) {
      // RED-FIRST, BY DESIGN A FAIL: same reasoning as C2's own live-entry
      // check above -- the store's absence is the unimplemented feature,
      // not an optional precondition.
      Verdict(false, "(cell 4) vectors.f32 rows equal semb_encode(text) bit for bit",
              "no live entry to read vectors.f32 from (red-first)");
    } else {
      const std::string vectors_path = a.store_root + "/live/" + fingerprint_hex + "/" + semb_epoch_contract::kVectorsFileName;
      std::ifstream vf(vectors_path, std::ios::binary);
      if (!vf) {
        Verdict(false, "(cell 4) vectors.f32 rows equal semb_encode(text) bit for bit",
                "cannot open " + vectors_path + " (lineage.tsv exists but vectors.f32 does not -- a malformed entry)");
      } else {
        std::vector<uint8_t> blob((std::istreambuf_iterator<char>(vf)), std::istreambuf_iterator<char>());
        semb_encoder enc = Open(a);
        if (enc) {
          // S3, TE-170: the text corpus (--corpus-jsonl) and the token
          // corpus (--tokens) are bound by DOCUMENT ID, never by list
          // position -- vectors.f32's own rows are written in --tokens
          // order (mint.cpp's RunAssemble), while the prior version of
          // this loop indexed by the jsonl's own position. The two
          // fixtures agree in order today, but nothing asserted they
          // must, and a short --corpus-jsonl silently reduced the row
          // count graded to whatever it happened to contain. Every id
          // named in --tokens (docs) is now required to have a jsonl
          // entry, and the row read from vectors.f32 is located by that
          // document's own index in `docs` -- the store's own corpus
          // order -- never by its index in `texts`.
          std::map<std::string, std::string> text_by_id;
          for (const auto& [id, text] : texts) text_by_id[id] = text;

          const size_t row_bytes = static_cast<size_t>(a.dims) * sizeof(float);
          int checked = 0, mismatches = 0;
          for (size_t index = 0; index < docs.size(); ++index) {
            const std::string& id = docs[index].id;
            auto it = text_by_id.find(id);
            if (it == text_by_id.end()) {
              Verdict(false, "(cell 4) row for '" + id + "'",
                      "FAIL -- id present in --tokens but absent from --corpus-jsonl; the text and token corpora "
                      "are bound by id, not by list position (S3, TE-170)");
              ++mismatches;
              continue;
            }
            if ((index + 1) * row_bytes > blob.size()) {
              Verdict(false, "(cell 4) row for '" + id + "'", "vectors.f32 is shorter than --tokens order implies");
              ++mismatches;
              continue;
            }
            std::vector<float> raw(a.dims);
            size_t required = 0;
            semb_fingerprint fp{};
            fp.struct_size = sizeof(fp);
            const semb_status es = semb_encode(enc, it->second.data(), it->second.size(), raw.data(),
                                                raw.size() * sizeof(float), &required, &fp);
            if (es != SEMB_OK) {
              Verdict(false, "(cell 4) row for '" + id + "'", std::string("semb_encode refused: ") + semb_status_name(es));
              ++mismatches;
              continue;
            }
            const bool match = std::memcmp(raw.data(), blob.data() + index * row_bytes, row_bytes) == 0;
            if (!match) ++mismatches;
            ++checked;
            Verdict(match, "(cell 4) row for '" + id + "' == semb_encode(text) bit for bit", match ? "match" : "MISMATCH");
          }
          semb_encoder_close(enc);
          std::printf("cell 4 summary: %d checked, %d mismatch(es)\n", checked, mismatches);
          // S3: the row count graded is asserted equal to the store's own
          // count (docs.size(), --tokens order) -- a short jsonl must not
          // silently reduce coverage.
          Verdict(static_cast<size_t>(checked) == docs.size(),
                  "(cell 4) every document named in --tokens was graded",
                  "checked=" + std::to_string(checked) + " docs.size()=" + std::to_string(docs.size()));
        }
      }
    }
  } else {
    std::printf("(cell 4) skipped: no --corpus-jsonl given (real-artifact-only leg)\n");
  }

  std::printf("\nc2_lineage_equality_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
