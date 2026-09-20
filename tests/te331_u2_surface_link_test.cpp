// tests/te331_u2_surface_link_test.cpp -- TE-331 (U2-1/U2-3/U2-7 red suite):
// the red-first driver for U2-7's four surface additions
// (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-7 items 1, 2, 6, 7):
//
//   semb_encoder_open_memory (C52, Q4/F21)
//   semb_encode_query        (C53, Q5/F22)
//   semb_interim_query_token_count (C55, R17)
//   semb_interim_certification_verdict (C57, R8/M22)
//
// RED AT `fca421b`: none of the four exist in `superembedder`
// (`git grep -n "semb_encoder_open_memory\|semb_encode_query\|semb_interim_
// query_token_count\|semb_interim_certification_verdict" src/ include/`
// returns nothing) -- this executable fails to LINK until the builder's
// round adds them. tests/te331_u2_surface_link_check.py builds this
// EXCLUDE_FROM_ALL target on demand and reports the unresolved symbol(s) by
// name, the te163/te194 red-first shape.
//
// WHAT RUNS ONCE IT LINKS, on the REAL Qwen3-Embedding-0.6B artifact (no
// synthetic mechanism leg: every cell here needs the real tokenizer's real
// vocabulary and the real forward, per StandardsDocument.md sec 5.4's "a
// test exercises the real workload"):
//
//   C52 -- the memory open equals the path open. The same model and
//   tokenizer bytes, opened once by path (`semb_encoder_open`, already
//   built) and once from memory (`semb_encoder_open_memory`), must report
//   identical dims, identical fingerprint, and identical encode output for
//   the same text.
//   C53 -- the raw query verb equals the checked one. A one-document bank
//   baked and opened normally (`semb_bake_to_path`, `semb_query_open`,
//   `semb_query_encode`, all already built) gives a baseline query vector
//   and fingerprint for a fixed text; `semb_encode_query`, called on the
//   SAME encoder with no bank at all, must emit the identical vector and
//   fingerprint for the identical text.
//   C55 (TE-321's empty-text extreme) -- `semb_interim_query_token_count("")`
//   returns exactly 0, verified at source from `ComposeQuery`'s own
//   no-separator concatenation (ComposeQuery("") is byte-identical to
//   kQueryPrefix, so the composed length equals the prefix's own length and
//   their difference is 0 by construction) -- a feature-oracle cell that
//   needs no external tokenizer to grade, unlike the general (non-empty)
//   case.
//   C57 (informational only, this round) -- calls the verb once and prints
//   every field. The plan's own must-accept/must-reject matrix (a build
//   outside the certified set reporting "uncertified"; an application
//   linking an engine item 14 would refuse reporting the check's own named
//   status) needs U2-3 items 1, 9, 13 and 14 (the cell-form list, the
//   identity file, and CheckLinkedEngine) to exist at all -- NONE of which
//   is in this tree (`Claude/Vitruvius/te335-u2-fold-2026-09-19.md` sec 4:
//   "U2-3's whole certification mechanism... is not committed to
//   D:\SuperEmbedder at any commit"), and the deliberately-mismatched
//   engine pins the matrix needs (a `/GS-` engine, a forced-tier engine
//   above the host) are the ADVERSARY's own commissioning constructions
//   (`Claude/Loki/te301-probe/`, `te313-probe/`), not artifacts this seat
//   duplicates into product test source. This cell is a placeholder that
//   proves the verb is callable and its fields are well-formed; C57's own
//   graded matrix is the builder's, against the adversary's re-strike, per
//   the plan's own handoff (sec 12, TE-335 addendum).
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --scratch <dir>
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
#include "semb_batch_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_bank_abi_contract.h"
#include "semb_query_abi_contract.h"
#include "te331_u2_abi_contract.h"

namespace fs = std::filesystem;

