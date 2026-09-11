// TE-234 diagnostic: tokenize length-prefixed UTF-8 strings through the
// converter-emitted SuperSLM tokenizer. Input records are little-endian u64
// byte length followed by that many bytes. One JSON integer array is written
// per record; the product-appended end token is included.

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <fcntl.h>
#include <io.h>
#include <iostream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include "superembedder/encoder_interim_abi.h"
#include "superslm/artifact.h"
#include "superslm/tokenizer.h"

namespace {

bool ReadFile(const char* path, std::vector<uint8_t>* out) {
  std::ifstream in(path, std::ios::binary | std::ios::ate);
  if (!in) return false;
  const std::streamsize size = in.tellg();
  if (size < 0) return false;
  out->resize(static_cast<size_t>(size));
  in.seekg(0);
  return size == 0 || static_cast<bool>(in.read(reinterpret_cast<char*>(out->data()), size));
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::fprintf(stderr, "usage: %s <tokenizer.sslm> < length-prefixed-utf8\n", argv[0]);
    return 2;
  }
  if (_setmode(_fileno(stdin), _O_BINARY) == -1) return 1;
#ifdef _WIN32
  if (_setmode(_fileno(stdin), _O_BINARY) == -1) return 1;
#endif
  std::vector<uint8_t> bytes;
  if (!ReadFile(argv[1], &bytes)) return 1;
  superslm::SslmArtifact artifact;
  superslm::SslmError artifact_error;
  if (superslm::SslmArtifact::OpenFromMemory(bytes.data(), bytes.size(), artifact,
                                              &artifact_error) != superslm::SslmStatus::Ok) {
    std::fprintf(stderr, "%s\n", artifact_error.message.c_str());
    return 1;
  }
  superslm::TokenizerView tokenizer;
  std::string error;
  if (!superslm::TokenizerView::Open(artifact, tokenizer, &error)) {
    std::fprintf(stderr, "%s\n", error.c_str());
    return 1;
  }
  for (;;) {
    uint64_t size = 0;
    std::cin.read(reinterpret_cast<char*>(&size), sizeof(size));
    if (std::cin.eof() && std::cin.gcount() == 0) break;
    if (!std::cin || size > (UINT64_C(1) << 30)) return 1;
    std::string text(static_cast<size_t>(size), '\0');
    if (size > 0) std::cin.read(text.data(), static_cast<std::streamsize>(size));
    if (!std::cin) return 1;
    std::vector<int32_t> ids = tokenizer.Encode(text);
    ids.push_back(kSembPsNAppendedTokenId);
    std::putchar('[');
    for (size_t i = 0; i < ids.size(); ++i) {
      if (i) std::putchar(',');
      std::printf("%d", ids[i]);
    }
    std::puts("]");
  }
  return 0;
}
