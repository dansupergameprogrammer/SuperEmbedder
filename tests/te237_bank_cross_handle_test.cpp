// tests/te237_bank_cross_handle_test.cpp -- TE-237 (U1 slice 6 fix-round
// pins, Claude/Bach/briefs/te237-slice6-s3-pins.md): the S-3 cross-handle
// construction the TE-236 review asks for (D-SLM6642, sec 6: "a
// cross-handle construction that parks snapshot materialization while
// proving close/acquire on a distinct live bank can complete").
//
// THE CELL. While one semb_bank_open is parked at its
// snapshot-materialization point, every registry operation on a DISTINCT,
// already-open bank completes without waiting for it: both state accessors
// (semb_bank_debug_state, semb_bank_ranked_state), a live query's close
// (semb_query_close, the review's named victim, which waits at
// semb_bank_release_query), a new query's acquisition and its release
// (semb_bank_acquire_query / semb_bank_release_query), and the bank's own
// close (semb_bank_close). The construction is DETERMINISTIC, never a
// timing race: the materializing open is parked at a known point by the
// test seam below, and each cross-handle operation runs under its own
// deadline (10 s), so a blocked operation is a FAIL row, never a hang.
//
// RED AT fe0c0e0, AT LINK, FOR THE NAMED MISSING SYMBOLS: no existing
// test-seam can park inside semb_bank_open. The workspace seam's park hooks
// (support/semb_workspace_seam.h, the OnAcquired/OnRowAcquired points in
// src/superembedder/engine_adapter_interim.cpp) fire at engine workspace
// acquisition inside semb::Encode -- a path semb_bank_open never calls; it
// reads the pair, validates the manifest, and decodes floats without ever
// reaching the encoder. So this cell DECLARES the internal hook the builder
// must provide (tests/support/semb_bank_open_seam.h carries the surface):
//
//   In src/superembedder/bank.cpp, semb_bank_open, guarded by
//   `#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM` (so the hook exists only in
//   the superembedder_testseam mirror, never in the shipped library), the
//   park point is the internal function
//
//       void semb::test_seam::OnBankSnapshotMaterialize();
//
//   invoked exactly once per semb_bank_open call that reaches snapshot
//   materialization -- an open refused earlier (unreadable pair, schema,
//   digest, label) never calls it. The invocation site is the FIRST
//   STATEMENT of the materialization block itself: the block that fills
//   the handle's ids / id_data / id_lengths / rows from the already-
//   validated manifest and payload bytes. Because the site is inside the
//   block, a thread parked there is parked at the moment materialization
//   work begins holding exactly the locks that block runs under: if the
//   block runs inside the process-global registry critical section (the
//   S-3 shape at fe0c0e0), the parked thread HOLDS RegistryMutex for the
//   whole parked window and every cross-handle operation below misses its
//   deadline; if the block runs before the registry lock is taken (the
//   review's remedy: build the complete immutable handle first, hold the
//   mutex only for cookie allocation and registry insertion), the parked
//   thread holds no registry lock and every operation completes. A park
//   point placed BEFORE a lock acquisition that materialization then takes
//   is NOT this contract -- it passes the cell while the defect stands;
//   the confirmation reviewer reads the remedy delta against exactly that.
//
//   The public test surface (extern "C", defined in bank.cpp under the same
//   guard, mirroring support/semb_workspace_seam.h's shape and semantics):
//       int32_t semb_bank_test_seam_arm_snapshot_park(uint32_t count);
//       uint32_t semb_bank_test_seam_snapshot_parked(void);
//       int32_t semb_bank_test_seam_snapshot_wait_parked(uint32_t n,
//                                                       uint32_t timeout_ms);
//       void   semb_bank_test_seam_snapshot_release(void);
//       int32_t semb_bank_test_seam_snapshot_reset(void);
//
// The cell is therefore red at fe0c0e0 as an unresolved link symbol
// reported by name by tests/te237_bank_cross_handle_check.py (the same
// red-first shape tests/te194_query_workspace_check.py established), and
// the builder's repair makes it green only by moving the materialization
// block outside the registry critical section.
//
// The fixture banks are small on purpose: the park point substitutes
// deterministically for the payload-sized work window the review describes
// (parking IS the known point; a large payload would only add runtime, not
// observability). Bank A and bank B carry different row counts and id
// prefixes so a cross-wired or partial snapshot cannot pass the final
// feature oracle, which reads bank B's ranked state after its parked open
// completes and requires exactly the ids bake wrote.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <future>
#include <string>
#include <thread>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bank_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_query_abi_contract.h"
#include "support/semb_bank_open_seam.h"

