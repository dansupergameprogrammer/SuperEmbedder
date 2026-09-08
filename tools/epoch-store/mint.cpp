// tools/epoch-store/mint.cpp -- TE-164 (U1 slice 3 build): the epoch
// store's own minting tool (`Claude/Plans/SuperEmbedder_Plan.md` sec 8,
// C32; `Claude/Bach/briefs/te164-slice3-build.md` item 1).
//
// THIS IS NOT tests/epoch_store_emit.cpp. That file is the test author's
// own independent ORACLE, used by the graded cells (epoch_store_check.py,
// epoch_store_constructions_check.py) to synthesise scratch entries and to
// grade what this tool mints; agreement between the two tools is only
// meaningful because they are two different producers reading the plan's
// same contract independently. Concretely, this tool differs in shape from
// that one:
//   - it is split into three MODES (fingerprint / encode / assemble, below)
//     so a corpus too large to finish inside one nine-minute foreground
//     command can be minted in batches without ever backgrounding a run or
//     losing the corpus-order "all" digest to a per-batch recomputation;
//   - its real-artifact leg never calls semb_ps_n_dequantize on the
//     witness call's own per-position codes at all (the exact construction
//     D-SLM6382 names as the disagreement's own cause, this round's own
//     Decision Log entry, resolved by execution) -- the real leg's vector
//     bytes come ONLY from semb_encode's raw path, and the synthetic leg's
//     (which has no committed text to call semb_encode on) come from the
//     PRODUCT'S OWN composed selection: semb_interim_encode_seam -> select
//     the last position through the engine's real final-norm site
//     (semb_interim_ps_n_select) -> dequantize, never the seam's raw,
//     pre-final-norm codes.
//
// THE THREE MODES.
//   fingerprint --model <.sslm> --tokenizer <.sslm> --dims <n>
//     Opens the PUBLIC handle (semb_encoder_open), issues one throwaway
//     semb_encode call solely to read semb_fingerprint via its
//     out-parameter (semb_fingerprint_of does not exist until Slice 5 --
//     this is the only public way to observe it this slice), and prints
//     `fingerprint=<64 lowercase hex>`. No document is touched.
//
//   encode --model <.sslm> --tokenizer <.sslm> --dims <n> --tokens <tsv>
//       --terminator-id <n> --raw-cache-dir <dir>
//       [--corpus-jsonl <jsonl>] [--doc-ids <id1,id2,...>]
//     For every selected document (corpus order, or --doc-ids order when
//     given): writes <raw-cache-dir>/<doc_id>.vec (the row's own
//     dims*4-byte float32 vector, little-endian) and
//     <raw-cache-dir>/<doc_id>.seam (semb_seam_serialize_document's own raw
//     bytes for every position of the document, position 0 and the
//     appended end token included) -- BOTH members' RAW BYTES, not their
//     digests, because assemble mode (below) needs the actual bytes to
//     compute the corpus-wide "all" digests correctly regardless of how
//     many encode invocations produced the cache. --corpus-jsonl present
//     and carrying the document's own text: the .vec bytes are
//     semb_encode's own raw-path output ("what a user receives," never a
//     second derivation) via a public handle opened ONCE for the whole
//     invocation. --corpus-jsonl absent (the synthetic leg, which has no
//     committed text): the .vec bytes are the product's own composed
//     selection -- semb_interim_encode_seam (this document's full seam,
//     one interim handle opened ONCE for the whole invocation) ->
//     semb_interim_ps_n_select(position = n-1) (the engine's own final
//     norm, applied through the SAME real data path the composed public
//     entry point uses) -> semb_ps_n_dequantize. The .seam bytes always
//     come from semb_encode_document_for_witness + semb_seam_serialize_document
//     (this round's own dispatch, item 1: "the lineage oracle's only two
//     primitives"), for both legs, unconditionally -- the SAME construction
//     tests/c2_lineage_equality_test.cpp and tests/epoch_store_emit.cpp
//     both already use for lineage.tsv, so lineage agreement with the
//     oracle is expected on both legs even where a leg's own vector
//     agreement is not (see this tool's own header comment above and this
//     round's own build record for the synthetic leg's own vector
//     disagreement, which is D-SLM6382's own construction defect
//     surviving in the ORACLE's synthetic output, not in this tool's).
//     Multiple encode invocations over disjoint --doc-ids subsets (never
//     re-run over an already-cached document, so nothing is silently
//     recomputed and possibly disagreeing with itself) populate the same
//     --raw-cache-dir; assemble mode below is what turns that cache into
//     the actual three committed members, in true corpus order, regardless
//     of how many encode invocations or what order they ran in.
//
//   assemble --tokens <tsv> --raw-cache-dir <dir> --fingerprint-hex <hex>
//       --out-dir <epoch-store repository root>
//     Reads --tokens for the corpus's own true order (file order, per the
//     contract), and for every document in that order reads
//     <raw-cache-dir>/<id>.vec and <raw-cache-dir>/<id>.seam (a missing
//     file for any document is a hard failure, named, before anything is
//     written -- an incomplete cache never produces a partial, silently
//     wrong entry). Writes epoch-store/live/<fingerprint-hex>/{vectors.f32,
//     row-digest.tsv, lineage.tsv} under --out-dir exactly per
//     tests/semb_epoch_store_contract.h: vectors.f32 is the .vec files
//     concatenated in corpus order; row-digest.tsv's psn_vector_sha256 is
//     SHA-256 over each document's own dims*4-byte slice of vectors.f32
//     (by definition -- always a hash of what is actually written, not of
//     however it was computed), plus a trailing "all" line SHA-256 over
//     the whole vectors.f32 blob; lineage.tsv's seam_sha256 is SHA-256 over
//     each document's own .seam bytes, plus a trailing "all" line SHA-256
//     over u64(document_count) little-endian followed by every document's
//     own .seam bytes, in corpus order. No model is opened in this mode --
//     pure file I/O and hashing, so a 239-document assemble finishes in
//     well under the nine-minute foreground rule regardless of how many
//     encode batches produced the cache.
//
// Exit codes: 0 success; 1 any engine refusal or missing-cache failure
// (named on stderr); 2 usage.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "semb_epoch_store_contract.h"  // tests/-owned contract; INCLUDED, never edited (path/member-name constants only)

