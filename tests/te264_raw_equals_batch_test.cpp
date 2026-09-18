// tests/te264_raw_equals_batch_test.cpp -- TE-264, U1 Slice 7 step 2's
// committed raw-equals-batch cell (`Claude/Plans/te140-u1-remainder-
// sequencing.md` sec 4.7 step 2; D-SLM7197, D-SLM7204, D-SLM7205).
//
// THE CLAIM. For each of the 239 corpus documents
// (tests/fixtures/c12b/corpus-239.jsonl) and each of the 16 W-B documents
// (src/superembedder/wb_corpus.cpp, kWbCorpusDocuments), the vector
// `semb_encode` returns equals the `semb_encode_batch` row for the same text,
// byte for byte, on one encoder handle over the real artifact.
//
// WHAT IT GUARDS. Step 2 routes `semb_encode` through the batch composition.
// This cell is green before and after that step (the plan's own statement):
// its job is to hold across the step and, afterwards, to guard the raw-only
// output copy that the W-B witness does not execute. It is not a red-first
// cell; step 2's red test is tests/te264_raw_entry_composition_check.py.
//
// THE ORACLE. Each side is the product's own public verb; the comparison is
// equality of the two public entry points on identical text, which is the
// property D-SLM7197 rules. Neither side is derived from the other, and no
// expected vector is stored. The batch side is called once per population
// (239 rows, then 16 rows) -- the row a bake stores.
//
// POPULATION CHECK. With --corpus-manifest, the corpus file's SHA-256 and
// document count are required to equal the committed manifest's, so the
// registered cell cannot run over a truncated or edited corpus.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --corpus <jsonl>
//        [--corpus-manifest <json>]
// Exit 0 every cell PASS; 1 any FAIL; 2 usage.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "json_mini.h"
#include "superembedder/semb.h"
#include "superslm/sha256.h"
#include "wb_corpus.h"

namespace {

int g_failures = 0;

void Verdict(bool ok, const std::string& cell, const std::string& detail) {
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), detail.c_str());
  std::fflush(stdout);
  if (!ok) ++g_failures;
}

const char* Value(int argc, char** argv, const char* key) {
  for (int i = 1; i + 1 < argc; ++i)
    if (std::strcmp(argv[i], key) == 0) return argv[i + 1];
  return nullptr;
}

bool ReadFile(const char* path, std::string* out) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  std::ostringstream ss;
  ss << in.rdbuf();
  *out = ss.str();
  return true;
}

std::string Sha256Hex(const std::string& bytes) {
  superslm::Sha256 h;
  h.Update(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
  uint8_t d[32];
  h.Final(d);
  static const char* k = "0123456789abcdef";
  std::string out;
  for (uint8_t b : d) { out.push_back(k[b >> 4]); out.push_back(k[b & 15]); }
  return out;
}

// A 16-byte-aligned float buffer (semb_encode refuses a misaligned vector).
struct Aligned {
  explicit Aligned(size_t bytes) : storage(bytes + 16) {
    data = reinterpret_cast<float*>((reinterpret_cast<uintptr_t>(storage.data()) + 15) & ~uintptr_t(15));
  }
  std::vector<uint8_t> storage;
  float* data;
};

struct Population {
  std::string name;
  std::vector<std::string> ids;
  std::vector<std::string> texts;
};

// Compares semb_encode against the semb_encode_batch row for every text.
void Compare(semb_encoder enc, uint32_t dims, const Population& p) {
  const size_t row_bytes = static_cast<size_t>(dims) * sizeof(float);
  const size_t n = p.texts.size();
  std::vector<semb_document> docs;
  for (size_t i = 0; i < n; ++i) {
    docs.push_back(semb_document{sizeof(semb_document), p.ids[i].data(), p.ids[i].size(),
                                 p.texts[i].data(), p.texts[i].size()});
  }
  Aligned rows(n * row_bytes);
  size_t required = 0;
  const semb_status bs = semb_encode_batch(enc, docs.data(), n, rows.data, n * row_bytes, &required);
  if (bs != SEMB_OK || required != n * row_bytes) {
    Verdict(false, p.name + ": semb_encode_batch over the whole population",
            std::string("status=") + semb_status_name(bs) + " required=" + std::to_string(required));
    return;
  }
  const auto* row_base = reinterpret_cast<const uint8_t*>(rows.data);
  size_t equal = 0;
  std::string differing, refused;
  std::vector<uint8_t> raw0;
  for (size_t i = 0; i < n; ++i) {
    Aligned raw(row_bytes);
    size_t raw_required = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    const semb_status rs = semb_encode(enc, p.texts[i].data(), p.texts[i].size(), raw.data, row_bytes,
                                       &raw_required, &fp);
    if (rs != SEMB_OK) {
      refused += " " + p.ids[i] + "=" + semb_status_name(rs);
      continue;
    }
    if (i == 0) {
      const auto* b = reinterpret_cast<const uint8_t*>(raw.data);
      raw0.assign(b, b + row_bytes);
    }
    if (std::memcmp(raw.data, row_base + i * row_bytes, row_bytes) == 0) {
      ++equal;
    } else if (differing.size() < 400) {
      differing += " " + p.ids[i];
    }
  }
  Verdict(equal == n,
          p.name + ": semb_encode's vector equals the semb_encode_batch row for the same text, byte for byte",
          std::to_string(equal) + " of " + std::to_string(n) + " equal" +
              (differing.empty() ? "" : "; differing:" + differing) +
              (refused.empty() ? "" : "; raw refused:" + refused));
  // Vitality: the comparison can fail. Document 0's raw vector against
  // document 1's row (two different texts) must differ; equal bytes here
  // would mean the comparison cannot distinguish documents at all.
  if (n >= 2 && raw0.size() == row_bytes) {
    Verdict(std::memcmp(raw0.data(), row_base + row_bytes, row_bytes) != 0,
            p.name + ": vitality -- document 0's raw vector differs from document 1's batch row",
            p.ids[0] + " vs " + p.ids[1]);
  }
}

}  // namespace

