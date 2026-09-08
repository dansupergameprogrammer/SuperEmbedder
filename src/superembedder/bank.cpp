// src/superembedder/bank.cpp -- TE-166 (U1 slice 4): `semb_bank_open` /
// `semb_bank_close` (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1, sec 3.4,
// sec 8 C9/C18/C34; `tests/semb_bank_abi_contract.h` is the suite's own
// concrete pin). Opens and validates a `.wvbank.json`/`.wvbank.bin`/
// `.semb.json` triple per FORMAT.md sec 1's own importer obligations plus
// the manifest's own internal self-consistency (cell 3, reading (a),
// D-SLM6391: no encoder argument, no comparison to any encoder -- the
// handle's own fingerprint validity is checked entirely from the
// manifest's own clear-text fields).
#include "superembedder/semb.h"

#include <array>
#include <atomic>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "json_lite.h"
#include "superslm/sha256.h"

// Completes semb.h's own forward declaration (`typedef struct
// semb_bank_opaque* semb_bank;`, global scope) -- defined here at GLOBAL
// scope too, not inside the anonymous namespace below, so this is the
// SAME type the public header names rather than a second, unrelated type
// that happens to share the name (MSVC C2872 "ambiguous symbol" is the
// build's own proof the two would otherwise collide). No read accessor
// exists through an already-open handle at this slice (Slice 5's own
// semb_query_open reads rows; D-SLM6393 item 2) -- the handle exists to be
// closed and to have been validated; nothing else is stored.
struct semb_bank_opaque {};

namespace {

// FORMAT.md sec 1's own header-geometry ceilings, mirrored as compiled
// constants (the same convention SEMB_MAX_CORPUS_ROWS already uses in
// encoder.cpp for the batch verb's own row ceiling).
constexpr int64_t kMaxCrossDeviceDims = 131072;  // FORMAT.md: dims > 0 and <= 131,072
constexpr int64_t kMaxBankRows = int64_t{1} << 28;  // FORMAT.md: count >= 0 and <= 2^28

std::mutex& RegistryMutex() {
  static auto* mutex = new std::mutex();
  return *mutex;
}
using HandleRegistry = std::unordered_map<semb_bank, std::unique_ptr<semb_bank_opaque>>;
HandleRegistry& Registry() {
  static auto* registry = new HandleRegistry();
  return *registry;
}
bool AllocateHandleCookie(semb_bank* out) {
  static uintptr_t next = 1;
  if (next == 0) return false;
  *out = reinterpret_cast<semb_bank>(next++);
  return true;
}

bool ReadFileBytes(const std::string& path, std::string* out) {
  std::ifstream stream;
  stream.exceptions(std::ios::badbit);
  try {
    stream.open(path, std::ios::binary | std::ios::ate);
  } catch (const std::ios_base::failure&) {
    return false;
  }
  if (!stream) return false;
  const std::streamoff end = stream.tellg();
  if (end < 0) return false;
  out->resize(static_cast<size_t>(end));
  stream.seekg(0, std::ios::beg);
  if (!stream) return false;
  if (end == 0) return true;
  try {
    return static_cast<bool>(stream.read(out->data(), static_cast<std::streamsize>(end)));
  } catch (const std::ios_base::failure&) {
    return false;
  }
}

void Hash(const void* data, size_t size, uint8_t out[32]) {
  superslm::Sha256Hash(static_cast<const uint8_t*>(data), size, out);
}
void UpdateU64(superslm::Sha256* hash, uint64_t value) {
  uint8_t bytes[8];
  for (size_t i = 0; i < 8; ++i) bytes[i] = static_cast<uint8_t>(value >> (8 * i));
  hash->Update(bytes, sizeof(bytes));
}
void UpdateField(superslm::Sha256* hash, const std::vector<uint8_t>& field) {
  UpdateU64(hash, static_cast<uint64_t>(field.size()));
  hash->Update(field.data(), field.size());
}
std::string Hex(const uint8_t* d, size_t n) {
  static const char* kHexDigits = "0123456789abcdef";
  std::string out(n * 2, '0');
  for (size_t i = 0; i < n; ++i) {
    out[2 * i] = kHexDigits[(d[i] >> 4) & 0xF];
    out[2 * i + 1] = kHexDigits[d[i] & 0xF];
  }
  return out;
}
bool HexToBytes(const std::string& hex, std::vector<uint8_t>* out) {
  if (hex.size() % 2 != 0) return false;
  out->resize(hex.size() / 2);
  for (size_t i = 0; i < out->size(); ++i) {
    auto nibble = [](char c, int* v) -> bool {
      if (c >= '0' && c <= '9') { *v = c - '0'; return true; }
      if (c >= 'a' && c <= 'f') { *v = c - 'a' + 10; return true; }
      if (c >= 'A' && c <= 'F') { *v = c - 'A' + 10; return true; }
      return false;
    };
    int hi = 0, lo = 0;
    if (!nibble(hex[2 * i], &hi) || !nibble(hex[2 * i + 1], &lo)) return false;
    (*out)[i] = static_cast<uint8_t>((hi << 4) | lo);
  }
  return true;
}

}  // namespace

