// TE-93: executable contract cells for the U1 public batch encoder slice.
#include "semb_batch_abi_contract.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace {

int failures = 0;
int cells = 0;

void Check(bool ok, const char* cell, const std::string& observed) {
  ++cells;
  if (!ok) ++failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell,
              observed.c_str());
}

struct Args {
  std::string model;
  std::string tokenizer;
  int32_t append_id = -1;
  uint32_t expected_dims = 0;
  uint32_t context_cap = 0;
};

bool Parse(int argc, char** argv, Args* out) {
  for (int i = 1; i < argc; ++i) {
    if (i + 1 >= argc) return false;
    const std::string key = argv[i++];
    const std::string value = argv[i];
    if (key == "--model") out->model = value;
    else if (key == "--tokenizer") out->tokenizer = value;
    else if (key == "--append-id") out->append_id = std::stoi(value);
    else if (key == "--dims") out->expected_dims =
        static_cast<uint32_t>(std::stoul(value));
    else if (key == "--context-cap") out->context_cap =
        static_cast<uint32_t>(std::stoul(value));
    else return false;
  }
  return !out->model.empty() && !out->tokenizer.empty() &&
         out->append_id >= 0 && out->expected_dims != 0;
}

semb_config Config(const Args& a) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = a.model.data();
  cfg.model_path_len = a.model.size();
  cfg.tokenizer_path = a.tokenizer.data();
  cfg.tokenizer_path_len = a.tokenizer.size();
  cfg.appended_token_id = a.append_id;
  cfg.max_concurrency = 2;
  return cfg;
}

semb_encoder Open(const Args& a) {
  semb_encoder enc = nullptr;
  semb_config cfg = Config(a);
  const semb_status status = semb_encoder_open(&cfg, &enc);
  Check(status == SEMB_OK && enc != nullptr, "B-00 open fixture pair",
        semb_status_name(status));
  return enc;
}

struct AlignedBuffer {
  explicit AlignedBuffer(size_t size, uint8_t fill = 0xA5)
      : storage(size + 31, fill), logical_size(size), fill_byte(fill) {
    const uintptr_t raw = reinterpret_cast<uintptr_t>(storage.data());
    data = reinterpret_cast<uint8_t*>((raw + 15u) & ~uintptr_t{15u});
  }
  float* Floats() { return reinterpret_cast<float*>(data); }
  bool Untouched(size_t begin = 0, size_t end = std::numeric_limits<size_t>::max()) const {
    end = std::min(end, logical_size);
    return std::all_of(data + begin, data + end,
                       [this](uint8_t value) { return value == fill_byte; });
  }
  std::vector<uint8_t> storage;
  uint8_t* data = nullptr;
  size_t logical_size = 0;
  uint8_t fill_byte = 0;
};

semb_document Doc(const std::string& id, const std::string& text) {
  return {sizeof(semb_document), id.data(), id.size(), text.data(), text.size()};
}

bool RawRow(semb_encoder enc, const std::string& text, float* out,
            size_t row_bytes) {
  size_t required = 0;
  semb_fingerprint fingerprint{};
  fingerprint.struct_size = sizeof(fingerprint);
  return semb_encode(enc, text.data(), text.size(), out, row_bytes, &required,
                     &fingerprint) == SEMB_OK && required == row_bytes;
}

}  // namespace

