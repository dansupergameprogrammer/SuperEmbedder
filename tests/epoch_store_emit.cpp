// tests/epoch_store_emit.cpp -- TE-162 (U1 slice 3 red suite): the shared
// SUPPORT tool `tests/epoch_store_check.py` (cell 1) and
// `tests/epoch_store_constructions_check.py` (cell 2) both shell out to, to
// materialise a well-formed, independently-derived epoch-store entry
// (`vectors.f32`, `row-digest.tsv`, `lineage.tsv`) for a given corpus and
// artifact -- and to print the artifact's own current fingerprint. This is
// INFRASTRUCTURE, not itself a graded cell (EXCLUDE_FROM_ALL; no
// PASS/FAIL verdict of its own) -- the same role `tests/support/` already
// holds for `u1_workspace_seam_test.cpp`'s helpers, applied here to a
// standalone executable because Python cannot call the C ABI directly in
// this project (every existing Python check drives a built C++ executable
// by subprocess, e.g. tests/u1_batch_contract_check.py's own header
// comment).
//
// WHAT IT COMPUTES, independent of any store on disk (it never reads
// epoch-store/ -- the checkers that USE this tool's output are the ones
// that compare it against a store). Per document, in corpus order:
//   1. token ids = the document's own committed content ids (from
//      --tokens) with --terminator-id appended once (sec 4.4b, sec 3.1's
//      PS-N entry-point crossing: "no document frame under PS-N ...
//      content-tokens-then-terminator, identical to raw's").
//   2. semb_encode_document_for_witness(--model, ids, n, chunk_budget=0,
//      ...) -- the real forward, per position, EXACTLY the primitive
//      the dispatch names as one of "the lineage oracle's only two
//      primitives."
//   3. semb_seam_serialize_document(...) over ALL positions -> this
//      document's own seam bytes -> SHA-256 -> lineage.tsv's own
//      seam_sha256 column. The corpus-level "all" line is SHA-256 over
//      u64(document_count) then every document's own seam bytes, in
//      corpus order (sec 4.4b's own corpus-level formula, the same one
//      tests/w_b_corpus_witness_test.cpp already computes independently
//      for W-B).
//   4. semb_ps_n_dequantize(codes at the LAST position, m[last], e[last],
//      hidden, out) -- PS-N's own single-position dequantize
//      (tests/semb_ps_n_pool_abi_contract.h; ALREADY BUILT,
//      src/superembedder/ps_n_pool.cpp per this slice's own ground truth,
//      sec 2) -- an INDEPENDENT recomputation of the pooled float32
//      vector that takes no input from the store and no input from
//      whatever encode path a founder used to mint it. This is
//      row-digest.tsv's own psn_vector_sha256 column's source, and
//      vectors.f32's own row bytes, for every document this tool is
//      given.
//   5. WHEN --corpus-jsonl is given (the real-artifact leg only, per the
//      dispatch's own cell 4: "for the real artifact"): additionally
//      calls semb_encode() on the document's own committed TEXT (not its
//      token ids) -- the raw public path, "what a user receives" -- and
//      ALWAYS WRITES THE RAW-PATH BYTES to vectors.f32 rather than step
//      4's dequantized ones ("the store's bytes are what a user receives,
//      not a second derivation," the dispatch's own cell 4 language,
//      verbatim). A PASS/INFO-MISMATCH line compares the two for
//      diagnostic value only and never changes what is written or this
//      tool's exit code: FINDING, executed this round -- on a
//      five-document real-artifact probe, step 4's dequantize(last
//      position) disagreed with semb_encode(text) on every document
//      (5/5), after the terminator-id fix below ruled out a stale
//      manifest value as the cause. Root cause unresolved this round
//      (product internals beyond a test author's writable scope);
//      ROUTED to the builder in this round's own handoff.
//   6. The artifact's own current fingerprint: opens a THIRD encoder
//      handle (or reuses step 5's, when --corpus-jsonl was given) and
//      calls semb_encode() once on a fixed throwaway string purely to
//      read semb_fingerprint via its out-parameter -- the public verb's
//      only way to observe it this slice (semb_fingerprint_of does not
//      exist until Slice 5). Printed as `fingerprint=<64 lowercase hex>`.
//
// USAGE
//   epoch_store_emit --model <.sslm> --tokenizer <.sslm> --dims <n>
//     --tokens <corpus.tokens.tsv> --terminator-id <n> --out-dir <dir>
//     [--corpus-jsonl <corpus.jsonl>] [--doc-ids <id1,id2,...>]
// --doc-ids restricts the run to the named documents, in the order given
// (used by the six-constructions cell to mint small, fast scratch entries
// rather than the full 239/8-document corpus every time).
//
// Exit codes: 0 on success (files written, fingerprint printed); 1 on any
// setup or per-document failure, named on stderr.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_seam_abi_contract.h"
#include "semb_ps_n_pool_abi_contract.h"
#include "semb_epoch_store_contract.h"

