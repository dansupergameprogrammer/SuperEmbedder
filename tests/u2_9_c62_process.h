// tests/u2_9_c62_process.h -- U2 cloud build, U2-9's C62 (te267 sec 5 U2-9,
// C62, P:2720-2826): one C62 process, at one max_concurrency (P:2722), on
// the public semb.h API and the real artifact.
//
//   max_concurrency 1:  open -> (a) -> (b) the 5-token encode, steady ->
//                       (b) the 1,111-token encode, with the ballast in place,
//                       steady and excursion -> close.
//   max_concurrency 4:  open -> (a) -> (c) semb_encode_batch over four copies
//                       of the 1,111-token text, with the ballast in place,
//                       steady and excursion -> close.
// The ballast is sized immediately before the encode it measures (step 1,
// P:2731), so at mc 1 it is sized after the 5-token encode, from whatever
// peak that encode left.
//
// After close, and before any verdict, the process counts both texts' content
// tokens with the tokenizer artifact it opened (SuperSLM's TokenizerView):
// C62's bounds are derived for n = 6 and n = 1,112 (5 and 1,111 content
// tokens plus the terminator), so a text of any other shape emits no
// per-document verdict. The count runs after the last reading, so the
// tokenizer's memory never enters one.
//
// The library (CMake target u2_9_c62_process) is linked with EITHER product
// library: C62's own executable links the shipped `superembedder`; a
// construction that must run "the same process on the test-seam library"
// (P:2803-2805) links `superembedder_testseam` and sets its arm through the
// hooks below. The hooks are the only difference; the readings, the steps
// and the grading are C62's own (u2_9_c62_reader.h).
#ifndef SEMB_U2_9_C62_PROCESS_H
#define SEMB_U2_9_C62_PROCESS_H

#include <cstdint>
#include <cstdio>

#include "superembedder/semb.h"
#include "u2_9_c62_reader.h"

namespace semb_c62 {

enum Leg : int { kLegShort = 0, kLegLong = 1, kLegBatch = 2 };
const char* LegName(Leg leg);

// Hooks for a construction. Every pointer may be null (C62's own run passes
// none). Nothing C62 reads is taken while a hook runs, except what the hook
// itself leaves behind.
struct Hooks {
  void* context = nullptr;
  // After open, after (a)'s reading; before any encode.
  void (*after_open)(void* context, semb_encoder enc) = nullptr;
  // Immediately before the leg's encode call (on a ballasted leg, after the
  // ballast step: the hook's own commits raise the floor's pre-encode value,
  // not the excursion).
  void (*before_encode)(void* context, semb_encoder enc, Leg leg) = nullptr;
  // Immediately after the leg's encode call returns, before the leg's
  // reading: what a hook commits and keeps here reads in both steady and
  // excursion; what it commits and frees reads in excursion only.
  void (*after_encode)(void* context, semb_encoder enc, Leg leg) = nullptr;
};

struct ProcessOptions {
  const char* model_path = nullptr;
  const char* tokenizer_path = nullptr;
  const char* short_text_path = nullptr;  // required at mc 1
  const char* long_text_path = nullptr;
  uint32_t max_concurrency = 0;           // 1 or 4
  std::FILE* out = nullptr;               // null = stdout
};

// Exit statuses of RunProcess.
constexpr int kExitPass = 0;          // every verdict PASS
constexpr int kExitFail = 1;          // one or more FAIL
constexpr int kExitNoVerdict = 2;     // no FAIL; one or more NO VERDICT
constexpr int kExitUsage = 64;        // bad options, unreadable text
constexpr int kExitSkipped = 77;      // not Windows (platform skip)

// The content-token shapes C62's bounds are derived for (P:2766-2780).
constexpr uint64_t kShortContentTokens = 5;
constexpr uint64_t kLongContentTokens = 1111;

int RunProcess(const ProcessOptions& options, const Hooks& hooks);

// Counts `text`'s content tokens (no terminator) with the tokenizer artifact
// at `tokenizer_path`. False if the artifact cannot be read.
bool CountContentTokens(const char* tokenizer_path, const char* text, size_t len, uint64_t* out);

}  // namespace semb_c62

#endif  // SEMB_U2_9_C62_PROCESS_H
