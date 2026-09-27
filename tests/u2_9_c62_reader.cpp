// tests/u2_9_c62_reader.cpp -- U2 cloud build, U2-9's C62: the reading and
// comparison code. See u2_9_c62_reader.h for the steps (P:2731-2741) and the
// entry points a calibration process uses.
#include "u2_9_c62_reader.h"

#include <cstring>

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <psapi.h>
#endif

namespace semb_c62 {

const char* CounterName(Counter c) { return c == kWorkingSet ? "working set" : "private bytes"; }

double OpenBoundMiB(uint32_t max_concurrency, Counter c) {
  // P:2757-2760: design (TE-398's fixed part less the product's copy) + 8 MiB.
  if (max_concurrency == 1) return c == kWorkingSet ? 641.2 : 646.9;
  if (max_concurrency == 4) return c == kWorkingSet ? 641.9 : 657.2;
  return 0.0;
}

#if defined(_WIN32)
namespace {
// QueryWorkingSetEx's buffer: static, so a leg allocates nothing but its
// ballast. 4,096 entries = 16 MiB of ballast per call on 4 KiB pages.
constexpr size_t kQueryChunk = 4096;
PSAPI_WORKING_SET_EX_INFORMATION g_query[kQueryChunk];
uint64_t g_page = 0;
}  // namespace

bool PlatformSupported() { return true; }

void InitInstrument() {
  if (g_page != 0) return;
  SYSTEM_INFO si{};
  GetSystemInfo(&si);
  g_page = si.dwPageSize ? si.dwPageSize : 4096;
  std::memset(g_query, 0, sizeof(g_query));
}

uint64_t PageSize() {
  InitInstrument();
  return g_page;
}

Counters Read() {
  Counters r;
  PROCESS_MEMORY_COUNTERS_EX pmc{};
  pmc.cb = sizeof(pmc);
  if (!GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc),
                            sizeof(pmc)))
    return r;
  r.ok = true;
  r.current[kWorkingSet] = pmc.WorkingSetSize;
  r.peak[kWorkingSet] = pmc.PeakWorkingSetSize;
  r.current[kPrivateBytes] = pmc.PrivateUsage;
  r.peak[kPrivateBytes] = pmc.PeakPagefileUsage;
  return r;
}

