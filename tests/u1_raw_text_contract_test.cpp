// tests/u1_raw_text_contract_test.cpp -- TE-92 (U1, the first frozen public
// raw-text vertical slice), RE-ENTERED at TE-94 (the planner's D-SLM6314
// resolution, P-1..P-9): the CONTRACT cells of sec 3.1's five frozen verbs
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1, "The C ABI, frozen"; the
// frozen properties 1-7; sec 8 C4's mechanism edges; the planner record
// `Claude/Fable/te92-d-slm6314-planner-resolution-2026-09-04.md` sec 5.6-5.8's
// precedence tables), executed against a model + tokenizer pair handed on
// the command line:
//
//   --model <.sslm> --tokenizer <.sslm> --dims <expected>
//   [--context-cap <n>]              enables the at-cap / over-cap cells (K-12)
//   [--other-model <.sslm>]          a model whose vocab_size is SMALLER than the
//                                    tokenizer's id range (mismatch cell K-06a)
//   [--other-tokenizer <.sslm>]      a tokenizer whose id range EXCEEDS --model's
//                                    vocab_size (mismatch cell K-06d)
//   [--absent-end-token-tokenizer <.sslm>]
//                                    a tokenizer artifact that loads and fits the
//                                    join but whose special table has no
//                                    <|endoftext|> (absent-template cell K-06f)
//   [--scratch-dir <dir>]            where this test writes its truncated and
//                                    zero-length artifact copies (K-05d/e)
//   [--workspace-precedence]         K-06i on the driver's tiny synthetic fixtures
//   [--legacy-append-id <id>]        DIAGNOSTIC ONLY, honoured only when compiled
//                                    with SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER
//
// The driver (tests/u1_raw_text_cells_check.py) runs this once on the
// synthetic pair (tests/fixtures/regenerate_tokenizer_pair_fixture.py: hidden
// 32, vocab 384, context_cap 64, <|endoftext|> = 262) -- the MECHANISM run --
// and, when the real Qwen3-Embedding-0.6B artifact and its converter-emitted
// tokenizer are configured, once more on the real pair (dims 1024,
// <|endoftext|> = 151643) -- the PRODUCT run. Every cell below is stated with
// the sec 3.1 item, sec 8 cell, or resolution ruling it realizes. Statuses
// are resolved BY NAME through semb_status_name (tests/semb_public_abi_contract.h),
// so a behavioural cell is red for its own reason and never because an
// ordinal moved; the ordinal pin is its own cell (K-07i).
//
// RED at main@496d036 for exactly the accepted product deltas (each cell's
// own comment names its ruling): every open refuses SEMB_STRUCT_SIZE_MISMATCH
// because the product's semb_config still carries the retired appended-id
// member (P-1) -- the driver's --diag-legacy-layout pass attributes each
// cell's own red past that.
//
// THE ALLOCATOR HOOK (K-15b, K-17). This translation unit replaces the global
// operator new/delete. The replacement is the allocator the statically
// linked library actually calls, so (a) a std::bad_alloc thrown from it is
// the instrument's real data path for SEMB_ALLOCATION_FAILED -- the cell the
// planner routed to this seat (sec 10.4) with the instruction not to accept
// a Linux-overcommit-dependent guess -- and (b) a thread parked inside it is
// PROVABLY inside the library call it entered, which is the deterministic
// "in flight" observation the close-during-flight cell needs: no sleep, no
// timing, no repeated attempts. Both policies are armed immediately before
// the call under test and disarm themselves on their one firing.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <vector>

#include "semb_public_abi_contract.h"

// ---------------------------------------------------------------------------
// The global allocator hook.
// ---------------------------------------------------------------------------
namespace alloc_hook {

// Policy 1: the first allocation request of at least `g_fail_min_bytes`
// bytes throws std::bad_alloc, then the policy disarms. 0 = disarmed.
std::atomic<std::size_t> g_fail_min_bytes{0};
std::atomic<std::uint64_t> g_fail_fired{0};
std::atomic<std::size_t> g_fail_fired_size{0};

// Fail-safe for K-06i's million-slot synthetic calls only. This bounds total
// requested bytes before malloc if a changed pool layout evades Policy 1.
// A safety firing is always a test failure, independent of the open status.
std::atomic<size_t> g_safety_remaining{0};
std::atomic<bool> g_safety_armed{false};
std::atomic<bool> g_safety_fired{false};

// Policy 2: the first allocation on thread `g_park_thread` parks that thread
// until Release(); the policy disarms on entry so the parked thread's later
// allocations proceed. Main observes `parked` under the mutex.
std::atomic<bool> g_park_armed{false};
std::thread::id g_park_thread;
std::mutex g_park_mutex;
std::condition_variable g_park_cv;
bool g_parked = false;
bool g_release = false;

void ArmFail(std::size_t min_bytes) {
  g_fail_min_bytes.store(min_bytes, std::memory_order_release);
}
void DisarmFail() { g_fail_min_bytes.store(0, std::memory_order_release); }

void ArmPark(std::thread::id target) {
  std::lock_guard<std::mutex> lock(g_park_mutex);
  g_parked = false;
  g_release = false;
  g_park_thread = target;
  g_park_armed.store(true, std::memory_order_release);
}

// Waits until the target thread is parked or `give_up` elapses. The timeout
// only converts a never-allocating library call into a NAMED failure rather
// than a hang; it never decides a PASS.
bool WaitParked(std::chrono::seconds give_up) {
  std::unique_lock<std::mutex> lock(g_park_mutex);
  return g_park_cv.wait_for(lock, give_up, [] { return g_parked; });
}

void Release() {
  {
    std::lock_guard<std::mutex> lock(g_park_mutex);
    g_release = true;
    g_park_armed.store(false, std::memory_order_release);
  }
  g_park_cv.notify_all();
}

void* Allocate(std::size_t n) {
  std::size_t min = g_fail_min_bytes.load(std::memory_order_acquire);
  if (min != 0 && n >= min &&
      g_fail_min_bytes.compare_exchange_strong(min, 0, std::memory_order_acq_rel)) {
    g_fail_fired.fetch_add(1, std::memory_order_acq_rel);
    g_fail_fired_size.store(n, std::memory_order_release);
    throw std::bad_alloc();
  }
  if (g_park_armed.load(std::memory_order_acquire) && std::this_thread::get_id() == g_park_thread) {
    std::unique_lock<std::mutex> lock(g_park_mutex);
    if (g_park_armed.load(std::memory_order_acquire)) {
      g_park_armed.store(false, std::memory_order_release);
      g_parked = true;
      g_park_cv.notify_all();
      g_park_cv.wait(lock, [] { return g_release; });
    }
  }
  if (g_safety_armed.load()) {
    size_t remaining = g_safety_remaining.load();
    for (;;) {
      if (n > remaining) {
        g_safety_fired.store(true);
        throw std::bad_alloc();
      }
      if (g_safety_remaining.compare_exchange_weak(remaining, remaining - n)) break;
    }
  }
  void* p = std::malloc(n == 0 ? 1 : n);
  if (!p) throw std::bad_alloc();
  return p;
}

}  // namespace alloc_hook

