// tests/semb_batch_abi_contract.h -- TE-145 (U1 slice 2): the test author's
// concrete pin of `semb_encode_batch` and its `semb_document` argument, as
// ratified by `Claude/Fable/te96-u1-contract-closure-2026-09-05.md` sec 4
// (P-5, the batch contract closure) against the frozen signature
// `Claude/Plans/SuperEmbedder_Plan.md` sec 3.1 (D-SLM4646):
//
//   semb_status semb_encode_batch(semb_encoder enc, const semb_document* docs,
//                                  size_t n, float* out_rows,
//                                  size_t out_capacity_bytes,
//                                  size_t* out_required_bytes)
//
// Like `tests/semb_seam_abi_contract.h` and `tests/semb_wa_pool_abi_contract.h`
// this is the suite's OWN header, not a copy of a product header -- the
// batch verb does not exist anywhere in `superembedder` yet (confirmed:
// `git grep -n semb_encode_batch src/ include/` at this branch's own base
// `c0f52d4` returns nothing), so every test that includes this header and
// calls semb_encode_batch fails to LINK until the builder's round adds it.
// The status ordinals 18-21 it needs are pinned in
// `tests/semb_public_abi_contract.h` (TE-145 append; see that header's own
// TE-145 comment) -- a TU that needs both includes semb_public_abi_contract.h
// FIRST, then this header, exactly as existing TUs already combine
// semb_public_abi_contract.h with semb_seam_abi_contract.h or
// semb_wa_pool_abi_contract.h (each contract header owns only the symbols
// IT adds; nothing here redeclares semb_encoder_open/_close/_dims/semb_encode/
// semb_status_name or the semb_status enum).
//
// LAYOUT ARITHMETIC IS PINNED, NEVER A HARDCODED NUMBER (TE-96 sec 4.1's own
// text: "the suite pins sizeof and offsetof, never the number: 40 bytes
// under LP64/LLP64 ... 20 bytes under ILP32"). The static_asserts below
// state member order and the ABSENCE of inter-member padding by comparing
// each field's offset against the running sum of the preceding fields'
// sizes -- never a literal byte count -- so the same header is exact on
// both pointer widths without a `#if` on the platform.
#ifndef SEMB_BATCH_ABI_CONTRACT_H
#define SEMB_BATCH_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>

// TE-96 sec 4.1: the ruled layout -- struct_size first (sec 3.1 item 6),
// then a sized id span, then a sized text span. The id is opaque bytes to
// the library: validated (sec 4.2 step 9), never interpreted, never
// tokenized, never digested by any fingerprint field (sec 4.5).
struct semb_document {
  uint32_t struct_size;  // sizeof(semb_document), validated exactly, per document (step 9)
  const char* id;        // the row's id, sized UTF-8 span; required iff id_len > 0
  size_t id_len;          // > 0: every document carries an id (plan sec 3.4)
  const char* utf8;       // the document text, sized UTF-8 span; required iff utf8_len > 0
  size_t utf8_len;
};

// Member order and padding-freedom, pinned structurally rather than by a
// literal sizeof(). `RoundUp` is the ONLY platform-dependent arithmetic
// here, and it is the compiler's own alignment rule stated as a formula,
// never a number this file writes down (TE-96 sec 4.1: "the suite pins
// sizeof and offsetof, never the number") -- exact on LP64/LLP64 and ILP32
// alike without a `#if` on the platform.
namespace semb_batch_contract_detail {
constexpr size_t RoundUp(size_t value, size_t align) {
  return (value + align - 1) / align * align;
}
}  // namespace semb_batch_contract_detail

static_assert(offsetof(semb_document, struct_size) == 0,
              "struct_size is the first member (sec 3.1 item 6)");
static_assert(offsetof(semb_document, id) ==
                  semb_batch_contract_detail::RoundUp(sizeof(uint32_t), alignof(const char*)),
              "id follows struct_size at exactly the compiler's own natural alignment, no hand-placed gap");
static_assert(offsetof(semb_document, id_len) == offsetof(semb_document, id) + sizeof(const char*),
              "id_len immediately follows id, no padding between two same-alignment members");
static_assert(offsetof(semb_document, utf8) == offsetof(semb_document, id_len) + sizeof(size_t),
              "utf8 immediately follows id_len, no padding between two same-alignment members");
static_assert(offsetof(semb_document, utf8_len) == offsetof(semb_document, utf8) + sizeof(const char*),
              "utf8_len immediately follows utf8, no padding between two same-alignment members");
static_assert(sizeof(semb_document) ==
                  semb_batch_contract_detail::RoundUp(offsetof(semb_document, utf8_len) + sizeof(size_t),
                                                       alignof(semb_document)),
              "no trailing padding beyond the last member's own extent, rounded only to the struct's own alignment");

// FORMAT.md's kMaxBankRows, mirrored as a compiled constant (TE-96 sec 4.2
// step 4: checked BEFORE `n * dims * 4` is computed, so the multiplication
// itself never has to detect a corpus this large).
inline constexpr size_t kSembMaxCorpusRows = 1ull << 28;

extern "C" {

// TE-96 sec 4.2: the frozen signature. Preflight is shape-before-content-
// before-work (steps 1-12), completed before any forward; runtime failures
// (step 13) can follow earlier staged rows. Nothing is written to `out_rows`
// on any non-SEMB_OK return; `*out_required_bytes` is written on exactly
// SEMB_OK and SEMB_BUFFER_TOO_SMALL (the query form `(NULL, 0)` lands there).
semb_status semb_encode_batch(semb_encoder enc, const semb_document* docs, size_t n,
                               float* out_rows, size_t out_capacity_bytes,
                               size_t* out_required_bytes);

}  // extern "C"

#endif  // SEMB_BATCH_ABI_CONTRACT_H
