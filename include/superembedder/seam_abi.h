// include/superembedder/seam_abi.h -- TE-63 (U0 slice B): the C ABI verbs
// for the SEAM -- the encoder's per-position {codes, m, e} output and its
// serialisation (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b).
//
// This header's symbol names, enum values and function signatures satisfy
// `tests/semb_seam_abi_contract.h` exactly, for the same reason
// `pool_abi.h` states.
#ifndef SEMB_SEAM_ABI_H
#define SEMB_SEAM_ABI_H

#include <cstddef>
#include <cstdint>

enum SembSerializeStatus : int32_t {
  kSembSerializeOk = 0,
  kSembSerializeBufferTooSmall = 1,
};

enum SembEncodeStatus : int32_t {
  kSembEncodeOk = 0,
  kSembEncodeEngineRefused = 1,
};

extern "C" {

// sec 4.4b's per-document seam serialisation, VERBATIM byte layout:
//   u64(n) || u64(hidden_size)
//   || for p in 0..n-1: codes[p][0..hidden-1] (raw int8, dimension order)
//                       || u64((uint64)m[p]) || u64((uint64)e[p])
// little-endian throughout. Writes into `out_buf` (capacity `out_buf_cap`
// bytes) and reports the exact length written (or required, on
// kSembSerializeBufferTooSmall) via `out_len`.
SembSerializeStatus semb_seam_serialize_document(const int8_t* codes, const int64_t* m,
                                                  const int64_t* e, size_t n, size_t hidden,
                                                  uint8_t* out_buf, size_t out_buf_cap,
                                                  size_t* out_len);

// The one encoder TU's real, timed seam call over a whole document (C39):
// runs the actual forward (EmbedEntry + RunLayerLoopChunkBatched) on
// `token_ids` and writes the per-position codes/scales. `chunk_budget` is
// sec 4.3's pinned chunk-budget parameter (0 or >= n means one
// whole-document call).
SembEncodeStatus semb_encode_document_for_witness(const char* model_path,
                                                   const int32_t* token_ids, size_t n,
                                                   size_t chunk_budget, int8_t* codes_out,
                                                   int64_t* m_out, int64_t* e_out,
                                                   size_t* hidden_out);

}  // extern "C"

#endif  // SEMB_SEAM_ABI_H
