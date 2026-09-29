// tests/u2_9_c62_process.cpp -- U2 cloud build, U2-9's C62: one C62 process.
// See u2_9_c62_process.h.
#include "u2_9_c62_process.h"

#include <chrono>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>

#include "superslm/artifact.h"
#include "superslm/tokenizer.h"

namespace semb_c62 {

const char* LegName(Leg leg) {
  switch (leg) {
    case kLegShort: return "the 5-token encode";
    case kLegLong: return "the 1,111-token encode";
    case kLegBatch: return "semb_encode_batch over four 1,111-token documents";
  }
  return "?";
}

bool CountContentTokens(const char* tokenizer_path, const char* text, size_t len, uint64_t* out) {
  std::ifstream f(tokenizer_path, std::ios::binary);
  if (!f) return false;
  std::stringstream ss;
  ss << f.rdbuf();
  const std::string bytes = ss.str();
  superslm::SslmArtifact art;
  superslm::SslmError err;
  if (superslm::SslmArtifact::OpenFromMemory(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size(), art,
                                             &err) != superslm::SslmStatus::Ok)
    return false;
  superslm::TokenizerView tv;
  std::string e;
  if (!superslm::TokenizerView::Open(art, tv, &e)) return false;
  *out = tv.Encode(std::string_view(text, len)).size();
  return true;
}

namespace {

// Everything a leg writes is allocated before open, so no heap allocation of
// the instrument's falls between the post-open reading and a leg's last.
constexpr size_t kMaxDims = 4096;
constexpr size_t kBatch = 4;
float g_rows[kBatch * kMaxDims];
semb_document g_docs[kBatch];
const char* const kDocIds[kBatch] = {"c62-0", "c62-1", "c62-2", "c62-3"};

bool ReadFile(const char* path, std::string* out) {
  if (!path) return false;
  std::ifstream f(path, std::ios::binary);
  if (!f) return false;
  std::stringstream ss;
  ss << f.rdbuf();
  *out = ss.str();
  return true;
}

const char* Name(semb_status s) {
  const char* n = semb_status_name(s);
  return n ? n : "?";
}

struct Tally {
  int pass = 0, fail = 0, none = 0;
  void Add(Verdict v) { (v == Verdict::kPass ? pass : v == Verdict::kFail ? fail : none) += 1; }
};

double Seconds(std::chrono::steady_clock::time_point t0) {
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
}

}  // namespace

int RunProcess(const ProcessOptions& o, const Hooks& hooks) {
  std::FILE* out = o.out ? o.out : stdout;
  const uint32_t mc = o.max_concurrency;
  if (mc != 1 && mc != 4) {
    std::fprintf(out, "C62: max_concurrency must be 1 or 4 (one process each, P:2722), got %u\n", mc);
    return kExitUsage;
  }
  if (!PlatformSupported()) {
    std::fprintf(out, "SKIPPED (platform): C62 reads GetProcessMemoryInfo and QueryWorkingSetEx; it is "
                      "Windows only (te267 U2-9, P:2845)\n");
    return kExitSkipped;
  }
  // Texts first: read before open, so their buffers are in every reading.
  std::string short_text, long_text;
  if ((mc == 1 && !ReadFile(o.short_text_path, &short_text)) || !ReadFile(o.long_text_path, &long_text)) {
    std::fprintf(out, "C62: cannot read the text(s) (--short/--long)\n");
    return kExitUsage;
  }
  InitInstrument();
  std::memset(g_rows, 0, sizeof(g_rows));
  for (size_t k = 0; k < kBatch; ++k) {
    g_docs[k] = semb_document{};
    g_docs[k].struct_size = sizeof(semb_document);
    g_docs[k].id = kDocIds[k];
    g_docs[k].id_len = std::strlen(kDocIds[k]);
    g_docs[k].utf8 = long_text.data();
    g_docs[k].utf8_len = long_text.size();
  }
  std::fprintf(out,
               "C62 -- resident memory of a real process (te267 U2-9, P:2720-2826), max_concurrency %u, one "
               "process\n"
               "  NOTE: C62 is registered under the instrument-commissioning rule (built_by the test author, "
               "constructed_by the adversary). Until both of the adversary's constructions have fired, every "
               "verdict below is QUARANTINED: it decides nothing (P:2791-2800).\n"
               "  texts: short %zu B, long %zu B\n",
               mc, short_text.size(), long_text.size());
  PrintCounters(out, "start", Read());

  const auto t_open = std::chrono::steady_clock::now();
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = o.model_path;
  cfg.model_path_len = std::strlen(o.model_path);
  cfg.tokenizer_path = o.tokenizer_path;
  cfg.tokenizer_path_len = std::strlen(o.tokenizer_path);
  cfg.max_concurrency = mc;
  semb_encoder enc = nullptr;
  const semb_status os = semb_encoder_open(&cfg, &enc);
  // (a): the reading is taken the moment open returns.
  const Counters post_open = Read();
  if (os != SEMB_OK) {
    std::fprintf(out, "[FAIL] C62 mc=%u: semb_encoder_open returned %s\n", mc, Name(os));
    return kExitFail;
  }
  std::fprintf(out, "open: SEMB_OK in %.1f s\n", Seconds(t_open));
  PrintCounters(out, "after open", post_open);
  if (hooks.after_open) hooks.after_open(hooks.context, enc);

  uint32_t dims = 0;
  const semb_status ds = semb_encoder_dims(enc, &dims);
  if (ds != SEMB_OK || dims == 0 || dims > kMaxDims) {
    std::fprintf(out, "[FAIL] C62 mc=%u: semb_encoder_dims returned %s, dims %u\n", mc, Name(ds), dims);
    semb_encoder_close(enc);
    return kExitFail;
  }

  semb_status short_status = SEMB_OK, long_status = SEMB_OK;
  LegReading short_leg, long_leg;
  const Leg long_kind = mc == 1 ? kLegLong : kLegBatch;
  size_t required = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);