namespace {

int g_failures = 0;
int g_cells = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
void Info(const std::string& cell, const std::string& observed) {
  std::printf("[INFO] %s: %s\n", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }

std::string ReadFileBytes(const fs::path& p) {
  std::ifstream f(p, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open " + p.string());
  std::ostringstream oss;
  oss << f.rdbuf();
  return oss.str();
}

std::string HexBytes(const void* data, size_t n) {
  static const char* kHex = "0123456789abcdef";
  const auto* d = static_cast<const uint8_t*>(data);
  std::string out(n * 2, '0');
  for (size_t i = 0; i < n; ++i) {
    out[2 * i] = kHex[(d[i] >> 4) & 0xF];
    out[2 * i + 1] = kHex[d[i] & 0xF];
  }
  return out;
}

struct Args {
  std::string model, tokenizer, scratch;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--scratch") next(&a.scratch);
  }
  return a;
}

// -----------------------------------------------------------------------
// C52 -- semb_encoder_open_memory equals semb_encoder_open.
// -----------------------------------------------------------------------
void CellC52MemoryEqualsPath(const Args& a) {
  const std::string kText = "the memory-opened encoder matches the path-opened one";

  semb_config path_cfg{};
  path_cfg.struct_size = sizeof(path_cfg);
  path_cfg.model_path = a.model.data();
  path_cfg.model_path_len = a.model.size();
  path_cfg.tokenizer_path = a.tokenizer.data();
  path_cfg.tokenizer_path_len = a.tokenizer.size();
  path_cfg.max_concurrency = 1;
  semb_encoder path_enc = nullptr;
  semb_status s = semb_encoder_open(&path_cfg, &path_enc);
  if (s != SEMB_OK || !path_enc) { Verdict(false, "C52 (setup) path open", Name(s)); return; }

  uint32_t path_dims = 0;
  semb_encoder_dims(path_enc, &path_dims);
  std::vector<float> path_vec(path_dims);
  semb_fingerprint path_fp{}; path_fp.struct_size = sizeof(path_fp);
  size_t required = 0;
  s = semb_encode(path_enc, kText.data(), kText.size(), path_vec.data(),
                  path_vec.size() * sizeof(float), &required, &path_fp);
  if (s != SEMB_OK) { Verdict(false, "C52 (setup) path encode", Name(s)); semb_encoder_close(path_enc); return; }

  const std::string model_bytes = ReadFileBytes(a.model);
  const std::string tok_bytes = ReadFileBytes(a.tokenizer);
  semb_memory_config mem_cfg{};
  mem_cfg.struct_size = sizeof(mem_cfg);
  mem_cfg.model_bytes = reinterpret_cast<const uint8_t*>(model_bytes.data());
  mem_cfg.model_len = model_bytes.size();
  mem_cfg.tokenizer_bytes = reinterpret_cast<const uint8_t*>(tok_bytes.data());
  mem_cfg.tokenizer_len = tok_bytes.size();
  mem_cfg.max_concurrency = 1;
  semb_encoder mem_enc = nullptr;
  s = semb_encoder_open_memory(&mem_cfg, &mem_enc);
  if (s != SEMB_OK || !mem_enc) { Verdict(false, "C52 memory open", Name(s)); semb_encoder_close(path_enc); return; }

  uint32_t mem_dims = 0;
  semb_encoder_dims(mem_enc, &mem_dims);
  Verdict(mem_dims == path_dims, "C52 dims equal", std::to_string(mem_dims) + " vs " + std::to_string(path_dims));

  std::vector<float> mem_vec(mem_dims);
  semb_fingerprint mem_fp{}; mem_fp.struct_size = sizeof(mem_fp);
  s = semb_encode(mem_enc, kText.data(), kText.size(), mem_vec.data(),
                  mem_vec.size() * sizeof(float), &required, &mem_fp);
  Verdict(s == SEMB_OK, "C52 memory encode", Name(s));
  if (s == SEMB_OK) {
    Verdict(mem_fp.digest && path_fp.digest &&
                std::memcmp(mem_fp.digest, path_fp.digest, sizeof(mem_fp.digest)) == 0,
            "C52 fingerprint equal", HexBytes(mem_fp.digest, 32) + " vs " + HexBytes(path_fp.digest, 32));
    Verdict(mem_vec.size() == path_vec.size() &&
                std::memcmp(mem_vec.data(), path_vec.data(), mem_vec.size() * sizeof(float)) == 0,
            "C52 vector bit-identical", "byte comparison over " + std::to_string(mem_vec.size() * 4) + " bytes");
  }
  // The caller's own copies may be dropped once the call returns (the
  // plan's own "the caller may release or rewrite its spans once the call
  // returns"); this cell exercises that once the mechanism exists by
  // scribbling over the source strings after open and re-encoding --
  // deferred here as a documented owed leg rather than asserted without
  // running it.
  semb_encoder_close(mem_enc);
  semb_encoder_close(path_enc);
}

// -----------------------------------------------------------------------
// C53 -- semb_encode_query equals the checked semb_query_encode.
// -----------------------------------------------------------------------
void CellC53RawEqualsChecked(const Args& a) {
  const std::string kText = "does the raw query verb match the checked one";
  const std::string stem = (fs::path(a.scratch) / "te331_c53_bank").string();

  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = a.model.data();
  cfg.model_path_len = a.model.size();
  cfg.tokenizer_path = a.tokenizer.data();
  cfg.tokenizer_path_len = a.tokenizer.size();
  cfg.max_concurrency = 1;
  semb_encoder enc = nullptr;
  semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != SEMB_OK || !enc) { Verdict(false, "C53 (setup) open", Name(s)); return; }

  semb_document doc{};
  doc.struct_size = sizeof(doc);
  const std::string id = "d0", text = "one document to bake a bank around";
  doc.id = id.data(); doc.id_len = id.size();
  doc.utf8 = text.data(); doc.utf8_len = text.size();
  s = semb_bake_to_path(enc, &doc, 1, stem.c_str(), stem.size());
  if (s != SEMB_OK) { Verdict(false, "C53 (setup) bake", Name(s)); semb_encoder_close(enc); return; }

  semb_bank bank = nullptr;
  s = semb_bank_open(stem.c_str(), stem.size(), &bank);
  if (s != SEMB_OK || !bank) { Verdict(false, "C53 (setup) bank open", Name(s)); semb_encoder_close(enc); return; }
  semb_query q = nullptr;
  s = semb_query_open(enc, bank, &q);
  if (s != SEMB_OK || !q) { Verdict(false, "C53 (setup) query open", Name(s)); semb_bank_close(bank); semb_encoder_close(enc); return; }

  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  std::vector<float> checked_vec(dims);
  size_t required = 0;
  s = semb_query_encode(q, kText.data(), kText.size(), checked_vec.data(),
                        checked_vec.size() * sizeof(float), &required);
  Verdict(s == SEMB_OK, "C53 (setup) checked query_encode", Name(s));

  std::vector<float> raw_vec(dims);
  semb_fingerprint raw_fp{}; raw_fp.struct_size = sizeof(raw_fp);
  s = semb_encode_query(enc, kText.data(), kText.size(), raw_vec.data(),
                        raw_vec.size() * sizeof(float), &required, &raw_fp);
  Verdict(s == SEMB_OK, "C53 raw semb_encode_query", Name(s));
  if (s == SEMB_OK) {
    Verdict(raw_vec.size() == checked_vec.size() &&
                std::memcmp(raw_vec.data(), checked_vec.data(), raw_vec.size() * sizeof(float)) == 0,
            "C53 vector bit-identical to checked query_encode",
            "byte comparison over " + std::to_string(raw_vec.size() * 4) + " bytes");
    semb_fingerprint enc_fp{}; enc_fp.struct_size = sizeof(enc_fp);
    s = semb_fingerprint_of(enc, &enc_fp);
    Verdict(s == SEMB_OK && std::memcmp(raw_fp.digest, enc_fp.digest, sizeof(enc_fp.digest)) == 0,
            "C53 raw fingerprint equals semb_fingerprint_of",
            HexBytes(raw_fp.digest, 32) + " vs " + HexBytes(enc_fp.digest, 32));
  }
  semb_query_close(q);
  semb_bank_close(bank);
  semb_encoder_close(enc);
}

// -----------------------------------------------------------------------
// C55 -- the empty-text extreme (TE-321). Self-contained: needs no
// external tokenizer, per the plan's own "0 by construction" argument.
// -----------------------------------------------------------------------
void CellC55EmptyText(const Args& a) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = a.model.data();
  cfg.model_path_len = a.model.size();
  cfg.tokenizer_path = a.tokenizer.data();
  cfg.tokenizer_path_len = a.tokenizer.size();
  cfg.max_concurrency = 1;
  semb_encoder enc = nullptr;
  semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != SEMB_OK || !enc) { Verdict(false, "C55 (setup) open", Name(s)); return; }

  // TE-321's own feature-oracle cell: verified at source, needs no external
  // tokenizer (ComposeQuery("") is byte-identical to kQueryPrefix, so the
  // composed length equals the prefix's own length and their difference is
  // 0 by construction, per this file's own header comment and the plan's
  // sec 10 M20 text). This suite's own signature choice (semb_encoder, not
  // SembInterimEncoder*) is documented in te331_u2_abi_contract.h.
  int64_t body_tokens = -1;
  const SembInterimStatus ts = semb_interim_query_token_count(enc, "", 0, &body_tokens);
  Verdict(ts == kSembInterimOk && body_tokens == 0, "C55 empty-text: token count is exactly 0",
          "status=" + std::to_string(static_cast<int>(ts)) + " body_tokens=" + std::to_string(body_tokens));

  // Non-empty text: reported, not graded (the general case needs an
  // independent tokenization of ComposeQuery(text) run outside the library
  // under test, per the plan's own Proof text -- owed to the builder/
  // Mendeleev's coverage pass, named in the Curie record).
  const std::string real_text = "a real query text, for informational reporting only";
  int64_t real_tokens = -1;
  const SembInterimStatus ts2 = semb_interim_query_token_count(enc, real_text.data(), real_text.size(),
                                                                &real_tokens);
  Info("C55 non-empty text (informational, no independent oracle wired)",
       "status=" + std::to_string(static_cast<int>(ts2)) + " body_tokens=" + std::to_string(real_tokens));
  semb_encoder_close(enc);
}

