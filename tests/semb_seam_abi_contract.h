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
};

SembEncodeStatus semb_encode_document_for_witness(const char* model_path,
                                                   const int32_t* token_ids, size_t n,
                                                   size_t chunk_budget, int8_t* codes_out,
                                                   int64_t* m_out, int64_t* e_out,
                                                   size_t* hidden_out);

}  // extern "C"

#endif  // SEMB_SEAM_ABI_CONTRACT_H
