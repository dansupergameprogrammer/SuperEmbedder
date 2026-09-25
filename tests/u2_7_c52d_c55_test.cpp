// tests/u2_7_c52d_c55_test.cpp -- U2 cloud build, U2-7's C52 (d) and C55's
// general oracle (te267 sec 5 U2-7, "Cells", "C52 (d)", "Proof"), on the
// synthetic pair (the real legs run with --model/--tokenizer pointing at the
// real artifact, and C55's real oracle needs the real checkpoint's
// tokenizer.json, which the driver supplies on the dev box).
//
//   C52 (d) -- the in-call rewrite. The test seam parks
//     `semb_encoder_open_memory` after the owned copies are digested and before
//     the interim open loads them; there the test overwrites both caller spans
//     with 0xFF, then releases the open. The open returns SEMB_OK, with the path
//     open's fingerprint, and 16 query vectors (`semb_encode_query`) equal to
//     the path open's. Must-reject (by construction): an implementation that
//     digests the caller's spans and hands them to the engine uncopied loads
//     0xFF bytes, and its open refuses or its fingerprint differs.
//   C55 (general) -- `semb_interim_query_token_count(text)` equals the count an
//     independent tokenization computes outside the library,
//     len(Encode(ComposeQuery(text))) - len(Encode(kQueryPrefix)), over C5's
//     239 texts, the prefix-merge construction and the empty text. The expected
//     counts arrive in --expected (hex text <TAB> count), written by the driver
//     from the pinned converter's `ref_encode`.
//
// RED TODAY: fails to LINK -- `semb_encoder_open_memory`, `semb_encode_query`,
// `semb_interim_query_token_count` and the three seam functions do not exist.
//
// USAGE: --model <m> --tokenizer <t> --expected <tsv> [--cells c52d,c55]
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_bank_abi_contract.h"
#include "semb_query_abi_contract.h"
#include "te331_u2_abi_contract.h"
#include "support/semb_u2_7_memory_open_seam.h"

namespace {

int g_fail = 0;
void Verdict(bool ok, const std::string& cell, const std::string& detail) {
  if (!ok) ++g_fail;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), detail.c_str());
  std::fflush(stdout);
}
std::string ReadAll(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}
std::string Hex(const uint8_t* d, size_t n) {
  static const char* k = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; ++i) { s += k[d[i] >> 4]; s += k[d[i] & 15]; }
  return s;
}
std::string Unhex(const std::string& h) {
  std::string s;
  for (size_t i = 0; i + 1 < h.size(); i += 2) s += static_cast<char>(std::stoi(h.substr(i, 2), nullptr, 16));
  return s;
}

std::vector<std::string> QueryTexts() {
  std::vector<std::string> t;
  for (int i = 0; i < 16; ++i) t.push_back("query number " + std::to_string(i) + ": where is the " + std::string(i + 1, 'x'));
  return t;
}

bool QueryVectors(semb_encoder e, std::vector<std::vector<float>>* out, std::string* why) {
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  for (const std::string& q : QueryTexts()) {
    std::vector<float> v(dims);
    size_t req = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    const semb_status s = semb_encode_query(e, q.data(), q.size(), v.data(), v.size() * 4, &req, &fp);
    if (s != SEMB_OK) { *why = std::string("semb_encode_query ") + semb_status_name(s); return false; }
    out->push_back(v);
  }
  return true;
}

