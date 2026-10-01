// tests/u3_gpu_cells_test.cpp -- U3 red suite: the GPU seam cells (te266 sec
// 4.5 C10 (c)-(e), (i) and sec 4.6 rows 1-7 and 11, P:4148-4221). The test
// author's, independently of the builder (P:4160, P:4221, P:4260).
//
// Built only with SEMB_BUILD_GPU=ON (Windows, D3D12). Links
// `superembedder_testseam` (tests/support/semb_u3_gpu_seam.h and
// semb_u2_memory_seam.h). ONE CELL PER PROCESS (--cell <name>): every dev-box
// step is one ctest running one cell, its log appended line by line to --log,
// so a crash loses at most the cell in flight (tests/u3_devbox_steps.py). The
// C10 (d) cells need their own process by the plan's own rule (P:4156-4159).
//
// Fixtures (all synthetic; the real-artifact legs are tests/u3_gpu_real_check.py):
//   --model/--tokenizer          the U1 pair (cap 64)
//   --model5k/--tokenizer5k      U2-9's minimal-geometry cap-5,000 pair (C(n) > 64)
//   --guard-model                row 5(a)'s guard model (same tokenizer as the U1 pair)
// Expected rows always come from a CPU handle over the same artifacts in the
// same process (the CPU forward is the oracle the agreement check itself uses,
// P:4106; it takes no input from the GPU forward).
//
// RED TODAY: link-red. Every semb_test_seam_gpu_* symbol and SEMB_BUILD_GPU
// itself are builder items (P:4263-4275). Off Windows or with the option OFF,
// the driver reports MISSING PREREQUISITE (exit 77) and this file is not built.
//
// Cells (name: plan line -- what it asserts):
//   row1_lifetime         P:4211 -- bake then query on one GPU handle; close releases
//                         every sequence, then the model map, then the context
//                         (E9, P:3914); context count 0; a second open after close
//                         succeeds and encodes the CPU row.
//   row1_slots_mc8        P:4211, J11 (te267 P:3756) -- a GPU open at max_concurrency 8:
//                         the CPU pool's slot-record count (U2-9 item 9's reader) is 1;
//                         the GPU slot bound is 8; at most 1 GPU slot record exists.
//   row1_slots_unbounded  P:4211, P:4085 -- max_concurrency (uint32_t)-1 opens SEMB_OK, at
//                         most 1 GPU slot record, a document encodes to its CPU row.
//   row1_default_release  P:4211, row 5(e) P:4215, P:4041 -- one read injected
//                         SSLM_PREFILL_HIDDEN_UNAVAILABLE: SEMB_ENGINE_REFUSED, the log
//                         shows the slot's sequence released, the next encode creates a
//                         sequence and returns its CPU row.
//   row1_hold_600         P:4211 -- a 600-position encode leaves its sequence held (no
//                         release logged inside it); a 12-position encode on the same
//                         slot then re-creates (C(n) 1,024 -> 64) and both rows equal CPU.
//   row3_mc4              P:4213 -- four threads encode concurrently on a mc 4 GPU handle;
//                         rows equal serial CPU rows; a fifth concurrent call is refused.
//                         The fifth call is made while all four slots are held, by
//                         construction: worker 1 is parked inside an engine call
//                         (holding the submission lock, see EnginePark below), workers
//                         2-4 then acquire the other three slots and wait on that
//                         lock, and the fifth call runs once the handle's slot-record
//                         count reads the bound. No scheduling luck is involved.
//                         SEMB_CONCURRENCY_EXCEEDED; occupancy max 1; no lock violation.
//   row3_batch16          P:4213 -- a 16-document batch on an 8-slot GPU handle holds at
//                         most one sequence at a time (creates minus releases <= 1).
//   row3a_two_handles     P:4213 (a) -- two GPU handles, four threads each, lengths
//                         alternating across C(n) boundaries, the second opening while the
//                         first encodes: occupancy max 1, 0 lock violations, rows = CPU.
//   row3b_one_handle      P:4213 (b) -- the same on one handle.
//   row4_shapes           P:4214, C10 (c) P:4154 -- 2, 63, 64, 65 and 512 positions on
//                         the cap-5,000 pair: every GPU row equals its CPU row.
//   row5a_guard           P:4215 (a) -- the guard pair: the GPU open succeeds (the 22
//                         witness sequences pass on the GPU), "abcdefg\xC3\xAD" refuses
//                         SEMB_ENGINE_REFUSED with SSLM_SEQUENCE_REJECTED from the prompt
//                         prefill in the log, and the handle then encodes a passing
//                         document to its CPU row. [U] until the dev box runs it.
//   row5a_mechanism       P:4215 (a), mechanism-only -- the prefill injected
//                         SSLM_SEQUENCE_REJECTED: SEMB_ENGINE_REFUSED, handle usable.
//   row5b_prefill         P:4215 (b) -- the prefill injected SSLM_DEVICE_LOST:
//                         SEMB_DEVICE_UNAVAILABLE; the next encode returns it with the call
//                         count unchanged; close SEMB_OK; context count 0.
//   row5b_seqcreate       P:4215 (b) -- the same from a sequence create.
//   row5c_open_lost       P:4215 (c) -- SSLM_DEVICE_LOST during the agreement check
//                         refuses the open SEMB_DEVICE_UNAVAILABLE; context count 0.
//   row5c_open_rejected   P:4215 (c) -- SSLM_SEQUENCE_REJECTED there refuses it
//                         SEMB_DEVICE_DIVERGED; context count 0.
//   row5d_seam            P:4215 (d), mechanism-only -- a sequence create injected
//                         SSLM_GPU_ALLOCATION_FAILED: SEMB_ALLOCATION_FAILED, then a
//                         shorter document on the same handle encodes to its CPU row.
//   row5f_batch_guard     P:4215 (f) -- a batch of 8 whose 5th is the guard document,
//                         into sentinel rows: SEMB_ENGINE_REFUSED, rows and
//                         *out_required_bytes untouched, the handle usable after; a CPU
//                         handle over the same batch gives the same status and rows.
//   row5f_batch_lost      P:4215 (f) -- the 5th prefill injected SSLM_DEVICE_LOST:
//                         SEMB_DEVICE_UNAVAILABLE, rows untouched, the handle poisoned.
//   c10e1                 P:4161 -- one code of W-B document 3 perturbed before the
//                         agreement check: the open refuses SEMB_DEVICE_DIVERGED and the
//                         internal channel names sequence 3; unarmed, the open succeeds.
//   c10e4_scale           P:4165 -- the mantissa of W-B document 7, codes untouched.
//   c10e4_last_wq         P:4166 -- one code of the last W-Q sequence (21, the truncation query).
//   c10e4_wb15            P:4167 -- one code of W-B document 15.
//   c10e2                 P:4162 -- the perturbation after the check: GPU rows written
//                         to <scratch>/c10e2-gpu.tsv differ from <scratch>/c10e2-cpu.tsv
//                         (the driver then requires the pairwise instrument to refuse).
//   c10i_before_device    P:4173 -- an over-cap document refuses SEMB_CONTEXT_CAP_EXCEEDED
//                         and empty text SEMB_INPUT_EMPTY, each with the engine call count
//                         unchanged; a short document next equals its CPU row.
//   row7_fingerprint      P:4217 -- semb_fingerprint_of is equal on a CPU and a GPU handle;
//                         a C17-style leg bakes the same documents on each: every manifest
//                         fingerprint field equal, `device` "cpu" against "gpu", and the
//                         CPU manifest carries no gpu_* label (P:4125).
//   row11_gpu_triples     P:4107, P:4221 -- a GPU open calls semb_interim_ps_n_select once
//                         per W-B document: the counter's delta is 16.
//   c10d_index            P:4156 -- SSLM_GPU_ADAPTER_INDEX = --index (or unset: "default"):
//                         the bake's manifest carries gpu_adapter_index equal to it,
//                         gpu_vendor_id/gpu_device_id equal an independent DXGI read by the
//                         engine's rule (E16), gpu_driver_version a value or "unknown" (the
//                         leg records which), and the rows equal the CPU rows.
//   c10d_refused_then_corrected  P:4157 -- --value (an out-of-range index, or "abc") set
//                         before the process's first GPU open: SEMB_DEVICE_UNAVAILABLE, the log
//                         shows sslm_gpu_context_create -> SSLM_DEVICE_LOST, context count 0;
//                         unset, a second open succeeds with CPU rows.
//   c10d_after_success    P:4158 -- unset open succeeds and bakes; the out-of-range index
//                         then refuses a second open; unset, a third open succeeds.
//   c10d_refused_after_creation  P:4159 -- --remove-shader <one .cso the engine loads>,
//                         by default the staged <exe dir>/shaders/down_proj_gemm_site.cso
//                         (te266 P:1496, T-2842 F1's measured construction; SETUP fails
//                         if it is absent), renamed away and restored: the open refuses
//                         SEMB_DEVICE_UNAVAILABLE during its agreement check, the log shows
//                         context create and model map SSLM_OK before the refusing call,
//                         and the context count is 0; the file restored, a second open
//                         succeeds with CPU rows. (Also row 5(d)'s ".cso removed"
//                         must-reject, P:4215.)
//   c10d_debug_layer      P:4146 -- SSLM_GPU_ENABLE_DEBUG_LAYER=1 before the first open:
//                         the rows equal the CPU rows.
//   c10d_b5_srv, c10d_b5_uav  P:4143-4144 -- each B5 variable set alone: rows equal CPU
//                         rows. SMOKE: passes on any shipping build (P:4143).
//   c10a_anchors          P:4151 -- REAL ARTIFACT: each document of --texts on a GPU handle;
//                         the read triple's one-position serialisation digested as the
//                         C12b anchors' psn_selected column, written for the driver.
//   c10g                  P:4168-4170, P:4096 -- REAL ARTIFACT: --positions N; CPU parity,
//                         or with --runs 2 (the cap row) two GPU runs byte-equal; the
//                         release above 4,096 read in the log; wall time reported.
//   c11_device            P:4193-4195 -- REAL ARTIFACT, measurement: GPU open time, local
//                         video memory after the open and at the peak of a --positions
//                         encode, and the longest witness forward the open runs.
//
// USAGE: u3_gpu_cells_test --cell <name> --model <m> --tokenizer <t> --scratch <dir>
//        [--model5k <m> --tokenizer5k <t>] [--guard-model <m>] [--index <n|default>]
//        [--value <v>] [--remove-shader <path>] [--texts <file>] [--positions <n>] [--runs 2]
//        [--log <file>]
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#endif

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "superembedder/bake_abi.h"
#include "superembedder/seam_abi.h"
#include "superslm/sha256.h"
#include "support/semb_u2_memory_seam.h"
#include "support/semb_u3_gpu_seam.h"
#include "support/u3_common.h"

