// TE-110: independent K-15 cells, adopted TE-96 section 3.
#include "semb_public_abi_contract.h"
#include "support/semb_workspace_seam.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <future>
#include <condition_variable>
#include <mutex>
#include <string>
#include <vector>

using namespace std::chrono_literals;
namespace {
int failures = 0;
#ifdef SEMB_WORKSPACE_DELAY_REFUSAL_HELPERS
std::mutex completion_mutex;
std::condition_variable completion_changed;
unsigned completed_workers = 0;
void WorkerFinished() {
  { std::lock_guard<std::mutex> lock(completion_mutex); ++completed_workers; }
  completion_changed.notify_all();
}
void DelayRefusalHelper(unsigned expected) {
  std::unique_lock<std::mutex> lock(completion_mutex);
  completion_changed.wait(lock, [=]{return completed_workers == expected;});
}
#else
void WorkerFinished() {}
void DelayRefusalHelper(unsigned) {}
#endif
std::chrono::steady_clock::time_point cleanup_deadline;
bool cleanup_started = false;
void BeginCleanup() {
  if (!cleanup_started) {cleanup_deadline = std::chrono::steady_clock::now() + 30s; cleanup_started = true;}
}
void Check(bool ok, const std::string& phase) {
  std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", phase.c_str());
  std::fflush(stdout);
  if (!ok) ++failures;
}
void Phase(const char* text) { std::printf("[PHASE] %s\n", text); std::fflush(stdout); }
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<null>"; }
bool Status(semb_status s, const char* name) { return s == semb_contract::StatusByName(name); }
struct Args { std::string model, tokenizer, cell, text; unsigned dims = 0; bool print = false, armed = false; };
struct Output {
  std::vector<float> storage;
  size_t required = 0xBAD5EED;
  semb_fingerprint fingerprint{};
  semb_status status = -1000;
  explicit Output(unsigned dims): storage(dims + 16) {
    std::memset(storage.data(), 0xA5, storage.size() * sizeof(float));
    fingerprint.struct_size = sizeof(fingerprint);
    std::memset(fingerprint.digest, 0xC3, sizeof(fingerprint.digest));
  }
  float* data() { auto p = reinterpret_cast<uintptr_t>(storage.data()) + 16; return reinterpret_cast<float*>((p + 15) & ~uintptr_t(15)); }
  std::vector<unsigned char> bytes(unsigned dims) {
    auto p = reinterpret_cast<unsigned char*>(data()); return {p, p + dims * sizeof(float)};
  }
  bool untouched() {
    for (auto b: std::vector<unsigned char>(reinterpret_cast<unsigned char*>(storage.data()), reinterpret_cast<unsigned char*>(storage.data() + storage.size()))) if (b != 0xA5) return false;
    for (auto b: fingerprint.digest) if (b != 0xC3) return false;
    return required == 0xBAD5EED && fingerprint.struct_size == sizeof(fingerprint);
  }
  bool guards(unsigned dims) {
    auto begin = reinterpret_cast<unsigned char*>(storage.data());
    auto first = reinterpret_cast<unsigned char*>(data());
    auto end = reinterpret_cast<unsigned char*>(storage.data() + storage.size());
    return std::all_of(begin, first, [](auto b){ return b == 0xA5; }) &&
           std::all_of(first + dims * sizeof(float), end, [](auto b){ return b == 0xA5; });
  }
};
semb_encoder Open(const Args& a, unsigned slots) {
  semb_config c{}; c.struct_size = sizeof(c); c.model_path = a.model.data(); c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data(); c.tokenizer_path_len = a.tokenizer.size(); c.max_concurrency = slots;
  semb_encoder enc = nullptr; auto s = semb_encoder_open(&c, &enc);
  if (!Status(s, "SEMB_OK") || !enc) { Check(false, std::string("open: ") + Name(s)); return nullptr; }
  return enc;
}
void Encode(semb_encoder enc, const std::string& doc, Output& out, unsigned dims) {
  out.status = semb_encode(enc, doc.data(), doc.size(), out.data(), dims * sizeof(float), &out.required, &out.fingerprint);
}
bool Success(Output& o, unsigned dims) { return Status(o.status, "SEMB_OK") && o.required == dims * sizeof(float) && o.guards(dims); }
// Process containment is intentional: never destroy a non-ready async future,
// whose destructor can wait forever. The parent also kills/waits at 600 seconds.
void FatalTimeout(const char* phase) { Check(false, phase); std::fflush(nullptr); std::_Exit(1); }
void ReleaseBounded() {
  BeginCleanup(); Phase("release"); auto f = std::async(std::launch::async, []{semb_test_seam_release();});
  if (f.wait_until(cleanup_deadline) != std::future_status::ready) FatalTimeout("cleanup release exceeded 30 seconds"); f.get();
}
void Drain(std::vector<std::future<void>>& jobs) {
  Phase("drain/join");
  if (!cleanup_started) {
    // Unarmed workers must complete without a release. If one sticks, retain
    // that failure and release all parks before the shared cleanup deadline.
    auto forward_deadline = std::chrono::steady_clock::now() + 30s;
    for (auto& f: jobs) if (f.wait_until(forward_deadline) != std::future_status::ready) {
      Check(false, "unarmed worker deadline"); ReleaseBounded(); break;
    }
  }
  BeginCleanup(); auto end = cleanup_deadline;
  for (auto& f: jobs) { if (f.wait_until(end) != std::future_status::ready) FatalTimeout("cleanup drain exceeded 30 seconds"); f.get(); }
}
void Close(semb_encoder enc) {
  BeginCleanup(); Phase("close after join"); auto f = std::async(std::launch::async, [=]{return semb_encoder_close(enc);});
  if (f.wait_until(cleanup_deadline) != std::future_status::ready) FatalTimeout("cleanup close exceeded 30 seconds");
  auto s = f.get(); Check(Status(s, "SEMB_OK"), std::string("close after join: ") + Name(s));
}
void Reset() {
  BeginCleanup(); Phase("reset joined epoch"); auto f = std::async(std::launch::async, []{return semb_test_seam_reset();});
  if (f.wait_until(cleanup_deadline) != std::future_status::ready) FatalTimeout("cleanup reset exceeded 30 seconds");
  Check(f.get() == 1 && semb_test_seam_acquisitions() == 0 && semb_test_seam_parked() == 0, "reset establishes empty epoch");
  cleanup_started = false;
}

// F1: every reset follows joined workers/helpers; the same handle spans two
// occupied epochs. References were captured earlier on a separate serial handle.
void Lifecycle(const Args& a, semb_encoder enc, unsigned n,
               const std::vector<std::string>& docs,
               const std::vector<std::vector<unsigned char>>& reference) {
  auto unarmed = [&](uint64_t expected, const char* phase) {
    Phase(phase); Output out(a.dims); std::vector<std::future<void>> jobs;
    jobs.push_back(std::async(std::launch::async, [&]{Encode(enc, docs[0], out, a.dims);}));
    bool ready = jobs[0].wait_for(10s) == std::future_status::ready;
    Check(ready, std::string(phase) + " completes without rearm/release");
    if (!ready) ReleaseBounded();
    Drain(jobs);
    Check(Success(out, a.dims) && out.bytes(a.dims) == reference[0], std::string(phase) + " serial bytes");
    Check(semb_test_seam_parked() == 0 && semb_test_seam_acquisitions() == expected,
          std::string(phase) + " no park and exact cumulative count");
    cleanup_started = false;
  };
  Phase("K-15h surplus budget");
  const auto before = semb_test_seam_acquisitions();
  Check(semb_test_seam_arm_park(n + 2) == 1 && semb_test_seam_acquisitions() == before,
        "K-15h arm preserves acquisition count");
  Output held(a.dims); std::vector<std::future<void>> one;
  one.push_back(std::async(std::launch::async, [&]{Encode(enc, docs[0], held, a.dims);}));
  Check(semb_test_seam_wait_parked(1, 10000) == 1 && semb_test_seam_parked() == 1,
        "K-15h strict subset acquired and parked");
  const auto acquired = semb_test_seam_acquisitions();
  Check(acquired == before + 1, "K-15h subset counted exactly once");
  ReleaseBounded();
  Check(semb_test_seam_acquisitions() == acquired, "K-15h release preserves count");
  Drain(one);
  Check(Success(held, a.dims) && held.bytes(a.dims) == reference[0], "K-15h released worker serial bytes");
  cleanup_started = false;
  unarmed(before + 2, "K-15h released residual budget");
  // No worker exists here. An unused arm is inside reset's permitted domain.
  const auto before_reset = semb_test_seam_acquisitions();
  Check(semb_test_seam_arm_park(n + 2) == 1 && semb_test_seam_acquisitions() == before_reset,
        "K-15h unused arm preserves prior epoch");
  Reset();
  unarmed(1, "K-15h reset residual budget");
  for (unsigned epoch = 0; epoch < 2; ++epoch) {
    Reset();
    Phase(epoch == 0 ? "K-15h occupied epoch 1" : "K-15h occupied epoch 2 same handle");
    Check(semb_test_seam_arm_park(n) == 1, "K-15h arm occupied epoch");
    std::vector<Output> outputs; for (unsigned i = 0; i < n; ++i) outputs.emplace_back(a.dims);
    std::vector<std::future<void>> jobs;
    for (unsigned i = 0; i < n; ++i) jobs.push_back(std::async(std::launch::async, [&, i]{Encode(enc, docs[i], outputs[i], a.dims); WorkerFinished();}));
    bool occupied = semb_test_seam_wait_parked(n, 10000) == 1 && semb_test_seam_parked() == n;
    Check(occupied, "K-15h occupied reused epoch");
    if (occupied) {
      const auto count = semb_test_seam_acquisitions();
      Check(count == n, "K-15h fresh epoch exact N acquisitions");
      Output rejected(a.dims);
      auto helper = std::async(std::launch::async, [&]{Encode(enc, docs[0], rejected, a.dims);});
      bool ready = helper.wait_for(10s) == std::future_status::ready;
      Check(ready, "K-15h reused epoch refusal deadline");
      if (ready) {
        helper.get();
        Check(Status(rejected.status, "SEMB_CONCURRENCY_EXCEEDED") && rejected.untouched() &&
              semb_test_seam_acquisitions() == count, "K-15h reused epoch refusal/canaries/count");
      }
      ReleaseBounded();
      if (!ready) {
        if (helper.wait_until(cleanup_deadline) != std::future_status::ready) FatalTimeout("K-15h helper cleanup deadline");
        helper.get();
      }
    } else ReleaseBounded();
    Drain(jobs);
    for (unsigned i = 0; i < n; ++i)
      Check(Success(outputs[i], a.dims) && outputs[i].bytes(a.dims) == reference[i], "K-15h reused epoch worker serial bytes");
    Check(semb_test_seam_parked() == 0 && semb_test_seam_acquisitions() == n, "K-15h drained epoch state");
    cleanup_started = false;
  }
}
}
int main(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    if (k == "--armed") { a.armed = true; continue; }
    if (i + 1 == argc) return 2;
    std::string v = argv[++i];
    if (k == "--model") a.model = v; else if (k == "--tokenizer") a.tokenizer = v;
    else if (k == "--dims") a.dims = std::stoul(v); else if (k == "--cell") a.cell = v;
    else if (k == "--print-vector-hex") {a.print = true; a.text = v;} else return 2;
  }
  if (a.model.empty() || a.tokenizer.empty() || !a.dims) return 2;
  if (!a.print && a.cell != "K-15d" && a.cell != "K-15e" && a.cell != "K-15f" && a.cell != "K-15g" && a.cell != "K-15h") return 2;
  Phase("startup before any encode/reset");
  Check(semb_test_seam_acquisitions() == 0 && semb_test_seam_parked() == 0, "K-15h startup epoch is empty");
  if (failures) return 1;
  const unsigned n = a.dims == 1024 ? 2 : 3;
  std::vector<std::string> docs = {"A small red boat.", "The green forest grows.", "Numbers: 17, 29, 43."};
  if (a.print) docs = {a.text};
  else if (a.cell != "K-15f") docs.resize(n);
  // Fresh serial handle is closed before opening the contended handle: real
  // workspace memory never includes both pools simultaneously.
  Phase("fresh-handle serial controls");
  auto serial = Open(a, 1); if (!serial) return 1;
  std::vector<std::vector<unsigned char>> reference;
  for (const auto& doc: docs) { Output out(a.dims); Encode(serial, doc, out, a.dims); Check(Success(out, a.dims), std::string("serial encode: ") + Name(out.status)); reference.push_back(out.bytes(a.dims)); }
  const std::string retry_doc = "A retry after refusal.";
  Output retry_reference(a.dims); Encode(serial, retry_doc, retry_reference, a.dims);
  Check(Success(retry_reference, a.dims), "serial retry reference"); Close(serial); cleanup_started = false;
  if (failures) return 1;
  auto enc = Open(a, (a.cell == "K-15f" || a.print) ? 1 : n); if (!enc) return 1;
  Reset();
  if (a.cell == "K-15h") {Lifecycle(a, enc, n, docs, reference); Close(enc); Reset(); return failures ? 1 : 0;}
  if (a.cell == "K-15f" || a.print) {
    for (size_t i = 0; i < docs.size(); ++i) {
      const bool armed = !a.print || a.armed;
      Check(semb_test_seam_arm_park(armed ? 1 : 0) == 1, "arm parity call");
      Output out(a.dims); std::vector<std::future<void>> jobs;
      jobs.push_back(std::async(std::launch::async, [&]{Encode(enc, docs[i], out, a.dims);}));
      if (armed) { Phase("parity rendezvous"); Check(semb_test_seam_wait_parked(1, 10000) == 1 && semb_test_seam_parked() == 1, "K-15f acquired park before release"); }
      ReleaseBounded(); Drain(jobs);
      Check(Success(out, a.dims) && out.bytes(a.dims) == reference[i], "K-15f serial bytes after seam call");
      cleanup_started = false;
      if (a.print && !failures) { std::printf("VECTOR_HEX "); for (auto b: out.bytes(a.dims)) std::printf("%02x", b); std::printf("\n"); }
    }
  } else {
    const bool inert = a.cell == "K-15g";
    Check(semb_test_seam_arm_park(inert ? 0 : n) == 1, "arm requested budget");
    std::vector<Output> outputs; for (unsigned i = 0; i < n; ++i) outputs.emplace_back(a.dims);
    std::vector<std::future<void>> jobs;
    for (unsigned i = 0; i < n; ++i) jobs.push_back(std::async(std::launch::async, [&, i]{Encode(enc, docs[i], outputs[i], a.dims); WorkerFinished();}));
    if (!inert) {
      Phase("occupancy rendezvous");
      bool occupied = semb_test_seam_wait_parked(n, 10000) == 1 && semb_test_seam_parked() == n;
      Check(occupied, a.cell + " exactly N acquired and parked");
      if (occupied) {
        auto before = semb_test_seam_acquisitions(); Check(before == n, "exact N acquisitions while parked");
        Check(semb_test_seam_arm_park(1) == 0 && semb_test_seam_parked() == n && semb_test_seam_acquisitions() == before, "arm refuses unchanged while parked");
        if (a.cell == "K-15d") {
          Output rejected(a.dims); auto f = std::async(std::launch::async, [&]{
            DelayRefusalHelper(n); Encode(enc, retry_doc, rejected, a.dims);
#ifdef SEMB_WORKSPACE_DELAY_REFUSAL_HELPERS
            std::printf("[CONTROL] late encode actual result: %s\n", Name(rejected.status)); std::fflush(stdout);
#endif
          });
          Phase("exhausted encode refusal"); bool ready = f.wait_for(10s) == std::future_status::ready;
          Check(ready, "K-15d refusal deadline");
          if (ready) {f.get(); Check(Status(rejected.status, "SEMB_CONCURRENCY_EXCEEDED"), std::string("K-15d refusal: ") + Name(rejected.status)); Check(rejected.untouched(), "K-15d all output canaries untouched"); Check(semb_test_seam_acquisitions() == before, "K-15d no additional acquisition");}
          ReleaseBounded();
          if (!ready) {if(f.wait_until(cleanup_deadline) != std::future_status::ready) FatalTimeout("exhausted helper drain exceeded 30 seconds"); f.get();}
        } else {
          auto f = std::async(std::launch::async, [=]{
            DelayRefusalHelper(n); auto result = semb_encoder_close(enc);
#ifdef SEMB_WORKSPACE_DELAY_REFUSAL_HELPERS
            std::printf("[CONTROL] late close actual result: %s\n", Name(result)); std::fflush(stdout);
#endif
            return result;
          });
          Phase("close refusal"); bool ready = f.wait_for(10s) == std::future_status::ready;
          Check(ready, "K-15e close refusal deadline");
          if (ready) {auto s=f.get(); Check(Status(s, "SEMB_HANDLE_IN_USE"), std::string("K-15e refusal: ") + Name(s));}
          ReleaseBounded();
          if (!ready) {if(f.wait_until(cleanup_deadline) != std::future_status::ready) FatalTimeout("close helper drain exceeded 30 seconds"); f.get();}
        }
      } else ReleaseBounded();
    } else {
      // Zero parked before and after joining; an unintended parked worker
      // cannot complete and therefore trips this bounded future wait.
      Check(semb_test_seam_parked() == 0, "K-15g unarmed parked count zero");
    }
    Drain(jobs);
    for (unsigned i = 0; i < n; ++i) Check(Success(outputs[i], a.dims) && outputs[i].bytes(a.dims) == reference[i], a.cell + " worker " + std::to_string(i) + " serial bytes");
    Check(semb_test_seam_parked() == 0, a.cell + " no parks after join");
    Check(semb_test_seam_acquisitions() == n, a.cell + " exactly N successful acquisitions");
    Output retry(a.dims); Encode(enc, retry_doc, retry, a.dims);
    Check(Success(retry, a.dims) && retry.bytes(a.dims) == retry_reference.bytes(a.dims), a.cell + " retry uses surviving handle and serial bytes");
  }
  Close(enc); Reset(); return failures ? 1 : 0;
}
