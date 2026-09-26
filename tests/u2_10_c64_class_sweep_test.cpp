// tests/u2_10_c64_class_sweep_test.cpp -- U2 cloud build, U2-10's C64: the
// class sweep (te267 sec 5 U2-10 "Cells", C64). The test author's,
// independently of the builder.
//
// One executable links the SHIPPED static product target (`superembedder`,
// no test seam) with the global `operator new` replaced to count live
// allocations and to fail the k-th one. One invocation runs one table row
// with one driver: it warms up (one open-and-close cycle), runs the driver
// unarmed counting the K allocations the swept call makes, then for each arm
//   (a)  std::bad_alloc      -> the row's allocation status,
//   (a') std::length_error   -> the row's allocation status,
//   (b)  a foreign exception -> the row's catch-all status,
// and each k in 1..K, it fails the k-th allocation and grades: the status,
// nothing escaping (the harness's own catch (...) is red), the process not
// terminating, (c) the live count equal to its value before the call (every
// driver but the growth driver), the follow-up returning its reference, and
// every handle the driver opened closing SEMB_OK with the live count back at
// its post-warm-up value.
//
// Each arm runs in a child process, so a termination (std::terminate from an
// escaped exception on a worker thread, or a noexcept frame) is read as a
// verdict for that k, never as the harness dying: the parent starts a new
// child from k + 1 and reports the terminating k. On POSIX the child is a
// fork() of the parent, read through a pipe and waitpid(). On Windows (cl.exe
// and clang-cl, where C64 (c)'s reds live) the parent re-launches this
// executable with the same command line plus --c64-child-arm <arm>
// --c64-child-k0 <k0>, its stdout redirected into a pipe the parent reads,
// and waits with WaitForSingleObject; the child rebuilds the same driver from
// the same arguments and runs exactly what the forked child runs. The
// parent runs no product code on either path.
//
// EXPECTED STATUSES COME FROM ITEM 3 (U2-10 Builds item 3's family table),
// in this source (`ExpectedFor` below), never from tools/c_boundary_table.json
// and never from the build. The driver script refuses a table row whose
// recorded statuses differ from what this source prints for it.
//
// The new values item 3 names are not in today's headers, so they are stated
// here: kSembInterimAllocationFailed = 10 (the plan: "the next free value,
// 10"), kSembEncodeAllocationFailed = 3 (the plan: "(3)"). The plan names
// kSembWaPoolAllocationFailed and kSembWaPoolInternalFailure without values;
// this suite takes the next free values, 6 and 7 (a build-time item: the
// builder's header must match, or this source changes with it).
//
// `semb_wa_digest` is declared here in its post-build form (item 3 makes it a
// semb_status function). Today it returns void, so its pre-build status
// reading is unspecified; its red today is read at its escape and leak legs.
//
// USAGE:
//   --model <m> --tokenizer <t> --scratch <dir> --row <name> --driver <d>
//   [--mc <n>] [--arms a,a2,b] [--k-stride <s>] [--count-only]
//   --k-stride s grades k = 1, 1+s, 1+2s, ... and K (a sampled reading, never
//   the verdict: the plan drops or subsamples no driver without a ruling).
//   --print-expected            one line per row: EXPECT <row> <family> <alloc> <catch-all>
// Output lines (parsed by tests/u2_10_c64_class_sweep_check.py):
//   K <row> <driver> <mc> <K>
//   ARM <arm> k=<k> status=<s> want=<w> fired=<0|1> escaped=<0|1> leak=<d> follow=<0|1> close=<0|1>
//   TERMINATED <arm> k=<k> signal=<n>        (POSIX: the signal, or -exit status)
//   TERMINATED <arm> k=<k> exit=0x<code>     (Windows: the child's exit code; an
//                                             unhandled SEH exception's code, 0x3
//                                             for abort(), 0x8E for the watchdog)
//   SUMMARY <row> <driver> <mc> <arm> K=<K> pass=<p> fail=<f> first_fail_k=<k> first_fail=<detail>
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <malloc.h>
#include <process.h>
#else
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <new>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "superembedder/semb.h"
#include "superembedder/bake_abi.h"
#include "superembedder/bank_internal_abi.h"
#include "superembedder/encoder_interim_abi.h"
#include "superembedder/pool_abi.h"
#include "superembedder/seam_abi.h"
#include "superembedder/wb_digest_abi.h"
#include "superembedder/wq_digest_abi.h"

// Not declared in any product header (bank.cpp defines them; query.cpp
// declares them locally).
extern "C" semb_status semb_bank_acquire_query(semb_bank bank, const uint8_t fingerprint[32]);
extern "C" semb_status semb_bank_release_query(semb_bank bank);
// Item 3's post-build form.
extern "C" semb_status semb_wa_digest(uint8_t out_digest[32]);
// Leaves the driver calls, not in the included headers.
extern "C" const char* semb_adapter_self_id(void);
extern "C" const char* semb_ps1_version_label(void);
extern "C" const char* semb_ps_n_version_label(void);
extern "C" void semb_library_build_generation(char out_token[32]);

// ---------------------------------------------------------------------------
// The replaced global operator new.
// ---------------------------------------------------------------------------
namespace hook {
std::atomic<int64_t> live{0};
std::atomic<uint64_t> count{0};
std::atomic<uint64_t> fail_at{0};  // absolute allocation index to fail; 0 = disarmed
std::atomic<int> mode{0};          // 0 bad_alloc, 1 length_error, 2 foreign
std::atomic<int> fired{0};
// Counts successful allocations of exactly `watch_size` bytes: a slot growth
// allocates P * C bytes, so this counts the growths to one C (the batch
// drivers' warm-up, below).
std::atomic<size_t> watch_size{0};
std::atomic<uint64_t> watch_hits{0};
struct Foreign {  // not derived from std::exception
  int code;
};

void* Allocate(size_t n, size_t align) {
  const uint64_t idx = count.fetch_add(1, std::memory_order_relaxed) + 1;
  const uint64_t f = fail_at.load(std::memory_order_relaxed);
  if (f != 0 && idx == f) {
    fail_at.store(0);
    fired.store(1);
    switch (mode.load()) {
      case 1: throw std::length_error("C64 (a') injected length_error");
      case 2: throw Foreign{64};
      default: throw std::bad_alloc();
    }
  }
  void* p = nullptr;
  const size_t a = align < sizeof(void*) ? sizeof(void*) : align;
#if defined(_WIN32)
  // Every hooked allocation is _aligned_malloc'd, so Release frees every one with _aligned_free.
  p = _aligned_malloc(n ? n : 1, a);
  if (!p) throw std::bad_alloc();
#else
  if (posix_memalign(&p, a, n ? n : 1) != 0) throw std::bad_alloc();
#endif
  live.fetch_add(1, std::memory_order_relaxed);
  if (n != 0 && n == watch_size.load(std::memory_order_relaxed)) watch_hits.fetch_add(1);
  return p;
}
void Release(void* p) {
  if (!p) return;
  live.fetch_sub(1, std::memory_order_relaxed);
#if defined(_WIN32)
  _aligned_free(p);
#else
  std::free(p);
#endif
}
void Disarm() { fail_at.store(0); }

// The swept window: only the product call itself, never the harness's own
// buffers, is counted and armed. Go/Stop bracket each product call on a
// driver's call path; they act only while a driver's call is running.
std::atomic<bool> in_call{false};
std::atomic<uint64_t> pending_k{0};
std::atomic<uint64_t> window{0};
uint64_t window_start = 0;
inline void Go() {
  if (!in_call.load()) return;
  window_start = count.load();
  if (pending_k.load() != 0) fail_at.store(count.load() + pending_k.load());
}
template <class T>
T Stop(T v) {
  if (in_call.load()) {
    fail_at.store(0);
    window.fetch_add(count.load() - window_start);
  }
  return v;
}
}  // namespace hook
#define SW(expr) (hook::Go(), hook::Stop(expr))
#define SWV(expr) (hook::Go(), (expr), hook::Stop(0))