// ---- EnginePark: row3_mc4's hold (test-only; replaces global operator new) ----
// A thread that arms it parks at its first allocation made INSIDE an engine
// call (semb_test_seam_gpu_occupancy_now() > 0; an engine call runs only under
// the process-wide submission lock, so the parked thread holds that lock and
// its slot) and waits there until released. Unarmed threads pay one
// thread_local read. The park loop sleeps without allocating.
namespace u3park {
std::atomic<int> parked{0};
std::atomic<int> released{0};
thread_local bool t_armed = false;
inline void Maybe() {
  if (!t_armed) return;
  if (semb_test_seam_gpu_occupancy_now() == 0) return;
  t_armed = false;
  parked.store(1);
  while (!released.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
}
}  // namespace u3park
void* operator new(std::size_t n) {
  u3park::Maybe();
  void* p = std::malloc(n ? n : 1);
  if (!p) throw std::bad_alloc();
  return p;
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }

namespace fs = std::filesystem;

namespace {

struct Args {
  std::string cell, model, tokenizer, model5k, tokenizer5k, guard_model, scratch, index, value, remove_shader, log;
  std::string texts, positions, runs;
};
Args g;

// ---- statuses by name --------------------------------------------------------
int32_t kUnsupported = -1, kUnavailable = -1, kDiverged = -1;
bool ResolveDeviceStatuses() {
  bool ok = u3::Resolve(g.cell, "SEMB_DEVICE_UNSUPPORTED", &kUnsupported);
  ok = u3::Resolve(g.cell, "SEMB_DEVICE_UNAVAILABLE", &kUnavailable) && ok;
  ok = u3::Resolve(g.cell, "SEMB_DEVICE_DIVERGED", &kDiverged) && ok;
  return ok;
}

// ---- environment -------------------------------------------------------------
void SetEnv(const char* name, const char* value) {
#if defined(_WIN32)
  _putenv_s(name, value ? value : "");
#else
  if (value) setenv(name, value, 1); else unsetenv(name);
#endif
}

// ---- handles -----------------------------------------------------------------
semb_status OpenOn(const std::string& m, const std::string& t, uint32_t mc, uint32_t device, semb_encoder* out) {
  *out = nullptr;
  return u3::Open(u3::MakeConfig(m, t, mc, device), out);
}
semb_encoder MustOpen(const std::string& m, const std::string& t, uint32_t mc, uint32_t device,
                      const std::string& what) {
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(m, t, mc, device, &e);
  if (s != SEMB_OK) u3::Verdict(false, g.cell + " setup: " + what + " opens", u3::Name(s));
  return s == SEMB_OK ? e : nullptr;
}

// Text of `positions` positions on a byte-level synthetic pair: positions - 1
// content ids ('a' merges with nothing) plus the appended end token.
std::string Text(size_t positions, char ch = 'a') { return std::string(positions - 1, ch); }

std::map<std::string, std::vector<float>> g_cpu_rows;
const std::vector<float>& CpuRow(const std::string& m, const std::string& t, const std::string& text) {
  const std::string key = m + "\n" + text;
  auto it = g_cpu_rows.find(key);
  if (it != g_cpu_rows.end()) return it->second;
  std::vector<float> row;
  semb_encoder e = nullptr;
  if (OpenOn(m, t, 1, u3::kDeviceCpu, &e) == SEMB_OK) {
    u3::EncodeRow(e, text, &row);
    semb_encoder_close(e);
  }
  return g_cpu_rows[key] = row;
}

// ---- the call log --------------------------------------------------------------
std::vector<semb_test_seam_gpu_call> Log() {
  const uint64_t n = semb_test_seam_gpu_call_log(nullptr, 0, 0);
  std::vector<semb_test_seam_gpu_call> v(n);
  if (n) semb_test_seam_gpu_call_log(v.data(), 0, n);
  return v;
}
bool Is(const semb_test_seam_gpu_call& c, const char* verb) { return std::strcmp(c.verb, verb) == 0; }
bool Ok(const semb_test_seam_gpu_call& c) { return std::strcmp(c.status, "SSLM_OK") == 0; }
std::string Describe(const std::vector<semb_test_seam_gpu_call>& v, size_t from = 0) {
  std::string s;
  for (size_t i = from; i < v.size() && i < from + 12; ++i) s += std::string(i > from ? " " : "") + v[i].verb + "=" + v[i].status;
  return s.empty() ? "(empty log)" : s;
}
void ResetLog() {
  semb_test_seam_gpu_call_log_reset();
  semb_test_seam_gpu_occupancy_reset();
  semb_test_seam_gpu_inject_clear();
}

// ---- documents and banks -------------------------------------------------------
struct Docs {
  std::vector<std::string> ids, texts;
  std::vector<semb_document> docs;
  explicit Docs(const std::vector<std::string>& t) : texts(t) {
    ids.resize(t.size());
    docs.resize(t.size());
    for (size_t i = 0; i < t.size(); ++i) {
      ids[i] = "d" + std::to_string(i);
      docs[i].struct_size = sizeof(semb_document);
      docs[i].id = ids[i].data();
      docs[i].id_len = ids[i].size();
      docs[i].utf8 = texts[i].data();
      docs[i].utf8_len = texts[i].size();
    }
  }
};
const std::vector<std::string> kShortDocs = {"alpha beta", "gamma delta epsilon", "zeta"};

std::string ReadText(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}
// The value of a string member `"key": "value"` in a manifest (flat read; the
// manifest writes labels as strings).
std::string ManifestString(const std::string& text, const std::string& key) {
  const std::string pat = "\"" + key + "\"";
  size_t p = text.find(pat);
  if (p == std::string::npos) return "(absent)";
  p = text.find(':', p + pat.size());
  if (p == std::string::npos) return "(absent)";
  p = text.find_first_not_of(" \t\r\n", p + 1);
  if (p == std::string::npos) return "(absent)";
  if (text[p] != '"') {
    const size_t e = text.find_first_of(",}\r\n", p);
    return text.substr(p, e - p);
  }
  const size_t e = text.find('"', p + 1);
  return text.substr(p + 1, e - p - 1);
}
bool Bake(semb_encoder e, const std::vector<std::string>& texts, const std::string& stem, std::string* manifest) {
  Docs d(texts);
  const semb_status s = semb_bake_to_path(e, d.docs.data(), d.docs.size(), stem.data(), stem.size());
  if (s != SEMB_OK) {
    *manifest = std::string("bake ") + u3::Name(s);
    return false;
  }
  *manifest = ReadText(stem + ".semb.json");
  return true;
}

// Every row of `texts` on `e` equals the CPU row for model/tokenizer.
bool RowsEqualCpu(semb_encoder e, const std::string& m, const std::string& t, const std::vector<std::string>& texts,
                  std::string* why) {
  for (const std::string& x : texts) {
    std::vector<float> row;
    const semb_status s = u3::EncodeRow(e, x, &row);
    if (s != SEMB_OK || !u3::SameBytes(row, CpuRow(m, t, x))) {
      *why = "text of " + u3::S(x.size()) + " bytes: " + u3::Name(s) + (s == SEMB_OK ? " row differs from CPU" : "");
      return false;
    }
  }
  *why = u3::S(texts.size()) + " rows byte-equal to CPU";
  return true;
}

#if defined(_WIN32)
// ---- the independent DXGI read (E16, P:3921) ------------------------------------
struct AdapterIds {
  bool ok = false;
  uint32_t vendor = 0, device = 0;
  std::string error;
};
AdapterIds ReadAdapter(const std::string& index) {
  AdapterIds r;
  IDXGIFactory6* f6 = nullptr;
  IDXGIFactory1* f1 = nullptr;
  if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&f1)))) {
    r.error = "CreateDXGIFactory1 failed";
    return r;
  }
  IDXGIAdapter1* a = nullptr;
  if (index != "default") {
    if (FAILED(f1->EnumAdapters1(static_cast<UINT>(std::strtoul(index.c_str(), nullptr, 10)), &a))) {
      r.error = "EnumAdapters1(" + index + ") failed";
    }
  } else if (SUCCEEDED(f1->QueryInterface(__uuidof(IDXGIFactory6), reinterpret_cast<void**>(&f6)))) {
    for (UINT i = 0;; ++i) {
      IDXGIAdapter1* c = nullptr;
      if (FAILED(f6->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, __uuidof(IDXGIAdapter1),
                                                reinterpret_cast<void**>(&c))))
        break;
      DXGI_ADAPTER_DESC1 d{};
      c->GetDesc1(&d);
      if (!(d.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) &&
          SUCCEEDED(D3D12CreateDevice(c, D3D_FEATURE_LEVEL_12_0, __uuidof(ID3D12Device), nullptr))) {
        a = c;
        break;
      }
      c->Release();
    }
    f6->Release();
    if (!a) r.error = "no hardware adapter by the engine's default rule";
  } else {
    r.error = "IDXGIFactory6 unavailable";
  }
  if (a) {
    DXGI_ADAPTER_DESC1 d{};
    a->GetDesc1(&d);
    r.ok = true;
    r.vendor = d.VendorId;
    r.device = d.DeviceId;
    a->Release();
  }
  f1->Release();
  return r;
}
#endif

