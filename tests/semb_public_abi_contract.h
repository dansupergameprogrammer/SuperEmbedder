// tests/semb_public_abi_contract.h -- TE-92 (U1, the first frozen public
// raw-text vertical slice): the test author's concrete pin of the FIVE
// frozen `semb_*` verbs this slice ships, exactly as
// `Claude/Plans/SuperEmbedder_Plan.md` sec 3.1 ("The C ABI, frozen --
// enumerated HERE and nowhere else", D-SLM4646) states their signatures:
//
//   semb_status semb_encoder_open(const semb_config* cfg, semb_encoder* out)
//   semb_status semb_encoder_close(semb_encoder enc)
//   semb_status semb_encoder_dims(semb_encoder enc, uint32_t* out_dims)
//   semb_status semb_encode(semb_encoder enc, const char* utf8, size_t utf8_len,
//                           float* out_vector, size_t out_capacity_bytes,
//                           size_t* out_required_bytes, semb_fingerprint* out_fingerprint)
//   const char* semb_status_name(semb_status s)
//
// Like `tests/semb_seam_abi_contract.h` (TE-62) this is the suite's OWN
// header, not a copy of a product header: none of these symbols is defined
// anywhere in `superembedder` at main@1a040a4 (the only encoder surface is
// the explicitly INTERIM `semb_interim_*` handle in
// include/superembedder/encoder_abi.h), so every cell that links against
// this header fails to LINK until the builder lands the frozen surface.
// `tests/u1_public_header_parity_check.py` then holds the builder's
// `include/superembedder/semb.h` to the declarations below.
//
// WHAT SEC 3.1 FIXES, AND WHAT IT LEAVES TO THE BUILDER (each stated so the
// pin is checkable rather than silently invented):
//
//   * The five signatures, verbatim from the table.
//   * `semb_status`: "the enum is closed and follows the sslm_* convention:
//     append, never renumber". Sec 3.1 names the members and NOT their
//     values, so this header pins exactly ONE value -- SEMB_OK == 0, the
//     convention every existing `kSemb*Ok = 0` enum in this project already
//     follows -- and every other status is resolved AT RUN TIME BY NAME
//     through `semb_status_name` (StatusByName below), which is how a
//     consumer reads a refusal anyway (D-SLM4653: the name is the ABI's only
//     error surface). The builder's numbering is therefore free; the NAMES
//     are frozen.
//   * `semb_encoder`: "every opaque handle is library-owned, released only by
//     its matching close verb, not copyable" -- pinned as a pointer to an
//     incomplete struct (a C caller cannot size, copy or construct one).
//   * `semb_config` (an IN struct with `uint32_t struct_size` first, sec 3.1
//     item 6, and `max_concurrency`, sec 3.1's concurrency paragraph): the
//     plan enumerates NO other member. This slice needs a model artifact, a
//     tokenizer artifact (the ratified candidate's converter-emitted
//     tokenizer is a separate `.sslm`, E0b), and PS-N's appended token id
//     (sec 3.2; a property of the candidate, taken as an argument by the
//     interim verb for exactly the reason it is taken here -- the synthetic
//     mechanism fixtures have no id 151643). Paths are sized spans, the
//     shape `semb_bank_open(const char* path, size_t path_len, ...)` already
//     uses. THIS MEMBER LIST IS THE TEST AUTHOR'S READING OF A GAP IN THE
//     PLAN, routed to the planner in the TE-92 test-design record; the
//     builder ships exactly this layout or the planner rules otherwise.
//   * `semb_fingerprint` (an IN struct, sec 3.1 item 6): sec 3.3 defines the
//     fingerprint as one SHA-256 over five length-prefixed fields; only
//     `struct_size` and the 32-byte digest are pinned here. The five-field
//     derivation and the witness are NOT this slice's claim (sec 7's U1 row
//     lists them separately); this slice's cells assert only the struct's
//     validation and its stability across encodes on one handle.
#ifndef SEMB_PUBLIC_ABI_CONTRACT_H
#define SEMB_PUBLIC_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>
#include <cstring>

// sec 3.1 item 1: every verb returns semb_status except semb_status_name.
// A 32-bit integer type whose named values the builder's closed enum
// supplies; SEMB_OK is the one value this suite pins.
typedef int32_t semb_status;
enum : int32_t { SEMB_OK = 0 };

// sec 3.1 item 5: library-owned, opaque, not copyable, released only by
// semb_encoder_close; a double close returns SEMB_INVALID_HANDLE.
struct semb_encoder_opaque;
typedef struct semb_encoder_opaque* semb_encoder;

