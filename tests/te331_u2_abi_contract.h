// tests/te331_u2_abi_contract.h -- TE-331 (U2-1/U2-3/U2-7 red suite): the
// test author's own declarations of the four verbs U2-7 adds before the ABI
// freezes (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-7 items 1, 2, 6,
// 7). Like `tests/semb_bake_abi_contract.h` and
// `tests/semb_wb_witness_abi_contract.h`, this is the SUITE'S OWN header,
// never a copy of a product header: `include/superembedder/semb.h` declares
// none of `semb_encoder_open_memory` or `semb_encode_query`, and
// `include/superembedder/encoder_interim_abi.h` declares neither
// `semb_interim_query_token_count` nor `semb_interim_certification_verdict`,
// confirmed absent at `fca421b`:
//
//   git grep -n "semb_encoder_open_memory\|semb_encode_query\|\
//     semb_interim_query_token_count\|semb_interim_certification_verdict" \
//     src/ include/
//
// returns nothing. Every test that includes this header and calls one of
// these four fails to LINK until the builder's round adds it --
// tests/te331_u2_surface_link_check.py builds the EXCLUDE_FROM_ALL target on
// demand and reports the unresolved symbol(s) by name, the te163/te194
// red-first shape.
//
// TWO PUBLIC (frozen semb_* C ABI, item 1/2) AND TWO INTERNAL, NON-FROZEN
// (encoder_interim_abi.h shape, item 6/7) VERBS, per the plan's own text:
//
//   semb_status semb_encoder_open_memory(const semb_memory_config* cfg, semb_encoder* out)
//   semb_status semb_encode_query(semb_encoder enc, const char* utf8, size_t utf8_len,
//                                 float* out_vector, size_t out_capacity_bytes,
//                                 size_t* out_required_bytes, semb_fingerprint* out_fingerprint)
//   SembInterimStatus semb_interim_query_token_count(semb_encoder enc, const char* utf8, size_t utf8_len,
//                                                    int64_t* out_body_tokens)
//
//   TAKES `semb_encoder`, THE FROZEN PUBLIC HANDLE, NOT `SembInterimEncoder*` --
//   a model gap this suite surfaces rather than silently resolves. The plan's
//   own text places this verb "beside the other semb_interim_* functions"
//   stylistically (encoder_interim_abi.h's naming convention), but its
//   actual work (ComposeQuery + tokenization, item 2's own composition) is
//   query.cpp's, which today is reachable only through a `semb_encoder`
//   (the handle that owns BOTH the model and the tokenizer artifact) --
//   `semb_interim_encoder_open`'s own real, existing signature
//   (`encoder_interim_abi.h`) takes a model path ALONE, no tokenizer, so a
//   `SembInterimEncoder*` cannot reach ComposeQuery's tokenizer at all. This
//   suite's own signature choice therefore takes `semb_encoder`; C55's
//   cells grade the COUNT, not this file's own argument order, so a builder
//   who instead exposes it differently (a new interim handle that DOES
//   carry a tokenizer, or a direct return value) is routed as a model gap
//   rather than blocking on this guess (Curie's own "route a model gap,
//   don't invent a stricter one" discipline; noted in the record).
//   SembInterimStatus semb_interim_certification_verdict(SembInterimCertificationVerdict* out,
//                                                        const char** out_engine_status_name)
//
// `semb_interim_certification_verdict`'s struct and status convention are
// pinned exactly as the plan's own text states them (sec 5 U2-7 item 7):
// `struct_size` validated on entry (kSembInterimStructSizeMismatch),
// `out_engine_status_name` carrying the engine's own refusal name on
// `kSembInterimEngineRefused` -- the same convention `encoder_interim_abi.h`
// already documents for every other interim verb's engine-refusal case.
#ifndef SUPEREMBEDDER_TE331_U2_ABI_CONTRACT_H
#define SUPEREMBEDDER_TE331_U2_ABI_CONTRACT_H

#include <cstdint>
#include <cstddef>

