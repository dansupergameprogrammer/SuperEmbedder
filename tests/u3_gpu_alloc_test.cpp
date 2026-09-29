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
    if (c.index == call_count_at_fault + 1) return std::string("engine:") + c.verb;
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

// d1 / d2: one armed encode per site.
void SweepEncode(bool device) {
  Encoder e1, e2;
  std::vector<float> ref;
  if (!Setup(&e1, &e2, &ref)) return;
  for (uint64_t k = a.first; a.last == 0 || k <= a.last; ++k) {
    Line("BEGIN " + a.leg + " k=" + u3::S(k));
    const bool clean = e1.Encode(a.text) == SEMB_OK && RowIs(e1, ref);
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
      Line("END " + a.leg + " k=" + u3::S(k) + " (past K: the arm did not fire)");
      break;
    }
    const std::string where = WhereFired(cc, occ);
    const uint64_t c0 = semb_test_seam_gpu_call_count();
    const bool follow = e1.Encode(a.text) == SEMB_OK && RowIs(e1, ref);
    const bool moved = semb_test_seam_gpu_call_count() > c0;
    const bool second = e2.Encode(a.text) == SEMB_OK && RowIs(e2, ref);
    const bool ok = clean && s == SEMB_ALLOCATION_FAILED && follow && moved && second;
    Line("SITE " + a.leg + " k=" + u3::S(k) + " kind=" + kind + " where=" + where + " status=" + u3::Name(s) +
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
  for (uint64_t k = a.first; a.last == 0 || k <= a.last; ++k) {
    Line("BEGIN " + a.leg + " k=" + u3::S(k));
    semb_test_seam_gpu_call_log_reset();
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
      Line("END " + a.leg + " k=" + u3::S(k) + " (past K: the arm did not fire)");
      break;
    }
    const std::string where = WhereFired(cc, occ);
    if (s == SEMB_OK && e) semb_encoder_close(e);
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
    const bool ok = s == SEMB_ALLOCATION_FAILED && null_out && contexts == 0 && second;
    Line("SITE " + a.leg + " k=" + u3::S(k) + " kind=" + kind + " where=" + where + " status=" + u3::Name(s) +
         " want=SEMB_ALLOCATION_FAILED contexts=" + std::to_string(contexts) + " second=" + (second ? "1" : "0") +
         (in_map ? (ok ? " PASS" : " FAIL") : " OUTSIDE-MAP"));
    if (in_map) u3::Verdict(ok, a.leg + " k=" + u3::S(k), u3::Name(s));
  }
}

void LegCount() {
  Encoder e1;
  std::vector<float> ref;
  if (!Setup(&e1, nullptr, &ref)) return;
  u3hook::Count();
#if defined(_WIN32)
  u3hook::DeviceCount();
#endif
  e1.Encode(a.text);
  const uint64_t host = u3hook::Disarm();
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
  u3hook::Count();
#if defined(_WIN32)
  u3hook::DeviceCount();
#endif
  const semb_status s = OpenGpu(&e);
  const uint64_t ohost = u3hook::Disarm();
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
