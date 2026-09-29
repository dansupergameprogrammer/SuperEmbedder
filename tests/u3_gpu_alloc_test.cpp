// tests/u3_gpu_alloc_test.cpp -- U3 red suite: sec 4.6 row 5(d), the
// real-allocation legs (te266 P:4215, "(d) Allocation: real-allocation legs").
// The test author's, in U3's GPU test binary, which links the engine
// statically (the allocation hooks reach inside it). The fault is a real
// allocation failing, never a status injected at U3's seam: the expected
// outcome shares no parameter with the engine it grades. The seam is read only
// for the call count ("the next encode calls the engine") and for where a
// fault fell (tests/support/u3_alloc_hook.h).
//
// Built only with SEMB_BUILD_GPU=ON on Windows (links superembedder_testseam
// and d3d12). Off Windows or with the option OFF the driver reports MISSING
// PREREQUISITE (exit 77). Each invocation runs one leg over one site range,
// writing BEGIN before each armed site and SITE after it, flushed per line, so
// a crash or a lost box loses one site: tests/u3_gpu_alloc_check.py resumes
// from the log (a BEGIN with no SITE is reported CRASHED and the sweep
// continues at the next site).
//
// Legs (--leg):
//   count       unarmed: prints the host-allocation count K_host and the
//               D3D12 creation count K_dev of one encode of --text on a warm
//               GPU handle, and of one GPU open (with each open fault's
//               engine verb, from the call log), with each creation's heap type.
//   d1          (P:4215 d1) host memory: for each k in [--first, --last], a
//               clean encode, then the encode with the k-th allocation failed
//               (std::bad_alloc) -> SEMB_ALLOCATION_FAILED; the next encode on
//               the same handle calls the engine (call count moves) and
//               returns the reference row; a second GPU handle's next encode
//               returns its reference row.
//   d2          (P:4215 d2) device memory: the same, with the k-th
//               CreateCommittedResource returning E_OUTOFMEMORY, each site
//               labelled with its heap type. Oracle: d1's.
//   d3h / d3d   (P:4215 d3) the open: k-th host allocation / creation of a GPU
//               open failed. Graded where the call log places the fault inside
//               sslm_gpu_model_map: the open returns SEMB_ALLOCATION_FAILED,
//               *out NULL, the context count reads 0, and a second open in the
//               process succeeds and encodes the reference row. A fault
//               elsewhere in the open is reported OUTSIDE-MAP and not graded
//               (the plan's (d3) is the model map).
//   d4          (P:4215 d4) first use, in a FRESH PROCESS (one invocation per
//               site): the --site-th creation of the handle's first encode
//               fails -> SEMB_ALLOCATION_FAILED; the next encode on the same
//               handle returns the reference row (the engine plan's E-7); a
//               reopened handle does too. At v1.7.1 every later encode reads
//               SEMB_DEVICE_UNAVAILABLE (the commissioning reading).
//   mr_removed  must-reject (P:4215): the first creation of an encode returns
//               DXGI_ERROR_DEVICE_REMOVED -> SEMB_DEVICE_UNAVAILABLE, and the
//               handle is poisoned: the next encode returns
//               SEMB_DEVICE_UNAVAILABLE with the call count unchanged.
//   (row 5(d)'s other must-reject, "one .cso removed gives
//   SEMB_DEVICE_UNAVAILABLE", is u3_gpu_cells_test --cell
//   c10d_refused_after_creation, which constructs exactly that.)
//
// POPULATION (planned; the dev box's reading at v1.8.0 on the real model).
// One armed call counts every replaced operator new in the process: for one
// encode of --text that was host=164,574 (dev=24), and for one GPU open
// host=13,893,260 (dev=1,931), against the plan's 674 host and 120 D3D12 sites
// (te266 P:4215's cost line, from the engine plan te421 sec 4.3 and its sec 2.2
// probe). The plan's figures are ENGINE sites: sec 2.2's probe armed the
// engine's own per-document loop (reset, prompt prefill, read) for a 40-id
// document, with no SuperEmbedder frame in the window, and row 5(d) says so:
// "the fault is a real allocation failing inside the engine". The product's
// encode adds its own frames around those calls (tokenization, U3 staging, and
// the CPU work on the read triple), and the open adds U2's whole CPU open and
// witness forward; those frames are C64's population (J12, and U2-10's CPU
// rows), not row 5(d)'s. So each leg now sweeps a planned site set, derived
// from a counting run in the sweep's own frame (the call log emptied first, so
// its reservation cannot shift k), and every armed site checks that k fell
// where the plan put it (same in-call state, same call offset; DRIFTED = FAIL):
//   d1   every host allocation made INSIDE an engine call of the encode (the
//        plan's population, exhaustively), plus the first and last allocation
//        of the first run of each U3-frame class (U3's frames between two
//        engine calls), graded by the same oracle;
//   d3h  every host allocation made inside sslm_gpu_model_map during the open
//        ("(d1) and (d2) at the model map");
//   d3d  every D3D12 creation made inside sslm_gpu_model_map during the open;
//   d2   every D3D12 creation of the encode (24 at v1.8.0), unchanged.
// The count leg prints the breakdown (CLASS lines) that shows where K goes.
//
// COMMISSIONED before its first decision-bearing run (P:4215): against the
// engine at v1.7.1 the same legs read 530 non-conforming d1 sites (50 + 480),
// 120 d2 sites and a permanent loss at d4 [M, the plan]. A (d) that passes at
// v1.7.1 is dead. tests/u3_gpu_alloc_check.py --commission grades that.
//
// RED TODAY: link-red (the seam symbols, SEMB_BUILD_GPU and the device member
// are builder items, P:4263-4275).
//
// Output lines:
//   K <leg> host=<n> dev=<n>
//   DEVSITE <i> heap=<type>
//   BEGIN <leg> k=<k>
//   SITE <leg> k=<k> kind=<host|dev:HEAP> where=<engine:<verb>|u3> status=<s> want=<w> follow=<0|1>
//        moved=<0|1> second=<0|1> PASS|FAIL|OUTSIDE-MAP
//   END <leg> k=<k> (past K: the arm did not fire)
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "support/u3_alloc_hook.h"
#include "support/semb_u3_gpu_seam.h"
#include "support/u3_common.h"

