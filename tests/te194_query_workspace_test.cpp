// tests/te194_query_workspace_test.cpp -- TE-194 (U1 slice 5 red suite,
// `Claude/Bach/briefs/te194-slice5-red.md`): C26's remaining two races (the
// query-side half of cell 3; dim 3), on the K-15 seam pattern
// tests/u1_batch_workspace_test.cpp's own C26a already establishes for the
// encoder-vs-batch race, with `semb_query_encode` as the in-flight call in
// place of `semb_encode_batch`. A PARKED CONTENDER AND A REAL CROSSING,
// NEVER A SLEEP (this round's own dispatch): `semb_test_seam_arm_park(1)`
// parks the next successful workspace acquisition process-wide, and
// `semb_query_encode` is expected to acquire a workspace through the SAME
// per-call pool `semb_encode`/`semb_encode_batch` already share (sec 3.1:
// "an internal per-call workspace from an internal pool"), so parking it
// mid-flight needs no product-side change beyond the verb existing.
//
// RED AT 21b1735: undefined at link, same reason as te194_query_test.cpp
// (`semb_query_open`/`semb_query_encode`/`semb_query_close` do not exist).
// Links `superembedder_testseam` (the K-15-instrumented mirror of
// `superembedder`), the identical wiring `u1_batch_workspace_test.cpp`
// already uses -- registered via a DEFERRED cmake function
// (`semb_add_te194_query_workspace_tests`, appended to
// `semb_add_workspace_tests`'s own scheduling in `tests/CMakeLists.txt`) so
// `superembedder_testseam` exists before this target links against it.
//
// THE BANK-CLOSED-UNDER-A-LIVE-QUERY LEG (C26's third race in the plan's
// own list, `SuperEmbedder_Plan.md` sec 8 C26) is NOT here: it needs no
// in-flight parking at all -- D-SLM4664's own reference count is
// incremented at OPEN and decremented at CLOSE, so "a bank closed under a
// live query handle" is a sequential construction (open bank, open query,
// attempt close, observe SEMB_BANK_IN_USE, close query, close bank again).
// That construction is in tests/te194_query_test.cpp (cell1/C26-leg3),
// which links plain `superembedder` and needs no seam. Only the FOURTH
// race -- "a query handle closed mid-semb_query_encode" -- and the
// "second concurrent call on one query handle" refusal cell1 names both
// need genuine in-flight parking, and both are the SAME construction
// (two callers contending for one live semb_query handle while a call is
// actually in flight on it), so this file builds it once and cites it for
// both.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <future>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bank_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_query_abi_contract.h"
#include "support/semb_workspace_seam.h"

using namespace std::chrono_literals;

namespace {

int g_failures = 0;
int g_cells = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
void Missing(const std::string& cell, const std::string& why) {
  ++g_cells;
  std::printf("[MISSING PREREQUISITE] %s: %s\n", cell.c_str(), why.c_str());
  std::fflush(stdout);
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }

void FatalTimeout(const char* phase) { Verdict(false, phase, "deadline exceeded"); std::fflush(nullptr); std::_Exit(1); }

void ReleaseBounded(std::chrono::steady_clock::time_point deadline) {
  auto f = std::async(std::launch::async, [] { semb_test_seam_release(); });
  if (f.wait_until(deadline) != std::future_status::ready) FatalTimeout("cleanup release exceeded deadline");
  f.get();
}

void ResetSeam(std::chrono::steady_clock::time_point deadline) {
  auto f = std::async(std::launch::async, [] { return semb_test_seam_reset(); });
  if (f.wait_until(deadline) != std::future_status::ready) FatalTimeout("cleanup reset exceeded deadline");
  Verdict(f.get() == 1 && semb_test_seam_acquisitions() == 0 && semb_test_seam_parked() == 0,
          "(setup) reset establishes empty epoch", "");
}

auto Deadline30() { return std::chrono::steady_clock::now() + 30s; }

class DocSet {
 public:
  DocSet() { arena_.reserve(64); }
  semb_document Add(std::string id, std::string text) {
    arena_.push_back(std::move(id));
    const std::string& sid = arena_.back();
    arena_.push_back(std::move(text));
    const std::string& stext = arena_.back();
    semb_document d{};
    d.struct_size = sizeof(semb_document);
    d.id = sid.c_str();
    d.id_len = sid.size();
    d.utf8 = stext.c_str();
    d.utf8_len = stext.size();
    return d;
  }

