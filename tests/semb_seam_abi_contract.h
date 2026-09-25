// tests/semb_seam_abi_contract.h -- TE-62 (U0 slice B red suite): the C ABI
// verbs this suite assumes for the SEAM -- the encoder's per-position
// `{codes, m, e}` output and its serialisation
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b: "THE SEAM SERIALISATION").
//
// Like `tests/semb_wa_pool_abi_contract.h`, this is Curie's own concrete
// pin of an entry-point shape the plan already commits to in prose, not a
// transcription of the fold-4 probe's own header (`semb_encoder_interim.h`,
// read only as population/anchor per this seat's brief). None of these
// symbols is defined anywhere in `superembedder` yet; every test that
// includes this header fails to LINK until TE-63 adds them.
#ifndef SEMB_SEAM_ABI_CONTRACT_H
#define SEMB_SEAM_ABI_CONTRACT_H

#include <cstddef>
#include <cstdint>

enum SembSerializeStatus : int32_t {
  kSembSerializeOk = 0,
  kSembSerializeBufferTooSmall = 1,
};

extern "C" {

// sec 4.4b's per-document seam serialisation, VERBATIM byte layout:
//   u64(n) || u64(hidden_size)
//   || for p in 0..n-1: codes[p][0..hidden-1] (raw int8, dimension order)
//                       || u64((uint64)m[p]) || u64((uint64)e[p])
// little-endian throughout. Writes into `out_buf` (capacity `out_buf_cap`
// bytes) and reports the exact length written (or required, on
// kSembSerializeBufferTooSmall) via `out_len`. This entry point does NOT
// run the forward pass -- it serialises caller-supplied per-position
// values, so the SERIALISATION FORMAT is testable independently of
// whether those values were computed correctly (a separate concern, C1's).
SembSerializeStatus semb_seam_serialize_document(const int8_t* codes, const int64_t* m,
                                                  const int64_t* e, size_t n, size_t hidden,
                                                  uint8_t* out_buf, size_t out_buf_cap,
                                                  size_t* out_len);

// The one encoder TU's real, timed seam call over a whole document (C39):
// runs the actual forward + pooling-epilogue-adjacent seam extraction on
// `token_ids` and writes the per-position codes/scales, from which a
// caller derives the seam digest C39/C40 compare against
// `tests/fixtures/reference-digests.txt`. `chunk_budget` is sec 4.3's
// pinned chunk-budget parameter (0 or >= n means one whole-document
// call).
enum SembEncodeStatus : int32_t {
  kSembEncodeOk = 0,
  kSembEncodeEngineRefused = 1,
  // TE-80 (TE-76 review F-7, closed by TE-79 in engine_adapter_interim.cpp):
  // the real hidden_size, known only after the model opens, exceeds
  // kSembWitnessMaxHidden -- refused BEFORE codes_out/m_out/e_out/
  // *hidden_out are written. Mirrors include/superembedder/seam_abi.h
  // exactly.
  kSembEncodeHiddenTooLarge = 2,
  // U2 cloud build, U2-10 item 3: the encode seam's allocation-failure status.
  kSembEncodeAllocationFailed = 3,
};

// Mirrors include/superembedder/seam_abi.h's kSembWitnessMaxHidden
// exactly: the fixed ceiling this verb enforces on the real hidden_size
// before writing anything, since it cannot take a real capacity
// parameter without breaking every existing extern "C" caller's fixed
// signature.
//
// THIS IS A MANUALLY-KEPT-IN-SYNC DUPLICATE, NOT A SHARED SYMBOL --
// TE-147 found this while raising the ceiling for the real W-B witness
// leg: this header does not include superembedder/seam_abi.h (it is the
// suite's own contract, independent of the product header by this
// project's own convention), so the two constants are two separate
// `constexpr` declarations that must be changed together by hand. The
// TE-145 casebook's own sec 7 states "every one keys off the SAME single
// constant ... raising it once updates every consumer's own behaviour" --
// true for src/witness/witness_main.cpp and tests/w_b_corpus_witness_test.cpp
// (both of which read the real product header), but NOT true for THIS
// mirror or for tests/c39_seam_digest_test.cpp (which reads this mirror,
// not the product header) -- confirmed by reading both files' own
// #include lists rather than taken on the casebook's word. Updated to
// 1024 in the same edit that raised the product constant, so the two stay
// equal; a future raise must update both again.
constexpr size_t kSembWitnessMaxHidden = 1024;

SembEncodeStatus semb_encode_document_for_witness(const char* model_path,
                                                   const int32_t* token_ids, size_t n,
                                                   size_t chunk_budget, int8_t* codes_out,
                                                   int64_t* m_out, int64_t* e_out,
                                                   size_t* hidden_out);

}  // extern "C"

#endif  // SEMB_SEAM_ABI_CONTRACT_H