#include "superembedder/semb.h"
#include "superembedder/seam_abi.h"
#include "superembedder/encoder_interim_abi.h"

#include "superslm/sha256.h"

namespace {

std::string Hex(const uint8_t d[32]) { return superslm::ToHex(d); }

bool ReadWholeFile(const std::string& path, std::vector<uint8_t>* out) {
  std::ifstream f(path, std::ios::binary);
  if (!f) return false;
  f.seekg(0, std::ios::end);
  const std::streamoff n = f.tellg();
  if (n < 0) return false;
  f.seekg(0, std::ios::beg);
  out->resize(static_cast<size_t>(n));
  if (n > 0) f.read(reinterpret_cast<char*>(out->data()), n);
  return static_cast<bool>(f) || n == 0;
}

bool WriteWholeFile(const std::string& path, const uint8_t* data, size_t len, std::string* why) {
  std::ofstream f(path, std::ios::binary | std::ios::trunc);
  if (!f) { *why = "cannot open for write: " + path; return false; }
  if (len) f.write(reinterpret_cast<const char*>(data), static_cast<std::streamsize>(len));
  return static_cast<bool>(f);
}

bool WriteText(const std::string& path, const std::string& text, std::string* why) {
  return WriteWholeFile(path, reinterpret_cast<const uint8_t*>(text.data()), text.size(), why);
}

void PutU64LE(std::vector<uint8_t>* out, uint64_t v) {
  for (int i = 0; i < 8; ++i) out->push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
}

struct DocTokens { std::string id; std::vector<int32_t> content_ids; };

// tests/fixtures/c12b/*.tokens.tsv's own format: "<id>\t<comma-separated
// CONTENT token ids>\n", corpus order is file order, no terminator appended
// here -- callers append it exactly once, at the point that matches
// whichever primitive they are about to call (identical convention to
// tests/epoch_store_emit.cpp's own ReadTokensTsv and
// tests/epoch_store_contract.py's own read_tokens_tsv).
std::vector<DocTokens> ReadTokensTsv(const std::string& path, std::string* why) {
  std::vector<DocTokens> out;
  std::ifstream f(path);
  if (!f) { *why = "cannot open " + path; return out; }
  std::string line;
  while (std::getline(f, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty()) continue;
    const size_t tab = line.find('\t');
    if (tab == std::string::npos) { *why = "line has no tab: " + line; return {}; }
    DocTokens d;
    d.id = line.substr(0, tab);
    std::string ids_field = line.substr(tab + 1);
    std::stringstream ss(ids_field);
    std::string tok;
    while (std::getline(ss, tok, ',')) {
      if (!tok.empty()) d.content_ids.push_back(static_cast<int32_t>(std::atol(tok.c_str())));
    }
    out.push_back(std::move(d));
  }
  return out;
}

std::vector<std::string> SplitCsv(const std::string& s) {
  std::vector<std::string> out;
  if (s.empty()) return out;
  std::stringstream ss(s);
  std::string item;
  while (std::getline(ss, item, ',')) out.push_back(item);
  return out;
}

// A minimal JSONL {"id"/"label":.., "text":..} reader -- an independent
// copy rather than a shared header, matching this tree's own established
// "manually-kept-in-sync duplicate" convention for a small, stable parser
// (tests/semb_seam_abi_contract.h's own header comment names the identical
// practice).
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
      const char c = line[p + 1];
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

bool ReadJsonlTexts(const std::string& path, std::vector<std::pair<std::string, std::string>>* out,
                     std::string* why) {
  std::ifstream f(path);
  if (!f) { *why = "cannot open " + path; return false; }
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    std::string id, text;
    if (!ExtractJsonString(line, "label", &id) && !ExtractJsonString(line, "id", &id)) {
      *why = "no 'label' or 'id' key: " + line;
      return false;
    }
    if (!ExtractJsonString(line, "text", &text)) { *why = "no 'text' key: " + line; return false; }
    out->push_back({id, text});
  }
  return true;
}

