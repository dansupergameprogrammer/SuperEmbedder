// src/superembedder/engine_adapter_interim.cpp -- THE interim adapter, and
// the only one (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.3: "the skeleton
// composes the forward from SuperSLM's installed C++ headers behind
// SuperEmbedder's own engine-adapter seam, calling EmbedEntry +
// RunLayerLoopChunkBatched"). This is the ONE translation unit in this
// library that names EmbedEntry, RunLayerLoopChunkBatched, RunLayerLoop,
// MarshalLayer or SslmModel::Load -- `tests/c39_singleton_check.py` is the
// structural check that enforces this (sec 8, C39/C31 clause 3: W-A's
// drivers and this adapter are compiled INTO the library; the engine's
// `inline` primitives must be reached through the library's own
// translation unit, never re-compiled inside a sibling TU).
//
// Ported from `Claude/Vitruvius/t2217-fold4-probe/cost/semb_encoder_interim.cpp`
// (TE-63, U0 slice B) under product discipline; see that round's build log
// for the port's own dispositions. U1 slice 1 (C12b first) adds, in this
// same TU:
//
//   * the interim handle surface (include/superembedder/encoder_interim_abi.h): the artifact
//     read ONCE into owned memory at open, every layer AND the final norm
//     marshaled once, the K/V workspace sized once from the artifact's own
//     geometry, and many documents encoded against that one handle -- the
//     shape a bake over 239 documents needs and the one-shot witness verb
//     below (which re-opens the 633 MB artifact per call) cannot supply;
//   * `q_width` threaded EXPLICITLY to both forward entry points
//     (`num_attention_heads * head_dim`), the way `sslm_prefill` itself does.
//     The U0 port relied on the parameter's default (0 = "derive as
//     hidden_size"), which is bit-identical for every square incumbent and
//     WRONG for the ratified candidate (hidden_size 1024, heads*head_dim
//     2048, sec 4.2 Track A) -- exactly the "silent-undercount defect" the
//     engine's own header names for this call site, and exactly C12b's
//     "the port is wrong" attribution, found by reading the production
//     caller before the first real-artifact run rather than by a red digest
//     after it. The witness verb inherits the fix; U0's synthetic fixture is
//     square, so its committed anchors are unaffected by construction (and
//     C39 grades that by execution);
//   * PS-N's selection (sec 3.2): the engine's own final norm applied to
//     the ONE selected position, through the same `RmsNormSite` under the
//     same "final_norm" site name and site constant the engine's own
//     generation loop uses;
//   * the per-token leg (the engine's single-token `RunLayerLoop`, one
//     position at a time against the same K/V store), so C12b's third
//     attribution -- "the entry-point substitution is not bit-identical after
//     all" -- is decided by running both entry points on the same document in
//     the same process, per row, never inherited from the header's claim.
#include "superembedder/encoder_interim_abi.h"
#include "superembedder/seam_abi.h"

#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "superslm/forward_sites.h"
#include "superslm/layer_marshal.h"
#include "superslm/model.h"

using namespace superslm;
using superslm_marshal::LayerBacking;
using superslm_marshal::MarshalLayer;
using superslm_marshal::PreflightScanWscFolds;
using superslm_marshal::ReadCarriedScale;
using superslm_marshal::ReadFile;
using superslm_marshal::WidenGainToInt32;

