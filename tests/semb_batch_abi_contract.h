// TE-93: independent consumer-side pin for U1's public batch encoder verb.
#ifndef SEMB_BATCH_ABI_CONTRACT_H
#define SEMB_BATCH_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>
#include <cstring>

typedef int32_t semb_status;
enum : int32_t { SEMB_OK = 0 };

struct semb_encoder_opaque;
typedef struct semb_encoder_opaque* semb_encoder;

struct semb_config {
  uint32_t struct_size;
  const char* model_path;
  size_t model_path_len;
  const char* tokenizer_path;
  size_t tokenizer_path_len;
  int32_t appended_token_id;
  uint32_t max_concurrency;
};

struct semb_fingerprint {
  uint32_t struct_size;
  uint8_t digest[32];
};

// D-SLM6314 follow-on reading, routed to the planner: bank IDs are the unique
// UTF-8 string IDs SuperFAISS persists; text is the raw document span.
struct semb_document {
  uint32_t struct_size;
  const char* id;
  size_t id_len;
  const char* utf8;
  size_t utf8_len;
};

static_assert(offsetof(semb_document, struct_size) == 0);

extern "C" {
semb_status semb_encoder_open(const semb_config* cfg, semb_encoder* out);
semb_status semb_encoder_close(semb_encoder enc);
semb_status semb_encoder_dims(semb_encoder enc, uint32_t* out_dims);
semb_status semb_encode(semb_encoder enc, const char* utf8, size_t utf8_len,
                        float* out_vector, size_t out_capacity_bytes,
                        size_t* out_required_bytes,
                        semb_fingerprint* out_fingerprint);
semb_status semb_encode_batch(semb_encoder enc, const semb_document* docs,
                              size_t n, float* out_rows,
                              size_t out_capacity_bytes,
                              size_t* out_required_bytes);
const char* semb_status_name(semb_status s);
}

inline int32_t BatchStatusByName(const char* name) {
  for (int32_t value = 0; value < 4096; ++value) {
    const char* observed = semb_status_name(value);
    if (observed && std::strcmp(observed, name) == 0) return value;
  }
  return -1;
}

#endif
