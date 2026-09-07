// include/superembedder/encoder_interim_abi.h -- U1 slice 1 (C12b first): the
// INTERIM encoder handle over the installed SuperSLM C++ surface
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.3, sec 7's U1 row: "C12b
// first ... the CPU encoder on the installed C++ surface at the pinned chunk
// budget; PS-N (sec 3.2), built to item 4's integer-exact construction
// applied to PS-N's single selected position").
//
// WHAT THIS IS, AND IS NOT. These verbs are the encoder's REAL data path --
// open the artifact once, embed and run the forward over a whole document,
// hand back the per-position `{codes, m, e}` seam, select PS-N's position
// after the engine's own final norm, dequantize it in integer code -- so
// C12b's instrument (src/c12b/) grades the product's own path and not a
// harness copy of it. They are NOT sec 3.1's twelve frozen `semb_*` verbs:
// those take UTF-8 spans and tokenize through the artifact's own tokenizer
// section. U1's frozen `semb_encoder_open`/`semb_encode` implementation is
// built ON these verbs (the converter-emitted tokenizer in front, the same
// seam behind): this surface remains internal for C12b attribution and the
// token-id parity oracle, while public callers include `superembedder/semb.h`.
//
// Refusal statuses are this header's own enum; an engine refusal reaches a
// caller as `kSembInterimEngineRefused` PLUS the engine's own status NAME
// (sec 8 C4: "mapped to SEMB_ENGINE_REFUSED carrying the engine's own status
// name, never propagated as an engine enum across the seam"). A returned
// status-name pointer remains valid until the next interim encoder call on
// the same thread; callers that need it longer must copy the string.
//
// Capacity convention (sec 3.1 item 3): every output-buffer verb takes a
// capacity; when it is insufficient the verb writes the required size to
// its required-size out-parameter, writes NOTHING to the buffer, and
// returns `kSembInterimBufferTooSmall`.
#ifndef SEMB_ENCODER_INTERIM_ABI_H
#define SEMB_ENCODER_INTERIM_ABI_H

#include <cstddef>
#include <cstdint>
#include <vector>

#include "superembedder/pool_abi.h"  // SembWaPoolStatus: the dequantize corner refusals

typedef struct SembInterimEncoder SembInterimEncoder;  // library-owned, opaque

enum SembInterimStatus : int32_t {
  kSembInterimOk = 0,
  kSembInterimNullArgument = 1,
  // The engine refused (open, marshal, embed, or forward); the engine's own
  // status name is written to the verb's `out_engine_status_name`.
  kSembInterimEngineRefused = 2,
  kSembInterimInputEmpty = 3,        // zero content tokens (SEMB_INPUT_EMPTY, sec 3.2)
  kSembInterimBufferTooSmall = 4,    // required size written; buffer untouched
  kSembInterimInvalidLeg = 5,        // `leg` outside SembForwardLeg
  kSembInterimPositionOutOfRange = 6,  // `position >= n`
  // The composed path's dequantize refused (`*out_dequantize_status` names
  // which corner); no vector was written.
  kSembInterimDequantizeRefused = 7,
  kSembInterimStructSizeMismatch = 8,  // an IN struct's `struct_size` is not this build's
  kSembInterimConcurrencyExceeded = 9,  // every preallocated workspace is in use
};

// Which of the two installed forward entry points runs the document. Both
// must emit the identical seam (sec 4.3: "bit-identical ... by
// construction", executed rather than taken on the header's word); C12b's
// third attribution ("the entry-point substitution is not bit-identical
// after all") is decided by running the same document down both.
enum SembForwardLeg : int32_t {
  kSembForwardLegChunkBatched = 0,  // the product's path (sec 4.3), at `chunk_budget`
  kSembForwardLegPerToken = 1,      // the engine's single-token path, one position at a time
};

// The single, fixed token id SuperEmbedder appends to every document's
// content ids before PS-N selects the last position (sec 3.2, corrected
// position rule: `<|endoftext|>`, id 151643 in the ratified candidate's
// tokenizer -- "appended as the pre-known id directly to the token-id
// sequence, not composed as literal text bytes re-tokenized"). A property
// of the CANDIDATE, so `semb_interim_encoder_open` takes it as an argument
// rather than hard-wiring it into a library that also opens the synthetic
// U0 fixture (whose 128-entry vocab has no such id).
constexpr int32_t kSembPsNAppendedTokenId = 151643;

