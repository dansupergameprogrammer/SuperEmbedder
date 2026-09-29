// tests/u2_9_c62_must_reject_test.cpp -- U2 cloud build, U2-9's C62: the
// adversary's must-reject constructions for (b) and (c) (te267 sec 5 U2-9,
// C62, P:2803-2805), plus the steady-reading must-reject a build-time item
// adds (D-SLM7811; not a plan revision). Authored by the adversary seat,
// blind to the test author's own controls (P:2794). Each is ONE C62 process
// -- `semb_c62::RunProcess`, C62's own open, readings, steps and grading
// (u2_9_c62_process.h, u2_9_c62_reader.h), unchanged -- linked with
// `superembedder_testseam` in place of the shipped library, on the real
// artifact. The constructions act only through RunProcess's hooks.
//
//   --construction forced  (P:2803-2805) item 9's forced-reference arm is set
//       for the leg's encode (before_encode; cleared in after_encode), so the
//       long encode grows its slot to C = context_cap: P * 32,768 = 1,792 MiB
//       on the published model, zero-filled by the arm, so every page is
//       touched. EXPECTED: the leg's EXCURSION is refused on both counters.
//       Excursion only: the built product releases a slot whose C exceeds
//       4,096 before the encode returns (U2-9 item 5), so the steady reading
//       sees none of it and this construction cannot reach the steady
//       comparison (build-time item). The hooks also confirm the arm reached
//       the forward: the long-document gate was taken for the leg (a C above
//       4,096; the unarmed 1,111-token document's C is 2,048).
//   --construction held    the steady comparison's refuse side. after_encode
//       commits and touches a 1,792 MiB block through C62's own
//       CommitAndTouch and KEEPS it past the leg's reading -- the resident
//       footprint the plan's forced-arm construction was stated to leave
//       (P:2804). EXPECTED: the leg's STEADY is refused on both counters.
//       --leg short (mc 1): held after the 5-token encode (steady bound
//       11.5 MiB); --leg long (mc 1: the 1,111-token encode, 120 MiB;
//       mc 4: the four-document batch, 456 MiB working set and 479.3 MiB
//       private bytes). One process each, so no
//       held block enters another leg's reading.
//
// Exit: 0 the construction's refusals all fired (C62 refuses what it must);
// 1 a refusal did not fire, or the arm never reached the forward (the
// instrument is NOT commissioned); 77 SKIPPED (platform) off Windows, or
// MISSING PREREQUISITE without the real model and tokenizer; 64 usage.
//
// --mechanism (every platform; the synthetic cap-5,000 pair): runs the SAME
// forced-construction hooks around a public semb_encode / semb_encode_batch,
// without C62's readings (which are Windows only), and checks what the hooks
// must do: the unarmed long document takes no gate; the armed one takes the
// gate once per document; the arm is cleared after the leg; and the slot
// holds nothing afterwards (U2-9 item 5 -- the reason the forced construction
// is excursion-only). This is the GCC-runnable proof of the construction's
// mechanism; the refusals themselves are the Windows run's.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "support/semb_u2_memory_seam.h"
#include "u2_9_c62_process.h"

