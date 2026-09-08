// SuperEmbedder's frozen public C ABI.
#ifndef SUPEREMBEDDER_SEMB_H
#define SUPEREMBEDDER_SEMB_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct semb_encoder_s* semb_encoder;

// sec 3.1 item 5: library-owned, opaque, not copyable, released only by
// semb_bank_close; a double close returns SEMB_INVALID_HANDLE. A distinct
// opaque tag from semb_encoder/semb_query -- the three handle kinds are
// never interchangeable (tests/semb_bank_abi_contract.h, TE-163/TE-166).
typedef struct semb_bank_opaque* semb_bank;

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
  X(SEMB_ALLOCATION_FAILED,        17) \
  X(SEMB_CORPUS_EMPTY,             18) \
  X(SEMB_DOCUMENT_ID_INVALID,      19) \
  X(SEMB_DOCUMENT_ID_DUPLICATE,    20) \
  X(SEMB_CORPUS_TOO_LARGE,         21) \
  X(SEMB_FINGERPRINT_MISMATCH,             22) \
  X(SEMB_MANIFEST_SCHEMA_UNSUPPORTED,      23) \
  X(SEMB_BANK_SIZE_MISMATCH,               24) \
  X(SEMB_ARTIFACT_SHA_MISMATCH,            25) \
  X(SEMB_ADAPTER_ID_MISMATCH,              26) \
  X(SEMB_PS_VERSION_LABEL_MISMATCH,        27) \
  X(SEMB_BANK_IDS_COUNT_MISMATCH,          28) \
  X(SEMB_BANK_NONFINITE_ROW,               29) \
  X(SEMB_BANK_ZERO_NORM_ROW,               30) \
  X(SEMB_BANK_GEOMETRY_CEILING_EXCEEDED,   31)

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

// The bake-side corpus entry's per-document argument
// (`Claude/Fable/te96-u1-contract-closure-2026-09-05.md` sec 4.1). The id is
// opaque bytes to the library: validated, never interpreted, never
// tokenized, never digested by any fingerprint field.
typedef struct semb_document semb_document;
struct semb_document {
  uint32_t struct_size;    // sizeof(semb_document), validated exactly, per document
  const char* id;          // the row's id, sized UTF-8 span; required iff id_len > 0
  size_t id_len;            // > 0: every document carries an id (plan sec 3.4)
  const char* utf8;         // the document text, sized UTF-8 span; required iff utf8_len > 0
  size_t utf8_len;
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
// The bake-side corpus entry (`Claude/Fable/te96-u1-contract-closure-2026-09-05.md`
// sec 4.2). Validation is shape-before-content-before-work; nothing is
// written to `out_rows` on any non-SEMB_OK return; `*out_required_bytes` is
// written on exactly SEMB_OK and SEMB_BUFFER_TOO_SMALL.
semb_status semb_encode_batch(semb_encoder enc, const semb_document* docs, size_t n,
                              float* out_rows, size_t out_capacity_bytes,
                              size_t* out_required_bytes);
// Opens and validates a `.wvbank`/`.semb.json` triple named by the shared
// stem `path` (sized UTF-8 span, `path_len` bytes, never NUL-terminated);
// owns the bank's own expected fingerprint, read from the manifest. `*out`
// is set to a live handle only on SEMB_OK; every refusal leaves
// `*out == NULL` (when `out` is non-NULL) (`Claude/Plans/SuperEmbedder_Plan.md`
// sec 3.1; `tests/semb_bank_abi_contract.h`).
semb_status semb_bank_open(const char* path, size_t path_len, semb_bank* out);
// Releases the handle. `SEMB_BANK_IN_USE` (a live query-handle reference
// count) is Slice 5's own and is not tracked by this slice.
semb_status semb_bank_close(semb_bank bank);
const char* semb_status_name(semb_status s);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // SUPEREMBEDDER_SEMB_H