int main(int argc, char** argv) {
  const char* model = Value(argc, argv, "--model");
  const char* tokenizer = Value(argc, argv, "--tokenizer");
  const char* corpus = Value(argc, argv, "--corpus");
  const char* corpus_manifest = Value(argc, argv, "--corpus-manifest");
  if (!model || !tokenizer || !corpus) {
    std::fputs("usage: --model M --tokenizer T --corpus JSONL [--corpus-manifest JSON]\n", stderr);
    return 2;
  }

  Population corpus_pop{"corpus", {}, {}};
  std::string corpus_bytes;
  if (!ReadFile(corpus, &corpus_bytes)) {
    Verdict(false, "corpus", std::string("cannot read ") + corpus);
    return 1;
  }
  try {
    std::istringstream lines(corpus_bytes);
    std::string line;
    while (std::getline(lines, line)) {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      if (line.empty()) continue;
      const json_mini::Value row = json_mini::Parse(line);
      corpus_pop.ids.push_back(row["label"].s());
      corpus_pop.texts.push_back(row["text"].s());
    }
  } catch (const std::exception& e) {
    Verdict(false, "corpus", std::string("JSONL parse: ") + e.what());
    return 1;
  }
  if (corpus_manifest) {
    std::string manifest_text;
    bool ok = ReadFile(corpus_manifest, &manifest_text);
    std::string detail = ok ? "" : std::string("cannot read ") + corpus_manifest;
    if (ok) {
      // The manifest carries a JSON boolean json_mini does not read, so the
      // two fields this check needs are taken by key: the quoted value after
      // "corpus-239.jsonl": and the integer after "documents":.
      std::string want_sha;
      long long want_n = -1;
      const size_t k = manifest_text.find("\"corpus-239.jsonl\"");
      if (k != std::string::npos) {
        const size_t q1 = manifest_text.find('"', manifest_text.find(':', k) + 1);
        const size_t q2 = q1 == std::string::npos ? q1 : manifest_text.find('"', q1 + 1);
        if (q2 != std::string::npos) want_sha = manifest_text.substr(q1 + 1, q2 - q1 - 1);
      }
      const size_t d = manifest_text.find("\"documents\"");
      if (d != std::string::npos) want_n = std::atoll(manifest_text.c_str() + manifest_text.find(':', d) + 1);
      const std::string got_sha = Sha256Hex(corpus_bytes);
      ok = !want_sha.empty() && got_sha == want_sha &&
           static_cast<long long>(corpus_pop.texts.size()) == want_n;
      detail = "sha256=" + got_sha + " (manifest " + want_sha + "), documents=" +
               std::to_string(corpus_pop.texts.size()) + " (manifest " + std::to_string(want_n) + ")";
    }
    Verdict(ok, "the corpus population is the committed corpus-239 (bytes and count)", detail);
    if (!ok) return 1;
  }

  Population wb_pop{"W-B", {}, {}};
  for (size_t i = 0; i < semb::kWbCorpusDocumentCount; ++i) {
    char id[8];
    std::snprintf(id, sizeof(id), "wb-%02zu", i);
    wb_pop.ids.push_back(id);
    wb_pop.texts.emplace_back(semb::kWbCorpusDocuments[i].text, semb::kWbCorpusDocuments[i].text_len);
  }

  semb_config cfg{sizeof(cfg), model, std::strlen(model), tokenizer, std::strlen(tokenizer), 1};
  semb_encoder enc = nullptr;
  const semb_status os = semb_encoder_open(&cfg, &enc);
  if (os != SEMB_OK) {
    Verdict(false, "semb_encoder_open", semb_status_name(os));
    return 1;
  }
  uint32_t dims = 0;
  const semb_status ds = semb_encoder_dims(enc, &dims);
  if (ds != SEMB_OK || dims == 0) {
    Verdict(false, "semb_encoder_dims", semb_status_name(ds));
    semb_encoder_close(enc);
    return 1;
  }
  Compare(enc, dims, corpus_pop);
  Compare(enc, dims, wb_pop);
  const semb_status cs = semb_encoder_close(enc);
  Verdict(cs == SEMB_OK, "semb_encoder_close", semb_status_name(cs));
  std::printf("[SUMMARY] failures=%d\n", g_failures);
  return g_failures ? 1 : 0;
}