void* operator new(size_t n) { return hook::Allocate(n, 0); }
void* operator new[](size_t n) { return hook::Allocate(n, 0); }
void* operator new(size_t n, std::align_val_t a) { return hook::Allocate(n, static_cast<size_t>(a)); }
void* operator new[](size_t n, std::align_val_t a) { return hook::Allocate(n, static_cast<size_t>(a)); }
void* operator new(size_t n, const std::nothrow_t&) noexcept {
  try { return hook::Allocate(n, 0); } catch (...) { return nullptr; }
}
void* operator new[](size_t n, const std::nothrow_t&) noexcept {
  try { return hook::Allocate(n, 0); } catch (...) { return nullptr; }
}
void* operator new(size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
  try { return hook::Allocate(n, static_cast<size_t>(a)); } catch (...) { return nullptr; }
}
void* operator new[](size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
  try { return hook::Allocate(n, static_cast<size_t>(a)); } catch (...) { return nullptr; }
}
void operator delete(void* p) noexcept { hook::Release(p); }
void operator delete[](void* p) noexcept { hook::Release(p); }
void operator delete(void* p, size_t) noexcept { hook::Release(p); }
void operator delete[](void* p, size_t) noexcept { hook::Release(p); }
void operator delete(void* p, std::align_val_t) noexcept { hook::Release(p); }
void operator delete[](void* p, std::align_val_t) noexcept { hook::Release(p); }
void operator delete(void* p, size_t, std::align_val_t) noexcept { hook::Release(p); }
void operator delete[](void* p, size_t, std::align_val_t) noexcept { hook::Release(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { hook::Release(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { hook::Release(p); }
void operator delete(void* p, std::align_val_t, const std::nothrow_t&) noexcept { hook::Release(p); }
void operator delete[](void* p, std::align_val_t, const std::nothrow_t&) noexcept { hook::Release(p); }

namespace fs = std::filesystem;

namespace {

int ProcessId() {
#if defined(_WIN32)
  return _getpid();
#else
  return static_cast<int>(getpid());
#endif
}

// ---------------------------------------------------------------------------
// Item 3's family table (U2-10 Builds item 3), in this source.
// ---------------------------------------------------------------------------
constexpr int32_t kInterimAllocationFailed = 10;  // "the next free value, 10"
constexpr int32_t kEncodeAllocationFailed = 3;    // "(3)"
constexpr int32_t kWaPoolAllocationFailed = 6;    // unvalued in the plan: next free (build-time item)
constexpr int32_t kWaPoolInternalFailure = 7;     // unvalued in the plan: next free (build-time item)

struct Expected {
  const char* family;
  int32_t alloc;
  int32_t catch_all;
  const char* alloc_name;
  const char* catch_all_name;
};

Expected ExpectedFor(const std::string& row) {
  static const std::map<std::string, int> kFamily = {
      {"semb_encoder_open", 0}, {"semb_encoder_open_memory", 0}, {"semb_encoder_close", 0}, {"semb_encoder_dims", 0}, {"semb_encode", 0},
      {"semb_encode_query", 0}, {"semb_encode_batch", 0}, {"semb_bank_open", 0}, {"semb_bank_close", 0}, {"semb_query_open", 0},
      {"semb_query_encode", 0}, {"semb_query_close", 0}, {"semb_fingerprint_of", 0}, {"semb_bake_to_path", 0},
      {"semb_wb_digest", 0}, {"semb_wq_digest", 0}, {"semb_bank_acquire_query", 0},
      {"semb_bank_release_query", 0}, {"semb_bank_debug_state", 0}, {"semb_bank_ranked_state", 0},
      {"semb_wa_digest", 0},
      {"semb_interim_encoder_open", 1}, {"semb_interim_encoder_open_from_memory", 1},
      {"semb_interim_encoder_geometry", 1}, {"semb_interim_encode_seam", 1}, {"semb_interim_ps_n_select", 1},
      {"semb_interim_encode_ps_n", 1}, {"semb_interim_encode_batch_ps_n", 1},
      {"semb_interim_release_workspaces", 1},  // U2-9 item 2's release verb, U2-10 Builds item 6
      // U2-7's three (U2-10 Builds item 6): two semb.h verbs, one interim verb.
      {"semb_interim_query_token_count", 1},
      {"semb_encode_document_for_witness", 2},
      {"semb_wa_pool_run", 3}, {"semb_ps_n_dequantize", 3},
  };
  const auto f = kFamily.find(row);
  if (f == kFamily.end()) return Expected{"leaf", 0, 0, "-", "-"};
  switch (f->second) {
    case 0:
      if (row == "semb_bank_open") {
        return Expected{"semb_status", SEMB_ALLOCATION_FAILED, SEMB_ARTIFACT_UNREADABLE, "SEMB_ALLOCATION_FAILED",
                        "SEMB_ARTIFACT_UNREADABLE"};
      }
      return Expected{"semb_status", SEMB_ALLOCATION_FAILED, SEMB_ENGINE_REFUSED, "SEMB_ALLOCATION_FAILED",
                      "SEMB_ENGINE_REFUSED"};
    case 1:
      return Expected{"SembInterimStatus", kInterimAllocationFailed, kSembInterimEngineRefused,
                      "kSembInterimAllocationFailed", "kSembInterimEngineRefused"};
    case 2:
      return Expected{"SembEncodeStatus", kEncodeAllocationFailed, kSembEncodeEngineRefused,
                      "kSembEncodeAllocationFailed", "kSembEncodeEngineRefused"};
    default:
      return Expected{"SembWaPoolStatus", kWaPoolAllocationFailed, kWaPoolInternalFailure,
                      "kSembWaPoolAllocationFailed", "kSembWaPoolInternalFailure"};
  }
}

const char* const kAllRows[] = {
    "semb_status_name", "semb_adapter_self_id", "semb_ps1_version_label", "semb_ps_n_version_label",
    "semb_library_build_generation", "semb_seam_serialize_document", "semb_wa_pooled_spread",
    "semb_interim_encoder_close", "semb_encoder_open", "semb_encoder_close", "semb_encoder_dims", "semb_encode",
    "semb_encode_batch", "semb_bank_open", "semb_bank_close", "semb_query_open", "semb_query_encode",
    "semb_query_close", "semb_fingerprint_of", "semb_bake_to_path", "semb_wb_digest", "semb_wq_digest",
    "semb_bank_acquire_query", "semb_bank_release_query", "semb_bank_debug_state", "semb_bank_ranked_state",
    "semb_interim_encoder_open", "semb_interim_encoder_open_from_memory", "semb_interim_encoder_geometry",
    "semb_interim_encode_seam", "semb_interim_ps_n_select", "semb_interim_encode_ps_n",
    "semb_interim_encode_batch_ps_n", "semb_encode_document_for_witness", "semb_wa_pool_run",
    "semb_ps_n_dequantize", "semb_wa_digest", "semb_interim_release_workspaces",
    // U2-7's three (U2-10 Builds item 6).
    "semb_encoder_open_memory", "semb_encode_query", "semb_interim_query_token_count",
};


// ---------------------------------------------------------------------------
// Fixture and helpers.
// ---------------------------------------------------------------------------
struct Args {
  std::string model, tokenizer, scratch, row, driver;
  uint32_t mc = 1;
  std::vector<int> arms = {0, 1, 2};
  uint64_t k_stride = 1;  // 1 = every k (see --k-stride)
  bool count_only = false;
};
Args g;

constexpr int32_t kPairAppended = 262;

std::string Text(size_t positions) { return std::string(positions - 1, 'a'); }  // byte-level pair
std::vector<int32_t> Ids(size_t positions) {
  std::vector<int32_t> ids(positions - 1);
  for (size_t i = 0; i < ids.size(); ++i) ids[i] = 3 + static_cast<int32_t>((i * 7 + 1) % 250);
  return ids;
}
std::vector<uint8_t> ReadAll(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}

semb_encoder OpenEnc(uint32_t mc) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = g.model.data();
  cfg.model_path_len = g.model.size();
  cfg.tokenizer_path = g.tokenizer.data();
  cfg.tokenizer_path_len = g.tokenizer.size();
  cfg.max_concurrency = mc;
  semb_encoder e = nullptr;
  return semb_encoder_open(&cfg, &e) == SEMB_OK ? e : nullptr;
}
std::vector<float> EncodeVec(semb_encoder e, const std::string& t, semb_status* st = nullptr) {
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  std::vector<float> v(dims ? dims : 1);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  const semb_status s = SW(semb_encode(e, t.data(), t.size(), v.data(), v.size() * 4, &req, &fp));
  if (st) *st = s;
  if (s != SEMB_OK) v.clear();
  return v;
}
std::vector<float> QueryVec(semb_query q, const std::string& t, uint32_t dims, semb_status* st = nullptr) {
  std::vector<float> v(dims ? dims : 1);
  size_t req = 0;
  const semb_status s = SW(semb_query_encode(q, t.data(), t.size(), v.data(), v.size() * 4, &req));
  if (st) *st = s;
  if (s != SEMB_OK) v.clear();
  return v;
}

// semb_encode_query (U2-7 item 2): the query form of semb_encode.
std::vector<float> EncodeQueryVec(semb_encoder e, const std::string& t, semb_status* st = nullptr) {
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  std::vector<float> v(dims ? dims : 1);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  const semb_status s = SW(semb_encode_query(e, t.data(), t.size(), v.data(), v.size() * 4, &req, &fp));
  if (st) *st = s;
  if (s != SEMB_OK) v.clear();
  return v;
}

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

// A 1-row bank baked once per process (unarmed), for the bank and query rows.
std::string BankStem() {
  static std::string stem;
  if (!stem.empty()) return stem;
  stem = (fs::path(g.scratch) / ("c64_bank_" + std::to_string(ProcessId()))).string();
  semb_encoder e = OpenEnc(1);
  Docs d({"a short bank document"});
  if (!e || semb_bake_to_path(e, d.docs.data(), 1, stem.data(), stem.size()) != SEMB_OK) {
    std::printf("SETUP-FAIL bank bake\n");
  }
  if (e) semb_encoder_close(e);
  return stem;
}
semb_bank OpenBank() {
  const std::string s = BankStem();
  semb_bank b = nullptr;
  return semb_bank_open(s.data(), s.size(), &b) == SEMB_OK ? b : nullptr;
}

// ---------------------------------------------------------------------------
// A driver: setup (unarmed opens), the swept call, the follow-up, the closes.
// ---------------------------------------------------------------------------
struct Ctx {
  semb_encoder enc = nullptr;
  semb_bank bank = nullptr;
  semb_query query = nullptr;
  SembInterimEncoder* ienc = nullptr;
  // Outputs a swept call may create (closed by the closes if it succeeded).
  semb_encoder out_enc = nullptr;
  semb_bank out_bank = nullptr;
  semb_query out_query = nullptr;
  SembInterimEncoder* out_ienc = nullptr;
  bool acquired = false;  // semb_bank_acquire_query succeeded
  // Row-specific carried state.
  std::vector<int8_t> codes;
  std::vector<int64_t> m, e;
  size_t n = 0;
  uint8_t fp[32] = {};
};

struct Driver {
  std::function<void(Ctx&)> setup;
  std::function<int32_t(Ctx&)> call;
  std::function<bool(Ctx&)> follow;
  bool fresh_per_k = false;   // closes after every k, on fresh handles
  bool growth = false;        // the growth driver: live count graded by the closes
};

// Every close returns SEMB_OK (any query first, then the bank, then the encoder).
bool Closes(Ctx& c) {
  bool ok = true;
  if (c.out_query) { ok = semb_query_close(c.out_query) == SEMB_OK && ok; c.out_query = nullptr; }
  if (c.query) { ok = semb_query_close(c.query) == SEMB_OK && ok; c.query = nullptr; }
  if (c.acquired && c.bank) { ok = semb_bank_release_query(c.bank) == SEMB_OK && ok; c.acquired = false; }
  if (c.out_bank) { ok = semb_bank_close(c.out_bank) == SEMB_OK && ok; c.out_bank = nullptr; }
  if (c.bank) { ok = semb_bank_close(c.bank) == SEMB_OK && ok; c.bank = nullptr; }
  if (c.out_enc) { ok = semb_encoder_close(c.out_enc) == SEMB_OK && ok; c.out_enc = nullptr; }
  if (c.enc) { ok = semb_encoder_close(c.enc) == SEMB_OK && ok; c.enc = nullptr; }
  if (c.out_ienc) { semb_interim_encoder_close(c.out_ienc); c.out_ienc = nullptr; }
  if (c.ienc) { semb_interim_encoder_close(c.ienc); c.ienc = nullptr; }
  return ok;
}

// References, computed once per process, unarmed.
std::map<std::string, std::vector<float>> g_ref_vec;
const std::vector<float>& RefVec(const std::string& t) {
  auto it = g_ref_vec.find(t);
  if (it != g_ref_vec.end()) return it->second;
  semb_encoder e = OpenEnc(1);
  std::vector<float> v = e ? EncodeVec(e, t) : std::vector<float>{};
  if (e) semb_encoder_close(e);
  return g_ref_vec[t] = v;
}
const std::string kShort = "a short document";

bool EncFollowText(Ctx& c, const std::string& t) {
  semb_encoder e = c.enc ? c.enc : c.out_enc;
  if (!e) return false;
  semb_status s = SEMB_OK;
  const auto v = EncodeVec(e, t, &s);
  return s == SEMB_OK && v == RefVec(t);
}
bool EncFollow(Ctx& c) { return EncFollowText(c, kShort); }
// semb_encode_query's follow-up: the query form on the same handle equals a
// fresh handle's (references computed once per process, unarmed).
bool EncQueryFollowText(Ctx& c, const std::string& t) {
  static std::map<std::string, std::vector<float>> refs;
  auto it = refs.find(t);
  if (it == refs.end()) {
    semb_encoder f = OpenEnc(1);
    std::vector<float> v = f ? EncodeQueryVec(f, t) : std::vector<float>{};
    if (f) semb_encoder_close(f);
    it = refs.emplace(t, v).first;
  }
  semb_encoder e = c.enc ? c.enc : c.out_enc;
  if (!e) return false;
  semb_status s = SEMB_OK;
  const auto v = EncodeQueryVec(e, t, &s);
  return s == SEMB_OK && !it->second.empty() && v == it->second;
}
// The long drivers' follow-up is the driver's own long document (U2-9 item 5
// releases its buffer after it), so every armed call on the handle grows from
// capacity 0, as C64's long driver states. A short follow-up would leave record
// 0 holding P * 64, and the next armed call's release-before-grow (item 3)
// would read -1 on the live count by design. A long follow-up also takes the
// gate, so a gate the failed call did not give back stalls it, which the
// per-k watchdog reads red.
struct SeamRef {
  SembInterimStatus st = kSembInterimOk;
  std::vector<int8_t> codes;
  std::vector<int64_t> m, e;
  bool operator==(const SeamRef& o) const { return st == o.st && codes == o.codes && m == o.m && e == o.e; }
};
size_t Hidden(const SembInterimEncoder* enc) {
  SembInterimGeometry gm{};
  gm.struct_size = sizeof(gm);
  semb_interim_encoder_geometry(enc, &gm);
  return gm.hidden_size;
}
SeamRef Seam(SembInterimEncoder* enc, const std::vector<int32_t>& ids, size_t budget, SembForwardLeg leg) {
  SeamRef r;
  const size_t n = ids.size() + 1, h = Hidden(enc);
  r.codes.assign(n * h, 0);
  r.m.assign(n, 0);
  r.e.assign(n, 0);
  size_t pos = 0;
  const char* name = nullptr;
  r.st = SW(semb_interim_encode_seam(enc, ids.data(), ids.size(), budget, leg, r.codes.data(), r.codes.size(),
                                     r.m.data(), r.e.data(), n, &pos, &name));
  return r;
}
SembInterimEncoder* OpenInterim() {
  SembInterimEncoder* e = nullptr;
  const char* name = nullptr;
  return semb_interim_encoder_open(g.model.c_str(), kPairAppended, &e, &name) == kSembInterimOk ? e : nullptr;
}
const SeamRef& RefSeam() {
  static SeamRef r;
  static bool done = false;
  if (!done) {
    SembInterimEncoder* e = OpenInterim();
    if (e) { r = Seam(e, Ids(6), 0, kSembForwardLegChunkBatched); semb_interim_encoder_close(e); }
    done = true;
  }
  return r;
}
bool InterimFollow(Ctx& c) {
  SembInterimEncoder* e = c.ienc ? c.ienc : c.out_ienc;
  return e && Seam(e, Ids(6), 0, kSembForwardLegChunkBatched) == RefSeam();
}
// The interim long drivers' follow-up: the 4,097-position document on the
// same handle, equal to a fresh handle's (see EncFollowText).
bool InterimFollowLong(Ctx& c) {
  static SeamRef ref;
  static bool done = false;
  if (!done) {
    SembInterimEncoder* f = OpenInterim();
    if (f) { ref = Seam(f, Ids(4097), 0, kSembForwardLegChunkBatched); semb_interim_encoder_close(f); }
    done = true;
  }
  SembInterimEncoder* e = c.ienc ? c.ienc : c.out_ienc;
  return e && ref.st == kSembInterimOk && Seam(e, Ids(4097), 0, kSembForwardLegChunkBatched) == ref;
}
bool BankFollow(Ctx& c) {
  semb_bank b = c.bank ? c.bank : c.out_bank;
  if (!b) return false;
  uint8_t fp[32];
  int64_t count = 0, dims = 0;
  return semb_bank_debug_state(b, fp, &count, &dims) == SEMB_OK && count == 1 && dims > 0;
}
bool QueryFollowText(Ctx& c, const std::string& text) {
  semb_query q = c.query ? c.query : c.out_query;
  if (!q) return false;
  uint32_t dims = 0;
  semb_encoder_dims(c.enc, &dims);
  static std::map<std::string, std::vector<float>> refs;
  auto it = refs.find(text);
  if (it == refs.end()) {
    std::vector<float> ref;
    semb_encoder e = OpenEnc(1);
    semb_bank b = OpenBank();
    semb_query rq = nullptr;
    if (e && b && semb_query_open(e, b, &rq) == SEMB_OK) {
      ref = QueryVec(rq, text, dims);
      semb_query_close(rq);
    }
    if (b) semb_bank_close(b);
    if (e) semb_encoder_close(e);
    it = refs.emplace(text, ref).first;
  }
  semb_status s = SEMB_OK;
  const auto v = QueryVec(q, text, dims, &s);
  return s == SEMB_OK && !it->second.empty() && v == it->second;
}
bool QueryFollow(Ctx& c) { return QueryFollowText(c, kShort); }

int32_t BatchCall(semb_encoder e, const std::vector<std::string>& texts) {
  Docs d(texts);
  uint32_t dims = 0;
  semb_encoder_dims(e, &dims);
  std::vector<float> rows(texts.size() * dims);
  size_t req = 0;
  return SW(semb_encode_batch(e, d.docs.data(), d.docs.size(), rows.data(), rows.size() * 4, &req));
}
int32_t BakeCall(semb_encoder e, const std::vector<std::string>& texts, const std::string& tag) {
  Docs d(texts);
  const std::string stem = (fs::path(g.scratch) / ("c64_bake_" + tag + "_" + std::to_string(ProcessId()))).string();
  return SW(semb_bake_to_path(e, d.docs.data(), d.docs.size(), stem.data(), stem.size()));
}
int32_t InterimBatchCall(SembInterimEncoder* e, const std::vector<std::vector<int32_t>>& docs) {
  const size_t h = Hidden(e);
  std::vector<const int32_t*> p;
  std::vector<size_t> l;
  for (const auto& d : docs) { p.push_back(d.data()); l.push_back(d.size()); }
  std::vector<float> rows(docs.size() * h);
  size_t req = 0, failed = 0;
  SembWaPoolStatus dq = kSembOk;
  const char* name = nullptr;
  return SW(semb_interim_encode_batch_ps_n(e, p.data(), l.data(), docs.size(), 0, rows.data(), rows.size() * 4,
                                           &req, &failed, &dq, &name, nullptr, 0, nullptr));
}
int32_t WitnessCall(size_t positions, size_t budget) {
  std::vector<int32_t> ids = Ids(positions);
  ids.push_back(kPairAppended);
  std::vector<int8_t> codes(ids.size() * kSembWitnessMaxHidden);
  std::vector<int64_t> m(ids.size()), e(ids.size());
  size_t hidden = 0;
  return SW(semb_encode_document_for_witness(g.model.c_str(), ids.data(), ids.size(), budget, codes.data(),
                                             m.data(), e.data(), &hidden));
}
bool WitnessFollow(size_t positions, size_t budget) { return WitnessCall(positions, budget) == kSembEncodeOk; }

// The growth driver's setup: a fresh handle warmed by a 6-position encode.
void WarmEnc(Ctx& c, uint32_t mc) {
  c.enc = OpenEnc(mc);
  if (c.enc) EncodeVec(c.enc, Text(6));
}

// P, the slot's bytes per position, read from the fixture through the interim
// geometry (the public handle has no geometry reader). Cached per process; the
// first read happens in the warm-up cycle, before the live-count baseline.
uint64_t PBytes() {
  static uint64_t p = 0;
  if (p == 0) {
    SembInterimEncoder* e = OpenInterim();
    if (e) {
      SembInterimGeometry gm{};
      gm.struct_size = sizeof(gm);
      if (semb_interim_encoder_geometry(e, &gm) == kSembInterimOk) {
        p = uint64_t{gm.num_hidden_layers} * gm.num_key_value_heads * gm.head_dim * 2;
      }
      semb_interim_encoder_close(e);
    }
  }
  return p;
}

// The batch drivers at T = 2 (TE-416 F2 (ii)): "a record either already holds
// P * C and does not grow, or grows from 0". A cold record that grows in an
// armed run keeps its buffer (U2-9 item 3), which is +1 on the live count by
// design, and which record a batch worker takes is not deterministic. So every
// record is warmed before the swept call, to C = 1,024 (a 1,000-position
// document; 1,000 is not a power of two, so no other allocation of the call
// has P * 1,024 bytes), above every swept batch document's C = 64: no armed
// batch then grows a record, and (c)'s per-call equality holds exactly. The
// warm-up counts the growths it causes and repeats until `records` records
// have grown; a warm-up that cannot reach them fails the setup, which the
// driver then reports red (a null handle), never green.
constexpr size_t kWarmPositions = 1000;
constexpr uint64_t kWarmC = 1024;
bool WarmAllRecords(const std::function<void()>& batch_of_two, uint64_t records) {
  hook::watch_hits.store(0);
  hook::watch_size.store(static_cast<size_t>(PBytes() * kWarmC));
  for (int i = 0; i < 50 && hook::watch_hits.load() < records; ++i) batch_of_two();
  const uint64_t hits = hook::watch_hits.load();
  hook::watch_size.store(0);
  if (hits != records) {
    std::printf("SETUP-FAIL warm-up grew %llu of %llu records to C=%llu\n", static_cast<unsigned long long>(hits),
                static_cast<unsigned long long>(records), static_cast<unsigned long long>(kWarmC));
    std::fflush(stdout);
    return false;
  }
  return true;
}

bool BuildDriver(const std::string& row, const std::string& drv, uint32_t mc, Driver* d) {
  const std::string L = Text(4097), G = Text(512);
  // ---- leaves: one call, K must be 0 ----
  if (drv == "call") {
    if (row == "semb_status_name") { d->call = [](Ctx&) { return SW(semb_status_name(SEMB_OK)) ? 0 : 1; }; }
    else if (row == "semb_adapter_self_id") { d->call = [](Ctx&) { return SW(semb_adapter_self_id()) ? 0 : 1; }; }
    else if (row == "semb_ps1_version_label") { d->call = [](Ctx&) { return SW(semb_ps1_version_label()) ? 0 : 1; }; }
    else if (row == "semb_ps_n_version_label") { d->call = [](Ctx&) { return SW(semb_ps_n_version_label()) ? 0 : 1; }; }
    else if (row == "semb_library_build_generation") {
      d->call = [](Ctx&) { char t[32]; return SWV(semb_library_build_generation(t)); };
    } else if (row == "semb_seam_serialize_document") {
      d->call = [](Ctx&) {
        int8_t codes[8] = {1, 2, 3, 4, 5, 6, 7, 8};
        int64_t m[1] = {1}, e[1] = {0};
        uint8_t buf[64];
        size_t len = 0;
        return static_cast<int32_t>(SW(semb_seam_serialize_document(codes, m, e, 1, 8, buf, sizeof(buf), &len)));
      };
    } else if (row == "semb_wa_pooled_spread") {
      d->call = [](Ctx&) {
        int64_t e[3] = {0, 1, 5};
        int64_t s = 0;
        return static_cast<int32_t>(SW(semb_wa_pooled_spread(e, 3, &s)));
      };
    } else if (row == "semb_interim_encoder_close") {
      d->setup = [](Ctx& c) { c.ienc = OpenInterim(); };
      d->call = [](Ctx& c) { SWV(semb_interim_encoder_close(c.ienc)); c.ienc = nullptr; return 0; };
      d->fresh_per_k = true;
    } else {
      return false;
    }
    d->follow = [](Ctx&) { return true; };
    return true;
  }

  // ---- semb_status rows ----
  if (row == "semb_encoder_open" && drv == "short") {
    d->call = [mc](Ctx& c) {
      semb_config cfg{};
      cfg.struct_size = sizeof(cfg);
      cfg.model_path = g.model.data(); cfg.model_path_len = g.model.size();
      cfg.tokenizer_path = g.tokenizer.data(); cfg.tokenizer_path_len = g.tokenizer.size();
      cfg.max_concurrency = mc;
      return static_cast<int32_t>(SW(semb_encoder_open(&cfg, &c.out_enc)));
    };
    d->follow = [mc](Ctx&) {
      semb_encoder e = OpenEnc(mc);
      semb_status s = SEMB_OK;
      const bool ok = e && EncodeVec(e, kShort, &s) == RefVec(kShort) && s == SEMB_OK;
      return e && semb_encoder_close(e) == SEMB_OK && ok;
    };
    return true;
  }
  if (row == "semb_encoder_close" && drv == "short") {
    d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); };
    d->call = [](Ctx& c) {
      const semb_status s = SW(semb_encoder_close(c.enc));
      if (s == SEMB_OK) c.enc = nullptr;
      return static_cast<int32_t>(s);
    };
    d->follow = [](Ctx& c) { return c.enc == nullptr || EncFollow(c); };
    d->fresh_per_k = true;
    return true;
  }
  if (row == "semb_encoder_dims" && drv == "short") {
    d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); };
    d->call = [](Ctx& c) { uint32_t dims = 0; return static_cast<int32_t>(SW(semb_encoder_dims(c.enc, &dims))); };
    d->follow = EncFollow;
    return true;
  }
  if (row == "semb_encode") {
    if (drv == "short") {
      d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); };
      d->call = [](Ctx& c) { semb_status s; EncodeVec(c.enc, kShort, &s); return static_cast<int32_t>(s); };
    } else if (drv == "growth") {
      d->setup = [](Ctx& c) { WarmEnc(c, 1); };
      d->call = [G](Ctx& c) { semb_status s; EncodeVec(c.enc, G, &s); return static_cast<int32_t>(s); };
      d->fresh_per_k = d->growth = true;
    } else if (drv == "long") {
      d->setup = [](Ctx& c) { c.enc = OpenEnc(1); };
      d->call = [L](Ctx& c) { semb_status s; EncodeVec(c.enc, L, &s); return static_cast<int32_t>(s); };
      d->follow = [L](Ctx& c) { return EncFollowText(c, L); };
      return true;
    } else {
      return false;
    }
    d->follow = EncFollow;
    return true;
  }
  if (row == "semb_encode_batch" || row == "semb_bake_to_path") {
    const bool bake = row == "semb_bake_to_path";
    auto run = [bake, row](semb_encoder e, const std::vector<std::string>& t) {
      return bake ? BakeCall(e, t, "x") : BatchCall(e, t);
    };
    // At T = 2 every record is warmed first (WarmAllRecords, above).
    auto open_warm = [](Ctx& c, uint32_t m) {
      c.enc = OpenEnc(m);
      if (c.enc && m >= 2 &&
          !WarmAllRecords([&c] { BatchCall(c.enc, {Text(kWarmPositions), Text(kWarmPositions)}); }, m)) {
        semb_encoder_close(c.enc);
        c.enc = nullptr;
      }
    };
    d->follow = EncFollow;
    if (drv == "short") {
      d->setup = [mc, open_warm](Ctx& c) { open_warm(c, mc); };
      d->call = [run](Ctx& c) { return run(c.enc, {kShort, "another short one"}); };
    } else if (drv == "batch_mc2") {
      // Documents of one C, at max_concurrency 2 (TE-416 F2 (ii)).
      d->setup = [open_warm](Ctx& c) { open_warm(c, 2); };
      d->call = [run](Ctx& c) { return run(c.enc, {Text(40), Text(41), Text(42), Text(43)}); };
    } else if (drv == "growth") {
      d->setup = [](Ctx& c) { WarmEnc(c, 1); };
      d->call = [run, G](Ctx& c) { return run(c.enc, {G}); };
      d->fresh_per_k = d->growth = true;
    } else if (drv == "long") {
      d->setup = [](Ctx& c) { c.enc = OpenEnc(1); };
      d->call = [run, L](Ctx& c) { return run(c.enc, {L}); };
      d->follow = [L](Ctx& c) { return EncFollowText(c, L); };
    } else {
      return false;
    }
    return true;
  }
  if (row == "semb_bank_open" && drv == "short") {
    d->setup = [](Ctx&) { BankStem(); };
    d->call = [](Ctx& c) {
      const std::string s = BankStem();
      return static_cast<int32_t>(SW(semb_bank_open(s.data(), s.size(), &c.out_bank)));
    };
    d->follow = [](Ctx&) {
      Ctx t;
      t.bank = OpenBank();
      const bool ok = BankFollow(t);
      return Closes(t) && ok;
    };
    return true;
  }
  if (row == "semb_bank_close" && drv == "short") {
    d->setup = [](Ctx& c) { c.bank = OpenBank(); };
    d->call = [](Ctx& c) {
      const semb_status s = SW(semb_bank_close(c.bank));
      if (s == SEMB_OK) c.bank = nullptr;
      return static_cast<int32_t>(s);
    };
    d->follow = [](Ctx& c) { return c.bank == nullptr || BankFollow(c); };
    d->fresh_per_k = true;
    return true;
  }
  if (row == "semb_query_open" && drv == "short") {
    d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); c.bank = OpenBank(); };
    d->call = [](Ctx& c) { return static_cast<int32_t>(SW(semb_query_open(c.enc, c.bank, &c.out_query))); };
    d->follow = [](Ctx& c) {
      semb_query q = nullptr;
      if (semb_query_open(c.enc, c.bank, &q) != SEMB_OK) return false;
      Ctx t;
      t.enc = c.enc;
      t.query = q;
      const bool ok = QueryFollow(t);
      return semb_query_close(q) == SEMB_OK && ok;
    };
    d->fresh_per_k = true;
    return true;
  }
  if (row == "semb_query_encode") {
    uint32_t qmc = mc;
    std::string text = kShort;
    if (drv == "truncated_query") text = Text(5200);
    else if (drv == "growth") text = G;
    else if (drv == "long") text = L;
    else if (drv != "short") return false;
    if (drv == "growth" || drv == "long") qmc = 1;
    const bool growth = drv == "growth";
    d->setup = [qmc, growth](Ctx& c) {
      c.enc = OpenEnc(qmc);
      c.bank = OpenBank();
      if (c.enc && c.bank) semb_query_open(c.enc, c.bank, &c.query);
      if (growth && c.query) {
        uint32_t dims = 0;
        semb_encoder_dims(c.enc, &dims);
        QueryVec(c.query, Text(6), dims);
      }
    };
    d->call = [text](Ctx& c) {
      uint32_t dims = 0;
      semb_encoder_dims(c.enc, &dims);
      semb_status s;
      QueryVec(c.query, text, dims, &s);
      return static_cast<int32_t>(s);
    };
    // The long and truncated queries (C > 4,096) follow up with their own
    // text, as the long drivers do (EncFollowText).
    if (drv == "long" || drv == "truncated_query") {
      d->follow = [text](Ctx& c) { return QueryFollowText(c, text); };
    } else {
      d->follow = QueryFollow;
    }
    d->fresh_per_k = d->growth = growth;
    return true;
  }
  if (row == "semb_query_close" && drv == "short") {
    d->setup = [mc](Ctx& c) {
      c.enc = OpenEnc(mc);
      c.bank = OpenBank();
      if (c.enc && c.bank) semb_query_open(c.enc, c.bank, &c.query);
    };
    d->call = [](Ctx& c) {
      const semb_status s = SW(semb_query_close(c.query));
      if (s == SEMB_OK) c.query = nullptr;
      return static_cast<int32_t>(s);
    };
    d->follow = [](Ctx& c) { return c.query == nullptr || QueryFollow(c); };
    d->fresh_per_k = true;
    return true;
  }
  if (row == "semb_fingerprint_of" && drv == "short") {
    d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); };
    d->call = [](Ctx& c) {
      semb_fingerprint fp{};
      fp.struct_size = sizeof(fp);
      return static_cast<int32_t>(SW(semb_fingerprint_of(c.enc, &fp)));
    };
    d->follow = EncFollow;
    return true;
  }
  if ((row == "semb_wb_digest" || row == "semb_wq_digest") && drv == "short") {
    const bool wb = row == "semb_wb_digest";
    d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); };
    d->call = [wb](Ctx& c) {
      uint8_t dg[32];
      return static_cast<int32_t>(wb ? SW(semb_wb_digest(c.enc, dg)) : SW(semb_wq_digest(c.enc, dg)));
    };
    d->follow = EncFollow;
    return true;
  }
  if (row == "semb_bank_acquire_query" && drv == "short") {
    d->setup = [](Ctx& c) {
      c.bank = OpenBank();
      int64_t n = 0, dims = 0;
      if (c.bank) semb_bank_debug_state(c.bank, c.fp, &n, &dims);
    };
    d->call = [](Ctx& c) {
      const semb_status s = SW(semb_bank_acquire_query(c.bank, c.fp));
      if (s == SEMB_OK) c.acquired = true;
      return static_cast<int32_t>(s);
    };
    d->follow = BankFollow;
    d->fresh_per_k = true;
    return true;
  }
  if (row == "semb_bank_release_query" && drv == "short") {
    d->setup = [](Ctx& c) {
      c.bank = OpenBank();
      int64_t n = 0, dims = 0;
      if (c.bank) semb_bank_debug_state(c.bank, c.fp, &n, &dims);
      if (c.bank) c.acquired = semb_bank_acquire_query(c.bank, c.fp) == SEMB_OK;
    };
    d->call = [](Ctx& c) {
      const semb_status s = SW(semb_bank_release_query(c.bank));
      if (s == SEMB_OK) c.acquired = false;
      return static_cast<int32_t>(s);
    };
    d->follow = BankFollow;
    d->fresh_per_k = true;
    return true;
  }
  if ((row == "semb_bank_debug_state" || row == "semb_bank_ranked_state") && drv == "short") {
    const bool dbg = row == "semb_bank_debug_state";
    d->setup = [](Ctx& c) { c.bank = OpenBank(); };
    d->call = [dbg](Ctx& c) {
      if (dbg) {
        uint8_t fp[32];
        int64_t n = 0, dims = 0;
        return static_cast<int32_t>(SW(semb_bank_debug_state(c.bank, fp, &n, &dims)));
      }
      semb_bank_ranked_view v{};
      return static_cast<int32_t>(SW(semb_bank_ranked_state(c.bank, &v)));
    };
    d->follow = BankFollow;
    return true;
  }
  if (row == "semb_wa_digest" && drv == "short") {
    d->call = [](Ctx&) { uint8_t dg[32]; return static_cast<int32_t>(SW(semb_wa_digest(dg))); };
    d->follow = [](Ctx&) { uint8_t dg[32]; return semb_wa_digest(dg) == SEMB_OK; };
    return true;
  }

  // ---- SembInterimStatus rows ----
  if (row == "semb_interim_encoder_open" && drv == "short") {
    d->call = [](Ctx& c) {
      const char* name = nullptr;
      return static_cast<int32_t>(SW(semb_interim_encoder_open(g.model.c_str(), kPairAppended, &c.out_ienc, &name)));
    };
    d->follow = [](Ctx&) { Ctx t; t.ienc = OpenInterim(); const bool ok = InterimFollow(t); Closes(t); return ok; };
    return true;
  }
  if (row == "semb_interim_encoder_open_from_memory" && drv == "short") {
    static std::vector<uint8_t> bytes;
    if (bytes.empty()) bytes = ReadAll(g.model);
    d->call = [mc](Ctx& c) {
      const char* name = nullptr;
      return static_cast<int32_t>(SW(semb_interim_encoder_open_from_memory(bytes.data(), bytes.size(), kPairAppended,
                                                                          mc, &c.out_ienc, &name)));
    };
    d->follow = [mc](Ctx&) {
      Ctx t;
      const char* name = nullptr;
      semb_interim_encoder_open_from_memory(bytes.data(), bytes.size(), kPairAppended, mc, &t.ienc, &name);
      const bool ok = InterimFollow(t);
      Closes(t);
      return ok;
    };
    return true;
  }
  if (row == "semb_interim_encoder_geometry" && drv == "short") {
    d->setup = [](Ctx& c) { c.ienc = OpenInterim(); };
    d->call = [](Ctx& c) {
      SembInterimGeometry gm{};
      gm.struct_size = sizeof(gm);
      return static_cast<int32_t>(SW(semb_interim_encoder_geometry(c.ienc, &gm)));
    };
    d->follow = InterimFollow;
    return true;
  }
  if (row == "semb_interim_encode_seam") {
    size_t positions = 6, budget = 0;
    SembForwardLeg leg = kSembForwardLegChunkBatched;
    if (drv == "per_token") leg = kSembForwardLegPerToken;
    else if (drv == "two_chunk") { positions = 200; budget = 100; }
    else if (drv == "growth") positions = 512;
    else if (drv == "long") positions = 4097;
    else if (drv != "short") return false;
    const bool growth = drv == "growth";
    d->setup = [growth](Ctx& c) {
      c.ienc = OpenInterim();
      if (growth && c.ienc) Seam(c.ienc, Ids(6), 0, kSembForwardLegChunkBatched);
    };
    d->call = [positions, budget, leg](Ctx& c) {
      return static_cast<int32_t>(Seam(c.ienc, Ids(positions), budget, leg).st);
    };
    d->follow = drv == "long" ? InterimFollowLong : InterimFollow;
    d->fresh_per_k = d->growth = growth;
    return true;
  }
  if (row == "semb_interim_ps_n_select" && drv == "short") {
    d->setup = [](Ctx& c) {
      c.ienc = OpenInterim();
      if (!c.ienc) return;
      const SeamRef s = Seam(c.ienc, Ids(6), 0, kSembForwardLegChunkBatched);
      c.codes = s.codes; c.m = s.m; c.e = s.e; c.n = s.m.size();
    };
    d->call = [](Ctx& c) {
      std::vector<int8_t> out(Hidden(c.ienc));
      int64_t m = 0, e = 0;
      const char* name = nullptr;
      return static_cast<int32_t>(SW(semb_interim_ps_n_select(c.ienc, c.codes.data(), c.m.data(), c.e.data(), c.n,
                                                              c.n - 1, out.data(), &m, &e, &name)));
    };
    d->follow = InterimFollow;
    return true;
  }
  if (row == "semb_interim_encode_ps_n") {
    size_t positions = 6;
    if (drv == "growth") positions = 512;
    else if (drv != "short") return false;
    const bool growth = drv == "growth";
    d->setup = [growth](Ctx& c) {
      c.ienc = OpenInterim();
      if (growth && c.ienc) Seam(c.ienc, Ids(6), 0, kSembForwardLegChunkBatched);
    };
    d->call = [positions](Ctx& c) {
      const std::vector<int32_t> ids = Ids(positions);
      std::vector<float> v(Hidden(c.ienc));
      size_t req = 0;
      SembWaPoolStatus dq = kSembOk;
      const char* name = nullptr;
      return static_cast<int32_t>(SW(semb_interim_encode_ps_n(c.ienc, ids.data(), ids.size(), 0, v.data(),
                                                              v.size() * 4, &req, &dq, &name)));
    };
    d->follow = InterimFollow;
    d->fresh_per_k = d->growth = growth;
    return true;
  }
  if (row == "semb_interim_encode_batch_ps_n") {
    static std::vector<uint8_t> bytes;
    if (bytes.empty()) bytes = ReadAll(g.model);
    uint32_t imc = 1;
    std::vector<std::vector<int32_t>> docs;
    if (drv == "short") { imc = mc; docs = {Ids(6), Ids(9)}; }
    else if (drv == "batch_mc2") { imc = 2; docs = {Ids(40), Ids(41), Ids(42), Ids(43)}; }
    else if (drv == "growth") docs = {Ids(512)};
    else if (drv == "long") docs = {Ids(4097)};
    else return false;
    const bool growth = drv == "growth";
    d->setup = [imc, growth](Ctx& c) {
      const char* name = nullptr;
      semb_interim_encoder_open_from_memory(bytes.data(), bytes.size(), kPairAppended, imc, &c.ienc, &name);
      if (growth && c.ienc) InterimBatchCall(c.ienc, {Ids(6)});
      // At T = 2 every record is warmed first (WarmAllRecords, above).
      if (!growth && imc >= 2 && c.ienc &&
          !WarmAllRecords([&c] { InterimBatchCall(c.ienc, {Ids(kWarmPositions), Ids(kWarmPositions)}); }, imc)) {
        semb_interim_encoder_close(c.ienc);
        c.ienc = nullptr;
      }
    };
    d->call = [docs](Ctx& c) { return InterimBatchCall(c.ienc, docs); };
    d->follow = drv == "long" ? InterimFollowLong : InterimFollow;
    d->fresh_per_k = d->growth = growth;
    return true;
  }

  if (row == "semb_interim_release_workspaces" && drv == "short") {
    // U2-9 item 2's end-of-open release verb (U2-10 Builds item 6). The
    // handle holds a grown buffer when the release runs, so the call has one
    // to release.
    static std::vector<uint8_t> bytes;
    if (bytes.empty()) bytes = ReadAll(g.model);
    d->setup = [mc](Ctx& c) {
      const char* name = nullptr;
      semb_interim_encoder_open_from_memory(bytes.data(), bytes.size(), kPairAppended, mc, &c.ienc, &name);
      if (c.ienc) Seam(c.ienc, Ids(6), 0, kSembForwardLegChunkBatched);
    };
    d->call = [](Ctx& c) { return static_cast<int32_t>(SW(semb_interim_release_workspaces(c.ienc))); };
    d->follow = InterimFollow;
    return true;
  }

  // ---- U2-7's three (U2-10 Builds item 6) ----
  if (row == "semb_encoder_open_memory" && drv == "short") {
    // The memory open runs semb_encoder_open's internal open (U2-7 item 1),
    // its witness included, on owned copies of the caller's spans.
    static std::vector<uint8_t> model_bytes, tok_bytes;
    if (model_bytes.empty()) { model_bytes = ReadAll(g.model); tok_bytes = ReadAll(g.tokenizer); }
    auto mem_cfg = [](uint32_t m) {
      semb_memory_config cfg{};
      cfg.struct_size = sizeof(cfg);
      cfg.model_bytes = model_bytes.data();
      cfg.model_len = model_bytes.size();
      cfg.tokenizer_bytes = tok_bytes.data();
      cfg.tokenizer_len = tok_bytes.size();
      cfg.max_concurrency = m;
      return cfg;
    };
    d->call = [mc, mem_cfg](Ctx& c) {
      const semb_memory_config cfg = mem_cfg(mc);
      return static_cast<int32_t>(SW(semb_encoder_open_memory(&cfg, &c.out_enc)));
    };
    // Follow-up: a fresh memory open encodes the path open's reference bytes.
    d->follow = [mc, mem_cfg](Ctx&) {
      const semb_memory_config cfg = mem_cfg(mc);
      semb_encoder e = nullptr;
      if (semb_encoder_open_memory(&cfg, &e) != SEMB_OK || !e) return false;
      semb_status s = SEMB_OK;
      const bool ok = EncodeVec(e, kShort, &s) == RefVec(kShort) && s == SEMB_OK;
      return semb_encoder_close(e) == SEMB_OK && ok;
    };
    return true;
  }
  if (row == "semb_encode_query") {
    // One composition, two wrappers (U2-7 item 2): the query form reaches
    // what semb_query_encode reaches, so it takes the same drivers when the
    // table lists them -- short, a query truncated at context_cap - 1, the
    // growth driver and the long driver.
    uint32_t qmc = mc;
    std::string text = kShort;
    if (drv == "truncated_query") text = Text(5200);
    else if (drv == "growth") text = G;
    else if (drv == "long") text = L;
    else if (drv != "short") return false;
    if (drv == "growth" || drv == "long") qmc = 1;
    const bool growth = drv == "growth";
    d->setup = [qmc, growth](Ctx& c) {
      c.enc = OpenEnc(qmc);
      if (growth && c.enc) EncodeQueryVec(c.enc, Text(6));
    };
    d->call = [text](Ctx& c) { semb_status s; EncodeQueryVec(c.enc, text, &s); return static_cast<int32_t>(s); };
    // The long and truncated queries (C > 4,096) follow up with their own
    // text, as the long drivers do (EncFollowText).
    if (drv == "long" || drv == "truncated_query") {
      d->follow = [text](Ctx& c) { return EncQueryFollowText(c, text); };
    } else {
      d->follow = [](Ctx& c) { return EncQueryFollowText(c, kShort); };
    }
    d->fresh_per_k = d->growth = growth;
    return true;
  }
  if (row == "semb_interim_query_token_count" && drv == "short") {
    // R17's count over the composed query, on the public handle (U2-7 item 6).
    d->setup = [mc](Ctx& c) { c.enc = OpenEnc(mc); };
    d->call = [](Ctx& c) {
      int64_t n = -1;
      return static_cast<int32_t>(SW(semb_interim_query_token_count(c.enc, kShort.data(), kShort.size(), &n)));
    };
    // Follow-up: the same count unarmed equals a fresh handle's, and the
    // handle still encodes its reference bytes.
    d->follow = [](Ctx& c) {
      static int64_t ref = -2;
      if (ref == -2) {
        semb_encoder f = OpenEnc(1);
        ref = -3;
        if (f && semb_interim_query_token_count(f, kShort.data(), kShort.size(), &ref) != kSembInterimOk) ref = -3;
        if (f) semb_encoder_close(f);
      }
      int64_t n = -1;
      return c.enc && ref >= 0 &&
             semb_interim_query_token_count(c.enc, kShort.data(), kShort.size(), &n) == kSembInterimOk &&
             n == ref && EncFollow(c);
    };
    return true;
  }

  // ---- SembEncodeStatus: the witness verb (stateless) ----
  if (row == "semb_encode_document_for_witness") {
    size_t positions = 6, budget = 0;
    if (drv == "two_chunk") { positions = 200; budget = 100; }
    else if (drv == "growth") positions = 512;
    else if (drv == "long") positions = 4097;
    else if (drv != "short") return false;
    d->call = [positions, budget](Ctx&) { return WitnessCall(positions, budget); };
    d->follow = [positions, budget](Ctx&) { return WitnessFollow(positions, budget); };
    return true;
  }

  // ---- SembWaPoolStatus rows (stateless) ----
  if (row == "semb_wa_pool_run" && drv == "short") {
    d->call = [](Ctx&) {
      const size_t n = 6, h = 8;
      std::vector<int8_t> codes(n * h);
      for (size_t i = 0; i < codes.size(); ++i) codes[i] = static_cast<int8_t>(i % 17 - 8);
      std::vector<int64_t> m(n, 3), e(n, -4);
      std::vector<float> out(h);
      return static_cast<int32_t>(SW(semb_wa_pool_run(codes.data(), m.data(), e.data(), n, h, out.data())));
    };
    d->follow = [d](Ctx& c) { return d->call(c) == kSembOk; };
    return true;
  }
  if (row == "semb_ps_n_dequantize" && drv == "short") {
    d->call = [](Ctx&) {
      int8_t codes[8] = {1, -2, 3, -4, 5, -6, 7, -8};
      float out[8];
      return static_cast<int32_t>(SW(semb_ps_n_dequantize(codes, 5, -3, 8, out)));
    };
    d->follow = [](Ctx&) {
      int8_t codes[8] = {1, -2, 3, -4, 5, -6, 7, -8};
      float out[8];
      return semb_ps_n_dequantize(codes, 5, -3, 8, out) == kSembOk;
    };
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// The sweep (one arm, from k0, in a child process).
// ---------------------------------------------------------------------------
#if defined(_WIN32)
// The Windows child's stdout is the parent's pipe (binary mode, set at the
// child's start); every protocol line is flushed as it is written, so a
// child that terminates leaves every line it finished in the pipe.
void Line(const std::string& s) {
  const std::string l = s + "\n";
  std::fwrite(l.data(), 1, l.size(), stdout);
  std::fflush(stdout);
}
#else
int g_out_fd = 1;
void Line(const std::string& s) {
  const std::string l = s + "\n";
  (void)!write(g_out_fd, l.data(), l.size());
}
#endif

struct Counted {
  uint64_t k = 0;
  int64_t live_after_warm = 0;
  double setup_s = 0, call_s = 0, follow_s = 0, close_s = 0;
};
double Now() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

// Warm-up (one open-and-close cycle) then the counting run.
Counted WarmAndCount(Driver& d) {
  Counted r;
  {
    Ctx c;
    if (d.setup) d.setup(c);
    d.call(c);
    d.follow(c);
    Closes(c);
  }
  r.live_after_warm = hook::live.load();
  Ctx c;
  double t = Now();
  if (d.setup) d.setup(c);
  r.setup_s = Now() - t;
  hook::pending_k.store(0);
  hook::window.store(0);
  hook::in_call.store(true);
  t = Now();
  d.call(c);
  r.call_s = Now() - t;
  hook::in_call.store(false);
  r.k = hook::window.load();
  t = Now();
  d.follow(c);
  r.follow_s = Now() - t;
  t = Now();
  Closes(c);
  r.close_s = Now() - t;
  return r;
}

// Per-k watchdog (seconds): a call or follow-up that stalls (a gate or a slot
// never given back makes the next waiter wait forever) ends the child, which
// the parent reports as TERMINATED at that k -- red, not a hang. POSIX:
// alarm(), so SIGALRM ends it. Windows has no alarm(): one watchdog thread,
// started with CreateThread before the warm-up (so it allocates nothing
// through the hooked operator new, and nothing it does is counted), polls the
// armed deadline and ends the process with kWatchdogExitCode.
unsigned g_watchdog_s = 0;
#if defined(_WIN32)
constexpr UINT kWatchdogExitCode = 0x8E;  // 128 + SIGALRM's 14, by analogy
std::atomic<unsigned long long> g_deadline_ms{0};  // GetTickCount64 value; 0 = disarmed
DWORD WINAPI WatchdogThread(LPVOID) {
  for (;;) {
    const unsigned long long d = g_deadline_ms.load();
    if (d != 0 && GetTickCount64() > d) TerminateProcess(GetCurrentProcess(), kWatchdogExitCode);
    Sleep(100);
  }
}
void StartWatchdog() {
  const HANDLE t = CreateThread(nullptr, 0, WatchdogThread, nullptr, 0, nullptr);
  if (t) CloseHandle(t);
}
void ArmWatchdog(unsigned s) { g_deadline_ms.store(s ? GetTickCount64() + 1000ull * s : 0ull); }
#else
void ArmWatchdog(unsigned s) { alarm(s); }
#endif

void RunArm(Driver& d, int arm, uint64_t K, uint64_t k0, int64_t live_after_warm, int32_t want) {
  Ctx c;
  bool open = false;
  for (uint64_t k = k0; k <= K; k = (k == K || k + g.k_stride <= K) ? k + g.k_stride : K) {
    if (!open || d.fresh_per_k) {
      if (d.setup) d.setup(c);
      open = true;
    }
    Line("BEGIN " + std::to_string(arm) + " k=" + std::to_string(k));
    if (g_watchdog_s) ArmWatchdog(g_watchdog_s);
    const int64_t live_before = hook::live.load();
    hook::fired.store(0);
    hook::mode.store(arm);
    hook::pending_k.store(k);
    hook::in_call.store(true);
    int32_t status = -1000;
    bool escaped = false;
    try {
      status = d.call(c);
    } catch (...) {
      escaped = true;
    }
    hook::in_call.store(false);
    hook::pending_k.store(0);
    hook::Disarm();
    const int fired = hook::fired.load();
    const int64_t leak = hook::live.load() - live_before;
    const bool follow = d.follow(c);
    bool close_ok = true;
    int64_t leak_after_close = 0;
    if (d.fresh_per_k) {
      close_ok = Closes(c);
      c = Ctx{};
      leak_after_close = hook::live.load() - live_after_warm;
      open = false;
    }
    std::ostringstream o;
    o << "ARM " << arm << " k=" << k << " status=" << status << " want=" << want << " fired=" << fired
      << " escaped=" << (escaped ? 1 : 0) << " leak=" << (d.growth ? 0 : leak) << " follow=" << (follow ? 1 : 0)
      << " close=" << (close_ok ? 1 : 0) << " leak_after_close=" << leak_after_close;
    Line(o.str());
    ArmWatchdog(0);
  }
  if (open) {
    const bool close_ok = Closes(c);
    c = Ctx{};  // the driver's carried state (e.g. ps_n_select's codes, m, e) is the harness's, not a leak
    Line("CLOSES " + std::to_string(arm) + " ok=" + std::to_string(close_ok ? 1 : 0) +
         " leak_after_close=" + std::to_string(hook::live.load() - live_after_warm));
  }
}

// What one child runs, on both platforms: the warm-up and the counting run
// (K and the per-k cost), then the arm from k0, then DONE.
void ChildBody(Driver& d, bool leaf, int arm, uint64_t k0, int32_t want) {
  const Counted cnt = WarmAndCount(d);
  Line("K " + std::to_string(cnt.k));
  {
    // Per-k cost of an armed step: the call and its follow-up, plus the
    // setup and closes when the driver runs them per k.
    const double per_k = cnt.call_s + cnt.follow_s + (d.fresh_per_k ? cnt.setup_s + cnt.close_s : 0.0);
    char b[128];
    std::snprintf(b, sizeof(b), "PERK %.6f", per_k);
    Line(b);
    g_watchdog_s = static_cast<unsigned>(std::max(120.0, 30.0 * per_k));
  }
  if (!leaf && !g.count_only) RunArm(d, arm, cnt.k, k0, cnt.live_after_warm, want);
  Line("DONE");
}

// One child's reading: everything it wrote, and how it ended when it did not
// reach DONE ("signal=<n>" on POSIX, "exit=0x<code>" on Windows).
struct ChildRun {
  std::string out;
  std::string ended;
};

#if defined(_WIN32)
// Appends one argument to a Windows command line, quoted by the rules
// CommandLineToArgvW and the CRT's argv parser undo.
void AppendArg(std::wstring& cmd, const std::wstring& a) {
  cmd += L' ';
  if (!a.empty() && a.find_first_of(L" \t\n\v\"") == std::wstring::npos) {
    cmd += a;
    return;
  }
  cmd += L'"';
  for (size_t i = 0;; ++i) {
    size_t slashes = 0;
    while (i < a.size() && a[i] == L'\\') { ++i; ++slashes; }
    if (i == a.size()) { cmd.append(slashes * 2, L'\\'); break; }
    if (a[i] == L'"') { cmd.append(slashes * 2 + 1, L'\\'); cmd += L'"'; }
    else { cmd.append(slashes, L'\\'); cmd += a[i]; }
  }
  cmd += L'"';
}

// Re-launches this executable with its own command line plus the child
// arguments, stdout into a pipe, and reads it to EOF before waiting.
bool SpawnChild(int arm, uint64_t k0, ChildRun* run) {
  SECURITY_ATTRIBUTES sa{};
  sa.nLength = sizeof(sa);
  sa.bInheritHandle = TRUE;
  HANDLE rd = nullptr, wr = nullptr;
  if (!CreatePipe(&rd, &wr, &sa, 0)) return false;
  SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);  // only the write end is the child's
  HANDLE err = nullptr;
  DuplicateHandle(GetCurrentProcess(), GetStdHandle(STD_ERROR_HANDLE), GetCurrentProcess(), &err, 0, TRUE,
                  DUPLICATE_SAME_ACCESS);
  std::wstring cmd = GetCommandLineW();
  AppendArg(cmd, L"--c64-child-arm");
  AppendArg(cmd, std::to_wstring(arm));
  AppendArg(cmd, L"--c64-child-k0");
  AppendArg(cmd, std::to_wstring(k0));
  std::vector<wchar_t> buf(cmd.begin(), cmd.end());
  buf.push_back(L'\0');
  wchar_t exe[32768];
  const DWORD n = GetModuleFileNameW(nullptr, exe, 32768);
  STARTUPINFOW si{};
  si.cb = sizeof(si);
  si.dwFlags = STARTF_USESTDHANDLES;
  si.hStdInput = nullptr;
  si.hStdOutput = wr;
  si.hStdError = err ? err : wr;
  PROCESS_INFORMATION pi{};
  const BOOL ok = n != 0 && n < 32768 &&
                  CreateProcessW(exe, buf.data(), nullptr, nullptr, TRUE, 0, nullptr, nullptr, &si, &pi);
  CloseHandle(wr);
  if (err) CloseHandle(err);
  if (!ok) {
    CloseHandle(rd);
    return false;
  }
  CloseHandle(pi.hThread);
  char tmp[4096];
  DWORD got = 0;
  while (ReadFile(rd, tmp, sizeof(tmp), &got, nullptr) && got > 0) run->out.append(tmp, got);
  CloseHandle(rd);
  WaitForSingleObject(pi.hProcess, INFINITE);
  DWORD code = 0;
  GetExitCodeProcess(pi.hProcess, &code);
  CloseHandle(pi.hProcess);
  char b[32];
  std::snprintf(b, sizeof(b), "exit=0x%lX", static_cast<unsigned long>(code));
  run->ended = b;
  return true;
}