// sec 3.1 item 6: an IN struct, `struct_size` first, validated on entry
// (SEMB_STRUCT_SIZE_MISMATCH). Sized UTF-8 path spans (item 2's convention
// applied to paths, as semb_bank_open's signature already does).
struct semb_config {
  uint32_t struct_size;         // sizeof(semb_config)
  const char* model_path;       // the converted model .sslm
  size_t model_path_len;
  const char* tokenizer_path;   // the converter-emitted tokenizer .sslm
  size_t tokenizer_path_len;
  int32_t appended_token_id;    // PS-N's single fixed end token id (sec 3.2): 151643 for the candidate
  uint32_t max_concurrency;     // sec 3.1 concurrency: the per-call workspace pool size (default 1)
};

// sec 3.1 item 6 + sec 3.3: struct_size first; the encoder fingerprint is one
// 32-byte SHA-256 digest.
struct semb_fingerprint {
  uint32_t struct_size;         // sizeof(semb_fingerprint)
  uint8_t digest[32];           // encoder_fingerprint (sec 3.3), written on SEMB_OK
};

static_assert(sizeof(semb_status) == 4, "semb_status is a 32-bit status");
static_assert(sizeof(semb_encoder) == sizeof(void*), "semb_encoder is an opaque pointer handle");
static_assert(offsetof(semb_config, struct_size) == 0, "struct_size is the first member (sec 3.1 item 6)");
static_assert(offsetof(semb_fingerprint, struct_size) == 0, "struct_size is the first member (sec 3.1 item 6)");

extern "C" {

semb_status semb_encoder_open(const semb_config* cfg, semb_encoder* out);
semb_status semb_encoder_close(semb_encoder enc);
semb_status semb_encoder_dims(semb_encoder enc, uint32_t* out_dims);
semb_status semb_encode(semb_encoder enc, const char* utf8, size_t utf8_len, float* out_vector,
                        size_t out_capacity_bytes, size_t* out_required_bytes,
                        semb_fingerprint* out_fingerprint);
const char* semb_status_name(semb_status s);

}  // extern "C"

namespace semb_contract {

// The plan's caller-facing status vocabulary this slice can reach (sec 3.1's
// frozen properties, sec 8 C4). Every one of these NAMES must be returned by
// semb_status_name for some value; the values are the builder's.
inline const char* const kSliceStatusNames[] = {
    "SEMB_OK",
    "SEMB_NULL_ARGUMENT",
    "SEMB_STRUCT_SIZE_MISMATCH",
    "SEMB_INVALID_HANDLE",
    "SEMB_BUFFER_TOO_SMALL",
    "SEMB_MISALIGNED_BUFFER",
    "SEMB_INPUT_EMPTY",
    "SEMB_ENGINE_REFUSED",
};
inline constexpr size_t kSliceStatusNameCount = sizeof(kSliceStatusNames) / sizeof(kSliceStatusNames[0]);

// The rest of sec 3.1's/sec 8's caller-facing vocabulary: reported by the
// status-name coverage cell as present or absent, never required by this
// slice (their verbs are not in it).
inline const char* const kPlanStatusNames[] = {
    "SEMB_INPUT_TOO_SHORT",
    "SEMB_FINGERPRINT_MISMATCH",
    "SEMB_CONCURRENCY_EXCEEDED",
    "SEMB_HANDLE_IN_USE",
    "SEMB_BANK_IN_USE",
    "SEMB_MANIFEST_SCHEMA_UNSUPPORTED",
    "SEMB_BANK_SIZE_MISMATCH",
    "SEMB_ARTIFACT_SHA_MISMATCH",
    "SEMB_TEMPLATE_TOKEN_ABSENT",
    "SEMB_POOLED_SUBNORMAL",
    "SEMB_POOLED_OVERFLOW",
    "SEMB_ACCUMULATOR_OVERFLOW",
    "SEMB_CORPUS_EMPTY",
    "SEMB_EPOCH_BYTES_DIVERGED",
    "SEMB_EPOCH_LINEAGE_DIVERGED",
    "SEMB_EPOCH_ENTRY_MODIFIED",
};
inline constexpr size_t kPlanStatusNameCount = sizeof(kPlanStatusNames) / sizeof(kPlanStatusNames[0]);

// The range scanned when resolving a status by name. Sec 3.1 does not bound
// the enum; a closed, append-only enum of a few dozen members sits far
// inside this.
inline constexpr int32_t kStatusScanLimit = 4096;

// Resolves the value whose semb_status_name is exactly `name`, scanning
// [0, kStatusScanLimit). Returns -1 when no value carries that name.
inline int32_t StatusByName(const char* name) {
  for (int32_t v = 0; v < kStatusScanLimit; ++v) {
    const char* n = semb_status_name(v);
    if (n && std::strcmp(n, name) == 0) return v;
  }
  return -1;
}

}  // namespace semb_contract

#endif  // SEMB_PUBLIC_ABI_CONTRACT_H
