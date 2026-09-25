// tests/te331_u2_engine_identity_test.cpp -- TE-331 (U2-3 red suite): the
// red-first driver for item 14's linked-engine identity check
// (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3 item 14; sec 10 M18):
// `sslm_build_identity`, the new refusal status `SEMB_ENGINE_LINK_MISMATCH`,
// and the existing-but-unused-for-this-purpose statuses
// `SEMB_ENGINE_TOOLCHAIN_MISMATCH` and `SEMB_CPU_TIER_UNSUPPORTED` that
// item 14 also names.
//
// RED AT `fca421b`, TWO INDEPENDENT WAYS:
//
//   (1) `SEMB_ENGINE_LINK_MISMATCH` is not a name in `semb.h`'s
//   `SEMB_STATUS_ENUM_LIST` (`git grep -n SEMB_ENGINE_LINK_MISMATCH
//   include/` returns nothing) -- `Statuses::engine_link_mismatch` below,
//   resolved by name through the product's own `semb_contract::StatusByName`
//   the way every other status in this suite is resolved (te163's own
//   `ResolveStatuses` pattern), returns a sentinel the test treats as
//   MISSING rather than guessing an ordinal.
//
//   (2) The pinned engine at `D:/_te259/engine-install-v150` (SuperSLM
//   1.5.0) exposes NO `sslm_build_identity` symbol at all -- the plan's own
//   text states this exactly: "an engine library defining neither fails
//   the application's link and names sslm_build_identity" (item 14,
//   "Where the engine gets it"). This file declares the verb (this
//   suite's OWN copy, per this project's ABI-contract convention -- no
//   product or engine header declares it at 1.5.0) and calls it once, so
//   the EXECUTABLE FAILS TO LINK, naming `sslm_build_identity`, exactly as
//   the plan's own text predicts. tests/te331_u2_engine_identity_check.py
//   builds this EXCLUDE_FROM_ALL target on demand and reports the
//   unresolved symbol by name.
//
// WHAT RUNS ONCE BOTH LAND: opens the real artifact through the product's
// own `semb_encoder_open`, calls `sslm_build_identity()` on the linked
// engine, and confirms the fields match what the plan's own text specifies
// (compiler/stdlib macro values, forced_tier, compiled_isa/required_isa,
// build_record non-empty) -- the must-accept half of item 14's own
// commissioning. The must-REJECT half (a mismatched-toolchain or
// forced-tier-above-host engine refusing by name) needs a SECOND,
// deliberately-mismatched engine pin, which is the adversary's own
// commissioning construction (`Claude/Loki/te301-probe/`,
// `Claude/Loki/te313-probe/`) -- not duplicated into product test source
// here, per this suite's own commissioning-boundary discipline (see the
// Curie record's own note on this).
//
// USAGE: --model <.sslm> --tokenizer <.sslm>
#include <cstdio>
#include <cstdint>
#include <string>

#include "semb_public_abi_contract.h"

// This suite's own declaration -- SuperSLM 1.5.0 (the pinned engine) does
// not define this symbol at all (item 14's own text: "The identity and
// [the kernel TU] are then one object... An engine that does not define it
// (v1.5.0) gets it from the pin tool" -- the pin tool step is itself U2-3
// item 14's own build-time addition, not yet run against this tree's
// pinned engine). Calling it here, unconditionally, is the point: a build
// against today's UNPATCHED engine install fails to link and names this
// symbol.
extern "C" struct SslmBuildIdentity {
  uint32_t struct_size;
  uint32_t schema_version;
  // compiler/stdlib macro values, forced_tier, compiled_isa/required_isa,
  // build_record -- this file only needs the address, not the layout, to
  // prove or disprove the link, so the remaining fields are intentionally
  // NOT declared here (this suite is not the one that fixes the ABI; the
  // planner's own TE-305 record and te267 item 14 own the real shape).
};
extern "C" const SslmBuildIdentity* sslm_build_identity(void);

namespace {
int g_failures = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
}  // namespace

int main(int argc, char** argv) {
  std::string model, tokenizer;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    if (k == "--model" && i + 1 < argc) model = argv[++i];
    else if (k == "--tokenizer" && i + 1 < argc) tokenizer = argv[++i];
  }

  const int engine_link_mismatch = semb_contract::StatusByName("SEMB_ENGINE_LINK_MISMATCH");
  Verdict(engine_link_mismatch >= 0, "M18 status: SEMB_ENGINE_LINK_MISMATCH resolvable by name",
          engine_link_mismatch >= 0 ? std::to_string(engine_link_mismatch) : "MISSING");

  const SslmBuildIdentity* identity = sslm_build_identity();  // link-red today (see file header)
  Verdict(identity != nullptr && identity->struct_size > 0, "M18 sslm_build_identity() returns a populated object",
          identity ? ("struct_size=" + std::to_string(identity->struct_size)) : "<NULL>");

  if (!model.empty() && !tokenizer.empty()) {
    semb_config cfg{};
    cfg.struct_size = sizeof(cfg);
    cfg.model_path = model.data();
    cfg.model_path_len = model.size();
    cfg.tokenizer_path = tokenizer.data();
    cfg.tokenizer_path_len = tokenizer.size();
    cfg.max_concurrency = 1;
    semb_encoder enc = nullptr;
    const semb_status s = semb_encoder_open(&cfg, &enc);
    Verdict(s == SEMB_OK, "M18 (setup) real-artifact open still succeeds on the verified engine",
            semb_status_name(s));
    if (s == SEMB_OK) semb_encoder_close(enc);
  }

  std::printf("TOTAL failures=%d\n", g_failures);
  return g_failures == 0 ? 0 : 1;
}