namespace {

struct Args {
  std::string leg, model, tokenizer, log, text = "an ordinary document for the allocation sweep";
  uint64_t first = 1, last = 0, site = 1;
} a;

int32_t kUnavailable = -1;

// Encodes into preallocated storage, so the armed window holds only product
// allocations.
struct Encoder {
  std::vector<float> row;
  semb_encoder enc = nullptr;
  semb_status Encode(const std::string& text) {
    size_t req = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    std::fill(row.begin(), row.end(), 0.0f);
    return semb_encode(enc, text.data(), text.size(), row.data(), row.size() * sizeof(float), &req, &fp);
  }
};

semb_status OpenGpu(semb_encoder* out) {
  return u3::Open(u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceGpu), out);
}

std::vector<float> CpuReference(const std::string& text) {
  semb_encoder e = nullptr;
  std::vector<float> row;
  if (u3::Open(u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceCpu), &e) == SEMB_OK) {
    u3::EncodeRow(e, text, &row);
    semb_encoder_close(e);
  }
  return row;
}

// The verb of the engine call in flight when the fault fired: the log record
// whose index is the call count read at the fault, plus one.
std::string WhereFired(uint64_t call_count_at_fault, uint32_t occupancy_at_fault) {
  if (occupancy_at_fault == 0) return "u3";
  const uint64_t total = semb_test_seam_gpu_call_log(nullptr, 0, 0);
  std::vector<semb_test_seam_gpu_call> v(static_cast<size_t>(total));
  if (total) semb_test_seam_gpu_call_log(v.data(), 0, total);
  for (const auto& c : v) {
    if (c.index == call_count_at_fault) return std::string("engine:") + c.verb;
  }
  return "engine:?";
}

