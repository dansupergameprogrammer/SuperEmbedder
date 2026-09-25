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
#include "superembedder/seam_abi.h"  // semb_seam_serialize_document (TE-159 C-2's seam tap)
#include "encoder_open_internal.h"

#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <fstream>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

// TE-356 (C-2): platform memory query for FinishEncoderOpen's adaptive
// workspace cap, below. Each branch reads THIS machine's own free memory at
// open time; none of them is a promise (StandardsDocument.md 5.4's
// resolution-floor rule -- a reading converts "definitely will not fit" into
// a refusal reliably, never "reads as fitting" into a guarantee against a
// concurrent allocator elsewhere in the process).
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#elif defined(__APPLE__)
#include <mach/mach.h>
#include <mach/mach_host.h>
#else
#include <unistd.h>
#endif

#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
#include "support/semb_workspace_seam.h"
#include "support/semb_u2_memory_seam.h"
#include <atomic>
#include <system_error>
#include "superslm/forward_sites.h"
#include <chrono>
#include <condition_variable>

namespace semb::test_seam {
static std::mutex state_mutex;
static std::condition_variable state_changed;
static uint32_t park_budget = 0;
static uint32_t parked = 0;
static uint64_t release_generation = 0;
static std::atomic<uint64_t> acquisitions{0};

static void OnAcquired() {
  acquisitions.fetch_add(1);
  std::unique_lock<std::mutex> lock(state_mutex);
  if (park_budget == 0) return;
  --park_budget;
  ++parked;
  const uint64_t generation = release_generation;
  state_changed.notify_all();
  state_changed.wait(lock, [generation] { return release_generation != generation; });
  --parked;
}

// TE-184 (D-SLM6434 item 2, TE-161 N-5, TE-149 sec 7 bare cell 2): a
// SECOND, independent park point at per-DOCUMENT granularity, distinct
// from OnAcquired's once-per-ACQUISITION park above. The batch verb
// (semb_interim_encode_batch_ps_n, below) acquires at most T workspace
// slots for the whole call (TE-350: T <= min(doc_count, pool size, hardware
// concurrency) -- an upper bound, not an equality; contention with another
// in-flight call can leave fewer free (TE-356) -- one worker thread per
// acquired slot) and each worker holds
// its own slot across every document that worker processes; OnAcquired
// fires once per slot, at that WORKER's entry (TE-356: every slot is
// actually acquired earlier, on the calling thread, inside WorkspacePool's
// own constructor, before any worker exists -- OnAcquired's firing point is
// a worker starting to use an already-acquired slot, not the acquisition
// itself), so no existing construction can observe a slot BETWEEN two documents processed by the
// SAME worker on that slot -- only between two separate acquisitions
// (which, at T == 1, is exactly "between two separate calls", the original
// TE-184 property, unchanged). This hook, called once per document inside
// a worker's own per-document loop -- possibly by more than one worker
// thread concurrently when T > 1 -- lets a test park a calling thread
// mid-call, still holding that thread's own slot, so a contender's own
// attempt to acquire a DIFFERENT slot at that finer granularity is
// observable: a defect that released and reacquired mid-row would be
// invisible to OnAcquired's own once-per-acquisition crossing alone.
// Shares state_mutex/state_changed with OnAcquired above (one lock
// protects both counters, safe under concurrent callers); its own
// budget/counter/generation are independent so arming one hook never arms
// the other.
static uint32_t row_park_budget = 0;
static uint32_t row_parked = 0;
static uint64_t row_release_generation = 0;
static std::atomic<uint64_t> row_acquisitions{0};

static void OnRowAcquired() {
  row_acquisitions.fetch_add(1);
  std::unique_lock<std::mutex> lock(state_mutex);
  if (row_park_budget == 0) return;
  --row_park_budget;
  ++row_parked;
  const uint64_t generation = row_release_generation;
  state_changed.notify_all();
  state_changed.wait(lock, [generation] { return row_release_generation != generation; });
  --row_parked;
}

// ---------------------------------------------------------------------------
// U2 cloud build, the seam commit (te267 sec 6.1 step 1): U2-9 Builds item 9's
// readers and arms, and U2-10 Builds item 2c's spawn fail arm (C66). Test-only,
// under this guard, so none of it reaches the shipped library. The C surface is
// tests/support/semb_u2_memory_seam.h; the C++ hooks below are what the builder
// calls from the U2-9/U2-10 build (that header's comment lists each one). On
// today's pool nothing calls the growth, fill, forced-reference or gate hooks.
// ---------------------------------------------------------------------------
static std::atomic<uint64_t> slot_growths{0};
static std::atomic<int32_t> fill_byte{-1};
static std::atomic<int32_t> forced_reference{0};

static std::mutex growth_fail_mutex;
static uint64_t growth_fail_min_c = 0;
static bool growth_fail_fired = false;
static uint64_t growth_fail_capacity_at_fire = 0;

// The builder's growth site calls this inside the new buffer's allocation
// step, before the allocation: `c` is the new C, `current_capacity` the slot
// buffer's capacity at that moment. Throws std::bad_alloc when the fail arm
// is armed and c >= its value (one shot), recording the capacity.
[[maybe_unused]] static void BeforeSlotGrowth(uint64_t c, uint64_t current_capacity) {
  std::lock_guard<std::mutex> lock(growth_fail_mutex);
  if (growth_fail_min_c != 0 && c >= growth_fail_min_c) {
    growth_fail_min_c = 0;
    growth_fail_fired = true;
    growth_fail_capacity_at_fire = current_capacity;
    throw std::bad_alloc();
  }
}

// After a successful growth: counts it, and applies the fill arm.
[[maybe_unused]] static void AfterSlotGrowth(uint8_t* data, size_t bytes) {
  slot_growths.fetch_add(1);
  const int32_t fb = fill_byte.load();
  if (fb >= 0 && data && bytes) std::memset(data, fb, bytes);
}

[[maybe_unused]] static bool ForcedReferenceArmed() { return forced_reference.load() != 0; }

// The long-document gate's hooks (U2-9 item 6).
static uint32_t gate_park_budget = 0;
static uint32_t gate_parked = 0;
static uint64_t gate_release_generation = 0;
static uint32_t gate_holders = 0;
static uint32_t gate_high_water = 0;
static uint32_t gate_waiters = 0;
static std::vector<uint64_t> gate_take_records;
static std::vector<uint64_t> gate_give_records;

[[maybe_unused]] static void OnGateWaitBegin() {
  std::lock_guard<std::mutex> lock(state_mutex);
  ++gate_waiters;
  state_changed.notify_all();
}
[[maybe_unused]] static void OnGateWaitEnd() {
  std::lock_guard<std::mutex> lock(state_mutex);
  if (gate_waiters) --gate_waiters;
  state_changed.notify_all();
}
[[maybe_unused]] static void OnGateTaken(uint64_t capacity) {
  std::lock_guard<std::mutex> lock(state_mutex);
  gate_take_records.push_back(capacity);
  ++gate_holders;
  if (gate_holders > gate_high_water) gate_high_water = gate_holders;
  state_changed.notify_all();
}
// The park point: after the holder's buffer has grown, before its forward.
[[maybe_unused]] static void OnGateHolding() {
  std::unique_lock<std::mutex> lock(state_mutex);
  if (gate_park_budget == 0) return;
  --gate_park_budget;
  ++gate_parked;
  const uint64_t generation = gate_release_generation;
  state_changed.notify_all();
  state_changed.wait(lock, [generation] { return gate_release_generation != generation; });
  --gate_parked;
}
[[maybe_unused]] static void OnGateGiveBack(uint64_t capacity) {
  std::lock_guard<std::mutex> lock(state_mutex);
  gate_give_records.push_back(capacity);
  if (gate_holders) --gate_holders;
  state_changed.notify_all();
}

// The poison arm (C60's must-reject and must-accept).
static std::mutex poison_mutex;
static bool poison_armed = false;
static bool poison_fired = false;
static uint64_t poison_split = 0;
static uint64_t poison_begin = 0;
static uint64_t poison_end = 0;
static uint8_t poison_byte = 0;

// Called by semb::Encode at the start of each chunk-batched call (at = its
// offset) and before each per-token position (at = the position).
// `context_cap` must be the cap the forward itself receives.
[[maybe_unused]] static void PoisonAt(uint64_t at, uint8_t* workspace, uint32_t num_layers,
                                      int64_t context_cap, size_t num_kv_heads, size_t head_dim) {
  std::lock_guard<std::mutex> lock(poison_mutex);
  if (!poison_armed || at != poison_split) return;
  poison_armed = false;
  poison_fired = true;
  const uint64_t end = std::min<uint64_t>(poison_end, static_cast<uint64_t>(context_cap));
  for (uint32_t layer = 0; layer < num_layers; ++layer) {
    for (size_t kvh = 0; kvh < num_kv_heads; ++kvh) {
      for (uint64_t pos = poison_begin; pos < end; ++pos) {
        int8_t* row = superslm::MutableKeyRow(workspace, layer, context_cap, num_kv_heads, head_dim,
                                              kvh, static_cast<int64_t>(pos));
        std::memset(row, poison_byte, head_dim);
      }
    }
  }
}

// C66's spawn fail arm (U2-10 Builds item 2c): called in place of each
// worker thread's construction with a token unique to the batch call
// (NextBatchCallToken(), taken once per batch call).
static std::atomic<uint64_t> batch_call_tokens{0};
[[maybe_unused]] static uint64_t NextBatchCallToken() { return ++batch_call_tokens; }
static std::mutex spawn_mutex;
static uint32_t spawn_fail_k = 0;
static uint32_t spawn_seen = 0;
static bool spawn_fired = false;
static uint64_t spawn_fired_call = 0;
static uint32_t spawn_starts_after = 0;
static uint64_t spawn_current_call = 0;

[[maybe_unused]] static void OnWorkerStart(uint64_t call_token) {
  std::lock_guard<std::mutex> lock(spawn_mutex);
  if (spawn_fired) {
    if (call_token == spawn_fired_call) ++spawn_starts_after;
    return;
  }
  if (spawn_fail_k == 0) return;
  if (call_token != spawn_current_call) {
    spawn_current_call = call_token;
    spawn_seen = 0;
  }
  ++spawn_seen;
  if (spawn_seen == spawn_fail_k) {
    spawn_fail_k = 0;
    spawn_fired = true;
    spawn_fired_call = call_token;
    spawn_starts_after = 0;
    throw std::system_error(std::make_error_code(std::errc::resource_unavailable_try_again));
  }
}
}  // namespace semb::test_seam