namespace {

using namespace semb_c62;

constexpr uint64_t kHeldBlockMiB = 1792;  // P:2804: the 1,792 MiB full-cap slot

struct HookState {
  bool forced = false;             // the forced construction
  bool held = false;               // the held construction
  Leg target = kLegLong;           // the leg the construction acts on
  uint64_t gate_takes_before = 0;
  uint64_t gate_takes_during = 0;  // gate takes during the target leg's encode
  bool target_ran = false;
  void* held_block = nullptr;
  uint64_t held_bytes = 0;
};

void BeforeEncode(void* ctx, semb_encoder, Leg leg) {
  auto* s = static_cast<HookState*>(ctx);
  if (leg != s->target) return;
  s->target_ran = true;
  s->gate_takes_before = semb_test_seam_gate_take_records(nullptr, 0);
  if (s->forced) semb_test_seam_arm_forced_reference(1);
}

void AfterEncode(void* ctx, semb_encoder, Leg leg) {
  auto* s = static_cast<HookState*>(ctx);
  if (leg != s->target) return;
  if (s->forced) semb_test_seam_arm_forced_reference(0);
  s->gate_takes_during = semb_test_seam_gate_take_records(nullptr, 0) - s->gate_takes_before;
  if (s->held) s->held_block = CommitAndTouch(kHeldBlockMiB * 1048576ull, &s->held_bytes);
}

int g_pass = 0, g_fail = 0;
void Check(bool ok, const std::string& what) {
  (ok ? g_pass : g_fail)++;
  std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", what.c_str());
  std::fflush(stdout);
}

// C62's verdict lines, as u2_9_c62_reader.cpp's Report prints them:
// "[FAIL] <cell> <counter>: <what> <reading> MiB > <bound> MiB".
bool Refused(const std::string& log, const std::string& cell, Counter c, const std::string& what) {
  const std::string head = "[FAIL] " + cell + " " + CounterName(c) + ": " + what;
  size_t pos = 0;
  while ((pos = log.find(head, pos)) != std::string::npos) {
    if (pos == 0 || log[pos - 1] == '\n') return true;
    pos += head.size();
  }
  return false;
}

const char* Arg(int argc, char** argv, const char* key) {
  for (int i = 1; i + 1 < argc; ++i)
    if (!std::strcmp(argv[i], key)) return argv[i + 1];
  return nullptr;
}

// --mechanism: the forced hooks around the public API on a synthetic pair.
int Mechanism(const char* model, const char* tokenizer) {
  std::printf("C62 must-reject (forced), the hooks' mechanism on the synthetic cap-5,000 pair (every platform)\n");
  std::string text;
  for (int i = 0; text.size() < 1110; ++i) text += static_cast<char>('a' + (i * 7) % 26);
  for (uint32_t mc : {1u, 4u}) {
    semb_config cfg{};
    cfg.struct_size = sizeof(cfg);
    cfg.model_path = model;
    cfg.model_path_len = std::strlen(model);
    cfg.tokenizer_path = tokenizer;
    cfg.tokenizer_path_len = std::strlen(tokenizer);
    cfg.max_concurrency = mc;
    semb_encoder enc = nullptr;
    const semb_status os = semb_encoder_open(&cfg, &enc);
    Check(os == SEMB_OK, "mc=" + std::to_string(mc) + ": open " + semb_status_name(os));
    if (os != SEMB_OK) continue;
    uint32_t dims = 0;
    semb_encoder_dims(enc, &dims);
    std::vector<float> rows(4 * dims);
    semb_document docs[4];
    const char* ids[4] = {"m0", "m1", "m2", "m3"};
    for (int k = 0; k < 4; ++k) {
      docs[k] = semb_document{};
      docs[k].struct_size = sizeof(semb_document);
      docs[k].id = ids[k];
      docs[k].id_len = 2;
      docs[k].utf8 = text.data();
      docs[k].utf8_len = text.size();
    }
    const Leg leg = mc == 1 ? kLegLong : kLegBatch;
    const uint64_t docs_in_leg = mc == 1 ? 1 : 4;
    SembInterimEncoder* in = semb_test_seam_interim_of(enc);
    for (int forced = 0; forced <= 1; ++forced) {
      HookState s;
      s.forced = forced != 0;
      s.target = leg;
      semb_test_seam_gate_reset();
      BeforeEncode(&s, enc, leg);
      size_t required = 0;
      semb_status es;
      if (mc == 1) {
        semb_fingerprint fp{};
        fp.struct_size = sizeof(fp);
        es = semb_encode(enc, text.data(), text.size(), rows.data(), dims * sizeof(float), &required, &fp);
      } else {
        es = semb_encode_batch(enc, docs, 4, rows.data(), rows.size() * sizeof(float), &required);
      }
      AfterEncode(&s, enc, leg);
      uint64_t held = 0;
      for (uint64_t k = 0; k < semb_test_seam_slot_record_count(in); ++k) {
        uint64_t c = 0;
        if (semb_test_seam_slot_capacity(in, k, &c)) held += c;
      }
      const std::string tag = "mc=" + std::to_string(mc) + (forced ? " armed" : " unarmed") + ": ";
      Check(es == SEMB_OK, tag + "the encode returns " + semb_status_name(es));
      const uint64_t want = forced ? docs_in_leg : 0;
      Check(s.gate_takes_during == want, tag + "the long-document gate was taken " +
                                             std::to_string(s.gate_takes_during) + " time(s) during the leg (expected " +
                                             std::to_string(want) + ")");
      if (forced) {
        Check(held == 0, tag + "the slots hold " + std::to_string(held) +
                             " B after the encode (0: item 5 released the full-cap slot, so C62's steady reading "
                             "cannot see it and the forced construction is excursion-only)");
      }
    }
    // The arm was cleared by after_encode: a further unarmed encode takes no gate.
    semb_test_seam_gate_reset();
    size_t required = 0;
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    semb_encode(enc, text.data(), text.size(), rows.data(), dims * sizeof(float), &required, &fp);
    Check(semb_test_seam_gate_take_records(nullptr, 0) == 0,
          "mc=" + std::to_string(mc) + ": after_encode cleared the arm (a later encode takes no gate)");
    semb_encoder_close(enc);
  }
  std::printf("C62 must-reject mechanism: %d PASS, %d FAIL\n", g_pass, g_fail);
  return g_fail ? 1 : 0;
}

}  // namespace