void Line(const std::string& s) {
  std::printf("%s\n", s.c_str());
  std::fflush(stdout);
  if (u3::LogFile()) {
    std::fprintf(u3::LogFile(), "%s\n", s.c_str());
    std::fflush(u3::LogFile());
  }
}

bool Setup(Encoder* e1, Encoder* e2, std::vector<float>* ref) {
  *ref = CpuReference(a.text);
  if (ref->empty()) {
    u3::Verdict(false, "5d setup: the CPU reference row", "the CPU open or encode failed");
    return false;
  }
  for (Encoder* e : {e1, e2}) {
    if (!e) continue;
    const semb_status s = OpenGpu(&e->enc);
    if (s != SEMB_OK) {
      u3::Red("5d setup: a GPU handle opens", std::string("open returned ") + u3::Name(s));
      return false;
    }
    e->row.assign(ref->size(), 0.0f);
    if (e->Encode(a.text) != SEMB_OK) {  // warm-up: first-use setup happens here, outside the sweep
      u3::Verdict(false, "5d setup: the warm-up encode", "not SEMB_OK");
      return false;
    }
  }
  return true;
}

bool RowIs(const Encoder& e, const std::vector<float>& ref) {
  return e.row.size() == ref.size() && std::memcmp(e.row.data(), ref.data(), ref.size() * sizeof(float)) == 0;
}

// ---- the planned site population ---------------------------------------------
struct Site {
  uint64_t k = 0;
  bool engine = false;
  uint64_t rel_call = 0;  // the running call count at k, minus the count before the armed call
  std::string cls;
};

std::string VerbOf(uint64_t index) {
  const uint64_t total = semb_test_seam_gpu_call_log(nullptr, 0, 0);
  std::vector<semb_test_seam_gpu_call> v(static_cast<size_t>(total));
  if (total) semb_test_seam_gpu_call_log(v.data(), 0, total);
  for (const auto& c : v) {
    if (c.index == index) return c.verb;
  }
  return "?";
}

void ResetCallLog() {
  if (semb_test_seam_gpu_call_log_reset() != 1) std::fprintf(stderr, "call log reset refused\n");
}

// From the host hook's segments of the counting run just made (call counts c0
// before it, c_end after it): the planned sites and a per-class breakdown.
// map_only: only allocations inside sslm_gpu_model_map, every one.
// Otherwise: every allocation inside any engine call, and the first and last
// allocation of the first run of each U3-frame class.
bool DeriveHostPlan(uint64_t c0, uint64_t c_end, bool map_only, std::vector<Site>* plan, std::string* why,
                    bool print_classes) {
  u3hook::HostState& h = u3hook::Host();
  if (h.seg_overflow) {
    *why = "more than " + u3::S(u3hook::HostState::kMaxSegments) + " allocation runs";
    return false;
  }
  struct Tally {
    std::string cls;
    uint64_t allocs = 0, runs = 0, swept = 0;
  };
  std::vector<Tally> tallies;
  auto tally = [&](const std::string& cls) -> Tally& {
    for (auto& t : tallies) {
      if (t.cls == cls) return t;
    }
    tallies.push_back(Tally{cls});
    return tallies.back();
  };
  std::vector<std::string> sampled;
  std::vector<std::string> verbs;  // verb per relative call index, read once
  for (uint64_t c = c0 + 1; c <= c_end; ++c) verbs.push_back(VerbOf(c));
  auto verb = [&](uint64_t c) { return c > c0 && c <= c_end ? verbs[c - c0 - 1] : std::string("?"); };
  for (int i = 0; i < h.nseg; ++i) {
    Site f;
    f.engine = h.seg_engine[i];
    f.rel_call = h.seg_call[i] - c0;
    if (f.engine) {
      f.cls = "engine:" + verb(h.seg_call[i]);
    } else {
      f.cls = "u3:" + (h.seg_call[i] == c0 ? std::string("start") : verb(h.seg_call[i])) + "->" +
              (h.seg_call[i] >= c_end ? std::string("end") : verb(h.seg_call[i] + 1));
    }
    Tally& t = tally(f.cls);
    t.allocs += h.seg_last[i] - h.seg_first[i] + 1;
    t.runs += 1;
    if (map_only) {
      if (f.cls != "engine:sslm_gpu_model_map") continue;
    } else if (!f.engine) {
      if (std::find(sampled.begin(), sampled.end(), f.cls) != sampled.end()) continue;
      sampled.push_back(f.cls);
      f.k = h.seg_first[i];
      plan->push_back(f);
      t.swept += 1;
      if (h.seg_last[i] != h.seg_first[i]) {
        f.k = h.seg_last[i];
        plan->push_back(f);
        t.swept += 1;
      }
      continue;
    }
    for (uint64_t k = h.seg_first[i]; k <= h.seg_last[i]; ++k) {
      f.k = k;
      plan->push_back(f);
    }
    t.swept += h.seg_last[i] - h.seg_first[i] + 1;
  }
  if (print_classes) {
    for (const auto& t : tallies) {
      Line("CLASS " + a.leg + " " + t.cls + " allocations=" + u3::S(t.allocs) + " runs=" + u3::S(t.runs) +
           " swept=" + u3::S(t.swept));
    }
  }
  std::sort(plan->begin(), plan->end(), [](const Site& x, const Site& y) { return x.k < y.k; });
  if (plan->empty()) {
    *why = map_only ? "no counted allocation inside sslm_gpu_model_map" : "no counted allocation";
    return false;
  }
  return true;
}