// The lineage oracle's own two primitives (this round's own dispatch, item
// 1), used unconditionally for BOTH legs: semb_encode_document_for_witness
// needs only a model path and the document's own token ids (terminator
// appended once by this function's own caller) -- no tokenizer is
// involved, since the ids are already resolved.
bool ComputeSeamBytes(const std::string& model_path, const std::vector<int32_t>& ids_with_terminator,
                       std::vector<uint8_t>* out_bytes, std::string* why) {
  const size_t n = ids_with_terminator.size();
  std::vector<int8_t> codes(n * kSembWitnessMaxHidden);
  std::vector<int64_t> m(n), e(n);
  size_t hidden = 0;
  const SembEncodeStatus st = semb_encode_document_for_witness(
      model_path.c_str(), ids_with_terminator.data(), n, /*chunk_budget=*/0, codes.data(), m.data(),
      e.data(), &hidden);
  if (st != kSembEncodeOk) {
    *why = "semb_encode_document_for_witness refused (status " + std::to_string(static_cast<int>(st)) + ")";
    return false;
  }
  std::vector<uint8_t> buf(16 + n * (hidden + 16));
  size_t len = 0;
  const SembSerializeStatus sst =
      semb_seam_serialize_document(codes.data(), m.data(), e.data(), n, hidden, buf.data(), buf.size(), &len);
  if (sst != kSembSerializeOk) { *why = "semb_seam_serialize_document refused"; return false; }
  buf.resize(len);
  *out_bytes = std::move(buf);
  return true;
}

