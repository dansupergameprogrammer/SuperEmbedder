// tests/semb_public_abi_contract.h -- TE-92 (U1, the first frozen public
// raw-text vertical slice), RE-ENTERED at TE-94 (the planner's D-SLM6314
// resolution, P-1..P-9 accepted by the conductor): the test author's concrete
// pin of the FIVE frozen `semb_*` verbs this slice ships, exactly as
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
// header, not a copy of a product header. `tests/u1_public_header_parity_check.py`
// holds the builder's `include/superembedder/semb.h` to the declarations
// below, declaration by declaration, ordinal by ordinal.
//
// WHAT THE ACCEPTED RESOLUTION FIXES (the planner's record
// `Claude/Fable/te92-d-slm6314-planner-resolution-2026-09-04.md`, sec 3-6;
// its P-1..P-8), each stated so the pin is checkable rather than invented:
//
//   * P-1  `semb_config` is SIX members and carries NO appended-token member:
//          open derives the end token by resolving the compiled-in literal
//          `<|endoftext|>` through the tokenizer artifact's own special table
//          (exactly one id, else SEMB_TEMPLATE_TOKEN_ABSENT). The vocabulary
//          join (`TokenizerView::VocabSize() <= model vocab_size`, else
//          SEMB_TOKENIZER_MODEL_MISMATCH) bounds it by construction.
//   * P-2  `semb_fingerprint` is `{struct_size, digest[32]}`, opaque.
//   * P-3  The U1 provisional tag `SEMBP001` in digest[0..7] is a value
//          convention, not a layout feature (K-14b asserts it until the
//          five-field derivation lands and flips that cell).
//   * P-4  SEMB_ENGINE_REFUSED is reserved for a status that ORIGINATES in
//          the engine; SuperEmbedder's own refusals are named for what it
//          found: SEMB_ARTIFACT_UNREADABLE, SEMB_TOKENIZER_MODEL_MISMATCH,
//          SEMB_TEMPLATE_TOKEN_ABSENT, SEMB_INVALID_UTF8,
//          SEMB_CONTEXT_CAP_EXCEEDED. SEMB_INVALID_ARGUMENT is REMOVED.
//   * P-5  The enum carries EXPLICIT ORDINALS 0-17 in the order below,
//          generated from ONE list (SEMB_CONTRACT_STATUS_LIST) with its name
//          table, SEMB_STATUS_NEXT_FREE last; the last renumber, append-only
//          from this header on. THIS header is the one generated source the
//          suite reads the list from: the C++ cells (via the enum and the
//          name table) and the Python header-parity check (which parses the
//          X-macro text below) both derive from it, so a name cannot land in
//          one and not the other.
//   * P-6  Refusal precedence is fixed (open: the planner's sec 5.6; encode:
//          sec 5.7, with the conductor's dispatch clarification that the
//          too-small-capacity answer precedes content examination, the text
//          pointer included; close/dims: sec 5.8). Nothing is written to the
//          vector or the fingerprint on any non-SEMB_OK return;
//          *out_required_bytes is written on exactly SEMB_OK and
//          SEMB_BUFFER_TOO_SMALL; *out = NULL on every refused open when
//          `out` is non-NULL -- including a NULL `cfg`.
//   * P-7  A NULL handle to close/dims/encode is SEMB_NULL_ARGUMENT;
//          SEMB_INVALID_HANDLE is reserved for a non-NULL value that names no
//          live handle.
//   * P-8  A sized span's pointer is required iff its length is nonzero:
//          `(NULL, 0)` text is SEMB_INPUT_EMPTY, `(NULL, n>0)` is
//          SEMB_NULL_ARGUMENT; the config's path spans follow the same rule
//          (`(NULL, 0)` path = an unreadable artifact, SEMB_ARTIFACT_UNREADABLE).
//
// TE-145 (U1 Slice 2, `Claude/Fable/te96-u1-contract-closure-2026-09-05.md`
// sec 4.4, P-5): four statuses APPENDED for `semb_encode_batch`
// (`tests/semb_batch_abi_contract.h`), ordinals 18-21, SEMB_STATUS_NEXT_FREE
// now 22. This is the append this header's own comment above promises --
// "the last renumber, append-only from this header on" -- landing for the
// first time. SEMB_CORPUS_EMPTY moves from kPlanStatusNames (below, "named
// in the plan, not yet required by any verb this slice pins") into the real
// list, since TE-96 sec 4.2 step 3 now requires it of a frozen verb.
//
// TE-163 (U1 Slice 4, `Claude/Bach/briefs/te163-slice4-red.md`): six
// statuses APPENDED for the bank pair / manifest sidecar and the internal
// bake primitive (`tests/semb_bake_abi_contract.h`, `tests/semb_bank_abi_contract.h`),
// ordinals 22-27, SEMB_STATUS_NEXT_FREE now 28 -- the plan's own C18 row
// (`SuperEmbedder_Plan.md` sec 8, "validation symmetry across entry paths")
// names all four of SEMB_FINGERPRINT_MISMATCH / SEMB_MANIFEST_SCHEMA_UNSUPPORTED
// / SEMB_BANK_SIZE_MISMATCH / SEMB_ARTIFACT_SHA_MISMATCH as `semb_bank_open`
// outcomes (D-SLM4649), and sec 3.4's label-check table names the two C34
// manifest-honesty statuses (SEMB_ADAPTER_ID_MISMATCH, SEMB_PS_VERSION_LABEL_MISMATCH)
// as bake outcomes. All six move from kPlanStatusNames (below) into the real
// list except SEMB_BANK_IN_USE, which stays there -- it is Slice 5's own
// (no `semb_query` handle exists yet to hold the reference count `semb_bank_close`
// would refuse against).
//
// TE-183 (D-SLM6393 item 1, D-SLM6410): four statuses APPENDED for the four
// `semb_bank_open` refusal classes TE-163's own cell 2 drives by value but
// this header left unpinned (D-SLM6392) -- SEMB_BANK_IDS_COUNT_MISMATCH,
// SEMB_BANK_NONFINITE_ROW, SEMB_BANK_ZERO_NORM_ROW,
// SEMB_BANK_GEOMETRY_CEILING_EXCEEDED -- ordinals 28-31,
// SEMB_STATUS_NEXT_FREE now 32. Provisional on the quarantined branch only
// (D-SLM6393); the plan-of-record amendment naming them is owed to the
// planner's next fold. None of the four was ever in kPlanStatusNames, so
// nothing moves out of it this round.
//
// STATUSES ARE PINNED BY NAME AND BY ORDINAL, AND THE CELLS COMPARE BY NAME.
// Behavioural cells resolve every status through `semb_status_name` (StatusByName
// below) so that a cell is red for its own reason -- a behaviour that differs
// -- and never merely because an ordinal moved; the ordinal pin is its OWN
// cell (K-07i), red on its own when the product's numbering differs, and
// the header-parity check pins the ordinals structurally.
//
// DIAGNOSTIC-ONLY LEGACY LAYOUT (never a contract): compiled with
// SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER defined, `semb_config` regains
// the `496d036` seven-member layout (an `int32_t appended_token_id` before
// `max_concurrency`) so that tests/u1_raw_text_cells_check.py's
// `--diag-legacy-layout` pass can attribute EACH cell's own red against a
// product still carrying the retired layout, instead of every cell refusing
// at open with SEMB_STRUCT_SIZE_MISMATCH. That pass reports [DIAG] lines
// only; it is never the suite's verdict, and the default build has no such
// member.
#ifndef SEMB_PUBLIC_ABI_CONTRACT_H
#define SEMB_PUBLIC_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>
#include <cstring>

