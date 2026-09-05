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
typedef enum semb_status {
  SEMB_OK = 0,
  SEMB_NULL_ARGUMENT,
  SEMB_STRUCT_SIZE_MISMATCH,
  SEMB_INVALID_ARGUMENT,
  SEMB_INVALID_HANDLE,
  SEMB_HANDLE_IN_USE,
  SEMB_CONCURRENCY_EXCEEDED,
  SEMB_BUFFER_TOO_SMALL,
  SEMB_MISALIGNED_BUFFER,
  SEMB_INVALID_UTF8,
  SEMB_INPUT_EMPTY,
  SEMB_CONTEXT_CAP_EXCEEDED,
  SEMB_ENGINE_REFUSED,
  SEMB_POOLED_SUBNORMAL,
  SEMB_POOLED_OVERFLOW,
  SEMB_ALLOCATION_FAILED,
  SEMB_STATUS_NEXT_FREE
} semb_status;

// Paths are sized byte spans and need not be NUL-terminated. The appended
// token id is an assertion of the tokenizer artifact's <|endoftext|> id, not
// a selectable encoding parameter; open refuses a mismatch. A zero
// concurrency value selects the default of one workspace.
typedef struct semb_config semb_config;
struct semb_config {
  uint32_t struct_size;
  const char* model_path;
  size_t model_path_len;
  const char* tokenizer_path;
  size_t tokenizer_path_len;
  int32_t appended_token_id;
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
