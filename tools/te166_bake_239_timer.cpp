// tools/te166_bake_239_timer.cpp -- TE-166 (U1 slice 4) diagnostic: times a
// real 239-document semb_bake_to_path call against the real candidate
// artifact, independent of tests/te163_bank_pair_test.cpp's own --real leg.
//
// WHY THIS EXISTS. It was introduced as a workaround: the tamper cell in
// te163_bank_pair_test.cpp that made that binary's --real leg unreachable
// (the unknown-schemaVersion construction's own ReplaceOnce throwing an
// uncaught std::runtime_error, exiting 0xC0000409 before the leg) was
// closed at ac12fac/c2b8380, and the --real leg now runs to completion --
// 48 cells, 0 failures at 21b1735, including the 239-document bake this
// tool also times. The tool is kept as a standalone timing diagnostic: an
// independent wall-clock reading of the bake that does not rerun the
// suite, calling the SAME semb_bake_to_path on the SAME committed fixture
// tests/fixtures/c12b/corpus-239.jsonl. It duplicates no row derivation,
// asserts nothing the suite itself does not already assert, and is not
// wired to ctest -- diagnostic only.
#include <chrono>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "json_lite.h"
#include "superembedder/bake_abi.h"
#include "superembedder/semb.h"

namespace {

// A minimal one-object-per-line JSONL reader over corpus-239.jsonl's own
// {"label":.., "text":.., ...} shape -- reads exactly the two fields this
// tool needs via this round's own product-side JSON parser
// (src/superembedder/json_lite.h), never a copy of tests/json_mini.h.
std::vector<std::pair<std::string, std::string>> LoadCorpus239(const std::string& path) {
  std::vector<std::pair<std::string, std::string>> out;
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open corpus: " + path);
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    namespace js = semb::json;
    const js::Value v = js::Parse(line);
    const js::Value* label = v.Find("label");
    const js::Value* text = v.Find("text");
    if (!label || !label->IsString() || !text || !text->IsString()) {
      throw std::runtime_error("corpus-239.jsonl: a line is missing label/text");
    }
    out.emplace_back(label->as_string, text->as_string);
  }
  return out;
}

// Arena-owned document set -- the identical pattern
// tests/u1_batch_contract_test.cpp and tests/te163_bank_pair_test.cpp both
// use (a temporary std::string bound to a semb_document's raw pointer
// dangles the instant the constructing expression ends).
class DocSet {
 public:
  explicit DocSet(size_t n) { arena_.reserve(n * 2); }
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

}  // namespace

int main(int argc, char** argv) {
  if (argc != 5) {
    std::fprintf(stderr,
                  "usage: %s <model.sslm> <tokenizer.sslm> <corpus-239.jsonl> <out-stem>\n",
                  argv[0]);
    return 2;
  }
  const std::string model = argv[1];
  const std::string tokenizer = argv[2];
  const std::string corpus_path = argv[3];
  const std::string stem = argv[4];

  std::vector<std::pair<std::string, std::string>> docs_raw;
  try {
    docs_raw = LoadCorpus239(corpus_path);
  } catch (const std::exception& e) {
    std::fprintf(stderr, "[FAIL] load corpus-239.jsonl: %s\n", e.what());
    return 1;
  }
  std::printf("[OBSERVED] corpus-239 document count: %zu\n", docs_raw.size());

  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = model.data();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tokenizer.data();
  cfg.tokenizer_path_len = tokenizer.size();
  cfg.max_concurrency = 4;
  semb_encoder enc = nullptr;
  const semb_status open_status = semb_encoder_open(&cfg, &enc);
  if (open_status != SEMB_OK || !enc) {
    std::printf("[FAIL] semb_encoder_open: %s\n", semb_status_name(open_status));
    return 1;
  }

  DocSet arena(docs_raw.size());
  std::vector<semb_document> docs;
  docs.reserve(docs_raw.size());
  for (auto& [id, text] : docs_raw) docs.push_back(arena.Add(id, text));

  const auto t0 = std::chrono::steady_clock::now();
  const semb_status bake_status =
      semb_bake_to_path(enc, docs.data(), docs.size(), stem.c_str(), stem.size());
  const auto t1 = std::chrono::steady_clock::now();
  const double wall_s = std::chrono::duration<double>(t1 - t0).count();

  std::printf("[%s] 239-document bake on the real candidate artifact -> SEMB_OK: %s\n",
              bake_status == SEMB_OK ? "PASS" : "FAIL", semb_status_name(bake_status));
  std::printf("[OBSERVED] 239-document real-artifact bake wall clock: %fs\n", wall_s);

  semb_encoder_close(enc);
  return bake_status == SEMB_OK ? 0 : 1;
}
