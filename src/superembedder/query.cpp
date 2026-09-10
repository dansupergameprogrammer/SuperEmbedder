#include "superembedder/semb.h"

#include "query_internal.h"

#include <array>
#include <atomic>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "superslm/sha256.h"

// These are deliberately TU-private declarations: the frozen public surface
// remains semb.h's twelve verbs. The query implementation alone bridges the
// bank registry and encoder's opening-time W-Q composition.
extern "C" semb_status semb_bank_acquire_query(semb_bank bank, const uint8_t fingerprint[32]);
extern "C" semb_status semb_bank_release_query(semb_bank bank);
namespace semb {
semb_status EncoderManifestFingerprint(semb_encoder enc, uint8_t out[32]);
semb_status EncoderAbiFingerprint(semb_encoder enc, uint8_t out[32]);
semb_status EncoderWqDigest(semb_encoder enc, uint8_t out[32]);
semb_status EncoderAcquireQuery(semb_encoder enc);
semb_status EncoderReleaseQuery(semb_encoder enc);
semb_status EncoderDims(semb_encoder enc, uint32_t* out_dims);
bool EncoderValidUtf8(const char* data, size_t size);
semb_status EncodeQueryComposedForWitness(semb_encoder_s* encoder,
                                          std::string_view composed,
                                          size_t max_content_ids,
                                          std::vector<float>* out_vector);
semb_status EncodeQueryComposed(semb_encoder enc, std::string_view composed,
                                size_t max_content_ids,
                                std::vector<float>* out_vector);
}  // namespace semb

const char semb::kQueryPrefix[] =
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:";

struct semb_query_opaque {
  semb_encoder encoder = nullptr;
  semb_bank bank = nullptr;
  std::atomic<uint32_t> active_calls{0};
};

namespace {

using semb::kQueryPrefix;

// The committed W-Q population: five uncapped join strings and one dedicated
// truncation-order string. The digest is intentionally built in this TU so a
// change to query composition rotates witness_sha during encoder open.
constexpr const char* kJoinQueries[] = {
    "temperature", "  leading and trailing whitespace query  ",
    "MixedCASE Query With Numbers 42", "unicode café façade 日本語 query",
    "<|endoftext|> embedded literal in the middle of a query"};
constexpr char kTruncationQueryLead[] =
    "A long committed query string for the truncation-order leg, four hundred distinct tokens long so "
    "any witness-internal cap set below its own length forces a real cut: ";
constexpr size_t kWitnessQueryContentCap = 96;

std::string ComposeQuery(std::string_view text) {
  std::string composed;
  composed.reserve(sizeof(kQueryPrefix) - 1 + text.size());
  composed.append(kQueryPrefix);
  composed.append(text);
  return composed;
}

std::string BuildTruncationQuery() {
  std::string query(kTruncationQueryLead);
  for (unsigned i = 1; i <= 400; ++i) {
    query.append("term-");
    if (i < 10) query.append("000");
    else if (i < 100) query.append("00");
    else if (i < 1000) query.append("0");
    query.append(std::to_string(i));
    if (i != 400) query.push_back(' ');
  }
  return query;
}

void UpdateU64(superslm::Sha256* hash, uint64_t value) {
  uint8_t bytes[8];
  for (size_t i = 0; i < sizeof(bytes); ++i) bytes[i] = static_cast<uint8_t>(value >> (8 * i));
  hash->Update(bytes, sizeof(bytes));
}

bool HashWitnessPosition(semb_encoder_s* encoder, std::string_view raw_query,
                         size_t max_content_ids, superslm::Sha256* hash) {
  const std::string composed = ComposeQuery(raw_query);
  std::vector<float> vector;
  if (semb::EncodeQueryComposedForWitness(encoder, composed, max_content_ids, &vector) != SEMB_OK) {
    return false;
  }
  const size_t byte_count = vector.size() * sizeof(float);
  UpdateU64(hash, static_cast<uint64_t>(byte_count));
  hash->Update(reinterpret_cast<const uint8_t*>(vector.data()), byte_count);
  return true;
}

std::mutex& RegistryMutex() {
  static auto* mutex = new std::mutex();
  return *mutex;
}
using RegistryType = std::unordered_map<semb_query, std::unique_ptr<semb_query_opaque>>;
RegistryType& Registry() {
  static auto* registry = new RegistryType();
  return *registry;
}
bool AllocateCookie(semb_query* out) {
  static uintptr_t next = 1;
  if (next == 0) return false;
  *out = reinterpret_cast<semb_query>(next++);
  return true;
}

class QueryLease {
 public:
  explicit QueryLease(semb_query q) {
    if (!q) return;
    std::lock_guard<std::mutex> lock(RegistryMutex());
    const auto found = Registry().find(q);
    if (found == Registry().end()) return;
    found_ = true;
    uint32_t expected = 0;
    if (!found->second->active_calls.compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) return;
    query_ = found->second.get();
  }
  ~QueryLease() {
    if (query_) query_->active_calls.store(0, std::memory_order_release);
  }
  semb_query_opaque* get() const { return query_; }
  bool found() const { return found_; }
 private:
  semb_query_opaque* query_ = nullptr;
  bool found_ = false;
};

}  // namespace