struct SembInterimGeometry {
  uint32_t struct_size;  // sizeof(SembInterimGeometry), validated on entry
  uint32_t hidden_size;
  uint32_t num_hidden_layers;
  uint32_t num_attention_heads;
  uint32_t num_key_value_heads;
  uint32_t head_dim;
  uint32_t vocab_size;
  uint32_t context_cap;
  int32_t appended_token_id;
};

extern "C" {

// Reads the artifact ONCE into owned memory, validates it through the
// engine's own loader, marshals every layer and the final norm, and sizes
// the K/V workspace from the artifact's own geometry. `appended_token_id`
// is the id appended to every document (see kSembPsNAppendedTokenId).
SembInterimStatus semb_interim_encoder_open(const char* model_path, int32_t appended_token_id,
                                             SembInterimEncoder** out_encoder,
                                             const char** out_engine_status_name);

// Product-layer entry: loads from bytes the caller already read exactly once
// and preallocates one independent K/V workspace per permitted concurrent call.
// The adapter copies the span into encoder-owned backing because SuperSLM's
// model view borrows it; the caller may release its span after this returns.
SembInterimStatus semb_interim_encoder_open_from_memory(
    const uint8_t* model_bytes, size_t model_size, int32_t appended_token_id,
    uint32_t max_concurrency, SembInterimEncoder** out_encoder,
    const char** out_engine_status_name);

void semb_interim_encoder_close(SembInterimEncoder* encoder);

SembInterimStatus semb_interim_encoder_geometry(const SembInterimEncoder* encoder,
                                                 SembInterimGeometry* out_geometry);

// THE SEAM over a whole document: appends the encoder's end token to the
// `n_content` content ids (so the document has `n = n_content + 1`
// positions), embeds every position, runs the forward down `leg`, and
// writes the per-position `{codes, m, e}` -- position 0 included, the
// appended token included, every position PRE-final-norm (the residual the
// forward writes back; sec 4.4b's W-B seam). `codes_out` needs
// `n * hidden_size` int8; `m_out`/`e_out` need `n` int64 each; `*out_positions`
// receives `n` on every return (including the too-small refusal, so a caller
// can size and retry). `chunk_budget` is sec 4.3's pinned budget (0 or >= n:
// one whole-document call); ignored on the per-token leg.
SembInterimStatus semb_interim_encode_seam(SembInterimEncoder* encoder, const int32_t* content_ids,
                                            size_t n_content, size_t chunk_budget,
                                            SembForwardLeg leg, int8_t* codes_out,
                                            size_t codes_capacity, int64_t* m_out, int64_t* e_out,
                                            size_t scales_capacity, size_t* out_positions,
                                            const char** out_engine_status_name);

// PS-N's SELECTION (sec 3.2): applies the engine's own final norm to ONE
// position of a seam this encoder produced and returns that position's
// post-final-norm `{codes, m, e}` -- `out_codes` needs `hidden_size` int8.
// The product's own wiring selects `position == n - 1` (the appended end
// token's position, the document's last); the verb takes the position
// explicitly so that C12b's must-reject -- the wrong position, second-to-last
// -- is producible through this SAME real data path rather than through a
// mutation of it. A position outside `[0, n)` is refused, never clamped.
SembInterimStatus semb_interim_ps_n_select(const SembInterimEncoder* encoder, const int8_t* codes,
                                            const int64_t* m, const int64_t* e, size_t n,
                                            size_t position, int8_t* out_codes, int64_t* out_m,
                                            int64_t* out_e, const char** out_engine_status_name);

// PS-N's DEQUANTIZE (sec 3.2 item 4, applied to one triple): each emitted
// element is the binary32 nearest the EXACT rational `c_i * m * 2^e`,
// round-to-nearest-ties-to-even applied once in integer code, classified
// over the ROUNDED result -- `kSembPooledSubnormal` for a non-zero result
// below 2^-126, `kSembPooledOverflow` for one that rounds to infinity, and
// `kSembEMinDomainExceeded` when |e| exceeds kSembWaPoolMaxAbsEMin (checked
// before any shift). `out` receives `hidden` float32 values ONLY on kSembOk.
// No floating-point operation is performed on this path. Emitted RAW: no
// L2 normalization (sec 3.2 item 5 -- that arithmetic is SuperFAISS's).
SembWaPoolStatus semb_ps_n_dequantize(const int8_t* codes, int64_t m, int64_t e, size_t hidden,
                                       float* out);

// THE PRODUCT'S COMPOSED PATH: seam (chunk-batched leg) -> select the LAST
// position -> dequantize. `out_vector` needs `hidden_size * sizeof(float)`
// bytes; `*out_required_bytes` is written on every return. A dequantize
// refusal returns `kSembInterimDequantizeRefused` with the corner named in
// `*out_dequantize_status`; the verb returns kSembInterimOk only when the
// vector was written.
SembInterimStatus semb_interim_encode_ps_n(SembInterimEncoder* encoder, const int32_t* content_ids,
                                            size_t n_content, size_t chunk_budget,
                                            float* out_vector, size_t out_capacity_bytes,
                                            size_t* out_required_bytes,
                                            SembWaPoolStatus* out_dequantize_status,
                                            const char** out_engine_status_name);

// THE BATCH COMPOSED PATH (TE-147, U1 slice 2): the SAME seam -> select ->
// dequantize composition as semb_interim_encode_ps_n, run for `doc_count`
// independent documents against ONE workspace acquired ONCE for the WHOLE
// call (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1 concurrency clause;
// TE-96 sec 4.2 step 12: "one workspace for the whole call ... rows run
// serially on that slot") -- unlike calling semb_interim_encode_ps_n once
// per document, which would acquire and release the pool's own slot once
// PER DOCUMENT. `docs_content_ids[i]`/`docs_n_content[i]` describe document
// `i`'s own content token ids (the terminator is appended internally,
// exactly as the raw path does); `out_vectors` receives `doc_count`
// consecutive `hidden`-sized rows, row-major, no padding. On any refusal
// `*out_failed_index` names which document failed (0 on a precondition
// refusal that precedes the loop); the workspace is released exactly once,
// on every return path, by RAII.
//
// out_vectors == nullptr: the row-output half of the composition (select +
// dequantize) is SKIPPED entirely for every document -- a caller that wants
// only the seam tap below pays for the forward alone. out_capacity_bytes is
// ignored in this mode; *out_required_bytes still reports doc_count *
// hidden * sizeof(float) (the size a caller WOULD need to get rows too).
// out_vectors != nullptr behaves exactly as before this parameter existed:
// out_capacity_bytes is validated against that same required size.
//
// out_seam_stream (TE-159, C-2, D-SLM6354 -- the conductor's ruling that
// W-B's own digest must derive through this SAME composition rather than a
// second, independent forward): when non-null, each document's FULL
// per-position seam -- every position, pre-final-norm, both scale fields,
// the identical {codes, m, e} the row path selects ONE position out of --
// is serialised via semb_seam_serialize_document (superembedder/seam_abi.h)
// and appended to *out_seam_stream, in call order, with NO framing between
// documents beyond what that serialisation already writes. This is the
// exact byte sequence a caller hashes to get a digest that is sensitive to
// this function's own composition (the tokenizer call this function's
// caller made, the appended-token id, the chunk-batched forward, the
// workspace-sharing) -- the same property `semb_encode_batch`'s own rows
// have, now shared by anything that taps the seam instead of the rows.
// out_seam_stream_capacity is validated BEFORE any document's forward runs
// (the same shape-before-work discipline `semb_encode_batch` itself uses):
// insufficient capacity returns kSembInterimBufferTooSmall with
// *out_seam_stream_len holding the exact required length, before touching
// out_seam_stream. On success *out_seam_stream_len holds the exact length
// written. A caller that wants only rows passes out_seam_stream == nullptr
// and pays nothing extra (no serialisation call is made per document).
SembInterimStatus semb_interim_encode_batch_ps_n(
    SembInterimEncoder* encoder, const int32_t* const* docs_content_ids,
    const size_t* docs_n_content, size_t doc_count, size_t chunk_budget, float* out_vectors,
    size_t out_capacity_bytes, size_t* out_required_bytes, size_t* out_failed_index,
    SembWaPoolStatus* out_dequantize_status, const char** out_engine_status_name,
    uint8_t* out_seam_stream, size_t out_seam_stream_capacity, size_t* out_seam_stream_len);

}  // extern "C"

// C++ product-layer entry: transfers the exactly-once file read into the
// adapter, avoiding a second 633 MB allocation while preserving the borrowed
// model view's lifetime. Not part of the frozen public C ABI.
SembInterimStatus semb_interim_encoder_open_owned(
    std::vector<uint8_t>&& model_bytes, int32_t appended_token_id,
    uint32_t max_concurrency, SembInterimEncoder** out_encoder,
    const char** out_engine_status_name);

#endif  // SEMB_ENCODER_INTERIM_ABI_H
