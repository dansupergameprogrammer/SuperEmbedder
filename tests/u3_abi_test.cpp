// tests/u3_abi_test.cpp -- U3 red suite: the device ABI and the three statuses
// (te266 sec 4.1, P:4022-4027; sec 4.6 row 2, P:4212; the U2 plan's sec 6.2 J9,
// te267 P:3754). The test author's, independently of the builder.
//
// Links the SHIPPED static target (`superembedder`, no seam), in every build.
// Runs on the U1 synthetic pair (tests/fixtures/regenerate_tokenizer_pair_fixture.py).
//
// Cells (one line each; P:<line> is te266-gpu-path.md at origin/develop):
//   J9-a    SEMB_DEVICE_UNSUPPORTED, SEMB_DEVICE_UNAVAILABLE and
//           SEMB_DEVICE_DIVERGED each name a semb_status (P:4023-4026).
//   J9-b    they take the next free ordinals after U2's, in sec 4.1's order:
//           SEMB_CPU_TIER_UNSUPPORTED + 1, + 2, + 3 (= 40, 41, 42; te267
//           P:3754: "the next free ordinals in landing order"; U2 landed 36-39
//           first), and no existing name moved.
//   ABI-a   `device` = SEMB_DEVICE_CPU (0) opens SEMB_OK and encodes a row
//           byte-equal to semb_encoder_open_memory's (a path with no device
//           field, so CPU) for the same artifacts and text (P:4022).
//   ABI-b   an unknown `device` (2, 0xFFFFFFFF) refuses SEMB_DEVICE_UNSUPPORTED
//           and writes NULL to *out (P:4024; row 2, P:4212).
//   ABI-c   SEMB_BUILD_GPU=OFF only: `device` = SEMB_DEVICE_GPU refuses
//           SEMB_DEVICE_UNSUPPORTED (P:4024, "or SEMB_DEVICE_GPU in a build
//           without SEMB_BUILD_GPU"; row 7's "no fallback", P:4217).
//   ABI-d   the layout is pinned and struct_size stays exactly validated
//           (P:4022 as restated by the planner's U3 ruling 1: `device` lands in
//           the former tail padding, so sizeof stays 48 and there is no
//           reserved word or 64-bit member).
//           (i)  compile time: offsetof(semb_config, device) ==
//                offsetof(semb_config, max_concurrency) + 4, and on 64-bit
//                sizeof(semb_config) == 48. The size pin holds in every build;
//                the offset pin is instantiated once the member exists, and
//                until then the cell reports RED.
//           (ii) struct_size 44 (= offsetof(device)), 52, 56 and 0 each refuse
//                SEMB_STRUCT_SIZE_MISMATCH and write NULL to *out. The
//                must-accept, sizeof(semb_config), is ABI-a's open.
//
// RED TODAY, each for its own reason: J9-a/b (the names resolve to nothing);
// ABI-a (semb_config has no `device` member: the open succeeds only because
// the product ignores the bytes, so the cell reports RED, never PASS, until
// the member exists); ABI-b/c (no SEMB_DEVICE_UNSUPPORTED; the open succeeds);
// ABI-d (i) (no member to pin). ABI-d (ii) is U2's exact validation, which
// holds today and must keep holding.
//
// USAGE: u3_abi_test --model <pair model> --tokenizer <pair tokenizer> [--log <file>]
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "support/u3_common.h"

namespace {

// ABI-d (i): the layout pin (ruling 1). The size pin needs no member and holds
// in every build; the offset pin is instantiated only once semb_config::device
// exists, so today's header compiles and the cell reports RED instead.
#if UINTPTR_MAX > 0xFFFFFFFFu
static_assert(sizeof(semb_config) == 48,
              "U3 ABI-d (i): sizeof(semb_config) stays 48 on 64-bit (P:4022 as restated; no padding member)");
#endif
template <class C, bool = u3::HasDevice<C>::value>
struct DevicePin {
  static constexpr bool present = false;
};
template <class C>
struct DevicePin<C, true> {
  static constexpr bool present = true;
  static_assert(offsetof(C, device) == offsetof(C, max_concurrency) + 4,
                "U3 ABI-d (i): `device` is the member right after max_concurrency, in the former tail padding");
  static_assert(sizeof(uint32_t) == sizeof(C::device), "U3 ABI-d (i): `device` is a uint32_t");
};

}  // namespace

