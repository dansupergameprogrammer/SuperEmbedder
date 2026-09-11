// TE-234 diagnostic: expose the exact product tokenizer output and PS-N endpoint
// for one already-composed UTF-8 input. The product's normal path tokenizes the
// input, appends its resolved <|endoftext|> id, runs the chunk-batched forward,
// selects that final position, applies final_norm, and dequantizes. This tool
// calls those same internal entries and adds no model arithmetic of its own.

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
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

void PrintIds(const char* name, const std::vector<int32_t>& ids) {
  std::printf("%s=[", name);
  for (size_t i = 0; i < ids.size(); ++i) {
    if (i) std::putchar(',');
    std::printf("%d", ids[i]);
  }
  std::puts("]");
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 6 || std::strcmp(argv[4], "--dump") != 0) {
    std::fprintf(stderr,
                 "usage: %s <model.sslm> <tokenizer.sslm> <composed-text> --dump <vector.bin>\n",
                 argv[0]);
    return 2;
  }

  std::vector<uint8_t> tokenizer_bytes;
  if (!ReadFile(argv[2], &tokenizer_bytes)) {
    std::fprintf(stderr, "tokenizer read failed\n");
    return 1;
  }
  superslm::SslmArtifact tokenizer_artifact;
  superslm::SslmError artifact_error;
  if (superslm::SslmArtifact::OpenFromMemory(tokenizer_bytes.data(), tokenizer_bytes.size(),
                                              tokenizer_artifact, &artifact_error) !=
      superslm::SslmStatus::Ok) {
    std::fprintf(stderr, "tokenizer artifact open failed: %s\n", artifact_error.message.c_str());
    return 1;
  }
  superslm::TokenizerView tokenizer;
  std::string tokenizer_error;
  if (!superslm::TokenizerView::Open(tokenizer_artifact, tokenizer, &tokenizer_error)) {
    std::fprintf(stderr, "tokenizer view open failed: %s\n", tokenizer_error.c_str());
    return 1;
  }

  const std::string composed = argv[3];
  const std::vector<int32_t> content_ids = tokenizer.Encode(composed);
  std::vector<int32_t> full_ids = content_ids;
  full_ids.push_back(kSembPsNAppendedTokenId);

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
    std::fprintf(stderr, "geometry failed: status=%d\n", static_cast<int>(status));
    semb_interim_encoder_close(encoder);
    return 1;
  }

  const size_t positions = full_ids.size();
  std::vector<int8_t> codes(positions * geometry.hidden_size);
  std::vector<int64_t> m(positions), e(positions);
  size_t positions_written = 0;
  status = semb_interim_encode_seam(
      encoder, content_ids.data(), content_ids.size(), 0, kSembForwardLegChunkBatched,
      codes.data(), codes.size(), m.data(), e.data(), m.size(), &positions_written,
      &engine_status);
  if (status != kSembInterimOk || positions_written != positions) {
    std::fprintf(stderr, "seam failed: status=%d positions=%zu expected=%zu engine=%s\n",
                 static_cast<int>(status), positions_written, positions,
                 engine_status ? engine_status : "<null>");
    semb_interim_encoder_close(encoder);
    return 1;
  }

  std::vector<int8_t> final_codes(geometry.hidden_size);
  int64_t final_m = 0, final_e = 0;
  status = semb_interim_ps_n_select(encoder, codes.data(), m.data(), e.data(), positions,
                                    positions - 1, final_codes.data(), &final_m, &final_e,
                                    &engine_status);
  if (status != kSembInterimOk) {
    std::fprintf(stderr, "final norm selection failed: status=%d engine=%s\n",
                 static_cast<int>(status), engine_status ? engine_status : "<null>");
    semb_interim_encoder_close(encoder);
    return 1;
  }

  std::vector<float> vector(geometry.hidden_size);
  const SembWaPoolStatus pool_status = semb_ps_n_dequantize(
      final_codes.data(), final_m, final_e, final_codes.size(), vector.data());
  semb_interim_encoder_close(encoder);
  if (pool_status != kSembOk) {
    std::fprintf(stderr, "dequantize failed: status=%d\n", static_cast<int>(pool_status));
    return 1;
  }

  std::ofstream dump(argv[5], std::ios::binary | std::ios::trunc);
  dump.write(reinterpret_cast<const char*>(vector.data()),
             static_cast<std::streamsize>(vector.size() * sizeof(float)));
  if (!dump) {
    std::fprintf(stderr, "vector dump failed\n");
    return 1;
  }

  const std::string prenorm_path = std::string(argv[5]) + ".prenorm.bin";
  std::ofstream prenorm(prenorm_path, std::ios::binary | std::ios::trunc);
  prenorm.write(reinterpret_cast<const char*>(&m.back()), sizeof(m.back()));
  prenorm.write(reinterpret_cast<const char*>(&e.back()), sizeof(e.back()));
  prenorm.write(reinterpret_cast<const char*>(codes.data() + (positions - 1) * geometry.hidden_size),
                static_cast<std::streamsize>(geometry.hidden_size));
  if (!prenorm) {
    std::fprintf(stderr, "pre-final-norm dump failed\n");
    return 1;
  }

  std::printf("composed_utf8_hex=");
  for (unsigned char byte : composed) std::printf("%02x", static_cast<unsigned>(byte));
  std::putchar('\n');
  PrintIds("content_ids", content_ids);
  PrintIds("full_ids", full_ids);
  std::printf("positions=%zu\nhidden_size=%u\npooled_token_id=%d\nfinal_m=%lld\nfinal_e=%lld\n",
              positions, geometry.hidden_size, full_ids.back(),
              static_cast<long long>(final_m), static_cast<long long>(final_e));
  return 0;
}