namespace semb {
namespace {

// The engine's own status NAME for the most recent refusal on this thread,
// returned through every verb's `out_engine_status_name` (sec 8 C4: the
// name crosses the seam, never the enum). A marshal refusal carries the
// marshal's own diagnostic string instead, since MarshalLayer reports
// through a std::string rather than a status.
thread_local std::string t_last_engine_status;

const char* SetEngineStatus(const std::string& s) {
  t_last_engine_status = s;
  return t_last_engine_status.c_str();
}

struct EncoderModel {
  // SslmModelView borrows section storage from these exact bytes.
  std::vector<uint8_t> model_bytes;
  SslmModelView view;
  std::vector<LayerBacking> backings;
  std::vector<LayerWeights> layers;
  const int8_t* embed_weights = nullptr;
  CarriedScale embed_site_constant{};
  std::vector<int32_t> final_norm_gain;
  CarriedScale final_norm_site_constant{};
  struct WorkspaceSlot {
    std::vector<uint8_t> bytes;
    bool in_use = false;
  };
  std::mutex workspace_mutex;
  std::vector<WorkspaceSlot> workspaces;
  size_t hidden_size = 0;
  uint32_t num_layers = 0;
  size_t q_width = 0;
  int64_t context_cap = 0;
  bool option_g_fused = false;
  int32_t appended_token_id = -1;
};

// Finishes an open after the artifact's exactly-once read has transferred its
// backing into `m`. The model view borrows from that backing for its lifetime.
EncoderModel* FinishEncoderOpen(std::unique_ptr<EncoderModel> m, uint32_t max_concurrency,
                                const char** engine_status_name) {
  std::string model_err;
  const SslmModelStatus ms =
      SslmModel::Load(m->model_bytes.data(), m->model_bytes.size(), m->view, &model_err);
  if (ms != SslmModelStatus::Ok) {
    if (engine_status_name) {
      *engine_status_name =
          SetEngineStatus(std::string(SslmModelStatusName(ms)) + ": " + model_err);
    }
    return nullptr;
  }
  const uint32_t num_heads = m->view.config.num_attention_heads;
  const uint32_t num_kv_heads = m->view.config.num_key_value_heads;
  m->num_layers = m->view.config.num_hidden_layers;
  m->hidden_size = m->view.config.hidden_size;
  m->q_width = static_cast<size_t>(num_heads) * m->view.config.head_dim;
  m->context_cap = static_cast<int64_t>(m->view.config.context_cap);
  m->option_g_fused = m->view.option_g_fused_k_landing;

  PreflightScanWscFolds(m->view);
  m->backings.resize(m->num_layers);
  m->layers.resize(m->num_layers);
  for (uint32_t l = 0; l < m->num_layers; ++l) {
    std::string merr;
    if (!MarshalLayer(m->view, l, num_heads, num_kv_heads, m->backings[l], m->layers[l], &merr)) {
      if (engine_status_name) *engine_status_name = SetEngineStatus("MarshalLayer: " + merr);
      return nullptr;
    }
  }
  const SslmTensorView* embed_w = m->view.weights.Tensor("embed");
  const SslmTensorView* final_gain_w = m->view.weights.Tensor("final_norm.gain");
  if (!embed_w || !final_gain_w) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("MissingEmbedOrFinalNormTensor");
    return nullptr;
  }
  m->embed_weights = reinterpret_cast<const int8_t*>(embed_w->data);
  m->final_norm_gain = WidenGainToInt32(*final_gain_w);
  if (m->final_norm_gain.size() != m->hidden_size) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("FinalNormGainWidthMismatch");
    return nullptr;
  }
  bool ok = true;
  m->embed_site_constant = ReadCarriedScale(m->view.composition_constants, "embed", &ok);
  if (!ok) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("MissingEmbedSiteConstant");
    return nullptr;
  }
  m->final_norm_site_constant = ReadCarriedScale(m->view.composition_constants, "final_norm", &ok);
  if (!ok) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("MissingFinalNormSiteConstant");
    return nullptr;
  }
  // The forward's own workspace requirement (forward_sites.h), identical for
  // both entry points: num_hidden_layers * context_cap * num_kv_heads *
  // head_dim * 2. Compute it without a wrapping intermediate before any
  // allocation, then allocate every concurrency slot at open as the frozen
  // public handle contract requires.
  size_t workspace_bytes = static_cast<size_t>(m->num_layers);
  const size_t factors[] = {static_cast<size_t>(m->context_cap),
                            static_cast<size_t>(num_kv_heads),
                            static_cast<size_t>(m->view.config.head_dim), size_t{2}};
  for (const size_t factor : factors) {
    if (factor != 0 && workspace_bytes > std::numeric_limits<size_t>::max() / factor) {
      if (engine_status_name) *engine_status_name = SetEngineStatus("WorkspaceSizeOverflow");
      return nullptr;
    }
    workspace_bytes *= factor;
  }
  m->workspaces.resize(max_concurrency);
  for (auto& slot : m->workspaces) slot.bytes.assign(workspace_bytes, 0);
  return m.release();
}