int main(int argc, char** argv) {
  std::string model, tokenizer, log;
  for (int i = 1; i + 1 < argc; i += 2) {
    const std::string a = argv[i];
    if (a == "--model") model = argv[i + 1];
    else if (a == "--tokenizer") tokenizer = argv[i + 1];
    else if (a == "--log") log = argv[i + 1];
  }
  if (!log.empty()) u3::LogFile() = std::fopen(log.c_str(), "ab");
  if (model.empty() || tokenizer.empty() || !u3::FileExists(model) || !u3::FileExists(tokenizer)) {
    u3::Missing("u3_abi", "the U1 synthetic pair (--model, --tokenizer) is absent");
    return u3::ExitCode();
  }

  // ---- J9 -------------------------------------------------------------------
  const char* const kNames[3] = {"SEMB_DEVICE_UNSUPPORTED", "SEMB_DEVICE_UNAVAILABLE", "SEMB_DEVICE_DIVERGED"};
  int32_t v[3] = {-1, -1, -1};
  bool all = true;
  for (int i = 0; i < 3; ++i) all = u3::Resolve("J9-a " + std::string(kNames[i]), kNames[i], &v[i]) && all;
  if (all) u3::Verdict(true, "J9-a the three device statuses are named", "40-42 resolve by name");
  const int32_t tier = u3::StatusByName("SEMB_CPU_TIER_UNSUPPORTED");
  if (!all) {
    u3::Red("J9-b the device statuses take ordinals 40, 41, 42 in sec 4.1's order",
            "not all three names resolve (see J9-a)");
  } else {
    const bool ok = tier == 39 && v[0] == tier + 1 && v[1] == tier + 2 && v[2] == tier + 3;
    u3::Verdict(ok, "J9-b the device statuses take ordinals 40, 41, 42 in sec 4.1's order",
                "SEMB_CPU_TIER_UNSUPPORTED=" + std::to_string(tier) + " UNSUPPORTED=" + std::to_string(v[0]) +
                    " UNAVAILABLE=" + std::to_string(v[1]) + " DIVERGED=" + std::to_string(v[2]));
  }
  {
    // No existing name moved (append only): 0 and 35-39 keep their ordinals.
    const bool kept = u3::StatusByName("SEMB_OK") == 0 && u3::StatusByName("SEMB_CORPUS_DIGEST_MISMATCH") == 35 &&
                      u3::StatusByName("SEMB_ENGINE_BUILD_UNRECORDED") == 36 && tier == 39;
    u3::Verdict(kept, "J9-b' the append moves no existing ordinal (pin)",
                "SEMB_OK=0, SEMB_CORPUS_DIGEST_MISMATCH=35, SEMB_ENGINE_BUILD_UNRECORDED=36, "
                "SEMB_CPU_TIER_UNSUPPORTED=39");
  }

  // ---- ABI-a: device = CPU equals the device-less memory open -------------
  const std::string text = "an ordinary short document";
  std::vector<float> cpu_row, mem_row;
  {
    semb_encoder e = nullptr;
    const u3::Config c = u3::MakeConfig(model, tokenizer, 1, u3::kDeviceCpu);
    const semb_status s = u3::Open(c, &e);
    if (!u3::kProductHasDevice) {
      if (s == SEMB_OK) semb_encoder_close(e);
      u3::Red("ABI-a device = SEMB_DEVICE_CPU opens and encodes",
              std::string("semb_config has no `device` member (P:4022); the open returned ") + u3::Name(s) +
                  " because the product never reads the member's bytes (sizeof(semb_config) = " +
                  u3::S(sizeof(semb_config)) + ", sizeof with device = " + u3::S(sizeof(u3::Config)) + ")");
    } else if (s != SEMB_OK) {
      u3::Red("ABI-a device = SEMB_DEVICE_CPU opens and encodes",
              std::string("open returned ") + u3::Name(s) + " with sizeof(semb_config)+device = " +
                  u3::S(sizeof(u3::Config)) + " (today's semb_config is " + u3::S(sizeof(semb_config)) +
                  "): semb_config has no `device` member (P:4022)");
    } else {
      const semb_status es = u3::EncodeRow(e, text, &cpu_row);
      semb_encoder_close(e);
      const std::vector<uint8_t> mb = u3::ReadAll(model), tb = u3::ReadAll(tokenizer);
      semb_memory_config mc{};
      mc.struct_size = sizeof(mc);
      mc.model_bytes = mb.data();
      mc.model_len = mb.size();
      mc.tokenizer_bytes = tb.data();
      mc.tokenizer_len = tb.size();
      mc.max_concurrency = 1;
      semb_encoder m = nullptr;
      const semb_status ms = semb_encoder_open_memory(&mc, &m);
      if (ms == SEMB_OK) {
        u3::EncodeRow(m, text, &mem_row);
        semb_encoder_close(m);
      }
      u3::Verdict(es == SEMB_OK && u3::SameBytes(cpu_row, mem_row), "ABI-a device = SEMB_DEVICE_CPU opens and encodes",
                  std::string("encode ") + u3::Name(es) + ", memory open " + u3::Name(ms) + ", rows " +
                      (u3::SameBytes(cpu_row, mem_row) ? "byte-equal" : "DIFFER or empty"));
    }
  }

  // ---- ABI-b: unknown device values ----------------------------------------
  int32_t unsupported = -1;
  const bool have_unsupported = u3::StatusByName("SEMB_DEVICE_UNSUPPORTED") >= 0;
  if (have_unsupported) unsupported = u3::StatusByName("SEMB_DEVICE_UNSUPPORTED");
  for (const uint32_t bad : {2u, 0xFFFFFFFFu}) {
    const std::string cell = "ABI-b device = " + std::to_string(bad) + " refuses SEMB_DEVICE_UNSUPPORTED";
    semb_encoder e = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    const u3::Config c = u3::MakeConfig(model, tokenizer, 1, bad);
    const semb_status s = u3::Open(c, &e);
    if (!have_unsupported) {
      u3::Red(cell, std::string("SEMB_DEVICE_UNSUPPORTED names no status; open returned ") + u3::Name(s));
    } else {
      u3::Verdict(s == unsupported && e == nullptr, cell,
                  std::string("status ") + u3::Name(s) + ", *out " + (e ? "NOT NULL" : "NULL"));
    }
    if (s == SEMB_OK && e) semb_encoder_close(e);
  }

  // ---- ABI-c: GPU requested in a CPU-only build ----------------------------
#if !defined(U3_TEST_BUILD_GPU) || !U3_TEST_BUILD_GPU
  {
    const std::string cell = "ABI-c device = SEMB_DEVICE_GPU in a SEMB_BUILD_GPU=OFF build refuses SEMB_DEVICE_UNSUPPORTED";
    semb_encoder e = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    const u3::Config c = u3::MakeConfig(model, tokenizer, 1, u3::kDeviceGpu);
    const semb_status s = u3::Open(c, &e);
    if (!have_unsupported) {
      u3::Red(cell, std::string("SEMB_DEVICE_UNSUPPORTED names no status; open returned ") + u3::Name(s));
    } else {
      u3::Verdict(s == unsupported && e == nullptr, cell,
                  std::string("status ") + u3::Name(s) + " (no fallback to the CPU, P:4051)");
    }
    if (s == SEMB_OK && e) semb_encoder_close(e);
  }
#else
  u3::Note("ABI-c", "SEMB_BUILD_GPU=ON: a GPU request is graded by the GPU cells (u3_gpu_cells_test)");
#endif

  // ---- ABI-d: layout pin and exact struct_size validation (ruling 1) -------
  {
    const std::string cell = "ABI-d (i) layout pin: offsetof(device) == offsetof(max_concurrency) + 4, "
                             "sizeof(semb_config) == 48 on 64-bit";
    const std::string layout = "sizeof(semb_config) = " + u3::S(sizeof(semb_config)) +
                               ", offsetof(max_concurrency) = " + u3::S(offsetof(semb_config, max_concurrency));
    if (!DevicePin<semb_config>::present) {
      u3::Red(cell, "semb_config has no `device` member to pin (P:4022); " + layout);
    } else {
      u3::Verdict(true, cell, "held at compile time; " + layout);
    }
  }
  {
    // A zeroed buffer larger than any size tried, so a product that read past
    // sizeof(semb_config) before refusing reads zeros, never another object.
    alignas(u3::Config) unsigned char buf[64] = {};
    const u3::Config good = u3::MakeConfig(model, tokenizer, 1, u3::kDeviceCpu);
    std::memcpy(buf, &good, sizeof(good));
    const uint32_t sizes[4] = {static_cast<uint32_t>(offsetof(u3::Config, device)), 52u, 56u, 0u};
    for (const uint32_t sz : sizes) {
      std::memcpy(buf, &sz, sizeof(sz));  // struct_size is the first member
      semb_encoder e = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
      const semb_status s = semb_encoder_open(reinterpret_cast<const semb_config*>(buf), &e);
      u3::Verdict(s == SEMB_STRUCT_SIZE_MISMATCH && e == nullptr,
                  "ABI-d (ii) struct_size " + u3::S(sz) + " refuses SEMB_STRUCT_SIZE_MISMATCH, *out NULL (P:4022)",
                  std::string("status ") + u3::Name(s) + ", *out " + (e ? "NOT NULL" : "NULL"));
      if (s == SEMB_OK && e && e != reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1))) semb_encoder_close(e);
    }
  }

  std::printf("SUMMARY u3_abi pass=%d fail=%d red=%d missing=%d\n", u3::T().pass, u3::T().fail, u3::T().red,
              u3::T().missing);
  return u3::ExitCode();
}