  if (mc == 1) {
    // (b), first bullet: the 5-token encode, steady only (P:2766-2768).
    const auto t = std::chrono::steady_clock::now();
    short_leg = MeasureSteadyLeg(post_open, [&] {
      if (hooks.before_encode) hooks.before_encode(hooks.context, enc, kLegShort);
      short_status = semb_encode(enc, short_text.data(), short_text.size(), g_rows, dims * sizeof(float),
                                 &required, &fp);
      if (hooks.after_encode) hooks.after_encode(hooks.context, enc, kLegShort);
      return short_status == SEMB_OK;
    });
    std::fprintf(out, "encode (%s): %s in %.2f s\n", LegName(kLegShort), Name(short_status), Seconds(t));
    PrintLeg(out, "C62 (b) mc=1, the 5-token encode", short_leg);
  }

  {
    // (b), second bullet (mc 1), or (c) (mc 4): with the ballast in place,
    // sized here, immediately before the encode (step 1).
    const auto t = std::chrono::steady_clock::now();
    long_leg = MeasureExcursionLeg(post_open, [&] {
      if (hooks.before_encode) hooks.before_encode(hooks.context, enc, long_kind);
      if (mc == 1) {
        long_status = semb_encode(enc, long_text.data(), long_text.size(), g_rows, dims * sizeof(float),
                                  &required, &fp);
      } else {
        long_status = semb_encode_batch(enc, g_docs, kBatch, g_rows, kBatch * dims * sizeof(float), &required);
      }
      if (hooks.after_encode) hooks.after_encode(hooks.context, enc, long_kind);
      return long_status == SEMB_OK;
    });
    std::fprintf(out, "encode (%s): %s in %.2f s\n", LegName(long_kind), Name(long_status), Seconds(t));
    PrintLeg(out, mc == 1 ? "C62 (b) mc=1, the 1,111-token encode" : "C62 (c) mc=4, the four-document batch",
             long_leg);
  }

  const semb_status cs = semb_encoder_close(enc);

