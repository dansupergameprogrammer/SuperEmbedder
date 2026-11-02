// tests/u1_batch_workspace_test.cpp -- TE-145 (U1 slice 2): the K-15-seam-
// dependent cells of `semb_encode_batch`'s red suite -- everything in this
// slice's dispatch that needs to OBSERVE the workspace lease directly
// (`semb_test_seam_*`, `tests/support/semb_workspace_seam.h`, TE-96 sec 3,
// adopted `Claude/Plans/SuperEmbedder_Plan.md` sec 3.1 "K-15 deterministic
// workspace contract") rather than only a returned status:
//
//   * C4's duplicate-id leg's OWN no-forward-ran proof (TE-96 sec 4.7 must-
//     reject: "byte-identical ids from distinct storage -> DOCUMENT_ID_DUPLICATE
//     WITH semb_test_seam_acquisitions() unchanged ... status-only evidence
//     does not close the no-forward claim");
//   * C26's two legs this slice closes (sec 8 C26; sub-plan sec 4.2 Slice
//     2): an encoder handle released while semb_encode_batch is in flight on
//     another thread -> SEMB_HANDLE_IN_USE, nothing freed, close succeeds
//     after the drain (the same active_calls/HandleLease pattern
//     src/superembedder/encoder.cpp already uses for semb_encoder_close vs
//     semb_encode, now driven with semb_encode_batch as the in-flight call);
//     and the sequence-released-mid-prefill leg -- the engine's own
//     per-document sequence lifecycle, now exercised across a MULTI-document
//     batch parked and released at the K-15 seam's single per-call
//     acquisition point (see this file's own C26b comment for the exact
//     construction this seat resolved against the existing seam);
//   * C48 (warm-vs-cold identity across 1,000 intervening documents), C49
//     (no growth on release/recreate, via this TU's own global-allocator
//     leak instrument -- the SAME technique
//     tests/u1_raw_text_contract_test.cpp already uses for its allocation-
//     failure hook, generalised here to COUNT live bytes rather than fail
//     them), and C50 (row-digest independence from batch size) -- TE-142
//     Finding G2, `Claude/Vitruvius/te143-01-c8-c17-dim1-gate-assignments.patch`
//     (proposed, not adopted; sub-plan sec 4.2 sequences all three here
//     regardless, TE-140 sec 4/6).
//
// RED-UNIMPLEMENTED at this branch's own base c0f52d4: semb_encode_batch
// does not exist. This target is EXCLUDE_FROM_ALL, built and run by
// tests/u1_batch_contract_check.py on demand (the same driver that builds
// the plain contract cells above), which reports the unresolved symbol by
// name -- the same shape TE-110's u1_workspace_seam_absent_check already
// establishes for the seam target.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <future>
#include <new>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_wb_witness_abi_contract.h"  // semb_wb_digest -- TE-172 N-9(i) polls it as a second
                                             // open-time observable alongside semb_encoder_dims; already
                                             // proven safe alongside the other two contract headers by
                                             // tests/w_b_corpus_witness_test.cpp's own include set.
#include "support/semb_workspace_seam.h"

using namespace std::chrono_literals;

// TE-192 item 6 (TE-187 bare cell 7, D-SLM6434 item 2): the per-document
// ("row") seam hook TE-184 added alongside the once-per-call hook this
// file's own C26a/C26b already exercise through
// `tests/support/semb_workspace_seam.h`. That header was not extended for
// the row-level surface (out of this seat's own writable scope --
// `tests/support/semb_workspace_seam.h` is not a file this round's brief
// lists), so the five row-level entry points this file's own C51 uses are
// declared directly here, in the identical shape
// `src/superembedder/engine_adapter_interim.cpp` already defines them
// (extern "C", the same names, `semb_test_seam_row_parked` omitted since
// C51 does not call it).
extern "C" {
int32_t semb_test_seam_row_arm_park(uint32_t count);
int32_t semb_test_seam_row_wait_parked(uint32_t n, uint32_t timeout_ms);
void semb_test_seam_row_release(void);
uint64_t semb_test_seam_row_acquisitions(void);
int32_t semb_test_seam_row_reset(void);
}

// ---------------------------------------------------------------------------
// C49's own leak instrument: a global operator-new/delete override that
// counts LIVE bytes (allocated minus freed), the leak-detection analogue of
// tests/u1_raw_text_contract_test.cpp's allocation-failure hook -- same
// mechanism (a global allocator override this TU alone links), different
// use (counting rather than injecting a failure). This is deliberately
// TEST-SIDE instrumentation, not a product build flag: this seat's writable
// scope is tests/** only, and a global allocator override in one TU is
// exactly the shape this project's own suite already uses for allocation
// control (u1_raw_text_contract_test.cpp), so no CMake/cmake/**/src/**
// change is needed to get a real leak signal.
// ---------------------------------------------------------------------------
namespace leak_hook {
std::atomic<int64_t> g_live_bytes{0};
std::atomic<int64_t> g_live_allocations{0};
// TE-172 N-9(ii): an ORDINAL-based one-shot failure policy, added to this
// SAME hook rather than a second one -- a translation unit installs only
// one global operator new/delete pair, and this file's own leak_hook
// already carries the D-SLM6353/S-5 alignment fix (the aligned Header,
// below) every allocator hook in this suite needs. g_alloc_ordinal counts
// every allocation THIS HOOK has ever served, process-wide, since before
// main(); g_fail_at_ordinal, when non-zero, names the ordinal whose
// request throws std::bad_alloc instead of allocating -- one-shot: the
// throwing call clears it, and a target that is never reached is left
// armed until DisarmFail() clears it explicitly (a trial whose target
// ordinal falls beyond that run's own total allocation count).
std::atomic<uint64_t> g_alloc_ordinal{0};
std::atomic<uint64_t> g_fail_at_ordinal{0};
void ArmFailAtOrdinal(uint64_t ordinal) { g_fail_at_ordinal.store(ordinal, std::memory_order_release); }
void DisarmFail() { g_fail_at_ordinal.store(0, std::memory_order_release); }
// TE-159 item 5 (S-5, D-SLM6353): plain `struct Header { size_t size; };` is
// 8 bytes, so `raw + sizeof(Header)` returns memory 8-mod-16 on x64 (malloc
// itself returns 16-aligned) -- violating `operator new`'s own alignment
// contract (__STDCPP_DEFAULT_NEW_ALIGNMENT__). Executed proof (TE-148
// review F-6): 10 of 12 measured std::vector<float> allocations under the
// unfixed hook landed at offset 8 mod 16. `alignas` here pads Header's own
// size up to the alignment, so `raw + sizeof(Header)` lands back on a
// 16-aligned boundary for every allocation this hook returns.
struct alignas(__STDCPP_DEFAULT_NEW_ALIGNMENT__) Header { size_t size; };
void* Allocate(std::size_t n) {
  const uint64_t ordinal = g_alloc_ordinal.fetch_add(1, std::memory_order_relaxed) + 1;
  const uint64_t target = g_fail_at_ordinal.load(std::memory_order_acquire);
  if (target != 0 && ordinal == target) {
    g_fail_at_ordinal.store(0, std::memory_order_release);  // one-shot
    throw std::bad_alloc();
  }
  const size_t total = n + sizeof(Header);
  void* raw = std::malloc(total == 0 ? 1 : total);
  if (!raw) throw std::bad_alloc();
  static_cast<Header*>(raw)->size = n;
  g_live_bytes.fetch_add(static_cast<int64_t>(n), std::memory_order_relaxed);
  g_live_allocations.fetch_add(1, std::memory_order_relaxed);
  return static_cast<uint8_t*>(raw) + sizeof(Header);
}
void Deallocate(void* p) noexcept {
  if (!p) return;
  void* raw = static_cast<uint8_t*>(p) - sizeof(Header);
  const size_t n = static_cast<Header*>(raw)->size;
  g_live_bytes.fetch_sub(static_cast<int64_t>(n), std::memory_order_relaxed);
  g_live_allocations.fetch_sub(1, std::memory_order_relaxed);
  std::free(raw);
}
}  // namespace leak_hook

void* operator new(std::size_t n) { return leak_hook::Allocate(n); }
void* operator new[](std::size_t n) { return leak_hook::Allocate(n); }
void operator delete(void* p) noexcept { leak_hook::Deallocate(p); }
void operator delete[](void* p) noexcept { leak_hook::Deallocate(p); }
void operator delete(void* p, std::size_t) noexcept { leak_hook::Deallocate(p); }
void operator delete[](void* p, std::size_t) noexcept { leak_hook::Deallocate(p); }

namespace {

int g_failures = 0;
int g_cells = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
void Phase(const char* text) { std::printf("[PHASE] %s\n", text); std::fflush(stdout); }
// TE-172: this file's own "not applicable to this leg" reporter, matching
// the [MISSING PREREQUISITE] convention every other TU in this suite
// already uses (e.g. tests/w_b_corpus_witness_test.cpp's Missing()) --
// named rather than silently skipped, so a leg that never drives a cell is
// visible in the suite's own output.
void Missing(const std::string& cell, const std::string& why) {
  ++g_cells;
  std::printf("[MISSING PREREQUISITE] %s: %s\n", cell.c_str(), why.c_str());
  std::fflush(stdout);
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }
bool Is(semb_status s, const char* name) { return s == semb_contract::StatusByName(name); }

struct Args {
  std::string model, tokenizer;
  unsigned dims = 0;
  // TE-357: isolates S-3 alone (see main()'s own early-exit comment) for
  // fast mutation-vitality iteration, independent of the rest of this
  // file's much longer-running cells (C48 alone bakes 1,002 documents).
  bool only_s3 = false;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--dims") { std::string v; next(&v); a.dims = static_cast<unsigned>(std::atoi(v.c_str())); }
    else if (k == "--only-s3") a.only_s3 = true;
  }
  return a;
}

