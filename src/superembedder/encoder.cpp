// The frozen public raw-text encoder vertical slice. Tokenization is the only
// operation added above the existing C12b-proven token-id path: the caller's
// span is validated, passed unchanged to SuperSLM's tokenizer, and the emitted
// ids enter the same PS-N composition already exercised by the row instrument.
#include "superembedder/semb.h"

#include "superembedder/encoder_interim_abi.h"
#include "superembedder/witness_abi.h"
#include "encoder_open_internal.h"

#include <array>
#include <atomic>
#include <cstring>
#include <fstream>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "superslm/artifact.h"
#include "superslm/sha256.h"
#include "superslm/tokenizer.h"

struct semb_encoder_s {
  // The tokenizer view borrows from these exact once-read bytes. Model bytes
  // are owned by the interim adapter because its SslmModelView borrows them.
  std::vector<uint8_t> tokenizer_bytes;
  SembInterimEncoder* interim = nullptr;
  superslm::SslmArtifact tokenizer_artifact;
  superslm::TokenizerView tokenizer;
  uint32_t dims = 0;
  uint32_t vocab_size = 0;
  uint32_t context_cap = 0;
  size_t chunk_budget = 0;
  std::array<uint8_t, 32> fingerprint{};
  std::atomic<uint32_t> active_calls{0};

  ~semb_encoder_s() {
    if (interim) semb_interim_encoder_close(interim);
  }
};

namespace {

constexpr char kQueryPrefix[] =
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:";
constexpr char kCanonicalEndToken[] = "<|endoftext|>";
constexpr char kWbPendingSentinel[] = "SEMB-W-B-PENDING-AFTER-U1-RAW-ENCODER-SLICE";
constexpr char kWqPendingSentinel[] = "SEMB-W-Q-PENDING-AFTER-U1-RAW-ENCODER-SLICE";
constexpr char kCertificationPendingSentinel[] =
    "SEMB-CERTIFIED-BUILDS-PENDING-AFTER-U1-RAW-ENCODER-SLICE";
constexpr char kProvisionalFingerprintTag[] = SEMB_FINGERPRINT_PROVISIONAL_TAG;
static_assert(sizeof(kProvisionalFingerprintTag) - 1 ==
              SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE);

std::mutex& RegistryMutex() {
  static auto* mutex = new std::mutex();
  return *mutex;
}

using HandleRegistry =
    std::unordered_map<semb_encoder, std::unique_ptr<semb_encoder_s>>;

HandleRegistry& Registry() {
  static auto* registry = new HandleRegistry();
  return *registry;
}

// The ABI type is an opaque pointer, but the published value is a monotonic
// cookie, never an allocation address. Registry entries own the actual handle
// objects and close erases them normally. A stale cookie therefore cannot
// become an alias through allocator address reuse, and closed handles retain
// no per-handle tombstone storage.
bool AllocateHandleCookie(semb_encoder* out) {
  static uintptr_t next = 1;
  if (next == 0) return false;  // The pointer-width cookie space was exhausted.
  *out = reinterpret_cast<semb_encoder>(next++);
  return true;
}

class HandleLease {
 public:
  explicit HandleLease(semb_encoder enc) {
    if (!enc) return;
    std::lock_guard<std::mutex> lock(RegistryMutex());
    const auto found = Registry().find(enc);
    if (found == Registry().end()) return;
    found->second->active_calls.fetch_add(1, std::memory_order_acq_rel);
    handle_ = found->second.get();
  }

  ~HandleLease() {
    if (handle_) handle_->active_calls.fetch_sub(1, std::memory_order_acq_rel);
  }

  HandleLease(const HandleLease&) = delete;
  HandleLease& operator=(const HandleLease&) = delete;
  semb_encoder_s* get() const { return handle_; }

