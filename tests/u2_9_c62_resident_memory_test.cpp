// tests/u2_9_c62_resident_memory_test.cpp -- U2 cloud build, U2-9's C62:
// resident memory of a real process (te267 sec 5 U2-9, C62, P:2720-2826).
// Authored by the test author, who is C62's builder (P:2792-2793); the
// adversary authors and executes its constructions (P:2794-2810).
//
// One process per max_concurrency (P:2722): tests/CMakeLists.txt registers
// this executable twice, at --mc 1 ((a) and (b)) and at --mc 4 ((a) and (c)).
// Public semb.h API, the shipped static product library, the real artifact.
// The process, the readings and the grading are u2_9_c62_process.h and
// u2_9_c62_reader.h; this file only parses arguments.
//
// usage: u2_9_c62_resident_memory_test --mc <1|4> --model <.sslm>
//            --tokenizer <.sslm> --long <long.txt> [--short <short.txt>]
//   (--short is required at --mc 1). The committed texts are
//   tests/fixtures/c62/{short,long}.txt.
//
// Exit: 0 every verdict PASS; 1 a FAIL; 2 no FAIL but a NO VERDICT (a
// precondition failed: the ballast floor, a trimmed ballast page, or a text
// of the wrong shape); 64 usage; 77 skipped: not Windows (C62 is Windows
// only, P:2845), or MISSING PREREQUISITE (no --model / --tokenizer). ctest
// maps 77 to "Skipped" (SKIP_RETURN_CODE), so neither case passes.
//
// RED on today's build (P:2833): (a) reads the pin-step open, ~3,031.5 MiB of
// working set at mc 1 and ~8,408.2 at mc 4, against 641.2 / 641.9. That
// reading is recorded QUARANTINED: C62 decides nothing until the adversary's
// constructions fire.
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "u2_9_c62_process.h"

int main(int argc, char** argv) {
  semb_c62::ProcessOptions o;
  for (int i = 1; i + 1 < argc; i += 2) {
    const char* k = argv[i];
    const char* v = argv[i + 1];
    if (!std::strcmp(k, "--mc")) o.max_concurrency = static_cast<uint32_t>(std::strtoul(v, nullptr, 10));
    else if (!std::strcmp(k, "--model")) o.model_path = v;
    else if (!std::strcmp(k, "--tokenizer")) o.tokenizer_path = v;
    else if (!std::strcmp(k, "--short")) o.short_text_path = v;
    else if (!std::strcmp(k, "--long")) o.long_text_path = v;
    else {
      std::fprintf(stderr, "C62: unknown argument %s\n", k);
      return semb_c62::kExitUsage;
    }
  }
  if (argc % 2 == 0) {
    std::fprintf(stderr, "C62: arguments come in pairs\n");
    return semb_c62::kExitUsage;
  }
  if (!semb_c62::PlatformSupported()) {
    std::printf("SKIPPED (platform): C62 reads GetProcessMemoryInfo and QueryWorkingSetEx; it is Windows only "
                "(te267 U2-9, P:2845)\n");
    return semb_c62::kExitSkipped;
  }
  if (!o.model_path || !*o.model_path || !o.tokenizer_path || !*o.tokenizer_path) {
    std::printf("MISSING PREREQUISITE: C62 needs the real model and tokenizer (--model, --tokenizer; "
                "configure with SEMB_C12B_MODEL and SEMB_U1_TOKENIZER). No verdict.\n");
    return semb_c62::kExitSkipped;
  }
  if (o.max_concurrency != 1 && o.max_concurrency != 4) {
    std::fprintf(stderr, "C62: --mc must be 1 or 4\n");
    return semb_c62::kExitUsage;
  }
  return semb_c62::RunProcess(o, semb_c62::Hooks{});
}