// -----------------------------------------------------------------------
// C57 -- informational call only, this round (see file header comment).
// -----------------------------------------------------------------------
void CellC57Informational() {
  SembInterimCertificationVerdict verdict{};
  verdict.struct_size = sizeof(verdict);
  const char* engine_status_name = nullptr;
  const SembInterimStatus s = semb_interim_certification_verdict(&verdict, &engine_status_name);
  if (s == kSembInterimOk) {
    Info("C57 verdict", std::string("os=") + verdict.os + " arch=" + verdict.arch +
                            " toolchain=" + verdict.compiler_id + " " + verdict.compiler_version +
                            " dispatch=" + verdict.dispatch + " dispatched_tier=" + verdict.dispatched_tier +
                            " certified_cell=" + verdict.certified_cell);
  } else if (s == kSembInterimEngineRefused) {
    Info("C57 verdict", std::string("kSembInterimEngineRefused: ") +
                            (engine_status_name ? engine_status_name : "<NULL>"));
  } else {
    Info("C57 verdict", "status=" + std::to_string(static_cast<int>(s)));
  }
  Info("C57 own matrix", "owed to the builder: needs U2-3 items 1/9/13/14 (the cell-form list, the "
                         "identity file, CheckLinkedEngine) to exist; the adversary's own mismatched-"
                         "engine constructions (Claude/Loki/te301-probe, te313-probe) are the "
                         "commissioning inputs, not fixtures this seat duplicates into product test "
                         "source");
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.scratch.empty()) {
    std::fprintf(stderr, "usage: %s --model <.sslm> --tokenizer <.sslm> --scratch <dir>\n", argv[0]);
    return 2;
  }
  fs::create_directories(a.scratch);
  CellC52MemoryEqualsPath(a);
  CellC53RawEqualsChecked(a);
  CellC55EmptyText(a);
  CellC57Informational();
  std::printf("TOTAL cells=%d failures=%d\n", g_cells, g_failures);
  return g_failures == 0 ? 0 : 1;
}