#if defined(_WIN32)
bool DeriveDevicePlan(uint64_t c0, uint64_t c_end, uint64_t n, std::vector<Site>* plan, std::string* why) {
  u3hook::DeviceState& d = u3hook::Dev();
  if (n > static_cast<uint64_t>(u3hook::kMaxLabels)) {
    *why = "more than " + u3::S(u3hook::kMaxLabels) + " creations";
    return false;
  }
  for (uint64_t i = 0; i < n; ++i) {
    if (!d.engine_at[i] || d.call_at[i] <= c0 || d.call_at[i] > c_end) continue;
    if (VerbOf(d.call_at[i]) != "sslm_gpu_model_map") continue;
    Site f;
    f.k = i + 1;
    f.engine = true;
    f.rel_call = d.call_at[i] - c0;
    f.cls = "engine:sslm_gpu_model_map";
    plan->push_back(f);
  }
  if (plan->empty()) {
    *why = "no D3D12 creation inside sslm_gpu_model_map";
    return false;
  }
  return true;
}
#endif

// Iterates a plan from --first (resume), writing END when it is exhausted.
const Site* NextSite(const std::vector<Site>& plan, size_t* pi, uint64_t K) {
  while (*pi < plan.size() && plan[*pi].k < a.first) ++*pi;
  if (*pi == plan.size() || (a.last != 0 && plan[*pi].k > a.last)) {
    Line("END " + a.leg + " k=" + u3::S(K + 1) + " (past the planned sites)");
    return nullptr;
  }
  return &plan[(*pi)++];
}