bool HexOrDecimalEquals(const std::string& label, uint32_t want) {
  if (label.empty() || label == "(absent)" || label == "unknown") return false;
  char* end = nullptr;
  const unsigned long v = std::strtoul(label.c_str(), &end, 0);
  if (end && *end == '\0' && v == want) return true;
  const unsigned long h = std::strtoul(label.c_str(), &end, 16);
  return end && *end == '\0' && h == want;
}

// ---- cells ---------------------------------------------------------------------
void CellRow1Lifetime() {
  ResetLog();
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  const std::string stem = (fs::path(g.scratch) / "row1_bank").string();
  std::string manifest;
  const bool baked = Bake(e, kShortDocs, stem, &manifest);
  semb_bank bank = nullptr;
  semb_query q = nullptr;
  semb_status bs = semb_bank_open(stem.data(), stem.size(), &bank);
  semb_status qs = bank ? semb_query_open(e, bank, &q) : SEMB_NULL_ARGUMENT;
  std::vector<float> qv(1024);
  size_t req = 0;
  semb_status es = q ? semb_query_encode(q, "alpha", 5, qv.data(), qv.size() * 4, &req) : SEMB_NULL_ARGUMENT;
  if (q) semb_query_close(q);
  if (bank) semb_bank_close(bank);
  const uint64_t before_close = semb_test_seam_gpu_call_count();
  const semb_status cs = semb_encoder_close(e);
  const std::vector<semb_test_seam_gpu_call> v = Log();
  // Order after close: every sequence release, then the unmap, then the destroy, all SSLM_OK.
  int stage = 0;
  bool order = true;
  for (const auto& c : v) {
    if (c.index <= before_close) continue;
    const int s = Is(c, "sslm_gpu_seq_release") ? 0 : Is(c, "sslm_gpu_model_unmap") ? 1 : Is(c, "sslm_gpu_context_destroy") ? 2 : -1;
    if (s < 0) continue;
    if (s < stage || !Ok(c)) order = false;
    stage = s;
  }
  u3::Verdict(baked && bs == SEMB_OK && qs == SEMB_OK && es == SEMB_OK, "row1_lifetime one GPU handle bakes then queries",
              std::string("bake ") + (baked ? "OK" : manifest) + ", bank " + u3::Name(bs) + ", query open " +
                  u3::Name(qs) + ", query encode " + u3::Name(es));
  u3::Verdict(cs == SEMB_OK && order && stage == 2 && semb_test_seam_gpu_context_count() == 0,
              "row1_lifetime close releases sequences, then the map, then the context (E9)",
              std::string(u3::Name(cs)) + ", log after close: " + Describe(v, static_cast<size_t>(before_close)) +
                  ", context count " + std::to_string(semb_test_seam_gpu_context_count()));
  semb_encoder e2 = nullptr;
  const semb_status s2 = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &e2);
  std::string why = u3::Name(s2);
  const bool rows = s2 == SEMB_OK && RowsEqualCpu(e2, g.model, g.tokenizer, {"reopened"}, &why);
  u3::Verdict(rows, "row1_lifetime a second open in the process after close succeeds", why);
  if (e2) semb_encoder_close(e2);
}

void CellRow1SlotsMc8() {
  semb_encoder e = MustOpen(g.model, g.tokenizer, 8, u3::kDeviceGpu, "a GPU handle at max_concurrency 8");
  if (!e) return;
  const uint64_t cpu_records = semb_test_seam_slot_record_count(semb_test_seam_interim_of(e));
  const uint64_t gpu_records = semb_test_seam_gpu_slot_record_count(e);
  const uint64_t bound = semb_test_seam_gpu_slot_bound(e);
  u3::Verdict(cpu_records == 1, "row1_slots_mc8 the GPU handle's CPU pool holds 1 slot record after open (J11, U2-9 item 9's reader)",
              "records " + u3::S(cpu_records));
  u3::Verdict(bound == 8 && gpu_records <= 1, "row1_slots_mc8 GPU slot bound 8, at most 1 GPU slot record after open",
              "bound " + u3::S(bound) + ", records " + u3::S(gpu_records));
  semb_encoder_close(e);
}

void CellRow1SlotsUnbounded() {
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(g.model, g.tokenizer, 0xFFFFFFFFu, u3::kDeviceGpu, &e);
  if (s != SEMB_OK) {
    u3::Verdict(false, "row1_slots_unbounded max_concurrency (uint32_t)-1 opens SEMB_OK", u3::Name(s));
    return;
  }
  const uint64_t records = semb_test_seam_gpu_slot_record_count(e);
  std::string why;
  const bool rows = RowsEqualCpu(e, g.model, g.tokenizer, {"one document"}, &why);
  u3::Verdict(records <= 1 && rows, "row1_slots_unbounded opens, at most 1 GPU slot record, CPU row",
              "records " + u3::S(records) + "; " + why);
  semb_encoder_close(e);
}

void CellRow1DefaultRelease() {
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  std::vector<float> warm;
  u3::EncodeRow(e, "warm", &warm);  // the slot now holds a sequence
  ResetLog();
  semb_test_seam_gpu_inject("sslm_gpu_seq_read_prefill_final_hidden", 1, "SSLM_PREFILL_HIDDEN_UNAVAILABLE");
  std::vector<float> row;
  const semb_status s = u3::EncodeRow(e, "refused by the read", &row);
  const std::vector<semb_test_seam_gpu_call> v = Log();
  bool injected = false, released = false;
  for (const auto& c : v) {
    if (Is(c, "sslm_gpu_seq_read_prefill_final_hidden") && c.injected &&
        std::strcmp(c.status, "SSLM_PREFILL_HIDDEN_UNAVAILABLE") == 0)
      injected = true;
    if (injected && Is(c, "sslm_gpu_seq_release") && Ok(c)) released = true;
  }
  u3::Verdict(s == SEMB_ENGINE_REFUSED && injected && released,
              "row1_default_release a default-row status refuses SEMB_ENGINE_REFUSED and releases the slot's sequence (P:4041)",
              std::string(u3::Name(s)) + "; " + Describe(v));
  const uint64_t n0 = semb_test_seam_gpu_call_count();
  std::string why;
  const bool rows = RowsEqualCpu(e, g.model, g.tokenizer, {"after the default row"}, &why);
  const std::vector<semb_test_seam_gpu_call> v2 = Log();
  bool created = false;
  for (const auto& c : v2)
    if (c.index > n0 && Is(c, "sslm_gpu_seq_create") && Ok(c)) created = true;
  u3::Verdict(rows && created, "row1_default_release the next encode creates a sequence and returns its CPU row (row 5(e))",
              why + (created ? ", sequence created" : ", NO sequence create logged"));
  semb_encoder_close(e);
}