void* CommitAndTouch(uint64_t bytes, uint64_t* out_committed_bytes) {
  InitInstrument();
  const uint64_t pages = (bytes + g_page - 1) / g_page;
  const uint64_t size = pages * g_page;
  if (out_committed_bytes) *out_committed_bytes = 0;
  if (size == 0) return nullptr;
  void* base = VirtualAlloc(nullptr, static_cast<SIZE_T>(size), MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
  if (!base) return nullptr;
  // Every page written, and no two pages alike (page index and address), so
  // every page is resident and memory combining has nothing to merge.
  auto* p = static_cast<volatile uint8_t*>(base);
  for (uint64_t k = 0; k < pages; ++k) {
    volatile uint64_t* w = reinterpret_cast<volatile uint64_t*>(p + k * g_page);
    w[0] = k ^ 0xC62C62C62C62C62Cull;
    w[1] = reinterpret_cast<uintptr_t>(p + k * g_page);
  }
  if (out_committed_bytes) *out_committed_bytes = size;
  return base;
}

void Release(void* base) {
  if (base) VirtualFree(base, 0, MEM_RELEASE);
}

namespace {
// Precondition 2 (P:2739-2741): pages of [base, base + bytes) not Valid in the
// working set.
uint64_t NonResidentPages(void* base, uint64_t bytes) {
  const uint64_t pages = bytes / g_page;
  uint64_t missing = 0;
  for (uint64_t first = 0; first < pages; first += kQueryChunk) {
    const size_t n = static_cast<size_t>(pages - first < kQueryChunk ? pages - first : kQueryChunk);
    for (size_t i = 0; i < n; ++i) {
      g_query[i].VirtualAddress = static_cast<uint8_t*>(base) + (first + i) * g_page;
      g_query[i].VirtualAttributes.Flags = 0;
    }
    if (!QueryWorkingSetEx(GetCurrentProcess(), g_query, static_cast<DWORD>(n * sizeof(g_query[0]))))
      return pages;  // unreadable: treated as not resident, so no verdict
    for (size_t i = 0; i < n; ++i)
      if (!g_query[i].VirtualAttributes.Valid) ++missing;
  }
  return missing;
}
}  // namespace

#else  // !_WIN32: C62 is Windows only (P:2845). Everything reports unsupported.

bool PlatformSupported() { return false; }
void InitInstrument() {}
uint64_t PageSize() { return 4096; }
Counters Read() { return Counters{}; }
void* CommitAndTouch(uint64_t, uint64_t* out_committed_bytes) {
  if (out_committed_bytes) *out_committed_bytes = 0;
  return nullptr;
}
void Release(void*) {}
namespace {
uint64_t NonResidentPages(void*, uint64_t bytes) { return bytes / 4096 + 1; }
}  // namespace

#endif

bool BeginExcursion(Ballast* b) {
  InitInstrument();
  *b = Ballast{};
  b->before = Read();
  if (!b->before.ok) return false;
  uint64_t gap = 0;
  for (int c = 0; c < kCounters; ++c) {
    const uint64_t g = b->before.peak[c] > b->before.current[c] ? b->before.peak[c] - b->before.current[c] : 0;
    if (g > gap) gap = g;
  }
  // 1 MiB larger than the larger gap, rounded up to a page by CommitAndTouch.
  b->base = CommitAndTouch(gap + static_cast<uint64_t>(kMiB), &b->bytes);
  if (!b->base) return false;
  b->raised = Read();
  b->floor_ok = FloorAboveEarlierPeaks(b->before, b->raised);
  return true;
}

bool FloorAboveEarlierPeaks(const Counters& before, const Counters& raised) {
  if (!before.ok || !raised.ok) return false;
  for (int c = 0; c < kCounters; ++c)
    if (raised.current[c] < before.peak[c]) return false;
  return true;
}

void EndExcursion(Ballast* b, const Counters& base, bool action_ok, LegReading* out) {
  // Step 2 first: nothing runs between the action and this reading.
  const Counters after = Read();
  LegReading& r = *out;
  r = LegReading{};
  r.after = after;
  r.base = base;
  r.ballasted = true;
  r.action_ok = action_ok;
  r.ballast_committed = b->base != nullptr;
  r.ballast_bytes = b->bytes;
  r.before = b->before;
  r.raised = b->raised;
  r.floor_ok = b->floor_ok;
  for (int c = 0; c < kCounters; ++c)
    r.floor_gap_bytes[c] = b->raised.peak[c] > b->raised.current[c] ? b->raised.peak[c] - b->raised.current[c] : 0;
  if (r.ballast_committed) {
    // Step 4.
    r.nonresident_pages = NonResidentPages(b->base, b->bytes);
    r.resident_ok = r.nonresident_pages == 0;
    // Step 3.
    ComputeStep3(&r);
  }
  Release(b->base);
  b->base = nullptr;
}

void ComputeStep3(LegReading* r) {
  for (int c = 0; c < kCounters; ++c) {
    // The ballast's size on this counter, as step 1 read it in this run.
    r->ballast_charge_mib[c] = MiB(r->raised.current[c]) - MiB(r->before.current[c]);
    r->excursion_mib[c] = MiB(r->after.peak[c]) - MiB(r->raised.current[c]);
    r->steady_mib[c] = MiB(r->after.current[c]) - r->ballast_charge_mib[c] - MiB(r->base.current[c]);
  }
}

Grade GradeAtMost(double reading_mib, double bound_mib, bool preconditions_hold) {
  Grade g;
  g.reading_mib = reading_mib;
  g.bound_mib = bound_mib;
  if (!preconditions_hold || bound_mib <= 0.0) {
    g.verdict = Verdict::kNoVerdict;
  } else {
    g.verdict = reading_mib <= bound_mib ? Verdict::kPass : Verdict::kFail;
  }
  return g;
}

Grade GradeOpen(const Counters& post_open, uint32_t max_concurrency, Counter c) {
  return GradeAtMost(MiB(post_open.current[c]), OpenBoundMiB(max_concurrency, c), post_open.ok);
}

Grade GradeSteady(const LegReading& leg, Counter c, double bound_mib) {
  return GradeAtMost(leg.steady_mib[c], bound_mib, leg.preconditions_hold());
}

Grade GradeExcursion(const LegReading& leg, Counter c, double bound_mib) {
  return GradeAtMost(leg.excursion_mib[c], bound_mib, leg.ballasted && leg.preconditions_hold());
}

Verdict Report(std::FILE* out, const char* cell, Counter c, const char* what, const Grade& g) {
  const char* tag = g.verdict == Verdict::kPass ? "PASS" : g.verdict == Verdict::kFail ? "FAIL" : "NO VERDICT";
  std::fprintf(out, "[%s] %s %s: %s %.1f MiB %s %.1f MiB\n", tag, cell, CounterName(c), what, g.reading_mib,
               g.verdict == Verdict::kFail ? ">" : g.verdict == Verdict::kPass ? "<=" : "vs", g.bound_mib);
  std::fflush(out);
  return g.verdict;
}

void PrintCounters(std::FILE* out, const char* label, const Counters& r) {
  if (!r.ok) {
    std::fprintf(out, "  %-22s (no reading)\n", label);
    return;
  }
  std::fprintf(out, "  %-22s WS %.1f MiB (peak %.1f)  private %.1f MiB (peak %.1f)\n", label,
               MiB(r.current[kWorkingSet]), MiB(r.peak[kWorkingSet]), MiB(r.current[kPrivateBytes]),
               MiB(r.peak[kPrivateBytes]));
}

void PrintLeg(std::FILE* out, const char* cell, const LegReading& leg) {
  std::fprintf(out, "%s: readings\n", cell);
  PrintCounters(out, "base (post-open)", leg.base);
  if (leg.ballasted) {
    PrintCounters(out, "step 1, before ballast", leg.before);
    std::fprintf(out, "  %-22s %.1f MiB (%llu B) committed and touched\n", "ballast", MiB(leg.ballast_bytes),
                 static_cast<unsigned long long>(leg.ballast_bytes));
    PrintCounters(out, "step 1, raised floor", leg.raised);
    for (int c = 0; c < kCounters; ++c) {
      const double excess = leg.ballast_charge_mib[c] - MiB(leg.ballast_bytes);
      std::fprintf(out, "  %-22s ballast charge %.2f MiB (bytes %+.2f MiB, 1/%.0f of them): what steady subtracts\n",
                   CounterName(static_cast<Counter>(c)), leg.ballast_charge_mib[c], excess,
                   excess > 0 && leg.ballast_bytes ? MiB(leg.ballast_bytes) / excess : 0.0);
    }
  }
  PrintCounters(out, "after", leg.after);
  for (int c = 0; c < kCounters; ++c) {
    const Counter k = static_cast<Counter>(c);
    if (leg.ballasted)
      std::fprintf(out, "  %-22s steady %+.1f MiB  excursion %.1f MiB\n", CounterName(k), leg.steady_mib[c],
                   leg.excursion_mib[c]);
    else
      std::fprintf(out, "  %-22s steady %+.1f MiB\n", CounterName(k), leg.steady_mib[c]);
  }
  if (leg.ballasted) {
    std::fprintf(out, "  precondition, ballast committed: %s\n", leg.ballast_committed ? "yes" : "NO");
    std::fprintf(out,
                 "  precondition, each raised current value is at or above its peak before the ballast "
                 "(P:2733): %s\n",
                 leg.floor_ok ? "yes" : "NO (no verdict)");
    std::fprintf(out, "  raised peak - raised current: WS %llu B, private %llu B (reported; errs toward refusal)\n",
                 static_cast<unsigned long long>(leg.floor_gap_bytes[kWorkingSet]),
                 static_cast<unsigned long long>(leg.floor_gap_bytes[kPrivateBytes]));
    std::fprintf(out, "  precondition, every ballast page resident after the action: %s",
                 leg.resident_ok ? "yes\n" : "NO (no verdict): ");
    if (!leg.resident_ok)
      std::fprintf(out, "%llu page(s) not resident\n", static_cast<unsigned long long>(leg.nonresident_pages));
  }
  std::fflush(out);
}

}  // namespace semb_c62