// TE-172 N-9(i): counts every SUCCESSFUL open this file's own shared Open()
// helper has produced. AllocateHandleCookie (src/superembedder/encoder.cpp)
// is a single process-wide monotonic counter that never resets or reuses a
// value, and this helper is the ONLY call site of semb_encoder_open in this
// TU besides N-9(i)'s own direct call (confirmed by inspection) -- so,
// since no two opens in this file ever run concurrently with each other,
// this counter lets N-9(i) predict EXACTLY which cookie its own real open
// will receive, without spending a throwaway open to learn it.
std::atomic<uint64_t> g_cookie_counter{0};

semb_encoder Open(const Args& a, unsigned slots = 1) {
  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = a.model.data();
  c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data();
  c.tokenizer_path_len = a.tokenizer.size();
  c.max_concurrency = slots;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&c, &enc);
  if (!Is(s, "SEMB_OK") || !enc) { Verdict(false, "(setup) open", Name(s)); return nullptr; }
  g_cookie_counter.fetch_add(1, std::memory_order_acq_rel);
  return enc;
}

semb_document MakeDoc(const std::string& id, const std::string& text) {
  semb_document d{};
  d.struct_size = sizeof(semb_document);
  d.id = id.c_str();
  d.id_len = id.size();
  d.utf8 = text.c_str();
  d.utf8_len = text.size();
  return d;
}

std::vector<uint8_t> BakeOne(semb_encoder enc, const std::string& id, const std::string& text, unsigned dims,
                              semb_status* out_status) {
  semb_document doc = MakeDoc(id, text);
  std::vector<uint8_t> row(static_cast<size_t>(dims) * sizeof(float) + 16);
  auto p = reinterpret_cast<uintptr_t>(row.data());
  float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
  size_t req = 0;
  *out_status = semb_encode_batch(enc, &doc, 1, aligned, dims * sizeof(float), &req);
  if (*out_status != SEMB_OK) return {};
  auto b = reinterpret_cast<uint8_t*>(aligned);
  return {b, b + dims * sizeof(float)};
}

void FatalTimeout(const char* phase) { Verdict(false, phase, "deadline exceeded"); std::fflush(nullptr); std::_Exit(1); }

void ReleaseBounded(std::chrono::steady_clock::time_point deadline) {
  Phase("release");
  auto f = std::async(std::launch::async, [] { semb_test_seam_release(); });
  if (f.wait_until(deadline) != std::future_status::ready) FatalTimeout("cleanup release exceeded deadline");
  f.get();
}

void ResetSeam(std::chrono::steady_clock::time_point deadline) {
  Phase("reset joined epoch");
  auto f = std::async(std::launch::async, [] { return semb_test_seam_reset(); });
  if (f.wait_until(deadline) != std::future_status::ready) FatalTimeout("cleanup reset exceeded deadline");
  Verdict(f.get() == 1 && semb_test_seam_acquisitions() == 0 && semb_test_seam_parked() == 0,
          "(setup) reset establishes empty epoch", "");
}

// ---------------------------------------------------------------------------
// TE-160/S-6: step 12's SEMB_CONCURRENCY_EXCEEDED and TE-96 sec 4.7's
// cross-entry occupancy crossings (batch/raw, raw/batch, batch/batch). Both
// call kinds -- a raw semb_encode and a singleton semb_encode_batch --
// occupy and release the SAME per-handle workspace pool through the
// identical seam instrumentation, so an occupant of one kind and a
// contender of the other exercise the crossing rather than two same-kind
// exhaustion runs standing in for it (TE-96 sec 4.7: "No raw-only
// exhaustion run substitutes for any batch/raw, raw/batch or batch/batch
// crossing").
// ---------------------------------------------------------------------------
struct RawOut {
  std::vector<uint8_t> storage;
  size_t required = 0xBAD5EED;
  semb_fingerprint fingerprint{};
  semb_status status = -1000;
  explicit RawOut(unsigned dims) : storage(static_cast<size_t>(dims) * sizeof(float) + 32, 0xA5) {
    fingerprint.struct_size = sizeof(fingerprint);
    std::memset(fingerprint.digest, 0xC3, sizeof(fingerprint.digest));
  }
  float* data() {
    auto p = reinterpret_cast<uintptr_t>(storage.data());
    return reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
  }
  std::vector<uint8_t> bytes(unsigned dims) {
    auto p = reinterpret_cast<uint8_t*>(data());
    return {p, p + static_cast<size_t>(dims) * sizeof(float)};
  }
  bool untouched() {
    for (auto b : storage)
      if (b != 0xA5) return false;
    for (auto b : fingerprint.digest)
      if (b != 0xC3) return false;
    return required == 0xBAD5EED;
  }
};
struct BatchOut {
  std::vector<uint8_t> storage;
  size_t required = 0xBAD5EED;
  semb_status status = -1000;
  explicit BatchOut(unsigned dims) : storage(static_cast<size_t>(dims) * sizeof(float) + 32, 0xA5) {}
  float* data() {
    auto p = reinterpret_cast<uintptr_t>(storage.data());
    return reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
  }
  std::vector<uint8_t> bytes(unsigned dims) {
    auto p = reinterpret_cast<uint8_t*>(data());
    return {p, p + static_cast<size_t>(dims) * sizeof(float)};
  }
  bool untouched() {
    for (auto b : storage)
      if (b != 0xA5) return false;
    return required == 0xBAD5EED;
  }
};
void RawCall(semb_encoder enc, const std::string& text, RawOut* out, unsigned dims) {
  out->status = semb_encode(enc, text.data(), text.size(), out->data(), static_cast<size_t>(dims) * sizeof(float),
                             &out->required, &out->fingerprint);
}
void BatchCall(semb_encoder enc, const std::string& id, const std::string& text, BatchOut* out, unsigned dims) {
  semb_document d = MakeDoc(id, text);
  out->status = semb_encode_batch(enc, &d, 1, out->data(), static_cast<size_t>(dims) * sizeof(float), &out->required);
}
enum class CallKind { kRaw, kBatch };

// Occupies `n` slots with `occupant_kind` calls, parked at their own
// acquisition; issues one extra `contender_kind` call and asserts
// SEMB_CONCURRENCY_EXCEEDED with output (and, for raw, the fingerprint)
// canaries untouched and no additional acquisition; releases and drains
// the occupants; retries the contender and asserts it now succeeds,
// serial-identical to a reference taken on a SEPARATE fresh handle before
// the contended handle opened (real workspace memory never includes both
// pools simultaneously, matching tests/u1_workspace_seam_test.cpp's own
// established convention). `close_check`, when true, additionally asserts
// semb_encoder_close refuses while the occupants hold their leases and
// succeeds only after every join -- folded into one crossing rather than
// duplicated across all three, per this round's own dispatch.
void Crossing(const Args& a, unsigned n, CallKind occupant_kind, CallKind contender_kind, const std::string& label,
              bool close_check) {
  const unsigned dims = a.dims;
  const std::string extra_id = "extra";
  const std::string extra_text = "the extra call issued once the pool is exhausted";

  std::vector<uint8_t> reference;
  {
    semb_encoder serial = Open(a, 1);
    if (!serial) { Verdict(false, label + " (setup) serial reference handle", ""); return; }
    if (contender_kind == CallKind::kRaw) {
      RawOut ref(dims);
      RawCall(serial, extra_text, &ref, dims);
      Verdict(Is(ref.status, "SEMB_OK"), label + " (setup) serial raw reference", Name(ref.status));
      reference = ref.bytes(dims);
    } else {
      BatchOut ref(dims);
      BatchCall(serial, extra_id, extra_text, &ref, dims);
      Verdict(Is(ref.status, "SEMB_OK"), label + " (setup) serial batch reference", Name(ref.status));
      reference = ref.bytes(dims);
    }
    semb_encoder_close(serial);
  }

  semb_encoder enc = Open(a, n);
  if (!enc) { Verdict(false, label + " (setup) contended handle open", ""); return; }
  ResetSeam(std::chrono::steady_clock::now() + 30s);
  Verdict(semb_test_seam_arm_park(n) == 1, label + " (setup) arm " + std::to_string(n) + " park(s)", "");

  std::vector<std::unique_ptr<RawOut>> raw_occupants;
  std::vector<std::unique_ptr<BatchOut>> batch_occupants;
  std::vector<std::future<void>> jobs;
  std::vector<std::string> occ_ids, occ_texts;
  for (unsigned i = 0; i < n; ++i) {
    occ_ids.push_back("occ" + std::to_string(i));
    occ_texts.push_back("occupant document number " + std::to_string(i));
  }
  if (occupant_kind == CallKind::kRaw) {
    for (unsigned i = 0; i < n; ++i) raw_occupants.push_back(std::make_unique<RawOut>(dims));
    for (unsigned i = 0; i < n; ++i) {
      jobs.push_back(
          std::async(std::launch::async, [&, i] { RawCall(enc, occ_texts[i], raw_occupants[i].get(), dims); }));
    }
  } else {
    for (unsigned i = 0; i < n; ++i) batch_occupants.push_back(std::make_unique<BatchOut>(dims));
    for (unsigned i = 0; i < n; ++i) {
      jobs.push_back(std::async(std::launch::async,
                                 [&, i] { BatchCall(enc, occ_ids[i], occ_texts[i], batch_occupants[i].get(), dims); }));
    }
  }

  const bool occupied = semb_test_seam_wait_parked(n, 10000) == 1 && semb_test_seam_parked() == n;
  Verdict(occupied, label + " all " + std::to_string(n) + " slot(s) acquired and parked by the occupant", "");
  if (occupied) {
    const uint64_t before = semb_test_seam_acquisitions();
    Verdict(before == n, label + " exactly n acquisitions while occupied", std::to_string(before));

    if (contender_kind == CallKind::kRaw) {
      RawOut extra(dims);
      RawCall(enc, extra_text, &extra, dims);
      Verdict(Is(extra.status, "SEMB_CONCURRENCY_EXCEEDED") && extra.untouched() &&
                  semb_test_seam_acquisitions() == before,
              label + " extra RAW call refused with output/fingerprint canaries untouched and no additional "
                      "acquisition",
              Name(extra.status));
    } else {
      BatchOut extra(dims);
      BatchCall(enc, extra_id, extra_text, &extra, dims);
      Verdict(Is(extra.status, "SEMB_CONCURRENCY_EXCEEDED") && extra.untouched() &&
                  semb_test_seam_acquisitions() == before,
              label + " extra BATCH call refused with output canaries untouched and no additional acquisition",
              Name(extra.status));
    }

    if (close_check) {
      auto close_job = std::async(std::launch::async, [=] { return semb_encoder_close(enc); });
      const bool close_ready = close_job.wait_for(10s) == std::future_status::ready;
      Verdict(close_ready, label + " close deadline while occupants hold their leases", "");
      if (close_ready) {
        const semb_status close_status = close_job.get();
        Verdict(Is(close_status, "SEMB_HANDLE_IN_USE"), label + " close refused while occupants hold their leases",
                Name(close_status));
      }
    }
  }

  ReleaseBounded(std::chrono::steady_clock::now() + 30s);
  const auto drain_deadline = std::chrono::steady_clock::now() + 30s;
  for (auto& f : jobs) {
    if (f.wait_until(drain_deadline) != std::future_status::ready) FatalTimeout((label + " occupant drain deadline").c_str());
    f.get();
  }
  bool occupants_ok = true;
  if (occupant_kind == CallKind::kRaw) {
    for (auto& o : raw_occupants)
      if (!Is(o->status, "SEMB_OK")) occupants_ok = false;
  } else {
    for (auto& o : batch_occupants)
      if (!Is(o->status, "SEMB_OK")) occupants_ok = false;
  }
  Verdict(occupants_ok, label + " every occupant call itself completes successfully once released", "");

  if (contender_kind == CallKind::kRaw) {
    RawOut retry(dims);
    RawCall(enc, extra_text, &retry, dims);
    Verdict(Is(retry.status, "SEMB_OK") && retry.bytes(dims) == reference,
            label + " the extra RAW call succeeds after release, serial-identical to the reference",
            Name(retry.status));
  } else {
    BatchOut retry(dims);
    BatchCall(enc, extra_id, extra_text, &retry, dims);
    Verdict(Is(retry.status, "SEMB_OK") && retry.bytes(dims) == reference,
            label + " the extra BATCH call succeeds after release, serial-identical to the reference",
            Name(retry.status));
  }
  semb_encoder_close(enc);
  ResetSeam(std::chrono::steady_clock::now() + 30s);
}

