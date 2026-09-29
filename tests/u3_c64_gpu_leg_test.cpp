// tests/u3_c64_gpu_leg_test.cpp -- U3 red suite: C64's GPU leg (the U2 plan's
// sec 6.2 J12, te267 P:3757; U2-10's C64). The test author's, independently of
// the builder.
//
// On the dev box's GPU binary, U3's rows run C64 (a) std::bad_alloc,
// (a') std::length_error, (b) a foreign exception and (c) the live count, with
// J12's two additions read through te266 sec 4.2's seam: after every failed
// call a try-lock of the submission lock from the test thread succeeds
// (capability 7), and after close the context count is 0 (capability 5). The
// hook (tests/support/u3_alloc_hook.h) also fails allocations inside the
// statically linked engine.
//
// ROWS. U3's C-linkage verbs are the builder's, in engine_adapter_gpu.cpp and
// engine_adapter_gpu_off.cpp (J12: each joins tools/c_boundary_table.json);
// they are reached through the public verbs on a GPU handle, so this leg's
// drivers are those verbs: --row semb_encoder_open | semb_encode |
// semb_encode_query | semb_encode_batch. The C65 census (U2-10) is what refuses
// an unlisted U3 verb; this leg grades the rows' behaviour.
//
// EXPECTED OUTCOMES NEVER COME FROM THE ENGINE'S STATUS (J12): the call log
// only locates k.
//   k inside an engine call (the hook read a nonzero in-call count):
//     (a), (a')  SEMB_ALLOCATION_FAILED;
//     (b)        SEMB_DEVICE_UNAVAILABLE on that handle (te266 sec 4.1's
//                non-allocation row), and a second GPU handle's next encode
//                returns its reference row (TE-422 S-4; at v1.7.1 it reads
//                SEMB_DEVICE_UNAVAILABLE -- the carry-over defect);
//     (c)        after SEMB_ALLOCATION_FAILED: the next encode on the same
//                handle calls the engine (call count moves) and returns the
//                reference row, and a second handle's next encode returns its
//                reference row; after SEMB_DEVICE_UNAVAILABLE: the next encode
//                on that handle returns SEMB_DEVICE_UNAVAILABLE with the call
//                count unchanged.
//   k in U3's own frames (in-call count 0):
//     (a), (a')  SEMB_ALLOCATION_FAILED;  (b) the row's catch-all,
//                SEMB_ENGINE_REFUSED (C64's family table, u2_10's ExpectedFor);
//     (c)        the reference row on the same handle.
//   (c)'s live count: equal before and after the failed call, except where the
//   log records a sequence release during it or the call poisoned the handle;
//   there the close-all check replaces it: every handle closes SEMB_OK, the
//   context count reads 0, and the live count returns to its value before the
//   handles opened.
//   Every failed call: the try-lock from the test thread succeeds. The mutant
//   the leg exists to kill -- a boundary holding the lock in its C-linkage
//   frame -- fails it whatever the status.
//
// POPULATION (the U3 code review's C2). semb_encode, semb_encode_query and
// semb_encode_batch: every k in 1..K of one call (J12). semb_encoder_open: the
// finite site plan described at PlanOpenSites -- the first and last allocation
// of the first run of each location class -- with the adapter-label stage
// graded under PD-1 (the open never refuses on a label read, te266 P:4212).
// The close-all base is taken after one GPU open-and-close cycle (te267 C64
// (c), P:3265-3266), and the counting run arms nothing but uses the sweep's
// own frame and state.
//
// RESUMABLE: one invocation grades --arm over k in [--first, --last], BEGIN
// before each arm and ARM after, flushed per line; a BEGIN with no ARM is a
// termination at that k (tests/u3_gpu_sweep_check.py reports it and resumes at
// k + 1). --count-only prints K for the row.
//
// Built only with SEMB_BUILD_GPU=ON on Windows (links superembedder_testseam).
// RED TODAY: link-red (every seam symbol and the device member are builder
// items). Off Windows the driver reports MISSING PREREQUISITE (exit 77).
//
// Output lines:
//   K <row> <K>
//   BEGIN <row> <arm> k=<k>
//   ARM <row> <arm> k=<k> where=<engine:<verb>|u3> status=<s> want=<w> trylock=<0|1> follow=<0|1>
//       moved=<0|1|-> second=<0|1|-> live=<equal|close-all|MOVED> PASS|FAIL
//   END <row> <arm> k=<k> (past K)
#include <algorithm>
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
  std::string row = "semb_encode", arm = "a", model, tokenizer, log;
  std::string text = "a document for the class sweep's GPU leg";
  uint64_t first = 1, last = 0;
  bool count_only = false;
} a;

