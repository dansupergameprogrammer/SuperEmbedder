// TE-120: independent prerequisite executable, linked to the engine alone.
// No production encode result supplies any reference token or boundary count.
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "superslm/artifact.h"
#include "superslm/model.h"
#include "superslm/tokenizer.h"

namespace {
void Require(bool ok, const std::string& why) {
  if (!ok) throw std::runtime_error("REAL_INPUT_SETUP: " + why);
}
std::vector<uint8_t> Read(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  Require(f.good(), "missing file " + path);
  return {std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>()};
}
void LoadTokenizer(const char* path, superslm::SslmArtifact& artifact, superslm::TokenizerView& view) {
  superslm::SslmError error;
  const auto status = superslm::SslmArtifact::OpenFromFile(path, artifact, &error);
  Require(status == superslm::SslmStatus::Ok, "artifact loader " + std::string(superslm::SslmStatusName(status)) + ": " + error.message);
  std::string message;
  Require(superslm::TokenizerView::Open(artifact, view, &message), "tokenizer loader: " + message);
}
}

int main(int argc, char** argv) {
  if (argc != 5) {
    std::fprintf(stderr, "usage: u1_real_input_probe model tokenizer foreign-tokenizer fixture-directory\n");
    return 2;
  }
  try {
    const auto bytes = Read(argv[1]);
    superslm::SslmModelView model;
    std::string error;
    const auto status = superslm::SslmModel::Load(bytes.data(), bytes.size(), model, &error);
    Require(status == superslm::SslmModelStatus::Ok, "model loader: " + error);
    const auto& cfg = model.config;
    Require(cfg.context_cap == 32768 && cfg.vocab_size == 151669 && cfg.hidden_size == 1024,
            "real model geometry differs: cap=" + std::to_string(cfg.context_cap) + " vocab=" + std::to_string(cfg.vocab_size) + " hidden=" + std::to_string(cfg.hidden_size));
    const size_t workspace = size_t(cfg.num_hidden_layers) * cfg.context_cap * cfg.num_key_value_heads * cfg.head_dim * 2;
    std::printf("[PASS] REAL_INPUT_SETUP model loaded: vocab=%u cap=%u hidden=%u layers=%u heads=%u kv_heads=%u head_dim=%u intermediate=%u kv_workspace_bytes=%zu\n",
                cfg.vocab_size, cfg.context_cap, cfg.hidden_size, cfg.num_hidden_layers, cfg.num_attention_heads,
                cfg.num_key_value_heads, cfg.head_dim, cfg.intermediate_size, workspace);
    superslm::SslmArtifact original_artifact, foreign_artifact;
    superslm::TokenizerView original, foreign;
    LoadTokenizer(argv[2], original_artifact, original);
    LoadTokenizer(argv[3], foreign_artifact, foreign);
    Require(original.VocabSize() <= static_cast<int32_t>(cfg.vocab_size), "matching tokenizer exceeds model vocabulary");
    Require(foreign.VocabSize() == static_cast<int32_t>(cfg.vocab_size + 1), "foreign tokenizer does not exceed model vocabulary by one");
    const std::vector<int32_t> end{151643};
    Require(original.Encode("<|endoftext|>") == end && foreign.Encode("<|endoftext|>") == end, "terminator resolution differs");
    Require(original.Encode("<|im_end|>") == std::vector<int32_t>{151645}, "matching special differs");
    Require(foreign.Encode("<|im_end|>") == std::vector<int32_t>{static_cast<int32_t>(cfg.vocab_size)}, "foreign special is not a reachable out-of-range ID");
    std::printf("[PASS] REAL_INPUT_SETUP tokenizers loaded: matching_vocab=%d foreign_vocab=%d terminator=151643 foreign_special_id=%u\n",
                original.VocabSize(), foreign.VocabSize(), cfg.vocab_size);
    for (const char* name : {"at-cap", "over-cap"}) {
      const size_t count = std::strcmp(name, "at-cap") == 0 ? 32767 : 32768;
      const std::string prefix = std::string(argv[4]) + "/" + name;
      const auto text = Read(prefix + ".utf8");
      const auto ids = Read(prefix + ".ids");
      Require(ids.size() == count * 4 && text.size() == count * 2 - 1, std::string(name) + " reference size differs");
      const auto encoded = original.Encode(std::string_view(reinterpret_cast<const char*>(text.data()), text.size()));
      Require(encoded.size() == count, std::string(name) + " actual content count differs");
      for (size_t i = 0; i < count; ++i) {
        const uint32_t id = uint32_t(ids[i * 4]) | (uint32_t(ids[i * 4 + 1]) << 8) |
                            (uint32_t(ids[i * 4 + 2]) << 16) | (uint32_t(ids[i * 4 + 3]) << 24);
        Require(id == (i == 0 ? 64u : 264u) && encoded[i] == static_cast<int32_t>(id), std::string(name) + " reference ID differs at " + std::to_string(i));
      }
      std::printf("[PASS] REAL_INPUT_SETUP %s: content_ids=%zu total_positions=%zu every HF reference ID agrees\n", name, count, count + 1);
    }
    auto invalid = Read(std::string(argv[4]) + "/over-cap-invalid.utf8");
    auto over = Read(std::string(argv[4]) + "/over-cap.utf8");
    over.push_back(0xFF);
    Require(over == invalid, "invalid UTF-8 precedence crossing differs");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "[FAIL] %s\n", error.what());
    return 2;
  }
}
