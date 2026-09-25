// tests/consumer/main.cpp -- TE-331 (U2-1, U2-7): the out-of-tree consumer's
// own program, built against the INSTALLED package only.
//
// It opens an encoder by path, checks the dimension, encodes one string and
// checks the written size; opens a second encoder from the same bytes in
// memory (semb_encoder_open_memory, U2-7 item 1) and checks its fingerprint
// equals the path open's; and encodes one query through semb_encode_query
// (U2-7 item 2), checking the size and that its fingerprint equals the
// encoder's. Any failure prints the verb and status and exits 1.
//
// USAGE: te331_consumer <model.sslm> <tokenizer.sslm>
// OUTPUT (exit 0): OK dims=<n> fingerprint=<64 hex>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

#include "superembedder/semb.h"

namespace {
std::vector<uint8_t> ReadAll(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}
int Fail(const char* verb, semb_status s) {
  std::fprintf(stderr, "%s: %s\n", verb, semb_status_name(s));
  return 1;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::fprintf(stderr, "usage: %s <model.sslm> <tokenizer.sslm>\n", argv[0]);
    return 2;
  }
  const std::string model = argv[1];
  const std::string tokenizer = argv[2];

  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = model.data();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tokenizer.data();
  cfg.tokenizer_path_len = tokenizer.size();
  cfg.max_concurrency = 1;

  semb_encoder enc = nullptr;
  semb_status status = semb_encoder_open(&cfg, &enc);
  if (status != SEMB_OK || !enc) return Fail("semb_encoder_open", status);

  uint32_t dims = 0;
  status = semb_encoder_dims(enc, &dims);
  if (status != SEMB_OK || dims == 0) {
    std::fprintf(stderr, "semb_encoder_dims: %s (%u)\n", semb_status_name(status), dims);
    return 1;
  }

  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  status = semb_fingerprint_of(enc, &fp);
  if (status != SEMB_OK) return Fail("semb_fingerprint_of", status);

  const std::string text = "an out-of-tree consumer, built against an installed package";
  std::vector<float> vec(dims);
  size_t required = 0;
  semb_fingerprint efp{};
  efp.struct_size = sizeof(efp);
  status = semb_encode(enc, text.data(), text.size(), vec.data(), vec.size() * sizeof(float), &required, &efp);
  if (status != SEMB_OK) return Fail("semb_encode", status);
  if (required != dims * sizeof(float) || std::memcmp(efp.digest, fp.digest, sizeof(fp.digest)) != 0) {
    std::fprintf(stderr, "semb_encode: required %zu for %u dims, or its fingerprint differs\n", required, dims);
    return 1;
  }

  // U2-7 item 2: the query form of semb_encode.
  const std::string query = "what does a consumer link against?";
  std::vector<float> qvec(dims);
  size_t qrequired = 0;
  semb_fingerprint qfp{};
  qfp.struct_size = sizeof(qfp);
  status = semb_encode_query(enc, query.data(), query.size(), qvec.data(), qvec.size() * sizeof(float), &qrequired,
                             &qfp);
  if (status != SEMB_OK) return Fail("semb_encode_query", status);
  if (qrequired != dims * sizeof(float) || std::memcmp(qfp.digest, fp.digest, sizeof(fp.digest)) != 0) {
    std::fprintf(stderr, "semb_encode_query: required %zu for %u dims, or its fingerprint differs\n", qrequired,
                 dims);
    return 1;
  }

  // U2-7 item 1: the same artifacts from memory give the same fingerprint.
  const std::vector<uint8_t> model_bytes = ReadAll(model), tok_bytes = ReadAll(tokenizer);
  semb_memory_config mcfg{};
  mcfg.struct_size = sizeof(mcfg);
  mcfg.model_bytes = model_bytes.data();
  mcfg.model_len = model_bytes.size();
  mcfg.tokenizer_bytes = tok_bytes.data();
  mcfg.tokenizer_len = tok_bytes.size();
  mcfg.max_concurrency = 1;
  semb_encoder menc = nullptr;
  status = semb_encoder_open_memory(&mcfg, &menc);
  if (status != SEMB_OK || !menc) return Fail("semb_encoder_open_memory", status);
  semb_fingerprint mfp{};
  mfp.struct_size = sizeof(mfp);
  status = semb_fingerprint_of(menc, &mfp);
  if (status != SEMB_OK) return Fail("semb_fingerprint_of (memory open)", status);
  if (std::memcmp(mfp.digest, fp.digest, sizeof(fp.digest)) != 0) {
    std::fprintf(stderr, "semb_encoder_open_memory: its fingerprint differs from the path open's\n");
    return 1;
  }
  status = semb_encoder_close(menc);
  if (status != SEMB_OK) return Fail("semb_encoder_close (memory open)", status);

  std::printf("OK dims=%u fingerprint=", dims);
  for (int i = 0; i < 32; ++i) std::printf("%02x", fp.digest[i]);
  std::printf("\n");
  status = semb_encoder_close(enc);
  if (status != SEMB_OK) return Fail("semb_encoder_close", status);
  return 0;
}