int RunFingerprint(int argc, char** argv) {
  std::string model, tokenizer;
  unsigned dims = 0;
  for (int i = 2; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&model);
    else if (k == "--tokenizer") next(&tokenizer);
    else if (k == "--dims") { std::string v; next(&v); dims = static_cast<unsigned>(std::atoi(v.c_str())); }
  }
  if (model.empty() || tokenizer.empty() || dims == 0) {
    std::fprintf(stderr, "usage: %s fingerprint --model <.sslm> --tokenizer <.sslm> --dims <n>\n", argv[0]);
    return 2;
  }
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = model.data();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tokenizer.data();
  cfg.tokenizer_path_len = tokenizer.size();
  cfg.max_concurrency = 1;
  semb_encoder enc = nullptr;
  const semb_status open_st = semb_encoder_open(&cfg, &enc);
  if (open_st != SEMB_OK || !enc) {
    std::fprintf(stderr, "epoch_store_mint: semb_encoder_open refused: %s\n", semb_status_name(open_st));
    return 1;
  }
  std::vector<float> throwaway(dims, 0.0f);
  size_t required = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  const char kProbe[] = "epoch_store_mint fingerprint probe";
  const semb_status es = semb_encode(enc, kProbe, sizeof(kProbe) - 1, throwaway.data(),
                                      throwaway.size() * sizeof(float), &required, &fp);
  semb_encoder_close(enc);
  if (es != SEMB_OK) {
    std::fprintf(stderr, "epoch_store_mint: fingerprint probe semb_encode refused: %s\n", semb_status_name(es));
    return 1;
  }
  std::printf("fingerprint=%s\n", Hex(fp.digest).c_str());
  return 0;
}

