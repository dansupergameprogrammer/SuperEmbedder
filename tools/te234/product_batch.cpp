// TE-234 diagnostic: run length-prefixed, already-composed UTF-8 inputs through
// the product's tokenizer -> append-EOS -> PS-N endpoint on one opened model.
// The output is consecutive hidden_size-wide float32 vectors.

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <fcntl.h>
#include <io.h>
#include <iostream>
#include <string>
#include <vector>

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
  if (argc != 4) {
    std::fprintf(stderr,
                 "usage: %s <model.sslm> <tokenizer.sslm> <vectors.bin> < length-prefixed-utf8\n",
                 argv[0]);
    return 2;
  }
  if (_setmode(_fileno(stdin), _O_BINARY) == -1) return 1;

  std::vector<uint8_t> tokenizer_bytes;
  if (!ReadFile(argv[2], &tokenizer_bytes)) return 1;
  superslm::SslmArtifact tokenizer_artifact;
  superslm::SslmError artifact_error;
  if (superslm::SslmArtifact::OpenFromMemory(tokenizer_bytes.data(), tokenizer_bytes.size(),
                                              tokenizer_artifact, &artifact_error) !=
      superslm::SslmStatus::Ok) {
    std::fprintf(stderr, "%s\n", artifact_error.message.c_str());
    return 1;
  }
  superslm::TokenizerView tokenizer;
  std::string tokenizer_error;
  if (!superslm::TokenizerView::Open(tokenizer_artifact, tokenizer, &tokenizer_error)) {
    std::fprintf(stderr, "%s\n", tokenizer_error.c_str());
    return 1;
  }

  SembInterimEncoder* encoder = nullptr;
  const char* engine_status = nullptr;
  SembInterimStatus status = semb_interim_encoder_open(
      argv[1], kSembPsNAppendedTokenId, &encoder, &engine_status);
  if (status != kSembInterimOk) {
    std::fprintf(stderr, "encoder open failed: status=%d engine=%s\n", static_cast<int>(status),
                 engine_status ? engine_status : "<null>");
    return 1;
  }
  SembInterimGeometry geometry{};
  geometry.struct_size = sizeof(geometry);
  status = semb_interim_encoder_geometry(encoder, &geometry);
  if (status != kSembInterimOk) {
    semb_interim_encoder_close(encoder);
    return 1;
  }

  std::ofstream output(argv[3], std::ios::binary | std::ios::trunc);
  if (!output) {
    semb_interim_encoder_close(encoder);
    return 1;
  }
  std::vector<float> vector(geometry.hidden_size);
  size_t count = 0;
  for (;;) {
    uint64_t byte_count = 0;
    std::cin.read(reinterpret_cast<char*>(&byte_count), sizeof(byte_count));
    if (std::cin.eof() && std::cin.gcount() == 0) break;
    if (!std::cin || byte_count > (UINT64_C(1) << 30)) {
      semb_interim_encoder_close(encoder);
      return 1;
    }
    std::string text(static_cast<size_t>(byte_count), '\0');
    if (byte_count > 0) {
      std::cin.read(text.data(), static_cast<std::streamsize>(byte_count));
    }
    if (!std::cin) {
      semb_interim_encoder_close(encoder);
      return 1;
    }
    const std::vector<int32_t> ids = tokenizer.Encode(text);
    size_t required = 0;
    SembWaPoolStatus pool_status = kSembOk;
    status = semb_interim_encode_ps_n(
        encoder, ids.data(), ids.size(), 0, vector.data(),
        vector.size() * sizeof(float), &required, &pool_status, &engine_status);
    if (status != kSembInterimOk || required != vector.size() * sizeof(float)) {
      std::fprintf(stderr,
                   "encode failed at record %zu: status=%d pool=%d required=%zu engine=%s\n",
                   count, static_cast<int>(status), static_cast<int>(pool_status), required,
                   engine_status ? engine_status : "<null>");
      semb_interim_encoder_close(encoder);
      return 1;
    }
    output.write(reinterpret_cast<const char*>(vector.data()),
                 static_cast<std::streamsize>(vector.size() * sizeof(float)));
    if (!output) {
      semb_interim_encoder_close(encoder);
      return 1;
    }
    ++count;
    if (count % 50 == 0) std::fprintf(stderr, "encoded=%zu\n", count);
  }
  semb_interim_encoder_close(encoder);
  std::printf("vectors=%zu hidden_size=%u\n", count, geometry.hidden_size);
  return 0;
}
