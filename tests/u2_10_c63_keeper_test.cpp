// tests/u2_10_c63_keeper_test.cpp -- U2 cloud build, U2-10's C63: the
// adversary's keeper (te267 sec 5 U2-10, C63), authored from the adversary's
// probe (te408_encode_oom_probe.cpp), independently of the builder.
//
// Public semb.h API only, on the pinned REAL model and tokenizer. Links the
// member's own static product target and engine, with the global operator new
// replaced: the armed call fails, once, the first allocation of at least
// 100,000 B it makes. The document has the adversary's mid.txt's measured
// shape, 133 positions (P:3183-3184).
//
// THE TEXTS. The adversary's mid.txt (603 B) and short.txt were cut from a
// pool that no longer exists. Their replacements are committed:
// tests/fixtures/c63/mid.txt (fiqa-295971, 645 B, 132 content tokens + the
// terminator = 133 positions) and short.txt (fiqa-103125, 56 B), selected by
// tests/fixtures/c63/regenerate_c63_texts.py from a committed FiQA pool whose
// token ids were measured by the real tokenizer; hashes in
// c63-texts.manifest.json. The cell asserts both files' byte counts first.
//
// SETUP PRECONDITION, ASSERTED ON EVERY LEG (P:3185-3192): the fired size
// equals the leg's predicted value, stated before the run: positions x
// hidden, the batch worker's `codes` buffer (std::vector<int8_t>), plus what
// the standard library's allocator adds to that request before it reaches
// operator new. On the encode legs, 133 x 1,024 = 136,192 B; under the MSVC
// STL (cl.exe and clang-cl) a request of 4,096 B or more is over-allocated for
// 32-byte alignment by sizeof(void*) + 31 = 39 B on x64 Release, which is
// the 136,231 B TE-408's hook read on cl.exe [M]; on libstdc++ it adds 0. On
// the query leg, the composed query's positions x 1,024 + the same overhead:
// the adversary's text read 154,663 B = 151 x 1,024 + 39 on cl.exe [M]. The
// replacement mid.txt's composed-query position count is NOT yet measured
// (it needs the real tokenizer; see the manifest), so until it is stated
// (--query-positions, or kQueryPositions below once measured) the query legs
// do not run and report PRECONDITION. A fired size that differs emits NO
// verdict for that leg (reported as PRECONDITION), and the difference is
// attributed before the cell runs again.
//
// Legs, at max_concurrency 1 and 4 (at 4, four consecutive armed calls fail
// before the follow-ups, each able to take one slot):
//   (i)   semb_encode armed        -> SEMB_ALLOCATION_FAILED
//   (ii)  semb_encode_batch armed  -> SEMB_ALLOCATION_FAILED
//   (iii) semb_query_encode armed  -> SEMB_ALLOCATION_FAILED
// then on the same handle: semb_encode of the short and mid texts,
// semb_encode_batch of the mid text, semb_query_encode of the short text on a
// query over a one-row bank baked from the same encoder before arming -- each
// SEMB_OK with the WHOLE vector byte-equal to its pre-arming baseline; then
// every close returns SEMB_OK.
//
// RED TODAY on cl.exe at 1 and 4 (the plan's reading); GREEN today on
// clang-cl for the adapter TU and on the prototype. On GCC it is run for its
// reading. Real artifact only: without --model/--tokenizer/--mid/--short it
// reports MISSING PREREQUISITE and exits 0 (tests/CMakeLists.txt passes the
// committed texts; the model and tokenizer are the configure's).
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <new>
#include <sstream>
#include <string>
#include <vector>

#include "superembedder/semb.h"
#include "superembedder/bake_abi.h"

namespace hook {
std::atomic<bool> armed{false};
std::atomic<size_t> threshold{100000};
std::atomic<size_t> fired_size{0};
std::atomic<int> fired{0};
void* Alloc(size_t n) {
  if (armed.load(std::memory_order_acquire) && n >= threshold.load()) {
    bool expected = true;
    if (armed.compare_exchange_strong(expected, false)) {
      fired_size.store(n);
      fired.fetch_add(1);
      throw std::bad_alloc();
    }
  }
  void* p = std::malloc(n ? n : 1);
  if (!p) throw std::bad_alloc();
  return p;
}
}  // namespace hook
void* operator new(size_t n) { return hook::Alloc(n); }
void* operator new[](size_t n) { return hook::Alloc(n); }
void* operator new(size_t n, const std::nothrow_t&) noexcept {
  try { return hook::Alloc(n); } catch (...) { return nullptr; }
}
void* operator new[](size_t n, const std::nothrow_t&) noexcept {
  try { return hook::Alloc(n); } catch (...) { return nullptr; }
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }

namespace {

int g_fail = 0;
void Verdict(bool ok, const std::string& cell, const std::string& detail) {
  if (!ok) ++g_fail;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), detail.c_str());
  std::fflush(stdout);
}
std::string ReadAll(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  std::stringstream ss;
  ss << f.rdbuf();
  return ss.str();
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "?"; }

