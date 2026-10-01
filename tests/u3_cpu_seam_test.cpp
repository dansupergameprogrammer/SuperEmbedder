// tests/u3_cpu_seam_test.cpp -- U3 red suite, sec 4.6 row 11's witness-triple
// mutant on the CPU path (te266 P:4221, "the witness triples computed on a CPU
// open too (TE-388 T388-11): a seam counter on semb_interim_ps_n_select reads 0
// across a CPU open"; P:4107, "A CPU open computes no triples"). The test
// author's.
//
// Links `superembedder_testseam` (tests/support/semb_u3_gpu_seam.h), every
// build: the counter lives in engine_adapter_interim.cpp.
//
// Cells:
//   R11-w     the counter's delta across a public CPU open of the U1 pair is 0.
//   R11-w'    must-accept (the counter is live, so R11-w cannot pass on a dead
//             counter): one direct semb_interim_ps_n_select call on that
//             handle's interim encoder raises it by exactly 1.
// RED TODAY: link-red on semb_test_seam_ps_n_select_count (a builder item,
// te266 P:4267).
//
// USAGE: u3_cpu_seam_test --model <pair model> --tokenizer <pair tokenizer> [--log <file>]
#include <cstdint>
#include <string>
#include <vector>

#include "superembedder/encoder_interim_abi.h"
#include "support/semb_u2_memory_seam.h"
#include "support/semb_u3_gpu_seam.h"
#include "support/u3_common.h"

int main(int argc, char** argv) {
  std::string model, tokenizer, log;
  for (int i = 1; i + 1 < argc; i += 2) {
    const std::string a = argv[i];
    if (a == "--model") model = argv[i + 1];
    else if (a == "--tokenizer") tokenizer = argv[i + 1];
    else if (a == "--log") log = argv[i + 1];
  }
  if (!log.empty()) u3::LogFile() = std::fopen(log.c_str(), "ab");
  if (!u3::FileExists(model) || !u3::FileExists(tokenizer)) {
    u3::Missing("u3_cpu_seam", "the U1 pair (--model, --tokenizer) is absent");
    return u3::ExitCode();
  }
  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = model.data();
  c.model_path_len = model.size();
  c.tokenizer_path = tokenizer.data();
  c.tokenizer_path_len = tokenizer.size();
  c.max_concurrency = 1;
  const uint64_t before = semb_test_seam_ps_n_select_count();
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&c, &enc);
  const uint64_t after = semb_test_seam_ps_n_select_count();
  if (s != SEMB_OK) {
    u3::Verdict(false, "R11-w setup: the CPU open succeeds", u3::Name(s));
    return u3::ExitCode();
  }
  u3::Verdict(after == before, "R11-w a CPU open computes no witness triples (semb_interim_ps_n_select count delta 0)",
              "delta " + u3::S(after - before));

  SembInterimEncoder* ie = semb_test_seam_interim_of(enc);
  SembInterimGeometry g{};
  g.struct_size = sizeof(g);
  semb_interim_encoder_geometry(ie, &g);
  const int32_t ids[3] = {97, 98, 99};
  std::vector<int8_t> codes(4 * g.hidden_size), sel(g.hidden_size);
  std::vector<int64_t> m(4), e(4);
  size_t n = 0;
  const char* name = nullptr;
  semb_interim_encode_seam(ie, ids, 3, 0, kSembForwardLegChunkBatched, codes.data(), codes.size(), m.data(),
                           e.data(), m.size(), &n, &name);
  const uint64_t c0 = semb_test_seam_ps_n_select_count();
  int64_t sm = 0, se = 0;
  const SembInterimStatus ps = semb_interim_ps_n_select(ie, codes.data(), m.data(), e.data(), n, n - 1, sel.data(),
                                                        &sm, &se, &name);
  const uint64_t c1 = semb_test_seam_ps_n_select_count();
  u3::Verdict(ps == kSembInterimOk && c1 - c0 == 1,
              "R11-w' must-accept: one semb_interim_ps_n_select call raises the counter by exactly 1",
              "select status " + std::to_string(static_cast<int>(ps)) + ", delta " + u3::S(c1 - c0));
  semb_encoder_close(enc);
  std::printf("SUMMARY u3_cpu_seam pass=%d fail=%d red=%d missing=%d\n", u3::T().pass, u3::T().fail, u3::T().red,
              u3::T().missing);
  return u3::ExitCode();
}