extern "C" int32_t semb_test_seam_arm_park(uint32_t count) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  if (semb::test_seam::parked != 0) return 0;
  semb::test_seam::park_budget = count;
  return 1;
}

extern "C" uint32_t semb_test_seam_parked(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::parked;
}

extern "C" int32_t semb_test_seam_wait_parked(uint32_t n, uint32_t timeout_ms) {
  std::unique_lock<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::state_changed.wait_for(
      lock, std::chrono::milliseconds(timeout_ms),
      [n] { return semb::test_seam::parked >= n; }) ? 1 : 0;
}

extern "C" void semb_test_seam_release(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  ++semb::test_seam::release_generation;
  semb::test_seam::park_budget = 0;
  semb::test_seam::state_changed.notify_all();
}

extern "C" uint64_t semb_test_seam_acquisitions(void) {
  return semb::test_seam::acquisitions.load();
}

extern "C" int32_t semb_test_seam_reset(void) {
  // The caller joins every worker/helper before resetting the counter epoch.
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  if (semb::test_seam::parked != 0) return 0;
  semb::test_seam::park_budget = 0;
  semb::test_seam::acquisitions.store(0);
  ++semb::test_seam::release_generation;
  return 1;
}

// TE-184 (D-SLM6434 item 2): the per-document park point's own surface, in
// the identical shape as the once-per-call surface above -- arm/parked/
// wait_parked/release/acquisitions/reset -- but naming the "row" hook
// (OnRowAcquired) each function reaches, so a test that wants call
// granularity and one that wants row granularity can arm each
// independently without one silently arming the other.
extern "C" int32_t semb_test_seam_row_arm_park(uint32_t count) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  if (semb::test_seam::row_parked != 0) return 0;
  semb::test_seam::row_park_budget = count;
  return 1;
}

