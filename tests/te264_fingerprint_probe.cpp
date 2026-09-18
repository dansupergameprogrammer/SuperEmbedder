// tests/te264_fingerprint_probe.cpp -- TE-264, U1 Slice 7 steps 3-5: one
// encoder handle reports the two ABI fingerprint values and bakes a bank,
// so tests/te264_fingerprint_final_check.py can compare the ABI values and
// the manifest's clear components against oracles typed from the plan and
// read from repository files.
//
// Output (stdout), one line each, lowercase hex:
//   FINGERPRINT_OF=<64 hex>     semb_fingerprint_of(enc)
//   ENCODE_FINGERPRINT=<64 hex> the fingerprint semb_encode returns
//   BAKE_STEM=<stem>            semb_bake_to_path(enc, <two documents>, stem)
// A refusal prints `<verb>: <status> (<ordinal>)` on stderr and exits 1.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --stem <path stem>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "superembedder/bake_abi.h"
#include "superembedder/semb.h"

namespace {
const char* Value(int argc, char** argv, const char* key) {
  for (int i = 1; i + 1 < argc; ++i)
    if (std::strcmp(argv[i], key) == 0) return argv[i + 1];
  return nullptr;
}
int Refuse(const char* where, semb_status s) {
  std::fprintf(stderr, "%s: %s (%d)\n", where, semb_status_name(s), static_cast<int>(s));
  return 1;
}
void PrintHex(const char* key, const uint8_t* d, size_t n) {
  std::printf("%s=", key);
  for (size_t i = 0; i < n; ++i) std::printf("%02x", d[i]);
  std::printf("\n");
}
}  // namespace

int main(int argc, char** argv) {
  const char* model = Value(argc, argv, "--model");
  const char* tokenizer = Value(argc, argv, "--tokenizer");
  const char* stem = Value(argc, argv, "--stem");
  if (!model || !tokenizer || !stem) {
    std::fputs("usage: --model M --tokenizer T --stem S\n", stderr);
    return 2;
  }
  semb_config cfg{sizeof(cfg), model, std::strlen(model), tokenizer, std::strlen(tokenizer), 1};
  semb_encoder enc = nullptr;
  semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != SEMB_OK) return Refuse("semb_encoder_open", s);

  semb_fingerprint of{};
  of.struct_size = sizeof(of);
  s = semb_fingerprint_of(enc, &of);
  if (s != SEMB_OK) { semb_encoder_close(enc); return Refuse("semb_fingerprint_of", s); }
  PrintHex("FINGERPRINT_OF", of.digest, sizeof(of.digest));

  uint32_t dims = 0;
  s = semb_encoder_dims(enc, &dims);
  if (s != SEMB_OK) { semb_encoder_close(enc); return Refuse("semb_encoder_dims", s); }
  std::vector<float> storage(static_cast<size_t>(dims) + 4);
  float* vector = reinterpret_cast<float*>((reinterpret_cast<uintptr_t>(storage.data()) + 15) & ~uintptr_t(15));
  size_t required = 0;
  semb_fingerprint raw{};
  raw.struct_size = sizeof(raw);
  const char text[] = "te264 fingerprint probe";
  s = semb_encode(enc, text, sizeof(text) - 1, vector, static_cast<size_t>(dims) * sizeof(float), &required, &raw);
  if (s != SEMB_OK) { semb_encoder_close(enc); return Refuse("semb_encode", s); }
  PrintHex("ENCODE_FINGERPRINT", raw.digest, sizeof(raw.digest));

  const std::string ids[2] = {"te264-a", "te264-b"};
  const std::string texts[2] = {"a short probe document", "another probe document"};
  semb_document docs[2];
  for (int i = 0; i < 2; ++i)
    docs[i] = semb_document{sizeof(semb_document), ids[i].data(), ids[i].size(), texts[i].data(), texts[i].size()};
  s = semb_bake_to_path(enc, docs, 2, stem, std::strlen(stem));
  if (s != SEMB_OK) { semb_encoder_close(enc); return Refuse("semb_bake_to_path", s); }
  std::printf("BAKE_STEM=%s\n", stem);
  s = semb_encoder_close(enc);
  if (s != SEMB_OK) return Refuse("semb_encoder_close", s);
  return 0;
}