// d1 / d2: one armed encode per site.
void SweepEncode(bool device) {
  Encoder e1, e2;
  std::vector<float> ref;
  if (!Setup(&e1, &e2, &ref)) return;
  std::vector<Site> plan;
  uint64_t K = 0;
  if (!device) {  // d1: the counting run, in the sweep's frame (a clean encode, then the counted one)
    e1.Encode(a.text);
    ResetCallLog();
    const uint64_t c0 = semb_test_seam_gpu_call_count();
    u3hook::Count(true);
    e1.Encode(a.text);
    K = u3hook::Disarm();
    std::string why;
    if (!DeriveHostPlan(c0, semb_test_seam_gpu_call_count(), false, &plan, &why, true)) {
      u3::Verdict(false, "d1 site plan", why);
      return;
    }
    Line("PLAN d1 K=" + u3::S(K) + " sites=" + u3::S(plan.size()));
  }
  size_t pi = 0;
  for (uint64_t k = a.first; a.last == 0 || k <= a.last || !device; ++k) {
    const Site* site = nullptr;
    if (!device) {
      site = NextSite(plan, &pi, K);
      if (!site) break;
      k = site->k;
    }
    Line("BEGIN " + a.leg + " k=" + u3::S(k));
    const bool clean = e1.Encode(a.text) == SEMB_OK && RowIs(e1, ref);
    if (!device) ResetCallLog();
    const uint64_t c_before = semb_test_seam_gpu_call_count();
    semb_status s;
    int fired = 0;
    uint64_t cc = 0;
    uint32_t occ = 0;
    std::string kind = "host";
    if (!device) {
      u3hook::Arm(k, u3hook::kBadAlloc);
      s = e1.Encode(a.text);
      u3hook::Disarm();
      fired = u3hook::Host().fired;
      cc = u3hook::Host().fired_call_count;
      occ = u3hook::Host().fired_occupancy;
    } else {
#if defined(_WIN32)
      u3hook::DeviceArm(k, E_OUTOFMEMORY);
      s = e1.Encode(a.text);
      u3hook::DeviceDisarm();
      fired = u3hook::Dev().fired;
      cc = u3hook::Dev().fired_call_count;
      occ = u3hook::Dev().fired_occupancy;
      kind = std::string("dev:") + u3hook::HeapName(u3hook::Dev().heap_type[(k - 1) % u3hook::kMaxLabels]);
#else
      s = SEMB_OK;
#endif
    }
    if (!fired) {
      if (site) {
        Line("SITE " + a.leg + " k=" + u3::S(k) + " class=" + site->cls + " NOT-REACHED FAIL");
        u3::Verdict(false, a.leg + " k=" + u3::S(k), "planned site not reached");
        continue;
      }
      Line("END " + a.leg + " k=" + u3::S(k) + " (past K: the arm did not fire)");
      break;
    }
    const bool on_plan = !site || ((occ > 0) == site->engine && cc - c_before == site->rel_call);
    const std::string where = WhereFired(cc, occ);
    const uint64_t c0 = semb_test_seam_gpu_call_count();
    const bool follow = e1.Encode(a.text) == SEMB_OK && RowIs(e1, ref);
    const bool moved = semb_test_seam_gpu_call_count() > c0;
    const bool second = e2.Encode(a.text) == SEMB_OK && RowIs(e2, ref);
    const bool ok = clean && s == SEMB_ALLOCATION_FAILED && follow && moved && second && on_plan;
    Line("SITE " + a.leg + " k=" + u3::S(k) + " kind=" + kind + (site ? " class=" + site->cls : std::string()) +
         (on_plan ? "" : " DRIFTED") + " where=" + where + " status=" + u3::Name(s) +
         " want=SEMB_ALLOCATION_FAILED follow=" + (follow ? "1" : "0") + " moved=" + (moved ? "1" : "0") +
         " second=" + (second ? "1" : "0") + " clean_before=" + (clean ? "1" : "0") + (ok ? " PASS" : " FAIL"));
    u3::Verdict(ok, a.leg + " k=" + u3::S(k), u3::Name(s));
  }
  semb_encoder_close(e1.enc);
  semb_encoder_close(e2.enc);
}

