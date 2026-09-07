// The frozen public raw-text encoder vertical slice. Tokenization is the only
// operation added above the existing C12b-proven token-id path: the caller's
// span is validated, passed unchanged to SuperSLM's tokenizer, and the emitted
// ids enter the same PS-N composition already exercised by the row instrument.
#include "superembedder/semb.h"

#include "superembedder/encoder_interim_abi.h"
#include "superembedder/seam_abi.h"
#include "superembedder/witness_abi.h"
#include "superembedder/wb_digest_abi.h"
#include "encoder_open_internal.h"
#include "wb_corpus.h"

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
  // W-B's own digest for this handle's artifacts, derived once at open (see
  // ComputeWbDigest's own comment) and returned by semb_wb_digest without a
  // second computation -- D-SLM3978's no-cache rule binds the FINGERPRINT
  // derivation (no re-read of a file another field derived from), not how
  // many times a diagnostic accessor is called against an already-open
  // handle (witness_abi.h's own semb_wb_digest comment).
  std::array<uint8_t, 32> wb_digest{};
  std::atomic<uint32_t> active_calls{0};

  ~semb_encoder_s() {
    if (interim) semb_interim_encoder_close(interim);
  }
};

namespace {

constexpr char kQueryPrefix[] =
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:";
constexpr char kCanonicalEndToken[] = "<|endoftext|>";
// W-B's own sentinel retired, TE-147: ComputeProvisionalFingerprint now
// takes a real, handle-derived wb_digest (ComputeWbDigest, below) instead
// of hashing a placeholder literal. W-Q is still out of this slice's own
// scope (SuperEmbedder_Plan.md sec 4.4c: "specification, probe-proven, not
// yet built") and keeps its sentinel.
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

// TE-159 (C-2, D-SLM6354, the conductor's ruling): W-B's own real digest,
// now derived through THE SAME COMPOSITION `semb_encode_batch` wraps
// (semb_interim_encode_batch_ps_n's seam tap, encoder_interim_abi.h)
// instead of a second, independent forward call
// (semb_interim_encode_seam) that TE-148's review (C-2) found bypasses the
// batch verb structurally -- under PS-N the bytes happened to coincide
// because the document frame is empty, but the PROPERTY the plan's own
// entry-point crossing table asserts (a drift in semb_encode_batch's own
// composition moves witness_sha) did not hold, because nothing actually
// ran through that composition. This function now tokenizes the sixteen
// compiled-in documents exactly as before (TE-155's D-SLM6341 cut applied
// identically) and hands them to semb_interim_encode_batch_ps_n -- the
// SAME function, same one-workspace-for-the-whole-call acquisition,
// semb_encode_batch's own steps 12-13 wrap -- tapped for its serialised
// seam stream rather than its rows (see that function's own doc comment
// for the tap's exact byte layout). Concatenates u64(document_count) first
// then the tapped stream (each document's own semb_seam_serialize_document
// record, in committed order, identical to before), and SHA-256s the
// whole thing with the engine's own portable routine -- "the same routine
// model_sha uses, so the fingerprint contains one hash function and not
// two" (SuperEmbedder_Plan.md sec 4.4b). The byte sequence hashed is
// UNCHANGED from before this round (same tokenization, same cut, same
// appended token, same forward, same per-document serialisation, same
// concatenation order) -- only HOW it is produced changed, from a second
// bespoke forward to a tap on the real composition -- so the digest values
// this round's own build record quotes are byte-identical to TE-147/
// TE-155's own prior readings; the difference the property now carries is
// that a change to the batch composition itself (special-token handling,
// document-frame application once PS-1 lands, truncation ordering) moves
// this value, because it is no longer computed by code that runs alongside
// the composition -- it runs THROUGH it.
//
// Called once, from semb_encoder_open, AFTER the handle already carries a
// live cookie in the registry (so the composition function can reach it
// through the ordinary path semb_encode_batch itself would use) but BEFORE
// *out is published to the caller -- "no caller can observe a handle
// without its fingerprint" (this round's own brief). A refusal here rolls
// back the registry insertion; see semb_encoder_open's own comment at the
// call site for the exact rollback.
//
// TE-155 item 1 (D-SLM6341, ruled by the conductor under delegation,
// subject to Dan's veto): the witness must be well-defined on every
// artifact the library legally opens, including a mechanism fixture too
// small to fit the sixteen compiled-in documents under its own tokenizer
// (TE-147 sec 4's own finding -- against the mechanism pair, context_cap
// 64, the sixteen W-B documents tokenize to well over 64 ids apiece under
// a near-byte-level tokenizer). The fix is a PER-DOCUMENT CUT, not a
// refusal: each document's own tokenized content is cut to
// `context_cap - 1` ids -- BEFORE the end token is appended -- so the
// appended-token count never exceeds context_cap, and the digest is over
// what actually executed (the cut content), never over the full,
// untokenized document text. Against the real candidate (context_cap
// 32,768) this never cuts: the sixteen documents are short prose,
// tokenizing to a small fraction of that cap. Against the mechanism pair
// (cap 64) every document is cut, deterministically, to the same 63
// leading content ids on every call.
//
// Returns false on an engine refusal from the real forward (including the
// composition's own buffer-too-small path, which this call site sizes
// exactly and therefore does not expect to hit). A caller maps a false
// return to SEMB_ENGINE_REFUSED, the same status every other mid-open
// engine failure already uses.
bool ComputeWbDigest(SembInterimEncoder* interim, const superslm::TokenizerView& tokenizer,
                     uint32_t hidden_size, uint32_t context_cap,
                     std::array<uint8_t, 32>* out_digest) {
  // The composition below is reached via `interim` directly, the same
  // handle semb_interim_encode_batch_ps_n itself takes -- it needs no
  // semb_encoder cookie or HandleLease (those guard the FROZEN public ABI;
  // this is the interim layer semb_encode_batch itself calls into). The
  // handle's cookie is nonetheless already live in the registry by the
  // time this runs -- semb_encoder_open's own call-site comment states why
  // ("no caller can observe a handle without its fingerprint" is an
  // invariant about what a PUBLIC caller can reach, not a requirement this
  // function itself has).
  // D-SLM6341: the largest content-id count that leaves room for the
  // appended end token without exceeding context_cap. context_cap == 0
  // (not reachable against a real candidate; guarded rather than assumed)
  // leaves no room for even the end token alone.
  const size_t max_content_ids =
      context_cap > 0 ? static_cast<size_t>(context_cap) - 1 : 0;

  std::vector<std::vector<int32_t>> content_ids(semb::kWbCorpusDocumentCount);
  std::vector<const int32_t*> doc_ptrs(semb::kWbCorpusDocumentCount);
  std::vector<size_t> doc_lens(semb::kWbCorpusDocumentCount);
  for (size_t doc_i = 0; doc_i < semb::kWbCorpusDocumentCount; ++doc_i) {
    const semb::WbCorpusDocument& doc = semb::kWbCorpusDocuments[doc_i];
    content_ids[doc_i] = tokenizer.Encode(std::string_view(doc.text, doc.text_len));
    if (content_ids[doc_i].size() > max_content_ids) {
      // D-SLM6341's cut: keep the leading max_content_ids ids only. The
      // digest is over this cut content, not the full document -- stated
      // as fact in wb_digest_abi.h's own contract comment.
      content_ids[doc_i].resize(max_content_ids);
    }
    doc_ptrs[doc_i] = content_ids[doc_i].data();
    doc_lens[doc_i] = content_ids[doc_i].size();
  }

  // The seam tap's own required size, computed with the exact formula
  // semb_interim_encode_batch_ps_n itself checks (encoder_interim_abi.h's
  // own doc comment): 16 + n*(hidden+16) per document.
  size_t seam_required = 0;
  for (size_t doc_i = 0; doc_i < semb::kWbCorpusDocumentCount; ++doc_i) {
    const size_t n = doc_lens[doc_i] + 1;
    seam_required += 16 + n * (static_cast<size_t>(hidden_size) + 16);
  }
  std::vector<uint8_t> seam_stream(seam_required);
  size_t seam_len = 0;
  size_t failed_index = 0;
  size_t rows_required_ignored = 0;
  SembWaPoolStatus dequantize_ignored = kSembOk;
  const char* engine_status = nullptr;
  const SembInterimStatus st = semb_interim_encode_batch_ps_n(
      interim, doc_ptrs.data(), doc_lens.data(), semb::kWbCorpusDocumentCount,
      /*chunk_budget=*/0, /*out_vectors=*/nullptr, /*out_capacity_bytes=*/0,
      &rows_required_ignored, &failed_index, &dequantize_ignored, &engine_status,
      seam_stream.data(), seam_stream.size(), &seam_len);
  if (st != kSembInterimOk) return false;

  std::vector<uint8_t> stream;
  stream.reserve(8 + seam_len);
  auto put_u64 = [](std::vector<uint8_t>* buf, uint64_t v) {
    for (int i = 0; i < 8; ++i) buf->push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
  };
  put_u64(&stream, static_cast<uint64_t>(semb::kWbCorpusDocumentCount));
  stream.insert(stream.end(), seam_stream.begin(), seam_stream.begin() + seam_len);

  superslm::Sha256 hash;
  hash.Update(stream.data(), stream.size());
  hash.Final(out_digest->data());
  return true;
}

// model_sha and tokenizer_sha are computed by the CALLER, from the exact
// owned buffers semb_encoder_open reads once (sec 3.3's one-read rule) --
// BEFORE model_bytes is moved into the interim encoder's own open, which
// must happen before W-B's own forward can run. wb_digest is
// ComputeWbDigest's own output, likewise computed by the caller once the
// interim encoder and the tokenizer's resolved end-token id are both
// available (sec 3.1: "derives all five fingerprint fields ... runs the
// witness", moved here from before the interim open per this round's own
// open-sequence change).
std::array<uint8_t, 32> ComputeProvisionalFingerprint(
    const uint8_t model_sha[32], const uint8_t tokenizer_sha[32],
    const std::array<uint8_t, 32>& wb_digest) {
  uint8_t wa_sha[32], wq_sha[32];
  uint8_t wb_sha[32];
  semb_wa_digest(wa_sha);
  std::memcpy(wb_sha, wb_digest.data(), 32);
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

    // model_sha/tokenizer_sha: computed from the exact owned buffers NOW,
    // before model_bytes is moved into the interim open below (sec 3.3's
    // one-read rule -- each artifact digested from the same buffer that
    // backs the handle, never a second read). The REST of the fingerprint
    // (witness_sha, which needs W-B's own real forward) is derived further
    // down, once the interim encoder has opened (TE-147: "the open
    // sequence moves the derivation after step 8 of sec 3.1's open table
    // without changing the first refusal a caller sees").
    uint8_t model_sha[32], tokenizer_sha[32];
    Hash(model_bytes.data(), model_bytes.size(), model_sha);
    Hash(handle->tokenizer_bytes.data(), handle->tokenizer_bytes.size(), tokenizer_sha);

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

    // The handle is otherwise complete (everything but its fingerprint):
    // fill it in and register its cookie NOW, before W-B runs (TE-159,
    // C-2, D-SLM6354, the conductor's ruling). W-B's own digest must
    // derive through semb_interim_encode_batch_ps_n -- the SAME composition
    // semb_encode_batch's own steps 12-13 wrap -- and that composition is
    // the interim layer's, reached via `interim` directly rather than a
    // semb_encoder cookie; the handle is registered at this point anyway,
    // ahead of the derivation, so that from here on the invariant reads the
    // same way it will for every future caller: a live registry entry
    // reached through the ordinary path always has a real fingerprint by
    // the time anything outside this function can reach it. *out is NOT
    // written yet -- "no caller can observe a handle without its
    // fingerprint" -- so a caller can never obtain this cookie before the
    // fingerprint below is set; the window is internal to this call.
    handle->interim = interim_guard.release();
    handle->tokenizer_artifact = std::move(tokenizer_artifact);
    handle->tokenizer = std::move(tokenizer);
    handle->dims = geometry.hidden_size;
    handle->vocab_size = geometry.vocab_size;
    handle->context_cap = geometry.context_cap;
    handle->chunk_budget = 0;
    semb_encoder cookie = nullptr;
    semb_encoder_s* const h = handle.get();
    {
      std::lock_guard<std::mutex> lock(RegistryMutex());
      if (!AllocateHandleCookie(&cookie)) return SEMB_ALLOCATION_FAILED;
      const auto inserted = Registry().emplace(cookie, std::move(handle));
      if (!inserted.second) return SEMB_ENGINE_REFUSED;
    }

    // W-B: the real forward over the sixteen compiled-in documents, now
    // that the interim encoder is open and the tokenizer's own resolved
    // end-token id is known, run through the batch verb's own composition
    // (see ComputeWbDigest's own comment). Folded into witness_sha below,
    // replacing the literal kWbPendingSentinel this open used to hash. A
    // refusal here is the one new refusal point TE-147 added to open's own
    // sequence; it moves with the derivation (now after registration) but
    // stays functionally in the same place from a caller's perspective --
    // after every pre-existing failure mode, before the caller can ever
    // observe a cookie -- because the just-inserted, not-yet-published
    // entry is rolled back before returning.
    std::array<uint8_t, 32> wb_digest{};
    if (!ComputeWbDigest(h->interim, h->tokenizer, geometry.hidden_size, geometry.context_cap,
                         &wb_digest)) {
      std::lock_guard<std::mutex> lock(RegistryMutex());
      Registry().erase(cookie);
      return SEMB_ENGINE_REFUSED;
    }

    h->fingerprint = ComputeProvisionalFingerprint(model_sha, tokenizer_sha, wb_digest);
    h->wb_digest = wb_digest;

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

// TE-147 (U1 slice 2 build): W-B's own diagnostic accessor
// (`include/superembedder/witness_abi.h`; the contract of record is
// `tests/semb_wb_witness_abi_contract.h`, AMENDED TE-151 to this
// handle-scoped shape). The value is derived once, at semb_encoder_open,
// and simply returned here -- D-SLM3978's no-cache rule binds the
// FINGERPRINT derivation (no re-read of a file another field was derived
// from), not how many times this accessor is called against an
// already-open handle.
extern "C" semb_status semb_wb_digest(semb_encoder enc, uint8_t out_digest[32]) {
  if (!enc) return SEMB_NULL_ARGUMENT;
  HandleLease lease(enc);
  if (!lease.get()) return SEMB_INVALID_HANDLE;
  if (!out_digest) return SEMB_NULL_ARGUMENT;
  std::memcpy(out_digest, lease.get()->wb_digest.data(), lease.get()->wb_digest.size());
  return SEMB_OK;
}

// TE-147 (U1 slice 2 build): the bake-side corpus entry
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1; the ratified contract is
// `Claude/Fable/te96-u1-contract-closure-2026-09-05.md` sec 4.2, quoted by
// step number throughout this function). Validation is shape-before-
// content-before-work, completed before any forward; nothing is written to
// `out_rows` on any non-SEMB_OK return; `*out_required_bytes` is written on
// exactly SEMB_OK and SEMB_BUFFER_TOO_SMALL.
extern "C" semb_status semb_encode_batch(semb_encoder enc, const semb_document* docs, size_t n,
                                          float* out_rows, size_t out_capacity_bytes,
                                          size_t* out_required_bytes) {
  // Step 1: enc==NULL, out_required_bytes==NULL, or docs==NULL && n>0 (P-8's
  // span rule on the array) -> SEMB_NULL_ARGUMENT. Checked before the
  // handle needs to be live, matching the table's own step ordering.
  if (!enc || !out_required_bytes || (!docs && n > 0)) return SEMB_NULL_ARGUMENT;
  try {
    HandleLease lease(enc);
    // Step 2: enc not a live cookie -> SEMB_INVALID_HANDLE.
    if (!lease.get()) return SEMB_INVALID_HANDLE;
    semb_encoder_s* h = lease.get();

    // Step 3: n == 0 (whatever docs is) -> SEMB_CORPUS_EMPTY.
    if (n == 0) return SEMB_CORPUS_EMPTY;
    // Step 4: n > kSembMaxCorpusRows (1u << 28, FORMAT.md's kMaxBankRows),
    // checked BEFORE the multiplication -- so an oversized n with a
    // deliberately non-dereferenceable docs pointer refuses cleanly rather
    // than touching docs[0] or overflowing the size computation below.
    constexpr size_t kMaxCorpusRows = size_t{1} << 28;
    if (n > kMaxCorpusRows) return SEMB_CORPUS_TOO_LARGE;

    // Step 5: required = n * dims * 4, computed using the handle's actual
    // uint32 dimensions. n <= 2^28 (step 4) and dims <= 2^32-1, so
    // n * dims * 4 <= 2^28 * (2^32-1) * 4 < 2^62, which fits uint64
    // unconditionally; the size_t conversion is still checked so a build
    // where size_t is narrower than 62 bits refuses by name rather than
    // silently truncating.
    const uint64_t required64 =
        static_cast<uint64_t>(n) * static_cast<uint64_t>(h->dims) * 4ull;
    if (required64 > static_cast<uint64_t>(std::numeric_limits<size_t>::max())) {
      return SEMB_CORPUS_TOO_LARGE;
    }
    const size_t required = static_cast<size_t>(required64);

    // Step 6: out_rows != NULL and not 16-byte aligned -> MISALIGNED_BUFFER,
    // checked BEFORE step 7's capacity so a generously-sized-but-misaligned
    // buffer refuses for the right reason.
    if (out_rows && (reinterpret_cast<uintptr_t>(out_rows) & 15u) != 0) {
      return SEMB_MISALIGNED_BUFFER;
    }
    // Step 7: out_capacity_bytes < required -> BUFFER_TOO_SMALL, required
    // stated. The query form (NULL, 0) lands here.
    if (out_capacity_bytes < required) {
      *out_required_bytes = required;
      return SEMB_BUFFER_TOO_SMALL;
    }
    // Step 8: out_rows == NULL with sufficient capacity -> NULL_ARGUMENT,
    // distinct from the query form above (which has capacity 0).
    if (!out_rows) return SEMB_NULL_ARGUMENT;

    // Step 9: per document, in index order, the first failing document's
    // first failing check. Stops at the FIRST document that fails any
    // check; later documents (even invalid ones) are never examined.
    for (size_t i = 0; i < n; ++i) {
      const semb_document& d = docs[i];
      if (d.struct_size != sizeof(semb_document)) return SEMB_STRUCT_SIZE_MISMATCH;
      if (!d.id && d.id_len > 0) return SEMB_NULL_ARGUMENT;
      if (!d.utf8 && d.utf8_len > 0) return SEMB_NULL_ARGUMENT;
      if (d.id_len == 0) return SEMB_DOCUMENT_ID_INVALID;
      if (std::memchr(d.id, '\0', d.id_len) != nullptr) return SEMB_DOCUMENT_ID_INVALID;
      if (!ValidUtf8(d.id, d.id_len)) return SEMB_DOCUMENT_ID_INVALID;
      if (d.utf8_len == 0) return SEMB_INPUT_EMPTY;
      if (!ValidUtf8(d.utf8, d.utf8_len)) return SEMB_INVALID_UTF8;
    }

    // Step 10: uniqueness over ALL n ids, byte identity (sec 4.3: no
    // normalization, no case folding) -> DOCUMENT_ID_DUPLICATE. Reached
    // only once every document has individually passed step 9.
    {
      std::unordered_set<std::string_view> seen;
      seen.reserve(n);
      for (size_t i = 0; i < n; ++i) {
        if (!seen.emplace(std::string_view(docs[i].id, docs[i].id_len)).second) {
          return SEMB_DOCUMENT_ID_DUPLICATE;
        }
      }
    }

    // Step 11: tokenize EVERY document (up to the first cap violation), per
    // document content + 1 > context_cap -> CONTEXT_CAP_EXCEEDED. All rows
    // tokenized before any forward, so a later bad document leaves an
    // earlier good one unwritten too.
    std::vector<std::vector<int32_t>> content_ids(n);
    for (size_t i = 0; i < n; ++i) {
      content_ids[i] = h->tokenizer.Encode(std::string_view(docs[i].utf8, docs[i].utf8_len));
      // Defensive, matching the raw path's own equivalent check: zero
      // content ids is unreachable for byte-level BPE over a non-empty
      // span (utf8_len > 0 already established by step 9).
      if (content_ids[i].empty()) return SEMB_INPUT_EMPTY;
      if (content_ids[i].size() >= h->context_cap) return SEMB_CONTEXT_CAP_EXCEEDED;
    }

    // Steps 12-13: one workspace for the whole call; forward each row into
    // staged storage; any runtime refusal discards the stage entirely
    // (out_rows is only ever written on full success, step 14).
    std::vector<float> staged(n * static_cast<size_t>(h->dims));
    std::vector<const int32_t*> doc_ptrs(n);
    std::vector<size_t> doc_lens(n);
    for (size_t i = 0; i < n; ++i) {
      doc_ptrs[i] = content_ids[i].data();
      doc_lens[i] = content_ids[i].size();
    }

    SembWaPoolStatus dequantize = kSembOk;
    const char* engine_status = nullptr;
    size_t failed_index = 0;
    size_t batch_required = 0;
    const SembInterimStatus batch_status = semb_interim_encode_batch_ps_n(
        h->interim, doc_ptrs.data(), doc_lens.data(), n, h->chunk_budget, staged.data(),
        staged.size() * sizeof(float), &batch_required, &failed_index, &dequantize,
        &engine_status, /*out_seam_stream=*/nullptr, /*out_seam_stream_capacity=*/0,
        /*out_seam_stream_len=*/nullptr);
    (void)engine_status;
    (void)failed_index;  // D-SLM4653: the enum name is the whole diagnosis (sec 4.2's own note)
    // TE-159 item 6 (M-4): batch_required is written by the composed call
    // (it always equals `required`, already computed and checked at step
    // 5/7 above) and was never read afterward -- a dead store beside
    // failed_index's own explicit, named discard. Named the same way.
    (void)batch_required;
    if (batch_status != kSembInterimOk) {
      return MapInterimStatus(batch_status, dequantize);
    }

    // Step 14: copy all rows to out_rows (contiguous, row-major, stride
    // dims * 4, no padding, input order); *out_required_bytes = required.
    std::memcpy(out_rows, staged.data(), required);
    *out_required_bytes = required;
    return SEMB_OK;
  } catch (const std::bad_alloc&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (const std::length_error&) {
    return SEMB_ALLOCATION_FAILED;
  } catch (...) {
    return SEMB_ENGINE_REFUSED;
  }
}
