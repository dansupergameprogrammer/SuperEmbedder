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
  const int64_t live_base = u3hook::Host().live.load();

  Handle h1, h2;
  auto open_both = [&]() -> bool {
    return OpenGpu(&h1, dims) == SEMB_OK && OpenGpu(&h2, dims) == SEMB_OK && h1.Encode(a.text) == SEMB_OK &&
           h2.Encode(a.text) == SEMB_OK;
  };
  if (!open_both()) {
    u3::Red("C64-GPU setup: two GPU handles open and encode", "a GPU open or warm-up encode was refused");
    return u3::ExitCode();
  }

  if (a.count_only) {
    u3hook::Count();
    if (is_open) {
      Handle h3;
      OpenGpu(&h3, dims);
      u3hook::Disarm();
      if (h3.enc) semb_encoder_close(h3.enc);
    } else {
      drv.Run(h1.enc);
    }
    Line("K " + a.row + " " + u3::S(u3hook::Disarm()));
    semb_encoder_close(h1.enc);
    semb_encoder_close(h2.enc);
    return 0;
  }

  const int fault = FaultOf(a.arm);
  for (uint64_t k = a.first; a.last == 0 || k <= a.last; ++k) {
    Line("BEGIN " + a.row + " " + a.arm + " k=" + u3::S(k));
    const uint64_t c_before = semb_test_seam_gpu_call_count();
    const int64_t live_before = u3hook::Host().live.load();
    semb_status s;
    Handle h3;
    if (is_open) {
      h3.row.assign(dims, 0.0f);
      const u3::Config cfg = u3::MakeConfig(a.model, a.tokenizer, 1, u3::kDeviceGpu);
      u3hook::Arm(k, fault);
      try {
        s = u3::Open(cfg, &h3.enc);
      } catch (...) {
        s = static_cast<semb_status>(-1000);  // escaped: the harness's own catch is red
      }
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
      Line("END " + a.row + " " + a.arm + " k=" + u3::S(k) + " (past K)");
      break;
    }
    const bool in_engine = u3hook::Host().fired_occupancy.load() > 0;
    const std::string where =
        in_engine ? "engine:" + VerbAt(u3hook::Host().fired_call_count.load() + 1) : std::string("u3");
    const bool trylock = semb_test_seam_gpu_try_lock() == 1;
    int32_t want;
    if (fault == u3hook::kForeign) {
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
      if (s == SEMB_OK && h3.enc) semb_encoder_close(h3.enc);
      Handle h4;
      follow = OpenGpu(&h4, dims) == SEMB_OK && h4.Encode(a.text) == SEMB_OK && h4.Is(ref);
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
    const bool ok = s == want && trylock && follow && second_ok && moved_ok && live_ok;
    Line("ARM " + a.row + " " + a.arm + " k=" + u3::S(k) + " where=" + where + " status=" +
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