// d3h / d3d: one armed open per site.
void SweepOpen(bool device) {
  const std::vector<float> ref = CpuReference(a.text);
  {  // warm: the process's first GPU open sets up what later opens reuse
    semb_encoder w = nullptr;
    if (OpenGpu(&w) == SEMB_OK) semb_encoder_close(w);
  }
  // The counting run, in the sweep's frame: the call log emptied, the config made, then the open.
  std::vector<Site> plan;
  uint64_t K = 0;
  {
    ResetCallLog();
    const uint64_t c0 = semb_test_seam_gpu_call_count();
    const u3::Config c = u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceGpu);
    semb_encoder e = nullptr;
    std::string why;
    bool ok = false;
    if (!device) {
      u3hook::Count(true);
      const semb_status s = u3::Open(c, &e);
      K = u3hook::Disarm();
      ok = s == SEMB_OK && DeriveHostPlan(c0, semb_test_seam_gpu_call_count(), true, &plan, &why, true);
      if (s != SEMB_OK) why = std::string("the counting open returned ") + u3::Name(s);
    } else {
#if defined(_WIN32)
      u3hook::DeviceCount();
      const semb_status s = u3::Open(c, &e);
      K = u3hook::DeviceDisarm();
      ok = s == SEMB_OK && DeriveDevicePlan(c0, semb_test_seam_gpu_call_count(), K, &plan, &why);
      if (s != SEMB_OK) why = std::string("the counting open returned ") + u3::Name(s);
#else
      why = "Windows/D3D12 only";
#endif
    }
    if (e) semb_encoder_close(e);
    if (!ok) {
      u3::Verdict(false, a.leg + " site plan", why);
      return;
    }
    Line("PLAN " + a.leg + " K=" + u3::S(K) + " sites=" + u3::S(plan.size()) + " (inside sslm_gpu_model_map)");
  }
  size_t pi = 0;
  for (;;) {
    const Site* site = NextSite(plan, &pi, K);
    if (!site) break;
    const uint64_t k = site->k;
    Line("BEGIN " + a.leg + " k=" + u3::S(k));
    ResetCallLog();
    const uint64_t c_before = semb_test_seam_gpu_call_count();
    semb_encoder e = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(1));
    semb_status s;
    int fired = 0;
    uint64_t cc = 0;
    uint32_t occ = 0;
    std::string kind = "host";
    const u3::Config c = u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceGpu);
    if (!device) {
      u3hook::Arm(k, u3hook::kBadAlloc);
      s = u3::Open(c, &e);
      u3hook::Disarm();
      fired = u3hook::Host().fired;
      cc = u3hook::Host().fired_call_count;
      occ = u3hook::Host().fired_occupancy;
    } else {
#if defined(_WIN32)
      u3hook::DeviceArm(k, E_OUTOFMEMORY);
      s = u3::Open(c, &e);
      u3hook::DeviceDisarm();
      fired = u3hook::Dev().fired;
      cc = u3hook::Dev().fired_call_count;
      occ = u3hook::Dev().fired_occupancy;
      kind = std::string("dev:") + u3hook::HeapName(u3hook::Dev().heap_type[(k - 1) % u3hook::kMaxLabels]);
#else
      s = SEMB_OK;
#endif
    }
    if (!fired) {
      if (s == SEMB_OK && e) semb_encoder_close(e);
      Line("SITE " + a.leg + " k=" + u3::S(k) + " kind=" + kind + " NOT-REACHED FAIL");
      u3::Verdict(false, a.leg + " k=" + u3::S(k), "planned site not reached");
      continue;
    }
    const std::string where = WhereFired(cc, occ);
    if (s == SEMB_OK && e) semb_encoder_close(e);
    const bool on_plan = occ > 0 && cc - c_before == site->rel_call;
    const bool in_map = where == "engine:sslm_gpu_model_map";
    const bool null_out = s != SEMB_OK && e == nullptr;
    const int64_t contexts = semb_test_seam_gpu_context_count();
    Encoder again;
    const semb_status s2 = OpenGpu(&again.enc);
    bool second = false;
    if (s2 == SEMB_OK) {
      again.row.assign(ref.size(), 0.0f);
      second = again.Encode(a.text) == SEMB_OK && RowIs(again, ref);
      semb_encoder_close(again.enc);
    }
    const bool ok = s == SEMB_ALLOCATION_FAILED && null_out && contexts == 0 && second && on_plan && in_map;
    Line("SITE " + a.leg + " k=" + u3::S(k) + " kind=" + kind + (on_plan && in_map ? "" : " DRIFTED") +
         " where=" + where + " status=" + u3::Name(s) + " want=SEMB_ALLOCATION_FAILED contexts=" +
         std::to_string(contexts) + " second=" + (second ? "1" : "0") + (ok ? " PASS" : " FAIL"));
    u3::Verdict(ok, a.leg + " k=" + u3::S(k), u3::Name(s));
  }
}

