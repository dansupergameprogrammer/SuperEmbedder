// Slice 6's library-side oracle for the CLI driver.  The driver bakes through
// `semb`, then this process independently opens the resulting bank and emits
// the shipping query bytes for one supplied text.  It deliberately calls the
// frozen library surface rather than sharing the CLI's parsing or output code.
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "superembedder/semb.h"

namespace {
const char* Value(int argc, char** argv, const char* key) {
  for (int i = 1; i + 1 < argc; ++i) if (std::strcmp(argv[i], key) == 0) return argv[i + 1];
  return nullptr;
}
void PrintStatus(const char* where, semb_status s) {
  std::fprintf(stderr, "%s: %s (%d)\n", where, semb_status_name(s), static_cast<int>(s));
}
}

int main(int argc, char** argv) {
  const char* model = Value(argc, argv, "--model");
  const char* tokenizer = Value(argc, argv, "--tokenizer");
  const char* stem = Value(argc, argv, "--stem");
  const char* text = Value(argc, argv, "--text");
  if (!model || !tokenizer || !stem || !text) {
    std::fputs("usage: --model M --tokenizer T --stem S --text Q\n", stderr); return 2;
  }
  semb_config cfg{sizeof(cfg), model, std::strlen(model), tokenizer, std::strlen(tokenizer), 1};
  semb_encoder enc = nullptr;
  semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != SEMB_OK) { PrintStatus("semb_encoder_open", s); return 1; }
  semb_bank bank = nullptr;
  s = semb_bank_open(stem, std::strlen(stem), &bank);
  if (s != SEMB_OK) { PrintStatus("semb_bank_open", s); semb_encoder_close(enc); return 1; }
  semb_query query = nullptr;
  s = semb_query_open(enc, bank, &query);
  if (s != SEMB_OK) { PrintStatus("semb_query_open", s); semb_bank_close(bank); semb_encoder_close(enc); return 1; }
  size_t required = 0;
  s = semb_query_encode(query, text, std::strlen(text), nullptr, 0, &required);
  if (s != SEMB_BUFFER_TOO_SMALL || required == 0) {
    PrintStatus("semb_query_encode(size)", s); semb_query_close(query); semb_bank_close(bank); semb_encoder_close(enc); return 1;
  }
  std::vector<float> vector(required / sizeof(float));
  s = semb_query_encode(query, text, std::strlen(text), vector.data(), required, &required);
  if (s != SEMB_OK) { PrintStatus("semb_query_encode(fill)", s); semb_query_close(query); semb_bank_close(bank); semb_encoder_close(enc); return 1; }
  const auto* bytes = reinterpret_cast<const unsigned char*>(vector.data());
  std::printf("VECTOR_HEX=");
  for (size_t i = 0; i < required; ++i) std::printf("%02x", bytes[i]);
  std::puts("");
  s = semb_query_close(query);
  if (s == SEMB_OK) s = semb_bank_close(bank);
  if (s == SEMB_OK) s = semb_encoder_close(enc);
  if (s != SEMB_OK) { PrintStatus("close", s); return 1; }
  return 0;
}