// semb_status/semb_encoder/semb_fingerprint come from the includer's own
// prior `#include "semb_public_abi_contract.h"` -- THIS SUITE'S OWN
// independent declaration of the frozen surface, per
// `tests/semb_bank_abi_contract.h` and `tests/semb_bake_abi_contract.h`'s
// own established convention (neither includes the product's semb.h or a
// sibling contract header; both rely on include order in the .cpp that
// uses them). Including `superembedder/semb.h` here would redeclare
// `semb_config` against semb_public_abi_contract.h's own independent
// definition and fail to compile -- confirmed by execution, not asserted.
#include "superembedder/encoder_interim_abi.h"  // SembInterimEncoder, SembInterimStatus (the real
                                                // product header; the interim ABI's own type is
                                                // reused directly, per epoch_store_emit.cpp's and
                                                // w_b_corpus_witness_test.cpp's own precedent)

#ifdef __cplusplus
extern "C" {
#endif

// U2-7 item 1 (Q4, F21): the memory-open verb. Shares the whole internal
// open `semb_encoder_open` calls (`OpenEncoder`, item 14's own repair,
// TE-313) -- including the linked-engine check -- passing a closure that
// copies both spans into encoder-owned buffers in place of the closure that
// reads a file. `struct_size`-validated IN struct, per sec 3.1's own
// convention for every sized-argument struct in this ABI.
struct semb_memory_config {
  uint32_t struct_size;
  const uint8_t* model_bytes;
  size_t model_len;
  const uint8_t* tokenizer_bytes;
  size_t tokenizer_len;
  uint32_t max_concurrency;
};

semb_status semb_encoder_open_memory(const semb_memory_config* cfg, semb_encoder* out);

// U2-7 item 2 (Q5, F22): the raw path's query form. One composition, two
// wrappers -- `semb_query_encode` and `semb_encode_query` both call one
// internal function running `ComposeQuery`/`EncodeQueryComposed`; this verb
// checks nothing against a bank and returns the fingerprint the vector was
// emitted under, exactly as `semb_encode` does.
semb_status semb_encode_query(semb_encoder enc, const char* utf8, size_t utf8_len,
                              float* out_vector, size_t out_capacity_bytes,
                              size_t* out_required_bytes, semb_fingerprint* out_fingerprint);

// U2-7 item 6 (R17): the body-token count over the composed query, without
// paying for the encode -- len(Encode(ComposeQuery(text))) -
// len(Encode(kQueryPrefix)), never a count over the bare text (C55).
// Declared beside the other `semb_interim_*` functions the vendoring
// plugin already compiles against (encoder_interim_abi.h), not one of the
// fourteen frozen `semb_*` verbs, and not exported by the installed shared
// library's version script (U2-1).
SembInterimStatus semb_interim_query_token_count(semb_encoder enc, const char* utf8, size_t utf8_len,
                                                 int64_t* out_body_tokens);

// U2-7 item 7 (R8, M22, C57): the model-free certification verdict. Every
// field is a compile-time constant of the linked engine, a compiler macro,
// or the compiled-in certified-builds/identity bytes -- no artifact path
// argument exists, and none can be supplied (the plan's own "there is no
// argument through which one could be supplied"). Shares OPEN's whole
// calling sequence (item 14's `CheckLinkedEngine`, then item 1's matcher),
// never a second, independently-sourced implementation (TE-333/TE-335's
// own repair).
struct SembInterimCertificationVerdict {
  uint32_t struct_size;
  char os[32];
  char arch[16];
  char compiler_id[32];
  char compiler_version[32];
  char frontend[32];
  char configuration[16];
  char build_system[16];
  char dispatch[16];          // "auto" or the forced tier
  char stdlib[32];
  uint8_t compile_flags_sha[32];
  uint8_t engine_flags_sha[32];
  char dispatched_tier[16];   // "sse2"/"avx2"/"avx512"/"scalar"
  char certified_cell[64];    // the matched cell id, or "uncertified"
  uint8_t certification_epoch[32];
};

SembInterimStatus semb_interim_certification_verdict(SembInterimCertificationVerdict* out,
                                                      const char** out_engine_status_name);

#ifdef __cplusplus
}  // extern "C"
#endif

#endif  // SUPEREMBEDDER_TE331_U2_ABI_CONTRACT_H