void LegCount() {
  Encoder e1;
  std::vector<float> ref;
  if (!Setup(&e1, nullptr, &ref)) return;
  e1.Encode(a.text);  // the sweep's frame: a clean encode, then the counted one
  ResetCallLog();
  const uint64_t ec0 = semb_test_seam_gpu_call_count();
  u3hook::Count(true);
#if defined(_WIN32)
  u3hook::DeviceCount();
#endif
  e1.Encode(a.text);
  const uint64_t host = u3hook::Disarm();
  {
    std::vector<Site> plan;
    std::string why;
    a.leg = "count-encode";
    DeriveHostPlan(ec0, semb_test_seam_gpu_call_count(), false, &plan, &why, true);
    Line("PLAN d1 sites=" + u3::S(plan.size()));
    a.leg = "count";
  }
  uint64_t dev = 0;
#if defined(_WIN32)
  dev = u3hook::DeviceDisarm();
  for (uint64_t i = 0; i < dev && i < static_cast<uint64_t>(u3hook::kMaxLabels); ++i) {
    Line("DEVSITE " + u3::S(i + 1) + " heap=" + u3hook::HeapName(u3hook::Dev().heap_type[i]));
  }
#endif
  Line("K encode host=" + u3::S(host) + " dev=" + u3::S(dev));
  semb_encoder_close(e1.enc);
  semb_encoder e = nullptr;
  ResetCallLog();
  const uint64_t oc0 = semb_test_seam_gpu_call_count();
  u3hook::Count(true);
#if defined(_WIN32)
  u3hook::DeviceCount();
#endif
  const semb_status s = OpenGpu(&e);
  const uint64_t ohost = u3hook::Disarm();
  {
    std::vector<Site> plan;
    std::string why;
    a.leg = "count-open";
    DeriveHostPlan(oc0, semb_test_seam_gpu_call_count(), true, &plan, &why, true);
    Line("PLAN d3h sites=" + u3::S(plan.size()));
    a.leg = "count";
  }
  uint64_t odev = 0;
#if defined(_WIN32)
  odev = u3hook::DeviceDisarm();
#endif
  if (s == SEMB_OK) semb_encoder_close(e);
  Line("K open host=" + u3::S(ohost) + " dev=" + u3::S(odev));
  u3::Note("count", "unarmed counts printed; the driver chunks d1/d2/d3 by them");
}

void LegD4() {
#if defined(_WIN32)
  const std::vector<float> ref = CpuReference(a.text);
  Encoder e;
  const semb_status so = OpenGpu(&e.enc);
  if (so != SEMB_OK) {
    u3::Red("d4 setup: a GPU handle opens", u3::Name(so));
    return;
  }
  e.row.assign(ref.size(), 0.0f);
  Line("BEGIN d4 k=" + u3::S(a.site));
  u3hook::DeviceArm(a.site, E_OUTOFMEMORY);
  const semb_status s = e.Encode(a.text);
  u3hook::DeviceDisarm();
  const bool fired = u3hook::Dev().fired;
  const std::string heap = u3hook::HeapName(u3hook::Dev().heap_type[(a.site - 1) % u3hook::kMaxLabels]);
  const bool follow = e.Encode(a.text) == SEMB_OK && RowIs(e, ref);
  semb_encoder_close(e.enc);
  Encoder r;
  bool reopened = false;
  if (OpenGpu(&r.enc) == SEMB_OK) {
    r.row.assign(ref.size(), 0.0f);
    reopened = r.Encode(a.text) == SEMB_OK && RowIs(r, ref);
    semb_encoder_close(r.enc);
  }
  if (!fired) {
    Line("END d4 k=" + u3::S(a.site) + " (past K: the arm did not fire)");
    return;
  }
  const bool ok = s == SEMB_ALLOCATION_FAILED && follow && reopened;
  Line("SITE d4 k=" + u3::S(a.site) + " kind=dev:" + heap + " status=" + u3::Name(s) +
       " want=SEMB_ALLOCATION_FAILED follow=" + (follow ? "1" : "0") + " reopened=" + (reopened ? "1" : "0") +
       (ok ? " PASS" : " FAIL"));
  u3::Verdict(ok, "d4 site " + u3::S(a.site), u3::Name(s));
#else
  u3::Missing("d4", "Windows/D3D12 only");
#endif
}