// sec 3.1 item 1: every verb returns semb_status except semb_status_name.
// A 32-bit integer type whose values the list below fixes (P-5).
typedef int32_t semb_status;

// P-5: the final pre-release status list, ONE generated source. Explicit
// ordinals, in this order, SEMB_STATUS_NEXT_FREE last. Append only.
#define SEMB_CONTRACT_STATUS_LIST(X) \
  X(SEMB_OK,                        0) \
  X(SEMB_NULL_ARGUMENT,             1) \
  X(SEMB_STRUCT_SIZE_MISMATCH,      2) \
  X(SEMB_INVALID_HANDLE,            3) \
  X(SEMB_HANDLE_IN_USE,             4) \
  X(SEMB_CONCURRENCY_EXCEEDED,      5) \
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

enum : int32_t {
#define SEMB_CONTRACT_STATUS_ENUM_(name, value) name = value,
  SEMB_CONTRACT_STATUS_LIST(SEMB_CONTRACT_STATUS_ENUM_)
#undef SEMB_CONTRACT_STATUS_ENUM_
  SEMB_STATUS_NEXT_FREE  // the sentinel: never returned, never a valid argument, never named
};

static_assert(SEMB_STATUS_NEXT_FREE == 32, "the contract pins 32 named statuses, ordinals 0-31 (TE-183 appends 28-31)");