// Opens the artifact and marshals every layer plus the final norm. Returns
// nullptr on any failure with the engine's own status name (or the marshal's
// diagnostic) in `*engine_status_name`.
EncoderModel* EncoderOpenFromMemory(const uint8_t* model_bytes, size_t model_size,
                                    uint32_t max_concurrency,
                                    const char** engine_status_name) {
  if (!model_bytes || model_size == 0 || max_concurrency == 0) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("InvalidOpenInput");
    return nullptr;
  }
  auto m = std::make_unique<EncoderModel>();
  m->model_bytes.assign(model_bytes, model_bytes + model_size);
  return FinishEncoderOpen(std::move(m), max_concurrency, engine_status_name);
}

EncoderModel* EncoderOpenOwned(std::vector<uint8_t>&& model_bytes,
                               uint32_t max_concurrency,
                               const char** engine_status_name) {
  if (model_bytes.empty() || max_concurrency == 0) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("InvalidOpenInput");
    return nullptr;
  }
  auto m = std::make_unique<EncoderModel>();
  m->model_bytes = std::move(model_bytes);
  return FinishEncoderOpen(std::move(m), max_concurrency, engine_status_name);
}

EncoderModel* EncoderOpen(const std::string& model_path, const char** engine_status_name) {
  auto m = std::make_unique<EncoderModel>();
  if (!ReadFile(model_path.c_str(), m->model_bytes)) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("ReadFileFailed");
    return nullptr;
  }
  return FinishEncoderOpen(std::move(m), 1, engine_status_name);
}

void EncoderClose(EncoderModel* m) { delete m; }