  // The texts' shape, counted after the last reading (see the header).
  uint64_t short_tokens = 0, long_tokens = 0;
  const bool short_counted =
      mc != 1 || CountContentTokens(o.tokenizer_path, short_text.data(), short_text.size(), &short_tokens);
  const bool long_counted = CountContentTokens(o.tokenizer_path, long_text.data(), long_text.size(), &long_tokens);
  const bool short_shape = mc != 1 || (short_counted && short_tokens == kShortContentTokens);
  const bool long_shape = long_counted && long_tokens == kLongContentTokens;
  if (mc == 1)
    std::fprintf(out, "precondition, the short text has %llu content tokens (n = 6): %s (%llu counted)\n",
                 static_cast<unsigned long long>(kShortContentTokens), short_shape ? "yes" : "NO (no verdict)",
                 static_cast<unsigned long long>(short_tokens));
  std::fprintf(out, "precondition, the long text has %llu content tokens (n = 1,112): %s (%llu counted)\n",
               static_cast<unsigned long long>(kLongContentTokens), long_shape ? "yes" : "NO (no verdict)",
               static_cast<unsigned long long>(long_tokens));

  // Verdicts.
  Tally tally;
  char cell[96];
  std::snprintf(cell, sizeof(cell), "C62 (a) mc=%u", mc);
  for (int c = 0; c < kCounters; ++c)
    tally.Add(Report(out, cell, static_cast<Counter>(c), "after open",
                     GradeOpen(post_open, mc, static_cast<Counter>(c))));

  if (mc == 1) {
    if (short_status != SEMB_OK) {
      std::fprintf(out, "[FAIL] C62 (b) mc=1: the 5-token semb_encode returned %s\n", Name(short_status));
      tally.Add(Verdict::kFail);
    } else {
      for (int c = 0; c < kCounters; ++c)
        tally.Add(Report(out, "C62 (b) mc=1, 5-token encode,", static_cast<Counter>(c), "steady (above post-open)",
                         GradeAtMost(short_leg.steady_mib[c], kShortSteadyBoundMiB,
                                     short_leg.preconditions_hold() && short_shape)));
    }
  }
  const char* long_cell = mc == 1 ? "C62 (b) mc=1, 1,111-token encode," : "C62 (c) mc=4, four-document batch,";
  const double excursion_bound = mc == 1 ? kLongExcursionBoundMiB : kBatchExcursionBoundMiB;
  if (long_status != SEMB_OK) {
    std::fprintf(out, "[FAIL] %s the encode returned %s\n", long_cell, Name(long_status));
    tally.Add(Verdict::kFail);
  } else {
    const bool pre = long_leg.preconditions_hold() && long_shape;
    for (int c = 0; c < kCounters; ++c) {
      const Counter k = static_cast<Counter>(c);
      const double steady_bound = mc == 1 ? kLongSteadyBoundMiB : BatchSteadyBoundMiB(k);
      tally.Add(Report(out, long_cell, k, "steady (above post-open, less the ballast)",
                       GradeAtMost(long_leg.steady_mib[c], steady_bound, pre)));
    }
    for (int c = 0; c < kCounters; ++c)
      tally.Add(Report(out, long_cell, static_cast<Counter>(c), "excursion (above the raised floor)",
                       GradeAtMost(long_leg.excursion_mib[c], excursion_bound, pre)));
  }
  if (cs != SEMB_OK) {
    std::fprintf(out, "[FAIL] C62 mc=%u: semb_encoder_close returned %s\n", mc, Name(cs));
    tally.Add(Verdict::kFail);
  }
  std::fprintf(out, "C62 mc=%u: %d PASS, %d FAIL, %d NO VERDICT (QUARANTINED until commissioned)\n", mc,
               tally.pass, tally.fail, tally.none);
  std::fflush(out);
  if (tally.fail) return kExitFail;
  if (tally.none) return kExitNoVerdict;
  return kExitPass;
}

}  // namespace semb_c62