extern "C" uint32_t semb_test_seam_row_parked(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::row_parked;
}

extern "C" int32_t semb_test_seam_row_wait_parked(uint32_t n, uint32_t timeout_ms) {
  std::unique_lock<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::state_changed.wait_for(
      lock, std::chrono::milliseconds(timeout_ms),
      [n] { return semb::test_seam::row_parked >= n; }) ? 1 : 0;
}

extern "C" void semb_test_seam_row_release(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  ++semb::test_seam::row_release_generation;
  semb::test_seam::row_park_budget = 0;
  semb::test_seam::state_changed.notify_all();
}

extern "C" uint64_t semb_test_seam_row_acquisitions(void) {
  return semb::test_seam::row_acquisitions.load();
}

extern "C" int32_t semb_test_seam_row_reset(void) {
  // The caller joins every worker/helper before resetting the counter epoch.
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  if (semb::test_seam::row_parked != 0) return 0;
  semb::test_seam::row_park_budget = 0;
  semb::test_seam::row_acquisitions.store(0);
  ++semb::test_seam::row_release_generation;
  return 1;
}
#endif

#include "superslm/forward_sites.h"
#include "superslm/layer_marshal.h"
#include "superslm/model.h"

#include "superembedder/manifest_labels_abi.h"

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

// TE-356 (C-2): a best-effort reading of physical memory actually free on
// THIS machine, right now -- never a figure carried over from any other
// box (main.cpp's retired kBakeMaxConcurrency comment named this project's
// own development box explicitly; that is the defect this closes). Returns
// false when no reading could be taken, which FinishEncoderOpen (below)
// treats as "unknown" rather than "unlimited" -- this term of the policy
// simply does not apply on that platform, named explicitly in the build
// record per StandardsDocument.md sec 5.4.
#if defined(_WIN32)
bool TryQueryAvailableMemoryBytes(size_t* out_bytes) {
  MEMORYSTATUSEX status;
  status.dwLength = sizeof(status);
  if (!GlobalMemoryStatusEx(&status)) return false;
  *out_bytes = static_cast<size_t>(status.ullAvailPhys);
  return true;
}
#elif defined(__APPLE__)
bool TryQueryAvailableMemoryBytes(size_t* out_bytes) {
  const mach_port_t host = mach_host_self();
  vm_size_t page_size = 0;
  if (host_page_size(host, &page_size) != KERN_SUCCESS) return false;
  vm_statistics64_data_t vm_stat{};
  mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;
  if (host_statistics64(host, HOST_VM_INFO64, reinterpret_cast<host_info64_t>(&vm_stat), &count) !=
      KERN_SUCCESS) {
    return false;
  }
  // free + inactive + speculative: pages the kernel will hand out without
  // first paging anything to disk -- the same "available, not merely
  // unallocated" reading /proc/meminfo's MemAvailable targets on Linux
  // (below). wired and active pages are excluded because they are in use.
  const uint64_t free_pages = static_cast<uint64_t>(vm_stat.free_count) +
                              static_cast<uint64_t>(vm_stat.inactive_count) +
                              static_cast<uint64_t>(vm_stat.speculative_count);
  *out_bytes = static_cast<size_t>(free_pages) * static_cast<size_t>(page_size);
  return true;
}
#else
bool TryQueryAvailableMemoryBytes(size_t* out_bytes) {
  // Linux: /proc/meminfo's own MemAvailable estimate (present since kernel
  // 3.14) accounts for reclaimable cache the way a raw free-page count does
  // not, so it is read first; sysconf is the fallback for a kernel or a
  // non-Linux POSIX system without that file.
  std::ifstream meminfo("/proc/meminfo");
  if (meminfo) {
    std::string line;
    const std::string_view key = "MemAvailable:";
    while (std::getline(meminfo, line)) {
      if (line.compare(0, key.size(), key) != 0) continue;
      const char* digits = line.c_str() + key.size();
      char* end = nullptr;
      const unsigned long long kib = std::strtoull(digits, &end, 10);
      if (end == digits) break;
      *out_bytes = static_cast<size_t>(kib) * size_t{1024};
      return true;
    }
  }
#if defined(_SC_AVPHYS_PAGES) && defined(_SC_PAGESIZE)
  const long pages = sysconf(_SC_AVPHYS_PAGES);
  const long page_size = sysconf(_SC_PAGESIZE);
  if (pages > 0 && page_size > 0) {
    *out_bytes = static_cast<size_t>(pages) * static_cast<size_t>(page_size);
    return true;
  }
#endif
  return false;
}
#endif

// TE-356 (C-2): a policy choice, not a derived or measured figure --
// headroom left unrequested at open so the workspace pool alone never
// claims every free byte a memory reading reports, leaving room for the
// OS and whatever else shares the box. Named explicitly as reasoned, not
// measured, per StandardsDocument.md sec 5.4.
constexpr size_t kOpenMemoryReserveBytes = size_t{1} << 30;  // 1 GiB