// sec 3.1 item 5: library-owned, opaque, not copyable, released only by
// semb_encoder_close; a double close returns SEMB_INVALID_HANDLE.
struct semb_encoder_opaque;
typedef struct semb_encoder_opaque* semb_encoder;

// sec 3.1 item 6: an IN struct, `struct_size` first, validated on entry
// (SEMB_STRUCT_SIZE_MISMATCH, exact). Sized UTF-8 path spans (item 2's
// convention applied to paths, the shape semb_bank_open already uses); P-8's
// span rule governs them. P-1: no token id member.
struct semb_config {
  uint32_t struct_size;         // sizeof(semb_config), validated exactly
  const char* model_path;       // the converted model .sslm (sized span; required iff len > 0)
  size_t model_path_len;
  const char* tokenizer_path;   // the converter-emitted tokenizer .sslm (sized span; required iff len > 0)
  size_t tokenizer_path_len;
#ifdef SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER
  int32_t appended_token_id;    // DIAGNOSTIC ONLY: the retired 496d036 member (see the header comment)
#endif
  uint32_t max_concurrency;     // sec 3.1 concurrency: the workspace pool size; 0 selects the default of 1 (D-10)
};

// sec 3.1 item 6 + sec 3.3, P-2/P-3: struct_size first; the encoder
// fingerprint is one opaque 32-byte value, written only on SEMB_OK.
struct semb_fingerprint {
  uint32_t struct_size;         // sizeof(semb_fingerprint), validated exactly
  uint8_t digest[32];           // encoder_fingerprint (sec 3.3); SEMBP001 in [0..7] while provisional (P-3)
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

// The one name table, generated from the same list as the enum above.
struct StatusEntry {
  const char* name;
  int32_t value;
};

inline const StatusEntry kStatusTable[] = {
#define SEMB_CONTRACT_STATUS_ENTRY_(name, value) {#name, value},
    SEMB_CONTRACT_STATUS_LIST(SEMB_CONTRACT_STATUS_ENTRY_)
#undef SEMB_CONTRACT_STATUS_ENTRY_
};
inline constexpr size_t kStatusCount = sizeof(kStatusTable) / sizeof(kStatusTable[0]);
static_assert(kStatusCount == 32, "32 named statuses (TE-183 appends 28-31)");

// The name every non-member int32_t resolves to (P-5: static storage, never NULL).
inline constexpr const char* kUnknownStatusName = "SEMB_UNKNOWN";

// The provisional fingerprint tag (P-3): a value convention, not a member.
inline constexpr char kProvisionalFingerprintTag[8] = {'S', 'E', 'M', 'B', 'P', '0', '0', '1'};

// The compiled-in end-token literal open resolves through the tokenizer
// artifact (plan sec 3.2; P-1).
inline constexpr const char* kCanonicalEndToken = "<|endoftext|>";

// The rest of sec 3.1's/sec 8's caller-facing vocabulary: reported by the
// status-name coverage cell as present or absent, never required by this
// slice (their verbs are not in it; P-5 appends each when its verb lands).
// TE-163: the four C18 names and the two C34 label names moved out of this
// list into SEMB_CONTRACT_STATUS_LIST above, landing as ordinals 22-27.
// SEMB_BANK_IN_USE stays here -- Slice 5's own (D-SLM4664: a live-query-
// handle reference count on the bank, and no `semb_query` handle exists
// yet to hold one).
inline const char* const kPlanStatusNames[] = {
    "SEMB_INPUT_TOO_SHORT",
    "SEMB_BANK_IN_USE",
    "SEMB_ACCUMULATOR_OVERFLOW",
    "SEMB_EPOCH_BYTES_DIVERGED",
    "SEMB_EPOCH_LINEAGE_DIVERGED",
    "SEMB_EPOCH_ENTRY_MODIFIED",
};
inline constexpr size_t kPlanStatusNameCount = sizeof(kPlanStatusNames) / sizeof(kPlanStatusNames[0]);

// Names retired by the resolution (P-4): a product that still names one of
// these anywhere in [0, kStatusScanLimit) fails K-07k.
inline const char* const kRetiredStatusNames[] = {
    "SEMB_INVALID_ARGUMENT",
};
inline constexpr size_t kRetiredStatusNameCount = sizeof(kRetiredStatusNames) / sizeof(kRetiredStatusNames[0]);

// The range scanned when resolving a status by name. A closed, append-only
// enum of a few dozen members sits far inside this.
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