void LegRemoved() {
#if defined(_WIN32)
  const std::vector<float> ref = CpuReference(a.text);
  Encoder e;
  if (OpenGpu(&e.enc) != SEMB_OK) {
    u3::Red("mr_removed setup: a GPU handle opens", "open refused");
    return;
  }
  e.row.assign(ref.size(), 0.0f);
  u3hook::DeviceArm(1, DXGI_ERROR_DEVICE_REMOVED);
  const semb_status s = e.Encode(std::string(200, 'r'));  // a longer document: a fresh sequence, so a creation
  u3hook::DeviceDisarm();
  const bool fired = u3hook::Dev().fired;
  const uint64_t c0 = semb_test_seam_gpu_call_count();
  const semb_status s2 = e.Encode(a.text);
  const bool unchanged = semb_test_seam_gpu_call_count() == c0;
  const semb_status sc = semb_encoder_close(e.enc);
  u3::Verdict(fired && s == kUnavailable && s2 == kUnavailable && unchanged && sc == SEMB_OK,
              "mr_removed a DXGI_ERROR_DEVICE_REMOVED creation gives SEMB_DEVICE_UNAVAILABLE and poisons the handle",
              std::string("fired=") + (fired ? "1" : "0") + " status " + u3::Name(s) + ", next " + u3::Name(s2) +
                  (unchanged ? " (no engine call)" : " (CALLED the engine)") + ", close " + u3::Name(sc));
#else
  u3::Missing("mr_removed", "Windows/D3D12 only");
#endif
}

}  // namespace

int main(int argc, char** argv) {
  for (int i = 1; i + 1 < argc; i += 2) {
    const std::string k = argv[i], v = argv[i + 1];
    if (k == "--leg") a.leg = v;
    else if (k == "--model") a.model = v;
    else if (k == "--tokenizer") a.tokenizer = v;
    else if (k == "--log") a.log = v;
    else if (k == "--text") a.text = v;
    else if (k == "--first") a.first = std::strtoull(v.c_str(), nullptr, 10);
    else if (k == "--last") a.last = std::strtoull(v.c_str(), nullptr, 10);
    else if (k == "--site") a.site = std::strtoull(v.c_str(), nullptr, 10);
  }
  if (!a.log.empty()) u3::LogFile() = std::fopen(a.log.c_str(), "ab");
  if (!u3::FileExists(a.model) || !u3::FileExists(a.tokenizer)) {
    u3::Missing("u3_gpu_alloc", "the artifacts (--model, --tokenizer) are absent");
    return u3::ExitCode();
  }
  kUnavailable = u3::StatusByName("SEMB_DEVICE_UNAVAILABLE");
#if defined(_WIN32)
  if (a.leg != "d1" && a.leg != "d3h" && !u3hook::InstallDeviceHook()) {
    u3::Missing("u3_gpu_alloc", "no D3D12 device could be created to install the CreateCommittedResource hook");
    return u3::ExitCode();
  }
#endif
  if (a.leg == "count") LegCount();
  else if (a.leg == "d1") SweepEncode(false);
  else if (a.leg == "d2") SweepEncode(true);
  else if (a.leg == "d3h") SweepOpen(false);
  else if (a.leg == "d3d") SweepOpen(true);
  else if (a.leg == "d4") LegD4();
  else if (a.leg == "mr_removed") LegRemoved();
  else u3::Verdict(false, "u3_gpu_alloc", "unknown --leg " + a.leg);
  std::printf("SUMMARY u3_gpu_alloc %s pass=%d fail=%d red=%d missing=%d\n", a.leg.c_str(), u3::T().pass,
              u3::T().fail, u3::T().red, u3::T().missing);
  return u3::ExitCode();
}
