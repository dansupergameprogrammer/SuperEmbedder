// src/superembedder/engine_adapter_interim.cpp -- TE-63 (U0 slice B): THE
// interim adapter, and the only one (`Claude/Plans/SuperEmbedder_Plan.md`
// sec 4.3: "the skeleton composes the forward from SuperSLM's installed
// C++ headers behind SuperEmbedder's own engine-adapter seam, calling
// EmbedEntry + RunLayerLoopChunkBatched"). This is the ONE translation
// unit in this library that names EmbedEntry, RunLayerLoopChunkBatched,
// MarshalLayer or SslmModel::Load -- `tests/c39_singleton_check.py` is the
// structural check that enforces this (sec 8, C39/C31 clause 3: W-A's
// drivers and this adapter are compiled INTO the library; the engine's
// `inline` primitives must be reached through the library's own
// translation unit, never re-compiled inside a sibling TU).
//
// Ported from `Claude/Vitruvius/t2217-fold4-probe/cost/semb_encoder_interim.cpp`
// (the plan's own named starting point, sec 4.3: "this TU is the reference
// implementation U1 adopts as engine_adapter_interim.cpp") under product
// discipline: the probe's `#include "sslm_marshal.h"` is corrected to the
// engine's actual installed header name, `<superslm/layer_marshal.h>`
// (confirmed installed and exporting MarshalLayer/ReadCarriedScale/
// WidenGainToInt32/PreflightScanWscFolds/LayerBacking -- brief's own
// "facts verified this session"); the probe's two must-fail hazard
// `#ifdef` blocks (FOLD9_MUSTFAIL_ENCODER_DRIFT/BUDGET_HAZARD) are not
// carried over -- they were the probe's own commissioning constructions
// for ITS identity/inertness cells, never part of the specified adapter,
// and this file is the specified adapter, not a probe.
//
// THIS TU'S OWN SEAM: `semb_encode_document_for_witness` (tests/
// semb_seam_abi_contract.h) opens the artifact, marshals every layer,
// embeds every token, and runs the chunk-batched forward at the caller's
// chunk budget -- one call, no persistent handle, matching the ABI
// contract's own one-shot shape (there is no separate open/close verb at
// U0; that is U1's `semb_encoder_open`).
#include "superembedder/seam_abi.h"

#include <cstring>
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

namespace semb {
namespace {

struct EncoderModel {
  std::vector<uint8_t> model_bytes;
  SslmModelView view;
  std::vector<LayerBacking> backings;
  std::vector<LayerWeights> layers;
  const int8_t* embed_weights = nullptr;
  CarriedScale embed_site_constant{};
  std::vector<uint8_t> workspace;
  size_t hidden_size = 0;
  uint32_t num_layers = 0;
  int64_t context_cap = 0;
  bool option_g_fused = false;
};

// Opens the artifact and marshals every layer. Returns nullptr on any
// failure -- the caller reports kSembEncodeEngineRefused; the exact
// SslmModelStatus/SslmForwardStatus is not yet propagated across the seam
// at U0 (sec 8 C4's own "never propagated as an engine enum across the
// seam" rule is U1's mapping to SEMB_ENGINE_REFUSED; this seam is a
// two-valued witness call, not the product's own bake path).
EncoderModel* EncoderOpen(const std::string& model_path) {
  auto m = new EncoderModel();
  if (!ReadFile(model_path.c_str(), m->model_bytes)) {
    delete m;
    return nullptr;
  }
  std::string model_err;
  if (SslmModel::Load(m->model_bytes.data(), m->model_bytes.size(), m->view, &model_err) !=
      SslmModelStatus::Ok) {
    delete m;
    return nullptr;
  }
  const uint32_t num_heads = m->view.config.num_attention_heads;
  const uint32_t num_kv_heads = m->view.config.num_key_value_heads;
  m->num_layers = m->view.config.num_hidden_layers;
  m->hidden_size = m->view.config.hidden_size;
  m->context_cap = static_cast<int64_t>(m->view.config.context_cap);
  m->option_g_fused = m->view.option_g_fused_k_landing;

  PreflightScanWscFolds(m->view);
  m->backings.resize(m->num_layers);
  m->layers.resize(m->num_layers);
  for (uint32_t l = 0; l < m->num_layers; ++l) {
    std::string merr;
    if (!MarshalLayer(m->view, l, num_heads, num_kv_heads, m->backings[l], m->layers[l], &merr)) {
      delete m;
      return nullptr;
    }
  }
  const SslmTensorView* embed_w = m->view.weights.Tensor("embed");
  if (!embed_w) {
    delete m;
    return nullptr;
  }
  m->embed_weights = reinterpret_cast<const int8_t*>(embed_w->data);
  bool ok = true;
  m->embed_site_constant = ReadCarriedScale(m->view.composition_constants, "embed", &ok);
  if (!ok) {
    delete m;
    return nullptr;
  }
  // RunLayerLoopChunkBatched's own workspace requirement (forward_sites.h):
  // num_hidden_layers * context_cap * num_kv_heads * head_dim * 2.
  m->workspace.assign(static_cast<size_t>(m->num_layers) * static_cast<size_t>(m->context_cap) *
                           num_kv_heads * m->view.config.head_dim * 2,
                       0);
  return m;
}

void EncoderClose(EncoderModel* m) { delete m; }

// The seam: embed every token, then run the chunk-batched forward at
// `chunk_budget` (0 or >= n resolves to one whole-document call).
SslmForwardStatus Encode(EncoderModel* m, const int32_t* tokens, size_t n, size_t chunk_budget,
                          int8_t* codes_out, CarriedScale* scales_out) {
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

  std::memset(m->workspace.data(), 0, m->workspace.size());
  uint64_t kv_sat = 0;
  for (size_t off = 0; off < n; off += chunk_budget) {
    const size_t span = (off + chunk_budget <= n) ? chunk_budget : (n - off);
    const SslmForwardStatus st = RunLayerLoopChunkBatched(
        codes_out + off * hidden, scales_out + off, span, m->layers.data(), m->num_layers, hidden,
        m->view.config.head_dim, m->view.config.num_key_value_heads,
        m->view.config.intermediate_size, m->context_cap, static_cast<int64_t>(off),
        m->view.rope_tables, m->workspace.data(), m->workspace.size(), m->option_g_fused, &kv_sat);
    if (st != SslmForwardStatus::Ok) return st;
  }
  return SslmForwardStatus::Ok;
}

}  // namespace
}  // namespace semb

extern "C" SembEncodeStatus semb_encode_document_for_witness(const char* model_path,
                                                               const int32_t* token_ids, size_t n,
                                                               size_t chunk_budget,
                                                               int8_t* codes_out, int64_t* m_out,
                                                               int64_t* e_out,
                                                               size_t* hidden_out) {
  semb::EncoderModel* model = semb::EncoderOpen(model_path);
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
  const superslm::SslmForwardStatus st =
      semb::Encode(model, token_ids, n, chunk_budget, codes_out, scales.data());
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
