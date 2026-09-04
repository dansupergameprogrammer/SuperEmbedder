// The frozen public raw-text encoder vertical slice. Tokenization is the only
// operation added above the existing C12b-proven token-id path: the caller's
// span is validated, passed unchanged to SuperSLM's tokenizer, and the emitted
// ids enter the same PS-N composition already exercised by the row instrument.
#include "superembedder/semb.h"

#include "superembedder/encoder_interim_abi.h"
#include "superembedder/witness_abi.h"

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
#include <unordered_set>
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
constexpr char kWbPendingSentinel[] = "SEMB-W-B-PENDING-AFTER-U1-RAW-ENCODER-SLICE";
constexpr char kWqPendingSentinel[] = "SEMB-W-Q-PENDING-AFTER-U1-RAW-ENCODER-SLICE";
constexpr char kCertificationPendingSentinel[] =
    "SEMB-CERTIFIED-BUILDS-PENDING-AFTER-U1-RAW-ENCODER-SLICE";

std::mutex& RegistryMutex() {
  static auto* mutex = new std::mutex();
  return *mutex;
}

std::unordered_set<semb_encoder_s*>& Registry() {
  static auto* registry = new std::unordered_set<semb_encoder_s*>();
  return *registry;
}

// A registry check alone is not enough after delete: the allocator may reuse
// the same address for a later handle, turning a stale value into an alias of
// the replacement (the classic ABA problem). Close destroys every owned
// resource immediately, then retains only the small allocation as a tombstone
// until process teardown so no published handle address can be reused.
struct RetiredHandleNode {
  RetiredHandleNode* next;
};
static_assert(sizeof(semb_encoder_s) >= sizeof(RetiredHandleNode));
static_assert(alignof(semb_encoder_s) >= alignof(RetiredHandleNode));

class RetiredHandleStorage {
 public:
  ~RetiredHandleStorage() {
    while (head_) {
      RetiredHandleNode* node = head_;
      head_ = node->next;
      node->~RetiredHandleNode();
      ::operator delete(node);
    }
  }

  void Retire(void* storage) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    head_ = ::new (storage) RetiredHandleNode{head_};
  }

 private:
  std::mutex mutex_;
  RetiredHandleNode* head_ = nullptr;
};

RetiredHandleStorage& RetiredHandles() {
  static RetiredHandleStorage storage;
  return storage;
}