int main(int argc, char** argv) {
  Args args;
  if (!Parse(argc, argv, &args)) {
    std::fprintf(stderr, "usage: %s --model P --tokenizer P --append-id N --dims N [--context-cap N]\n", argv[0]);
    return 2;
  }

  const int32_t buffer_too_small = BatchStatusByName("SEMB_BUFFER_TOO_SMALL");
  const int32_t misaligned = BatchStatusByName("SEMB_MISALIGNED_BUFFER");
  const int32_t null_argument = BatchStatusByName("SEMB_NULL_ARGUMENT");
  const int32_t struct_mismatch = BatchStatusByName("SEMB_STRUCT_SIZE_MISMATCH");
  const int32_t invalid_argument = BatchStatusByName("SEMB_INVALID_ARGUMENT");
  const int32_t invalid_utf8 = BatchStatusByName("SEMB_INVALID_UTF8");
  const int32_t input_empty = BatchStatusByName("SEMB_INPUT_EMPTY");
  const int32_t context_exceeded = BatchStatusByName("SEMB_CONTEXT_CAP_EXCEEDED");
  const int32_t corpus_empty = BatchStatusByName("SEMB_CORPUS_EMPTY");
  const int32_t invalid_handle = BatchStatusByName("SEMB_INVALID_HANDLE");
  Check(buffer_too_small >= 0 && misaligned >= 0 && null_argument >= 0 &&
            struct_mismatch >= 0 && invalid_argument >= 0 && invalid_utf8 >= 0 &&
            input_empty >= 0 && context_exceeded >= 0 && corpus_empty >= 0 &&
            invalid_handle >= 0,
        "B-01 reachable status vocabulary is named", "resolved by semb_status_name");

  semb_encoder enc = Open(args);
  if (!enc) return 1;
  uint32_t dims = 0;
  const semb_status dims_status = semb_encoder_dims(enc, &dims);
  Check(dims_status == SEMB_OK && dims == args.expected_dims,
        "B-02 dimensions come from the opened artifact", std::to_string(dims));
  const size_t row_bytes = static_cast<size_t>(dims) * sizeof(float);

  std::array<std::string, 3> ids = {"doc-c", "doc-a", "doc-b"};
  std::array<std::string, 3> texts = {
      "third input row", "a", "second input row with punctuation!"};
  std::array<semb_document, 3> docs = {
      Doc(ids[0], texts[0]), Doc(ids[1], texts[1]), Doc(ids[2], texts[2])};
  const size_t required_all = docs.size() * row_bytes;
  size_t required = 0xC5C5C5C5u;

  semb_status status = semb_encode_batch(enc, docs.data(), docs.size(), nullptr,
                                         0, &required);
  Check(status == buffer_too_small && required == required_all,
        "B-03 query form returns n*dims*4", semb_status_name(status));

  AlignedBuffer short_buffer(required_all);
  required = 0;
  status = semb_encode_batch(enc, docs.data(), docs.size(), short_buffer.Floats(),
                             required_all - sizeof(float), &required);
  Check(status == buffer_too_small && required == required_all &&
            short_buffer.Untouched(),
        "B-04 short capacity reports size and writes no row bytes",
        semb_status_name(status));

  AlignedBuffer batch(required_all + 64);
  required = 0;
  status = semb_encode_batch(enc, docs.data(), docs.size(), batch.Floats(),
                             required_all + 64, &required);
  AlignedBuffer singles(required_all, 0x33);
  bool raw_ok = true;
  for (size_t i = 0; i < docs.size(); ++i) {
    raw_ok = RawRow(enc, texts[i], singles.Floats() + i * dims, row_bytes) && raw_ok;
  }
  Check(status == SEMB_OK && required == required_all && raw_ok &&
            std::memcmp(batch.data, singles.data, required_all) == 0 &&
            batch.Untouched(required_all, required_all + 64),
        "B-05 rows are contiguous, input-ordered, raw-path bit-identical, tail untouched",
        semb_status_name(status));

  AlignedBuffer malformed(required_all);
  auto bad_docs = docs;
  bad_docs[2].struct_size += 4;
  required = 0xC5C5C5C5u;
  status = semb_encode_batch(enc, bad_docs.data(), bad_docs.size(),
                             malformed.Floats(), required_all, &required);
  Check(status == struct_mismatch && required == 0xC5C5C5C5u && malformed.Untouched(),
        "B-06 a malformed later document is atomic", semb_status_name(status));

  AlignedBuffer duplicate(required_all);
  auto duplicate_docs = docs;
  std::string duplicate_storage = ids[0];
  duplicate_docs[2].id = duplicate_storage.data();
  duplicate_docs[2].id_len = duplicate_storage.size();
  status = semb_encode_batch(enc, duplicate_docs.data(), duplicate_docs.size(),
                             duplicate.Floats(), required_all, &required);
  Check(status == invalid_argument && duplicate.Untouched(),
        "B-07 byte-identical duplicate IDs are refused before forward",
        semb_status_name(status));

  AlignedBuffer invalid(required_all);
  const char bad_utf8[] = {static_cast<char>(0xED), static_cast<char>(0xA0),
                           static_cast<char>(0x80)};
  auto invalid_docs = docs;
  invalid_docs[1].utf8 = bad_utf8;
  invalid_docs[1].utf8_len = sizeof(bad_utf8);
  status = semb_encode_batch(enc, invalid_docs.data(), invalid_docs.size(),
                             invalid.Floats(), required_all, &required);
  Check(status == invalid_utf8 && invalid.Untouched(),
        "B-08 invalid UTF-8 in a later row is atomic", semb_status_name(status));

  auto empty_docs = docs;
  empty_docs[1].utf8_len = 0;
  status = semb_encode_batch(enc, empty_docs.data(), empty_docs.size(),
                             invalid.Floats(), required_all, &required);
  Check(status == input_empty && invalid.Untouched(),
        "B-09 an empty document is refused before forward", semb_status_name(status));

  if (args.context_cap > 0) {
    std::string over;
    over.reserve(args.context_cap);
    for (uint32_t i = 0; i < args.context_cap; ++i) over.push_back(i % 2 ? 'b' : 'a');
    auto over_docs = docs;
    over_docs[2] = Doc(ids[2], over);
    status = semb_encode_batch(enc, over_docs.data(), over_docs.size(),
                               invalid.Floats(), required_all, &required);
    Check(status == context_exceeded && invalid.Untouched(),
          "B-10 context_cap+1 positions in a later row is atomic",
          semb_status_name(status));
  }

  AlignedBuffer alignment(required_all + 16);
  float* off_by_four = reinterpret_cast<float*>(alignment.data + 4);
  status = semb_encode_batch(enc, docs.data(), docs.size(), off_by_four,
                             required_all, &required);
  Check(status == misaligned && alignment.Untouched(),
        "B-11 misalignment is refused before work", semb_status_name(status));

  required = 0xC5C5C5C5u;
  const semb_document one = docs[0];
  const size_t impossible_n = std::numeric_limits<size_t>::max() / row_bytes + 1;
  status = semb_encode_batch(enc, &one, impossible_n, nullptr, 0, &required);
  Check(status == invalid_argument && required == 0xC5C5C5C5u,
        "B-12 required-size multiplication overflow is refused",
        semb_status_name(status));

  status = semb_encode_batch(enc, docs.data(), 0, nullptr, 0, &required);
  Check(status == corpus_empty, "B-13 zero documents is SEMB_CORPUS_EMPTY",
        semb_status_name(status));

  status = semb_encode_batch(nullptr, docs.data(), docs.size(), batch.Floats(),
                             required_all, &required);
  const bool null_encoder = status == null_argument;
  status = semb_encode_batch(enc, nullptr, docs.size(), batch.Floats(),
                             required_all, &required);
  const bool null_docs = status == null_argument;
  status = semb_encode_batch(enc, docs.data(), docs.size(), batch.Floats(),
                             required_all, nullptr);
  Check(null_encoder && null_docs && status == null_argument,
        "B-14 required NULL pointers are refused", semb_status_name(status));

  status = semb_encoder_close(enc);
  const semb_status stale = semb_encode_batch(enc, docs.data(), docs.size(),
                                               batch.Floats(), required_all,
                                               &required);
  Check(status == SEMB_OK && stale == invalid_handle,
        "B-15 a closed encoder cookie cannot batch encode",
        semb_status_name(stale));

  std::printf("\nu1_batch_contract_test: %d cells, %d failures\n", cells, failures);
  return failures ? 1 : 0;
}