void* operator new(std::size_t n) { return alloc_hook::Allocate(n); }
void* operator new[](std::size_t n) { return alloc_hook::Allocate(n); }
void* operator new(std::size_t n, const std::nothrow_t&) noexcept {
  try { return alloc_hook::Allocate(n); } catch (...) { return nullptr; }
}
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept {
  try { return alloc_hook::Allocate(n); } catch (...) { return nullptr; }
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { std::free(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { std::free(p); }

namespace {

int g_failures = 0;
int g_cells = 0;
constexpr size_t kRequiredSentinel = static_cast<size_t>(0xC5C5C5C5u);

void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}

void Missing(const std::string& cell, const std::string& why) {
  ++g_cells;
  std::printf("[MISSING PREREQUISITE] %s: %s\n", cell.c_str(), why.c_str());
  std::fflush(stdout);
}

void Observed(const std::string& what) {
  std::printf("[OBSERVED] %s\n", what.c_str());
  std::fflush(stdout);
}

const char* Name(semb_status s) {
  const char* n = semb_status_name(s);
  return n ? n : "<NULL>";
}

// Every status this slice can reach, resolved by name, or -1 (a -1 never
// equals a real status, so a missing name fails every cell that expects it).
struct Statuses {
  int32_t ok, null_argument, struct_size_mismatch, invalid_handle, handle_in_use, concurrency_exceeded,
      buffer_too_small, misaligned_buffer, input_empty, invalid_utf8, context_cap_exceeded,
      artifact_unreadable, engine_refused, tokenizer_model_mismatch, template_token_absent,
      allocation_failed;
};

Statuses ResolveStatuses() {
  using semb_contract::StatusByName;
  Statuses s{};
  s.ok = StatusByName("SEMB_OK");
  s.null_argument = StatusByName("SEMB_NULL_ARGUMENT");
  s.struct_size_mismatch = StatusByName("SEMB_STRUCT_SIZE_MISMATCH");
  s.invalid_handle = StatusByName("SEMB_INVALID_HANDLE");
  s.handle_in_use = StatusByName("SEMB_HANDLE_IN_USE");
  s.concurrency_exceeded = StatusByName("SEMB_CONCURRENCY_EXCEEDED");
  s.buffer_too_small = StatusByName("SEMB_BUFFER_TOO_SMALL");
  s.misaligned_buffer = StatusByName("SEMB_MISALIGNED_BUFFER");
  s.input_empty = StatusByName("SEMB_INPUT_EMPTY");
  s.invalid_utf8 = StatusByName("SEMB_INVALID_UTF8");
  s.context_cap_exceeded = StatusByName("SEMB_CONTEXT_CAP_EXCEEDED");
  s.artifact_unreadable = StatusByName("SEMB_ARTIFACT_UNREADABLE");
  s.engine_refused = StatusByName("SEMB_ENGINE_REFUSED");
  s.tokenizer_model_mismatch = StatusByName("SEMB_TOKENIZER_MODEL_MISMATCH");
  s.template_token_absent = StatusByName("SEMB_TEMPLATE_TOKEN_ABSENT");
  s.allocation_failed = StatusByName("SEMB_ALLOCATION_FAILED");
  return s;
}

int32_t g_legacy_append_id = -1;  // diagnostic-only, see the header comment

semb_config MakeConfig(const std::string& model, const std::string& tokenizer, uint32_t max_concurrency = 1) {
  semb_config cfg{};
  cfg.struct_size = sizeof(semb_config);
  cfg.model_path = model.c_str();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tokenizer.c_str();
  cfg.tokenizer_path_len = tokenizer.size();
#ifdef SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER
  cfg.appended_token_id = g_legacy_append_id;
#endif
  cfg.max_concurrency = max_concurrency;
  return cfg;
}

// A sentinel-filled, 16-byte-aligned float buffer with slack on both ends so
// "nothing written" and "nothing written past the required size" are both
// checkable byte for byte.
struct SentinelBuffer {
  static constexpr uint8_t kSentinel = 0xA5;
  std::vector<float> storage;  // over-allocated; Data() is 16-byte aligned
  size_t capacity_bytes = 0;
  explicit SentinelBuffer(size_t bytes) : capacity_bytes(bytes) {
    storage.assign((bytes + 64) / sizeof(float) + 16, 0.0f);
    std::memset(storage.data(), kSentinel, storage.size() * sizeof(float));
  }
  float* Data() {
    auto p = reinterpret_cast<uintptr_t>(storage.data());
    p = (p + 15) & ~static_cast<uintptr_t>(15);
    return reinterpret_cast<float*>(p);
  }
  bool Untouched(size_t bytes_from_start) {
    const auto* b = reinterpret_cast<const uint8_t*>(Data());
    for (size_t i = 0; i < bytes_from_start; ++i)
      if (b[i] != kSentinel) return false;
    return true;
  }
  bool UntouchedFrom(size_t offset, size_t count) {
    const auto* b = reinterpret_cast<const uint8_t*>(Data());
    for (size_t i = offset; i < offset + count; ++i)
      if (b[i] != kSentinel) return false;
    return true;
  }
};

semb_fingerprint MakeFingerprint() {
  semb_fingerprint fp{};
  fp.struct_size = sizeof(semb_fingerprint);
  std::memset(fp.digest, 0xC3, sizeof(fp.digest));
  return fp;
}

bool FingerprintUntouched(const semb_fingerprint& fp) {
  for (uint8_t b : fp.digest)
    if (b != 0xC3) return false;
  return fp.struct_size == sizeof(semb_fingerprint);
}

std::string Hex(const uint8_t* p, size_t n) {
  static const char* d = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; ++i) {
    s += d[p[i] >> 4];
    s += d[p[i] & 15];
  }
  return s;
}

std::string Untouched(bool u) { return u ? " untouched" : " WRITTEN"; }
std::string OutState(semb_encoder enc) { return enc ? " *out NOT cleared" : " *out NULL"; }

// The garbage-cookie value K-02d/K-09k/K-13i hand in: a non-NULL value no
// open ever published (cookies are monotonic from 1; this is far past any
// count a process reaches).
semb_encoder GarbageHandle() {
  return reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x7FFFFFFFFFFF0001ull));
}

// The sentinel a cell puts in *out before an open, so "cleared to NULL" is
// distinguishable from "never written".
semb_encoder OutSentinel() { return reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1)); }

struct Args {
  std::string model, tokenizer, other_model, other_tokenizer, absent_end_token_tokenizer, scratch_dir;
  uint32_t dims = 0;
  size_t context_cap = 0;
  bool workspace_precedence = false;
  bool print_vector = false;
  std::string print_text;
};

Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&](std::string* dst) {
      if (i + 1 >= argc) { std::fprintf(stderr, "missing value for %s\n", k.c_str()); std::exit(2); }
      *dst = argv[++i];
    };
    std::string v;
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--other-model") next(&a.other_model);
    else if (k == "--other-tokenizer") next(&a.other_tokenizer);
    else if (k == "--absent-end-token-tokenizer") next(&a.absent_end_token_tokenizer);
    else if (k == "--scratch-dir") next(&a.scratch_dir);
    else if (k == "--print-vector-hex") { next(&a.print_text); a.print_vector = true; }
    else if (k == "--workspace-precedence") a.workspace_precedence = true;
    else if (k == "--legacy-append-id") { next(&v); g_legacy_append_id = std::atoi(v.c_str()); }
    else if (k == "--dims") { next(&v); a.dims = static_cast<uint32_t>(std::atoi(v.c_str())); }
    else if (k == "--context-cap") { next(&v); a.context_cap = static_cast<size_t>(std::atoll(v.c_str())); }
    else { std::fprintf(stderr, "unknown argument %s\n", k.c_str()); std::exit(2); }
  }
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0) {
    std::fprintf(stderr, "usage: --model <.sslm> --tokenizer <.sslm> --dims <n> ...\n");
    std::exit(2);
  }
#ifndef SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER
  if (g_legacy_append_id >= 0) {
    std::fprintf(stderr, "note: --legacy-append-id is ignored -- this build carries the contract's six-member "
                         "semb_config (no appended-token member)\n");
  }
#endif
  return a;
}

// Opens the pair or fails the named cell; returns nullptr on failure.
semb_encoder OpenPair(const Args& a, const Statuses& st, const char* cell, uint32_t max_concurrency = 1) {
  const semb_config cfg = MakeConfig(a.model, a.tokenizer, max_concurrency);
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != st.ok || !enc) {
    Verdict(false, cell, std::string("open refused: ") + Name(s));
    return nullptr;
  }
  return enc;
}

std::vector<char> ReadAll(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  return std::vector<char>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

bool WriteAll(const std::string& path, const char* data, size_t n) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  if (n) out.write(data, static_cast<std::streamsize>(n));
  out.close();
  return static_cast<bool>(out);
}

const char kDoc[] = "hello world";

// One encode into a fresh buffer; the vector bytes on SEMB_OK.
struct EncodeResult {
  semb_status status = 0;
  std::vector<float> vector;
  size_t required = kRequiredSentinel;
};

EncodeResult EncodeDoc(semb_encoder enc, const char* text, size_t len, uint32_t dims) {
  EncodeResult r;
  r.vector.assign(dims, 0.0f);
  semb_fingerprint fp = MakeFingerprint();
  r.status = semb_encode(enc, text, len, r.vector.data(), r.vector.size() * sizeof(float), &r.required, &fp);
  return r;
}