void CellRow1Hold600() {
  if (g.model5k.empty()) { u3::Missing(g.cell, "--model5k/--tokenizer5k (the cap-5,000 pair)"); return; }
  semb_encoder e = MustOpen(g.model5k, g.tokenizer5k, 1, u3::kDeviceGpu, "a GPU handle on the cap-5,000 pair");
  if (!e) return;
  ResetLog();
  std::string why;
  const bool r600 = RowsEqualCpu(e, g.model5k, g.tokenizer5k, {Text(600)}, &why);
  const std::vector<semb_test_seam_gpu_call> v = Log();
  bool create1024 = false, released = false;
  for (const auto& c : v) {
    if (Is(c, "sslm_gpu_seq_create") && c.arg == 1024) create1024 = true;
    if (Is(c, "sslm_gpu_seq_release")) released = true;
  }
  u3::Verdict(r600 && create1024 && !released, "row1_hold_600 a 600-position encode creates C(n)=1,024 and keeps it held",
              why + "; " + Describe(v));
  const uint64_t n0 = semb_test_seam_gpu_call_count();
  std::string why12;
  const bool r12 = RowsEqualCpu(e, g.model5k, g.tokenizer5k, {Text(12)}, &why12);
  const std::vector<semb_test_seam_gpu_call> v2 = Log();
  bool rel = false, create64 = false;
  for (const auto& c : v2) {
    if (c.index <= n0) continue;
    if (Is(c, "sslm_gpu_seq_release")) rel = true;
    if (rel && Is(c, "sslm_gpu_seq_create") && c.arg == 64) create64 = true;
  }
  u3::Verdict(r12 && rel && create64, "row1_hold_600 a 12-position encode on the same slot re-creates at 64 (C10 (c))",
              why12 + "; " + Describe(v2, static_cast<size_t>(n0)));
  semb_encoder_close(e);
}

void Threads(semb_encoder e, const std::string& m, const std::string& t, const std::vector<std::string>& texts,
             int n_threads, int rounds, std::atomic<int>* bad) {
  std::vector<std::thread> ts;
  for (int k = 0; k < n_threads; ++k) {
    ts.emplace_back([&, k] {
      for (int r = 0; r < rounds; ++r) {
        const std::string& x = texts[(k + r) % texts.size()];
        std::vector<float> row;
        const semb_status s = u3::EncodeRow(e, x, &row);
        if (s == SEMB_CONCURRENCY_EXCEEDED) continue;  // an extra caller, not a wrong row
        if (s != SEMB_OK || !u3::SameBytes(row, g_cpu_rows[m + "\n" + x])) bad->fetch_add(1);
      }
    });
  }
  for (auto& th : ts) th.join();
}

void CellRow3Mc4() {
  const std::vector<std::string> texts = {Text(40), Text(12), Text(60), Text(5)};
  for (const auto& x : texts) CpuRow(g.model, g.tokenizer, x);
  semb_encoder e = MustOpen(g.model, g.tokenizer, 4, u3::kDeviceGpu, "a GPU handle at max_concurrency 4");
  if (!e) return;
  ResetLog();
  // (1) Four encoders, concurrently, many rounds: every row is the serial CPU
  // row. Four callers at a bound of 4 are never refused, so a refusal is bad.
  std::atomic<int> bad{0};
  {
    std::vector<std::thread> ts;
    for (int k = 0; k < 4; ++k) {
      ts.emplace_back([&, k] {
        for (int r = 0; r < 40; ++r) {
          const std::string& x = texts[(k + r) % texts.size()];
          std::vector<float> row;
          if (u3::EncodeRow(e, x, &row) != SEMB_OK || !u3::SameBytes(row, g_cpu_rows.at(g.model + "\n" + x))) {
            bad.fetch_add(1);
          }
        }
      });
    }
    for (auto& th : ts) th.join();
  }
  u3::Verdict(bad == 0, "row3_mc4 four concurrent encoders give their serial CPU rows",
              "bad rows " + std::to_string(bad) + " of 160 (a refusal at 4 callers counts as bad)");

  // (2) The fifth call, with all four slots held by construction.
  semb_encoder f = MustOpen(g.model, g.tokenizer, 4, u3::kDeviceGpu, "a fresh GPU handle at max_concurrency 4");
  if (!f) {
    semb_encoder_close(e);
    return;
  }
  const uint64_t bound = semb_test_seam_gpu_slot_bound(f);
  u3park::parked = 0;
  u3park::released = 0;
  std::vector<semb_status> st(4, SEMB_OK);
  std::vector<std::vector<float>> rows(4);
  std::vector<std::thread> ws;
  ws.emplace_back([&] {
    u3park::t_armed = true;
    st[0] = u3::EncodeRow(f, texts[0], &rows[0]);
    u3park::t_armed = false;
  });
  auto wait_for = [](const std::function<bool()>& cond, int seconds) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
    while (!cond()) {
      if (std::chrono::steady_clock::now() > deadline) return false;
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    return true;
  };
  const bool w1 = wait_for([] { return u3park::parked.load() == 1; }, 120);
  bool held = false;
  semb_status fifth = SEMB_OK;
  std::string why;
  if (!w1) {
    why = "apparatus: worker 1 made no allocation inside an engine call within 120 s, so no slot could be held "
          "(the hold needs one; nothing was proven)";
  } else {
    for (int k = 1; k < 4; ++k) ws.emplace_back([&, k] { st[k] = u3::EncodeRow(f, texts[k], &rows[k]); });
    held = wait_for([&] { return semb_test_seam_gpu_slot_record_count(f) == 4; }, 120);
    if (!held) {
      why = "apparatus: the handle's slot records reached " + u3::S(semb_test_seam_gpu_slot_record_count(f)) +
            " of 4 while worker 1 held the lock";
    } else {
      // Every record is busy: none can be freed without the lock worker 1 holds.
      std::vector<float> row;
      std::atomic<int> done{0};
      std::thread t5([&] {
        fifth = u3::EncodeRow(f, texts[0], &row);
        done = 1;
      });
      const bool returned = wait_for([&] { return done.load() == 1; }, 60);
      if (!returned) {
        u3park::released = 1;  // unblock so the thread can be joined; the verdict is already a failure
        why = "the fifth call BLOCKED while all four slots were held (a refusal must not wait)";
      }
      t5.join();
      if (returned) {
        why = std::string("slot records ") + u3::S(semb_test_seam_gpu_slot_record_count(f)) + " (bound " +
              u3::S(bound) + ") all held; the fifth call returned " + u3::Name(fifth);
      }
    }
  }
  u3park::released = 1;
  for (auto& th : ws) th.join();
  u3::Verdict(w1 && held && fifth == SEMB_CONCURRENCY_EXCEEDED && bound == 4,
              "row3_mc4 a fifth concurrent call is refused SEMB_CONCURRENCY_EXCEEDED", why);
  int held_bad = 0;
  for (size_t k = 0; k < (w1 ? 4u : 1u); ++k) {
    if (st[k] != SEMB_OK || !u3::SameBytes(rows[k], g_cpu_rows.at(g.model + "\n" + texts[k]))) ++held_bad;
  }
  u3::Verdict(held_bad == 0, "row3_mc4 the four holders then complete with their serial CPU rows",
              std::to_string(held_bad) + " bad of " + std::to_string(w1 ? 4 : 1));
  u3::Verdict(semb_test_seam_gpu_occupancy_max() <= 1 && semb_test_seam_gpu_lock_violations() == 0,
              "row3_mc4 every engine call serialized under the lock",
              "occupancy max " + std::to_string(semb_test_seam_gpu_occupancy_max()) + ", lock violations " +
                  u3::S(semb_test_seam_gpu_lock_violations()));
  semb_encoder_close(f);
  semb_encoder_close(e);
}

void CellRow3Batch16() {
  std::vector<std::string> texts;
  for (int i = 0; i < 16; ++i) texts.push_back(Text(5 + 3 * i));
  semb_encoder e = MustOpen(g.model, g.tokenizer, 8, u3::kDeviceGpu, "a GPU handle at max_concurrency 8");
  semb_encoder c = MustOpen(g.model, g.tokenizer, 8, u3::kDeviceCpu, "a CPU handle");
  if (!e || !c) return;
  Docs d(texts);
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  std::vector<float> gr(16 * dims), cr(16 * dims);
  size_t req = 0;
  ResetLog();
  const semb_status gs = semb_encode_batch(e, d.docs.data(), 16, gr.data(), gr.size() * 4, &req);
  const semb_status cs = semb_encode_batch(c, d.docs.data(), 16, cr.data(), cr.size() * 4, &req);
  int64_t live = 0, peak = 0;
  for (const auto& call : Log()) {
    if (Is(call, "sslm_gpu_seq_create") && Ok(call)) peak = std::max(peak, ++live);
    if (Is(call, "sslm_gpu_seq_release") && Ok(call)) --live;
  }
  u3::Verdict(gs == SEMB_OK && cs == SEMB_OK && gr == cr && peak <= 1,
              "row3_batch16 a GPU batch runs on one worker (sequences held at once <= 1) with CPU rows",
              std::string("gpu ") + u3::Name(gs) + ", cpu " + u3::Name(cs) + ", rows " + (gr == cr ? "equal" : "DIFFER") +
                  ", peak sequences " + std::to_string(peak));
  semb_encoder_close(e);
  semb_encoder_close(c);
}