// The child's side: no error-reporting dialog or abort message box may stall
// a terminating child (the parent reads its exit code instead), and its
// stdout is binary so the parent reads LF lines.
void PrepareChild() {
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
#if defined(_MSC_VER) || defined(_UCRT)
  _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
#endif
  _setmode(_fileno(stdout), _O_BINARY);
  StartWatchdog();
}
#else
// fork()s the child, which runs ChildBody writing into a pipe and _exit()s;
// the parent reads the pipe to EOF, then waitpid()s.
bool SpawnChild(Driver& d, bool leaf, int arm, uint64_t k0, int32_t want, ChildRun* run) {
  int fds[2];
  if (pipe(fds) != 0) return false;
  const pid_t pid = fork();
  if (pid == 0) {
    close(fds[0]);
    g_out_fd = fds[1];
    ChildBody(d, leaf, arm, k0, want);
    close(fds[1]);
    _exit(0);
  }
  close(fds[1]);
  char tmp[4096];
  ssize_t r;
  while ((r = read(fds[0], tmp, sizeof(tmp))) > 0) run->out.append(tmp, static_cast<size_t>(r));
  close(fds[0]);
  int wst = 0;
  waitpid(pid, &wst, 0);
  const int sig = WIFSIGNALED(wst) ? WTERMSIG(wst) : -WEXITSTATUS(wst);
  run->ended = "signal=" + std::to_string(sig);
  return true;
}
#endif

}  // namespace