// The seam: embed every token, then run the forward down `leg`. On the
// chunk-batched leg `chunk_budget` (0 or >= n resolves to one whole-document
// call) bounds each call's span; on the per-token leg every position runs
// through the engine's single-token loop in order against the same K/V
// store, exactly as the engine's own decode path drives it.
SslmForwardStatus Encode(EncoderModel* m, std::vector<uint8_t>& workspace,
                         const int32_t* tokens, size_t n, size_t chunk_budget,
                         SembForwardLeg leg, int8_t* codes_out, CarriedScale* scales_out) {
  if (n == 0) return SslmForwardStatus::InvalidLayerBudget;
  if (chunk_budget == 0 || chunk_budget > n) chunk_budget = n;
  const size_t hidden = m->hidden_size;
  const int32_t vocab = static_cast<int32_t>(m->view.config.vocab_size);

  for (size_t p = 0; p < n; ++p) {
    CarriedScale es{};
    const SslmForwardStatus st = EmbedEntry(tokens[p], vocab, m->embed_weights, hidden,
                                             m->embed_site_constant, codes_out + p * hidden, &es);
    if (st != SslmForwardStatus::Ok) return st;
    scales_out[p] = es;
  }

  std::memset(workspace.data(), 0, workspace.size());
  uint64_t kv_sat = 0;
  if (leg == kSembForwardLegChunkBatched) {
    for (size_t off = 0; off < n; off += chunk_budget) {
      const size_t span = (off + chunk_budget <= n) ? chunk_budget : (n - off);
      const SslmForwardStatus st = RunLayerLoopChunkBatched(
          codes_out + off * hidden, scales_out + off, span, m->layers.data(), m->num_layers, hidden,
          m->view.config.head_dim, m->view.config.num_key_value_heads,
          m->view.config.intermediate_size, m->context_cap, static_cast<int64_t>(off),
          m->view.rope_tables, workspace.data(), workspace.size(), m->option_g_fused, &kv_sat,
          /*site_prefix=*/{}, /*trace_hook_state=*/nullptr, /*q_width=*/m->q_width);
      if (st != SslmForwardStatus::Ok) return st;
    }
    return SslmForwardStatus::Ok;
  }

  // The per-token leg. The K/V store carries state between positions; each
  // position's residual starts from its own embedding, exactly as the
  // chunk-batched path's own contract states.
  SequenceLayerState seq;
  seq.kv_saturation_count = 0;
  seq.context_length = 0;
  for (size_t p = 0; p < n; ++p) {
    seq.hidden_codes = codes_out + p * hidden;
    seq.hidden_scale = scales_out[p];
    seq.layer_index = 0;
    seq.context_length = static_cast<int64_t>(p);
    SslmForwardStatus st;
    if (m->option_g_fused) {
      st = RunLayerLoop(seq, m->layers.data(), m->num_layers, m->num_layers, hidden,
                        m->view.config.head_dim, m->view.config.num_key_value_heads,
                        m->view.config.intermediate_size, m->context_cap, m->view.rope_tables,
                        workspace.data(), workspace.size(), OptionGKLandingMode::kFused,
                        /*site_prefix=*/{}, /*token_index=*/0, /*trace_hook_state=*/nullptr,
                        /*q_width=*/m->q_width);
    } else {
      st = RunLayerLoop(seq, m->layers.data(), m->num_layers, m->num_layers, hidden,
                        m->view.config.head_dim, m->view.config.num_key_value_heads,
                        m->view.config.intermediate_size, m->context_cap, m->view.rope_tables,
                        workspace.data(), workspace.size(), /*site_prefix=*/{},
                        /*token_index=*/0, /*trace_hook_state=*/nullptr, /*q_width=*/m->q_width);
    }
    if (st != SslmForwardStatus::Ok) return st;
    scales_out[p] = seq.hidden_scale;
  }
  return SslmForwardStatus::Ok;
}

bool TryAcquireWorkspace(EncoderModel* m, size_t* out_index) {
  std::lock_guard<std::mutex> lock(m->workspace_mutex);
  for (size_t i = 0; i < m->workspaces.size(); ++i) {
    if (!m->workspaces[i].in_use) {
      m->workspaces[i].in_use = true;
      *out_index = i;
      return true;
    }
  }
  return false;
}

void ReleaseWorkspace(EncoderModel* m, size_t index) {
  std::lock_guard<std::mutex> lock(m->workspace_mutex);
  m->workspaces[index].in_use = false;
}

struct WorkspaceLease {
  EncoderModel* model;
  size_t index;
  ~WorkspaceLease() { ReleaseWorkspace(model, index); }
};

}  // namespace
}  // namespace semb

// ---------------------------------------------------------------------------
// The U0 witness verb, unchanged in shape (one-shot: opens, encodes, closes).
// ---------------------------------------------------------------------------
extern "C" SembEncodeStatus semb_encode_document_for_witness(const char* model_path,
                                                               const int32_t* token_ids, size_t n,
                                                               size_t chunk_budget,
                                                               int8_t* codes_out, int64_t* m_out,
                                                               int64_t* e_out,
                                                               size_t* hidden_out) {
  semb::EncoderModel* model = semb::EncoderOpen(model_path, nullptr);
  if (!model) return kSembEncodeEngineRefused;

  const size_t hidden = model->hidden_size;
  // TE-79 F-7 (Significant, TE-76 review): the real hidden_size is only
  // known now, after the model has opened -- refused here, before
  // *hidden_out, codes_out, m_out or e_out are touched, rather than
  // writing n*hidden bytes into a codes_out buffer no caller could have
  // sized correctly (this verb takes no capacity parameter; see
  // seam_abi.h's own kSembWitnessMaxHidden comment for why).
  if (hidden > kSembWitnessMaxHidden) {
    semb::EncoderClose(model);
    return kSembEncodeHiddenTooLarge;
  }
  if (hidden_out) *hidden_out = hidden;

  std::vector<superslm::CarriedScale> scales(n);
  size_t workspace_index = 0;
  if (!semb::TryAcquireWorkspace(model, &workspace_index)) {
    semb::EncoderClose(model);
    return kSembEncodeEngineRefused;
  }
  superslm::SslmForwardStatus st;
  {
    semb::WorkspaceLease lease{model, workspace_index};
    st = semb::Encode(model, model->workspaces[workspace_index].bytes, token_ids, n,
                      chunk_budget, kSembForwardLegChunkBatched, codes_out, scales.data());
  }
  if (st != superslm::SslmForwardStatus::Ok) {
    semb::EncoderClose(model);
    return kSembEncodeEngineRefused;
  }
  for (size_t p = 0; p < n; ++p) {
    m_out[p] = scales[p].m;
    e_out[p] = scales[p].e;
  }
  semb::EncoderClose(model);
  return kSembEncodeOk;
}

