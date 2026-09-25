// tests/consumer/main.cpp -- TE-331 (U2-1 red suite): the out-of-tree
// consumer's own program. Opens an encoder from the installed package,
// encodes one string, checks the dimension and prints the descriptor line
// (once U2-1's `semb --version`-equivalent surface exists on the library
// side; today this is exactly the frozen `semb_encoder_dims` and
// `semb_fingerprint_of` verbs, already public at fca421b, so the ONLY
// thing this program actually exercises that is new is whether it can be
// built and linked against an INSTALLED package at all).
//
// USAGE: te331_consumer <model.sslm> <tokenizer.sslm>
#include <cstdio>
#include <string>
#include <vector>

#include "superembedder/semb.h"

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
  if (status != SEMB_OK || !enc) {
    std::fprintf(stderr, "semb_encoder_open failed: %s\n", semb_status_name(status));
    return 1;
  }

  uint32_t dims = 0;
  status = semb_encoder_dims(enc, &dims);
  if (status != SEMB_OK || dims == 0) {
    std::fprintf(stderr, "semb_encoder_dims failed or zero: %s (%u)\n", semb_status_name(status), dims);
    semb_encoder_close(enc);
    return 1;
  }

  const std::string text = "an out-of-tree consumer, built against an installed package";
  std::vector<float> vec(dims);
  size_t required = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  status = semb_encode(enc, text.data(), text.size(), vec.data(), vec.size() * sizeof(float), &required, &fp);
  if (status != SEMB_OK) {
    std::fprintf(stderr, "semb_encode failed: %s\n", semb_status_name(status));
    semb_encoder_close(enc);
    return 1;
  }

  std::printf("OK dims=%u fingerprint=", dims);
  for (int i = 0; i < 32; ++i) std::printf("%02x", fp.digest[i]);
  std::printf("\n");
  semb_encoder_close(enc);
  return 0;
}