int main(int argc, char** argv) {
  bool print_expected = false;
  int child_arm = -1;  // >= 0: this process is a Windows child (--c64-child-arm)
  uint64_t child_k0 = 1;
  for (int i = 1; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&]() -> std::string { return i + 1 < argc ? argv[++i] : ""; };
    if (k == "--model") g.model = next();
    else if (k == "--tokenizer") g.tokenizer = next();
    else if (k == "--scratch") g.scratch = next();
    else if (k == "--row") g.row = next();
    else if (k == "--driver") g.driver = next();
    else if (k == "--mc") g.mc = static_cast<uint32_t>(std::stoul(next()));
    else if (k == "--k-stride") g.k_stride = std::max<uint64_t>(1, std::stoull(next()));
    else if (k == "--count-only") g.count_only = true;
    else if (k == "--print-expected") print_expected = true;
    else if (k == "--c64-child-arm") child_arm = std::stoi(next());
    else if (k == "--c64-child-k0") child_k0 = std::stoull(next());
    else if (k == "--arms") {
      g.arms.clear();
      std::stringstream ss(next());
      std::string a;
      while (std::getline(ss, a, ',')) g.arms.push_back(a == "a" ? 0 : a == "a2" ? 1 : 2);
    }
  }
  if (print_expected) {
    for (const char* r : kAllRows) {
      const Expected e = ExpectedFor(r);
      std::printf("EXPECT %s %s %s %s\n", r, e.family, e.alloc_name, e.catch_all_name);
    }
    return 0;
  }
  if (g.model.empty() || g.tokenizer.empty() || g.scratch.empty() || g.row.empty() || g.driver.empty()) {
    std::fprintf(stderr, "usage: %s --model m --tokenizer t --scratch d --row r --driver d [--mc n]\n", argv[0]);
    return 2;
  }
  fs::create_directories(g.scratch);
  Driver d;
  if (!BuildDriver(g.row, g.driver, g.mc, &d)) {
    std::printf("NO-DRIVER %s %s\n", g.row.c_str(), g.driver.c_str());
    return 3;
  }
  const Expected ex = ExpectedFor(g.row);
  const bool leaf = std::string(ex.family) == "leaf";
  std::fflush(stdout);