// ---------------------------------------------------------------------------
// The handle surface (encoder_interim_abi.h).
// ---------------------------------------------------------------------------
struct SembInterimEncoder {
  semb::EncoderModel* model = nullptr;
};

namespace {

const char* OkName() { return "Ok"; }

}  // namespace

extern "C" SembInterimStatus semb_interim_encoder_open(const char* model_path,
                                                        int32_t appended_token_id,
                                                        SembInterimEncoder** out_encoder,
                                                        const char** out_engine_status_name) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (!model_path || !out_encoder) return kSembInterimNullArgument;
  *out_encoder = nullptr;
  const char* name = nullptr;
  semb::EncoderModel* model = semb::EncoderOpen(model_path, &name);
  if (!model) {
    if (out_engine_status_name) *out_engine_status_name = name ? name : "Unknown";
    return kSembInterimEngineRefused;
  }
  std::unique_ptr<semb::EncoderModel, void (*)(semb::EncoderModel*)> model_guard(
      model, semb::EncoderClose);
  model->appended_token_id = appended_token_id;
  auto enc = std::make_unique<SembInterimEncoder>();
  enc->model = model_guard.release();
  *out_encoder = enc.release();
  return kSembInterimOk;
}

extern "C" SembInterimStatus semb_interim_encoder_open_from_memory(
    const uint8_t* model_bytes, size_t model_size, int32_t appended_token_id,
    uint32_t max_concurrency, SembInterimEncoder** out_encoder,
    const char** out_engine_status_name) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (!model_bytes || model_size == 0 || max_concurrency == 0 || !out_encoder) {
    return kSembInterimNullArgument;
  }
  *out_encoder = nullptr;
  const char* name = nullptr;
  semb::EncoderModel* model =
      semb::EncoderOpenFromMemory(model_bytes, model_size, max_concurrency, &name);
  if (!model) {
    if (out_engine_status_name) *out_engine_status_name = name ? name : "Unknown";
    return kSembInterimEngineRefused;
  }
  std::unique_ptr<semb::EncoderModel, void (*)(semb::EncoderModel*)> model_guard(
      model, semb::EncoderClose);
  model->appended_token_id = appended_token_id;
  auto enc = std::make_unique<SembInterimEncoder>();
  enc->model = model_guard.release();
  *out_encoder = enc.release();
  return kSembInterimOk;
}