 private:
  semb_encoder_s* handle_ = nullptr;
};

bool ReadFileOnce(std::string_view path_span, std::vector<uint8_t>* out) {
  if (path_span.empty() || path_span.find('\0') != std::string_view::npos) return false;
  const std::string path(path_span);
  try {
    std::ifstream stream;
    // Propagate allocation exceptions from stream operations to the ABI's
    // allocation-failure boundary. Ordinary I/O exceptions mean unreadable.
    stream.exceptions(std::ios::badbit);
    stream.open(path, std::ios::binary | std::ios::ate);
    if (!stream) return false;
    const std::streamoff end = stream.tellg();
    if (end < 0 || static_cast<uintmax_t>(end) > std::numeric_limits<size_t>::max() ||
        static_cast<uintmax_t>(end) >
            static_cast<uintmax_t>(std::numeric_limits<std::streamsize>::max())) return false;
    out->resize(static_cast<size_t>(end));
    stream.seekg(0, std::ios::beg);
    if (!stream) return false;
    // A successfully read empty file is delivered to the artifact boundary.
    if (end == 0) return true;
    return static_cast<bool>(stream.read(reinterpret_cast<char*>(out->data()),
                                         static_cast<std::streamsize>(end)));
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

void UpdateField(superslm::Sha256* hash, const uint8_t field[32]) {
  UpdateU64(hash, 32);
  hash->Update(field, 32);
}

std::array<uint8_t, 32> ComputeTemplateDigest() {
  superslm::Sha256 hash;
  UpdateU64(&hash, 0);  // PS-N has no document frame.
  UpdateU64(&hash, sizeof(kQueryPrefix) - 1);
  hash.Update(reinterpret_cast<const uint8_t*>(kQueryPrefix), sizeof(kQueryPrefix) - 1);
  std::array<uint8_t, 32> out{};
  hash.Final(out.data());
  return out;
}

std::array<uint8_t, 32> ComputeProvisionalFingerprint(
    const std::vector<uint8_t>& model_bytes,
    const std::vector<uint8_t>& tokenizer_bytes) {
  uint8_t model_sha[32], tokenizer_sha[32], wa_sha[32], wb_sha[32], wq_sha[32];
  Hash(model_bytes.data(), model_bytes.size(), model_sha);
  Hash(tokenizer_bytes.data(), tokenizer_bytes.size(), tokenizer_sha);
  semb_wa_digest(wa_sha);
  Hash(kWbPendingSentinel, sizeof(kWbPendingSentinel) - 1, wb_sha);
  Hash(kWqPendingSentinel, sizeof(kWqPendingSentinel) - 1, wq_sha);

  uint8_t witness_sha[32];
  {
    superslm::Sha256 hash;
    hash.Update(wa_sha, 32);
    hash.Update(wb_sha, 32);
    hash.Update(wq_sha, 32);
    hash.Final(witness_sha);
  }
  uint8_t certification_epoch[32];
  Hash(kCertificationPendingSentinel, sizeof(kCertificationPendingSentinel) - 1,
       certification_epoch);
  const auto template_sha = ComputeTemplateDigest();

  uint8_t digest[32];
  superslm::Sha256 hash;
  // This is deliberately not the final five-field wire value. Domain-separate
  // the provisional derivation and reserve an unmistakable public prefix so a
  // consumer can reject it without relying on README prose.
  hash.Update(reinterpret_cast<const uint8_t*>(kProvisionalFingerprintTag),
              SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE);
  UpdateField(&hash, model_sha);
  UpdateField(&hash, tokenizer_sha);
  UpdateField(&hash, template_sha.data());
  UpdateField(&hash, witness_sha);
  UpdateField(&hash, certification_epoch);
  hash.Final(digest);

  std::array<uint8_t, 32> out{};
  std::memcpy(out.data(), kProvisionalFingerprintTag,
              SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE);
  std::memcpy(out.data() + SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE, digest,
              out.size() - SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE);
  return out;
}

bool ValidUtf8(const char* data, size_t size) {
  size_t i = 0;
  while (i < size) {
    const uint8_t lead = static_cast<uint8_t>(data[i]);
    if (lead <= 0x7F) {
      ++i;
      continue;
    }
    size_t count = 0;
    uint32_t codepoint = 0;
    uint32_t minimum = 0;
    if (lead >= 0xC2 && lead <= 0xDF) {
      count = 2;
      codepoint = lead & 0x1F;
      minimum = 0x80;
    } else if (lead >= 0xE0 && lead <= 0xEF) {
      count = 3;
      codepoint = lead & 0x0F;
      minimum = 0x800;
    } else if (lead >= 0xF0 && lead <= 0xF4) {
      count = 4;
      codepoint = lead & 0x07;
      minimum = 0x10000;
    } else {
      return false;
    }
    if (count > size - i) return false;
    for (size_t j = 1; j < count; ++j) {
      const uint8_t continuation = static_cast<uint8_t>(data[i + j]);
      if ((continuation & 0xC0) != 0x80) return false;
      codepoint = (codepoint << 6) | (continuation & 0x3F);
    }
    if (codepoint < minimum || codepoint > 0x10FFFF ||
        (codepoint >= 0xD800 && codepoint <= 0xDFFF)) {
      return false;
    }
    i += count;
  }
  return true;
}

semb_status MapInterimStatus(SembInterimStatus status, SembWaPoolStatus dequantize) {
  switch (status) {
    case kSembInterimOk: return SEMB_OK;
    case kSembInterimNullArgument: return SEMB_NULL_ARGUMENT;
    case kSembInterimInputEmpty: return SEMB_INPUT_EMPTY;
    case kSembInterimBufferTooSmall: return SEMB_BUFFER_TOO_SMALL;
    case kSembInterimConcurrencyExceeded: return SEMB_CONCURRENCY_EXCEEDED;
    case kSembInterimDequantizeRefused:
      if (dequantize == kSembPooledSubnormal) return SEMB_POOLED_SUBNORMAL;
      if (dequantize == kSembPooledOverflow) return SEMB_POOLED_OVERFLOW;
      return SEMB_ENGINE_REFUSED;
    case kSembInterimEngineRefused:
    case kSembInterimInvalidLeg:
    case kSembInterimPositionOutOfRange:
    case kSembInterimStructSizeMismatch: return SEMB_ENGINE_REFUSED;
  }
  return SEMB_ENGINE_REFUSED;
}

}  // namespace

extern "C" const char* semb_status_name(semb_status status) {
  switch (status) {
#define SEMB_STATUS_NAME_(name, value) case name: return #name;
    SEMB_STATUS_ENUM_LIST(SEMB_STATUS_NAME_)
#undef SEMB_STATUS_NAME_
    case SEMB_STATUS_NEXT_FREE: break;
  }
  return "SEMB_UNKNOWN";
}

extern "C" semb_status semb_encoder_open(const semb_config* cfg, semb_encoder* out) {
  if (out) *out = nullptr;
  if (!cfg || !out) return SEMB_NULL_ARGUMENT;
  if (cfg->struct_size != sizeof(semb_config)) return SEMB_STRUCT_SIZE_MISMATCH;
  if ((!cfg->model_path && cfg->model_path_len > 0) ||
      (!cfg->tokenizer_path && cfg->tokenizer_path_len > 0)) return SEMB_NULL_ARGUMENT;

  try {
    std::vector<uint8_t> model_bytes;
    std::vector<uint8_t> tokenizer_bytes;
    if (!ReadFileOnce(std::string_view(cfg->tokenizer_path ? cfg->tokenizer_path : "",
                                      cfg->tokenizer_path_len),
                      &tokenizer_bytes)) {
      return SEMB_ARTIFACT_UNREADABLE;
    }

    auto handle = std::make_unique<semb_encoder_s>();
    handle->tokenizer_bytes = std::move(tokenizer_bytes);
    superslm::SslmArtifact tokenizer_artifact;
    superslm::SslmError artifact_error;
    if (superslm::SslmArtifact::OpenFromMemory(handle->tokenizer_bytes.data(),
                                                handle->tokenizer_bytes.size(),
                                                tokenizer_artifact, &artifact_error) !=
        superslm::SslmStatus::Ok) {
      return SEMB_ENGINE_REFUSED;
    }
    superslm::TokenizerView tokenizer;
    std::string tokenizer_error;
    if (!superslm::TokenizerView::Open(tokenizer_artifact, tokenizer, &tokenizer_error)) {
      return SEMB_ENGINE_REFUSED;
    }
    if (tokenizer.VocabSize() <= 0) return SEMB_ENGINE_REFUSED;

    // Resolve the compiled-in literal from the same tokenizer bytes the
    // handle owns and fingerprints, before reading the model artifact.
    const std::vector<int32_t> canonical_end_ids =
        tokenizer.Encode(kCanonicalEndToken);
    if (canonical_end_ids.size() != 1 || canonical_end_ids[0] < 0) {
      return SEMB_TEMPLATE_TOKEN_ABSENT;
    }
    const int32_t appended_token_id = canonical_end_ids[0];

    if (!ReadFileOnce(std::string_view(cfg->model_path ? cfg->model_path : "",
                                      cfg->model_path_len), &model_bytes)) {
      return SEMB_ARTIFACT_UNREADABLE;
    }
    // The interim owned-open entry requires nonempty backing. Zero bytes
    // were successfully read but cannot form an engine artifact.
    if (model_bytes.empty()) return SEMB_ENGINE_REFUSED;

    handle->fingerprint =
        ComputeProvisionalFingerprint(model_bytes, handle->tokenizer_bytes);

    const uint32_t max_concurrency = cfg->max_concurrency == 0 ? 1 : cfg->max_concurrency;
    SembInterimEncoder* interim = nullptr;
    const char* engine_status = nullptr;
    bool vocab_mismatch = false;
    const SembInterimStatus open_status = semb::OpenEncoderOwnedWithVocabJoin(
        std::move(model_bytes), appended_token_id, max_concurrency,
        static_cast<uint32_t>(tokenizer.VocabSize()), &interim,
        &engine_status, vocab_mismatch);
    (void)engine_status;
    if (vocab_mismatch) return SEMB_TOKENIZER_MODEL_MISMATCH;
    if (open_status != kSembInterimOk) return MapInterimStatus(open_status, kSembOk);

    std::unique_ptr<SembInterimEncoder, void (*)(SembInterimEncoder*)> interim_guard(
        interim, semb_interim_encoder_close);

    SembInterimGeometry geometry{};
    geometry.struct_size = sizeof(geometry);
    if (semb_interim_encoder_geometry(interim, &geometry) != kSembInterimOk) {
      return SEMB_ENGINE_REFUSED;
    }

    handle->interim = interim_guard.release();
    handle->tokenizer_artifact = std::move(tokenizer_artifact);
    handle->tokenizer = std::move(tokenizer);
    handle->dims = geometry.hidden_size;
    handle->vocab_size = geometry.vocab_size;
    handle->context_cap = geometry.context_cap;
    handle->chunk_budget = 0;
    semb_encoder cookie = nullptr;
    {
      std::lock_guard<std::mutex> lock(RegistryMutex());
      if (!AllocateHandleCookie(&cookie)) return SEMB_ALLOCATION_FAILED;
      const auto inserted = Registry().emplace(cookie, std::move(handle));
      if (!inserted.second) return SEMB_ENGINE_REFUSED;
    }
    *out = cookie;
    return SEMB_OK;
  } catch (const std::bad_alloc&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (const std::length_error&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (...) {
    return SEMB_ENGINE_REFUSED;
  }
}

extern "C" semb_status semb_encoder_close(semb_encoder enc) {
  if (!enc) return SEMB_NULL_ARGUMENT;
  std::unique_ptr<semb_encoder_s> closing;
  {
    std::lock_guard<std::mutex> lock(RegistryMutex());
    const auto found = Registry().find(enc);
    if (found == Registry().end()) return SEMB_INVALID_HANDLE;
    if (found->second->active_calls.load(std::memory_order_acquire) != 0) {
      return SEMB_HANDLE_IN_USE;
    }
    closing = std::move(found->second);
    Registry().erase(found);
  }
  closing.reset();
  return SEMB_OK;
}

extern "C" semb_status semb_encoder_dims(semb_encoder enc, uint32_t* out_dims) {
  if (!enc || !out_dims) return SEMB_NULL_ARGUMENT;
  HandleLease lease(enc);
  if (!lease.get()) return SEMB_INVALID_HANDLE;
  *out_dims = lease.get()->dims;
  return SEMB_OK;
}

extern "C" semb_status semb_encode(semb_encoder enc, const char* utf8, size_t utf8_len,
                                    float* out_vector, size_t out_capacity_bytes,
                                    size_t* out_required_bytes,
                                    semb_fingerprint* out_fingerprint) {
  if (!enc || !out_required_bytes || !out_fingerprint) return SEMB_NULL_ARGUMENT;
  try {
    HandleLease lease(enc);
    if (!lease.get()) return SEMB_INVALID_HANDLE;
    if (out_fingerprint->struct_size != sizeof(semb_fingerprint)) {
      return SEMB_STRUCT_SIZE_MISMATCH;
    }

    const size_t required = static_cast<size_t>(lease.get()->dims) * sizeof(float);
    if (out_vector && (reinterpret_cast<uintptr_t>(out_vector) & 15u) != 0) {
      return SEMB_MISALIGNED_BUFFER;
    }
    if (out_capacity_bytes < required) {
      *out_required_bytes = required;
      return SEMB_BUFFER_TOO_SMALL;
    }
    if (!out_vector) return SEMB_NULL_ARGUMENT;
    if (utf8_len == 0) return SEMB_INPUT_EMPTY;
    if (!utf8) return SEMB_NULL_ARGUMENT;
    if (!ValidUtf8(utf8, utf8_len)) return SEMB_INVALID_UTF8;

    const std::vector<int32_t> ids =
        lease.get()->tokenizer.Encode(std::string_view(utf8, utf8_len));
    if (ids.empty()) return SEMB_INPUT_EMPTY;
    if (ids.size() >= lease.get()->context_cap) return SEMB_CONTEXT_CAP_EXCEEDED;

    // Keep caller bytes private until tokenization, forward, selection, and
    // dequantization have all succeeded, including every allocation they make.
    std::vector<float> staged_vector(lease.get()->dims);
    SembWaPoolStatus dequantize = kSembOk;
    const char* engine_status = nullptr;
    size_t interim_required = 0;
    const SembInterimStatus status = semb_interim_encode_ps_n(
        lease.get()->interim, ids.data(), ids.size(), lease.get()->chunk_budget,
        staged_vector.data(), required, &interim_required, &dequantize, &engine_status);
    (void)engine_status;
    const semb_status mapped = MapInterimStatus(status, dequantize);
    if (mapped != SEMB_OK) return mapped;
    std::memcpy(out_vector, staged_vector.data(), required);
    *out_required_bytes = interim_required;
    std::memcpy(out_fingerprint->digest, lease.get()->fingerprint.data(),
                lease.get()->fingerprint.size());
    return SEMB_OK;
  } catch (const std::bad_alloc&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (const std::length_error&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (...) {
    return SEMB_ENGINE_REFUSED;
  }
}
