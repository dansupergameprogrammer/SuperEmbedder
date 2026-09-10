#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#include "superembedder/semb.h"
#include "semb_bake_abi_contract.h"

int main(int argc, char** argv) {
  if (argc != 4) return 2;
  const std::string model = argv[1], tokenizer = argv[2], stem = argv[3];
  semb_config config{};
  config.struct_size = sizeof(config); config.model_path = model.data(); config.model_path_len = model.size();
  config.tokenizer_path = tokenizer.data(); config.tokenizer_path_len = tokenizer.size(); config.max_concurrency = 1;
  semb_encoder encoder = nullptr;
  if (semb_encoder_open(&config, &encoder) != SEMB_OK) return 3;
  const char id[] = "c17", text[] = "short C17 probe bank document";
  semb_document document{};
  document.struct_size = sizeof(document); document.id = id; document.id_len = sizeof(id) - 1;
  document.utf8 = text; document.utf8_len = sizeof(text) - 1;
  if (semb_bake_to_path(encoder, &document, 1, stem.c_str(), stem.size()) != SEMB_OK) return 4;
  semb_bank bank = nullptr;
  if (semb_bank_open(stem.c_str(), stem.size(), &bank) != SEMB_OK) return 5;
  semb_query query = nullptr;
  if (semb_query_open(encoder, bank, &query) != SEMB_OK) return 6;
  uint32_t dims = 0;
  if (semb_encoder_dims(encoder, &dims) != SEMB_OK) return 7;
  std::vector<uint8_t> storage(static_cast<size_t>(dims) * sizeof(float) + 16);
  const uintptr_t raw = reinterpret_cast<uintptr_t>(storage.data());
  float* vector = reinterpret_cast<float*>((raw + 15) & ~uintptr_t(15));
  size_t required = 0;
  constexpr char kQuery[] = "temperature";
  if (semb_query_encode(query, kQuery, sizeof(kQuery) - 1, vector,
                        static_cast<size_t>(dims) * sizeof(float), &required) != SEMB_OK) return 8;
  static constexpr char kHex[] = "0123456789abcdef";
  std::string vector_hex;
  for (size_t i = 0; i < required; ++i) {
    const uint8_t byte = reinterpret_cast<uint8_t*>(vector)[i];
    vector_hex += kHex[byte >> 4]; vector_hex += kHex[byte & 15];
  }
  semb_fingerprint fingerprint{};
  fingerprint.struct_size = sizeof(fingerprint);
  if (semb_fingerprint_of(encoder, &fingerprint) != SEMB_OK) return 9;
  std::string fingerprint_hex;
  for (uint8_t byte : fingerprint.digest) { fingerprint_hex += kHex[byte >> 4]; fingerprint_hex += kHex[byte & 15]; }
  std::cout << "VECTOR_HEX=" << vector_hex << "\nFINGERPRINT=" << fingerprint_hex << "\n";
  semb_query_close(query); semb_bank_close(bank); semb_encoder_close(encoder);
  return 0;
}