SembInterimStatus semb_interim_encoder_open_owned(
    std::vector<uint8_t>&& model_bytes, int32_t appended_token_id,
    uint32_t max_concurrency, SembInterimEncoder** out_encoder,
    const char** out_engine_status_name) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (model_bytes.empty() || max_concurrency == 0 || !out_encoder) {
    return kSembInterimNullArgument;
  }
  *out_encoder = nullptr;
  const char* name = nullptr;
  semb::EncoderModel* model =
      semb::EncoderOpenOwned(std::move(model_bytes), max_concurrency, &name);
  if (!model) {
    if (out_engine_status_name) *out_engine_status_name = name ? name : "Unknown";
    return kSembInterimEngineRefused;
  }
  std::unique_ptr<semb::EncoderModel, void (*)(semb::EncoderModel*)> model_guard(
      model, semb::EncoderClose);
  model->appended_token_id = appended_token_id;
  auto enc = std::make_unique<SembInterimEncoder>();
  enc->model = model_guard.release();
  *out_encoder = enc.release();
  return kSembInterimOk;
}

extern "C" void semb_interim_encoder_close(SembInterimEncoder* encoder) {
  if (!encoder) return;
  semb::EncoderClose(encoder->model);
  delete encoder;
}

extern "C" SembInterimStatus semb_interim_encoder_geometry(const SembInterimEncoder* encoder,
                                                            SembInterimGeometry* out_geometry) {
  if (!encoder || !out_geometry) return kSembInterimNullArgument;
  if (out_geometry->struct_size != sizeof(SembInterimGeometry)) return kSembInterimStructSizeMismatch;
  const semb::EncoderModel* m = encoder->model;
  out_geometry->hidden_size = m->view.config.hidden_size;
  out_geometry->num_hidden_layers = m->view.config.num_hidden_layers;
  out_geometry->num_attention_heads = m->view.config.num_attention_heads;
  out_geometry->num_key_value_heads = m->view.config.num_key_value_heads;
  out_geometry->head_dim = m->view.config.head_dim;
  out_geometry->vocab_size = m->view.config.vocab_size;
  out_geometry->context_cap = m->view.config.context_cap;
  out_geometry->appended_token_id = m->appended_token_id;
  return kSembInterimOk;
}

extern "C" SembInterimStatus semb_interim_encode_seam(
    SembInterimEncoder* encoder, const int32_t* content_ids, size_t n_content, size_t chunk_budget,
    SembForwardLeg leg, int8_t* codes_out, size_t codes_capacity, int64_t* m_out, int64_t* e_out,
    size_t scales_capacity, size_t* out_positions, const char** out_engine_status_name) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (!encoder || !out_positions) return kSembInterimNullArgument;
  if (n_content > 0 && !content_ids) return kSembInterimNullArgument;
  if (n_content == 0) {
    *out_positions = 0;
    return kSembInterimInputEmpty;
  }
  if (leg != kSembForwardLegChunkBatched && leg != kSembForwardLegPerToken) {
    *out_positions = n_content + 1;
    return kSembInterimInvalidLeg;
  }
  semb::EncoderModel* m = encoder->model;
  const size_t n = n_content + 1;  // the appended end token
  *out_positions = n;
  const size_t hidden = m->hidden_size;
  if (codes_capacity < n * hidden || scales_capacity < n) return kSembInterimBufferTooSmall;
  if (!codes_out || !m_out || !e_out) return kSembInterimNullArgument;

  // SuperEmbedder's own code appends the single fixed end token id (sec 3.2)
  // to the token-id sequence, never composed as text and re-tokenized.
  std::vector<int32_t> tokens(n);
  std::memcpy(tokens.data(), content_ids, n_content * sizeof(int32_t));
  tokens[n_content] = m->appended_token_id;

  std::vector<superslm::CarriedScale> scales(n);
  size_t workspace_index = 0;
  if (!semb::TryAcquireWorkspace(m, &workspace_index)) {
    return kSembInterimConcurrencyExceeded;
  }
  semb::WorkspaceLease lease{m, workspace_index};
  const superslm::SslmForwardStatus st = semb::Encode(
      m, m->workspaces[workspace_index].bytes, tokens.data(), n, chunk_budget, leg,
      codes_out, scales.data());
  if (st != superslm::SslmForwardStatus::Ok) {
    if (out_engine_status_name) {
      *out_engine_status_name = semb::SetEngineStatus(superslm::SslmForwardStatusName(st));
    }
    return kSembInterimEngineRefused;
  }
  for (size_t p = 0; p < n; ++p) {
    m_out[p] = scales[p].m;
    e_out[p] = scales[p].e;
  }
  return kSembInterimOk;
}