// Finishes an open after the artifact's exactly-once read has transferred its
// backing into `m`. The model view borrows from that backing for its lifetime.
EncoderModel* FinishEncoderOpen(std::unique_ptr<EncoderModel> m, uint32_t max_concurrency,
                                const char** engine_status_name,
                                uint32_t tokenizer_vocab_size = 0,
                                bool* vocab_mismatch = nullptr) {
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
  // The raw-text join follows all engine validation, but precedes the pool.
  // Interim token-id callers have no tokenizer vocabulary to join.
  if (tokenizer_vocab_size > m->view.config.vocab_size) {
    if (vocab_mismatch) *vocab_mismatch = true;
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

  // TE-356 (C-2): `max_concurrency` is the caller's request -- already
  // capped by document count and by hardware concurrency where the caller
  // knows both (main.cpp's Bake()/Verify() compute
  // min(requested, doc_count, hardware_concurrency) before this call; a raw
  // library caller that wants every requested slot regardless of thread
  // count, e.g. one slot per independent concurrent caller rather than one
  // per worker inside a single batch call, is unaffected -- hardware
  // concurrency is deliberately NOT re-applied here, only by the one
  // caller that means it as a WORKER-COUNT bound). What every caller gets,
  // uniformly, is the one term no caller can compute for itself: this open
  // never allocates more slots than a reading of memory actually free on
  // this machine, right now, can afford, at kOpenMemoryReserveBytes of
  // headroom -- replacing the retired kBakeMaxConcurrency=8 comment's own
  // one-development-box figure with a number sized from the box that is
  // actually opening the handle. Where the reading is unavailable on this
  // toolchain (returns false), this term does not apply -- named
  // explicitly here and in the build record, per StandardsDocument.md sec
  // 5.4, as what this policy does NOT cover on that platform; the caller's
  // own document-count and hardware-concurrency terms still do.
  size_t effective_concurrency = static_cast<size_t>(max_concurrency);
  size_t available_bytes = 0;
  if (TryQueryAvailableMemoryBytes(&available_bytes)) {
    const size_t reserve = std::min(available_bytes, kOpenMemoryReserveBytes);
    const size_t budget = available_bytes - reserve;
    const size_t affordable = (workspace_bytes == 0) ? effective_concurrency : budget / workspace_bytes;
    effective_concurrency = std::min(effective_concurrency, affordable);
  }
  if (effective_concurrency == 0) {
    // Genuinely cannot afford even one workspace slot on this machine.
    // Refuse the same way an allocation failure inside open already does
    // (K-17a's own contract) rather than attempt the allocation and let
    // overcommit -- or a crash -- decide silently. This throw is caught by
    // semb_encoder_open's own catch(std::bad_alloc), which is the ONLY
    // status this path needs; `m` (owned by value in this frame) unwinds
    // cleanly, freeing the artifact bytes and every layer already
    // marshaled above.
    throw std::bad_alloc();
  }
  m->workspaces.resize(effective_concurrency);
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
                               const char** engine_status_name,
                               uint32_t tokenizer_vocab_size,
                               bool* vocab_mismatch) {
  if (model_bytes.empty() || max_concurrency == 0) {
    if (engine_status_name) *engine_status_name = SetEngineStatus("InvalidOpenInput");
    return nullptr;
  }
  auto m = std::make_unique<EncoderModel>();
  m->model_bytes = std::move(model_bytes);
  return FinishEncoderOpen(std::move(m), max_concurrency, engine_status_name,
                           tokenizer_vocab_size, vocab_mismatch);
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
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
      test_seam::PoisonAt(off, workspace.data(), m->num_layers, m->context_cap,
                          m->view.config.num_key_value_heads, m->view.config.head_dim);
#endif
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
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
    test_seam::PoisonAt(p, workspace.data(), m->num_layers, m->context_cap,
                        m->view.config.num_key_value_heads, m->view.config.head_dim);
#endif
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

// TE-350: acquires at most `want` workspace slots up front (fewer if the
// pool has less than `want` free at the moment of the call -- contention
// with another in-flight call on the same handle is not an error, it is
// simply fewer workers for THIS call), and releases every slot it holds
// on destruction, on every path including an exception unwind. Never
// copied or moved, so there is exactly one owner of each acquired index
// for the pool's whole lifetime -- the property that makes "every
// workspace acquired is released before return" checkable by inspection
// rather than by trusting a per-thread cleanup lambda to run on every
// path.
class WorkspacePool {
 public:
  WorkspacePool(EncoderModel* model, size_t want) : model_(model) {
    indices_.reserve(want);
    for (size_t i = 0; i < want; ++i) {
      size_t idx = 0;
      if (!TryAcquireWorkspace(model_, &idx)) break;
      indices_.push_back(idx);
    }
  }
  WorkspacePool(const WorkspacePool&) = delete;
  WorkspacePool& operator=(const WorkspacePool&) = delete;
  ~WorkspacePool() {
    for (size_t index : indices_) ReleaseWorkspace(model_, index);
  }
  size_t count() const { return indices_.size(); }
  size_t index(size_t worker) const { return indices_[worker]; }

 private:
  EncoderModel* model_;
  std::vector<size_t> indices_;
};

// TE-350: T = min(documents, workspaces in the pool, hardware concurrency).
// Bounding by hardware concurrency avoids oversubscribing the machine when
// the pool is sized larger than the box's own thread count; bounding by the
// pool size is the workspace contract itself; bounding by document count
// means a small batch never spins up idle workers with nothing to do.
// std::thread::hardware_concurrency() is permitted to return 0 when it
// cannot determine an answer, in which case this falls back to 1 rather
// than propagating a 0 that would make every batch call refuse for want of
// a worker.
size_t HardwareConcurrencyOrOne() {
  const unsigned hc = std::thread::hardware_concurrency();
  return hc == 0 ? size_t{1} : static_cast<size_t>(hc);
}

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
  bool vocab_mismatch = false;
  return semb::OpenEncoderOwnedWithVocabJoin(
      std::move(model_bytes), appended_token_id, max_concurrency, 0,
      out_encoder, out_engine_status_name, vocab_mismatch);
}

SembInterimStatus semb::OpenEncoderOwnedWithVocabJoin(
    std::vector<uint8_t>&& model_bytes, int32_t appended_token_id,
    uint32_t max_concurrency, uint32_t tokenizer_vocab_size,
    SembInterimEncoder** out_encoder, const char** out_engine_status_name,
    bool& vocab_mismatch) {
  vocab_mismatch = false;
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (model_bytes.empty() || max_concurrency == 0 || !out_encoder) {
    return kSembInterimNullArgument;
  }
  *out_encoder = nullptr;
  const char* name = nullptr;
  semb::EncoderModel* model =
      semb::EncoderOpenOwned(std::move(model_bytes), max_concurrency, &name,
                             tokenizer_vocab_size, &vocab_mismatch);
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
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
  semb::test_seam::OnAcquired();
#endif
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

// TE-147 (U1 slice 2 build), re-stated TE-350 for cross-document
// parallelism: the batch composed path, AT MOST T workspace acquisitions
// for the whole call (T <= min(doc_count, pool size, hardware concurrency),
// see encoder_interim_abi.h's own doc comment for the full contract). Every
// document's own per-document seam+select+dequantize steps are unchanged
// (select and dequantize touch no workspace, so they are called exactly as
// the singleton path calls them; only the seam step -- semb::Encode -- is
// inlined here against a worker's OWN already-held workspace rather than
// going through semb_interim_encode_seam's own internal acquire). Threading
// is scheduling only: each document's arithmetic depends on nothing but
// that document's own tokens and the model's read-only weights, so which
// worker computes it and when never changes what it computes -- output
// offsets (row stride, seam-stream offset) are sizes known before any
// forward runs, precomputed once, never accumulated as a running total
// inside the per-document work.
extern "C" SembInterimStatus semb_interim_encode_batch_ps_n(
    SembInterimEncoder* encoder, const int32_t* const* docs_content_ids,
    const size_t* docs_n_content, size_t doc_count, size_t chunk_budget, float* out_vectors,
    size_t out_capacity_bytes, size_t* out_required_bytes, size_t* out_failed_index,
    SembWaPoolStatus* out_dequantize_status, const char** out_engine_status_name,
    uint8_t* out_seam_stream, size_t out_seam_stream_capacity, size_t* out_seam_stream_len) {
  if (out_engine_status_name) *out_engine_status_name = OkName();
  if (out_dequantize_status) *out_dequantize_status = kSembOk;
  if (out_failed_index) *out_failed_index = 0;
  if (!encoder || !out_required_bytes) return kSembInterimNullArgument;
  semb::EncoderModel* m = encoder->model;
  const size_t hidden = m->hidden_size;
  const size_t required = doc_count * hidden * sizeof(float);
  // TE-159 (C-2): row output is now OPTIONAL. out_vectors == nullptr skips
  // the capacity gate and the select+dequantize half of the composition
  // entirely for every document -- a caller that only taps the seam (W-B)
  // never has to supply a row buffer or pay for PS-N's own final-norm
  // selection and dequantize. *out_required_bytes still reports what a row
  // buffer WOULD need, matching every other capacity-convention verb here.
  *out_required_bytes = required;
  if (out_vectors) {
    if (out_capacity_bytes < required) return kSembInterimBufferTooSmall;
  }
  if (doc_count == 0) {
    // TE-184 (D-SLM6434 item 1, TE-161/TE-148 M-2): the header's own
    // contract ("On success *out_seam_stream_len holds the exact length
    // written") applies to this early return too -- zero documents means
    // zero bytes written to out_seam_stream, and a caller that supplied
    // the pointer reads that fact rather than its own caller-supplied
    // sentinel.
    if (out_seam_stream_len) *out_seam_stream_len = 0;
    return kSembInterimOk;  // the caller's own CORPUS_EMPTY guards n==0 earlier
  }
  if (!docs_content_ids || !docs_n_content) return kSembInterimNullArgument;

  // The seam tap's own capacity, checked BEFORE any forward runs (shape-
  // before-work, the same discipline semb_encode_batch's own steps 1-11
  // apply before its first forward). Each document's serialised record is
  // exactly semb_seam_serialize_document's own VERBATIM layout: u64(n) ||
  // u64(hidden) || n * (codes[hidden] || u64(m) || u64(e)) -- a fixed
  // function of that document's own token count alone, so every document's
  // start offset is knowable from docs_n_content up front (TE-350: this is
  // what makes per-document seam writes safe to run out of order, on
  // disjoint threads, without any running accumulator).
  size_t seam_required = 0;
  std::vector<size_t> seam_offsets;  // seam_offsets[doc]..seam_offsets[doc+1] is doc's own slice
  if (out_seam_stream) {
    seam_offsets.resize(doc_count + 1);
    for (size_t doc = 0; doc < doc_count; ++doc) {
      seam_offsets[doc] = seam_required;
      const size_t n = docs_n_content[doc] + 1;
      seam_required += 16 + n * (hidden + 16);
    }
    seam_offsets[doc_count] = seam_required;
    if (out_seam_stream_len) *out_seam_stream_len = seam_required;
    if (out_seam_stream_capacity < seam_required) return kSembInterimBufferTooSmall;
  }

  // T = min(documents, workspaces in the pool, hardware concurrency). See
  // WorkspacePool's and HardwareConcurrencyOrOne's own comments above.
  const size_t t_target =
      std::min({doc_count, m->workspaces.size(), semb::HardwareConcurrencyOrOne()});
  semb::WorkspacePool pool(m, t_target);
  const size_t worker_count = pool.count();
  if (worker_count == 0) {
    return kSembInterimConcurrencyExceeded;
  }
  // TE-350's deterministic-failure state: every worker records its own
  // failure, if any, into this ONE mutex-guarded slot, keeping only the
  // LOWEST document index seen so far. Workers never stop early on a
  // failure elsewhere -- every document assigned to every worker still
  // runs to completion -- so by the time every worker has joined, this
  // slot holds the true minimum over every document that failed, regardless
  // of which worker reached which document first or how the workers
  // finished relative to each other. The engine-status message is captured
  // as a copy at the point of failure, on the thread that produced it,
  // because `t_last_engine_status` (SetEngineStatus, above) is thread-local
  // -- a raw pointer into it would dangle or point at the wrong message the
  // instant control returns to the calling thread.
  struct FailureRecord {
    size_t doc_index = 0;
    SembInterimStatus interim_status = kSembInterimOk;
    bool has_engine_status = false;
    std::string engine_status;
    SembWaPoolStatus dequant_status = kSembOk;
  };
  std::mutex failure_mutex;
  bool have_failure = false;
  FailureRecord best_failure{};
  // TE-356 (C-1): an exception from ANY worker (spawned or the calling
  // thread's own inline worker 0) is captured here rather than left to
  // propagate out of that worker's own frame -- an uncaught exception
  // escaping a std::thread's initial function is std::terminate by the
  // standard, and ProcessOneDocument performs five heap allocations per
  // document with no boundary of its own. Guarded by the same mutex
  // RecordFailure already uses; the first exception any worker sees wins
  // (later ones are dropped -- one execution is all the caller ever gets
  // back, and every worker that saw one is a machine already in trouble).
  std::exception_ptr captured_exception;
  auto RecordFailure = [&](size_t doc, SembInterimStatus status, bool has_status,
                           const std::string& status_str, SembWaPoolStatus dq) {
    std::lock_guard<std::mutex> lock(failure_mutex);
    if (!have_failure || doc < best_failure.doc_index) {
      have_failure = true;
      best_failure.doc_index = doc;
      best_failure.interim_status = status;
      best_failure.has_engine_status = has_status;
      best_failure.engine_status = status_str;
      best_failure.dequant_status = dq;
    }
  };

  // One document at a time is claimed from this shared counter -- dynamic
  // scheduling rather than a static split -- so workers balance the load
  // evenly even though document encode cost varies with document length;
  // every claim is a distinct fetch_add result, so every document is
  // claimed by exactly one worker, exactly once.
  std::atomic<size_t> next_doc{0};

  auto ProcessOneDocument = [&](size_t doc, std::vector<uint8_t>& workspace_bytes) {
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
    // TE-184 (D-SLM6434 item 2): the per-document park point, fired once
    // per document while that document's OWN worker workspace slot is
    // held. Possibly called concurrently by more than one worker thread
    // when worker_count > 1; state_mutex (shared with OnAcquired) makes
    // that safe. A no-op (one counter increment) when unarmed.
    semb::test_seam::OnRowAcquired();
#endif
    const size_t n_content = docs_n_content[doc];
    const size_t n = n_content + 1;  // the appended end token
    std::vector<int32_t> tokens(n);
    if (n_content > 0) {
      std::memcpy(tokens.data(), docs_content_ids[doc], n_content * sizeof(int32_t));
    }
    tokens[n_content] = m->appended_token_id;

    std::vector<int8_t> codes(n * hidden);
    std::vector<superslm::CarriedScale> scales(n);
    const superslm::SslmForwardStatus st =
        semb::Encode(m, workspace_bytes, tokens.data(), n, chunk_budget,
                    kSembForwardLegChunkBatched, codes.data(), scales.data());
    if (st != superslm::SslmForwardStatus::Ok) {
      RecordFailure(doc, kSembInterimEngineRefused, /*has_status=*/true,
                    superslm::SslmForwardStatusName(st), kSembOk);
      return;
    }

    std::vector<int64_t> ms(n), es(n);
    for (size_t p = 0; p < n; ++p) {
      ms[p] = scales[p].m;
      es[p] = scales[p].e;
    }

    // The seam tap (TE-159, C-2): this document's FULL per-position seam --
    // every position, pre-final-norm, exactly what select below reads ONE
    // position out of -- serialised into this document's own precomputed
    // slice [seam_offsets[doc], seam_offsets[doc + 1]). Passing the exact
    // slice width, not "capacity to the buffer's end", means a defect that
    // ever wrote more than the documented formula would refuse here rather
    // than silently overwrite a neighbouring document's own region on
    // another thread -- stricter than, and (per this format's own VERBATIM
    // contract above) always equal in practice to, the single-threaded
    // predecessor's "remaining capacity to the end of the buffer" bound.
    if (out_seam_stream) {
      const size_t offset = seam_offsets[doc];
      const size_t slice = seam_offsets[doc + 1] - offset;
      size_t doc_len = 0;
      const SembSerializeStatus sst = semb_seam_serialize_document(
          codes.data(), ms.data(), es.data(), n, hidden, out_seam_stream + offset, slice, &doc_len);
      if (sst != kSembSerializeOk) {
        RecordFailure(doc, kSembInterimBufferTooSmall, /*has_status=*/false, std::string(), kSembOk);
        return;
      }
      if (doc_len != slice) {
        // TE-356 (M-3): doc_len is the serializer's OWN report of what it
        // wrote; this precomputed slice width is the only tie between that
        // write and every OTHER document's own start offset in
        // seam_offsets (above). This function's own `16 + n * (hidden +
        // 16)` and seam_serialize.cpp's identical restatement agree today
        // (verified by reading both, not assumed) -- this refuses rather
        // than silently accepting a write shorter or longer than the slice
        // the offset table promised, which a future drift between the two
        // formulas would otherwise leave uninitialised bytes inside a
        // stream whose reported length is the PRECOMPUTED one, not the
        // one actually written.
        RecordFailure(doc, kSembInterimEngineRefused, /*has_status=*/true, "SeamLengthMismatch",
                      kSembOk);
        return;
      }
    }

    // PS-N's position rule: the LAST position. Neither select nor
    // dequantize touches the workspace, so these are the SAME public
    // primitives the singleton path calls (encoder_interim_abi.h). Skipped
    // entirely when no row output was requested (TE-159 C-2): a seam-only
    // caller does not need PS-N's own final-norm selection or dequantize,
    // and skipping means a dequantize corner (kSembPooledSubnormal /
    // kSembPooledOverflow) on a committed W-B document can never turn into
    // a spurious semb_encoder_open refusal that has nothing to do with the
    // digest actually derived. `out_vectors + doc * hidden` is this
    // document's own fixed-stride row -- disjoint from every other
    // document's row regardless of processing order.
    if (out_vectors) {
      std::vector<int8_t> sel(hidden);
      int64_t sel_m = 0, sel_e = 0;
      const char* local_status = nullptr;
      const SembInterimStatus sel_st =
          semb_interim_ps_n_select(encoder, codes.data(), ms.data(), es.data(), n, n - 1, sel.data(),
                                    &sel_m, &sel_e, &local_status);
      if (sel_st != kSembInterimOk) {
        RecordFailure(doc, sel_st, /*has_status=*/local_status != nullptr,
                      local_status ? local_status : "", kSembOk);
        return;
      }

      const SembWaPoolStatus dq =
          semb_ps_n_dequantize(sel.data(), sel_m, sel_e, hidden, out_vectors + doc * hidden);
      if (dq != kSembOk) {
        RecordFailure(doc, kSembInterimDequantizeRefused, /*has_status=*/false, std::string(), dq);
        return;
      }
    }
  };

  auto Worker = [&](size_t worker_workspace_index) {
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
    // Fired on THIS worker's own thread, as the first thing it does after
    // being handed its slot -- not in a loop on the calling thread before
    // any worker starts. OnAcquired can itself BLOCK (park) the calling
    // thread; calling it worker_count times in a pre-spawn loop on one
    // thread would serialize what must be simultaneous parks across
    // worker_count independent threads, defeating the exact observation
    // (tests/u1_batch_workspace_test.cpp's C52) this hook exists to make.
    // At worker_count == 1 this is the ONE call the original single-
    // workspace path always made, on the same calling thread it always
    // ran on (Worker 0 below runs inline, no std::thread spawned).
    semb::test_seam::OnAcquired();
#endif
    std::vector<uint8_t>& workspace_bytes = m->workspaces[worker_workspace_index].bytes;
    // TE-356 (C-1): this try/catch is what makes Worker's own frame return
    // normally on every path -- including a std::bad_alloc from any of
    // ProcessOneDocument's five per-document allocations -- so a spawned
    // thread's initial function never exits via an uncaught exception, and
    // the calling thread's own inline call (worker 0, below) never leaves
    // this function with `threads` still holding joinable threads either.
    // The exception is captured, not acted on here; a worker that caught
    // one stops claiming further documents (continuing to allocate on a
    // thread that just failed to allocate is not a recovery), but every
    // OTHER worker still runs every document assigned to it, exactly as
    // RecordFailure's own lowest-index contract already assumes.
    try {
      for (;;) {
        const size_t doc = next_doc.fetch_add(1, std::memory_order_relaxed);
        if (doc >= doc_count) break;
        ProcessOneDocument(doc, workspace_bytes);
      }
    } catch (...) {
      std::lock_guard<std::mutex> lock(failure_mutex);
      if (!captured_exception) captured_exception = std::current_exception();
    }
  };

  // Threads 1..worker_count-1 are spawned FIRST, so every worker (including
  // worker 0 below) reaches its own OnAcquired call at roughly the same
  // time when the test seam arms a park -- required for C52's "kPoolSize
  // simultaneous parks" observation to be reachable at all. Worker 0 runs
  // on the calling thread itself -- no std::thread is ever created when
  // worker_count == 1, so the single-workspace call this function has
  // always supported is not merely a special case of the parallel path, it
  // is the identical call stack it always was. Every spawned thread is
  // joined before this function inspects any failure state or touches any
  // output length.
  //
  // TE-356 (C-1): `joiner`'s destructor joins every thread `threads` holds
  // on EVERY exit from this point on, including std::thread's own
  // constructor throwing std::system_error partway through the spawn loop
  // below (a documented resource-exhaustion path) -- declared after
  // `threads` so it is destroyed FIRST during unwind (reverse declaration
  // order), before `threads` itself destroys its now-non-joinable
  // std::thread objects. Worker's own try/catch above means neither the
  // spawned threads' entry function nor the inline call below can throw at
  // all in the ordinary (allocation-failure) case; this guard exists for
  // the thread-construction failure Worker's own catch cannot reach,
  // because it fires before that thread's entry function ever runs.
  std::vector<std::thread> threads;
  struct ThreadJoiner {
    std::vector<std::thread>& threads;
    ~ThreadJoiner() {
      for (std::thread& t : threads) {
        if (t.joinable()) t.join();
      }
    }
  } joiner{threads};
  threads.reserve(worker_count - 1);
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
  // C66's spawn fail arm (U2-10 Builds item 2c), at today's spawn statement:
  // fires in place of the thread's construction. Item 2c moves it into
  // StartWorker.
  const uint64_t seam_batch_call = semb::test_seam::NextBatchCallToken();
#endif
  for (size_t w = 1; w < worker_count; ++w) {
#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
    semb::test_seam::OnWorkerStart(seam_batch_call);
#endif
    threads.emplace_back(Worker, pool.index(w));
  }
  Worker(pool.index(0));
  for (std::thread& t : threads) {
    if (t.joinable()) t.join();
  }

  if (captured_exception) {
    // TE-356 (C-1): rethrown only after every spawned thread has been
    // joined above -- std::rethrow_exception restores the ORIGINAL
    // exception object (a std::bad_alloc stays a std::bad_alloc), so the
    // existing catch(std::bad_alloc) at semb_encode_batch and
    // semb_bake_to_path still produces SEMB_ALLOCATION_FAILED exactly as
    // it always has; no new status was added for this.
    std::rethrow_exception(captured_exception);
  }

  if (have_failure) {
    if (out_failed_index) *out_failed_index = best_failure.doc_index;
    if (best_failure.has_engine_status && out_engine_status_name) {
      *out_engine_status_name = semb::SetEngineStatus(best_failure.engine_status);
    }
    if (out_dequantize_status) *out_dequantize_status = best_failure.dequant_status;
    return best_failure.interim_status;
  }
  if (out_seam_stream && out_seam_stream_len) *out_seam_stream_len = seam_required;
  return kSembInterimOk;
}


#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM
// ---------------------------------------------------------------------------
// U2 cloud build, the seam commit: the C surface of
// tests/support/semb_u2_memory_seam.h (see the hook block near the top of this
// file). Readers read today's state on today's pool.
// ---------------------------------------------------------------------------
extern "C" uint64_t semb_test_seam_slot_record_count(const SembInterimEncoder* enc) {
  if (!enc || !enc->model) return 0;
  std::lock_guard<std::mutex> lock(enc->model->workspace_mutex);
  return enc->model->workspaces.size();
}

extern "C" int32_t semb_test_seam_slot_capacity(const SembInterimEncoder* enc, uint64_t index,
                                                uint64_t* out_capacity_bytes) {
  if (!enc || !enc->model || !out_capacity_bytes) return 0;
  std::lock_guard<std::mutex> lock(enc->model->workspace_mutex);
  if (index >= enc->model->workspaces.size()) return 0;
  *out_capacity_bytes = enc->model->workspaces[index].bytes.capacity();
  return 1;
}

extern "C" uint64_t semb_test_seam_model_buffer_capacity(const SembInterimEncoder* enc) {
  if (!enc || !enc->model) return 0;
  return enc->model->model_bytes.capacity();
}

extern "C" uint64_t semb_test_seam_slot_growths(void) { return semb::test_seam::slot_growths.load(); }

extern "C" void semb_test_seam_arm_fill(int32_t byte) {
  semb::test_seam::fill_byte.store(byte < 0 ? -1 : (byte & 0xFF));
}

extern "C" void semb_test_seam_arm_forced_reference(int32_t on) {
  semb::test_seam::forced_reference.store(on ? 1 : 0);
}

extern "C" void semb_test_seam_arm_growth_fail(uint64_t min_c) {
  std::lock_guard<std::mutex> lock(semb::test_seam::growth_fail_mutex);
  semb::test_seam::growth_fail_min_c = min_c;
  semb::test_seam::growth_fail_fired = false;
  semb::test_seam::growth_fail_capacity_at_fire = 0;
}

extern "C" int32_t semb_test_seam_growth_fail_fired(uint64_t* out_capacity_at_fire) {
  std::lock_guard<std::mutex> lock(semb::test_seam::growth_fail_mutex);
  if (out_capacity_at_fire) *out_capacity_at_fire = semb::test_seam::growth_fail_capacity_at_fire;
  return semb::test_seam::growth_fail_fired ? 1 : 0;
}

extern "C" void semb_test_seam_arm_poison(uint64_t split, uint64_t pos_begin, uint64_t pos_end,
                                          uint8_t byte) {
  std::lock_guard<std::mutex> lock(semb::test_seam::poison_mutex);
  semb::test_seam::poison_armed = true;
  semb::test_seam::poison_fired = false;
  semb::test_seam::poison_split = split;
  semb::test_seam::poison_begin = pos_begin;
  semb::test_seam::poison_end = pos_end;
  semb::test_seam::poison_byte = byte;
}

extern "C" int32_t semb_test_seam_poison_disarm(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::poison_mutex);
  semb::test_seam::poison_armed = false;
  const bool fired = semb::test_seam::poison_fired;
  semb::test_seam::poison_fired = false;
  return fired ? 1 : 0;
}

extern "C" int32_t semb_test_seam_gate_arm_park(uint32_t count) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  if (semb::test_seam::gate_parked != 0) return 0;
  semb::test_seam::gate_park_budget = count;
  return 1;
}