void TwoOrOneHandle(bool two) {
  if (g.model5k.empty()) { u3::Missing(g.cell, "--model5k/--tokenizer5k (the cap-5,000 pair)"); return; }
  const std::vector<std::string> texts = {Text(63), Text(65), Text(600), Text(12)};
  for (const auto& x : texts) CpuRow(g.model5k, g.tokenizer5k, x);
  semb_encoder a = MustOpen(g.model5k, g.tokenizer5k, 4, u3::kDeviceGpu, "GPU handle A");
  if (!a) return;
  ResetLog();
  std::atomic<int> bad{0};
  std::thread ta([&] { Threads(a, g.model5k, g.tokenizer5k, texts, 4, 12, &bad); });
  semb_encoder b = nullptr;
  std::thread tb;
  if (two) {
    std::this_thread::sleep_for(std::chrono::milliseconds(200));  // A's threads are encoding
    const semb_status s = OpenOn(g.model5k, g.tokenizer5k, 4, u3::kDeviceGpu, &b);
    if (s != SEMB_OK) u3::Verdict(false, g.cell + " handle B opens while A encodes", u3::Name(s));
    if (b) tb = std::thread([&] { Threads(b, g.model5k, g.tokenizer5k, texts, 4, 12, &bad); });
  }
  ta.join();
  if (tb.joinable()) tb.join();
  const uint32_t occ = semb_test_seam_gpu_occupancy_max();
  const uint64_t viol = semb_test_seam_gpu_lock_violations();
  u3::Verdict(occ == 1 && viol == 0 && bad == 0,
              std::string(two ? "row3a_two_handles" : "row3b_one_handle") +
                  " occupancy max 1, every call under the lock, rows equal serial",
              "occupancy " + std::to_string(occ) + ", violations " + u3::S(viol) + ", bad rows " + std::to_string(bad));
  if (b) semb_encoder_close(b);
  semb_encoder_close(a);
}

void CellRow4Shapes() {
  if (g.model5k.empty()) { u3::Missing(g.cell, "--model5k/--tokenizer5k (the cap-5,000 pair)"); return; }
  semb_encoder e = MustOpen(g.model5k, g.tokenizer5k, 1, u3::kDeviceGpu, "a GPU handle on the cap-5,000 pair");
  if (!e) return;
  for (const size_t n : {size_t{2}, size_t{63}, size_t{64}, size_t{65}, size_t{512}}) {
    std::string why;
    const bool ok = RowsEqualCpu(e, g.model5k, g.tokenizer5k, {Text(n)}, &why);
    u3::Verdict(ok, "row4_shapes " + std::to_string(n) + " positions: GPU row = CPU row (C10 (c))", why);
  }
  semb_encoder_close(e);
}

const std::string kGuardDoc = "abcdefg\xC3\xAD";  // ids 97..103, 195, 173 (P:4215)

void CellRow5aGuard() {
  if (g.guard_model.empty()) { u3::Missing(g.cell, "--guard-model (tests/fixtures/regenerate_u3_guard_pair_fixture.py)"); return; }
  semb_encoder e = MustOpen(g.guard_model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle over the guard pair");
  if (!e) return;
  ResetLog();
  std::vector<float> row;
  const semb_status s = u3::EncodeRow(e, kGuardDoc, &row);
  bool rejected = false;
  for (const auto& c : Log())
    if (Is(c, "SslmGpuSeqPrefillPromptForG5Bridge") && !c.injected && std::strcmp(c.status, "SSLM_SEQUENCE_REJECTED") == 0)
      rejected = true;
  u3::Verdict(s == SEMB_ENGINE_REFUSED && rejected,
              "row5a_guard the GPU refuses the guard document SEMB_ENGINE_REFUSED, the prefill returning SSLM_SEQUENCE_REJECTED",
              std::string(u3::Name(s)) + "; " + Describe(Log()));
  std::string why;
  u3::Verdict(RowsEqualCpu(e, g.guard_model, g.tokenizer, {"abcdefg"}, &why),
              "row5a_guard the refused slot is reset and the handle encodes a passing document to its CPU row", why);
  semb_encoder_close(e);
}

void InjectedEncode(const char* verb, uint64_t nth, const char* status, int32_t want, bool poisons, const std::string& cell,
                    const std::string& m, const std::string& t, const std::string& text, const std::string& follow_text) {
  semb_encoder e = MustOpen(m, t, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  std::vector<float> warm;
  u3::EncodeRow(e, "warm", &warm);
  ResetLog();
  semb_test_seam_gpu_inject(verb, nth, status);
  std::vector<float> row;
  const semb_status s = u3::EncodeRow(e, text, &row);
  u3::Verdict(s == want, cell + " the injected " + status + " maps to " + u3::Name(want), u3::Name(s));
  const uint64_t n0 = semb_test_seam_gpu_call_count();
  std::vector<float> next;
  const semb_status s2 = u3::EncodeRow(e, follow_text, &next);
  const uint64_t n1 = semb_test_seam_gpu_call_count();
  if (poisons) {
    u3::Verdict(s2 == kUnavailable && n1 == n0, cell + " the handle is poisoned: the next encode refuses without an engine call",
                std::string(u3::Name(s2)) + ", calls " + u3::S(n0) + " -> " + u3::S(n1));
    const semb_status cs = semb_encoder_close(e);
    u3::Verdict(cs == SEMB_OK && semb_test_seam_gpu_context_count() == 0, cell + " close releases everything (context count 0)",
                std::string(u3::Name(cs)) + ", count " + std::to_string(semb_test_seam_gpu_context_count()));
    return;
  }
  u3::Verdict(s2 == SEMB_OK && n1 > n0 && u3::SameBytes(next, CpuRow(m, t, follow_text)),
              cell + " the handle stays usable: the next encode calls the engine and returns its CPU row",
              std::string(u3::Name(s2)) + ", calls " + u3::S(n0) + " -> " + u3::S(n1));
  semb_encoder_close(e);
}

void OpenInjected(const char* status, int32_t want, const std::string& cell) {
  ResetLog();
  // The agreement check's first prefill (P:4106): the open's first prefill.
  semb_test_seam_gpu_inject("SslmGpuSeqPrefillPromptForG5Bridge", 1, status);
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &e);
  u3::Verdict(s == want && e == nullptr && semb_test_seam_gpu_context_count() == 0,
              cell + " " + status + " during the agreement check refuses the open " + u3::Name(want) +
                  " and releases every engine handle",
              std::string(u3::Name(s)) + ", context count " + std::to_string(semb_test_seam_gpu_context_count()));
  if (e) semb_encoder_close(e);
}

void CellBatch(bool guard) {
  const std::string m = guard ? g.guard_model : g.model;
  if (m.empty()) { u3::Missing(g.cell, "--guard-model"); return; }
  std::vector<std::string> texts = {"one", "two", "three", "four", "five", "six", "seven", "eight"};
  if (guard) texts[4] = kGuardDoc;
  Docs d(texts);
  semb_encoder e = MustOpen(m, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  std::vector<float> rows(8 * dims);
  std::memset(rows.data(), 0x5A, rows.size() * 4);
  const std::vector<float> sentinel = rows;
  size_t req = 0xDEADBEEF;
  if (!guard) {
    ResetLog();
    semb_test_seam_gpu_inject("SslmGpuSeqPrefillPromptForG5Bridge", 5, "SSLM_DEVICE_LOST");
  }
  const semb_status s = semb_encode_batch(e, d.docs.data(), 8, rows.data(), rows.size() * 4, &req);
  const int32_t want = guard ? SEMB_ENGINE_REFUSED : kUnavailable;
  const bool untouched = std::memcmp(rows.data(), sentinel.data(), rows.size() * 4) == 0 && req == 0xDEADBEEF;
  u3::Verdict(s == want && untouched,
              g.cell + " a batch refused at its 5th document writes nothing (status " + u3::Name(want) + ")",
              std::string(u3::Name(s)) + ", out_rows " + (untouched ? "and *out_required_bytes untouched" : "WRITTEN"));
  std::vector<float> next;
  const semb_status s2 = u3::EncodeRow(e, "after", &next);
  if (guard) {
    u3::Verdict(s2 == SEMB_OK && u3::SameBytes(next, CpuRow(m, g.tokenizer, "after")), g.cell + " the handle is usable after",
                u3::Name(s2));
    semb_encoder c = MustOpen(m, g.tokenizer, 1, u3::kDeviceCpu, "a CPU handle");
    if (c) {
      std::vector<float> crow(8 * dims);
      std::memset(crow.data(), 0x5A, crow.size() * 4);
      size_t creq = 0xDEADBEEF;
      const semb_status cs = semb_encode_batch(c, d.docs.data(), 8, crow.data(), crow.size() * 4, &creq);
      u3::Verdict(cs == s && std::memcmp(crow.data(), sentinel.data(), crow.size() * 4) == 0,
                  g.cell + " a CPU handle over the same batch gives the same status and untouched rows", u3::Name(cs));
      semb_encoder_close(c);
    }
  } else {
    u3::Verdict(s2 == kUnavailable, g.cell + " the handle is poisoned after the device loss", u3::Name(s2));
  }
  semb_encoder_close(e);
}

void CellPerturbOpen(int32_t target, int32_t sequence, const std::string& what) {
  semb_test_seam_gpu_arm_perturb(0, target, sequence, 0);
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &e);
  const int32_t fired = semb_test_seam_gpu_perturb_disarm();
  const int32_t named = semb_test_seam_gpu_last_diverged_sequence();
  u3::Verdict(fired && s == kDiverged && e == nullptr && named == sequence,
              g.cell + " " + what + " refuses the open SEMB_DEVICE_DIVERGED and the channel names sequence " +
                  std::to_string(sequence),
              std::string(u3::Name(s)) + ", fired " + std::to_string(fired) + ", named " + std::to_string(named));
  if (e) semb_encoder_close(e);
  semb_encoder ok = nullptr;
  const semb_status s2 = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &ok);
  u3::Verdict(s2 == SEMB_OK && semb_test_seam_gpu_last_diverged_sequence() == -1,
              g.cell + " must-accept: the same open unperturbed succeeds", u3::Name(s2));
  if (ok) semb_encoder_close(ok);
}