void CellC52d(const std::string& model, const std::string& tok) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = model.data();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tok.data();
  cfg.tokenizer_path_len = tok.size();
  cfg.max_concurrency = 1;
  semb_encoder path_enc = nullptr;
  semb_status s = semb_encoder_open(&cfg, &path_enc);
  if (s != SEMB_OK) { Verdict(false, "C52 (d) setup: path open", semb_status_name(s)); return; }
  semb_fingerprint path_fp{};
  path_fp.struct_size = sizeof(path_fp);
  semb_fingerprint_of(path_enc, &path_fp);
  std::vector<std::vector<float>> path_q;
  std::string why;
  if (!QueryVectors(path_enc, &path_q, &why)) { Verdict(false, "C52 (d) setup: path query vectors", why); }
  semb_encoder_close(path_enc);

  std::string model_bytes = ReadAll(model), tok_bytes = ReadAll(tok);
  semb_memory_config mcfg{};
  mcfg.struct_size = sizeof(mcfg);
  mcfg.model_bytes = reinterpret_cast<const uint8_t*>(model_bytes.data());
  mcfg.model_len = model_bytes.size();
  mcfg.tokenizer_bytes = reinterpret_cast<const uint8_t*>(tok_bytes.data());
  mcfg.tokenizer_len = tok_bytes.size();
  mcfg.max_concurrency = 1;
  if (!semb_test_seam_memory_open_arm_park()) { Verdict(false, "C52 (d) setup: arm the park point", "refused"); return; }
  semb_encoder mem_enc = nullptr;
  std::atomic<int> mem_status{-1};
  std::thread opener([&] { mem_status = semb_encoder_open_memory(&mcfg, &mem_enc); });
  const bool parked = semb_test_seam_memory_open_wait_parked(120000) == 1;
  if (parked) {
    std::memset(&model_bytes[0], 0xFF, model_bytes.size());
    std::memset(&tok_bytes[0], 0xFF, tok_bytes.size());
  }
  semb_test_seam_memory_open_release();
  opener.join();
  Verdict(parked, "C52 (d) the memory open reached the park point (after the digest, before the interim open)",
          parked ? "parked; both caller spans overwritten with 0xFF" : "bounded wait (120 s) timed out");
  const semb_status ms = static_cast<semb_status>(mem_status.load());
  Verdict(ms == SEMB_OK, "C52 (d) the open returns SEMB_OK after its caller's spans were rewritten in-call",
          semb_status_name(ms));
  if (ms != SEMB_OK || !mem_enc) return;
  semb_fingerprint mem_fp{};
  mem_fp.struct_size = sizeof(mem_fp);
  semb_fingerprint_of(mem_enc, &mem_fp);
  Verdict(std::memcmp(mem_fp.digest, path_fp.digest, 32) == 0, "C52 (d) fingerprint equals the path open's",
          Hex(mem_fp.digest, 32).substr(0, 16) + " vs " + Hex(path_fp.digest, 32).substr(0, 16));
  std::vector<std::vector<float>> mem_q;
  const bool got = QueryVectors(mem_enc, &mem_q, &why);
  Verdict(got && mem_q == path_q && path_q.size() == 16, "C52 (d) 16 query vectors equal the path open's",
          got ? std::to_string(mem_q.size()) + " vectors" : why);
  semb_encoder_close(mem_enc);
}

void CellC55(const std::string& model, const std::string& tok, const std::string& expected) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = model.data();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tok.data();
  cfg.tokenizer_path_len = tok.size();
  cfg.max_concurrency = 1;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != SEMB_OK) { Verdict(false, "C55 setup: open", semb_status_name(s)); return; }
  std::ifstream f(expected);
  std::string line;
  int n = 0, bad = 0;
  std::string first_bad;
  while (std::getline(f, line)) {
    if (line.empty() || line[0] == '#') continue;
    const auto tab = line.find('\t');
    const std::string text = Unhex(line.substr(0, tab));
    const int64_t want = std::stoll(line.substr(tab + 1));
    int64_t got = -1;
    const SembInterimStatus ts = semb_interim_query_token_count(enc, text.data(), text.size(), &got);
    ++n;
    if (ts != kSembInterimOk || got != want) {
      ++bad;
      if (first_bad.empty()) {
        first_bad = "text " + std::to_string(n) + " (" + std::to_string(text.size()) + " B): got " +
                    std::to_string(got) + " status " + std::to_string(ts) + ", independent count " +
                    std::to_string(want);
      }
    }
  }
  semb_encoder_close(enc);
  Verdict(n > 0 && bad == 0,
          "C55 token count == independent tokenization of ComposeQuery(text) less the prefix, every text",
          std::to_string(n - bad) + " of " + std::to_string(n) + (first_bad.empty() ? "" : "; first: " + first_bad));
}

}  // namespace

int main(int argc, char** argv) {
  std::string model, tok, expected;
  std::set<std::string> cells;
  for (int i = 1; i + 1 < argc; ++i) {
    const std::string k = argv[i];
    if (k == "--model") model = argv[++i];
    else if (k == "--tokenizer") tok = argv[++i];
    else if (k == "--expected") expected = argv[++i];
    else if (k == "--cells") {
      std::stringstream ss(argv[++i]);
      std::string c;
      while (std::getline(ss, c, ',')) cells.insert(c);
    }
  }
  if (model.empty() || tok.empty()) {
    std::fprintf(stderr, "usage: %s --model m --tokenizer t --expected tsv [--cells c52d,c55]\n", argv[0]);
    return 2;
  }
  if (cells.empty() || cells.count("c52d")) CellC52d(model, tok);
  if ((cells.empty() || cells.count("c55")) && !expected.empty()) CellC55(model, tok, expected);
  std::printf("TOTAL fail=%d\n", g_fail);
  return g_fail ? 1 : 0;
}