#include "superslm/artifact.h"
#include "superslm/sha256.h"
#include "superslm/tokenizer.h"

namespace {

struct Args {
  std::string model, tokenizer, tokens, out_dir, corpus_jsonl, doc_ids_csv;
  unsigned dims = 0;
  long terminator_id = -1;
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
    else if (k == "--out-dir") next(&a.out_dir);
    else if (k == "--corpus-jsonl") next(&a.corpus_jsonl);
    else if (k == "--doc-ids") next(&a.doc_ids_csv);
  }
  return a;
}

std::vector<std::string> SplitCsv(const std::string& s) {
  std::vector<std::string> out;
  if (s.empty()) return out;
  std::stringstream ss(s);
  std::string item;
  while (std::getline(ss, item, ',')) out.push_back(item);
  return out;
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

// A minimal JSONL {"id":..,"text":..} reader, identical shape to
// tests/w_b_corpus_witness_test.cpp's own ParseJsonlLine (kept as an
// independent copy rather than a shared header, matching this suite's own
// "manually-kept-in-sync duplicate" convention -- tests/
// semb_seam_abi_contract.h's own header comment names the same practice).
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

void PutU64LE(std::vector<uint8_t>* out, uint64_t v) {
  for (int i = 0; i < 8; ++i) out->push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}

std::string Hex(const uint8_t d[32]) { return superslm::ToHex(d); }

bool WriteFile(const std::string& path, const std::vector<uint8_t>& bytes, std::string* why) {
  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  if (!f) { *why = "cannot open for write: " + path; return false; }
  if (!bytes.empty()) f.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
  return static_cast<bool>(f);
}

bool WriteTextFile(const std::string& path, const std::string& text, std::string* why) {
  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  if (!f) { *why = "cannot open for write: " + path; return false; }
  f.write(text.data(), static_cast<std::streamsize>(text.size()));
  return static_cast<bool>(f);
}

// FINDING, executed rather than assumed (this round): --terminator-id,
// taken at face value from a fixture manifest (corpus-239.manifest.json's
// own appended_token_id, 151643), produced a lineage/vector sequence that
// disagreed with the raw public path (semb_encode) on EVERY document of a
// five-document probe -- confirmed by execution
// (raw_path_mismatches=5/5). tests/w_b_corpus_witness_test.cpp and
// tests/c39_seam_digest_test.cpp both avoid exactly this fragility by
// resolving the end token from the LIVE tokenizer artifact
// (tokenizer.Encode("<|endoftext|>")) rather than trusting a value
// transcribed elsewhere -- this function does the identical resolution.
// --terminator-id is kept as a cross-check (reported, never load-bearing)
// rather than removed, so a future disagreement is visible rather than
// silent.
bool ResolveEndTokenId(const std::string& tokenizer_path, int32_t* out_id, std::string* why) {
  std::ifstream f(tokenizer_path, std::ios::binary | std::ios::ate);
  if (!f) { *why = "cannot open tokenizer artifact " + tokenizer_path; return false; }
  const std::streamoff end = f.tellg();
  if (end <= 0) { *why = "tokenizer artifact is empty: " + tokenizer_path; return false; }
  std::vector<uint8_t> bytes(static_cast<size_t>(end));
  f.seekg(0, std::ios::beg);
  f.read(reinterpret_cast<char*>(bytes.data()), end);
  superslm::SslmArtifact artifact;
  superslm::SslmError artifact_error;
  if (superslm::SslmArtifact::OpenFromMemory(bytes.data(), bytes.size(), artifact, &artifact_error) !=
      superslm::SslmStatus::Ok) {
    *why = "tokenizer artifact open refused: " + tokenizer_path;
    return false;
  }
  superslm::TokenizerView tokenizer;
  std::string tok_err;
  if (!superslm::TokenizerView::Open(artifact, tokenizer, &tok_err)) {
    *why = "TokenizerView::Open refused: " + tok_err;
    return false;
  }
  const std::vector<int32_t> ids = tokenizer.Encode("<|endoftext|>");
  if (ids.size() != 1) { *why = "<|endoftext|> does not resolve to exactly one id"; return false; }
  *out_id = ids[0];
  return true;
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0 || a.tokens.empty() || a.out_dir.empty()) {
    std::fprintf(stderr,
                 "usage: epoch_store_emit --model <.sslm> --tokenizer <.sslm> --dims <n> "
                 "--tokens <tsv> [--terminator-id <n>] --out-dir <dir> [--corpus-jsonl <jsonl>] "
                 "[--doc-ids <id1,id2,...>]\n");
    return 1;
  }

  // Resolve the end token from the LIVE tokenizer rather than trusting
  // --terminator-id at face value (see ResolveEndTokenId's own header
  // comment: a five-document real-artifact probe this round found the
  // CLI-supplied manifest value disagreed with the raw path on every
  // document; the live resolution is what tests/w_b_corpus_witness_test.cpp
  // and tests/c39_seam_digest_test.cpp both already use).
  int32_t resolved_terminator_id = 0;
  std::string resolve_why;
  long terminator_id = a.terminator_id;
  if (ResolveEndTokenId(a.tokenizer, &resolved_terminator_id, &resolve_why)) {
    if (a.terminator_id >= 0 && resolved_terminator_id != a.terminator_id) {
      std::printf("terminator_id_mismatch=--terminator-id %ld disagrees with the live tokenizer's own "
                  "<|endoftext|>=%d; using the live value\n", a.terminator_id, resolved_terminator_id);
    }
    terminator_id = resolved_terminator_id;
  } else if (a.terminator_id < 0) {
    std::fprintf(stderr, "epoch_store_emit: could not resolve the end token live and no --terminator-id given: %s\n",
                 resolve_why.c_str());
    return 1;
  } else {
    std::printf("terminator_id_resolution_failed=%s; falling back to --terminator-id %ld\n", resolve_why.c_str(),
                a.terminator_id);
  }

  std::string why;
  std::vector<DocTokens> docs = ReadTokensTsv(a.tokens, terminator_id, &why);
  if (docs.empty() && !why.empty()) {
    std::fprintf(stderr, "epoch_store_emit: %s\n", why.c_str());
    return 1;
  }
  if (!a.doc_ids_csv.empty()) {
    const std::vector<std::string> wanted = SplitCsv(a.doc_ids_csv);
    std::vector<DocTokens> filtered;
    for (const auto& id : wanted) {
      bool found = false;
      for (const auto& d : docs) {
        if (d.id == id) { filtered.push_back(d); found = true; break; }
      }
      if (!found) { std::fprintf(stderr, "epoch_store_emit: --doc-ids named '%s', not in --tokens\n", id.c_str()); return 1; }
    }
    docs = std::move(filtered);
  }
  if (docs.empty()) { std::fprintf(stderr, "epoch_store_emit: no documents selected\n"); return 1; }

  std::vector<std::pair<std::string, std::string>> texts;
  if (!a.corpus_jsonl.empty()) {
    texts = ReadJsonlTexts(a.corpus_jsonl, &why);
    if (texts.empty() && !why.empty()) {
      std::fprintf(stderr, "epoch_store_emit: %s\n", why.c_str());
      return 1;
    }
  }
  auto find_text = [&](const std::string& id) -> const std::string* {
    for (const auto& p : texts) if (p.first == id) return &p.second;
    return nullptr;
  };

  // ---- Open ONE encoder handle used both for the fingerprint read and,
  // when a corpus is given, for the raw-path (semb_encode) leg -- fewer
  // handles, identical artifacts either way. ----
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = a.model.data();
  cfg.model_path_len = a.model.size();
  cfg.tokenizer_path = a.tokenizer.data();
  cfg.tokenizer_path_len = a.tokenizer.size();
  cfg.max_concurrency = 1;
  semb_encoder enc = nullptr;
  const semb_status open_status = semb_encoder_open(&cfg, &enc);
  if (open_status != SEMB_OK || !enc) {
    std::fprintf(stderr, "epoch_store_emit: semb_encoder_open refused: %s\n", semb_status_name(open_status));
    return 1;
  }

  // Fingerprint: one throwaway semb_encode call.
  {
    std::vector<float> throwaway(static_cast<size_t>(a.dims), 0.0f);
    size_t required = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    const char kThrowawayText[] = "epoch_store_emit fingerprint probe";
    const semb_status es = semb_encode(enc, kThrowawayText, sizeof(kThrowawayText) - 1, throwaway.data(),
                                        throwaway.size() * sizeof(float), &required, &fp);
    if (es != SEMB_OK) {
      std::fprintf(stderr, "epoch_store_emit: fingerprint probe semb_encode refused: %s\n", semb_status_name(es));
      semb_encoder_close(enc);
      return 1;
    }
    std::printf("fingerprint=%s\n", Hex(fp.digest).c_str());
  }
  std::printf("dims=%u\n", a.dims);
  std::printf("document_count=%zu\n", docs.size());

  std::vector<uint8_t> vectors_blob;
  std::vector<std::pair<std::string, std::string>> row_digest_rows;   // id -> psn_vector_sha256
  std::vector<std::pair<std::string, std::string>> lineage_rows;      // id -> seam_sha256
  std::vector<uint8_t> lineage_all_stream;
  PutU64LE(&lineage_all_stream, static_cast<uint64_t>(docs.size()));

  int raw_path_mismatches = 0;

  for (const DocTokens& d : docs) {
    std::vector<int8_t> codes(d.ids.size() * kSembWitnessMaxHidden);
    std::vector<int64_t> m(d.ids.size()), e(d.ids.size());
    size_t hidden = 0;
    const SembEncodeStatus est = semb_encode_document_for_witness(
        a.model.c_str(), d.ids.data(), d.ids.size(), /*chunk_budget=*/0, codes.data(), m.data(), e.data(), &hidden);
    if (est != kSembEncodeOk) {
      std::fprintf(stderr, "epoch_store_emit: semb_encode_document_for_witness refused for '%s' (status %d)\n",
                   d.id.c_str(), static_cast<int>(est));
      semb_encoder_close(enc);
      return 1;
    }
    if (hidden != a.dims) {
      std::fprintf(stderr, "epoch_store_emit: '%s' hidden_size=%zu != --dims %u\n", d.id.c_str(), hidden, a.dims);
      semb_encoder_close(enc);
      return 1;
    }

    // Lineage: serialise EVERY position (sec 4.4b's own per-document
    // formula), SHA-256 the stream.
    std::vector<uint8_t> doc_buf(16 + d.ids.size() * (hidden + 16));
    size_t doc_len = 0;
    const SembSerializeStatus sst = semb_seam_serialize_document(codes.data(), m.data(), e.data(), d.ids.size(),
                                                                    hidden, doc_buf.data(), doc_buf.size(), &doc_len);
    if (sst != kSembSerializeOk) {
      std::fprintf(stderr, "epoch_store_emit: semb_seam_serialize_document refused for '%s'\n", d.id.c_str());
      semb_encoder_close(enc);
      return 1;
    }
    uint8_t seam_digest[32];
    superslm::Sha256Hash(doc_buf.data(), doc_len, seam_digest);
    lineage_rows.push_back({d.id, Hex(seam_digest)});
    lineage_all_stream.insert(lineage_all_stream.end(), doc_buf.begin(), doc_buf.begin() + doc_len);

    // PS-N vector: dequantize the LAST position (PS-N's own selection
    // rule, sec 3.2 item 4) -- independent of the store, independent of
    // whatever entry point minted it.
    std::vector<float> dequantized(hidden);
    const SembWaPoolStatus dq = semb_ps_n_dequantize(
        codes.data() + (d.ids.size() - 1) * hidden, m[d.ids.size() - 1], e[d.ids.size() - 1], hidden, dequantized.data());
    if (dq != kSembOk) {
      std::fprintf(stderr, "epoch_store_emit: semb_ps_n_dequantize refused for '%s' (status %d)\n", d.id.c_str(),
                   static_cast<int>(dq));
      semb_encoder_close(enc);
      return 1;
    }

    std::vector<float> row_vector = dequantized;

    // Real-artifact leg: cross-check and prefer the raw public path.
    if (const std::string* text = find_text(d.id)) {
      std::vector<float> raw(hidden);
      size_t required = 0;
      semb_fingerprint fp{};
      fp.struct_size = sizeof(fp);
      const semb_status es = semb_encode(enc, text->data(), text->size(), raw.data(), raw.size() * sizeof(float),
                                          &required, &fp);
      if (es != SEMB_OK) {
        std::fprintf(stderr, "epoch_store_emit: raw-path semb_encode refused for '%s': %s\n", d.id.c_str(),
                     semb_status_name(es));
        semb_encoder_close(enc);
        return 1;
      }
      // FINDING, executed rather than assumed, this round: on a
      // five-document real-artifact probe, semb_ps_n_dequantize(last
      // position) disagreed with semb_encode(text) on every document
      // (5/5) even after the terminator-id/live-tokenizer fix above ruled
      // out a stale manifest value. The root cause is not resolved this
      // round (it would require tracing semb_interim_encode_ps_n's exact
      // composition against semb_encode_document_for_witness's, product
      // internals beyond a grep-level check) -- ROUTED to the builder.
      // INFORMATIONAL ONLY: never fails this tool's exit code, and never
      // changes what is written -- the raw path is preferred for
      // row_vector regardless ("the store's bytes are what a user
      // receives, not a second derivation"), so this finding does not
      // threaten vectors.f32's own correctness, only this tool's own
      // extra cross-check.
      const bool match = std::memcmp(raw.data(), dequantized.data(), hidden * sizeof(float)) == 0;
      std::printf("[%s] (raw-path cross-check, informational) '%s' semb_encode(text) == "
                  "semb_ps_n_dequantize(last position)\n",
                  match ? "PASS" : "INFO-MISMATCH", d.id.c_str());
      if (!match) ++raw_path_mismatches;
      row_vector = raw;  // "the store's bytes are what a user receives" -- prefer the raw path always when available.
    }

    const uint8_t* row_bytes = reinterpret_cast<const uint8_t*>(row_vector.data());
    const size_t row_len = row_vector.size() * sizeof(float);
    vectors_blob.insert(vectors_blob.end(), row_bytes, row_bytes + row_len);
    uint8_t row_digest[32];
    superslm::Sha256Hash(row_bytes, row_len, row_digest);
    row_digest_rows.push_back({d.id, Hex(row_digest)});
  }
  semb_encoder_close(enc);

  uint8_t vectors_all_digest[32];
  superslm::Sha256Hash(vectors_blob.data(), vectors_blob.size(), vectors_all_digest);
  uint8_t lineage_all_digest[32];
  superslm::Sha256Hash(lineage_all_stream.data(), lineage_all_stream.size(), lineage_all_digest);

  std::string row_digest_text;
  for (const auto& r : row_digest_rows) row_digest_text += r.first + "\t" + r.second + "\n";
  row_digest_text += "all\t" + Hex(vectors_all_digest) + "\n";

  std::string lineage_text;
  for (const auto& r : lineage_rows) lineage_text += r.first + "\t" + r.second + "\n";
  lineage_text += "all\t" + Hex(lineage_all_digest) + "\n";

  std::error_code mkdir_ec;
  std::filesystem::create_directories(a.out_dir, mkdir_ec);
  if (mkdir_ec) {
    std::fprintf(stderr, "epoch_store_emit: cannot create --out-dir '%s': %s\n", a.out_dir.c_str(),
                 mkdir_ec.message().c_str());
    return 1;
  }

  std::string wwhy;
  if (!WriteFile(a.out_dir + "/" + semb_epoch_contract::kVectorsFileName, vectors_blob, &wwhy) ||
      !WriteTextFile(a.out_dir + "/" + semb_epoch_contract::kRowDigestFileName, row_digest_text, &wwhy) ||
      !WriteTextFile(a.out_dir + "/" + semb_epoch_contract::kLineageFileName, lineage_text, &wwhy)) {
    std::fprintf(stderr, "epoch_store_emit: %s\n", wwhy.c_str());
    return 1;
  }

  std::printf("vectors_all_sha256=%s\n", Hex(vectors_all_digest).c_str());
  std::printf("lineage_all_sha256=%s\n", Hex(lineage_all_digest).c_str());
  std::printf("raw_path_mismatches=%d (informational; see this file's own header comment -- routed, not "
              "load-bearing)\n", raw_path_mismatches);
  return 0;
}