bool SameBytes(const std::vector<float>& a, const std::vector<float>& b) {
  return a.size() == b.size() && std::memcmp(a.data(), b.data(), a.size() * sizeof(float)) == 0;
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  const Statuses st = ResolveStatuses();
  const size_t need = a.dims * sizeof(float);

  // TE-110: standalone production-byte output; all existing cells below are unchanged.
  if (a.print_vector) {
    auto enc = OpenPair(a, st, "K-15f production open");
    if (!enc) return 1;
    SentinelBuffer output(need);
    auto fp = MakeFingerprint();
    size_t required = 0;
    auto status = semb_encode(enc, a.print_text.data(), a.print_text.size(),
                              output.Data(), need, &required, &fp);
    auto closed = semb_encoder_close(enc);
    if (status != st.ok || required != need || closed != st.ok) {
      std::fprintf(stderr, "K-15f production encode=%s close=%s\n", Name(status), Name(closed));
      return 1;
    }
    std::printf("VECTOR_HEX %s\n", Hex(reinterpret_cast<const uint8_t*>(output.Data()), need).c_str());
    return 0;
  }

  // ---- K-07 status names: names, ordinals, static storage, the retired name (P-4, P-5) ----
  {
    std::string missing, found;
    for (size_t i = 0; i < semb_contract::kStatusCount; ++i) {
      const int32_t v = semb_contract::StatusByName(semb_contract::kStatusTable[i].name);
      if (v < 0) missing += std::string(" ") + semb_contract::kStatusTable[i].name;
      else found += std::string(" ") + semb_contract::kStatusTable[i].name + "=" + std::to_string(v);
    }
    Verdict(missing.empty(), "K-07a every status name this slice reaches is returned by semb_status_name",
            missing.empty() ? found : "missing:" + missing + "; found:" + found);
    Verdict(st.ok == SEMB_OK, "K-07b SEMB_OK is value 0", "SEMB_OK resolved to " + std::to_string(st.ok));
    std::string absent;
    int present = 0;
    for (size_t i = 0; i < semb_contract::kPlanStatusNameCount; ++i) {
      if (semb_contract::StatusByName(semb_contract::kPlanStatusNames[i]) < 0)
        absent += std::string(" ") + semb_contract::kPlanStatusNames[i];
      else ++present;
    }
    Observed("K-07c later-verb vocabulary outside this slice (P-5: appended when its verb lands): " +
             std::to_string(present) + " present, absent:" + (absent.empty() ? " none" : absent));
    bool distinct = true;
    std::vector<int32_t> values;
    for (size_t i = 0; i < semb_contract::kStatusCount; ++i)
      values.push_back(semb_contract::StatusByName(semb_contract::kStatusTable[i].name));
    std::sort(values.begin(), values.end());
    for (size_t i = 1; i < values.size(); ++i)
      if (values[i] == values[i - 1] && values[i] >= 0) distinct = false;
    Verdict(distinct, "K-07d recognized status values are distinct", "values sorted, no duplicate >= 0");
    const char* n_neg = semb_status_name(-1);
    const char* n_big = semb_status_name(INT32_MAX);
    const char* n_scan = semb_status_name(semb_contract::kStatusScanLimit);
    Verdict(n_neg && n_big && n_scan, "K-07e semb_status_name is never NULL, including for non-member values",
            std::string("name(-1)=") + (n_neg ? n_neg : "<NULL>") + " name(INT32_MAX)=" + (n_big ? n_big : "<NULL>"));
    bool nonmember_distinct = true;
    if (n_neg) {
      for (size_t i = 0; i < semb_contract::kStatusCount; ++i)
        if (std::strcmp(n_neg, semb_contract::kStatusTable[i].name) == 0) nonmember_distinct = false;
    }
    Verdict(nonmember_distinct, "K-07f a non-member value's name is not a member's name", n_neg ? n_neg : "<NULL>");
    const char* p1 = semb_status_name(st.ok);
    const char* p2 = semb_status_name(st.ok);
    const char* q1 = semb_status_name(st.null_argument);
    Verdict(p1 && p1 == p2 && q1 && q1 != p1,
            "K-07g the returned pointer is stable across calls (static storage) and per-status",
            std::string("name(SEMB_OK) ") + (p1 == p2 ? "same pointer" : "DIFFERENT pointers"));
    std::string copy_before = p1 ? p1 : "";
    {
      semb_encoder enc = OpenPair(a, st, "K-07h (setup)");
      if (enc) {
        SentinelBuffer buf(need);
        size_t req = 0;
        semb_fingerprint fp = MakeFingerprint();
        (void)semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), buf.capacity_bytes, &req, &fp);
        (void)semb_encoder_close(enc);
      }
    }
    const char* p3 = semb_status_name(st.ok);
    Verdict(p3 == p1 && p3 && copy_before == p3,
            "K-07h the pointer outlives an encoder handle's whole life (open, encode, close)",
            std::string("before=") + copy_before + " after=" + (p3 ? p3 : "<NULL>"));
    // P-5: the ordinal pin. Every listed value carries exactly its listed name.
    std::string wrong;
    for (size_t i = 0; i < semb_contract::kStatusCount; ++i) {
      const auto& e = semb_contract::kStatusTable[i];
      const char* n = semb_status_name(e.value);
      if (!n || std::strcmp(n, e.name) != 0)
        wrong += std::string(" ") + std::to_string(e.value) + "=" + (n ? n : "<NULL>") + "(want " + e.name + ")";
    }
    Verdict(wrong.empty(), "K-07i every ordinal 0-17 names exactly the contract's status in the contract's order (P-5)",
            wrong.empty() ? "18 of 18 ordinals agree" : "disagree:" + wrong);
    const char* n_next = semb_status_name(SEMB_STATUS_NEXT_FREE);
    Verdict(n_next && std::strcmp(n_next, semb_contract::kUnknownStatusName) == 0 && n_neg &&
                std::strcmp(n_neg, semb_contract::kUnknownStatusName) == 0,
            "K-07j the sentinel SEMB_STATUS_NEXT_FREE (18) and every non-member value name the fixed string SEMB_UNKNOWN (P-5)",
            std::string("name(18)=") + (n_next ? n_next : "<NULL>") + " name(-1)=" + (n_neg ? n_neg : "<NULL>"));
    std::string retired_present;
    for (size_t i = 0; i < semb_contract::kRetiredStatusNameCount; ++i)
      if (semb_contract::StatusByName(semb_contract::kRetiredStatusNames[i]) >= 0)
        retired_present += std::string(" ") + semb_contract::kRetiredStatusNames[i];
    Verdict(retired_present.empty(), "K-07k no retired status name is reachable (P-4: SEMB_INVALID_ARGUMENT removed)",
            retired_present.empty() ? "none present" : "present:" + retired_present);
  }

  // ---- K-01 open / close round trip; K-02 dims ------------------------------------------------
  {
    const semb_config cfg = MakeConfig(a.model, a.tokenizer);
    semb_encoder enc = nullptr;
    const semb_status s = semb_encoder_open(&cfg, &enc);
    Verdict(s == st.ok && enc != nullptr, "K-01a semb_encoder_open on the pair returns SEMB_OK and a non-NULL handle",
            std::string(Name(s)) + (enc ? ", handle non-NULL" : ", handle NULL"));
    if (enc) {
      uint32_t dims = 0;
      const semb_status sd = semb_encoder_dims(enc, &dims);
      Verdict(sd == st.ok && dims == a.dims, "K-02a semb_encoder_dims reports the artifact's hidden_size",
              std::string(Name(sd)) + " dims=" + std::to_string(dims) + " expected=" + std::to_string(a.dims));
      uint32_t sentinel = 0xDEADBEEF;
      const semb_status sn = semb_encoder_dims(nullptr, &sentinel);
      Verdict(sn == st.null_argument && sentinel == 0xDEADBEEF,
              "K-02b semb_encoder_dims(NULL handle) -> SEMB_NULL_ARGUMENT, out untouched (P-7)", Name(sn));
      const semb_status so = semb_encoder_dims(enc, nullptr);
      Verdict(so == st.null_argument, "K-02c semb_encoder_dims(enc, NULL) -> SEMB_NULL_ARGUMENT", Name(so));
      sentinel = 0xDEADBEEF;
      const semb_status sg = semb_encoder_dims(GarbageHandle(), &sentinel);
      Verdict(sg == st.invalid_handle && sentinel == 0xDEADBEEF,
              "K-02d semb_encoder_dims on a non-NULL value that names no live handle -> SEMB_INVALID_HANDLE, out untouched (P-7)",
              Name(sg));
      const semb_status sc = semb_encoder_close(enc);
      Verdict(sc == st.ok, "K-01b semb_encoder_close returns SEMB_OK", Name(sc));
    }
  }

  // ---- K-03 / K-04 open: NULL pointers, the span rule, struct_size, and their precedence ------
  {
    const std::string nowhere_t = a.tokenizer + ".does-not-exist";
    semb_config cfg = MakeConfig(a.model, a.tokenizer);
    semb_encoder enc = OutSentinel();
    semb_status s = semb_encoder_open(nullptr, &enc);
    Verdict(s == st.null_argument && enc == nullptr,
            "K-03a open(NULL cfg, &out) -> SEMB_NULL_ARGUMENT AND *out cleared to NULL (P-6 step 1)",
            std::string(Name(s)) + OutState(enc));
    s = semb_encoder_open(&cfg, nullptr);
    Verdict(s == st.null_argument, "K-03b open(cfg, NULL out) -> SEMB_NULL_ARGUMENT", Name(s));
    semb_config c2 = cfg; c2.model_path = nullptr; enc = OutSentinel();
    s = semb_encoder_open(&c2, &enc);
    Verdict(s == st.null_argument && enc == nullptr,
            "K-03c open with model_path NULL and model_path_len > 0 -> SEMB_NULL_ARGUMENT, *out = NULL (P-8)",
            std::string(Name(s)) + OutState(enc));
    semb_config c3 = cfg; c3.tokenizer_path = nullptr; enc = OutSentinel();
    s = semb_encoder_open(&c3, &enc);
    Verdict(s == st.null_argument && enc == nullptr,
            "K-03d open with tokenizer_path NULL and tokenizer_path_len > 0 -> SEMB_NULL_ARGUMENT, *out = NULL (P-8)",
            std::string(Name(s)) + OutState(enc));
    semb_config c4 = cfg; c4.model_path = nullptr; c4.model_path_len = 0; enc = OutSentinel();
    s = semb_encoder_open(&c4, &enc);
    const bool e1 = s == st.artifact_unreadable && enc == nullptr;
    const std::string obs1 = std::string(Name(s)) + OutState(enc);
    semb_config c5 = cfg; c5.tokenizer_path = nullptr; c5.tokenizer_path_len = 0; enc = OutSentinel();
    s = semb_encoder_open(&c5, &enc);
    Verdict(e1 && s == st.artifact_unreadable && enc == nullptr,
            "K-03e a (NULL, 0) path span is the empty path, an unreadable artifact -> SEMB_ARTIFACT_UNREADABLE, *out = NULL (P-8; model then tokenizer)",
            "model: " + obs1 + "; tokenizer: " + Name(s) + OutState(enc));
    semb_config c6 = cfg; c6.struct_size = sizeof(semb_config) + 4; c6.model_path = nullptr; enc = OutSentinel();
    s = semb_encoder_open(&c6, &enc);
    Verdict(s == st.struct_size_mismatch && enc == nullptr,
            "K-03f struct_size wrong AND model_path NULL -> SEMB_STRUCT_SIZE_MISMATCH (P-6: step 2 precedes step 3)",
            std::string(Name(s)) + OutState(enc));
    semb_config c7 = MakeConfig(a.model, nowhere_t); c7.model_path = nullptr; enc = OutSentinel();
    s = semb_encoder_open(&c7, &enc);
    Verdict(s == st.null_argument && enc == nullptr,
            "K-03g model_path NULL (len > 0) AND a tokenizer path that does not exist -> SEMB_NULL_ARGUMENT (P-6: step 3 precedes step 4)",
            std::string(Name(s)) + OutState(enc));
    std::string nul_path = a.tokenizer;
    nul_path.push_back('\0');
    nul_path += "x";
    semb_config c8 = cfg; c8.tokenizer_path = nul_path.data(); c8.tokenizer_path_len = nul_path.size(); enc = OutSentinel();
    s = semb_encoder_open(&c8, &enc);
    Verdict(s == st.artifact_unreadable && enc == nullptr,
            "K-03h a path span carrying an embedded NUL -> SEMB_ARTIFACT_UNREADABLE, *out = NULL (P-4/P-8)",
            std::string(Name(s)) + OutState(enc));
    const uint32_t sizes[] = {0u, static_cast<uint32_t>(sizeof(semb_config) - 4), static_cast<uint32_t>(sizeof(semb_config) + 4)};
    for (uint32_t sz : sizes) {
      semb_config c9 = cfg; c9.struct_size = sz; enc = OutSentinel();
      s = semb_encoder_open(&c9, &enc);
      Verdict(s == st.struct_size_mismatch && enc == nullptr,
              "K-04 open with struct_size=" + std::to_string(sz) + " -> SEMB_STRUCT_SIZE_MISMATCH, *out = NULL (item 6)",
              std::string(Name(s)) + OutState(enc));
    }
  }

  // ---- K-05 the artifacts are a trust boundary: refusals at open, named for what was found ----
  {
    const std::string nowhere_m = a.model + ".does-not-exist";
    const std::string nowhere_t = a.tokenizer + ".does-not-exist";
    semb_encoder enc = OutSentinel();
    semb_config c1 = MakeConfig(nowhere_m, a.tokenizer);
    semb_status s = semb_encoder_open(&c1, &enc);
    Verdict(s == st.artifact_unreadable && enc == nullptr,
            "K-05a a model path that does not exist -> SEMB_ARTIFACT_UNREADABLE, *out = NULL (P-4: the engine was never called)",
            std::string(Name(s)) + OutState(enc));
    enc = OutSentinel();
    semb_config c2 = MakeConfig(a.model, nowhere_t);
    s = semb_encoder_open(&c2, &enc);
    Verdict(s == st.artifact_unreadable && enc == nullptr,
            "K-05b a tokenizer path that does not exist -> SEMB_ARTIFACT_UNREADABLE, *out = NULL (P-4)",
            std::string(Name(s)) + OutState(enc));
    enc = OutSentinel();
    semb_config c3 = MakeConfig(a.model, a.model);  // the model handed as the tokenizer
    s = semb_encoder_open(&c3, &enc);
    Verdict(s == st.engine_refused && enc == nullptr,
            "K-05c the model artifact handed as the tokenizer (no Tokenizer section: the engine's loader refuses) -> SEMB_ENGINE_REFUSED, *out = NULL",
            std::string(Name(s)) + OutState(enc));
    if (!a.scratch_dir.empty()) {
      const std::vector<char> bytes = ReadAll(a.tokenizer);
      const size_t keep = bytes.size() > 4096 ? bytes.size() - 4096 : bytes.size() / 2;
      const std::string truncated = a.scratch_dir + "/u1_contract_tokenizer.truncated.sslm";
      const std::string empty_t = a.scratch_dir + "/u1_contract_tokenizer.empty.sslm";
      const std::string empty_m = a.scratch_dir + "/u1_contract_model.empty.sslm";
      const bool wrote = WriteAll(truncated, bytes.data(), keep) && WriteAll(empty_t, nullptr, 0) &&
                         WriteAll(empty_m, nullptr, 0);
      if (!wrote) {
        Verdict(false, "K-05d/e (setup) scratch artifact copies written", "could not write under " + a.scratch_dir);
      } else {
        enc = OutSentinel();
        semb_config c4 = MakeConfig(a.model, truncated);
        s = semb_encoder_open(&c4, &enc);
        Verdict(s == st.engine_refused && enc == nullptr,
                "K-05d a truncated tokenizer artifact (the engine's own loader refuses it) -> SEMB_ENGINE_REFUSED, *out = NULL",
                std::string(Name(s)) + " (" + std::to_string(keep) + " of " + std::to_string(bytes.size()) + " bytes kept)" + OutState(enc));
        enc = OutSentinel();
        semb_config c5 = MakeConfig(a.model, empty_t);
        s = semb_encoder_open(&c5, &enc);
        const bool e1 = s == st.engine_refused && enc == nullptr;
        const std::string o1 = std::string(Name(s)) + OutState(enc);
        enc = OutSentinel();
        semb_config c6 = MakeConfig(empty_m, a.tokenizer);
        s = semb_encoder_open(&c6, &enc);
        Verdict(e1 && s == st.engine_refused && enc == nullptr,
                "K-05e a zero-length file (the OS delivered zero bytes; the engine's loader rejects them) -> SEMB_ENGINE_REFUSED, *out = NULL (tokenizer, then model)",
                "tokenizer: " + o1 + "; model: " + Name(s) + OutState(enc));
        enc = OutSentinel();
        semb_config c7 = MakeConfig(nowhere_m, truncated);
        s = semb_encoder_open(&c7, &enc);
        Verdict(s == st.engine_refused && enc == nullptr,
                "K-05g a truncated tokenizer AND a model path that does not exist -> SEMB_ENGINE_REFUSED (P-6: the tokenizer is read and opened, step 5, before the model is read, step 7)",
                std::string(Name(s)) + OutState(enc));
      }
    } else {
      Missing("K-05d truncated tokenizer artifact refused", "no --scratch-dir given");
      Missing("K-05e zero-length artifact files refused", "no --scratch-dir given");
      Missing("K-05g tokenizer-first precedence (truncated tokenizer + missing model)", "no --scratch-dir given");
    }
    if (!a.absent_end_token_tokenizer.empty()) {
      enc = OutSentinel();
      semb_config c8 = MakeConfig(nowhere_m, a.absent_end_token_tokenizer);
      s = semb_encoder_open(&c8, &enc);
      Verdict(s == st.template_token_absent && enc == nullptr,
              "K-05f a tokenizer without <|endoftext|> AND a model path that does not exist -> SEMB_TEMPLATE_TOKEN_ABSENT (P-6: step 6 precedes the model read, step 7)",
              std::string(Name(s)) + OutState(enc));
    } else {
      Missing("K-05f tokenizer-first precedence (absent end token + missing model)", "no --absent-end-token-tokenizer given");
    }
  }

  // ---- K-06 the artifact pair's join, the end-token literal, the concurrency default ---------
  {
    semb_encoder enc = OutSentinel();
    if (!a.other_model.empty()) {
      semb_config c1 = MakeConfig(a.other_model, a.tokenizer);
      const semb_status s = semb_encoder_open(&c1, &enc);
      Verdict(s == st.tokenizer_model_mismatch && enc == nullptr,
              "K-06a a tokenizer whose id range exceeds the model's vocab_size -> SEMB_TOKENIZER_MODEL_MISMATCH at open, *out = NULL (P-4)",
              std::string(Name(s)) + OutState(enc));
    } else {
      Missing("K-06a tokenizer ids exceed the model's vocab_size", "no --other-model given");
    }
    if (!a.other_tokenizer.empty()) {
      enc = OutSentinel();
      semb_config c4 = MakeConfig(a.model, a.other_tokenizer);
      const semb_status s = semb_encoder_open(&c4, &enc);
      Verdict(s == st.tokenizer_model_mismatch && enc == nullptr,
              "K-06d a foreign tokenizer artifact (id range past this model's vocab_size) -> SEMB_TOKENIZER_MODEL_MISMATCH at open, *out = NULL (P-4)",
              std::string(Name(s)) + OutState(enc));
    } else {
      Missing("K-06d foreign tokenizer artifact against this model", "no --other-tokenizer given");
    }
    if (!a.absent_end_token_tokenizer.empty()) {
      enc = OutSentinel();
      semb_config c6 = MakeConfig(a.model, a.absent_end_token_tokenizer);
      semb_status s = semb_encoder_open(&c6, &enc);
      Verdict(s == st.template_token_absent && enc == nullptr,
              "K-06f a tokenizer artifact that loads and fits the join but has no <|endoftext|> special -> SEMB_TEMPLATE_TOKEN_ABSENT, *out = NULL (P-1/P-4)",
              std::string(Name(s)) + OutState(enc));
      if (!a.other_model.empty()) {
        enc = OutSentinel();
        semb_config c7 = MakeConfig(a.other_model, a.absent_end_token_tokenizer);
        s = semb_encoder_open(&c7, &enc);
        Verdict(s == st.template_token_absent && enc == nullptr,
                "K-06g absent end token AND a join that would also fail -> SEMB_TEMPLATE_TOKEN_ABSENT (P-6: step 6 precedes the join, step 9)",
                std::string(Name(s)) + OutState(enc));
      } else {
        Missing("K-06g absent-end-token precedence over the join", "no --other-model given");
      }
    } else {
      Missing("K-06f absent <|endoftext|> special", "no --absent-end-token-tokenizer given");
      Missing("K-06g absent-end-token precedence over the join", "no --absent-end-token-tokenizer given");
    }
    {
      semb_config c8 = MakeConfig(a.model, a.tokenizer, /*max_concurrency=*/0);
      enc = nullptr;
      const semb_status s = semb_encoder_open(&c8, &enc);
      bool encoded = false;
      semb_status se = 0;
      if (s == st.ok && enc) {
        const EncodeResult r = EncodeDoc(enc, kDoc, sizeof(kDoc) - 1, a.dims);
        se = r.status;
        encoded = r.status == st.ok;
        (void)semb_encoder_close(enc);
      }
      Verdict(s == st.ok && enc && encoded,
              "K-06h max_concurrency = 0 selects the default of one workspace: open SEMB_OK, encode SEMB_OK (D-10, normalized never refused)",
              std::string("open ") + Name(s) + ", encode " + (s == st.ok ? Name(se) : "not attempted"));
    }
  }

  // ---- K-08 output capacity, required size, no partial writes, alignment (items 3-4; P-6) ----
  {
    semb_encoder enc = OpenPair(a, st, "K-08 (setup)");
    if (enc) {
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      semb_status s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, nullptr, 0, &req, &fp);
      Verdict(s == st.buffer_too_small && req == need,
              "K-08a the query form (NULL, capacity 0) -> SEMB_BUFFER_TOO_SMALL with required = dims*4",
              std::string(Name(s)) + " required=" + std::to_string(req) + " expected=" + std::to_string(need));
      Verdict(FingerprintUntouched(fp), "K-08b the query form writes no fingerprint", Hex(fp.digest, 4) + "...");
      {
        SentinelBuffer buf(need);
        req = 0;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need - 4, &req, &fp);
        Verdict(s == st.buffer_too_small && req == need && buf.Untouched(need) && FingerprintUntouched(fp),
                "K-08c capacity dims*4-4 -> SEMB_BUFFER_TOO_SMALL, required written, buffer and fingerprint untouched",
                std::string(Name(s)) + " required=" + std::to_string(req) + Untouched(buf.Untouched(need)));
      }
      {
        SentinelBuffer buf(need);
        req = 0;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
        Verdict(s == st.ok && req == need && !buf.Untouched(need),
                "K-08d capacity dims*4 exactly -> SEMB_OK, required written on success too, vector written",
                std::string(Name(s)) + " required=" + std::to_string(req));
      }
      {
        SentinelBuffer buf(need + 64);
        req = 0;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need + 64, &req, &fp);
        Verdict(s == st.ok && req == need && buf.UntouchedFrom(need, 64),
                "K-08e capacity dims*4+64 -> SEMB_OK; the 64 bytes past the required size are untouched",
                std::string(Name(s)) + " required=" + std::to_string(req) + (buf.UntouchedFrom(need, 64) ? " tail untouched" : " TAIL WRITTEN"));
      }
      {
        SentinelBuffer buf(need + 16);
        float* mis = reinterpret_cast<float*>(reinterpret_cast<uint8_t*>(buf.Data()) + 4);
        req = kRequiredSentinel;
        fp = MakeFingerprint();
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, mis, need, &req, &fp);
        Verdict(s == st.misaligned_buffer && req == kRequiredSentinel && buf.Untouched(need + 16) && FingerprintUntouched(fp),
                "K-08f a buffer 4 bytes off 16-byte alignment -> SEMB_MISALIGNED_BUFFER before any write; required untouched",
                std::string(Name(s)) + Untouched(buf.Untouched(need + 16)));
        req = kRequiredSentinel;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, mis, need - 4, &req, &fp);
        Verdict(s == st.misaligned_buffer && req == kRequiredSentinel && buf.Untouched(need + 16),
                "K-08g misaligned AND too small -> SEMB_MISALIGNED_BUFFER, required untouched (P-6: step 4 precedes step 5)",
                std::string(Name(s)) + " required " + (req == kRequiredSentinel ? "untouched" : "WRITTEN"));
      }
      {
        semb_fingerprint bad = MakeFingerprint();
        bad.struct_size = sizeof(semb_fingerprint) + 8;
        req = kRequiredSentinel;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, nullptr, 0, &req, &bad);
        Verdict(s == st.struct_size_mismatch && req == kRequiredSentinel,
                "K-08h the query form with a wrong fingerprint struct_size -> SEMB_STRUCT_SIZE_MISMATCH, required untouched (P-6: step 3 precedes step 5)",
                std::string(Name(s)) + " required " + (req == kRequiredSentinel ? "untouched" : "WRITTEN"));
      }
      (void)semb_encoder_close(enc);
    }
  }

  // ---- K-09 / K-10 / K-11 encode: NULL and malformed arguments, the span rule, empty input, UTF-8 --
  {
    semb_encoder enc = OpenPair(a, st, "K-09 (setup)");
    if (enc) {
      SentinelBuffer buf(need);
      size_t req = kRequiredSentinel;
      semb_fingerprint fp = MakeFingerprint();
      auto reset = [&] { req = kRequiredSentinel; fp = MakeFingerprint(); };
      auto clean = [&] { return req == kRequiredSentinel && buf.Untouched(need) && FingerprintUntouched(fp); };
      semb_status s = semb_encode(nullptr, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.null_argument && clean(), "K-09a encode(NULL handle) -> SEMB_NULL_ARGUMENT, nothing written (P-7)", Name(s));
      reset();
      s = semb_encode(enc, nullptr, 5, buf.Data(), need, &req, &fp);
      Verdict(s == st.null_argument && clean(), "K-09b encode((NULL, 5) text, sufficient buffer) -> SEMB_NULL_ARGUMENT, nothing written (P-8)", Name(s));
      reset();
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, nullptr, &fp);
      Verdict(s == st.null_argument && buf.Untouched(need) && FingerprintUntouched(fp),
              "K-09c encode(out_required_bytes NULL) -> SEMB_NULL_ARGUMENT, nothing written", Name(s));
      reset();
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, nullptr);
      Verdict(s == st.null_argument && req == kRequiredSentinel && buf.Untouched(need),
              "K-09d encode(out_fingerprint NULL) -> SEMB_NULL_ARGUMENT, nothing written", Name(s));
      reset();
      semb_fingerprint bad = MakeFingerprint();
      bad.struct_size = sizeof(semb_fingerprint) + 8;
      const semb_fingerprint bad_before = bad;
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &bad);
      const bool bad_untouched = bad.struct_size == bad_before.struct_size &&
          std::memcmp(bad.digest, bad_before.digest, sizeof(bad.digest)) == 0;
      Verdict(s == st.struct_size_mismatch && req == kRequiredSentinel && buf.Untouched(need) && bad_untouched,
              "K-09e a fingerprint struct_size that is not this build's -> SEMB_STRUCT_SIZE_MISMATCH, nothing written", Name(s));
      reset();
      s = semb_encode(enc, nullptr, 0, buf.Data(), need, &req, &fp);
      Verdict(s == st.input_empty && clean(),
              "K-09f encode((NULL, 0) text) is the empty span -> SEMB_INPUT_EMPTY, nothing written (P-8)",
              std::string("observed ") + Name(s));
      reset();
      s = semb_encode(enc, nullptr, 5, nullptr, 0, &req, &fp);
      Verdict(s == st.buffer_too_small && req == need && FingerprintUntouched(fp),
              "K-09g encode((NULL, 5) text, query-form buffer) -> SEMB_BUFFER_TOO_SMALL with required written (P-6: capacity, step 5, precedes the text pointer)",
              std::string(Name(s)) + " required=" + std::to_string(req));
      reset();
      s = semb_encode(enc, nullptr, 0, nullptr, 0, &req, &fp);
      Verdict(s == st.buffer_too_small && req == need && FingerprintUntouched(fp),
              "K-09h encode((NULL, 0) text, query-form buffer) -> SEMB_BUFFER_TOO_SMALL (P-6: step 5 precedes step 7)",
              std::string(Name(s)) + " required=" + std::to_string(req));
      reset();
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, nullptr, need, &req, &fp);
      Verdict(s == st.null_argument && req == kRequiredSentinel && FingerprintUntouched(fp),
              "K-09i encode(out_vector NULL with sufficient capacity) -> SEMB_NULL_ARGUMENT, required untouched (P-6 step 6)",
              std::string(Name(s)) + " required " + (req == kRequiredSentinel ? "untouched" : "WRITTEN"));
      reset();
      s = semb_encode(enc, "", 0, nullptr, need, &req, &fp);
      Verdict(s == st.null_argument && req == kRequiredSentinel,
              "K-09j encode(out_vector NULL with sufficient capacity, empty text) -> SEMB_NULL_ARGUMENT (P-6: step 6 precedes step 7)",
              Name(s));
      reset();
      s = semb_encode(GarbageHandle(), kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.invalid_handle && clean(),
              "K-09k encode on a non-NULL value that names no live handle -> SEMB_INVALID_HANDLE, nothing written (P-7)", Name(s));
      reset();
      s = semb_encode(enc, "", 0, buf.Data(), need, &req, &fp);
      Verdict(s == st.input_empty && clean(),
              "K-10a the empty string -> SEMB_INPUT_EMPTY (sec 8 C4), nothing written, required untouched", Name(s));
      reset();
      s = semb_encode(enc, " ", 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.ok && req == need, "K-10b a whitespace-only input is one token and is ACCEPTED under PS-N (D-SLM4729)", Name(s));
      const char bad1[] = {static_cast<char>(0xFF)};
      const char bad2[] = {'a', static_cast<char>(0x80), 'b'};
      const char bad3[] = {static_cast<char>(0xE4), static_cast<char>(0xBD)};
      const char bad4[] = {static_cast<char>(0xED), static_cast<char>(0xA0), static_cast<char>(0x80)};  // UTF-16 surrogate
      const char bad5[] = {static_cast<char>(0xC0), static_cast<char>(0xAF)};                            // overlong '/'
      const char bad6[] = {static_cast<char>(0xF4), static_cast<char>(0x90), static_cast<char>(0x80), static_cast<char>(0x80)};  // > U+10FFFF
      struct { const char* p; size_t n; const char* what; } bads[] = {
          {bad1, sizeof(bad1), "0xFF"}, {bad2, sizeof(bad2), "lone continuation 0x80"},
          {bad3, sizeof(bad3), "truncated 3-byte sequence"}, {bad4, sizeof(bad4), "encoded surrogate U+D800"},
          {bad5, sizeof(bad5), "overlong encoding C0 AF"}, {bad6, sizeof(bad6), "codepoint above U+10FFFF"}};
      for (const auto& b : bads) {
        SentinelBuffer buf2(need);
        req = kRequiredSentinel;
        fp = MakeFingerprint();
        s = semb_encode(enc, b.p, b.n, buf2.Data(), need, &req, &fp);
        Verdict(s == st.invalid_utf8 && req == kRequiredSentinel && buf2.Untouched(need) && FingerprintUntouched(fp),
                std::string("K-11 invalid UTF-8 (") + b.what + ") -> SEMB_INVALID_UTF8 (sec 8 C4, P-4), nothing written",
                std::string("observed ") + Name(s) + Untouched(buf2.Untouched(need)));
      }
      (void)semb_encoder_close(enc);
    }
  }

  // ---- K-12 the context cap: at cap accepted, cap+1 refused by name, UTF-8 before the cap ------
  if (a.context_cap > 0) {
    semb_encoder enc = OpenPair(a, st, "K-12 (setup)");
    if (enc) {
      // "ab" tokenizes to two single-byte tokens in the synthetic pair (m-017);
      // n content tokens + the appended token = n + 1 positions.
      std::string at_cap, over_cap;
      for (size_t i = 0; i + 1 < a.context_cap; ++i) at_cap += (i % 2 == 0 ? 'a' : 'b');   // cap-1 content -> cap positions
      for (size_t i = 0; i < a.context_cap; ++i) over_cap += (i % 2 == 0 ? 'a' : 'b');     // cap content -> cap+1 positions
      SentinelBuffer b1(need);
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      semb_status s = semb_encode(enc, at_cap.data(), at_cap.size(), b1.Data(), need, &req, &fp);
      Verdict(s == st.ok, "K-12a a document of exactly context_cap positions (content + appended token) is accepted",
              std::string(Name(s)) + " content=" + std::to_string(at_cap.size()));
      SentinelBuffer b2(need);
      req = kRequiredSentinel;
      fp = MakeFingerprint();
      s = semb_encode(enc, over_cap.data(), over_cap.size(), b2.Data(), need, &req, &fp);
      Verdict(s == st.context_cap_exceeded && req == kRequiredSentinel && b2.Untouched(need) && FingerprintUntouched(fp),
              "K-12b context_cap+1 positions -> SEMB_CONTEXT_CAP_EXCEEDED (sec 8 C4, P-4), nothing written",
              std::string("observed ") + Name(s) + Untouched(b2.Untouched(need)));
      std::string over_bad = over_cap;
      over_bad.push_back(static_cast<char>(0xFF));
      SentinelBuffer b3(need);
      req = kRequiredSentinel;
      s = semb_encode(enc, over_bad.data(), over_bad.size(), b3.Data(), need, &req, &fp);
      Verdict(s == st.invalid_utf8 && req == kRequiredSentinel && b3.Untouched(need),
              "K-12c an over-cap document that is also invalid UTF-8 -> SEMB_INVALID_UTF8 (P-6: step 8 precedes step 10)",
              std::string("observed ") + Name(s));
      (void)semb_encoder_close(enc);
    }
  } else {
    Missing("K-12 context cap edges", "no --context-cap given (the real artifact's 32,768 is not driven here)");
  }

  // ---- K-13 opaque-handle ownership (item 5; P-7) -----------------------------------------------
  {
    semb_encoder enc = OpenPair(a, st, "K-13 (setup)");
    if (enc) {
      semb_encoder copy = enc;  // a copy of the VALUE grants no second lifetime
      semb_status s = semb_encoder_close(enc);
      Verdict(s == st.ok, "K-13a first close -> SEMB_OK", Name(s));
      s = semb_encoder_close(enc);
      Verdict(s == st.invalid_handle, "K-13b double close -> SEMB_INVALID_HANDLE, never undefined", Name(s));
      s = semb_encoder_close(copy);
      Verdict(s == st.invalid_handle, "K-13c closing a copied handle value after the close -> SEMB_INVALID_HANDLE", Name(s));
      uint32_t dims = 0;
      s = semb_encoder_dims(copy, &dims);
      Verdict(s == st.invalid_handle, "K-13d dims on a closed handle -> SEMB_INVALID_HANDLE", Name(s));
      SentinelBuffer buf(need);
      size_t req = kRequiredSentinel;
      semb_fingerprint fp = MakeFingerprint();
      s = semb_encode(copy, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.invalid_handle && req == kRequiredSentinel && buf.Untouched(need) && FingerprintUntouched(fp),
              "K-13e encode on a closed handle -> SEMB_INVALID_HANDLE, nothing written", Name(s));
      semb_fingerprint bad = MakeFingerprint();
      bad.struct_size = sizeof(semb_fingerprint) + 8;
      req = kRequiredSentinel;
      s = semb_encode(copy, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &bad);
      Verdict(s == st.invalid_handle && req == kRequiredSentinel,
              "K-13j a closed handle AND a wrong fingerprint struct_size -> SEMB_INVALID_HANDLE (P-6: step 2 precedes step 3)", Name(s));
    }
    semb_status s = semb_encoder_close(nullptr);
    Verdict(s == st.null_argument, "K-13f close(NULL) -> SEMB_NULL_ARGUMENT (item 7, P-7)", Name(s));
    s = semb_encoder_close(GarbageHandle());
    Verdict(s == st.invalid_handle, "K-13i close on a non-NULL value that names no live handle -> SEMB_INVALID_HANDLE, never undefined (P-7)", Name(s));
    semb_encoder e1 = OpenPair(a, st, "K-13g (setup 1)");
    semb_encoder e2 = OpenPair(a, st, "K-13g (setup 2)");
    if (e1 && e2) {
      SentinelBuffer b2(need);
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      (void)semb_encoder_close(e1);
      s = semb_encode(e2, kDoc, sizeof(kDoc) - 1, b2.Data(), need, &req, &fp);
      Verdict(e1 != e2 && s == st.ok, "K-13g two handles are distinct; closing one leaves the other encoding", Name(s));
      (void)semb_encoder_close(e2);
    }
    semb_encoder stale = OpenPair(a, st, "K-13h (setup stale)");
    if (stale) {
      (void)semb_encoder_close(stale);
      semb_encoder replacement = OpenPair(a, st, "K-13h (setup replacement)");
      if (replacement) {
        uint32_t stale_dims = 0xC5C5C5C5u;
        const semb_status dims_status = semb_encoder_dims(stale, &stale_dims);
        const semb_status close_status = semb_encoder_close(stale);
        Verdict(replacement != stale && dims_status == st.invalid_handle && close_status == st.invalid_handle &&
                    stale_dims == 0xC5C5C5C5u,
                "K-13h reopening cannot recycle a published handle value or make the stale handle valid again (P-7: cookies are never reissued)",
                std::string("replacement ") + (replacement == stale ? "ALIASED" : "distinct") + "; dims=" + Name(dims_status) +
                    "; close=" + Name(close_status));
        (void)semb_encoder_close(replacement);
      }
    }
  }

  // ---- K-14 the fingerprint IN/OUT struct: preserved size, stable, untagged (P-2/P-3) --
  {
    semb_encoder e1 = OpenPair(a, st, "K-14 (setup 1)");
    if (e1) {
      SentinelBuffer buf(need);
      size_t req = 0;
      semb_fingerprint f1 = MakeFingerprint(), f2 = MakeFingerprint(), f3 = MakeFingerprint();
      const char other[] = "a completely different document, with more words in it";
      semb_status s1 = semb_encode(e1, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &f1);
      semb_status s2 = semb_encode(e1, other, sizeof(other) - 1, buf.Data(), need, &req, &f2);
      semb_status s3 = semb_encode(e1, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &f3);
      const bool same = std::memcmp(f1.digest, f2.digest, 32) == 0 && std::memcmp(f1.digest, f3.digest, 32) == 0;
      const bool written = !FingerprintUntouched(f1);
      Verdict(s1 == st.ok && s2 == st.ok && s3 == st.ok && same && written && f1.struct_size == sizeof(semb_fingerprint),
              "K-14a the fingerprint is written on SEMB_OK, is the HANDLE's (identical across documents), struct_size preserved (P-2)",
              std::string(Name(s1)) + " digest=" + Hex(f1.digest, 8) + "... " + (same ? "identical" : "DIFFERS across documents"));
      Verdict(std::memcmp(f1.digest, semb_contract::kRetiredProvisionalFingerprintTag,
                          sizeof(semb_contract::kRetiredProvisionalFingerprintTag)) != 0,
              "K-14b the fingerprint is the untagged five-field value: digest[0..7] != the retired provisional tag SEMBP001 (P-3)",
              "prefix=" + Hex(f1.digest, 8));
      semb_encoder e2 = OpenPair(a, st, "K-14c (setup 2)");
      if (e2) {
        semb_fingerprint f4 = MakeFingerprint();
        semb_status s4 = semb_encode(e2, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &f4);
        Verdict(s4 == st.ok && std::memcmp(f1.digest, f4.digest, 32) == 0,
                "K-14c a second handle on the same pair reports the identical fingerprint", Hex(f4.digest, 8) + "...");
        (void)semb_encoder_close(e2);
      }
      (void)semb_encoder_close(e1);
    }
  }

  // ---- K-15 concurrency and lifetime (sec 3.1's concurrency contract, D-SLM4647; sec 8 C26) ---
  {
    const char* docs[3] = {"hello world", "a second, concurrent document", "the third document has more tokens in it than the others"};
    std::vector<std::vector<float>> serial(3);
    {
      semb_encoder ref = OpenPair(a, st, "K-15 (serial reference)");
      if (ref) {
        for (int d = 0; d < 3; ++d) {
          const EncodeResult r = EncodeDoc(ref, docs[d], std::strlen(docs[d]), a.dims);
          if (r.status == st.ok) serial[d] = r.vector;
        }
        (void)semb_encoder_close(ref);
      }
    }
    const bool have_serial = !serial[0].empty() && !serial[1].empty() && !serial[2].empty();
    // K-15a: the declared bound is respected by construction (3 threads, 3
    // workspaces), so NO call may ever be refused, whatever the interleaving,
    // and every result must equal the serial bytes -- the feature oracle for
    // a shared or corrupted workspace.
    if (have_serial) {
      semb_encoder enc = OpenPair(a, st, "K-15a (setup)", /*max_concurrency=*/3);
      if (enc) {
        constexpr int kRounds = 4;
        std::atomic<int> refused{0}, mismatched{0}, other{0}, ok{0};
        std::vector<std::thread> threads;
        for (int t = 0; t < 3; ++t) {
          threads.emplace_back([&, t] {
            for (int r = 0; r < kRounds; ++r) {
              const EncodeResult res = EncodeDoc(enc, docs[t], std::strlen(docs[t]), a.dims);
              if (res.status == st.ok) {
                ++ok;
                if (!SameBytes(res.vector, serial[t])) ++mismatched;
              } else if (res.status == st.concurrency_exceeded) {
                ++refused;
              } else {
                ++other;
              }
            }
          });
        }
        for (auto& th : threads) th.join();
        Verdict(ok == 3 * kRounds && refused == 0 && mismatched == 0 && other == 0,
                "K-15a max_concurrency = 3, three threads x 4 rounds each on its own document: never SEMB_CONCURRENCY_EXCEEDED (the bound is respected by construction), every vector byte-identical to the serial run",
                "ok=" + std::to_string(ok.load()) + " refused=" + std::to_string(refused.load()) + " mismatched=" +
                    std::to_string(mismatched.load()) + " other=" + std::to_string(other.load()));
        const semb_status sc = semb_encoder_close(enc);
        Verdict(sc == st.ok, "K-15a close after every thread joined -> SEMB_OK", Name(sc));
      }
    } else {
      Verdict(false, "K-15a (serial reference) three documents encode serially", "a serial encode refused");
    }
    // K-15b: close during a PROVABLY in-flight encode. The worker's first
    // allocation inside semb_encode parks it (allocator hook, policy 2); the
    // worker allocates nothing between arming and the call, so being parked
    // is being inside the call. Close must refuse SEMB_HANDLE_IN_USE and free
    // nothing; released, the encode completes with the serial bytes; the
    // close then succeeds.
    if (have_serial) {
      semb_encoder enc = OpenPair(a, st, "K-15b (setup)");
      if (enc) {
        std::vector<float> worker_vec(a.dims, 0.0f);
        size_t worker_req = kRequiredSentinel;
        semb_fingerprint worker_fp = MakeFingerprint();
        std::atomic<int> worker_done{0};
        semb_status worker_status = 0;
        const char* text = docs[2];
        const size_t text_len = std::strlen(text);
        std::thread worker([&] {
          alloc_hook::ArmPark(std::this_thread::get_id());
          worker_status = semb_encode(enc, text, text_len, worker_vec.data(), worker_vec.size() * sizeof(float),
                                      &worker_req, &worker_fp);
          worker_done.store(1, std::memory_order_release);
        });
        const bool parked = alloc_hook::WaitParked(std::chrono::seconds(120));
        if (!parked) {
          // Not a timing verdict: the call returned (or never allocated) before
          // any allocation could park it, so the state is not observable this
          // way on this build -- a named failure, never a hang.
          alloc_hook::Release();
          worker.join();
          Verdict(false, "K-15b (rendezvous) the encode allocated inside the call and parked",
                  std::string("no allocation observed inside semb_encode before it returned (status ") + Name(worker_status) +
                      "); the in-flight state is not observable through the allocator on this build");
        } else {
          // The close itself runs on a helper so a close that BLOCKS (the
          // rejected policy) is a named failure rather than a hang.
          std::atomic<int> close_done{0};
          semb_status close_status = 0;
          std::thread closer([&] {
            close_status = semb_encoder_close(enc);
            close_done.store(1, std::memory_order_release);
          });
          const auto t0 = std::chrono::steady_clock::now();
          while (close_done.load(std::memory_order_acquire) == 0 &&
                 std::chrono::steady_clock::now() - t0 < std::chrono::seconds(120)) {
            std::this_thread::yield();
          }
          const bool close_returned = close_done.load(std::memory_order_acquire) != 0;
          const bool in_flight_seen = worker_done.load(std::memory_order_acquire) == 0;
          alloc_hook::Release();
          worker.join();
          closer.join();
          Verdict(close_returned && in_flight_seen && close_status == st.handle_in_use,
                  "K-15b close while an encode is provably in flight on the handle -> SEMB_HANDLE_IN_USE, returned without blocking, nothing freed (D-SLM4647; sec 8 C26)",
                  std::string("close ") + (close_returned ? Name(close_status) : "DID NOT RETURN (blocked)") +
                      (in_flight_seen ? "; encode was in flight" : "; encode had ALREADY RETURNED"));
          Verdict(worker_status == st.ok && worker_req == need && SameBytes(worker_vec, serial[2]),
                  "K-15b the in-flight encode then completes SEMB_OK with the serial bytes (the refused close freed nothing)",
                  std::string(Name(worker_status)) + (SameBytes(worker_vec, serial[2]) ? " bytes equal serial" : " BYTES DIFFER"));
          const semb_status sc = semb_encoder_close(enc);
          Verdict(sc == st.ok, "K-15b close after the call drained -> SEMB_OK", Name(sc));
        }
      }
    }
    // K-15c: the bound EXCEEDED by construction is a testability blocker at
    // the frozen seam: nothing public holds a workspace or observes its
    // acquisition, so no construction can put N+1 calls provably inside the
    // forward at once without timing. Recorded, not shipped as a flaky cell.
    // What IS deterministic whatever the interleaving is asserted: with one
    // workspace and eight simultaneous callers every status is SEMB_OK or
    // SEMB_CONCURRENCY_EXCEEDED, every SEMB_OK carries the serial bytes, and
    // at least one call succeeds. The counts are reported as observed.
    if (have_serial) {
      semb_encoder enc = OpenPair(a, st, "K-15c (setup)", /*max_concurrency=*/1);
      if (enc) {
        constexpr int kThreads = 8;
        std::atomic<int> arrived{0};
        std::atomic<int> ok{0}, refused{0}, mismatched{0}, other{0};
        std::vector<std::thread> threads;
        for (int t = 0; t < kThreads; ++t) {
          threads.emplace_back([&, t] {
            ++arrived;
            while (arrived.load(std::memory_order_acquire) < kThreads) std::this_thread::yield();
            const EncodeResult res = EncodeDoc(enc, docs[t % 3], std::strlen(docs[t % 3]), a.dims);
            if (res.status == st.ok) {
              ++ok;
              if (!SameBytes(res.vector, serial[t % 3])) ++mismatched;
            } else if (res.status == st.concurrency_exceeded) {
              ++refused;
            } else {
              ++other;
            }
          });
        }
        for (auto& th : threads) th.join();
        Verdict(ok >= 1 && other == 0 && mismatched == 0,
                "K-15c max_concurrency = 1, eight simultaneous callers: every status is SEMB_OK or SEMB_CONCURRENCY_EXCEEDED, every SEMB_OK carries the serial bytes, at least one succeeds (deterministic under every interleaving)",
                "ok=" + std::to_string(ok.load()) + " refused=" + std::to_string(refused.load()) + " mismatched=" +
                    std::to_string(mismatched.load()) + " other=" + std::to_string(other.load()));
        Observed("K-15c the bound-exceeded must-reject (N+1 provably inside the forward at once) is NOT a cell: the frozen seam "
                 "exposes no way to hold a workspace or observe its acquisition, so 'refused=" + std::to_string(refused.load()) +
                 "' above is an observation, never a verdict -- TESTABILITY BLOCKER, routed (test-design record)");
        (void)semb_encoder_close(enc);
      }
    }
  }

  // ---- K-17 SEMB_ALLOCATION_FAILED: a real allocation failure on the real data path (sec 10.4) --
  {
    const std::uint64_t fired_before = alloc_hook::g_fail_fired.load();
    // Must-accept first: an armed threshold no allocation reaches leaves a
    // healthy open and encode untouched (the hook's mere presence refuses nothing).
    {
      alloc_hook::ArmFail(static_cast<std::size_t>(-1));
      semb_encoder enc = OpenPair(a, st, "K-17c (setup)");
      bool encoded = false;
      if (enc) {
        const EncodeResult r = EncodeDoc(enc, kDoc, sizeof(kDoc) - 1, a.dims);
        encoded = r.status == st.ok;
        (void)semb_encoder_close(enc);
      }
      alloc_hook::DisarmFail();
      Verdict(enc != nullptr && encoded && alloc_hook::g_fail_fired.load() == fired_before,
              "K-17c must-accept: with the allocation-failure policy armed at a threshold nothing reaches, open and encode succeed and the policy never fires",
              "fired=" + std::to_string(alloc_hook::g_fail_fired.load() - fired_before));
    }
    // K-17a: the first allocation of >= 100,000 bytes inside open fails. On
    // the synthetic pair that is the model artifact's own buffer (141,716
    // bytes -- observed as a 141,755-byte request under MSVC's STL, whose
    // large-allocation path adds its alignment header to the request; the
    // tokenizer artifact and its tables are smaller); on the real pair it is
    // the first large tokenizer or model allocation. Either way it is inside
    // open, on the real data path, and open must answer SEMB_ALLOCATION_FAILED
    // with *out = NULL -- and leave the process able to open normally
    // afterwards.
    {
      const semb_config cfg = MakeConfig(a.model, a.tokenizer);
      semb_encoder enc = OutSentinel();
      alloc_hook::ArmFail(100000);
      const semb_status s = semb_encoder_open(&cfg, &enc);
      alloc_hook::DisarmFail();
      const std::uint64_t fired = alloc_hook::g_fail_fired.load() - fired_before;
      Verdict(fired == 1 && s == st.allocation_failed && enc == nullptr,
              "K-17a an allocation failure inside open (the first request >= 100,000 bytes throws std::bad_alloc from the global allocator) -> SEMB_ALLOCATION_FAILED, *out = NULL (P-4/P-6 step 10)",
              std::string(Name(s)) + OutState(enc) + "; hook fired " + std::to_string(fired) + " time(s) on a " +
                  std::to_string(alloc_hook::g_fail_fired_size.load()) + "-byte request");
      semb_encoder after = OpenPair(a, st, "K-17a (a normal open afterwards)");
      if (after) {
        const EncodeResult r = EncodeDoc(after, kDoc, sizeof(kDoc) - 1, a.dims);
        Verdict(r.status == st.ok, "K-17a after the refused open, a normal open and encode succeed (no registry or pool state leaked)", Name(r.status));
        (void)semb_encoder_close(after);
      }
    }
    // K-17b: the first allocation of any size inside encode fails. The
    // handle stays live and usable: the next encode on it equals a fresh
    // handle's bytes (the failed call released its lease and any workspace).
    {
      semb_encoder enc = OpenPair(a, st, "K-17b (setup)");
      if (enc) {
        const std::uint64_t before = alloc_hook::g_fail_fired.load();
        SentinelBuffer buf(need);
        size_t req = kRequiredSentinel;
        semb_fingerprint fp = MakeFingerprint();
        alloc_hook::ArmFail(1);
        const semb_status s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
        alloc_hook::DisarmFail();
        const std::uint64_t fired = alloc_hook::g_fail_fired.load() - before;
        Verdict(fired == 1 && s == st.allocation_failed && req == kRequiredSentinel && buf.Untouched(need) && FingerprintUntouched(fp),
                "K-17b an allocation failure inside encode (the first request throws std::bad_alloc from the global allocator) -> SEMB_ALLOCATION_FAILED, nothing written, required untouched (P-4/P-6 step 12)",
                std::string(Name(s)) + "; hook fired " + std::to_string(fired) + " time(s) on a " +
                    std::to_string(alloc_hook::g_fail_fired_size.load()) + "-byte request" + Untouched(buf.Untouched(need)));
        const EncodeResult again = EncodeDoc(enc, kDoc, sizeof(kDoc) - 1, a.dims);
        semb_encoder fresh = OpenPair(a, st, "K-17b (fresh handle)");
        if (fresh) {
          const EncodeResult ref = EncodeDoc(fresh, kDoc, sizeof(kDoc) - 1, a.dims);
          Verdict(again.status == st.ok && ref.status == st.ok && SameBytes(again.vector, ref.vector),
                  "K-17b the handle stays usable after the refused encode: the next encode equals a fresh handle's bytes (lease and workspace released)",
                  std::string(Name(again.status)) + (SameBytes(again.vector, ref.vector) ? " bytes equal" : " BYTES DIFFER"));
          (void)semb_encoder_close(fresh);
        }
        const semb_status sc = semb_encoder_close(enc);
        Verdict(sc == st.ok, "K-17b close after the refused encode -> SEMB_OK (no call left in flight)", Name(sc));
      }
    }
    // K-17d (TE-154/TE-155, D-SLM6341's own fix round item 2): the SAME
    // allocation-failure policy as K-17b above, isolated -- ONE refused
    // encode, ONE close, NO intervening retry encode and NO second handle.
    // K-17b's own sequence (Claude/Curie/te145-slice2-red-2026-09-07.md
    // sec 10b) interposes a retry encode ("the handle stays usable") on
    // the SAME handle between the refused call and close; this cell
    // removes that retry to isolate whether the FIRST refused call ALONE
    // leaves active_calls nonzero (src/superembedder/encoder.cpp's
    // HandleLease/semb_encoder_close), or whether the retry encode is the
    // one that does. This is the pin: if a future change reintroduces the
    // defect this cell's own close returns SEMB_HANDLE_IN_USE and the
    // cell goes red.
    {
      semb_encoder enc = OpenPair(a, st, "K-17d (setup)");
      if (enc) {
        const std::uint64_t before = alloc_hook::g_fail_fired.load();
        SentinelBuffer buf(need);
        size_t req = kRequiredSentinel;
        semb_fingerprint fp = MakeFingerprint();
        alloc_hook::ArmFail(1);
        const semb_status s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
        alloc_hook::DisarmFail();
        const std::uint64_t fired = alloc_hook::g_fail_fired.load() - before;
        Verdict(fired == 1 && s == st.allocation_failed,
                "K-17d an allocation failure inside encode (the first request throws std::bad_alloc from the global allocator), NO retry -> SEMB_ALLOCATION_FAILED",
                std::string(Name(s)) + "; hook fired " + std::to_string(fired) + " time(s) on a " +
                    std::to_string(alloc_hook::g_fail_fired_size.load()) + "-byte request");
        const semb_status sc = semb_encoder_close(enc);
        Verdict(sc == st.ok,
                "K-17d close IMMEDIATELY after the refused encode, with NO intervening retry call, no second handle -> SEMB_OK",
                Name(sc));
      }
    }
  }

  // K-06i (TE-101, TE-97 regression): section 5.6 steps 9-10 require the
  // vocabulary join refusal BEFORE allocating the workspace pool. This is
  // synthetic-only: real artifacts can reach the hook during their reads.
  // The fixed 16 MiB threshold is not calibrated from product observations.
  // At 1,000,000 slots, the current contiguous slot vector reaches it before
  // malloc; no large allocation or OS-overcommit failure is required. The
  // controls below must fire correctly before that attribution is trusted.
  if (a.workspace_precedence) {
    constexpr size_t kPoolFailThreshold = 16u * 1024u * 1024u;
    constexpr uint32_t kPoolSlots = 1000000;
    auto open_cell = [&](const char* cell, const std::string& model,
                         uint32_t slots, int32_t expected, uint64_t expected_firings) {
      semb_config cfg = MakeConfig(model, a.tokenizer, slots);
      semb_encoder enc = OutSentinel();
      const uint64_t before = alloc_hook::g_fail_fired.load();
      alloc_hook::g_fail_fired_size.store(0);
      alloc_hook::g_safety_remaining.store(128u * 1024u * 1024u);
      alloc_hook::g_safety_fired.store(false);
      alloc_hook::g_safety_armed.store(slots == kPoolSlots);
      alloc_hook::ArmFail(kPoolFailThreshold);
      const semb_status result = semb_encoder_open(&cfg, &enc);
      alloc_hook::DisarmFail();
      alloc_hook::g_safety_armed.store(false);
      const uint64_t fired = alloc_hook::g_fail_fired.load() - before;
      const size_t fired_size = alloc_hook::g_fail_fired_size.load();
      const bool output_ok = expected == st.ok ? enc != nullptr && enc != OutSentinel() : enc == nullptr;
      const bool safety_fired = alloc_hook::g_safety_fired.load();
      const bool ok = result == expected && output_ok && fired == expected_firings && !safety_fired;
      Verdict(ok, cell, std::string(Name(result)) + "; slots=" + std::to_string(slots) +
              "; out_null=" + std::to_string(enc == nullptr) + "; hook_firings=" +
              std::to_string(fired) + "; intercepted_bytes=" + std::to_string(fired_size) +
              "; safety_fired=" + std::to_string(safety_fired));
      if (result == st.ok && enc != nullptr && enc != OutSentinel()) {
        const semb_status closed = semb_encoder_close(enc);
        Verdict(closed == st.ok, std::string(cell) + " close", Name(closed));
      }
      return ok;
    };
    const bool matched_control = open_cell("K-06i1 matched control: no large request during normal open",
                                           a.model, 1, st.ok, 0);
    const bool mismatch_control = open_cell("K-06i2 mismatch control: mismatch and null output before injection",
                                            a.other_model, 1, st.tokenizer_model_mismatch, 0);
    if (matched_control && mismatch_control) {
      const bool injected_control = open_cell("K-06i3 matched pool-allocation failure: ALLOCATION_FAILED and null output",
                                               a.model, kPoolSlots, st.allocation_failed, 1);
      if (injected_control) {
        open_cell("K-06i4 mismatch precedes pool allocation: TOKENIZER_MODEL_MISMATCH, null output, zero pool requests",
                  a.other_model, kPoolSlots, st.tokenizer_model_mismatch, 0);
      } else {
        Verdict(false, "K-06i4 precedence attribution unavailable", "matched injection control failed");
      }
    } else {
      Verdict(false, "K-06i3/i4 precedence attribution unavailable", "normal-open controls failed");
    }
    open_cell("K-06i5 healthy matched open after refused opens", a.model, 1, st.ok, 0);
  }

  std::printf("\nu1_raw_text_contract_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
