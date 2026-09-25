// tests/u2_10_c66b_rlimit_sweep_test.cpp -- U2 cloud build, U2-10's C66 (b):
// the real limit, the adversary's P1 sweep re-run against the build (te267
// sec 5 U2-10, C66 (b)). The GCC 13.3.0 leg: RLIMIT_AS, 256 KiB steps to
// 16 MiB above the process's current commit.
//
// Links the SHIPPED static product target (`superembedder`): no test seam, no
// injection. Opens the minimal-geometry cap-5,000 pair at max_concurrency 2
// and at 8, warms each handle with one unlimited batch of 16 documents and
// records the baseline rows. Then, for each step, it lowers the soft
// RLIMIT_AS to (address-space size now + step) and records:
//   - whether a probe thread started by the harness itself starts, and is joined;
//   - whether 256 KiB of 4 KiB objects can be allocated and freed (P1's heap leg);
//   - the status of the same 16-document batch.
// It then clears the limit and runs the batch again on the same handle.
//
// ORACLE, per step: the batch returns SEMB_OK with rows byte-equal to the
// baseline, or SEMB_ALLOCATION_FAILED, never another status; the unlimited
// follow-up returns the baseline. REACH, reported beside the verdict: the
// number of steps where the probe thread failed while the heap leg succeeded
// (the band the adversary's probe predicts). A sweep that reaches no such step
// reports that its real limit did not reach the thread start; leg (a) carries
// the thread-start grade there.
//
// The driver runs it with GLIBC_TUNABLES=glibc.pthread.stack_cache_size=0:
// glibc otherwise reuses an exited thread's cached stack without a new
// mapping, and the limit never reaches a thread start (read at the first run:
// 0 reach steps with the cache on, 32 of 64 with it off).
//
// RED TODAY [U until run; P1's prediction]: any step in the reach band reads
// SEMB_ENGINE_REFUSED.
//
// USAGE: --model <pair model> --tokenizer <pair tokenizer>
#include <sys/resource.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <new>
#include <string>
#include <system_error>
#include <thread>
#include <vector>

#include "superembedder/semb.h"

namespace {

uint64_t AddressSpaceBytes() {
  std::ifstream f("/proc/self/status");
  std::string line;
  while (std::getline(f, line)) {
    if (line.rfind("VmSize:", 0) == 0) return std::stoull(line.substr(7)) * 1024;
  }
  return 0;
}

bool SetAsLimit(rlim_t soft) {
  rlimit r{};
  if (getrlimit(RLIMIT_AS, &r) != 0) return false;
  r.rlim_cur = soft;
  return setrlimit(RLIMIT_AS, &r) == 0;
}

struct Batch {
  std::vector<std::string> ids, texts;
  std::vector<semb_document> docs;
  Batch() {
    for (int i = 0; i < 16; ++i) {
      ids.push_back("d" + std::to_string(i));
      texts.push_back(std::string(24 + i, static_cast<char>('a' + (i % 20))));
    }
    docs.resize(16);
    for (int i = 0; i < 16; ++i) {
      docs[i].struct_size = sizeof(semb_document);
      docs[i].id = ids[i].data();
      docs[i].id_len = ids[i].size();
      docs[i].utf8 = texts[i].data();
      docs[i].utf8_len = texts[i].size();
    }
  }
};

semb_status RunBatch(semb_encoder e, const Batch& b, std::vector<float>* rows) {
  size_t req = 0;
  return semb_encode_batch(e, b.docs.data(), b.docs.size(), rows->data(), rows->size() * 4, &req);
}

bool ProbeThread() {
  try {
    std::thread t([] {});
    t.join();
    return true;
  } catch (const std::system_error&) {
    return false;
  } catch (...) {
    return false;
  }
}

bool HeapLeg() {
  std::vector<char*> blocks;
  blocks.reserve(64);
  bool ok = true;
  try {
    for (int i = 0; i < 64; ++i) blocks.push_back(new char[4096]);
  } catch (const std::bad_alloc&) {
    ok = false;
  }
  for (char* p : blocks) delete[] p;
  return ok;
}

}  // namespace