bool semb_compute_wq_digest(semb_encoder_s* encoder, std::array<uint8_t, 32>* out_digest) {
  if (!encoder || !out_digest) return false;
  superslm::Sha256 hash;
  UpdateU64(&hash, sizeof(kJoinQueries) / sizeof(kJoinQueries[0]) + 1);
  for (const char* query : kJoinQueries) {
    if (!HashWitnessPosition(encoder, query, std::numeric_limits<size_t>::max(), &hash)) return false;
  }
  if (!HashWitnessPosition(encoder, BuildTruncationQuery(), kWitnessQueryContentCap, &hash)) return false;
  hash.Final(out_digest->data());
  return true;
}

extern "C" semb_status semb_query_open(semb_encoder enc, semb_bank bank, semb_query* out) {
  if (out) *out = nullptr;
  if (!enc || !bank || !out) return SEMB_NULL_ARGUMENT;
  uint8_t fingerprint[32];
  const semb_status fingerprint_status = semb::EncoderManifestFingerprint(enc, fingerprint);
  if (fingerprint_status != SEMB_OK) return fingerprint_status;
  const semb_status encoder_status = semb::EncoderAcquireQuery(enc);
  if (encoder_status != SEMB_OK) return encoder_status;
  const semb_status bank_status = semb_bank_acquire_query(bank, fingerprint);
  if (bank_status != SEMB_OK) {
    (void)semb::EncoderReleaseQuery(enc);
    return bank_status;
  }
  try {
    auto query = std::make_unique<semb_query_opaque>();
    query->encoder = enc;
    query->bank = bank;
    semb_query cookie = nullptr;
    {
      std::lock_guard<std::mutex> lock(RegistryMutex());
      if (!AllocateCookie(&cookie)) {
        (void)semb_bank_release_query(bank);
        (void)semb::EncoderReleaseQuery(enc);
        return SEMB_ALLOCATION_FAILED;
      }
      Registry().emplace(cookie, std::move(query));
    }
    *out = cookie;
    return SEMB_OK;
  } catch (const std::bad_alloc&) {
    (void)semb_bank_release_query(bank);
    (void)semb::EncoderReleaseQuery(enc);
    return SEMB_ALLOCATION_FAILED;
  }
}

extern "C" semb_status semb_query_encode(semb_query q, const char* utf8, size_t utf8_len,
                                            float* out_vector, size_t out_capacity_bytes,
                                            size_t* out_required_bytes) {
  if (!q || !out_required_bytes) return SEMB_NULL_ARGUMENT;
  QueryLease lease(q);
  if (!lease.get()) return lease.found() ? SEMB_HANDLE_IN_USE : SEMB_INVALID_HANDLE;
  uint32_t dims = 0;
  const semb_status dims_status = semb::EncoderDims(lease.get()->encoder, &dims);
  if (dims_status != SEMB_OK) return dims_status;
  const size_t required = static_cast<size_t>(dims) * sizeof(float);
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
  if (!semb::EncoderValidUtf8(utf8, utf8_len)) return SEMB_INVALID_UTF8;
  try {
    const std::string composed = ComposeQuery(std::string_view(utf8, utf8_len));
    std::vector<float> staged_vector;
    const semb_status encoded = semb::EncodeQueryComposed(
        lease.get()->encoder, composed, std::numeric_limits<size_t>::max(), &staged_vector);
    if (encoded != SEMB_OK) return encoded;
    std::memcpy(out_vector, staged_vector.data(), required);
    *out_required_bytes = required;
    return SEMB_OK;
  } catch (const std::bad_alloc&) {
    return SEMB_ALLOCATION_FAILED;
  }
}

extern "C" semb_status semb_query_close(semb_query q) {
  if (!q) return SEMB_NULL_ARGUMENT;
  std::unique_ptr<semb_query_opaque> closing;
  {
    std::lock_guard<std::mutex> lock(RegistryMutex());
    const auto found = Registry().find(q);
    if (found == Registry().end()) return SEMB_INVALID_HANDLE;
    if (found->second->active_calls.load(std::memory_order_acquire) != 0) return SEMB_HANDLE_IN_USE;
    closing = std::move(found->second);
    Registry().erase(found);
  }
  const semb_status released = semb_bank_release_query(closing->bank);
  const semb_status encoder_released = semb::EncoderReleaseQuery(closing->encoder);
  return released != SEMB_OK ? released : encoder_released;
}

extern "C" semb_status semb_fingerprint_of(semb_encoder enc, semb_fingerprint* out) {
  if (!enc || !out) return SEMB_NULL_ARGUMENT;
  if (out->struct_size != sizeof(semb_fingerprint)) return SEMB_STRUCT_SIZE_MISMATCH;
  // The ABI form is intentionally tagged. Query open uses the separate
  // untagged accessor above, never this consumer-facing value.
  return semb::EncoderAbiFingerprint(enc, out->digest);
}