using namespace std::chrono_literals;

// Internal verbs with no test-side contract header yet: declared here
// rather than including bank_internal_abi.h, which would redefine the
// contract types above (tests/te163_bank_pair_test.cpp's own precedent for
// semb_bank_debug_state). semb_bank_ranked_view is restated exactly as
// include/superembedder/bank_internal_abi.h defines it.
extern "C" semb_status semb_bank_acquire_query(semb_bank bank, const uint8_t fingerprint[32]);
extern "C" semb_status semb_bank_release_query(semb_bank bank);
extern "C" semb_status semb_bank_debug_state(semb_bank bank, uint8_t out_fingerprint[32],
                                             int64_t* out_count, int64_t* out_dims);
struct semb_bank_ranked_view {
  const char* const* ids;
  const size_t* id_lengths;
  const float* rows;
  int64_t count;
  int64_t dims;
};
extern "C" semb_status semb_bank_ranked_state(semb_bank bank, semb_bank_ranked_view* out);

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

// Every cross-handle operation below runs under its own bound: a blocked
// operation is a FAIL row after its deadline, never a hang of ctest. The
// control cell at the top of main proves this machinery can report
// not-ready, so a green deadline row means the operation completed, not
// that the bound is dead.
constexpr auto kOpBound = 10s;
bool BoundedReady(std::future<semb_status>& f) { return f.wait_for(kOpBound) == std::future_status::ready; }

void ReleaseParkBounded() {
  auto f = std::async(std::launch::async, [] { semb_bank_test_seam_snapshot_release(); });
  if (f.wait_for(30s) != std::future_status::ready) FatalTimeout("park release exceeded deadline");
  f.get();
}

void ResetSeamBounded() {
  auto f = std::async(std::launch::async, [] { return semb_bank_test_seam_snapshot_reset(); });
  if (f.wait_for(30s) != std::future_status::ready) FatalTimeout("seam reset exceeded deadline");
  const int32_t reset = f.get();
  Verdict(reset == 1 && semb_bank_test_seam_snapshot_parked() == 0,
          "(setup) snapshot seam reset establishes empty epoch", "");
}

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