int main(int argc, char** argv) {
  std::string model, tokenizer;
  for (int i = 1; i + 1 < argc; ++i) {
    const std::string k = argv[i];
    if (k == "--model") model = argv[++i];
    else if (k == "--tokenizer") tokenizer = argv[++i];
  }
  if (model.empty() || tokenizer.empty()) {
    std::fprintf(stderr, "usage: %s --model <m> --tokenizer <t>\n", argv[0]);
    return 2;
  }
  const Batch batch;
  int fails = 0;
  for (const uint32_t mc : {2u, 8u}) {
    semb_config cfg{};
    cfg.struct_size = sizeof(cfg);
    cfg.model_path = model.data();
    cfg.model_path_len = model.size();
    cfg.tokenizer_path = tokenizer.data();
    cfg.tokenizer_path_len = tokenizer.size();
    cfg.max_concurrency = mc;
    semb_encoder enc = nullptr;
    const semb_status os = semb_encoder_open(&cfg, &enc);
    if (os != SEMB_OK) {
      std::printf("[FAIL] C66 (b) mc %u open: %s\n", mc, semb_status_name(os));
      ++fails;
      continue;
    }
    uint32_t dims = 0;
    semb_encoder_dims(enc, &dims);
    std::vector<float> baseline(16 * dims), rows(16 * dims), follow(16 * dims);
    const semb_status bs = RunBatch(enc, batch, &baseline);
    if (bs != SEMB_OK) {
      std::printf("[FAIL] C66 (b) mc %u warm-up batch: %s\n", mc, semb_status_name(bs));
      ++fails;
      semb_encoder_close(enc);
      continue;
    }
    int steps = 0, bad = 0, reach = 0, ok_steps = 0, alloc_failed = 0;
    std::string first_bad;
    for (uint64_t step = 256 * 1024; step <= 16ull * 1024 * 1024; step += 256 * 1024) {
      std::fill(rows.begin(), rows.end(), 0.0f);
      const uint64_t base = AddressSpaceBytes();
      if (!SetAsLimit(static_cast<rlim_t>(base + step))) {
        std::printf("[FAIL] C66 (b) setrlimit refused at step %llu\n", static_cast<unsigned long long>(step));
        ++fails;
        break;
      }
      const bool thread_ok = ProbeThread();
      const bool heap_ok = HeapLeg();
      const semb_status s = RunBatch(enc, batch, &rows);
      SetAsLimit(RLIM_INFINITY);
      ++steps;
      if (!thread_ok && heap_ok) ++reach;
      const bool good = (s == SEMB_OK && rows == baseline) || s == SEMB_ALLOCATION_FAILED;
      if (s == SEMB_OK) ++ok_steps;
      if (s == SEMB_ALLOCATION_FAILED) ++alloc_failed;
      if (!good) {
        ++bad;
        if (first_bad.empty()) {
          first_bad = "step " + std::to_string(step / 1024) + " KiB: " + semb_status_name(s) +
                      (s == SEMB_OK ? " (rows differ)" : "") + " thread=" + (thread_ok ? "1" : "0") +
                      " heap=" + (heap_ok ? "1" : "0");
        }
      }
      std::printf("STEP mc=%u limit=+%llu KiB thread=%d heap=%d batch=%s%s\n", mc,
                  static_cast<unsigned long long>(step / 1024), thread_ok ? 1 : 0, heap_ok ? 1 : 0,
                  semb_status_name(s), s == SEMB_OK && rows != baseline ? " ROWS-DIFFER" : "");
    }
    const semb_status fs = RunBatch(enc, batch, &follow);
    const bool follow_ok = fs == SEMB_OK && follow == baseline;
    const semb_status cs = semb_encoder_close(enc);
    const bool pass = bad == 0 && follow_ok && cs == SEMB_OK;
    if (!pass) ++fails;
    std::printf("[%s] C66 (b) mc %u RLIMIT_AS sweep, 256 KiB steps to 16 MiB: every step SEMB_OK = baseline or "
                "SEMB_ALLOCATION_FAILED; unlimited follow-up = baseline: steps=%d ok=%d alloc_failed=%d bad=%d%s "
                "follow=%s close=%s\n",
                pass ? "PASS" : "FAIL", mc, steps, ok_steps, alloc_failed, bad,
                first_bad.empty() ? "" : (" first bad: " + first_bad).c_str(), semb_status_name(fs),
                semb_status_name(cs));
    if (reach == 0) {
      std::printf("[REACH] C66 (b) mc %u: 0 steps where the probe thread failed while the heap leg succeeded -- "
                  "the real limit did not reach the thread start; leg (a) carries the thread-start grade\n",
                  mc);
    } else {
      std::printf("[REACH] C66 (b) mc %u: %d steps where the probe thread failed while the heap leg succeeded\n",
                  mc, reach);
    }
  }
  std::printf("TOTAL fail=%d\n", fails);
  return fails ? 1 : 0;
}