class HandleLease {
 public:
  explicit HandleLease(semb_encoder enc) {
    if (!enc) return;
    std::lock_guard<std::mutex> lock(RegistryMutex());
    if (Registry().find(enc) == Registry().end()) return;
    enc->active_calls.fetch_add(1, std::memory_order_acq_rel);
    handle_ = enc;
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
  std::ifstream stream(path, std::ios::binary | std::ios::ate);
  if (!stream) return false;
  const std::streamoff end = stream.tellg();
  if (end <= 0 || static_cast<uintmax_t>(end) > std::numeric_limits<size_t>::max()) return false;
  out->resize(static_cast<size_t>(end));
  stream.seekg(0, std::ios::beg);
  return static_cast<bool>(stream.read(reinterpret_cast<char*>(out->data()), end));
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

std::array<uint8_t, 32> ComputeFingerprint(const std::vector<uint8_t>& model_bytes,
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

  std::array<uint8_t, 32> out{};
  superslm::Sha256 hash;
  UpdateField(&hash, model_sha);
  UpdateField(&hash, tokenizer_sha);
  UpdateField(&hash, template_sha.data());
  UpdateField(&hash, witness_sha);
  UpdateField(&hash, certification_epoch);
  hash.Final(out.data());
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
    case SEMB_OK: return "SEMB_OK";
    case SEMB_NULL_ARGUMENT: return "SEMB_NULL_ARGUMENT";
    case SEMB_STRUCT_SIZE_MISMATCH: return "SEMB_STRUCT_SIZE_MISMATCH";
    case SEMB_INVALID_ARGUMENT: return "SEMB_INVALID_ARGUMENT";
    case SEMB_INVALID_HANDLE: return "SEMB_INVALID_HANDLE";
    case SEMB_HANDLE_IN_USE: return "SEMB_HANDLE_IN_USE";
    case SEMB_CONCURRENCY_EXCEEDED: return "SEMB_CONCURRENCY_EXCEEDED";
    case SEMB_BUFFER_TOO_SMALL: return "SEMB_BUFFER_TOO_SMALL";
    case SEMB_MISALIGNED_BUFFER: return "SEMB_MISALIGNED_BUFFER";
    case SEMB_INVALID_UTF8: return "SEMB_INVALID_UTF8";
    case SEMB_INPUT_EMPTY: return "SEMB_INPUT_EMPTY";
    case SEMB_CONTEXT_CAP_EXCEEDED: return "SEMB_CONTEXT_CAP_EXCEEDED";
    case SEMB_ENGINE_REFUSED: return "SEMB_ENGINE_REFUSED";
    case SEMB_POOLED_SUBNORMAL: return "SEMB_POOLED_SUBNORMAL";
    case SEMB_POOLED_OVERFLOW: return "SEMB_POOLED_OVERFLOW";
    case SEMB_ALLOCATION_FAILED: return "SEMB_ALLOCATION_FAILED";
    case SEMB_STATUS_NEXT_FREE: break;
  }
  return "SEMB_UNKNOWN";
}

extern "C" semb_status semb_encoder_open(const semb_config* cfg, semb_encoder* out) {
  if (!cfg || !out) return SEMB_NULL_ARGUMENT;
  *out = nullptr;
  if (cfg->struct_size != sizeof(semb_config)) return SEMB_STRUCT_SIZE_MISMATCH;
  if (!cfg->model_path || !cfg->tokenizer_path) return SEMB_NULL_ARGUMENT;
  if (cfg->appended_token_id < 0) return SEMB_INVALID_ARGUMENT;

  try {
    std::vector<uint8_t> model_bytes;
    std::vector<uint8_t> tokenizer_bytes;
    if (!ReadFileOnce(std::string_view(cfg->model_path, cfg->model_path_len), &model_bytes) ||
        !ReadFileOnce(std::string_view(cfg->tokenizer_path, cfg->tokenizer_path_len),
                      &tokenizer_bytes)) {
      return SEMB_ENGINE_REFUSED;
    }

    auto handle = std::make_unique<semb_encoder_s>();
    handle->fingerprint = ComputeFingerprint(model_bytes, tokenizer_bytes);
    handle->tokenizer_bytes = std::move(tokenizer_bytes);

    const uint32_t max_concurrency = cfg->max_concurrency == 0 ? 1 : cfg->max_concurrency;
    SembInterimEncoder* interim = nullptr;
    const char* engine_status = nullptr;
    const SembInterimStatus open_status = semb_interim_encoder_open_owned(
        std::move(model_bytes), cfg->appended_token_id, max_concurrency, &interim,
        &engine_status);
    (void)engine_status;
    if (open_status != kSembInterimOk) return MapInterimStatus(open_status, kSembOk);

    std::unique_ptr<SembInterimEncoder, void (*)(SembInterimEncoder*)> interim_guard(
        interim, semb_interim_encoder_close);
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

    SembInterimGeometry geometry{};
    geometry.struct_size = sizeof(geometry);
    if (semb_interim_encoder_geometry(interim, &geometry) != kSembInterimOk) {
      return SEMB_ENGINE_REFUSED;
    }
    if (static_cast<uint32_t>(cfg->appended_token_id) >= geometry.vocab_size ||
        tokenizer.VocabSize() <= 0 ||
        tokenizer.VocabSize() > static_cast<int32_t>(geometry.vocab_size)) {
      return SEMB_ENGINE_REFUSED;
    }

    handle->interim = interim_guard.release();
    handle->tokenizer_artifact = std::move(tokenizer_artifact);
    handle->tokenizer = std::move(tokenizer);
    handle->dims = geometry.hidden_size;
    handle->vocab_size = geometry.vocab_size;
    handle->context_cap = geometry.context_cap;
    handle->chunk_budget = 0;
    {
      std::lock_guard<std::mutex> lock(RegistryMutex());
      Registry().insert(handle.get());
    }
    *out = handle.release();
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
  RetiredHandleStorage* retired = nullptr;
  {
    std::lock_guard<std::mutex> lock(RegistryMutex());
    const auto found = Registry().find(enc);
    if (found == Registry().end()) return SEMB_INVALID_HANDLE;
    if (enc->active_calls.load(std::memory_order_acquire) != 0) return SEMB_HANDLE_IN_USE;
    retired = &RetiredHandles();
    Registry().erase(found);
  }
  enc->~semb_encoder_s();
  retired->Retire(enc);
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
  if (!enc || !utf8 || !out_required_bytes || !out_fingerprint) return SEMB_NULL_ARGUMENT;
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
  if (!ValidUtf8(utf8, utf8_len)) return SEMB_INVALID_UTF8;

  try {
    const std::vector<int32_t> ids =
        lease.get()->tokenizer.Encode(std::string_view(utf8, utf8_len));
    if (ids.empty()) return SEMB_INPUT_EMPTY;
    if (ids.size() >= lease.get()->context_cap) return SEMB_CONTEXT_CAP_EXCEEDED;

    SembWaPoolStatus dequantize = kSembOk;
    const char* engine_status = nullptr;
    size_t interim_required = 0;
    const SembInterimStatus status = semb_interim_encode_ps_n(
        lease.get()->interim, ids.data(), ids.size(), lease.get()->chunk_budget,
        out_vector, out_capacity_bytes, &interim_required, &dequantize, &engine_status);
    (void)engine_status;
    const semb_status mapped = MapInterimStatus(status, dequantize);
    if (mapped != SEMB_OK) return mapped;
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