extern "C" SembInterimStatus semb_interim_ps_n_select(const SembInterimEncoder* encoder,
                                                       const int8_t* codes, const int64_t* m,
                                                       const int64_t* e, size_t n, size_t position,
                                                       int8_t* out_codes, int64_t* out_m,
                                                       int64_t* out_e,
                                                       const char** out_engine_status_name) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (!encoder || !codes || !m || !e || !out_codes || !out_m || !out_e) {
    return kSembInterimNullArgument;
  }
  if (position >= n) return kSembInterimPositionOutOfRange;
  const semb::EncoderModel* model = encoder->model;
  const size_t hidden = model->hidden_size;
  const superslm::CarriedScale incoming{m[position], e[position]};
  superslm::CarriedScale out_scale{};
  // The engine's own final norm, under the same site name and site constant
  // its generation loop applies before the head -- PS-N's post-final-norm
  // source state (sec 3.2). The incoming scale is annihilated by the site's
  // own scale-killing form (forward_sites.h's RmsNormSite contract).
  const superslm::SslmForwardStatus st = superslm::RmsNormSite(
      codes + position * hidden, model->final_norm_gain.data(), hidden, incoming,
      model->final_norm_site_constant, out_codes, &out_scale, "final_norm");
  if (st != superslm::SslmForwardStatus::Ok) {
    if (out_engine_status_name) {
      *out_engine_status_name = semb::SetEngineStatus(superslm::SslmForwardStatusName(st));
    }
    return kSembInterimEngineRefused;
  }
  *out_m = out_scale.m;
  *out_e = out_scale.e;
  return kSembInterimOk;
}

extern "C" SembInterimStatus semb_interim_encode_ps_n(
    SembInterimEncoder* encoder, const int32_t* content_ids, size_t n_content, size_t chunk_budget,
    float* out_vector, size_t out_capacity_bytes, size_t* out_required_bytes,
    SembWaPoolStatus* out_dequantize_status, const char** out_engine_status_name) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (out_dequantize_status) *out_dequantize_status = kSembOk;
  if (!encoder || !out_required_bytes) return kSembInterimNullArgument;
  semb::EncoderModel* m = encoder->model;
  const size_t hidden = m->hidden_size;
  *out_required_bytes = hidden * sizeof(float);
  if (n_content == 0) return kSembInterimInputEmpty;
  if (out_capacity_bytes < hidden * sizeof(float)) return kSembInterimBufferTooSmall;
  if (!out_vector || !content_ids) return kSembInterimNullArgument;

  const size_t n = n_content + 1;
  std::vector<int8_t> codes(n * hidden);
  std::vector<int64_t> ms(n), es(n);
  size_t positions = 0;
  SembInterimStatus st = semb_interim_encode_seam(encoder, content_ids, n_content, chunk_budget,
                                                  kSembForwardLegChunkBatched, codes.data(),
                                                  codes.size(), ms.data(), es.data(), n,
                                                  &positions, out_engine_status_name);
  if (st != kSembInterimOk) return st;

  // PS-N's position rule: the LAST position -- the appended end token's.
  std::vector<int8_t> sel(hidden);
  int64_t sel_m = 0, sel_e = 0;
  st = semb_interim_ps_n_select(encoder, codes.data(), ms.data(), es.data(), n, n - 1, sel.data(),
                                &sel_m, &sel_e, out_engine_status_name);
  if (st != kSembInterimOk) return st;

  const SembWaPoolStatus dq = semb_ps_n_dequantize(sel.data(), sel_m, sel_e, hidden, out_vector);
  if (out_dequantize_status) *out_dequantize_status = dq;
  if (dq != kSembOk) return kSembInterimDequantizeRefused;
  return kSembInterimOk;
}