std::string RowSha(const std::vector<float>& row) {
  uint8_t d[32];
  superslm::Sha256Hash(reinterpret_cast<const uint8_t*>(row.data()), row.size() * 4, d);
  static const char* hx = "0123456789abcdef";
  std::string s;
  for (uint8_t b : d) { s += hx[b >> 4]; s += hx[b & 15]; }
  return s;
}

void CellC10e2() {
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  semb_test_seam_gpu_arm_perturb(1, 0, 0, 0);
  std::ofstream gf(fs::path(g.scratch) / "c10e2-gpu.tsv", std::ios::binary), cf(fs::path(g.scratch) / "c10e2-cpu.tsv", std::ios::binary);
  int differ = 0;
  for (size_t i = 0; i < kShortDocs.size(); ++i) {
    std::vector<float> row;
    u3::EncodeRow(e, kShortDocs[i], &row);
    const std::vector<float>& cpu = CpuRow(g.model, g.tokenizer, kShortDocs[i]);
    gf << "d" << i << "\t" << RowSha(row) << "\n";
    cf << "d" << i << "\t" << RowSha(cpu) << "\n";
    differ += u3::SameBytes(row, cpu) ? 0 : 1;
  }
  semb_test_seam_gpu_perturb_disarm();
  u3::Verdict(differ > 0, "c10e2 the perturbation after the check changes the GPU rows (the pairwise instrument must refuse them)",
              std::to_string(differ) + " of " + u3::S(kShortDocs.size()) + " rows differ; files c10e2-gpu.tsv / c10e2-cpu.tsv");
  semb_encoder_close(e);
}

void CellC10iBeforeDevice() {
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  std::vector<float> row(dims);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  const std::string over = Text(65);  // 64 content ids reach the pair's context_cap of 64 (encoder.cpp:411)
  uint64_t n0 = semb_test_seam_gpu_call_count();
  const semb_status s1 = semb_encode(e, over.data(), over.size(), row.data(), row.size() * 4, &req, &fp);
  uint64_t n1 = semb_test_seam_gpu_call_count();
  u3::Verdict(s1 == SEMB_CONTEXT_CAP_EXCEEDED && n1 == n0, "c10i_before_device an over-cap document refuses before any engine call",
              std::string(u3::Name(s1)) + ", calls " + u3::S(n0) + " -> " + u3::S(n1));
  n0 = semb_test_seam_gpu_call_count();
  const semb_status s2 = semb_encode(e, "", 0, row.data(), row.size() * 4, &req, &fp);
  n1 = semb_test_seam_gpu_call_count();
  u3::Verdict(s2 == SEMB_INPUT_EMPTY && n1 == n0, "c10i_before_device empty text refuses before any engine call",
              std::string(u3::Name(s2)) + ", calls " + u3::S(n0) + " -> " + u3::S(n1));
  std::string why;
  u3::Verdict(RowsEqualCpu(e, g.model, g.tokenizer, {"short"}, &why), "c10i_before_device a short document next equals its CPU row", why);
  semb_encoder_close(e);
}

void CellRow7Fingerprint() {
  semb_encoder c = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceCpu, "a CPU handle");
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!c || !e) return;
  semb_fingerprint fc{}, fg{};
  fc.struct_size = fg.struct_size = sizeof(semb_fingerprint);
  const semb_status sc = semb_fingerprint_of(c, &fc), sg = semb_fingerprint_of(e, &fg);
  u3::Verdict(sc == SEMB_OK && sg == SEMB_OK && std::memcmp(fc.digest, fg.digest, 32) == 0,
              "row7_fingerprint one fingerprint across devices", std::string(u3::Name(sc)) + " / " + u3::Name(sg));
  std::string mc, mg;
  const std::string sc_stem = (fs::path(g.scratch) / "row7_cpu").string(), sg_stem = (fs::path(g.scratch) / "row7_gpu").string();
  const bool bc = Bake(c, kShortDocs, sc_stem, &mc), bg = Bake(e, kShortDocs, sg_stem, &mg);
  bool same = bc && bg;
  std::string diff;
  for (const char* k : {"encoder_fingerprint", "model_sha", "tokenizer_sha", "witness_sha", "certification_epoch",
                        "row_digest", "engine_path_id"}) {
    if (ManifestString(mc, k) != ManifestString(mg, k)) { same = false; diff += std::string(k) + " "; }
  }
  const std::string dc = ManifestString(mc, "device"), dg = ManifestString(mg, "device");
  u3::Verdict(same && dc == "cpu" && dg == "gpu",
              "row7_fingerprint C17-style: only the device label changes between a CPU and a GPU bake",
              "device " + dc + " / " + dg + (diff.empty() ? "" : "; differing: " + diff));
  u3::Verdict(bc && mc.find("\"gpu_") == std::string::npos, "row7_fingerprint a CPU bake writes no gpu_* label (P:4125)",
              mc.find("\"gpu_") == std::string::npos ? "none" : "a gpu_* label is present");
  semb_encoder_close(c);
  semb_encoder_close(e);
}

void CellRow11GpuTriples() {
  const uint64_t before = semb_test_seam_ps_n_select_count();
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  const uint64_t after = semb_test_seam_ps_n_select_count();
  u3::Verdict(e && after - before == 16, "row11_gpu_triples a GPU open selects one triple per W-B document (16)",
              "delta " + u3::S(after - before));
  if (e) semb_encoder_close(e);
}

void CellC10dIndex() {
  const std::string idx = g.index.empty() ? "default" : g.index;
  SetEnv("SSLM_GPU_ADAPTER_INDEX", idx == "default" ? nullptr : idx.c_str());
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle");
  if (!e) return;
  std::string man;
  const bool baked = Bake(e, kShortDocs, (fs::path(g.scratch) / ("c10d_index_" + idx)).string(), &man);
  u3::Verdict(baked && ManifestString(man, "gpu_adapter_index") == idx,
              "c10d_index the manifest's gpu_adapter_index is " + idx, ManifestString(man, "gpu_adapter_index"));
#if defined(_WIN32)
  const AdapterIds a = ReadAdapter(idx);
  const std::string v = ManifestString(man, "gpu_vendor_id"), d = ManifestString(man, "gpu_device_id");
  u3::Verdict(a.ok && HexOrDecimalEquals(v, a.vendor) && HexOrDecimalEquals(d, a.device),
              "c10d_index gpu_vendor_id/gpu_device_id equal an independent DXGI read by the engine's rule (E16)",
              "manifest " + v + "/" + d + ", DXGI " + (a.ok ? std::to_string(a.vendor) + "/" + std::to_string(a.device) : a.error));
  const std::string drv = ManifestString(man, "gpu_driver_version");
  u3::Verdict(drv != "(absent)", "c10d_index gpu_driver_version is a value or \"unknown\"", drv);
  u3::Note("c10d_index", std::string("sec 4.3's [U] settles: the driver query ") + (drv == "unknown" ? "fails" : "answers") +
                             " for this D3D12 adapter (" + drv + ")");
#endif
  std::string why;
  u3::Verdict(RowsEqualCpu(e, g.model, g.tokenizer, kShortDocs, &why), "c10d_index rows equal the CPU rows", why);
  semb_encoder_close(e);
}

bool OpenRefusedByIndex(const std::string& value, const std::string& leg) {
  SetEnv("SSLM_GPU_ADAPTER_INDEX", value.c_str());
  ResetLog();
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &e);
  bool lost = false;
  for (const auto& c : Log())
    if (Is(c, "sslm_gpu_context_create") && std::strcmp(c.status, "SSLM_DEVICE_LOST") == 0) lost = true;
  u3::Verdict(s == kUnavailable && e == nullptr && lost && semb_test_seam_gpu_context_count() == 0,
              g.cell + " " + leg + ": SSLM_GPU_ADAPTER_INDEX=" + value + " refuses SEMB_DEVICE_UNAVAILABLE",
              std::string(u3::Name(s)) + ", context_create SSLM_DEVICE_LOST " + (lost ? "logged" : "NOT logged") +
                  ", context count " + std::to_string(semb_test_seam_gpu_context_count()));
  if (e) semb_encoder_close(e);
  SetEnv("SSLM_GPU_ADAPTER_INDEX", nullptr);
  return s == kUnavailable;
}
void OpenSucceedsWithCpuRows(const std::string& leg) {
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &e);
  std::string why = u3::Name(s);
  u3::Verdict(s == SEMB_OK && RowsEqualCpu(e, g.model, g.tokenizer, kShortDocs, &why), g.cell + " " + leg, why);
  if (e) semb_encoder_close(e);
}