// The committed texts' measured shape (tests/fixtures/c63/c63-texts.manifest.json).
constexpr size_t kMidBytes = 645;
constexpr size_t kShortBytes = 56;
constexpr size_t kMidPositions = 133;
// The query leg's composed positions for mid.txt: 0 = not yet measured.
constexpr size_t kQueryPositions = 0;
constexpr size_t kHidden = 1024;

// What the standard library's allocator adds to a std::vector request before
// calling operator new. The MSVC STL over-allocates requests of at least
// 4,096 B on x86/x64 for 32-byte alignment: sizeof(void*) + 31 B, plus one
// more pointer (a sentinel) under _DEBUG. libstdc++ and libc++ add nothing.
size_t AllocatorOverhead(size_t request) {
#if defined(_MSVC_STL_VERSION) && (defined(_M_X64) || defined(_M_IX86)) && !defined(_M_ARM64EC)
  if (request >= 4096) {
#ifdef _DEBUG
    return 2 * sizeof(void*) + 31;
#else
    return sizeof(void*) + 31;
#endif
  }
#endif
  (void)request;
  return 0;
}
size_t Predicted(size_t positions) { return positions * kHidden + AllocatorOverhead(positions * kHidden); }

struct Vec {
  semb_status st = SEMB_OK;
  std::vector<float> v;
};
Vec Encode(semb_encoder e, const std::string& t, uint32_t dims) {
  Vec r;
  r.v.assign(dims, 0.0f);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  r.st = semb_encode(e, t.data(), t.size(), r.v.data(), r.v.size() * 4, &req, &fp);
  return r;
}
Vec Batch(semb_encoder e, const std::string& t, uint32_t dims) {
  Vec r;
  r.v.assign(dims, 0.0f);
  semb_document d{};
  d.struct_size = sizeof(d);
  d.id = "d0";
  d.id_len = 2;
  d.utf8 = t.data();
  d.utf8_len = t.size();
  size_t req = 0;
  r.st = semb_encode_batch(e, &d, 1, r.v.data(), r.v.size() * 4, &req);
  return r;
}
Vec Query(semb_query q, const std::string& t, uint32_t dims) {
  Vec r;
  r.v.assign(dims, 0.0f);
  size_t req = 0;
  r.st = semb_query_encode(q, t.data(), t.size(), r.v.data(), r.v.size() * 4, &req);
  return r;
}

}  // namespace