int32_t kUnavailable = -1;

struct Handle {
  semb_encoder enc = nullptr;
  std::vector<float> row;
  semb_status Encode(const std::string& text) {
    size_t req = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    std::fill(row.begin(), row.end(), 0.0f);
    return semb_encode(enc, text.data(), text.size(), row.data(), row.size() * sizeof(float), &req, &fp);
  }
  bool Is(const std::vector<float>& ref) const {
    return row.size() == ref.size() && std::memcmp(row.data(), ref.data(), ref.size() * sizeof(float)) == 0;
  }
};

semb_status OpenGpu(Handle* h, size_t dims) {
  h->row.assign(dims, 0.0f);
  return u3::Open(u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceGpu), &h->enc);
}

void Line(const std::string& s) {
  std::printf("%s\n", s.c_str());
  std::fflush(stdout);
  if (u3::LogFile()) {
    std::fprintf(u3::LogFile(), "%s\n", s.c_str());
    std::fflush(u3::LogFile());
  }
}

// Preallocated inputs and outputs for every driver, so the armed window holds
// only product allocations.
struct Driver {
  std::vector<float> out;
  std::vector<semb_document> docs;
  std::vector<std::string> ids, texts;
  semb_encoder opened = nullptr;
  void Prepare(size_t dims) {
    out.assign(dims * 4, 0.0f);
    ids = {"d0", "d1", "d2", "d3"};
    texts = {a.text, "second document", "third", "a fourth and final document"};
    docs.resize(4);
    for (size_t i = 0; i < 4; ++i) {
      docs[i].struct_size = sizeof(semb_document);
      docs[i].id = ids[i].data();
      docs[i].id_len = ids[i].size();
      docs[i].utf8 = texts[i].data();
      docs[i].utf8_len = texts[i].size();
    }
  }
  semb_status Run(semb_encoder enc) {
    size_t req = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    if (a.row == "semb_encode") {
      return semb_encode(enc, a.text.data(), a.text.size(), out.data(), out.size() * sizeof(float), &req, &fp);
    }
    if (a.row == "semb_encode_query") {
      return semb_encode_query(enc, a.text.data(), a.text.size(), out.data(), out.size() * sizeof(float), &req, &fp);
    }
    if (a.row == "semb_encode_batch") {
      return semb_encode_batch(enc, docs.data(), docs.size(), out.data(), out.size() * sizeof(float), &req);
    }
    return SEMB_NULL_ARGUMENT;  // semb_encoder_open is driven by RunOpen
  }
};

bool SeqReleaseLogged(uint64_t from_count) {
  const uint64_t total = semb_test_seam_gpu_call_log(nullptr, 0, 0);
  std::vector<semb_test_seam_gpu_call> v(static_cast<size_t>(total));
  if (total) semb_test_seam_gpu_call_log(v.data(), 0, total);
  for (const auto& c : v) {
    if (c.index > from_count && std::strcmp(c.verb, "sslm_gpu_seq_release") == 0) return true;
  }
  return false;
}

std::string VerbAt(uint64_t index) {
  const uint64_t total = semb_test_seam_gpu_call_log(nullptr, 0, 0);
  std::vector<semb_test_seam_gpu_call> v(static_cast<size_t>(total));
  if (total) semb_test_seam_gpu_call_log(v.data(), 0, total);
  for (const auto& c : v) {
    if (c.index == index) return c.verb;
  }
  return "?";
}