// =========================================================================
// TE-357 S-3 (D-SLM7559 corrected clause, `Claude/Plans/SuperEmbedder_Plan.md`
// sec 3.1 "Batch acquisition commissioning"): S-6 above measures acquisitions
// by EXACTLY ONE only at pool size 1 -- a tautology under TE-350's own
// per-worker-thread acquisition scheme, since T = min(doc_count, pool size,
// hardware concurrency) collapses to 1 whenever the pool itself is 1. At the
// pool size the product actually ships (main.cpp's kBakeMaxConcurrency = 8),
// the count a healthy call must reach is T itself, not a literal: "the cell
// asserts against the count the call itself determined, observed at the
// seam, never against a constant" (the corrected clause). This cell computes
// T from the SAME formula production uses (mirrored, never imported --
// HardwareConcurrencyOrOne is a file-local symbol in
// engine_adapter_interim.cpp with no exported entry point) and asserts the
// seam's own observed delta equals it exactly, across doc counts that put
// T on both sides of the pool-size bound. Factored into its own function
// (rather than left inline in main()) so --only-s3 can run it alone --
// this file's other cells (C48 alone bakes 1,002 documents) make a full
// run too slow for fast mutation-vitality iteration on this one claim.
//
// A DEPENDENCY NAMED, NOT CLOSED (per the conductor's own request when
// TE-356's adaptive concurrency reopened this round -- D-SLM7560/D-SLM7563):
// this cell's own `expected_t` formula assumes `m->workspaces.size() ==
// kPoolSize` (the literal 8 requested at open). TE-356 makes the REALIZED
// pool size `effective_concurrency <= max_concurrency`, capped by memory
// actually free at open (`engine_adapter_interim.cpp`'s own
// `kOpenMemoryReserveBytes` policy) -- on a machine too memory-constrained
// to afford 8 slots of this model's own ~256 KiB workspace_bytes, the real
// pool would be smaller than 8 and this cell's own `expected_t` would be
// wrong. Re-run against the actual TE-356 commit (`69dfaa3`) on this round's
// own 32-core, 50+ GiB box: PASS, because affording 8 slots of a 256 KiB
// workspace costs about 2 MiB, nowhere near this machine's own limit. Unlike
// K-06i's own recalibration (a byte-threshold cell that was ACTIVELY,
// SILENTLY wrong -- a false PASS on the very property it existed to
// verify), a wrong `expected_t` here fails LOUDLY (a named PASS/FAIL
// mismatch on an exact-count assertion, never a silent pass) -- the failure
// mode this cell risks on a memory-starved machine is a visible, honest
// [FAIL], not a defect masquerading as green. Not recalibrated to a
// self-measured pool size in this round, given that risk asymmetry and this
// round's own time budget; a future round wanting full portability would
// query the REALIZED pool size (there is no public accessor for it today --
// `semb_test_seam_acquisitions()` reports a cumulative count, not the pool's
// own realized size) rather than assume it equals the request.
// =========================================================================
void RunS3Cell(const Args& a, size_t required1) {
  const auto deadline30 = [] { return std::chrono::steady_clock::now() + 30s; };
  // Mirrors engine_adapter_interim.cpp's own HardwareConcurrencyOrOne():
  // std::thread::hardware_concurrency() may return 0 when it cannot
  // determine an answer, in which case production falls back to 1.
  auto hardware_concurrency_or_one = []() -> size_t {
    const unsigned hc = std::thread::hardware_concurrency();
    return hc == 0 ? size_t{1} : static_cast<size_t>(hc);
  };
  constexpr unsigned kPoolSize = 8;  // main.cpp's kBakeMaxConcurrency
  semb_encoder enc = Open(a, kPoolSize);
  if (!enc) return;
  ResetSeam(deadline30());
  // doc_count on both sides of the pool-size bound: 4 (< pool, T =
  // doc_count), 8 (== pool), 16 (> pool, T = pool on any machine with
  // hardware_concurrency() >= 8).
  const std::vector<size_t> doc_counts = {4, 8, 16};
  uint64_t running = semb_test_seam_acquisitions();
  bool ok = true;
  std::string detail;
  for (size_t doc_count : doc_counts) {
    std::vector<semb_document> docs;
    std::vector<std::string> ids, texts;
    for (size_t i = 0; i < doc_count; ++i) {
      ids.push_back("s3-" + std::to_string(doc_count) + "-" + std::to_string(i));
      texts.push_back("document number " + std::to_string(i));
    }
    for (size_t i = 0; i < doc_count; ++i) docs.push_back(MakeDoc(ids[i], texts[i]));
    std::vector<uint8_t> buf((docs.size() * required1) + 64, 0xA5);
    auto p = reinterpret_cast<uintptr_t>(buf.data());
    float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
    const uint64_t after = semb_test_seam_acquisitions();
    const size_t expected_t = std::min({doc_count, size_t(kPoolSize), hardware_concurrency_or_one()});
    const uint64_t delta = after - running;
    if (!Is(s, "SEMB_OK") || delta != expected_t) {
      ok = false;
      detail += " doc_count=" + std::to_string(doc_count) + "(status=" + std::string(Name(s)) +
                 " delta=" + std::to_string(delta) + " expected=" + std::to_string(expected_t) + ")";
    }
    running = after;
  }
  Verdict(ok,
          "S-3 (T>1) a valid batch call's own acquisition count equals T = min(doc_count, pool size, "
          "hardware_concurrency()) exactly -- observed at the seam, computed from the call's own "
          "conditions, never asserted against a literal -- at pool size " +
              std::to_string(kPoolSize) + " over doc counts on both sides of the pool bound",
          detail.empty() ? "every doc_count matched its own computed T" : detail);
  semb_encoder_close(enc);
  ResetSeam(deadline30());
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0) {
    std::fprintf(stderr, "usage: %s --model <.sslm> --tokenizer <.sslm> --dims <n>\n", argv[0]);
    return 2;
  }
  const auto deadline30 = [] { return std::chrono::steady_clock::now() + 30s; };
  const unsigned dims = a.dims;
  const size_t required1 = static_cast<size_t>(dims) * sizeof(float);

  // TE-357: isolates S-3 alone, skipping every other cell in this file
  // (see RunS3Cell's own comment for why -- C48 alone bakes 1,002
  // documents, making a full run too slow for fast mutation-vitality
  // iteration on this one claim).
  if (a.only_s3) {
    RunS3Cell(a, required1);
    std::printf("\nu1_batch_workspace_test (isolated --only-s3): %d cell(s), %d failure(s)\n", g_cells, g_failures);
    return g_failures ? 1 : 0;
  }

  // =========================================================================
  // C4: byte-identical duplicate ids -> SEMB_DOCUMENT_ID_DUPLICATE, with
  // semb_test_seam_acquisitions() UNCHANGED -- the no-forward-ran proof
  // (TE-96 sec 4.7 must-reject). The future batch-acquisition-count
  // commissioning cells below establish that a VALID batch increments the
  // seam by exactly one; THIS cell establishes that a REJECTED one does not
  // increment it at all, which is what makes "no forward ran" checkable
  // rather than merely plausible from the returned status alone.
  // =========================================================================
  {
    semb_encoder enc = Open(a, 1);
    if (enc) {
      ResetSeam(deadline30());
      const uint64_t before = semb_test_seam_acquisitions();
      // Named locals, not string literals passed directly to MakeDoc: a
      // literal argument binds to a TEMPORARY std::string whose lifetime
      // ends at this statement's own close, dangling the semb_document's
      // raw pointer by the time the semb_encode_batch call below runs (see
      // tests/u1_batch_contract_test.cpp's DocSet comment for the full
      // account of this bug class, found by executing that file).
      const std::string dup_id = "dup", first_text = "first", second_text = "second";
      std::vector<semb_document> docs = {MakeDoc(dup_id, first_text), MakeDoc(dup_id, second_text)};
      std::vector<uint8_t> buf((docs.size() * required1) + 64, 0xA5);
      auto p = reinterpret_cast<uintptr_t>(buf.data());
      float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
      size_t req = 0xBAD5EED;
      const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), aligned,
                                               buf.size() - 16, &req);
      const uint64_t after = semb_test_seam_acquisitions();
      Verdict(Is(s, "SEMB_DOCUMENT_ID_DUPLICATE") && after == before,
              "C4-no-forward duplicate ids refused with the workspace acquisition count UNCHANGED "
              "(step 10 fires before step 12's acquisition; the refusal never reaches the forward)",
              "status=" + std::string(Name(s)) + " before=" + std::to_string(before) +
                  " after=" + std::to_string(after));
      semb_encoder_close(enc);
    }
  }

  // =========================================================================
  // C26a: an encoder handle released while semb_encode_batch is in flight
  // on another thread -> SEMB_HANDLE_IN_USE, nothing freed, close succeeds
  // after the drain. Mirrors tests/u1_workspace_seam_test.cpp's own K-15e
  // (the identical construction for semb_encode) with semb_encode_batch as
  // the in-flight call.
  // =========================================================================
  {
    semb_encoder enc = Open(a, 1);
    if (enc) {
      ResetSeam(deadline30());
      Verdict(semb_test_seam_arm_park(1) == 1, "C26a (setup) arm one park", "");
      const std::string p0_id = "p0", p0_text = "parked document";
      std::vector<semb_document> docs = {MakeDoc(p0_id, p0_text)};
      std::vector<uint8_t> buf(required1 + 64, 0xA5);
      auto p = reinterpret_cast<uintptr_t>(buf.data());
      float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
      size_t req = 0xBAD5EED;
      semb_status batch_status = -1000;
      auto batch_job = std::async(std::launch::async, [&] {
        batch_status = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
      });
      const bool parked = semb_test_seam_wait_parked(1, 10000) == 1 && semb_test_seam_parked() == 1;
      Verdict(parked, "C26a (setup) the batch call parks at its single workspace acquisition", "");
      if (parked) {
        auto close_job = std::async(std::launch::async, [=] { return semb_encoder_close(enc); });
        const bool close_ready = close_job.wait_for(10s) == std::future_status::ready;
        Verdict(close_ready, "C26a close deadline while batch is parked in flight", "");
        if (close_ready) {
          const semb_status close_status = close_job.get();
          Verdict(Is(close_status, "SEMB_HANDLE_IN_USE"),
                  "C26a close while semb_encode_batch is in flight -> SEMB_HANDLE_IN_USE, nothing freed",
                  Name(close_status));
        }
        ReleaseBounded(deadline30());
        if (batch_job.wait_until(deadline30()) != std::future_status::ready) FatalTimeout("C26a batch job cleanup deadline");
        batch_job.get();
        Verdict(Is(batch_status, "SEMB_OK"),
                "C26a the parked batch call itself completes successfully once released", Name(batch_status));
        // The handle was never freed (close was refused): a second close now
        // succeeds, proving the handle survived the in-flight refusal intact.
        const semb_status final_close = semb_encoder_close(enc);
        Verdict(Is(final_close, "SEMB_OK"),
                "C26a close AFTER the drain succeeds -- the handle was never freed by the refused close",
                Name(final_close));
      } else {
        ReleaseBounded(deadline30());
        if (batch_job.wait_until(deadline30()) != std::future_status::ready) FatalTimeout("C26a batch job cleanup (unparked path)");
        batch_job.get();
        semb_encoder_close(enc);
      }
      ResetSeam(deadline30());
    }
  }

  // =========================================================================
  // C26b: the sequence-released-mid-prefill leg -- the engine's own
  // per-document sequence lifecycle, exercised across a MULTI-document
  // batch. RESOLUTION OF AN UNDERSPECIFIED CELL, stated rather than
  // silently assumed: the sub-plan (sec 4.2, Slice 2) names this leg in
  // prose without stating how a per-ROW sequence boundary is observed
  // through the K-15 seam, which parks once per WORKSPACE ACQUISITION --
  // for semb_encode_batch that is ONCE PER CALL (TE-96 sec 4.2 step 12:
  // "One workspace for the whole call ... rows run serially on that slot"),
  // not once per row. This cell therefore parks a MULTI-ROW batch call at
  // its single per-call acquisition point (before row 0's own forward
  // begins), releases it, and asserts every row -- not only the first --
  // completes with bytes serial-identical to an unparked reference: the
  // claim this construction can actually see is that the per-document
  // sequence loop inside one held-and-released workspace lease is unharmed
  // by a park/release cycle, for every document in the batch, not only the
  // one whose forward happened to be first. A finer, per-row parking point
  // would need a seam extension this seat's writable scope (tests/**) does
  // not reach into src/**/include/** to build, and none exists today
  // (`git grep -n SEMB_ENABLE_WORKSPACE_TEST_SEAM src/` shows the one
  // existing hook site) -- routed as a finding (this file's own header
  // comment; the handoff repeats it) rather than invented.
  // =========================================================================
  {
    semb_encoder serial = Open(a, 1);
    std::vector<std::pair<std::string, std::string>> docs_named = {
        {"m0", "the first document in a parked multi-row batch"},
        {"m1", "the second document, encoded after the release"},
        {"m2", "the third and final document in this batch"},
    };
    std::vector<std::vector<uint8_t>> reference;
    if (serial) {
      for (auto& [id, text] : docs_named) {
        semb_status s = -1000;
        reference.push_back(BakeOne(serial, id, text, dims, &s));
        Verdict(Is(s, "SEMB_OK"), "C26b (setup) serial reference row for " + id, Name(s));
      }
      semb_encoder_close(serial);
    }

    semb_encoder enc = Open(a, 1);
    if (enc && !reference.empty()) {
      ResetSeam(deadline30());
      Verdict(semb_test_seam_arm_park(1) == 1, "C26b (setup) arm one park", "");
      std::vector<semb_document> docs;
      for (auto& [id, text] : docs_named) docs.push_back(MakeDoc(id, text));
      std::vector<uint8_t> buf((docs.size() * required1) + 64, 0xA5);
      auto p = reinterpret_cast<uintptr_t>(buf.data());
      float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
      size_t req = 0xBAD5EED;
      semb_status batch_status = -1000;
      auto job = std::async(std::launch::async, [&] {
        batch_status = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
      });
      const bool parked = semb_test_seam_wait_parked(1, 10000) == 1;
      Verdict(parked, "C26b (setup) the multi-row batch parks before any row's own forward begins", "");
      ReleaseBounded(deadline30());
      if (job.wait_until(deadline30()) != std::future_status::ready) FatalTimeout("C26b job cleanup deadline");
      job.get();
      bool all_match = Is(batch_status, "SEMB_OK");
      std::string detail = "status=" + std::string(Name(batch_status));
      if (all_match) {
        for (size_t i = 0; i < docs_named.size(); ++i) {
          auto b = reinterpret_cast<uint8_t*>(aligned) + i * required1;
          const std::vector<uint8_t> row(b, b + required1);
          if (row != reference[i]) { all_match = false; detail += " row" + std::to_string(i) + "-mismatch"; }
        }
      }
      Verdict(all_match,
              "C26b every row of a batch parked mid-call (before its first forward) and released "
              "completes serial-identical to an unparked reference -- the per-document sequence loop "
              "survives the park/release cycle for all N documents, not only the first",
              detail);
      semb_encoder_close(enc);
      ResetSeam(deadline30());
    }
  }

  // =========================================================================
  // C48: warm-vs-cold identity. Encode a fixed document, then 1,000 others
  // through the SAME handle (each its own singleton semb_encode_batch call,
  // so the handle genuinely cycles cold-to-warm across many SEPARATE calls
  // rather than staying warm inside one call), then re-encode the fixed
  // document -- byte-identical.
  // =========================================================================
  {
    semb_encoder enc = Open(a, 1);
    if (enc) {
      ResetSeam(deadline30());
      const uint64_t before_count = semb_test_seam_acquisitions();
      semb_status s0 = -1000;
      const std::vector<uint8_t> cold = BakeOne(enc, "fixed", "the fixed document under test", dims, &s0);
      bool intervening_ok = Is(s0, "SEMB_OK");
      for (int i = 0; i < 1000 && intervening_ok; ++i) {
        semb_status si = -1000;
        BakeOne(enc, "filler" + std::to_string(i), "filler document number " + std::to_string(i) + " of one thousand",
                dims, &si);
        if (!Is(si, "SEMB_OK")) intervening_ok = false;
      }
      semb_status s1 = -1000;
      const std::vector<uint8_t> warm = BakeOne(enc, "fixed", "the fixed document under test", dims, &s1);
      const uint64_t after_count = semb_test_seam_acquisitions();
      Verdict(intervening_ok && Is(s1, "SEMB_OK") && cold == warm,
              "C48 warm-vs-cold identity: the fixed document's own row is byte-identical before and after "
              "1,000 intervening documents through the same handle",
              "intervening_ok=" + std::to_string(intervening_ok) + " match=" + std::to_string(cold == warm));
      Verdict(after_count == before_count + 1002,
              "C48-count exactly 1,002 workspace acquisitions (1 cold + 1,000 filler + 1 warm), one per "
              "singleton batch call, none dropped and none doubled",
              "before=" + std::to_string(before_count) + " after=" + std::to_string(after_count));
      semb_encoder_close(enc);
      ResetSeam(deadline30());
    }
  }

  // =========================================================================
  // C49: no growth on release/recreate, under this TU's own leak instrument
  // (the header comment explains why this is a genuine leak-detection
  // instrument despite being test-side rather than a CMake/ASan build flag).
  // Open, bake one small batch, close -- N times -- and assert the live-byte
  // reading STABILISES rather than growing without bound.
  //
  // WHY A WARM-UP WINDOW, RATHER THAN COMPARING EVERY CYCLE TO CYCLE 0'S OWN
  // BASELINE: found by executing this file against a scratch stand-in
  // implementation (never committed; see u1_batch_contract_test.cpp's
  // DocSet comment for this file's sibling finding from the same kind of
  // check). A one-time lazy allocation that does not happen to fire on the
  // very FIRST cycle -- a static cache seeded on the first call down some
  // rarely-hit branch, a locale facet touched only once per process -- is
  // legitimate one-time cost, not a leak, and comparing every cycle against
  // cycle 0's own reading flags it as "growth" anyway. A REAL per-cycle
  // leak, by contrast, keeps growing in the SECOND half of the run just as
  // it did in the first. The kWarmupCycles window absorbs one-time cost;
  // the tail window is what must be flat.
  // =========================================================================
  {
    constexpr int kCycles = 50;
    constexpr int kWarmupCycles = 10;
    // TE-147 (U1 slice 2 build): RESERVED up front. Found by execution: an
    // un-reserved vector here means ITS OWN geometric reallocation, growing
    // one int64_t per cycle under this same global-allocator instrument,
    // shows up as part of the "live bytes" reading being measured -- an
    // isolated, model-free reproduction (no encoder, no engine, just this
    // exact push_back pattern under the identical leak_hook) reproduced the
    // SAME 400-byte growth this cell originally reported (cycle 0 -> final)
    // byte for byte. Reserving the full capacity up front removes the
    // instrument's own bookkeeping from the quantity it measures, so a
    // reading that moves is the product's own allocations moving, not this
    // vector's.
    std::vector<int64_t> live_after_cycle;
    live_after_cycle.reserve(kCycles);
    bool cycle_ok = true;
    for (int i = 0; i < kCycles && cycle_ok; ++i) {
      semb_encoder cyc = Open(a, 1);
      if (!cyc) { cycle_ok = false; break; }
      semb_status s = -1000;
      BakeOne(cyc, "cyc" + std::to_string(i), "a small document baked once per open/close cycle", dims, &s);
      if (!Is(s, "SEMB_OK")) cycle_ok = false;
      const semb_status closed = semb_encoder_close(cyc);
      if (!Is(closed, "SEMB_OK")) cycle_ok = false;
      live_after_cycle.push_back(leak_hook::g_live_bytes.load(std::memory_order_relaxed));
    }
    bool no_growth = cycle_ok && static_cast<int>(live_after_cycle.size()) > kWarmupCycles;
    if (no_growth) {
      const int64_t tail_baseline = live_after_cycle[kWarmupCycles];
      for (size_t i = kWarmupCycles; i < live_after_cycle.size(); ++i)
        if (live_after_cycle[i] > tail_baseline) no_growth = false;
    }
    Verdict(no_growth,
            "C49 the live-allocated-bytes reading is flat across cycles " + std::to_string(kWarmupCycles) +
                ".." + std::to_string(kCycles) + " of " + std::to_string(kCycles) +
                " open/bake/close cycles, after a " + std::to_string(kWarmupCycles) +
                "-cycle warm-up window (this TU's own global-allocator leak instrument)",
            live_after_cycle.size() <= kWarmupCycles
                ? "too few cycles ran to evaluate the tail window"
                : "cycle0=" + std::to_string(live_after_cycle.front()) +
                      " tail_baseline(cycle" + std::to_string(kWarmupCycles) +
                      ")=" + std::to_string(live_after_cycle[kWarmupCycles]) +
                      " final=" + std::to_string(live_after_cycle.back()) +
                      " max=" + std::to_string(*std::max_element(live_after_cycle.begin(), live_after_cycle.end())));
  }

  // =========================================================================
  // C50: row-digest independence from batch size, distinct from C27's
  // order-only claim -- the SAME corpus baked as one call vs. as many
  // smaller calls, per-document rows identical.
  // =========================================================================
  {
    semb_encoder enc = Open(a, 2);
    if (enc) {
      // Text length kept modest, matching C27's own fix: well under any
      // host's context_cap (the mechanism pair's own 64-token cap
      // included), so this cell exercises batch-size independence, not a
      // second, unrelated context-cap refusal.
      std::vector<std::pair<std::string, std::string>> corpus = {
          {"c0", "the first short document"},
          {"c1", "the second document"},
          {"c2", "a third, slightly longer one"},
          {"c3", "the fourth and final document"},
      };
      std::vector<semb_document> docs;
      for (auto& [id, text] : corpus) docs.push_back(MakeDoc(id, text));
      std::vector<uint8_t> one_call_buf((docs.size() * required1) + 64, 0xA5);
      auto p1 = reinterpret_cast<uintptr_t>(one_call_buf.data());
      float* one_call_rows = reinterpret_cast<float*>((p1 + 15) & ~uintptr_t(15));
      size_t req = 0xBAD5EED;
      const semb_status s_one = semb_encode_batch(enc, docs.data(), docs.size(), one_call_rows,
                                                    one_call_buf.size() - 16, &req);

      std::vector<std::vector<uint8_t>> many_calls;
      bool many_ok = true;
      for (auto& [id, text] : corpus) {
        semb_status s = -1000;
        many_calls.push_back(BakeOne(enc, id, text, dims, &s));
        if (!Is(s, "SEMB_OK")) many_ok = false;
      }

      bool rows_match = Is(s_one, "SEMB_OK") && many_ok;
      if (rows_match) {
        for (size_t i = 0; i < corpus.size(); ++i) {
          auto b = reinterpret_cast<uint8_t*>(one_call_rows) + i * required1;
          const std::vector<uint8_t> row_one(b, b + required1);
          if (row_one != many_calls[i]) rows_match = false;
        }
      }
      Verdict(rows_match,
              "C50 row-digest independence from batch size: baking a 4-document corpus as ONE call vs. as "
              "4 singleton calls produces byte-identical per-document rows (distinct from C27's order-only claim)",
              "s_one=" + std::string(Name(s_one)) + " many_ok=" + std::to_string(many_ok) +
                  " rows_match=" + std::to_string(rows_match));
      semb_encoder_close(enc);
    }
  }

  // =========================================================================
  // C51 (TE-187 bare cell 7, D-SLM6434 item 2, TE-149 sec 7 bare cell 2):
  // the between-row seam hook (OnRowAcquired, TE-184's own K-15 per-row
  // park point) proves the ONE workspace slot acquired for the whole call
  // is STILL held strictly BETWEEN two rows of a multi-document batch --
  // a granularity C26a/C26b cannot reach, since the once-per-call hook
  // (OnAcquired) parks exactly once, before ANY row's own forward begins,
  // so a park there is observationally identical to a park at the very
  // first row's own hook call. The property under test (a contender
  // refused while the slot is held) is not new; WHERE the observation is
  // taken is: this cell's own park is armed a SECOND time only once the
  // FIRST row's own hook call has fully returned (confirmed via a bounded
  // retry on re-arming, which `semb_test_seam_row_arm_park` refuses while
  // any row is still parked, and via the row-level acquisition counter,
  // incremented unconditionally on every hook call before the park check)
  // -- never by racing the model's own forward-pass wall-clock time. A
  // build reverted to call-boundary-only parking (no working row hook)
  // leaves this cell's own second park request permanently unconsumed:
  // `semb_test_seam_row_wait_parked` times out, a loud, named failure
  // (TE-187's own must-reject: "a scratch build parking only at the call
  // boundary fails it") rather than a false pass.
  // =========================================================================
  {
    semb_encoder enc = Open(a, 1);
    if (enc) {
      ResetSeam(deadline30());
      Verdict(semb_test_seam_row_reset() == 1, "C51 (setup) reset the row-level seam epoch", "");

      std::vector<std::pair<std::string, std::string>> docs_named = {
          {"r0", "the first short document"},
          {"r1", "the second document"},
          {"r2", "the third document"},
      };
      std::vector<semb_document> docs;
      for (auto& [id, text] : docs_named) docs.push_back(MakeDoc(id, text));
      std::vector<uint8_t> buf((docs.size() * required1) + 64, 0xA5);
      auto p = reinterpret_cast<uintptr_t>(buf.data());
      float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
      size_t req = 0xBAD5EED;

      Verdict(semb_test_seam_row_arm_park(1) == 1, "C51 (setup) arm the row-level park for row 0", "");
      semb_status batch_status = -1000;
      auto job = std::async(std::launch::async, [&] {
        batch_status = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
      });
      const bool row0_parked = semb_test_seam_row_wait_parked(1, 10000) == 1;
      Verdict(row0_parked, "C51 (setup) row 0's own hook call parks", "");
      bool mid_batch_parked = false;
      if (row0_parked) {
        semb_test_seam_row_release();
        bool rearmed = false;
        const auto rearm_deadline = std::chrono::steady_clock::now() + 10s;
        while (std::chrono::steady_clock::now() < rearm_deadline) {
          if (semb_test_seam_row_arm_park(1) == 1) { rearmed = true; break; }
        }
        Verdict(rearmed,
                "C51 (setup) re-arm the row-level park for the row AFTER row 0, refused until row 0's own "
                "hook call has fully returned (the row parked-count back to zero)", "");
        mid_batch_parked = rearmed && semb_test_seam_row_wait_parked(1, 10000) == 1;
        Verdict(mid_batch_parked,
                "C51 (setup) the batch parks a SECOND time, strictly between two rows -- past row 0's own "
                "hook call, before the batch's own last row", "");
        if (mid_batch_parked) {
          const uint64_t acquisitions_at_park = semb_test_seam_row_acquisitions();
          Verdict(acquisitions_at_park >= 2,
                  "C51 (setup) the second park is genuinely past row 0: the row-level acquisition counter "
                  "reads at least 2 hook calls, so this park is not the once-per-call hook's own first-row "
                  "timing wearing a different name",
                  std::to_string(acquisitions_at_park));

          // The ONE workspace slot from this call's own once-per-call
          // acquisition is still held while parked strictly between two
          // rows: a contender on the SAME encoder (pool size 1, no other
          // slot to acquire) is refused SEMB_CONCURRENCY_EXCEEDED, output
          // canaries untouched, no additional acquisition recorded.
          const uint64_t before_contender = semb_test_seam_acquisitions();
          BatchOut extra(dims);
          BatchCall(enc, "extra", "the contender issued while parked strictly between two rows", &extra, dims);
          Verdict(Is(extra.status, "SEMB_CONCURRENCY_EXCEEDED") && extra.untouched() &&
                      semb_test_seam_acquisitions() == before_contender,
                  "C51 a contender parked strictly BETWEEN two rows of a 3-document batch (past row 0, "
                  "before the last row) is refused SEMB_CONCURRENCY_EXCEEDED with output canaries "
                  "untouched and no additional acquisition -- proven at the between-row seam hook's own "
                  "granularity, distinct from the once-per-call hook's own call-boundary observation",
                  Name(extra.status));
        }
        semb_test_seam_row_release();
      }
      if (job.wait_until(deadline30()) != std::future_status::ready) FatalTimeout("C51 batch job cleanup deadline");
      job.get();
      Verdict(Is(batch_status, "SEMB_OK"),
              "C51 the call parked strictly between two of its own rows completes successfully once fully "
              "released, every row's own forward having run exactly once",
              Name(batch_status));
      // Every row ran exactly once: the batch's own emitted row for r1
      // (the row parked mid-call) matches an unparked serial reference,
      // proving the mid-batch park changed timing only, never content.
      if (Is(batch_status, "SEMB_OK")) {
        semb_encoder serial_ref = Open(a, 1);
        semb_status ref_status = -1000;
        std::vector<uint8_t> reference;
        if (serial_ref) {
          reference = BakeOne(serial_ref, "r1", docs_named[1].second, dims, &ref_status);
          semb_encoder_close(serial_ref);
        }
        auto b = reinterpret_cast<uint8_t*>(aligned) + 1 * required1;
        const std::vector<uint8_t> row1(b, b + required1);
        Verdict(Is(ref_status, "SEMB_OK") && row1 == reference,
                "C51 row 1 (the row parked mid-call) is byte-identical to an unparked serial reference",
                "ref_status=" + std::string(Name(ref_status)));
      }
      semb_encoder_close(enc);
      ResetSeam(deadline30());
      Verdict(semb_test_seam_row_reset() == 1, "C51 (teardown) reset the row-level seam epoch", "");
    }
  }

  // =========================================================================
  // TE-160/S-6 (TE-96 sec 4.7's "Batch acquisition commissioning" paragraph,
  // its own text: "valid multirow batches (varied counts, short/long shapes
  // and both orders) must ... increment acquisitions by exactly one").
  // C48-count above only bakes SINGLETON (n=1) batch calls, so a defect that
  // releases and reacquires the workspace once PER ROW would be invisible to
  // it -- n=1 makes "once per row" and "once per call" the same number. This
  // cell bakes varied row COUNTS (1, 2, 5), varied per-row SHAPES (a short
  // text and a longer one -- both held well under the mechanism fixture's
  // own 64-token context_cap, per TE-145 sec 6's own precedent for this
  // exact fixture), and BOTH ORDERS of short/long at n=2, and checks each
  // call's own delta against the running total.
  // =========================================================================
  {
    semb_encoder enc = Open(a, 1);
    if (enc) {
      ResetSeam(deadline30());
      const std::string kShortText = "a short doc";
      const std::string kLongText = "a longer document with more distinct words than the short one";
      // {label, per-row texts} -- varied counts (1, 2, 5), short/long shapes,
      // and both orders at n=2 (short-then-long, long-then-short).
      const std::vector<std::pair<std::string, std::vector<std::string>>> specs = {
          {"n1-short", {kShortText}},
          {"n2-short-long", {kShortText, kLongText}},
          {"n2-long-short", {kLongText, kShortText}},
          {"n5-mixed", {kShortText, kLongText, kShortText, kLongText, kShortText}},
      };
      uint64_t running = semb_test_seam_acquisitions();
      bool ok = true;
      std::string detail;
      for (auto& [label, texts] : specs) {
        std::vector<semb_document> docs;
        std::vector<std::string> ids;
        for (size_t i = 0; i < texts.size(); ++i) ids.push_back(std::string(label) + "-" + std::to_string(i));
        for (size_t i = 0; i < texts.size(); ++i) docs.push_back(MakeDoc(ids[i], texts[i]));
        std::vector<uint8_t> buf((docs.size() * required1) + 64, 0xA5);
        auto p = reinterpret_cast<uintptr_t>(buf.data());
        float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
        size_t req = 0xBAD5EED;
        const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
        const uint64_t after = semb_test_seam_acquisitions();
        const bool delta_one = (after == running + 1);
        if (!Is(s, "SEMB_OK") || !delta_one) {
          ok = false;
          detail += " " + label + "(status=" + std::string(Name(s)) + " delta=" + std::to_string(after - running) +
                     ")";
        }
        running = after;
      }
      Verdict(ok,
              "S-6 a valid multirow batch call (varied row counts 1/2/5, short/long per-row shapes, "
              "both orders at n=2) increments the workspace acquisition count by EXACTLY ONE per call, "
              "never once per row (TE-96 sec 4.7 batch-acquisition commissioning)",
              detail.empty() ? "every spec delta=1" : detail);
      semb_encoder_close(enc);
      ResetSeam(deadline30());
    }
  }

  RunS3Cell(a, required1);

  // =========================================================================
  // TE-160/S-6: step 12's SEMB_CONCURRENCY_EXCEEDED with the pool's only
  // slot held (TE-148 review S-6: "No cell anywhere drives
  // semb_encode_batch to SEMB_CONCURRENCY_EXCEEDED"), and TE-96 sec 4.7's
  // three named cross-entry occupancy crossings. See the `Crossing`
  // function's own header comment (above `main`) for the full construction.
  // =========================================================================
  Crossing(a, 1, CallKind::kBatch, CallKind::kBatch,
           "S-6 step 12 (semb_encode_batch -> SEMB_CONCURRENCY_EXCEEDED with the pool's only slot held)", false);
  Crossing(a, 2, CallKind::kBatch, CallKind::kRaw, "S-6 cross-entry occupancy: batch occupies, raw contends", false);
  Crossing(a, 2, CallKind::kRaw, CallKind::kBatch, "S-6 cross-entry occupancy: raw occupies, batch contends", false);
  Crossing(a, 2, CallKind::kBatch, CallKind::kBatch, "S-6 cross-entry occupancy: batch occupies, batch contends",
           /*close_check=*/true);

  // =========================================================================
  // TE-172 N-9(i): the open-time cookie is unobservable to any OTHER
  // caller until `ready` is published (D-SLM6390 item 4; N-1, D-SLM6383).
  // Reproduces the reviewer's own N-1 construction
  // (Claude/Poirot/2c6882c-te167-slice2-reconfirm.md sec 6 F-3): a second
  // thread polls a GUESSED cookie through semb_encoder_dims and
  // semb_wb_digest every 50ms for the whole duration of a real-candidate
  // open (semb_encoder_open, max_concurrency=2) -- zero observations
  // expected; a third thread attempts semb_encoder_close on the same
  // guessed cookie while the open is held between the registry insert and
  // `ready` -- SEMB_INVALID_HANDLE expected, never a crash on a half-built
  // handle.
  //
  // SEQUENCED ON AN EVENT, NOT A DELAY. The reviewer's F-3 construction
  // closed 10s into the call, a delay chosen against a ~19.8s open
  // (D-SLM6352) so the insert had happened and `ready` had not. An open of
  // 6.7s (SuperSLM 1.18.1) has returned its handle by 10s, so the guessed
  // cookie was then the real one and the close succeeded. The closer now
  // waits for the workspace seam's acquisition park (OnAcquired,
  // engine_adapter_interim.cpp), armed for one park before the open: the
  // open's first workspace acquisition is W-B's forward (ComputeWbDigest),
  // which runs after the registry insert and before `ready` is stored
  // (encoder.cpp, semb_encoder_open's HandleInsertGuard) -- nothing earlier
  // in the open acquires a workspace. While the open is parked there the
  // cookie is provably inserted and not ready, whatever the open's speed.
  // The closer closes, then releases the park; the open then completes.
  //
  // PRODUCT-LEG ONLY (a.dims == 1024, this suite's own established
  // real-leg signal, tests/u1_workspace_seam_test.cpp's precedent): the
  // mechanism pair's open completes in well under 50ms, so a polling
  // thread there would report zero observations by construction --
  // vacuous, not evidence, whichever way the guard behaves.
  //
  // THE GUESSED COOKIE is g_cookie_counter's own next value (above), not
  // literal cookie 1: every earlier cell in this file has already opened
  // and closed several handles through the shared Open() helper, and
  // AllocateHandleCookie never resets or reuses a value. No other thread
  // opens concurrently before this point, so the next cookie this
  // process's registry hands out is deterministically g_cookie_counter+1
  // -- confirmed below by comparing the prediction against the cookie the
  // real open actually returns.
  // =========================================================================
  if (a.dims == 1024) {
    const uint64_t predicted_next = g_cookie_counter.load(std::memory_order_acquire) + 1;
    const semb_encoder guess = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(predicted_next));

    std::atomic<int> observations{0};
    std::atomic<bool> stop_polling{false};
    std::thread poller([&] {
      while (!stop_polling.load(std::memory_order_acquire)) {
        uint32_t dims_out = 0;
        if (Is(semb_encoder_dims(guess, &dims_out), "SEMB_OK")) observations.fetch_add(1);
        uint8_t digest_out[32];
        if (Is(semb_wb_digest(guess, digest_out), "SEMB_OK")) observations.fetch_add(1);
        std::this_thread::sleep_for(50ms);
      }
    });
    // The window's event: the open's first workspace acquisition (W-B's
    // forward), after the insert and before `ready`. Armed for one park.
    const bool park_armed = semb_test_seam_arm_park(1) == 1;
    std::atomic<int> close_during_open_status{-1000};
    std::atomic<bool> closed_while_parked{false};
    std::thread closer([&] {
      // A generous bound: the park comes before W-B's forward, early in the open.
      if (park_armed && semb_test_seam_wait_parked(1, 600000) == 1 && semb_test_seam_parked() == 1) {
        close_during_open_status.store(static_cast<int>(semb_encoder_close(guess)));
        // Still parked after the close returned: the close ran inside the window.
        closed_while_parked.store(semb_test_seam_parked() == 1);
      }
      // Always released, so the open completes. A park that has not happened
      // yet will not happen: release clears the budget.
      semb_test_seam_release();
    });

    semb_config c{};
    c.struct_size = sizeof(c);
    c.model_path = a.model.data();
    c.model_path_len = a.model.size();
    c.tokenizer_path = a.tokenizer.data();
    c.tokenizer_path_len = a.tokenizer.size();
    c.max_concurrency = 2;
    semb_encoder opened = nullptr;
    const auto t0 = std::chrono::steady_clock::now();
    const semb_status open_status = semb_encoder_open(&c, &opened);
    const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    stop_polling.store(true, std::memory_order_release);
    poller.join();
    closer.join();

    Verdict(Is(open_status, "SEMB_OK") && opened == guess,
            "N-9(i) (setup) the predicted next cookie (g_cookie_counter+1) matches the cookie the real "
            "open actually issued",
            "predicted=" + std::to_string(predicted_next) + " open_status=" + std::string(Name(open_status)) +
                " elapsed=" + std::to_string(elapsed) + "s");

    Verdict(observations.load() == 0,
            "N-9(i) a second thread polling the guessed cookie's semb_encoder_dims/semb_wb_digest every "
            "50ms for the whole duration of a real open observes ZERO live reads -- the cookie is "
            "unobservable before `ready` is published (D-SLM6390 item 4, N-1/D-SLM6383)",
            "observations=" + std::to_string(observations.load()));

    Verdict(park_armed && closed_while_parked.load(),
            "N-9(i) (setup) the close ran while the open was parked at its W-B forward's workspace "
            "acquisition -- after the registry insert, before `ready`",
            std::string("armed=") + (park_armed ? "1" : "0") +
                " closed_while_parked=" + (closed_while_parked.load() ? "1" : "0"));

    Verdict(Is(static_cast<semb_status>(close_during_open_status.load()), "SEMB_INVALID_HANDLE"),
            "N-9(i) semb_encoder_close on the guessed cookie, attempted while the open is held between "
            "its registry insert and `ready`, returns SEMB_INVALID_HANDLE -- never a crash on a "
            "half-built handle",
            close_during_open_status.load() == -1000
                ? std::string("not attempted: the open never parked")
                : std::string(Name(static_cast<semb_status>(close_during_open_status.load()))));

    if (Is(open_status, "SEMB_OK") && opened) {
      g_cookie_counter.fetch_add(1, std::memory_order_acq_rel);
      const semb_status close_status = semb_encoder_close(opened);
      Verdict(Is(close_status, "SEMB_OK"), "N-9(i) (cleanup) close of the real handle succeeds after the "
                                            "open completes", Name(close_status));
    }
  } else {
    Missing("N-9(i) the open-time cookie is unobservable until ready",
            "mechanism leg: the open completes in well under the polling interval, so no observation "
            "window exists to drive -- product leg only");
  }

  // =========================================================================
  // TE-172 N-9(ii): no cookie survives a FAILED open. Reproduces the
  // reviewer's own N-2 construction
  // (Claude/Poirot/2c6882c-te167-slice2-reconfirm.md sec 6 F-4): operator
  // new throws on the Nth allocation across the TAIL of the open sequence
  // (near ComputeWbDigest's own W-B derivation, well after
  // AllocateHandleCookie has already run -- src/superembedder/encoder.cpp),
  // sweeping trip points ending at the ordinal an untripped open actually
  // needs. Reuses THIS FILE'S OWN aligned global-allocator instrument
  // (leak_hook, above -- the D-SLM6353/S-5 alignment fix applies here too)
  // rather than a second hook: a TU installs only one global operator
  // new/delete pair, and leak_hook already is this file's.
  //
  // THE DETECTION IS THE FILE'S OWN LIVE-ALLOCATION COUNT (C49's own
  // technique, above), NOT a semb_encoder_dims probe on the guessed
  // cookie -- found by execution, not assumed: `ready` (D-SLM6390 item 4)
  // gates semb_encoder_dims/semb_wb_digest/semb_encoder_close alike
  // through FindReadyHandleLocked, and a leaked-but-never-ready entry is
  // refused SEMB_INVALID_HANDLE by that gate WHETHER OR NOT
  // HandleInsertGuard ever erases it -- so a cookie probe cannot
  // distinguish "erased" from "leaked but not yet ready" and would pass
  // under a neutered guard exactly as it passes under the real one
  // (executed: a scratch build with HandleInsertGuard's destructor
  // neutered reports 0 leaks under a cookie-probe check -- Claude/Curie's
  // own record for this round names the reading). The guard's OWN job is
  // freeing the partially-built handle -- its owned interim encoder and
  // tokenizer copy included -- and that IS observable: every TRIPPED
  // trial's own live-allocation count must return to its pre-trial
  // reading once the failed open returns, with no explicit close (there
  // is no cookie to close), because the guard's destructor runs on the
  // SAME stack unwind that returns SEMB_ALLOCATION_FAILED.
  //
  // MECHANISM-LEG ONLY: the sweep needs one baseline open plus up to 200
  // trials; at the real artifact's ~19.8s/open (D-SLM6352) that is
  // unaffordable, and it is unnecessary -- the guard's own correctness
  // does not depend on artifact size (TE-165's own build record makes the
  // identical call for its own re-execution of this construction).
  // =========================================================================
  if (a.dims != 1024) {
    auto open_raw = [&](semb_encoder* out) {
      semb_config c{};
      c.struct_size = sizeof(c);
      c.model_path = a.model.data();
      c.model_path_len = a.model.size();
      c.tokenizer_path = a.tokenizer.data();
      c.tokenizer_path_len = a.tokenizer.size();
      c.max_concurrency = 1;
      return semb_encoder_open(&c, out);
    };

    // Warm-up (unmeasured): one throwaway open+close before any
    // measurement begins, so a one-time lazy static/pool cost the interim
    // engine pays on its FIRST open (C49's own established caveat, above)
    // does not read as this cell's own "excess."
    {
      semb_encoder warm = nullptr;
      open_raw(&warm);
      if (warm) semb_encoder_close(warm);
    }

    // Baseline: one untripped open, closed. Its own allocation DELTA (not
    // the process-wide total, which already carries every earlier cell's
    // own allocations) is the tail window's own upper edge, and its
    // live-allocation reading once closed is the reading every TRIPPED
    // trial is compared against (a full open+close cycle already returns
    // to its own pre-open reading, C49's own established property, above).
    const uint64_t before = leak_hook::g_alloc_ordinal.load(std::memory_order_acquire);
    const int64_t live_before_baseline = leak_hook::g_live_allocations.load(std::memory_order_acquire);
    semb_encoder baseline = nullptr;
    const semb_status baseline_status = open_raw(&baseline);
    const uint64_t after = leak_hook::g_alloc_ordinal.load(std::memory_order_acquire);
    Verdict(Is(baseline_status, "SEMB_OK") && baseline != nullptr,
            "N-9(ii) (setup) one untripped mechanism-pair open succeeds, to measure its own allocation cost",
            Name(baseline_status));
    if (Is(baseline_status, "SEMB_OK") && baseline) {
      const uint64_t baseline_delta = after - before;
      semb_encoder_close(baseline);
      const int64_t live_after_baseline = leak_hook::g_live_allocations.load(std::memory_order_acquire);
      Verdict(live_after_baseline == live_before_baseline,
              "N-9(ii) (setup) the live-allocation count returns to its pre-open reading after the "
              "untripped open's own close",
              "before=" + std::to_string(live_before_baseline) + " after=" + std::to_string(live_after_baseline));

      // TE-172: the pass/fail line is a THRESHOLD, not zero, calibrated by
      // execution against a known-healthy and a known-defective build
      // (StandardsDocument.md sec 5.4's inert-vs-moving calibration),
      // because zero is not the correct-code reading. Executed against
      // THIS committed cell, real (guarded) code: every trial's own
      // per-trip excess is small and DECELERATES across the sweep (max
      // single-trial excess 8; cumulative growth over 200 trials ~1,286,
      // converging rather than compounding -- consistent with a bounded,
      // one-time cost paid across the first several tail-region trials,
      // not a per-trip leak). Against a scratch build with
      // HandleInsertGuard's own destructor neutered (the must-reject,
      // §"mutation-proof" below): every trial's own excess is
      // large and does NOT decelerate (~2,381-2,400 every trial, ~477,101
      // cumulative over 200 trials) -- the entire leaked handle, its
      // tokenizer copy and its interim encoder included. kLeakThreshold
      // sits at 25x the healthy build's own observed ceiling and under
      // 1/10th the defective build's own observed floor -- a minimum
      // effect size the check can act on, not a razor edge either
      // execution's own sampling noise could cross.
      constexpr int64_t kLeakThreshold = 200;

      const uint64_t window = baseline_delta > 200 ? 200 : (baseline_delta > 0 ? baseline_delta : 1);
      int tripped = 0, leaks = 0, untripped = 0;
      int64_t max_excess = 0, cumulative_excess = 0;
      std::string leak_detail;
      for (uint64_t trial = 0; trial < window; ++trial) {
        // Sweeps the TAIL, ending exactly at baseline_delta.
        const uint64_t trip_offset = baseline_delta - window + 1 + trial;
        const uint64_t trial_before = leak_hook::g_alloc_ordinal.load(std::memory_order_acquire);
        const int64_t live_before_trial = leak_hook::g_live_allocations.load(std::memory_order_acquire);
        leak_hook::ArmFailAtOrdinal(trial_before + trip_offset);
        semb_encoder trial_handle = nullptr;
        const semb_status trial_status = open_raw(&trial_handle);
        leak_hook::DisarmFail();  // one-shot already on a fired trip; clears an untripped one too

        if (Is(trial_status, "SEMB_OK") && trial_handle) {
          ++untripped;  // the target ordinal was beyond this run's own total -- legitimate, not a defect
          semb_encoder_close(trial_handle);
        } else {
          ++tripped;
          const int64_t live_after_trial = leak_hook::g_live_allocations.load(std::memory_order_acquire);
          const int64_t excess = live_after_trial - live_before_trial;
          if (excess > 0) cumulative_excess += excess;
          if (excess > kLeakThreshold) {
            ++leaks;
            max_excess = excess > max_excess ? excess : max_excess;
            leak_detail += " trip#" + std::to_string(trial) + "(excess=" + std::to_string(excess) + ")";
          }
        }
      }
      Verdict(leaks == 0,
              "N-9(ii) no cookie survives a FAILED open: sweeping " + std::to_string(window) +
                  " injected-allocation-failure trip points across the tail of the open sequence, no "
                  "TRIPPED trial's own live-allocation excess exceeds the commissioned threshold (" +
                  std::to_string(kLeakThreshold) + ") -- the guard's rollback frees the leaked handle "
                  "immediately, with no explicit close",
              std::to_string(tripped) + " of " + std::to_string(window) + " trip(s) fired, " +
                  std::to_string(untripped) + " untripped, " + std::to_string(leaks) +
                  " over-threshold trip(s), max excess " + std::to_string(max_excess) +
                  ", cumulative excess " + std::to_string(cumulative_excess) + leak_detail);
    }
  } else {
    Missing("N-9(ii) no cookie survives a failed open",
            "real leg: a 201-open sweep (D-SLM6352: ~19.8s/open) is unaffordable and unnecessary -- the "
            "guard's own correctness does not depend on artifact size -- mechanism leg only");
  }

  // =========================================================================
  // C52 (TE-350): the RE-STATED workspace contract for T > 1. Every cell
  // above this one opens its handle with a pool of size 1 (Open(a) defaults
  // to 1; every explicit Open(a, n>1) in this file only ever issues
  // SINGLE-document batch calls through it, via Crossing's own per-occupant
  // BatchCall), so T = min(doc_count, pool, hardware concurrency) has been
  // forced to 1 in every earlier cell -- none of them can tell a genuinely
  // parallel acquisition from the original single-workspace path. This cell
  // opens a pool of kPoolSize > 1 and issues a batch call over MORE
  // documents than the pool, so T == min(kPoolSize, hardware concurrency)
  // -- the product's own T formula (engine_adapter_interim.cpp's
  // HardwareConcurrencyOrOne()), computed here rather than assumed: a hosted
  // CI runner with fewer hardware threads than kPoolSize realizes a smaller
  // T, and this cell asserts against that T (kParallel below). On a host
  // whose T would be 1 the cell cannot observe parallelism at all and is
  // reported [MISSING PREREQUISITE] rather than failed. With that T, the
  // cell proves, at the seam's own per-acquisition
  // granularity (OnAcquired fires once per slot acquired, TE-350's own
  // restatement above):
  //
  //   1. the call genuinely acquires MORE than one workspace (T of
  //      them, parked simultaneously -- not T sequential
  //      acquisitions disguised as one observation);
  //   2. every row it produces is byte-identical to a serial (pool-of-1)
  //      reference, for every document, not only the first or the last;
  //   3. every one of the T workspaces acquired is released before
  //      the call returns -- proven by a SECOND full-size call, through the
  //      SAME handle, reaching T simultaneous parks again. A leaked
  //      lease from the first call caps the second call's own parked count
  //      strictly below T, which `semb_test_seam_wait_parked` below
  //      reports as a timeout (a named FAIL, not a silent pass at a lower
  //      number, since the Verdict compares the exact reading to T).
  // =========================================================================
  {
    constexpr unsigned kPoolSize = 4;
    constexpr unsigned kDocCount = 9;  // > kPoolSize, so every worker's own queue holds > 1 document
    // T = min(documents, pool, hardware concurrency), exactly as production
    // computes it; kDocCount > kPoolSize, so the document bound never binds.
    const unsigned hc_raw = std::thread::hardware_concurrency();
    const unsigned kParallel = std::min(kPoolSize, hc_raw == 0 ? 1u : hc_raw);
    std::vector<std::pair<std::string, std::string>> docs_named;
    for (unsigned i = 0; i < kDocCount; ++i) {
      docs_named.emplace_back("c52-" + std::to_string(i),
                              "TE-350 parallel workspace document number " + std::to_string(i));
    }

    // The serial reference: one document at a time, through a pool-of-1
    // handle -- the ORIGINAL, unchanged single-workspace path.
    std::vector<std::vector<uint8_t>> reference;
    {
      semb_encoder serial = Open(a, 1);
      if (serial) {
        for (auto& [id, text] : docs_named) {
          semb_status s = -1000;
          reference.push_back(BakeOne(serial, id, text, dims, &s));
          Verdict(Is(s, "SEMB_OK"), "C52 (setup) serial reference row for " + id, Name(s));
        }
        semb_encoder_close(serial);
      }
    }

    semb_encoder enc = kParallel >= 2 ? Open(a, kPoolSize) : nullptr;
    if (kParallel < 2) {
      Missing("C52",
              "hardware_concurrency()=" + std::to_string(hc_raw) +
                  " makes T = 1, so no parallel acquisition exists to observe");
    } else if (enc && reference.size() == kDocCount) {
      ResetSeam(deadline30());

      std::vector<semb_document> docs;
      for (auto& [id, text] : docs_named) docs.push_back(MakeDoc(id, text));
      std::vector<uint8_t> buf((docs.size() * required1) + 64, 0xA5);
      auto p = reinterpret_cast<uintptr_t>(buf.data());
      float* aligned = reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));

      auto RunFullPoolBatch = [&](const char* label) -> bool {
        Verdict(semb_test_seam_arm_park(kParallel) == 1,
                std::string(label) + " (setup) arm " + std::to_string(kParallel) + " park(s)", "");
        size_t req = 0xBAD5EED;
        semb_status batch_status = -1000;
        auto job = std::async(std::launch::async, [&] {
          batch_status = semb_encode_batch(enc, docs.data(), docs.size(), aligned, buf.size() - 16, &req);
        });
        const bool all_parked =
            semb_test_seam_wait_parked(kParallel, 10000) == 1 && semb_test_seam_parked() == kParallel;
        Verdict(all_parked,
                std::string(label) + " all " + std::to_string(kParallel) +
                    " workspace(s) acquired and parked SIMULTANEOUSLY (T = min(kPoolSize=" +
                    std::to_string(kPoolSize) + ", hardware_concurrency()) > 1 genuinely reached, not "
                    "T sequential single-workspace acquisitions)",
                "parked=" + std::to_string(semb_test_seam_parked()));
        if (all_parked) {
          const uint64_t acquisitions = semb_test_seam_acquisitions();
          Verdict(acquisitions >= kParallel,
                  std::string(label) + " at least T acquisitions recorded while parked",
                  std::to_string(acquisitions));
        }
        ReleaseBounded(deadline30());
        if (job.wait_until(deadline30()) != std::future_status::ready) {
          FatalTimeout((std::string(label) + " job cleanup deadline").c_str());
        }
        job.get();
        Verdict(Is(batch_status, "SEMB_OK"), std::string(label) + " the batch call completes successfully",
                Name(batch_status));
        return Is(batch_status, "SEMB_OK");
      };

      const bool first_ok = RunFullPoolBatch("C52-first");
      if (first_ok) {
        bool rows_match = true;
        for (size_t i = 0; i < kDocCount; ++i) {
          auto b = reinterpret_cast<uint8_t*>(aligned) + i * required1;
          const std::vector<uint8_t> row(b, b + required1);
          if (row != reference[i]) rows_match = false;
        }
        Verdict(rows_match,
                "C52 every one of " + std::to_string(kDocCount) +
                    " documents in a genuinely T = " + std::to_string(kParallel) +
                    " parallel batch call is byte-identical to "
                    "the serial (pool-of-1) reference -- threading changes only which worker computes "
                    "which document, never what it computes",
                "");
      }

      // The leak-detection re-run: every workspace the first call acquired
      // must be released before this second call, through the SAME handle,
      // can reach kPoolSize simultaneous parks again.
      ResetSeam(deadline30());
      RunFullPoolBatch("C52-second (leak detection: every lease from the first call is released)");

      semb_encoder_close(enc);
      ResetSeam(deadline30());
    } else {
      Verdict(false, "C52 (setup) contended handle open or serial reference", "");
    }
  }

  std::printf("\nu1_batch_workspace_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