int main(int argc, char** argv) {
  const char* model = Arg(argc, argv, "--model");
  const char* tokenizer = Arg(argc, argv, "--tokenizer");
  if (Arg(argc, argv, "--mechanism")) {
    if (!model || !tokenizer) {
      std::fprintf(stderr, "--mechanism needs --model and --tokenizer (the synthetic pair)\n");
      return 64;
    }
    return Mechanism(model, tokenizer);
  }
  const char* construction = Arg(argc, argv, "--construction");
  const char* mc_arg = Arg(argc, argv, "--mc");
  const char* leg_arg = Arg(argc, argv, "--leg");
  const uint32_t mc = mc_arg ? static_cast<uint32_t>(std::strtoul(mc_arg, nullptr, 10)) : 0;
  const bool forced = construction && !std::strcmp(construction, "forced");
  const bool held = construction && !std::strcmp(construction, "held");
  const bool short_leg = leg_arg && !std::strcmp(leg_arg, "short");
  if ((!forced && !held) || (mc != 1 && mc != 4) || (short_leg && (mc != 1 || !held))) {
    std::fprintf(stderr,
                 "usage: u2_9_c62_must_reject_test --construction forced|held --mc 1|4 [--leg short|long] "
                 "--model M --tokenizer T --long L [--short S] [--log F]\n"
                 "       u2_9_c62_must_reject_test --mechanism 1 --model M --tokenizer T\n");
    return 64;
  }
  if (!PlatformSupported()) {
    std::printf("SKIPPED (platform): C62 reads GetProcessMemoryInfo and QueryWorkingSetEx; it is Windows only "
                "(te267 U2-9, P:2845). The construction's mechanism runs on every platform (--mechanism).\n");
    return 77;
  }
  if (!model || !*model || !tokenizer || !*tokenizer) {
    std::printf("MISSING PREREQUISITE: C62's must-rejects need the real model and tokenizer (--model, "
                "--tokenizer; configure with SEMB_C12B_MODEL and SEMB_U1_TOKENIZER). No verdict.\n");
    return 77;
  }

  HookState state;
  state.forced = forced;
  state.held = held;
  state.target = short_leg ? kLegShort : (mc == 1 ? kLegLong : kLegBatch);
  Hooks hooks;
  hooks.context = &state;
  hooks.before_encode = &BeforeEncode;
  hooks.after_encode = &AfterEncode;

  ProcessOptions o;
  o.model_path = model;
  o.tokenizer_path = tokenizer;
  o.short_text_path = Arg(argc, argv, "--short");
  o.long_text_path = Arg(argc, argv, "--long");
  o.max_concurrency = mc;
  // C62's own log goes to a file this process reads back (not std::tmpfile,
  // which the Windows CRT may place in a drive's root directory).
  const char* log_arg = Arg(argc, argv, "--log");
  const std::string log_path = log_arg ? log_arg : "u2_9_c62_must_reject.log";
  std::FILE* log_file = std::fopen(log_path.c_str(), "w+b");
  if (!log_file) {
    std::printf("C62 must-reject: cannot open the log %s\n", log_path.c_str());
    return 1;
  }
  o.out = log_file;
  std::printf("C62 must-reject (%s, mc=%u, %s), the adversary's construction (te267 U2-9, P:2803-2805)\n",
              forced ? "forced-reference arm, excursion" : "held 1,792 MiB block, steady", mc,
              LegName(state.target));
  const int rc = RunProcess(o, hooks);
  // C62's own log, echoed, then read back for its verdict lines.
  std::string log;
  std::rewind(log_file);
  char buf[4096];
  size_t got;
  while ((got = std::fread(buf, 1, sizeof(buf), log_file)) > 0) log.append(buf, got);
  std::fclose(log_file);
  std::fwrite(log.data(), 1, log.size(), stdout);
  Release(state.held_block);

  Check(state.target_ran, std::string("the construction's hooks ran for ") + LegName(state.target));
  Check(rc == kExitFail, "C62's process exits FAIL (" + std::to_string(rc) + ")");
  const std::string cell = state.target == kLegShort  ? "C62 (b) mc=1, 5-token encode,"
                           : state.target == kLegLong ? "C62 (b) mc=1, 1,111-token encode,"
                                                      : "C62 (c) mc=4, four-document batch,";
  if (forced) {
    const uint64_t docs = mc == 1 ? 1 : 4;
    Check(state.gate_takes_during == docs, "the forced-reference arm reached the forward: the long-document gate "
                                           "was taken " + std::to_string(state.gate_takes_during) +
                                               " time(s) (expected " + std::to_string(docs) + ")");
    for (int c = 0; c < kCounters; ++c)
      Check(Refused(log, cell, static_cast<Counter>(c), "excursion"),
            cell + " " + CounterName(static_cast<Counter>(c)) + ": C62 refuses the excursion");
  } else {
    Check(state.held_block != nullptr && state.held_bytes == kHeldBlockMiB * 1048576ull,
          "the hook held " + std::to_string(state.held_bytes) + " B through the leg's reading");
    const std::string what = state.target == kLegShort ? "steady (above post-open)" : "steady";
    for (int c = 0; c < kCounters; ++c)
      Check(Refused(log, cell, static_cast<Counter>(c), what),
            cell + " " + CounterName(static_cast<Counter>(c)) + ": C62 refuses the steady reading");
  }
  std::printf("C62 must-reject (%s, mc=%u): %d PASS, %d FAIL\n", forced ? "forced" : "held", mc, g_pass, g_fail);
  return g_fail ? 1 : 0;
}