// ---- semb_encoder_open's site plan (the review's C2; te267 P:3757, P:3219-3310) --
// An exhaustive k in 1..K is not a runnable population for the open: on the
// U1 pair one GPU open makes ~11.6 million counted allocations (the agreement
// check re-runs the same stages for 22 witness sequences, and the CPU witness
// forward is U2's, swept by C64's CPU rows), at ~30 s a site. J12 grades k by
// WHERE it falls -- inside an engine call (by the verb the log names) or in
// U3's own frames -- so the population is one site set per location class:
//   * the counting run (the sweep's own frame, below) records maximal runs of
//     allocations with one key: an engine call, or U3's frames between two
//     engine calls;
//   * each run is classed: "engine:<verb>", or "u3:<verb before>-><verb after>"
//     ("start" before the open's first engine call);
//   * the first run of each class contributes its first and its last
//     allocation. Later runs of a class repeat the same code for another
//     witness sequence.
// The U3 frames after the open's last engine call are the adapter-label read
// (encoder.cpp publishes the handle after semb::gpu::Open without allocating;
// engine_adapter_gpu.cpp reads the labels after the agreement check). PD-1
// (conductor's ruling, te266 P:4212): label discovery is OUTSIDE C64's
// allocation-status population -- the open never refuses on a label read. Those
// sites are graded "label": every arm must return SEMB_OK, and the handle must
// then encode its reference row. Every armed site also checks that k fell where
// the plan put it (same in-call state, same call offset); a drifted site FAILs.
struct Site {
  uint64_t k = 0;
  bool engine = false;
  uint64_t rel_call = 0;  // the running call count at k, minus the count before the open
  bool label = false;
  std::string cls;
};

// The seam's call log grows by reservation when it fills, and that growth is a
// counted U3-frame allocation whose position depends on how many records came
// before: it would shift k between the counting run and an armed run. Each
// counted or armed open therefore starts from an empty log (capacity kept).
void ResetCallLog() {
  if (semb_test_seam_gpu_call_log_reset() != 1) std::fprintf(stderr, "call log reset refused\n");
}

// The sweep's frame, shared by the counting run and every armed run: the row
// buffer and the config exist before counting or arming starts.
semb_status OpenFrame(Handle* h3, size_t dims, bool count, uint64_t k, int fault) {
  h3->row.assign(dims, 0.0f);
  const u3::Config cfg = u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceGpu);
  if (count) u3hook::Count(true);
  else u3hook::Arm(k, fault);
  semb_status s;
  try {
    s = u3::Open(cfg, &h3->enc);
  } catch (...) {
    s = static_cast<semb_status>(-1000);  // escaped: the harness's own catch is red
  }
  u3hook::Disarm();
  return s;
}

// Counts one open in the sweep's frame and derives the site plan. Returns
// false (with *why) when the counting run cannot supply one.
bool PlanOpenSites(size_t dims, uint64_t* K, std::vector<Site>* plan, std::string* why) {
  Handle h3;
  ResetCallLog();
  const uint64_t c0 = semb_test_seam_gpu_call_count();
  const semb_status s = OpenFrame(&h3, dims, true, 0, 0);
  *K = u3hook::Host().seen.load();
  const uint64_t c_end = semb_test_seam_gpu_call_count();
  if (h3.enc) semb_encoder_close(h3.enc);
  u3hook::HostState& h = u3hook::Host();
  if (s != SEMB_OK) {
    *why = std::string("the unarmed counting open returned ") + u3::Name(s);
    return false;
  }
  if (h.seg_overflow) {
    *why = "more than " + u3::S(u3hook::HostState::kMaxSegments) + " allocation runs";
    return false;
  }
  std::vector<std::string> seen;
  for (int i = 0; i < h.nseg; ++i) {
    Site f;
    f.engine = h.seg_engine[i];
    f.rel_call = h.seg_call[i] - c0;
    if (f.engine) {
      f.cls = "engine:" + VerbAt(h.seg_call[i]);
    } else if (h.seg_call[i] >= c_end) {
      f.cls = "label";
      f.label = true;
    } else {
      f.cls = "u3:" + (h.seg_call[i] == c0 ? std::string("start") : VerbAt(h.seg_call[i])) + "->" +
              VerbAt(h.seg_call[i] + 1);
    }
    if (std::find(seen.begin(), seen.end(), f.cls) != seen.end()) continue;
    seen.push_back(f.cls);
    f.k = h.seg_first[i];
    plan->push_back(f);
    if (h.seg_last[i] != h.seg_first[i]) {
      f.k = h.seg_last[i];
      plan->push_back(f);
    }
  }
  std::sort(plan->begin(), plan->end(), [](const Site& x, const Site& y) { return x.k < y.k; });
  if (plan->empty()) {
    *why = "the counting open made no counted allocation";
    return false;
  }
  return true;
}

