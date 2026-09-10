#include <chrono>
#include <cstdio>
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
const char* Name(semb_status status) {
  const char* name = semb_status_name(status);
  return name ? name : "<NULL>";
}

struct Args { std::string model, tokenizer, scratch; };
Args ParseArgs(int argc, char** argv) {
  Args args;
  for (int i = 1; i < argc; ++i) {
    const std::string key = argv[i];
    auto next = [&](std::string* out) { if (i + 1 < argc) *out = argv[++i]; };
    if (key == "--model") next(&args.model);
    else if (key == "--tokenizer") next(&args.tokenizer);
    else if (key == "--scratch") next(&args.scratch);
  }
  return args;
}

struct Fixture {
  semb_encoder encoder = nullptr;
  semb_bank bank = nullptr;
  semb_query query = nullptr;
  uint32_t dims = 0;
};

bool OpenFixture(const Args& args, const std::string& suffix, Fixture* fixture) {
  semb_config config{};
  config.struct_size = sizeof(config);
  config.model_path = args.model.data();
  config.model_path_len = args.model.size();
  config.tokenizer_path = args.tokenizer.data();
  config.tokenizer_path_len = args.tokenizer.size();
  config.max_concurrency = 1;
  const semb_status open = semb_encoder_open(&config, &fixture->encoder);
  if (open != SEMB_OK) { Verdict(false, suffix + " setup encoder", Name(open)); return false; }
  const char id[] = "te222-ownership";
  const char text[] = "short fixture document for query encoder ownership";
  semb_document doc{};
  doc.struct_size = sizeof(doc);
  doc.id = id; doc.id_len = sizeof(id) - 1;
  doc.utf8 = text; doc.utf8_len = sizeof(text) - 1;
  const std::string stem = args.scratch + "/" + suffix;
  const semb_status baked = semb_bake_to_path(fixture->encoder, &doc, 1, stem.c_str(), stem.size());
  if (baked != SEMB_OK) { Verdict(false, suffix + " setup bake", Name(baked)); return false; }
  const semb_status bank_open = semb_bank_open(stem.c_str(), stem.size(), &fixture->bank);
  if (bank_open != SEMB_OK) { Verdict(false, suffix + " setup bank", Name(bank_open)); return false; }
  const semb_status query_open = semb_query_open(fixture->encoder, fixture->bank, &fixture->query);
  if (query_open != SEMB_OK) { Verdict(false, suffix + " setup query", Name(query_open)); return false; }
  const semb_status dims = semb_encoder_dims(fixture->encoder, &fixture->dims);
  if (dims != SEMB_OK) { Verdict(false, suffix + " setup dims", Name(dims)); return false; }
  return true;
}

semb_status Encode(Fixture* fixture, std::vector<float>* vector) {
  vector->assign(fixture->dims, 0.0f);
  size_t required = 0;
  static constexpr char kText[] = "query ownership must retain the encoder";
  return semb_query_encode(fixture->query, kText, sizeof(kText) - 1, vector->data(),
                           vector->size() * sizeof(float), &required);
}

void CloseQueryAndBank(Fixture* fixture) {
  if (fixture->query) { (void)semb_query_close(fixture->query); fixture->query = nullptr; }
  if (fixture->bank) { (void)semb_bank_close(fixture->bank); fixture->bank = nullptr; }
}

}  // namespace

int main(int argc, char** argv) {
  const Args args = ParseArgs(argc, argv);
  if (args.model.empty() || args.tokenizer.empty() || args.scratch.empty()) return 2;

  // S-1 sequential: a live query owns an encoder lease. At 279951d the
  // close succeeds and poisons the query, so the following encode is the
  // feature oracle rather than a lifecycle bookkeeping check alone.
  {
    Fixture fixture;
    if (OpenFixture(args, "sequential", &fixture)) {
      const semb_status close_live = semb_encoder_close(fixture.encoder);
      Verdict(close_live == SEMB_HANDLE_IN_USE,
              "S-1 sequential encoder close while query is live -> SEMB_HANDLE_IN_USE", Name(close_live));
      std::vector<float> vector;
      const semb_status encode = Encode(&fixture, &vector);
      Verdict(encode == SEMB_OK, "S-1 sequential live query remains encodable after refused encoder close", Name(encode));
      CloseQueryAndBank(&fixture);
      const semb_status close_after_query = semb_encoder_close(fixture.encoder);
      Verdict(close_after_query == SEMB_OK,
              "S-1 sequential encoder close succeeds after query close", Name(close_after_query));
    }
  }

  // S-1 in-flight: park the real query encode at its workspace acquisition;
  // a second thread closes the encoder while that call is genuinely live.
  {
    Fixture fixture;
    if (OpenFixture(args, "inflight", &fixture)) {
      (void)semb_test_seam_reset();
      Verdict(semb_test_seam_arm_park(1) == 1, "S-1 in-flight setup arm park", "");
      std::vector<float> vector;
      auto encode_job = std::async(std::launch::async, [&] { return Encode(&fixture, &vector); });
      const bool parked = semb_test_seam_wait_parked(1, 10000) == 1;
      Verdict(parked, "S-1 in-flight setup query encode is parked", "");
      if (parked) {
        auto close_job = std::async(std::launch::async, [&] { return semb_encoder_close(fixture.encoder); });
        const bool close_ready = close_job.wait_for(10s) == std::future_status::ready;
        Verdict(close_ready, "S-1 in-flight encoder-close deadline", "");
        if (close_ready) {
          const semb_status close_live = close_job.get();
          Verdict(close_live == SEMB_HANDLE_IN_USE,
                  "S-1 in-flight encoder close while query encodes -> SEMB_HANDLE_IN_USE", Name(close_live));
        }
      }
      semb_test_seam_release();
      const bool encode_ready = encode_job.wait_for(30s) == std::future_status::ready;
      Verdict(encode_ready, "S-1 in-flight parked query completion deadline", "");
      if (encode_ready) Verdict(encode_job.get() == SEMB_OK,
                                "S-1 in-flight query encode completes after encoder-close refusal", "SEMB_OK required");
      CloseQueryAndBank(&fixture);
      const semb_status close_after_query = semb_encoder_close(fixture.encoder);
      Verdict(close_after_query == SEMB_OK,
              "S-1 in-flight encoder close succeeds after query close", Name(close_after_query));
      (void)semb_test_seam_reset();
    }
  }

  std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
  return g_failures == 0 ? 0 : 1;
}