 private:
  std::vector<std::string> arena_;
};

struct Args {
  std::string model, tokenizer, scratch;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--scratch") next(&a.scratch);
  }
  return a;
}

}  // namespace

int main(int argc, char** argv) {
  Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.scratch.empty()) {
    Missing("te194 query workspace cells", "requires --model --tokenizer --scratch");
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return g_failures > 0 ? 1 : 0;
  }

  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = a.model.data();
  c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data();
  c.tokenizer_path_len = a.tokenizer.size();
  c.max_concurrency = 1;  // one workspace slot: guarantees a second in-flight
                          // call cannot silently proceed on a SPARE slot --
                          // it must contend for the SAME one this test parks.
  semb_encoder enc = nullptr;
  const semb_status open_s = semb_encoder_open(&c, &enc);
  if (open_s != SEMB_OK || !enc) {
    Verdict(false, "(setup) semb_encoder_open", Name(open_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  DocSet docs;
  std::vector<semb_document> doc_vec = {docs.Add("wsq-00", "a single document for the query workspace fixture bank")};
  const std::string stem = a.scratch + "/te194_ws_bank";
  const semb_status bake_s = semb_bake_to_path(enc, doc_vec.data(), doc_vec.size(), stem.c_str(), stem.size());
  if (bake_s != SEMB_OK) {
    Verdict(false, "(setup) semb_bake_to_path", Name(bake_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }
  semb_bank bank = nullptr;
  const semb_status bank_open_s = semb_bank_open(stem.c_str(), stem.size(), &bank);
  if (bank_open_s != SEMB_OK || !bank) {
    Verdict(false, "(setup) semb_bank_open", Name(bank_open_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }
  semb_query q = nullptr;
  const semb_status q_open_s = semb_query_open(enc, bank, &q);
  if (q_open_s != SEMB_OK || !q) {
    Verdict(false, "(setup) semb_query_open", Name(q_open_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  const std::vector<uint8_t> vec_buf_storage(dims * sizeof(float) + 64, 0xA5);
  auto AlignedFloatPtr = [&](std::vector<uint8_t>& buf) {
    auto p = reinterpret_cast<uintptr_t>(buf.data());
    return reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
  };

  // =========================================================================
  // Cell 3a / cell1's own "second concurrent call on one query handle":
  // a semb_query_encode call parked mid-flight (one workspace slot,
  // arm_park(1)), a SECOND semb_query_encode on the SAME q from the main
  // thread while parked -> SEMB_HANDLE_IN_USE, nothing freed; release; the
  // first call completes SEMB_OK.
  // =========================================================================
  {
    ResetSeam(Deadline30());
    Verdict(semb_test_seam_arm_park(1) == 1, "cell3a (setup) arm one park", "");

    std::vector<uint8_t> buf1 = vec_buf_storage;
    size_t req1 = 0;
    semb_status status1 = static_cast<semb_status>(-1000);
    const std::string qtext = "the parked in-flight query";
    auto job1 = std::async(std::launch::async, [&] {
      status1 = semb_query_encode(q, qtext.data(), qtext.size(), AlignedFloatPtr(buf1),
                                   buf1.size() - 16, &req1);
    });

    const bool parked = semb_test_seam_wait_parked(1, 10000) == 1 && semb_test_seam_parked() == 1;
    Verdict(parked, "cell3a (setup) the first semb_query_encode call parks at its workspace acquisition", "");

    if (parked) {
      std::vector<uint8_t> buf2 = vec_buf_storage;
      size_t req2 = 0;
      const std::string qtext2 = "a second call contending for the same query handle";
      auto job2 = std::async(std::launch::async, [&] {
        return semb_query_encode(q, qtext2.data(), qtext2.size(), AlignedFloatPtr(buf2), buf2.size() - 16, &req2);
      });
      const bool ready2 = job2.wait_for(10s) == std::future_status::ready;
      Verdict(ready2, "cell3a second call deadline while the first is parked in flight", "");
      if (ready2) {
        const semb_status status2 = job2.get();
        Verdict(status2 == SEMB_HANDLE_IN_USE,
                "cell3a second semb_query_encode call on the SAME live handle -> SEMB_HANDLE_IN_USE, nothing freed",
                Name(status2));
      }
      ReleaseBounded(Deadline30());
      if (job1.wait_until(Deadline30()) != std::future_status::ready) FatalTimeout("cell3a first job cleanup deadline");
      job1.get();
      Verdict(status1 == SEMB_OK,
              "cell3a the parked first semb_query_encode call itself completes once released", Name(status1));
    } else {
      ReleaseBounded(Deadline30());
      if (job1.wait_until(Deadline30()) != std::future_status::ready) FatalTimeout("cell3a first job cleanup (unparked path)");
      job1.get();
    }
    ResetSeam(Deadline30());
  }

  // =========================================================================
  // Cell 3b / C26's fourth race: a query handle closed mid-semb_query_encode.
  // Mirrors u1_batch_workspace_test.cpp's own C26a exactly, with
  // semb_query_encode as the in-flight call and semb_query_close as the
  // contending teardown.
  // =========================================================================
  {
    ResetSeam(Deadline30());
    Verdict(semb_test_seam_arm_park(1) == 1, "cell3b (setup) arm one park", "");

    std::vector<uint8_t> buf = vec_buf_storage;
    size_t req = 0;
    semb_status encode_status = static_cast<semb_status>(-1000);
    const std::string qtext = "parked while a close races it";
    auto encode_job = std::async(std::launch::async, [&] {
      encode_status = semb_query_encode(q, qtext.data(), qtext.size(), AlignedFloatPtr(buf), buf.size() - 16, &req);
    });

    const bool parked = semb_test_seam_wait_parked(1, 10000) == 1 && semb_test_seam_parked() == 1;
    Verdict(parked, "cell3b (setup) semb_query_encode parks at its workspace acquisition", "");

    if (parked) {
      auto close_job = std::async(std::launch::async, [&] { return semb_query_close(q); });
      const bool close_ready = close_job.wait_for(10s) == std::future_status::ready;
      Verdict(close_ready, "cell3b close deadline while semb_query_encode is parked in flight", "");
      if (close_ready) {
        const semb_status close_status = close_job.get();
        Verdict(close_status == SEMB_HANDLE_IN_USE,
                "cell3b/C26-leg4 semb_query_close while semb_query_encode is in flight -> SEMB_HANDLE_IN_USE, nothing freed",
                Name(close_status));
      }
      ReleaseBounded(Deadline30());
      if (encode_job.wait_until(Deadline30()) != std::future_status::ready) FatalTimeout("cell3b encode job cleanup deadline");
      encode_job.get();
      Verdict(encode_status == SEMB_OK,
              "cell3b/C26-leg4 the parked semb_query_encode call itself completes once released", Name(encode_status));

      // The handle was never freed (the close was refused): a real close
      // now succeeds, proving the handle survived the in-flight refusal
      // intact -- the same "close AFTER the drain succeeds" evidence
      // u1_batch_workspace_test.cpp's own C26a requires.
      const semb_status final_close = semb_query_close(q);
      Verdict(final_close == SEMB_OK,
              "cell3b/C26-leg4 close AFTER the drain succeeds -- the handle was never freed by the refused close",
              Name(final_close));
      const semb_status bank_close_after = semb_bank_close(bank);
      Verdict(bank_close_after == SEMB_OK,
              "cell3b (teardown) semb_bank_close now succeeds -- no outstanding query handle remains",
              Name(bank_close_after));
    } else {
      ReleaseBounded(Deadline30());
      if (encode_job.wait_until(Deadline30()) != std::future_status::ready) FatalTimeout("cell3b encode job cleanup (unparked path)");
      encode_job.get();
      semb_query_close(q);
      semb_bank_close(bank);
    }
    ResetSeam(Deadline30());
  }

  semb_encoder_close(enc);

  std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
  return g_failures > 0 ? 1 : 0;
}