#if defined(_WIN32)
  if (child_arm >= 0) {
    // The Windows child: exactly the forked child's work, then exit 0.
    PrepareChild();
    ChildBody(d, leaf, child_arm, child_k0, child_arm == 2 ? ex.catch_all : ex.alloc);
    std::fflush(stdout);
    return 0;
  }
#else
  if (child_arm >= 0) {
    std::fprintf(stderr, "--c64-child-arm is the Windows child's; POSIX children are forked\n");
    return 2;
  }
#endif

  // K is counted in a child too, so the parent never runs product code.
  uint64_t K = 0;
  for (const int arm : leaf ? std::vector<int>{0} : g.arms) {
    const int32_t want = arm == 2 ? ex.catch_all : ex.alloc;
    uint64_t k0 = 1;
    uint64_t pass = 0, fail = 0, first_fail_k = 0;
    std::string first_fail;
    bool counted = false;
    for (int attempt = 0; attempt < 100000; ++attempt) {
      ChildRun child;
#if defined(_WIN32)
      if (!SpawnChild(arm, k0, &child)) return 4;
#else
      if (!SpawnChild(d, leaf, arm, k0, want, &child)) return 4;
#endif
      std::istringstream lines(child.out);
      std::string line;
      uint64_t last_begin = 0;
      bool done = false;
      while (std::getline(lines, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.rfind("K ", 0) == 0) {
          const uint64_t kk = std::stoull(line.substr(2));
          if (!counted) {
            K = kk;
            counted = true;
            std::printf("K %s %s %u %llu\n", g.row.c_str(), g.driver.c_str(), g.mc,
                        static_cast<unsigned long long>(K));
          }
        } else if (line.rfind("PERK ", 0) == 0) {
          if (g.count_only) std::printf("%s\n", line.c_str());
        } else if (line.rfind("BEGIN ", 0) == 0) {
          last_begin = std::stoull(line.substr(line.find("k=") + 2));
        } else if (line.rfind("ARM ", 0) == 0) {
          std::printf("%s\n", line.c_str());
          auto field = [&](const char* key) {
            const auto p = line.find(std::string(" ") + key + "=");
            return std::stoll(line.substr(p + std::strlen(key) + 2));
          };
          const bool ok = field("status") == want && field("escaped") == 0 && field("leak") == 0 &&
                          field("follow") == 1 && field("close") == 1 && field("leak_after_close") == 0;
          if (field("fired") == 0) {
            // The k-th allocation did not happen on this run (K varies with scheduling): not graded.
          } else if (ok) {
            ++pass;
          } else {
            ++fail;
            if (!first_fail_k) { first_fail_k = static_cast<uint64_t>(field("k")); first_fail = line; }
          }
        } else if (line.rfind("CLOSES ", 0) == 0) {
          std::printf("%s\n", line.c_str());
          if (line.find("ok=1") == std::string::npos || line.find("leak_after_close=0") == std::string::npos) {
            ++fail;
            if (!first_fail_k) { first_fail_k = K; first_fail = line; }
          }
        } else if (line == "DONE") {
          done = true;
        }
#if defined(_WIN32)
        else if (!line.empty()) {
          // Anything else the child printed (a SETUP-FAIL line): a forked
          // child's printf reaches the parent's stdout directly; this one's
          // reached the pipe, so it is passed on.
          std::printf("%s\n", line.c_str());
        }
#endif
      }
      if (done) break;
      std::printf("TERMINATED %d k=%llu %s\n", arm, static_cast<unsigned long long>(last_begin), child.ended.c_str());
      ++fail;
      if (!first_fail_k) {
        std::string how = child.ended;
        std::replace(how.begin(), how.end(), '=', ' ');
        first_fail_k = last_begin;
        first_fail = "terminated " + how;
      }
      if (last_begin == 0) break;  // died before any armed call: nothing to resume
      k0 = last_begin + g.k_stride > K ? (last_begin < K ? K : K + 1) : last_begin + g.k_stride;
      if (k0 > K) break;
    }
    if (g.count_only) {
      std::printf("COUNT %s %s %u K=%llu\n", g.row.c_str(), g.driver.c_str(), g.mc, static_cast<unsigned long long>(K));
      return 0;
    }
    if (leaf) {
      std::printf("SUMMARY %s %s %u leaf K=%llu %s\n", g.row.c_str(), g.driver.c_str(), g.mc,
                  static_cast<unsigned long long>(K), K == 0 ? "pass" : "fail");
    } else {
      std::printf("SUMMARY %s %s %u %s K=%llu pass=%llu fail=%llu first_fail_k=%llu first_fail=%s\n",
                  g.row.c_str(), g.driver.c_str(), g.mc, arm == 0 ? "a" : arm == 1 ? "a2" : "b",
                  static_cast<unsigned long long>(K), static_cast<unsigned long long>(pass),
                  static_cast<unsigned long long>(fail), static_cast<unsigned long long>(first_fail_k),
                  first_fail.c_str());
    }
    std::fflush(stdout);
  }
  return 0;
}