extern "C" int32_t semb_test_seam_gate_wait_parked(uint32_t n, uint32_t timeout_ms) {
  std::unique_lock<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::state_changed.wait_for(
      lock, std::chrono::milliseconds(timeout_ms),
      [n] { return semb::test_seam::gate_parked >= n; }) ? 1 : 0;
}

extern "C" uint32_t semb_test_seam_gate_parked(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::gate_parked;
}

extern "C" void semb_test_seam_gate_release(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  ++semb::test_seam::gate_release_generation;
  semb::test_seam::gate_park_budget = 0;
  semb::test_seam::state_changed.notify_all();
}

extern "C" uint32_t semb_test_seam_gate_holders(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::gate_holders;
}

extern "C" uint32_t semb_test_seam_gate_high_water(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::gate_high_water;
}

extern "C" uint32_t semb_test_seam_gate_waiters(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  return semb::test_seam::gate_waiters;
}

extern "C" uint64_t semb_test_seam_gate_take_records(uint64_t* out, uint64_t cap) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  const auto& r = semb::test_seam::gate_take_records;
  for (uint64_t i = 0; out && i < cap && i < r.size(); ++i) out[i] = r[i];
  return r.size();
}

extern "C" uint64_t semb_test_seam_gate_give_records(uint64_t* out, uint64_t cap) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  const auto& r = semb::test_seam::gate_give_records;
  for (uint64_t i = 0; out && i < cap && i < r.size(); ++i) out[i] = r[i];
  return r.size();
}

