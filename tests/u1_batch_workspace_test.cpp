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
#include <utility>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "support/semb_workspace_seam.h"

using namespace std::chrono_literals;

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
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }
bool Is(semb_status s, const char* name) { return s == semb_contract::StatusByName(name); }

struct Args {
  std::string model, tokenizer;
  unsigned dims = 0;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--dims") { std::string v; next(&v); a.dims = static_cast<unsigned>(std::atoi(v.c_str())); }
  }
  return a;
}

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

  std::printf("\nu1_batch_workspace_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