extern "C" semb_status semb_bank_open(const char* path, size_t path_len, semb_bank* out) {
  if (out) *out = nullptr;
  if ((!path && path_len > 0) || !out) return SEMB_NULL_ARGUMENT;
  if (!path || path_len == 0) return SEMB_ARTIFACT_UNREADABLE;

  try {
    const std::string stem(path, path_len);
    const std::string header_path = stem + ".wvbank.json";
    const std::string bin_path = stem + ".wvbank.bin";
    const std::string manifest_path = stem + ".semb.json";

    std::string header_text, bin_bytes, manifest_text;
    if (!ReadFileBytes(header_path, &header_text)) return SEMB_ARTIFACT_UNREADABLE;
    if (!ReadFileBytes(bin_path, &bin_bytes)) return SEMB_ARTIFACT_UNREADABLE;
    if (!ReadFileBytes(manifest_path, &manifest_text)) return SEMB_ARTIFACT_UNREADABLE;

    namespace js = semb::json;
    js::Value header, manifest;
    try {
      header = js::Parse(header_text);
      manifest = js::Parse(manifest_text);
    } catch (const std::exception&) {
      return SEMB_ARTIFACT_UNREADABLE;
    }
    if (!header.IsObject() || !manifest.IsObject()) return SEMB_ARTIFACT_UNREADABLE;

    // FORMAT.md sec 1: "schemaVersion ... Unknown versions are rejected."
    const js::Value* schema_version = header.Find("schemaVersion");
    if (!schema_version || schema_version->kind != js::Kind::kInt || schema_version->as_int != 1) {
      return SEMB_MANIFEST_SCHEMA_UNSUPPORTED;
    }

    const js::Value* dims_v = header.Find("dims");
    const js::Value* count_v = header.Find("count");
    if (!dims_v || dims_v->kind != js::Kind::kInt || !count_v || count_v->kind != js::Kind::kInt) {
      return SEMB_ARTIFACT_UNREADABLE;
    }
    const int64_t dims = dims_v->as_int;
    const int64_t count = count_v->as_int;

    // FORMAT.md sec 1: "header geometry over the format ceilings ...
    // rejected on the header fields alone, BEFORE any payload size is
    // computed from them." D-SLM6393 provisionally names this class
    // SEMB_BANK_GEOMETRY_CEILING_EXCEEDED (D-SLM6392).
    if (dims <= 0 || dims > kMaxCrossDeviceDims || count < 0 || count > kMaxBankRows) {
      return SEMB_BANK_GEOMETRY_CEILING_EXCEEDED;
    }

    const js::Value* metric_v = header.Find("metric");
    const js::Value* dtype_v = header.Find("dtype");
    if (!metric_v || !metric_v->IsString() || !dtype_v || !dtype_v->IsString()) {
      return SEMB_ARTIFACT_UNREADABLE;
    }

    // Payload size disagreeing with the header (checked AFTER the ceiling
    // check above, per FORMAT.md's own ordering, so the multiplication
    // below is over already-bounded operands).
    const uint64_t expected_bytes =
        static_cast<uint64_t>(count) * static_cast<uint64_t>(dims) * 4ull;
    if (static_cast<uint64_t>(bin_bytes.size()) != expected_bytes) {
      return SEMB_BANK_SIZE_MISMATCH;
    }

    // ids: "duplicate or wrongly-counted ids" rejected (FORMAT.md sec 1);
    // sec 3.4 requires ids on SuperEmbedder's own banks. Missing or a
    // count other than `count` -> the provisionally-named
    // SEMB_BANK_IDS_COUNT_MISMATCH (D-SLM6392); a duplicate -> the
    // already-pinned SEMB_DOCUMENT_ID_DUPLICATE, reused (C18/C4's own
    // identical semantic, per this round's own casebook).
    const js::Value* ids_v = header.Find("ids");
    if (!ids_v || !ids_v->IsArray() || static_cast<int64_t>(ids_v->as_array.size()) != count) {
      return SEMB_BANK_IDS_COUNT_MISMATCH;
    }
    {
      std::unordered_set<std::string_view> seen;
      seen.reserve(ids_v->as_array.size());
      for (const auto& id : ids_v->as_array) {
        if (!id.IsString()) return SEMB_BANK_IDS_COUNT_MISMATCH;
        if (!seen.emplace(std::string_view(id.as_string)).second) {
          return SEMB_DOCUMENT_ID_DUPLICATE;
        }
      }
    }

    // A non-finite row value (FORMAT.md sec 1's own importer obligation).
    // D-SLM6392's own proposed name: SEMB_BANK_NONFINITE_ROW.
    {
      const auto* floats = reinterpret_cast<const float*>(bin_bytes.data());
      const size_t total = static_cast<size_t>(count) * static_cast<size_t>(dims);
      for (size_t i = 0; i < total; ++i) {
        if (!std::isfinite(floats[i])) return SEMB_BANK_NONFINITE_ROW;
      }
    }

    // A zero-norm row under metric "cosine" (FORMAT.md sec 1; sec 2 of
    // FORMAT.md: "zero-norm rows are a bake-time error" under cosine).
    // D-SLM6392's own proposed name: SEMB_BANK_ZERO_NORM_ROW.
    if (metric_v->as_string == "cosine") {
      const auto* floats = reinterpret_cast<const float*>(bin_bytes.data());
      for (int64_t row = 0; row < count; ++row) {
        double sumsq = 0.0;
        for (int64_t d = 0; d < dims; ++d) {
          const double v = floats[row * dims + d];
          sumsq += v * v;
        }
        if (sumsq == 0.0) return SEMB_BANK_ZERO_NORM_ROW;
      }
    }

    // The manifest's own artifact SHA: provenance.artifact_sha, an
    // independent recomputation over model_sha||tokenizer_sha alone
    // (sec 3.4/C18's own "artifact SHA not matching the manifest" class,
    // distinct from the broader encoder_fingerprint self-consistency
    // check below -- see semb_bake_to_path's own comment for why this
    // seat split the two).
    const js::Value* provenance_v = manifest.Find("provenance");
    if (!provenance_v || !provenance_v->IsObject()) return SEMB_ARTIFACT_UNREADABLE;
    const js::Value* artifact_sha_v = provenance_v->Find("artifact_sha");
    const js::Value* model_sha_v = manifest.Find("model_sha");
    const js::Value* tokenizer_sha_v = manifest.Find("tokenizer_sha");
    if (!artifact_sha_v || !artifact_sha_v->IsString() || !model_sha_v || !model_sha_v->IsString() ||
        !tokenizer_sha_v || !tokenizer_sha_v->IsString()) {
      return SEMB_ARTIFACT_UNREADABLE;
    }
    {
      std::vector<uint8_t> model_sha, tokenizer_sha;
      if (!HexToBytes(model_sha_v->as_string, &model_sha) ||
          !HexToBytes(tokenizer_sha_v->as_string, &tokenizer_sha)) {
        return SEMB_ARTIFACT_UNREADABLE;
      }
      superslm::Sha256 hash;
      UpdateField(&hash, model_sha);
      UpdateField(&hash, tokenizer_sha);
      uint8_t recomputed[32];
      hash.Final(recomputed);
      if (Hex(recomputed, 32) != artifact_sha_v->as_string) return SEMB_ARTIFACT_SHA_MISMATCH;
    }

    // The manifest's own encoder_fingerprint: the PURE sec 3.3 formula
    // (SHA-256 over the five clear-text components, length-prefixed, no
    // tag) -- reading (a), D-SLM6391: checked entirely against the
    // manifest's OWN fields, no encoder argument, no comparison to
    // anything this handle does not already own.
    const js::Value* fingerprint_v = manifest.Find("encoder_fingerprint");
    if (!fingerprint_v || !fingerprint_v->IsString()) return SEMB_ARTIFACT_UNREADABLE;
    {
      static const char* kFields[] = {"model_sha", "tokenizer_sha", "template_sha256", "witness_sha",
                                       "certification_epoch"};
      superslm::Sha256 hash;
      for (const char* key : kFields) {
        const js::Value* field_v = manifest.Find(key);
        if (!field_v || !field_v->IsString()) return SEMB_ARTIFACT_UNREADABLE;
        std::vector<uint8_t> bytes;
        if (!HexToBytes(field_v->as_string, &bytes)) return SEMB_ARTIFACT_UNREADABLE;
        UpdateField(&hash, bytes);
      }
      uint8_t recomputed[32];
      hash.Final(recomputed);
      if (Hex(recomputed, 32) != fingerprint_v->as_string) return SEMB_FINGERPRINT_MISMATCH;
    }

    semb_bank cookie = nullptr;
    {
      std::lock_guard<std::mutex> lock(RegistryMutex());
      if (!AllocateHandleCookie(&cookie)) return SEMB_ALLOCATION_FAILED;
      Registry().emplace(cookie, std::make_unique<semb_bank_opaque>());
    }
    *out = cookie;
    return SEMB_OK;
  } catch (const std::bad_alloc&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (const std::length_error&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (...) {
    return SEMB_ARTIFACT_UNREADABLE;
  }
}

extern "C" semb_status semb_bank_close(semb_bank bank) {
  if (!bank) return SEMB_NULL_ARGUMENT;
  std::unique_ptr<semb_bank_opaque> closing;
  {
    std::lock_guard<std::mutex> lock(RegistryMutex());
    const auto found = Registry().find(bank);
    if (found == Registry().end()) return SEMB_INVALID_HANDLE;
    // SEMB_BANK_IN_USE (a live semb_query reference count on the bank) is
    // Slice 5's own -- no semb_query_open exists yet to raise it
    // (D-SLM4664; D-SLM6393). Every open handle closes unconditionally at
    // this slice.
    closing = std::move(found->second);
    Registry().erase(found);
  }
  closing.reset();
  return SEMB_OK;
}