extern "C" int32_t semb_test_seam_gate_reset(void) {
  std::lock_guard<std::mutex> lock(semb::test_seam::state_mutex);
  if (semb::test_seam::gate_parked != 0) return 0;
  semb::test_seam::gate_park_budget = 0;
  semb::test_seam::gate_holders = 0;
  semb::test_seam::gate_high_water = 0;
  semb::test_seam::gate_waiters = 0;
  semb::test_seam::gate_take_records.clear();
  semb::test_seam::gate_give_records.clear();
  ++semb::test_seam::gate_release_generation;
  return 1;
}

extern "C" void semb_test_seam_arm_spawn_fail(uint32_t k) {
  std::lock_guard<std::mutex> lock(semb::test_seam::spawn_mutex);
  semb::test_seam::spawn_fail_k = k;
  semb::test_seam::spawn_seen = 0;
  semb::test_seam::spawn_current_call = 0;
  semb::test_seam::spawn_fired = false;
  semb::test_seam::spawn_fired_call = 0;
  semb::test_seam::spawn_starts_after = 0;
}

extern "C" int32_t semb_test_seam_spawn_fail_fired(uint32_t* out_starts_after) {
  std::lock_guard<std::mutex> lock(semb::test_seam::spawn_mutex);
  if (out_starts_after) *out_starts_after = semb::test_seam::spawn_starts_after;
  return semb::test_seam::spawn_fired ? 1 : 0;
}
#endif

// TE-166 (U1 slice 4, C34 leg (e)): this TU's own compiled-in adapter
// identity (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.4's label-check
// table: engine_path_id is checked against the linked adapter TU's own
// compiled-in identity below). This is the ONE translation unit in this
// library that names EmbedEntry/RunLayerLoopChunkBatched/etc. (this
// file's own header comment; C39's singleton scan enforces it) -- the
// value below names the interim adapter itself, distinct from any future
// second adapter U3 might add. A plain string literal, located and
// mutated BY NAME in a scratch clone by
// `tests/te163_c34_manifest_honesty_check.py`'s own leg (e), never by a
// linked symbol lookup -- ITS OWN VALUE MUST NOT APPEAR QUOTED ANYWHERE
// ELSE EARLIER IN THIS FILE (that mutation-driver replaces only the
// FIRST quoted occurrence of the literal in the whole file, so an
// earlier quoted copy in a comment would silently absorb the edit and
// leave this constant, the one this bake actually reads, untouched).
constexpr char SEMB_ADAPTER_SELF_ID[] = "interim";

extern "C" const char* semb_adapter_self_id() { return SEMB_ADAPTER_SELF_ID; }
