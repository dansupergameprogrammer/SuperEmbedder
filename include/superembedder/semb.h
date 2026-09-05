// SuperEmbedder's frozen public C ABI.
#ifndef SUPEREMBEDDER_SEMB_H
#define SUPEREMBEDDER_SEMB_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct semb_encoder_s* semb_encoder;

// Closed and append-only: existing names and ordinals never move.
#define SEMB_STATUS_ENUM_LIST(X) \
  X(SEMB_OK,                        0) \
  X(SEMB_NULL_ARGUMENT,             1) \
  X(SEMB_STRUCT_SIZE_MISMATCH,       2) \
  X(SEMB_INVALID_HANDLE,            3) \
  X(SEMB_HANDLE_IN_USE,             4) \
  X(SEMB_CONCURRENCY_EXCEEDED,       5) \
  X(SEMB_BUFFER_TOO_SMALL,          6) \
  X(SEMB_MISALIGNED_BUFFER,         7) \
  X(SEMB_INPUT_EMPTY,               8) \
  X(SEMB_INVALID_UTF8,              9) \
  X(SEMB_CONTEXT_CAP_EXCEEDED,     10) \
  X(SEMB_ARTIFACT_UNREADABLE,      11) \
  X(SEMB_ENGINE_REFUSED,           12) \
  X(SEMB_TOKENIZER_MODEL_MISMATCH, 13) \
  X(SEMB_TEMPLATE_TOKEN_ABSENT,    14) \
  X(SEMB_POOLED_SUBNORMAL,         15) \
  X(SEMB_POOLED_OVERFLOW,          16) \
  X(SEMB_ALLOCATION_FAILED,        17)

typedef enum semb_status {
#define SEMB_STATUS_ENUM_VALUE_(name, value) name = value,
  SEMB_STATUS_ENUM_LIST(SEMB_STATUS_ENUM_VALUE_)
#undef SEMB_STATUS_ENUM_VALUE_
  SEMB_STATUS_NEXT_FREE
} semb_status;

// Paths are sized byte spans and need not be NUL-terminated. Open derives
// the appended end token from the tokenizer artifact's <|endoftext|> id. A zero
// concurrency value selects the default of one workspace.
typedef struct semb_config semb_config;
struct semb_config {
  uint32_t struct_size;
  const char* model_path;
  size_t model_path_len;
  const char* tokenizer_path;
  size_t tokenizer_path_len;
  uint32_t max_concurrency;
};

typedef struct semb_fingerprint semb_fingerprint;
struct semb_fingerprint {
  uint32_t struct_size;
  uint8_t digest[32];
};

// U1's raw-text slice does not yet carry the certified W-B, W-Q, and epoch
// fields required by the final five-field fingerprint. Successful encodes are
// therefore marked in-band: digest[0..7] equals this eight-byte tag. Consumers
// MUST reject tagged values as persistent bank/query compatibility identities.
// The tag disappears only when the complete certified derivation replaces it.
#define SEMB_FINGERPRINT_PROVISIONAL_TAG "SEMBP001"
#define SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE 8u

semb_status semb_encoder_open(const semb_config* cfg, semb_encoder* out);
semb_status semb_encoder_close(semb_encoder enc);
semb_status semb_encoder_dims(semb_encoder enc, uint32_t* out_dims);
semb_status semb_encode(semb_encoder enc, const char* utf8, size_t utf8_len,
                        float* out_vector, size_t out_capacity_bytes,
                        size_t* out_required_bytes,
                        semb_fingerprint* out_fingerprint);
const char* semb_status_name(semb_status s);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // SUPEREMBEDDER_SEMB_H