int RunEncode(int argc, char** argv) {
  std::string model, tokenizer, tokens, raw_cache_dir, corpus_jsonl, doc_ids_csv;
  unsigned dims = 0;
  long terminator_id = -1;
  for (int i = 2; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&model);
    else if (k == "--tokenizer") next(&tokenizer);
    else if (k == "--dims") { std::string v; next(&v); dims = static_cast<unsigned>(std::atoi(v.c_str())); }
    else if (k == "--tokens") next(&tokens);
    else if (k == "--terminator-id") { std::string v; next(&v); terminator_id = std::atol(v.c_str()); }
    else if (k == "--raw-cache-dir") next(&raw_cache_dir);
    else if (k == "--corpus-jsonl") next(&corpus_jsonl);
    else if (k == "--doc-ids") next(&doc_ids_csv);
  }
  if (model.empty() || tokenizer.empty() || dims == 0 || tokens.empty() || terminator_id < 0 ||
      raw_cache_dir.empty()) {
    std::fprintf(stderr,
                 "usage: %s encode --model <.sslm> --tokenizer <.sslm> --dims <n> --tokens <tsv> "
                 "--terminator-id <n> --raw-cache-dir <dir> [--corpus-jsonl <jsonl>] "
                 "[--doc-ids <id1,id2,...>]\n",
                 argv[0]);
    return 2;
  }

  std::string why;
  std::vector<DocTokens> docs = ReadTokensTsv(tokens, &why);
  if (docs.empty() && !why.empty()) { std::fprintf(stderr, "epoch_store_mint: %s\n", why.c_str()); return 1; }
  if (!doc_ids_csv.empty()) {
    const std::vector<std::string> wanted = SplitCsv(doc_ids_csv);
    std::vector<DocTokens> filtered;
    for (const auto& id : wanted) {
      bool found = false;
      for (const auto& d : docs) if (d.id == id) { filtered.push_back(d); found = true; break; }
      if (!found) { std::fprintf(stderr, "epoch_store_mint: --doc-ids named '%s', not in --tokens\n", id.c_str()); return 1; }
    }
    docs = std::move(filtered);
  }
  if (docs.empty()) { std::fprintf(stderr, "epoch_store_mint: no documents selected\n"); return 1; }

  std::vector<std::pair<std::string, std::string>> texts;
  const bool have_text_corpus = !corpus_jsonl.empty();
  if (have_text_corpus && !ReadJsonlTexts(corpus_jsonl, &texts, &why)) {
    std::fprintf(stderr, "epoch_store_mint: %s\n", why.c_str());
    return 1;
  }
  auto find_text = [&](const std::string& id) -> const std::string* {
    for (const auto& p : texts) if (p.first == id) return &p.second;
    return nullptr;
  };

  std::error_code mkdir_ec;
  std::filesystem::create_directories(raw_cache_dir, mkdir_ec);
  if (mkdir_ec) {
    std::fprintf(stderr, "epoch_store_mint: cannot create --raw-cache-dir '%s': %s\n", raw_cache_dir.c_str(),
                 mkdir_ec.message().c_str());
    return 1;
  }

  // ---- The vector leg's own producer, opened ONCE for the whole
  // invocation (not per document): the real leg's public handle when text
  // is available, the synthetic leg's interim handle (the product's own
  // composed selection path) when it is not. Never both -- a corpus either
  // carries committed text or it does not, for the whole run. ----
  semb_encoder pub_enc = nullptr;
  SembInterimEncoder* interim_enc = nullptr;
  if (have_text_corpus) {
    semb_config cfg{};
    cfg.struct_size = sizeof(cfg);
    cfg.model_path = model.data();
    cfg.model_path_len = model.size();
    cfg.tokenizer_path = tokenizer.data();
    cfg.tokenizer_path_len = tokenizer.size();
    cfg.max_concurrency = 1;
    const semb_status st = semb_encoder_open(&cfg, &pub_enc);
    if (st != SEMB_OK || !pub_enc) {
      std::fprintf(stderr, "epoch_store_mint: semb_encoder_open (public, raw-path leg) refused: %s\n",
                   semb_status_name(st));
      return 1;
    }
  } else {
    const char* engine_status = nullptr;
    const SembInterimStatus st =
        semb_interim_encoder_open(model.c_str(), static_cast<int32_t>(terminator_id), &interim_enc, &engine_status);
    if (st != kSembInterimOk || !interim_enc) {
      std::fprintf(stderr, "epoch_store_mint: semb_interim_encoder_open (synthetic leg) refused (status=%d, engine=%s)\n",
                   static_cast<int>(st), engine_status ? engine_status : "?");
      return 1;
    }
  }

  int written = 0;
  for (const DocTokens& d : docs) {
    // ---- The vector member's own raw bytes. ----
    std::vector<float> row_vector(dims, 0.0f);
    if (have_text_corpus) {
      const std::string* text = find_text(d.id);
      if (!text) {
        std::fprintf(stderr, "epoch_store_mint: '%s' has no entry in --corpus-jsonl\n", d.id.c_str());
        if (pub_enc) semb_encoder_close(pub_enc);
        return 1;
      }
      size_t required = 0;
      semb_fingerprint fp{};
      fp.struct_size = sizeof(fp);
      const semb_status es = semb_encode(pub_enc, text->data(), text->size(), row_vector.data(),
                                          row_vector.size() * sizeof(float), &required, &fp);
      if (es != SEMB_OK) {
        std::fprintf(stderr, "epoch_store_mint: '%s' raw-path semb_encode refused: %s\n", d.id.c_str(),
                     semb_status_name(es));
        semb_encoder_close(pub_enc);
        return 1;
      }
    } else {
      // The product's own composed selection, driven by token ids: seam ->
      // select the last position through the engine's real final-norm
      // site -> dequantize. NEVER dequantize the seam's own raw,
      // pre-final-norm codes directly (D-SLM6382's own construction
      // defect, this round's own Decision Log entry).
      const size_t n = d.content_ids.size() + 1;  // the appended end token
      std::vector<int8_t> codes(n * dims);
      std::vector<int64_t> m(n), e(n);
      size_t positions = 0;
      const char* engine_status = nullptr;
      SembInterimStatus st = semb_interim_encode_seam(interim_enc, d.content_ids.data(), d.content_ids.size(),
                                                       /*chunk_budget=*/0, kSembForwardLegChunkBatched,
                                                       codes.data(), codes.size(), m.data(), e.data(), n,
                                                       &positions, &engine_status);
      if (st != kSembInterimOk || positions != n) {
        std::fprintf(stderr, "epoch_store_mint: '%s' semb_interim_encode_seam refused (status=%d, engine=%s, positions=%zu/%zu)\n",
                     d.id.c_str(), static_cast<int>(st), engine_status ? engine_status : "?", positions, n);
        semb_interim_encoder_close(interim_enc);
        return 1;
      }
      std::vector<int8_t> sel(dims);
      int64_t sel_m = 0, sel_e = 0;
      st = semb_interim_ps_n_select(interim_enc, codes.data(), m.data(), e.data(), n, n - 1, sel.data(),
                                    &sel_m, &sel_e, &engine_status);
      if (st != kSembInterimOk) {
        std::fprintf(stderr, "epoch_store_mint: '%s' semb_interim_ps_n_select refused (status=%d, engine=%s)\n",
                     d.id.c_str(), static_cast<int>(st), engine_status ? engine_status : "?");
        semb_interim_encoder_close(interim_enc);
        return 1;
      }
      const SembWaPoolStatus dq = semb_ps_n_dequantize(sel.data(), sel_m, sel_e, dims, row_vector.data());
      if (dq != kSembOk) {
        std::fprintf(stderr, "epoch_store_mint: '%s' semb_ps_n_dequantize refused (status=%d)\n", d.id.c_str(),
                     static_cast<int>(dq));
        semb_interim_encoder_close(interim_enc);
        return 1;
      }
    }
    const uint8_t* vec_bytes = reinterpret_cast<const uint8_t*>(row_vector.data());
    const size_t vec_len = row_vector.size() * sizeof(float);
    if (!WriteWholeFile(raw_cache_dir + "/" + d.id + ".vec", vec_bytes, vec_len, &why)) {
      std::fprintf(stderr, "epoch_store_mint: %s\n", why.c_str());
      if (pub_enc) semb_encoder_close(pub_enc);
      if (interim_enc) semb_interim_encoder_close(interim_enc);
      return 1;
    }

    // ---- The lineage member's own raw seam bytes -- the lineage oracle's
    // only two primitives, unconditionally, for both legs. ----
    std::vector<int32_t> ids_with_terminator = d.content_ids;
    ids_with_terminator.push_back(static_cast<int32_t>(terminator_id));
    std::vector<uint8_t> seam_bytes;
    if (!ComputeSeamBytes(model, ids_with_terminator, &seam_bytes, &why)) {
      std::fprintf(stderr, "epoch_store_mint: '%s' %s\n", d.id.c_str(), why.c_str());
      if (pub_enc) semb_encoder_close(pub_enc);
      if (interim_enc) semb_interim_encoder_close(interim_enc);
      return 1;
    }
    if (!WriteWholeFile(raw_cache_dir + "/" + d.id + ".seam", seam_bytes.data(), seam_bytes.size(), &why)) {
      std::fprintf(stderr, "epoch_store_mint: %s\n", why.c_str());
      if (pub_enc) semb_encoder_close(pub_enc);
      if (interim_enc) semb_interim_encoder_close(interim_enc);
      return 1;
    }

    ++written;
    std::printf("[cached] %s (.vec %zu bytes, .seam %zu bytes)\n", d.id.c_str(), vec_len, seam_bytes.size());
  }

  if (pub_enc) semb_encoder_close(pub_enc);
  if (interim_enc) semb_interim_encoder_close(interim_enc);
  std::printf("epoch_store_mint encode: %d document(s) cached to %s\n", written, raw_cache_dir.c_str());
  return 0;
}