int FaultOf(const std::string& arm) {
  if (arm == "a2") return u3hook::kLengthError;
  if (arm == "b") return u3hook::kForeign;
  return u3hook::kBadAlloc;
}

}  // namespace

int main(int argc, char** argv) {
  for (int i = 1; i < argc; ++i) {
    const std::string k = argv[i];
    if (k == "--count-only") {
      a.count_only = true;
      continue;
    }
    if (i + 1 >= argc) break;
    const std::string v = argv[++i];
    if (k == "--row") a.row = v;
    else if (k == "--arm") a.arm = v;
    else if (k == "--model") a.model = v;
    else if (k == "--tokenizer") a.tokenizer = v;
    else if (k == "--log") a.log = v;
    else if (k == "--text") a.text = v;
    else if (k == "--first") a.first = std::strtoull(v.c_str(), nullptr, 10);
    else if (k == "--last") a.last = std::strtoull(v.c_str(), nullptr, 10);
  }
  if (!a.log.empty()) u3::LogFile() = std::fopen(a.log.c_str(), "ab");
  if (!u3::FileExists(a.model) || !u3::FileExists(a.tokenizer)) {
    u3::Missing("u3_c64_gpu_leg", "the artifacts (--model, --tokenizer) are absent");
    return u3::ExitCode();
  }
  kUnavailable = u3::StatusByName("SEMB_DEVICE_UNAVAILABLE");
  const bool is_open = a.row == "semb_encoder_open";

  // Reference rows: a CPU handle over the same artifacts, before any GPU work.
  std::vector<float> ref;
  {
    semb_encoder c = nullptr;
    if (u3::Open(u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceCpu), &c) != SEMB_OK) {
      u3::Red("C64-GPU setup: the CPU reference handle opens", "open refused");
      return u3::ExitCode();
    }
    u3::EncodeRow(c, a.text, &ref);
    semb_encoder_close(c);
  }
  const size_t dims = ref.size();
  Driver drv;
  drv.Prepare(dims);
  // te267 C64 (c) (P:3265-3266): the close-all base is taken after one
  // open-and-close cycle in the same process, so the process's lasting statics
  // (the engine's device, its pipeline caches) are already in it.
  {
    Handle w;
    const bool warm = OpenGpu(&w, dims) == SEMB_OK && w.Encode(a.text) == SEMB_OK && w.Is(ref);
    if (w.enc) semb_encoder_close(w.enc);
    if (!warm) {
      u3::Red("C64-GPU setup: a warm-up GPU handle opens, encodes its reference row and closes", "refused");
      return u3::ExitCode();
    }
  }
  Handle h1, h2;
  auto open_both = [&]() -> bool {
    return OpenGpu(&h1, dims) == SEMB_OK && OpenGpu(&h2, dims) == SEMB_OK && h1.Encode(a.text) == SEMB_OK &&
           h2.Encode(a.text) == SEMB_OK;
  };
  if (!open_both()) {
    u3::Red("C64-GPU setup: two GPU handles open and encode", "a GPU open or warm-up encode was refused");
    return u3::ExitCode();
  }
  // semb_encoder_open: the finite site plan, from a counting run in the sweep's
  // own frame and state (both handles open, as in every armed run). The other
  // rows keep every k in 1..K (J12; their K is one encode). The two handles are
  // then closed and reopened around the close-all base, so the plan's own
  // storage is inside the base and the handles are not.
  std::vector<Site> plan;
  uint64_t K = 0;
  if (is_open) {
    std::string why;
    if (!PlanOpenSites(dims, &K, &plan, &why)) {
      u3::Verdict(false, "C64-GPU semb_encoder_open site plan", why);
      return u3::ExitCode();
    }
    Line("PLAN " + a.row + " K=" + u3::S(K) + " sites=" + u3::S(plan.size()));
    for (const auto& st : plan) Line("PLANSITE " + a.row + " k=" + u3::S(st.k) + " class=" + st.cls);
  }
  semb_encoder_close(h1.enc);
  semb_encoder_close(h2.enc);
  h1 = Handle{};
  h2 = Handle{};
  // `where` keeps one buffer for the whole sweep, reserved before the base is
  // read, so its label is never a live allocation of the harness's own.
  std::string where;
  where.reserve(128);
  const int64_t live_base = u3hook::Host().live.load();
  if (!open_both()) {
    u3::Red("C64-GPU setup: two GPU handles reopen and encode", "a GPU open or warm-up encode was refused");
    return u3::ExitCode();
  }


  if (a.count_only) {
    if (!is_open) {
      u3hook::Count();
      drv.Run(h1.enc);
      K = u3hook::Disarm();
    }
    Line("K " + a.row + " " + u3::S(K));
    semb_encoder_close(h1.enc);
    semb_encoder_close(h2.enc);
    return 0;
  }

  const int fault = FaultOf(a.arm);
  size_t pi = 0;
  for (uint64_t k = a.first;; ++k) {
    const Site* site = nullptr;
    if (is_open) {
      while (pi < plan.size() && plan[pi].k < a.first) ++pi;
      if (pi == plan.size() || (a.last != 0 && plan[pi].k > a.last)) {
        Line("END " + a.row + " " + a.arm + " k=" + u3::S(K + 1) + " (past K)");
        break;
      }
      site = &plan[pi++];
      k = site->k;
    } else if (a.last != 0 && k > a.last) {
      break;
    }
    Line("BEGIN " + a.row + " " + a.arm + " k=" + u3::S(k));
    if (is_open) ResetCallLog();
    const uint64_t c_before = semb_test_seam_gpu_call_count();
    const int64_t live_before = u3hook::Host().live.load();
    semb_status s;
    Handle h3;
    if (is_open) {
      s = OpenFrame(&h3, dims, false, k, fault);
    } else {
      u3hook::Arm(k, fault);
      try {
        s = drv.Run(h1.enc);
      } catch (...) {
        s = static_cast<semb_status>(-1000);
      }
    }
    u3hook::Disarm();
    if (!u3hook::Host().fired) {
      if (h3.enc) semb_encoder_close(h3.enc);
      if (site) {  // a planned site the armed open never reached: the plan does not describe this run
        Line("ARM " + a.row + " " + a.arm + " k=" + u3::S(k) + " site=" + site->cls + " NOT-REACHED FAIL");
        u3::Verdict(false, "C64-GPU " + a.row + " " + a.arm + " k=" + u3::S(k), "planned site not reached");
        continue;
      }
      Line("END " + a.row + " " + a.arm + " k=" + u3::S(k) + " (past K)");
      break;
    }
    const bool in_engine = u3hook::Host().fired_occupancy.load() > 0;
    {
      const std::string w = in_engine ? "engine:" + VerbAt(u3hook::Host().fired_call_count.load()) : std::string("u3");
      where.assign(w.data(), std::min<size_t>(w.size(), 127));  // within the reserved capacity: no allocation
    }
    const bool trylock = semb_test_seam_gpu_try_lock() == 1;
    // The plan's location must be where k actually fell (the open is deterministic).
    const bool on_plan = !site || (in_engine == site->engine &&
                                   u3hook::Host().fired_call_count.load() - c_before == site->rel_call);
    int32_t want;
    if (site && site->label) {
      want = SEMB_OK;  // PD-1: the label read never refuses the open (te266 P:4212)
    } else if (fault == u3hook::kForeign) {
      want = in_engine ? kUnavailable : static_cast<int32_t>(SEMB_ENGINE_REFUSED);
    } else {
      want = SEMB_ALLOCATION_FAILED;
    }
    const bool released = SeqReleaseLogged(c_before);
    const bool poisoned = s == kUnavailable;
    const int64_t live_after = u3hook::Host().live.load();

    // (c): the follow-ups.
    std::string moved = "-", second = "-";
    bool follow = false, second_ok = true, moved_ok = true;
    if (is_open) {
      bool h3_ok = true;
      if (s == SEMB_OK && h3.enc) {
        h3_ok = h3.Encode(a.text) == SEMB_OK && h3.Is(ref);  // an open that succeeded yields a working handle
        semb_encoder_close(h3.enc);
      }
      Handle h4;
      follow = h3_ok && OpenGpu(&h4, dims) == SEMB_OK && h4.Encode(a.text) == SEMB_OK && h4.Is(ref);
      if (h4.enc) semb_encoder_close(h4.enc);
      second_ok = h2.Encode(a.text) == SEMB_OK && h2.Is(ref);
      second = second_ok ? "1" : "0";
    } else {
      const uint64_t c0 = semb_test_seam_gpu_call_count();
      const semb_status sf = h1.Encode(a.text);
      const bool mv = semb_test_seam_gpu_call_count() > c0;
      moved = mv ? "1" : "0";
      if (poisoned) {
        follow = sf == kUnavailable;
        moved_ok = !mv;
      } else {
        follow = sf == SEMB_OK && h1.Is(ref);
        moved_ok = !in_engine || mv;
      }
      if (in_engine || poisoned) {
        second_ok = h2.Encode(a.text) == SEMB_OK && h2.Is(ref);
        second = second_ok ? "1" : "0";
      }
    }
    // (c)'s live count.
    std::string live;
    bool live_ok;
    if (released || poisoned || is_open) {
      const semb_status c1 = semb_encoder_close(h1.enc), c2 = semb_encoder_close(h2.enc);
      // The base was read before any handle existed, so the harness's own row
      // buffers (allocated after it) are freed before the live count is read.
      std::vector<float>().swap(h1.row);
      std::vector<float>().swap(h2.row);
      std::vector<float>().swap(h3.row);
      const int64_t contexts = semb_test_seam_gpu_context_count();
      const int64_t live_closed = u3hook::Host().live.load();
      live_ok = c1 == SEMB_OK && c2 == SEMB_OK && contexts == 0 && live_closed == live_base;
      live = live_ok ? "close-all" : "CLOSE-ALL-FAILED(contexts=" + std::to_string(contexts) +
                                         ",live=" + std::to_string(live_closed - live_base) + ")";
      h1 = Handle{};
      h2 = Handle{};
      if (!open_both()) {
        Line("ARM " + a.row + " " + a.arm + " k=" + u3::S(k) + " reopen after close-all failed FAIL");
        u3::Verdict(false, "C64-GPU " + a.row + " " + a.arm + " k=" + u3::S(k), "reopen failed");
        break;
      }
    } else {
      live_ok = live_after == live_before;
      live = live_ok ? "equal" : "MOVED(" + std::to_string(live_after - live_before) + ")";
    }
    const bool ok = s == want && trylock && follow && second_ok && moved_ok && live_ok && on_plan;
    Line("ARM " + a.row + " " + a.arm + " k=" + u3::S(k) + (site ? " site=" + site->cls : std::string()) +
         (on_plan ? "" : " DRIFTED") + " where=" + where + " status=" +
         (s == static_cast<semb_status>(-1000) ? std::string("ESCAPED") : std::string(u3::Name(s))) +
         " want=" + u3::Name(want) + " trylock=" + (trylock ? "1" : "0") + " follow=" + (follow ? "1" : "0") +
         " moved=" + moved + " second=" + second + " live=" + live + (ok ? " PASS" : " FAIL"));
    u3::Verdict(ok, "C64-GPU " + a.row + " " + a.arm + " k=" + u3::S(k), where);
  }
  if (h1.enc) semb_encoder_close(h1.enc);
  if (h2.enc) semb_encoder_close(h2.enc);
  const int64_t contexts = semb_test_seam_gpu_context_count();
  u3::Verdict(contexts == 0, "C64-GPU after close the context count is 0 (J12, capability 5)",
              std::to_string(contexts));
  std::printf("SUMMARY u3_c64_gpu_leg %s %s pass=%d fail=%d red=%d missing=%d\n", a.row.c_str(), a.arm.c_str(),
              u3::T().pass, u3::T().fail, u3::T().red, u3::T().missing);
  return u3::ExitCode();
}