std::string Hex(const uint8_t* bytes, size_t n) {
  static constexpr char kHex[] = "0123456789abcdef";
  std::string out;
  out.reserve(n * 2);
  for (size_t i = 0; i < n; ++i) {
    out.push_back(kHex[bytes[i] >> 4]);
    out.push_back(kHex[bytes[i] & 0x0f]);
  }
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.scratch.empty()) {
    Missing("S-3 cross-handle cells", "requires --model --tokenizer --scratch");
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return g_failures > 0 ? 1 : 0;
  }

  // Control (must-reject of this harness's own bound): a future that never
  // becomes ready must be reported not-ready within the bound. Without this
  // cell, every green deadline row below could mean the bound cannot fire.
  {
    std::promise<semb_status> never;
    std::future<semb_status> never_ready = never.get_future();
    const bool bounded_fired = never_ready.wait_for(250ms) != std::future_status::ready;
    Verdict(bounded_fired, "S-3 control: the deadline machinery reports a never-ready operation as not-ready",
            bounded_fired ? "a future from an unset promise did not become ready within its bound" :
                            "the bound reported ready on an unset promise -- every deadline row below is vacuous");
  }

  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = a.model.data();
  c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data();
  c.tokenizer_path_len = a.tokenizer.size();
  c.max_concurrency = 1;
  semb_encoder enc = nullptr;
  const semb_status open_s = semb_encoder_open(&c, &enc);
  if (open_s != SEMB_OK || !enc) {
    Verdict(false, "(setup) semb_encoder_open", Name(open_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  // Two banks with different row counts and id prefixes, so the final
  // feature oracle cannot pass on a partial or cross-wired snapshot.
  DocSet docs_a;
  std::vector<semb_document> docs_a_vec = {
      docs_a.Add("s3a-00", "cross-handle bank A row zero"),
      docs_a.Add("s3a-01", "cross-handle bank A row one"),
      docs_a.Add("s3a-02", "cross-handle bank A row two"),
  };
  DocSet docs_b;
  std::vector<semb_document> docs_b_vec = {
      docs_b.Add("s3b-00", "the materializing bank B row zero"),
      docs_b.Add("s3b-01", "the materializing bank B row one"),
      docs_b.Add("s3b-02", "the materializing bank B row two"),
      docs_b.Add("s3b-03", "the materializing bank B row three"),
  };
  const std::string stem_a = a.scratch + "/te237_bank_a";
  const std::string stem_b = a.scratch + "/te237_bank_b";
  const semb_status bake_a_s = semb_bake_to_path(enc, docs_a_vec.data(), docs_a_vec.size(),
                                                 stem_a.c_str(), stem_a.size());
  if (bake_a_s != SEMB_OK) {
    Verdict(false, "(setup) semb_bake_to_path bank A", Name(bake_a_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }
  const semb_status bake_b_s = semb_bake_to_path(enc, docs_b_vec.data(), docs_b_vec.size(),
                                                 stem_b.c_str(), stem_b.size());
  if (bake_b_s != SEMB_OK) {
    Verdict(false, "(setup) semb_bake_to_path bank B", Name(bake_b_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  ResetSeamBounded();
  semb_bank bank_a = nullptr;
  const semb_status open_a_s = semb_bank_open(stem_a.c_str(), stem_a.size(), &bank_a);
  if (open_a_s != SEMB_OK || !bank_a) {
    Verdict(false, "(setup) semb_bank_open bank A (unparked)", Name(open_a_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }
  uint8_t fingerprint_a[32] = {};
  int64_t count_a = 0, dims_a = 0;
  const semb_status state_a_s = semb_bank_debug_state(bank_a, fingerprint_a, &count_a, &dims_a);
  if (state_a_s != SEMB_OK || count_a != 3) {
    Verdict(false, "(setup) semb_bank_debug_state bank A", Name(state_a_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }
  semb_query query_a = nullptr;
  const semb_status query_a_s = semb_query_open(enc, bank_a, &query_a);
  if (query_a_s != SEMB_OK || !query_a) {
    Verdict(false, "(setup) semb_query_open on bank A", Name(query_a_s));
    semb_bank_close(bank_a);
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  // =========================================================================
  // S-3: the materializing semb_bank_open parks at its snapshot-
  // materialization point; while it is parked, every registry operation on
  // the distinct live bank A completes within its bound. A missed bound is
  // the review's defect: payload-sized snapshot construction inside the
  // process-global registry critical section, head-of-line blocking every
  // other bank's close and query acquire/release.
  // =========================================================================
  {
    ResetSeamBounded();
    Verdict(semb_bank_test_seam_arm_snapshot_park(1) == 1,
            "S-3 (setup) arm one snapshot-materialization park", "");

    semb_bank bank_b = nullptr;
    semb_status status_b = static_cast<semb_status>(-1000);
    auto job_b = std::async(std::launch::async, [&] {
      status_b = semb_bank_open(stem_b.c_str(), stem_b.size(), &bank_b);
    });

    const bool parked = semb_bank_test_seam_snapshot_wait_parked(1, 10000) == 1 &&
                        semb_bank_test_seam_snapshot_parked() == 1;
    Verdict(parked, "S-3 (setup) the materializing semb_bank_open parks at its snapshot-materialization point",
            parked ? "" : "no thread reached the park point within 10s -- the hook is not wired into semb_bank_open's materialization");

    if (parked) {
      // Cross-handle legs, each bounded by kOpBound. Every one must both
      // complete and return its expected status; a miss is head-of-line
      // blocking, reported in the evaluated-FAIL detail below.
      uint8_t fp_after[32] = {};
      int64_t count_after = 0, dims_after = 0;
      semb_status debug_s = static_cast<semb_status>(-1000);
      auto debug_job = std::async(std::launch::async, [&] {
        return semb_bank_debug_state(bank_a, fp_after, &count_after, &dims_after);
      });
      const bool debug_ready = BoundedReady(debug_job);
      debug_s = debug_ready ? debug_job.get() : static_cast<semb_status>(-1000);
      Verdict(debug_ready && debug_s == SEMB_OK &&
              std::memcmp(fp_after, fingerprint_a, 32) == 0 && count_after == count_a && dims_after == dims_a,
              "S-3 semb_bank_debug_state on bank A completes while bank B's open is parked",
              debug_ready ? Name(debug_s) : "deadline exceeded: the state accessor waited behind bank B's materializing open");

      semb_bank_ranked_view view_a{};
      semb_status ranked_s = static_cast<semb_status>(-1000);
      auto ranked_job = std::async(std::launch::async, [&] {
        return semb_bank_ranked_state(bank_a, &view_a);
      });
      const bool ranked_ready = BoundedReady(ranked_job);
      ranked_s = ranked_ready ? ranked_job.get() : static_cast<semb_status>(-1000);
      Verdict(ranked_ready && ranked_s == SEMB_OK && view_a.count == count_a,
              "S-3 semb_bank_ranked_state on bank A completes while bank B's open is parked",
              ranked_ready ? Name(ranked_s) : "deadline exceeded: the ranked-state read waited behind bank B's materializing open");

      semb_status qclose_s = static_cast<semb_status>(-1000);
      auto qclose_job = std::async(std::launch::async, [&] { return semb_query_close(query_a); });
      const bool qclose_ready = BoundedReady(qclose_job);
      qclose_s = qclose_ready ? qclose_job.get() : static_cast<semb_status>(-1000);
      Verdict(qclose_ready && qclose_s == SEMB_OK,
              "S-3 semb_query_close on bank A's live query completes while bank B's open is parked",
              qclose_ready ? Name(qclose_s) :
              "deadline exceeded: the live query's close waited behind bank B's materializing open (the review's shutdown victim)");

      semb_status acquire_s = static_cast<semb_status>(-1000);
      auto acquire_job = std::async(std::launch::async, [&] {
        return semb_bank_acquire_query(bank_a, fingerprint_a);
      });
      const bool acquire_ready = BoundedReady(acquire_job);
      acquire_s = acquire_ready ? acquire_job.get() : static_cast<semb_status>(-1000);
      Verdict(acquire_ready && acquire_s == SEMB_OK,
              "S-3 semb_bank_acquire_query on bank A completes while bank B's open is parked",
              acquire_ready ? Name(acquire_s) : "deadline exceeded: a new query's acquisition waited behind bank B's materializing open");

      semb_status release_s = static_cast<semb_status>(-1000);
      auto release_job = std::async(std::launch::async, [&] {
        return semb_bank_release_query(bank_a);
      });
      const bool release_ready = BoundedReady(release_job);
      release_s = release_ready ? release_job.get() : static_cast<semb_status>(-1000);
      Verdict(release_ready && release_s == SEMB_OK,
              "S-3 semb_bank_release_query on bank A completes while bank B's open is parked",
              release_ready ? Name(release_s) : "deadline exceeded: the query release waited behind bank B's materializing open");

      semb_status close_s = static_cast<semb_status>(-1000);
      auto close_job = std::async(std::launch::async, [&] { return semb_bank_close(bank_a); });
      const bool close_ready = BoundedReady(close_job);
      close_s = close_ready ? close_job.get() : static_cast<semb_status>(-1000);
      Verdict(close_ready && close_s == SEMB_OK,
              "S-3 semb_bank_close on bank A completes while bank B's open is parked",
              close_ready ? Name(close_s) : "deadline exceeded: bank A's close waited behind bank B's materializing open");

      // Release the park and let the materializing open finish. Cleanup is
      // bounded on every path: a hung cell fails, it never hangs ctest.
      ReleaseParkBounded();
      if (job_b.wait_for(30s) != std::future_status::ready) FatalTimeout("S-3 parked open exceeded deadline after release");
      job_b.get();
      Verdict(status_b == SEMB_OK && bank_b != nullptr,
              "S-3 the parked semb_bank_open itself completes once released",
              Name(status_b));

      if (bank_b) {
        // Feature oracle: the parked open materialized the COMPLETE correct
        // snapshot -- exactly the ids bake wrote for bank B, all four rows.
        // Grounded in the bake inputs, not in a re-read of what open did.
        semb_bank_ranked_view view_b{};
        const semb_status state_b_s = semb_bank_ranked_state(bank_b, &view_b);
        bool ids_ok = state_b_s == SEMB_OK && view_b.count == 4 && view_b.ids != nullptr;
        const char* expected_b[4] = {"s3b-00", "s3b-01", "s3b-02", "s3b-03"};
        for (int64_t row = 0; ids_ok && row < view_b.count; ++row) {
          const std::string got(view_b.ids[row], view_b.id_lengths[row]);
          if (got != expected_b[row]) ids_ok = false;
        }
        Verdict(ids_ok, "S-3 the parked open materialized bank B's complete snapshot (ranked ids equal the bake)",
                state_b_s == SEMB_OK ? std::string("count=") + std::to_string(view_b.count) : Name(state_b_s));
        semb_bank_close(bank_b);
      }
    } else {
      // The park never happened; release, drain the open, and fail.
      ReleaseParkBounded();
      if (job_b.wait_for(30s) != std::future_status::ready) FatalTimeout("S-3 unparked-path open cleanup deadline");
      job_b.get();
      if (bank_b) semb_bank_close(bank_b);
      semb_query_close(query_a);
      semb_bank_close(bank_a);
    }
    ResetSeamBounded();
  }

  semb_encoder_close(enc);
  std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
  return g_failures > 0 ? 1 : 0;
}