int RunAssemble(int argc, char** argv) {
  std::string tokens, raw_cache_dir, fingerprint_hex, out_dir;
  for (int i = 2; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--tokens") next(&tokens);
    else if (k == "--raw-cache-dir") next(&raw_cache_dir);
    else if (k == "--fingerprint-hex") next(&fingerprint_hex);
    else if (k == "--out-dir") next(&out_dir);
  }
  if (tokens.empty() || raw_cache_dir.empty() || fingerprint_hex.empty() || out_dir.empty() ||
      fingerprint_hex.size() != static_cast<size_t>(semb_epoch_contract::kFingerprintHexChars)) {
    std::fprintf(stderr,
                 "usage: %s assemble --tokens <tsv> --raw-cache-dir <dir> --fingerprint-hex <64-hex> "
                 "--out-dir <epoch-store repository root>\n",
                 argv[0]);
    return 2;
  }

  std::string why;
  const std::vector<DocTokens> docs = ReadTokensTsv(tokens, &why);
  if (docs.empty()) {
    std::fprintf(stderr, "epoch_store_mint: %s\n", why.empty() ? "empty corpus" : why.c_str());
    return 1;
  }

  std::vector<uint8_t> vectors_blob;
  std::string row_digest_text;
  std::string lineage_text;
  std::vector<uint8_t> lineage_all_stream;
  PutU64LE(&lineage_all_stream, static_cast<uint64_t>(docs.size()));

  for (const DocTokens& d : docs) {
    std::vector<uint8_t> vec_bytes, seam_bytes;
    const std::string vec_path = raw_cache_dir + "/" + d.id + ".vec";
    const std::string seam_path = raw_cache_dir + "/" + d.id + ".seam";
    if (!ReadWholeFile(vec_path, &vec_bytes)) {
      std::fprintf(stderr, "epoch_store_mint: assemble: missing cache file %s (encode mode did not run for '%s' -- nothing written)\n",
                   vec_path.c_str(), d.id.c_str());
      return 1;
    }
    if (!ReadWholeFile(seam_path, &seam_bytes)) {
      std::fprintf(stderr, "epoch_store_mint: assemble: missing cache file %s (encode mode did not run for '%s' -- nothing written)\n",
                   seam_path.c_str(), d.id.c_str());
      return 1;
    }
    vectors_blob.insert(vectors_blob.end(), vec_bytes.begin(), vec_bytes.end());
    uint8_t row_digest[32];
    superslm::Sha256Hash(vec_bytes.data(), vec_bytes.size(), row_digest);
    row_digest_text += d.id + "\t" + Hex(row_digest) + "\n";

    uint8_t seam_digest[32];
    superslm::Sha256Hash(seam_bytes.data(), seam_bytes.size(), seam_digest);
    lineage_text += d.id + "\t" + Hex(seam_digest) + "\n";
    lineage_all_stream.insert(lineage_all_stream.end(), seam_bytes.begin(), seam_bytes.end());
  }

  uint8_t vectors_all_digest[32];
  superslm::Sha256Hash(vectors_blob.data(), vectors_blob.size(), vectors_all_digest);
  row_digest_text += std::string("all\t") + Hex(vectors_all_digest) + "\n";

  uint8_t lineage_all_digest[32];
  superslm::Sha256Hash(lineage_all_stream.data(), lineage_all_stream.size(), lineage_all_digest);
  lineage_text += std::string("all\t") + Hex(lineage_all_digest) + "\n";

  std::string fp_lower = fingerprint_hex;
  for (char& c : fp_lower) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  const std::string entry_dir = out_dir + "/" + semb_epoch_contract::kLiveDir + "/" + fp_lower;
  std::error_code mkdir_ec;
  std::filesystem::create_directories(entry_dir, mkdir_ec);
  if (mkdir_ec) {
    std::fprintf(stderr, "epoch_store_mint: cannot create %s: %s\n", entry_dir.c_str(), mkdir_ec.message().c_str());
    return 1;
  }
  if (!WriteWholeFile(entry_dir + "/" + semb_epoch_contract::kVectorsFileName, vectors_blob.data(),
                       vectors_blob.size(), &why) ||
      !WriteText(entry_dir + "/" + semb_epoch_contract::kRowDigestFileName, row_digest_text, &why) ||
      !WriteText(entry_dir + "/" + semb_epoch_contract::kLineageFileName, lineage_text, &why)) {
    std::fprintf(stderr, "epoch_store_mint: %s\n", why.c_str());
    return 1;
  }

  std::printf("assembled: %s (%zu documents, %zu vector bytes)\n", entry_dir.c_str(), docs.size(), vectors_blob.size());
  std::printf("vectors_all_sha256=%s\n", Hex(vectors_all_digest).c_str());
  std::printf("lineage_all_sha256=%s\n", Hex(lineage_all_digest).c_str());
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s <fingerprint|encode|assemble> [options]\n", argv[0]);
    return 2;
  }
  const std::string mode = argv[1];
  if (mode == "fingerprint") return RunFingerprint(argc, argv);
  if (mode == "encode") return RunEncode(argc, argv);
  if (mode == "assemble") return RunAssemble(argc, argv);
  std::fprintf(stderr, "epoch_store_mint: unknown mode '%s' (want fingerprint|encode|assemble)\n", mode.c_str());
  return 2;
}