void CellC10dRefusedThenCorrected() {
  const std::string v = g.value.empty() ? "99" : g.value;
  for (const auto& x : kShortDocs) CpuRow(g.model, g.tokenizer, x);  // CPU work only before the first GPU open
  OpenRefusedByIndex(v, "the process's first GPU open");
  OpenSucceedsWithCpuRows("unset, a second open in the process succeeds with CPU rows");
}

void CellC10dAfterSuccess() {
  OpenSucceedsWithCpuRows("an unset open succeeds and bakes");
  OpenRefusedByIndex(g.value.empty() ? "99" : g.value, "after a successful open");
  OpenSucceedsWithCpuRows("unset, a third open succeeds with CPU rows");
}

void CellC10dRefusedAfterCreation() {
  if (g.remove_shader.empty()) { u3::Missing(g.cell, "--remove-shader (the driver prepares a scratch copy)"); return; }
  const std::string moved = g.remove_shader + ".removed";
  if (!fs::exists(g.remove_shader) && fs::exists(moved)) fs::rename(moved, g.remove_shader);  // resume after a crash
  if (!fs::exists(g.remove_shader)) {
    // SETUP: the construction needs a shader the engine loads and the prefill dispatches (P:1496).
    u3::Verdict(false, "c10d_refused_after_creation SETUP the shader to hide exists where the engine loads it",
                g.remove_shader + " is absent (the engine reads <executable dir>/shaders; see SEMB_U3_SHADER_TO_REMOVE)");
    return;
  }
  for (const auto& x : kShortDocs) CpuRow(g.model, g.tokenizer, x);
  fs::rename(g.remove_shader, moved);
  ResetLog();
  semb_encoder e = nullptr;
  const semb_status s = OpenOn(g.model, g.tokenizer, 1, u3::kDeviceGpu, &e);
  const std::vector<semb_test_seam_gpu_call> v = Log();
  bool ctx = false, map = false, refused_after = false;
  for (const auto& c : v) {
    if (Is(c, "sslm_gpu_context_create") && Ok(c)) ctx = true;
    if (Is(c, "sslm_gpu_model_map") && Ok(c)) map = true;
    if (ctx && map && !Ok(c) && !Is(c, "sslm_gpu_context_create") && !Is(c, "sslm_gpu_model_map")) refused_after = true;
  }
  const int64_t count = semb_test_seam_gpu_context_count();
  fs::rename(moved, g.remove_shader);
  u3::Verdict(s == kUnavailable && e == nullptr && ctx && map && refused_after && count == 0,
              "c10d_refused_after_creation a missing .cso refuses SEMB_DEVICE_UNAVAILABLE after context and map, count 0",
              std::string(u3::Name(s)) + "; " + Describe(v) + "; context count " + std::to_string(count));
  if (e) semb_encoder_close(e);
  OpenSucceedsWithCpuRows("the file restored, a second open succeeds with CPU rows");
}

// ---- C10 (a)'s anchors and C10 (g): real-artifact cells --------------------
// Both run on the REAL artifact (the driver passes it as --model/--tokenizer;
// tests/u3_gpu_real_check.py), never on a synthetic pair.

std::string Hex(const uint8_t* d, size_t n) {
  static const char* hx = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; ++i) { s += hx[d[i] >> 4]; s += hx[d[i] & 15]; }
  return s;
}
std::string Unhex(const std::string& h) {
  std::string out;
  for (size_t i = 0; i + 1 < h.size(); i += 2) out += static_cast<char>(std::stoi(h.substr(i, 2), nullptr, 16));
  return out;
}

// C10 (a), P:4151: each GPU psn_selected equals the committed anchors. The GPU
// triple the read verb returned for each document (capability "last read",
// what dequantize received) is serialised by semb_seam_serialize_document as
// one position and digested exactly as the C12b anchors' psn_selected_sha256
// column is (src/c12b). Writes "<label>\t<sha>" per document to
// <scratch>/c10a-gpu-psn.tsv; the driver compares it with
// tests/fixtures/c12b/anchors-*.tsv. --texts: "<label>\t<hex of the text>" lines.
void CellC10aAnchors() {
  std::ifstream in(g.texts, std::ios::binary);
  if (!in) { u3::Missing(g.cell, "--texts <label\\thex-text file> is absent"); return; }
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle on the real artifact");
  if (!e) return;
  std::ofstream out(fs::path(g.scratch) / "c10a-gpu-psn.tsv", std::ios::binary);
  std::string line;
  size_t n = 0, refused = 0, unread = 0;
  std::vector<int8_t> codes(1 << 16);
  while (std::getline(in, line)) {
    const size_t tab = line.find('\t');
    if (tab == std::string::npos) continue;
    const std::string label = line.substr(0, tab), text = Unhex(line.substr(tab + 1));
    std::vector<float> row;
    if (u3::EncodeRow(e, text, &row) != SEMB_OK) { ++refused; continue; }
    size_t width = 0;
    int64_t m = 0, ex = 0;
    if (!semb_test_seam_gpu_last_read(codes.data(), codes.size(), &width, &m, &ex) || width > codes.size()) {
      ++unread;
      continue;
    }
    std::vector<uint8_t> buf(16 + width + 16);
    size_t len = 0;
    semb_seam_serialize_document(codes.data(), &m, &ex, 1, width, buf.data(), buf.size(), &len);
    uint8_t d[32];
    superslm::Sha256Hash(buf.data(), len, d);
    out << label << "\t" << Hex(d, 32) << "\n";
    out.flush();
    ++n;
  }
  semb_encoder_close(e);
  u3::Verdict(refused == 0 && unread == 0 && n > 0,
              "c10a_anchors every document encodes on the GPU and its read triple is serialised",
              u3::S(n) + " written, " + u3::S(refused) + " refused, " + u3::S(unread) + " without a read");
}

// C10 (g), P:4168-4170 and the release rule P:4096: --positions N content
// tokens ("the" then " the" repeated; the call log's prefill `arg` confirms the
// count, N + 1 with the terminator). Parity with the CPU row, unless --runs 2
// (the cap row: two GPU runs byte-equal, the CPU half not run for 1.0,
// D-SLM7722). Where C(N + 1) > 4,096 the log shows the sequence released
// inside the same encode (P:4096). Reports the encode's wall time (the cap
// row's single-submission figure, P:4169, is derived from it by the driver).
void CellC10g() {
  const size_t n = static_cast<size_t>(std::strtoull(g.positions.c_str(), nullptr, 10));
  if (n == 0) { u3::Missing(g.cell, "--positions <content tokens>"); return; }
  std::string text = "the";
  for (size_t i = 1; i < n; ++i) text += " the";
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle on the real artifact");
  if (!e) return;
  ResetLog();
  std::vector<float> r1, r2;
  const auto t0 = std::chrono::steady_clock::now();
  const semb_status s1 = u3::EncodeRow(e, text, &r1);
  const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  const auto log = Log();
  uint64_t prefill_arg = 0;
  size_t prefill_at = 0;
  for (size_t i = 0; i < log.size(); ++i) {
    if (Is(log[i], "SslmGpuSeqPrefillPromptForG5Bridge")) { prefill_arg = log[i].arg; prefill_at = i; }
  }
  if (prefill_arg != n + 1) {
    u3::Verdict(false, "c10g setup: the text is " + u3::S(n) + " content tokens",
                "the prefill's arg is " + u3::S(prefill_arg) + ", want " + u3::S(n + 1));
  }
  uint64_t cap = 64;
  while (cap < n + 1) cap <<= 1;
  if (cap > 4096) {
    bool released = false;
    for (size_t i = prefill_at + 1; i < log.size(); ++i) released = released || Is(log[i], "sslm_gpu_seq_release");
    u3::Verdict(released, "c10g C(n) = " + u3::S(cap) + " > 4,096: the sequence is released inside the same encode (P:4096)",
                Describe(log, prefill_at));
  }
  u3::Note(g.cell, "positions=" + u3::S(n + 1) + " gpu_encode_ms=" + std::to_string(ms));
  if (g.runs == "2") {
    const semb_status s2 = u3::EncodeRow(e, text, &r2);
    u3::Verdict(s1 == SEMB_OK && s2 == SEMB_OK && u3::SameBytes(r1, r2),
                "c10g the cap row: SEMB_OK and two GPU runs byte-equal (P:4168)",
                std::string(u3::Name(s1)) + " / " + u3::Name(s2));
  } else {
    const std::vector<float>& cpu = CpuRow(g.model, g.tokenizer, text);
    u3::Verdict(s1 == SEMB_OK && u3::SameBytes(r1, cpu), "c10g byte parity with the CPU row at " + u3::S(n) + " tokens",
                std::string(u3::Name(s1)) + (u3::SameBytes(r1, cpu) ? ", byte-equal" : ", DIFFERS"));
  }
  semb_encoder_close(e);
}