int main(int argc, char** argv) {
  std::string model, tokenizer, mid_path, short_path, scratch = ".";
  size_t mid_positions = kMidPositions, query_positions = kQueryPositions;
  size_t predicted_encode = 0, predicted_query = 0;  // 0 = derive from positions
  for (int i = 1; i + 1 < argc; ++i) {
    const std::string k = argv[i];
    if (k == "--model") model = argv[++i];
    else if (k == "--tokenizer") tokenizer = argv[++i];
    else if (k == "--mid") mid_path = argv[++i];
    else if (k == "--short") short_path = argv[++i];
    else if (k == "--scratch") scratch = argv[++i];
    else if (k == "--predicted-encode") predicted_encode = std::strtoull(argv[++i], nullptr, 10);
    else if (k == "--predicted-query") predicted_query = std::strtoull(argv[++i], nullptr, 10);
    else if (k == "--mid-positions") mid_positions = std::strtoull(argv[++i], nullptr, 10);
    else if (k == "--query-positions") query_positions = std::strtoull(argv[++i], nullptr, 10);
  }
  if (predicted_encode == 0) predicted_encode = Predicted(mid_positions);
  if (predicted_query == 0 && query_positions != 0) predicted_query = Predicted(query_positions);
  if (model.empty() || tokenizer.empty() || mid_path.empty() || short_path.empty()) {
    std::printf("[MISSING PREREQUISITE] C63: needs the real model, its tokenizer, and the committed mid.txt "
                "(645 B, 133 positions) and short.txt -- owed to the dev box (cl.exe members at 1 and 4)\n");
    return 0;
  }
  const std::string mid = ReadAll(mid_path), shrt = ReadAll(short_path);
  Verdict(mid.size() == kMidBytes, "C63 setup: mid.txt is the committed 645-byte, 133-position document",
          std::to_string(mid.size()) + " bytes");
  Verdict(shrt.size() == kShortBytes, "C63 setup: short.txt is the committed 56-byte document",
          std::to_string(shrt.size()) + " bytes");
  std::printf("C63 predicted fired sizes, stated before the run: encode legs %zu B (%zu positions); query leg %s\n",
              predicted_encode, mid_positions,
              predicted_query ? (std::to_string(predicted_query) + " B").c_str()
                              : "NOT STATED (the composed query's positions are unmeasured)");
  for (const uint32_t mc : {1u, 4u}) {
    for (int leg = 0; leg < 3; ++leg) {
      const char* leg_name = leg == 0 ? "(i) semb_encode" : leg == 1 ? "(ii) semb_encode_batch" : "(iii) semb_query_encode";
      const std::string tag = std::string("C63 ") + leg_name + " armed, mc " + std::to_string(mc);
      if (leg == 2 && predicted_query == 0) {
        std::printf("[PRECONDITION] %s: the query leg's predicted fired size is not stated (mid.txt's composed-query "
                    "positions are unmeasured; tests/fixtures/c63/regenerate_c63_texts.py --measure) -- no verdict\n",
                    tag.c_str());
        ++g_fail;
        continue;
      }
      semb_config cfg{};
      cfg.struct_size = sizeof(cfg);
      cfg.model_path = model.data();
      cfg.model_path_len = model.size();
      cfg.tokenizer_path = tokenizer.data();
      cfg.tokenizer_path_len = tokenizer.size();
      cfg.max_concurrency = mc;
      semb_encoder enc = nullptr;
      const semb_status os = semb_encoder_open(&cfg, &enc);
      if (os != SEMB_OK) { Verdict(false, tag + " open", Name(os)); continue; }
      uint32_t dims = 0;
      semb_encoder_dims(enc, &dims);
      // Baselines, before arming.
      const Vec b_short = Encode(enc, shrt, dims), b_mid = Encode(enc, mid, dims), b_batch = Batch(enc, mid, dims);
      const std::string stem = scratch + "/c63_bank_" + std::to_string(mc) + "_" + std::to_string(leg);
      semb_document d{};
      d.struct_size = sizeof(d);
      d.id = "s0";
      d.id_len = 2;
      d.utf8 = shrt.data();
      d.utf8_len = shrt.size();
      semb_bank bank = nullptr;
      semb_query q = nullptr;
      const semb_status bk = semb_bake_to_path(enc, &d, 1, stem.data(), stem.size());
      const semb_status bo = bk == SEMB_OK ? semb_bank_open(stem.data(), stem.size(), &bank) : bk;
      const semb_status qo = bo == SEMB_OK ? semb_query_open(enc, bank, &q) : bo;
      if (qo != SEMB_OK) { Verdict(false, tag + " setup bank/query", Name(qo)); semb_encoder_close(enc); continue; }
      const Vec b_query = Query(q, shrt, dims);
      // The armed calls: one at mc 1, four consecutive at mc 4.
      const size_t predicted = leg == 2 ? predicted_query : predicted_encode;
      bool statuses_ok = true, sizes_ok = true, escaped = false;
      std::string detail;
      for (uint32_t call = 0; call < (mc == 1 ? 1u : 4u); ++call) {
        hook::fired.store(0);
        hook::fired_size.store(0);
        hook::armed.store(true, std::memory_order_release);
        semb_status st = SEMB_OK;
        try {
          st = leg == 0 ? Encode(enc, mid, dims).st : leg == 1 ? Batch(enc, mid, dims).st : Query(q, mid, dims).st;
        } catch (...) {
          escaped = true;
        }
        hook::armed.store(false);
        const size_t fs = hook::fired_size.load();
        sizes_ok = sizes_ok && hook::fired.load() == 1 && fs == predicted;
        statuses_ok = statuses_ok && !escaped && st == SEMB_ALLOCATION_FAILED;
        detail += (call ? "; " : "") + std::string(escaped ? "ESCAPED" : Name(st)) + " fired=" + std::to_string(fs);
      }
      if (!sizes_ok) {
        std::printf("[PRECONDITION] %s: fired size differs from the predicted %zu B (%s) -- no verdict; the "
                    "difference is attributed before the cell runs again\n",
                    tag.c_str(), predicted, detail.c_str());
        ++g_fail;
      } else {
        const Vec f_short = Encode(enc, shrt, dims), f_mid = Encode(enc, mid, dims), f_batch = Batch(enc, mid, dims);
        const Vec f_query = Query(q, shrt, dims);
        const bool follow = f_short.st == SEMB_OK && f_short.v == b_short.v && f_mid.st == SEMB_OK &&
                            f_mid.v == b_mid.v && f_batch.st == SEMB_OK && f_batch.v == b_batch.v &&
                            f_query.st == SEMB_OK && f_query.v == b_query.v;
        const semb_status qc = semb_query_close(q);
        const semb_status bc = semb_bank_close(bank);
        const semb_status ec = semb_encoder_close(enc);
        q = nullptr;
        bank = nullptr;
        enc = nullptr;
        Verdict(statuses_ok && follow && qc == SEMB_OK && bc == SEMB_OK && ec == SEMB_OK,
                tag + ": SEMB_ALLOCATION_FAILED; follow-ups SEMB_OK with whole vectors = baseline; closes SEMB_OK",
                detail + " | follow-ups " + Name(f_short.st) + "/" + Name(f_mid.st) + "/" + Name(f_batch.st) + "/" +
                    Name(f_query.st) + (follow ? " equal" : " DIFFER") + " | closes " + Name(qc) + "/" + Name(bc) +
                    "/" + Name(ec));
      }
      if (q) semb_query_close(q);
      if (bank) semb_bank_close(bank);
      if (enc) semb_encoder_close(enc);
    }
  }
  std::printf("TOTAL fail=%d\n", g_fail);
  return g_fail ? 1 : 0;
}