// C11's device readings (P:4194-4195), REAL ARTIFACT, measurement (no
// threshold): the process's local video memory in use (DXGI
// QueryVideoMemoryInfo, CurrentUsage) after the open (the model map) and its
// peak while a --positions encode runs (sampled every 50 ms), and the longest
// forward the open-time agreement check runs (the largest prefill `arg` in the
// open's call log), the longest position the check proves (sec 4.3).
uint64_t LocalVideoMemoryInUse() {
#if defined(_WIN32)
  IDXGIFactory1* f = nullptr;
  if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&f))) || !f) return 0;
  IDXGIAdapter1* a = nullptr;
  uint64_t used = 0;
  if (SUCCEEDED(f->EnumAdapters1(0, &a)) && a) {
    IDXGIAdapter3* a3 = nullptr;
    if (SUCCEEDED(a->QueryInterface(__uuidof(IDXGIAdapter3), reinterpret_cast<void**>(&a3))) && a3) {
      DXGI_QUERY_VIDEO_MEMORY_INFO info{};
      if (SUCCEEDED(a3->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &info))) used = info.CurrentUsage;
      a3->Release();
    }
    a->Release();
  }
  f->Release();
  return used;
#else
  return 0;
#endif
}

void CellC11Device() {
#if defined(_WIN32)
  const uint64_t before = LocalVideoMemoryInUse();
  ResetLog();
  const auto t0 = std::chrono::steady_clock::now();
  semb_encoder e = MustOpen(g.model, g.tokenizer, 1, u3::kDeviceGpu, "a GPU handle on the real artifact");
  const double open_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  if (!e) return;
  uint64_t longest = 0;
  for (const auto& c : Log()) {
    if (Is(c, "SslmGpuSeqPrefillPromptForG5Bridge") && c.arg > longest) longest = c.arg;
  }
  const uint64_t after_map = LocalVideoMemoryInUse();
  u3::Note(g.cell, "READING gpu_open_ms=" + std::to_string(open_ms) + " vram_before=" + u3::S(before) +
                       " vram_after_open=" + u3::S(after_map) + " longest_witness_positions=" + u3::S(longest));
  const size_t n = g.positions.empty() ? 0 : static_cast<size_t>(std::strtoull(g.positions.c_str(), nullptr, 10));
  if (n) {
    std::string text = "the";
    for (size_t i = 1; i < n; ++i) text += " the";
    std::atomic<bool> done{false};
    std::atomic<uint64_t> peak{after_map};
    std::thread sampler([&] {
      while (!done) {
        const uint64_t v = LocalVideoMemoryInUse();
        if (v > peak) peak = v;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
      }
    });
    std::vector<float> row;
    const semb_status s = u3::EncodeRow(e, text, &row);
    done = true;
    sampler.join();
    u3::Note(g.cell, "READING positions=" + u3::S(n + 1) + " status=" + u3::Name(s) + " vram_peak=" + u3::S(peak.load()));
  }
  semb_encoder_close(e);
  u3::Verdict(longest > 0 && after_map > 0, "c11_device readings taken (measurement, no threshold)",
              "open " + std::to_string(open_ms) + " ms");
#else
  u3::Missing(g.cell, "DXGI: Windows only");
#endif
}

void CellEnvRows(const char* name, const char* value) {
  for (const auto& x : kShortDocs) CpuRow(g.model, g.tokenizer, x);
  SetEnv(name, value);
  OpenSucceedsWithCpuRows(std::string(name) + "=" + value + " set before the first open: rows equal CPU rows");
}

}  // namespace

int main(int argc, char** argv) {
  for (int i = 1; i + 1 < argc; i += 2) {
    const std::string a = argv[i], v = argv[i + 1];
    if (a == "--cell") g.cell = v;
    else if (a == "--model") g.model = v;
    else if (a == "--tokenizer") g.tokenizer = v;
    else if (a == "--model5k") g.model5k = v;
    else if (a == "--tokenizer5k") g.tokenizer5k = v;
    else if (a == "--guard-model") g.guard_model = v;
    else if (a == "--scratch") g.scratch = v;
    else if (a == "--index") g.index = v;
    else if (a == "--value") g.value = v;
    else if (a == "--remove-shader") g.remove_shader = v;
    else if (a == "--log") g.log = v;
    else if (a == "--texts") g.texts = v;
    else if (a == "--positions") g.positions = v;
    else if (a == "--runs") g.runs = v;
  }
  if (!g.log.empty()) u3::LogFile() = std::fopen(g.log.c_str(), "ab");
  u3::Note(g.cell, "BEGIN");
  if (!u3::FileExists(g.model) || !u3::FileExists(g.tokenizer)) {
    u3::Missing(g.cell, "the U1 pair (--model, --tokenizer)");
    return u3::ExitCode();
  }
  if (!g.scratch.empty()) fs::create_directories(g.scratch);
  if (!ResolveDeviceStatuses()) return u3::ExitCode();

  const std::map<std::string, std::function<void()>> cells = {
      {"row1_lifetime", CellRow1Lifetime},
      {"row1_slots_mc8", CellRow1SlotsMc8},
      {"row1_slots_unbounded", CellRow1SlotsUnbounded},
      {"row1_default_release", CellRow1DefaultRelease},
      {"row1_hold_600", CellRow1Hold600},
      {"row3_mc4", CellRow3Mc4},
      {"row3_batch16", CellRow3Batch16},
      {"row3a_two_handles", [] { TwoOrOneHandle(true); }},
      {"row3b_one_handle", [] { TwoOrOneHandle(false); }},
      {"row4_shapes", CellRow4Shapes},
      {"row5a_guard", CellRow5aGuard},
      {"row5a_mechanism", [] { InjectedEncode("SslmGpuSeqPrefillPromptForG5Bridge", 1, "SSLM_SEQUENCE_REJECTED", SEMB_ENGINE_REFUSED, false, "row5a_mechanism", g.model, g.tokenizer, "rejected", "after"); }},
      {"row5b_prefill", [] { InjectedEncode("SslmGpuSeqPrefillPromptForG5Bridge", 1, "SSLM_DEVICE_LOST", kUnavailable, true, "row5b_prefill", g.model, g.tokenizer, "lost", "after"); }},
      {"row5b_seqcreate", [] {
         if (g.model5k.empty()) { u3::Missing(g.cell, "--model5k"); return; }
         InjectedEncode("sslm_gpu_seq_create", 1, "SSLM_DEVICE_LOST", kUnavailable, true, "row5b_seqcreate", g.model5k, g.tokenizer5k, Text(600), Text(12)); }},
      {"row5c_open_lost", [] { OpenInjected("SSLM_DEVICE_LOST", kUnavailable, "row5c_open_lost"); }},
      {"row5c_open_rejected", [] { OpenInjected("SSLM_SEQUENCE_REJECTED", kDiverged, "row5c_open_rejected"); }},
      {"row5d_seam", [] {
         if (g.model5k.empty()) { u3::Missing(g.cell, "--model5k"); return; }
         InjectedEncode("sslm_gpu_seq_create", 1, "SSLM_GPU_ALLOCATION_FAILED", SEMB_ALLOCATION_FAILED, false, "row5d_seam", g.model5k, g.tokenizer5k, Text(600), Text(12)); }},
      {"row5f_batch_guard", [] { CellBatch(true); }},
      {"row5f_batch_lost", [] { CellBatch(false); }},
      {"c10e1", [] { CellPerturbOpen(0, 3, "one code of W-B document 3"); }},
      {"c10e4_scale", [] { CellPerturbOpen(1, 7, "the mantissa of W-B document 7, codes untouched"); }},
      {"c10e4_last_wq", [] { CellPerturbOpen(0, 21, "one code of the last W-Q sequence (the truncation query)"); }},
      {"c10e4_wb15", [] { CellPerturbOpen(0, 15, "one code of W-B document 15"); }},
      {"c10e2", CellC10e2},
      {"c10i_before_device", CellC10iBeforeDevice},
      {"row7_fingerprint", CellRow7Fingerprint},
      {"row11_gpu_triples", CellRow11GpuTriples},
      {"c10d_index", CellC10dIndex},
      {"c10d_refused_then_corrected", CellC10dRefusedThenCorrected},
      {"c10d_after_success", CellC10dAfterSuccess},
      {"c10d_refused_after_creation", CellC10dRefusedAfterCreation},
      {"c10d_debug_layer", [] { CellEnvRows("SSLM_GPU_ENABLE_DEBUG_LAYER", "1"); }},
      {"c10d_b5_srv", [] { CellEnvRows("SSLM_B5_ASYNC_SWAP_SRV_REBIND", "1"); }},
      {"c10d_b5_uav", [] { CellEnvRows("SSLM_B5_ASYNC_DROP_UAV_REBIND", "1"); }},
      {"c10a_anchors", CellC10aAnchors},
      {"c10g", CellC10g},
      {"c11_device", CellC11Device},
  };
  const auto it = cells.find(g.cell);
  if (it == cells.end()) {
    u3::Verdict(false, "u3_gpu_cells", "unknown --cell " + g.cell);
    return 1;
  }
  it->second();
  std::printf("SUMMARY %s pass=%d fail=%d red=%d missing=%d\n", g.cell.c_str(), u3::T().pass, u3::T().fail, u3::T().red,
              u3::T().missing);
  return u3::ExitCode();
}
