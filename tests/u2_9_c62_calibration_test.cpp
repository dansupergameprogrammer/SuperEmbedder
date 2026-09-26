// tests/u2_9_c62_calibration_test.cpp -- U2 cloud build, U2-9's C62: the
// adversary's must-accept constructions (te267 sec 5 U2-9, C62, P:2806-2811).
// Authored by the adversary seat, blind to the test author's own controls
// (P:2794); C62's reading and comparison code is the test author's
// (u2_9_c62_reader.h, P:2792) and is linked unchanged. This process links
// ONLY `u2_9_c62_reader` -- no product library -- so every byte it reads is a
// footprint it made itself, of a known size.
//
// Two legs, registered as two ctest entries:
//
//   --legs reading     (Windows; the plan's construction)
//     (a)  For each max_concurrency in {1, 4} and each counter, the process
//          commits and touches a footprint that brings that counter's CURRENT
//          value to 16 MiB under the (a) bound (P:2757-2760), reads it with
//          Read(), and grades it with GradeOpen: accepted. It then raises the
//          counter to 16 MiB over: refused. P:2807-2808. The footprint is
//          placed by the counter C62 reads, read back after each commit
//          (PlaceCounter), not by its block size: holding memory also costs
//          the block's page tables, 1/512 of it on Windows (a 630.2 MiB block
//          read 632.1 MiB against 630.9 aimed by size on the dev box). The
//          plan fixes no readback tolerance for (a); the placement is checked
//          to land within 1 MiB of its aim.
//     ORDER: the per-document legs run first, while this process's peak gap
//          is small, so C62's ballast step sizes a small ballast. Run after
//          (a), every ballast would be ~670 MiB, and steady -- which
//          subtracts the ballast's bytes but not its page tables -- would
//          read a kept block ~1.3 MiB high (a kept 64 MiB block read 65.6 MiB
//          of private bytes on the dev box). A diagnostic leg measures that
//          residue under a ~653 MiB ballast and prints it as a NOTE.
//     (b), (c) excursion   C62's own ballast step (MeasureExcursionLeg), then
//          an action that touches and frees a known block. A 64 MiB block
//          must read 64 MiB of excursion within 1 MiB on both counters; a
//          block 16 MiB under each excursion bound (189.5, 734.0) is
//          accepted and 16 MiB over is refused, on both counters.
//          P:2809-2811.
//     (b), (c) steady      (a build-time item under D-SLM7811, not a plan
//          revision: the plan's forced-arm must-reject cannot reach the
//          steady comparison, because the built product releases a
//          C > 4,096 slot at the end of its encode (U2-9 item 5), so the
//          steady comparison's accept and refuse sides are calibrated here
//          too.) The action commits, touches and KEEPS a block: a 64 MiB
//          block must read 64 MiB of steady within 1 MiB on both counters;
//          blocks 16 MiB under and over the steady bounds 120 and 456 (the
//          ballasted legs) are accepted and refused; the short leg's steady
//          bound, 11.5 MiB (a steady-only leg, MeasureSteadyLeg), accepts a
//          3.5 MiB block (the design figure; 16 MiB under is negative) and
//          refuses 27.5 MiB (16 MiB over).
//     Off Windows: SKIPPED (platform), exit 77. C62 is Windows only (P:2845).
//
//   --legs comparison  (every platform)
//     C62's comparison code alone, driven with constructed readings: every
//     bound's accept side (bound - 16 MiB) and refuse side (bound + 16 MiB)
//     through GradeOpen, GradeSteady, GradeExcursion and GradeAtMost, and a
//     leg whose preconditions fail (floor, residency, a steady-only leg's
//     excursion) emits no verdict. It proves the comparison, not the
//     reading; the reading leg is the plan's construction.
//
// Exit: 0 every construction held; 1 a construction failed (the instrument is
// NOT commissioned); 77 skipped (not Windows, reading leg); 64 usage.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "u2_9_c62_reader.h"

namespace {

using namespace semb_c62;

int g_pass = 0, g_fail = 0;

void Check(bool ok, const std::string& what) {
  (ok ? g_pass : g_fail)++;
  std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", what.c_str());
  std::fflush(stdout);
}

const char* V(Verdict v) {
  return v == Verdict::kPass ? "accepted" : v == Verdict::kFail ? "refused" : "no verdict";
}

std::string F(double x) {
  char b[32];
  std::snprintf(b, sizeof(b), "%.1f", x);
  return b;
}

constexpr double kMargin = 16.0;      // P:2807-2810
constexpr double kResolution = 1.0;   // P:2743, P:2809-2811
constexpr uint64_t kKnownBlockMiB = 64;

uint64_t Bytes(double mib) { return static_cast<uint64_t>(std::llround(mib * kMiB)); }

// ---------------------------------------------------------------------------
// --legs comparison: C62's comparison code, constructed readings.
// ---------------------------------------------------------------------------
LegReading ConstructedLeg(bool ballasted, double steady, double excursion) {
  LegReading r;
  r.base.ok = true;
  r.after.ok = true;
  r.raised.ok = true;
  r.ballasted = ballasted;
  r.ballast_committed = ballasted;
  r.floor_ok = ballasted;
  r.resident_ok = ballasted;
  for (int c = 0; c < kCounters; ++c) {
    r.steady_mib[c] = steady;
    r.excursion_mib[c] = excursion;
  }
  return r;
}

void ComparisonLegs() {
  std::printf("C62 must-accept, the comparison (constructed readings; every platform)\n");
  // (a): GradeOpen against P:2757-2760's four bounds.
  const struct { uint32_t mc; Counter c; double bound; } open_bounds[] = {
      {1, kWorkingSet, 641.2}, {1, kPrivateBytes, 646.9}, {4, kWorkingSet, 641.9}, {4, kPrivateBytes, 657.2}};
  for (const auto& b : open_bounds) {
    Check(OpenBoundMiB(b.mc, b.c) == b.bound, "(a) mc=" + std::to_string(b.mc) + " " + CounterName(b.c) +
                                                  ": OpenBoundMiB reads the plan's " + F(b.bound) + " MiB (" +
                                                  F(OpenBoundMiB(b.mc, b.c)) + ")");
    for (int side = -1; side <= 1; side += 2) {
      Counters r;
      r.ok = true;
      r.current[b.c] = Bytes(b.bound + side * kMargin);
      const Grade g = GradeOpen(r, b.mc, b.c);
      const Verdict want = side < 0 ? Verdict::kPass : Verdict::kFail;
      Check(g.verdict == want, "(a) mc=" + std::to_string(b.mc) + " " + CounterName(b.c) + ": a reading " +
                                   F(std::fabs(kMargin)) + " MiB " + (side < 0 ? "under" : "over") +
                                   " the bound is " + V(g.verdict) + " (expected " + V(want) + ")");
    }
    Counters bad;  // no reading
    Check(GradeOpen(bad, b.mc, b.c).verdict == Verdict::kNoVerdict,
          "(a) mc=" + std::to_string(b.mc) + " " + CounterName(b.c) + ": a failed reading emits no verdict");
  }
  // (b), (c): steady and excursion bounds (P:2770-2785).
  const struct { const char* name; double bound; bool steady; bool ballasted; } per_doc[] = {
      {"(b) 5-token steady", kShortSteadyBoundMiB, true, false},
      {"(b) 1,111-token steady", kLongSteadyBoundMiB, true, true},
      {"(b) 1,111-token excursion", kLongExcursionBoundMiB, false, true},
      {"(c) batch steady", kBatchSteadyBoundMiB, true, true},
      {"(c) batch excursion", kBatchExcursionBoundMiB, false, true}};
  const double plan_bounds[] = {11.5, 120.0, 189.5, 456.0, 734.0};
  for (size_t i = 0; i < sizeof(per_doc) / sizeof(per_doc[0]); ++i) {
    const auto& d = per_doc[i];
    Check(d.bound == plan_bounds[i], std::string(d.name) + ": the bound reads the plan's " + F(plan_bounds[i]) +
                                         " MiB (" + F(d.bound) + ")");
    for (int side = -1; side <= 1; side += 2) {
      const double reading = d.bound + side * kMargin;
      const LegReading leg = ConstructedLeg(d.ballasted, reading, reading);
      for (int c = 0; c < kCounters; ++c) {
        const Counter k = static_cast<Counter>(c);
        const Grade g = d.steady ? GradeSteady(leg, k, d.bound) : GradeExcursion(leg, k, d.bound);
        const Verdict want = side < 0 ? Verdict::kPass : Verdict::kFail;
        Check(g.verdict == want, std::string(d.name) + " " + CounterName(k) + ": " + F(reading) + " MiB is " +
                                     V(g.verdict) + " (expected " + V(want) + ")");
      }
    }
    if (d.ballasted) {
      // A leg whose floor or residency precondition failed emits no verdict,
      // however far over the bound it reads (P:2733-2734, P:2739-2741).
      LegReading floor = ConstructedLeg(true, d.bound + 1000, d.bound + 1000);
      floor.floor_ok = false;
      LegReading trimmed = ConstructedLeg(true, d.bound + 1000, d.bound + 1000);
      trimmed.resident_ok = false;
      trimmed.nonresident_pages = 1;
      for (int c = 0; c < kCounters; ++c) {
        const Counter k = static_cast<Counter>(c);
        const Grade gf = d.steady ? GradeSteady(floor, k, d.bound) : GradeExcursion(floor, k, d.bound);
        const Grade gt = d.steady ? GradeSteady(trimmed, k, d.bound) : GradeExcursion(trimmed, k, d.bound);
        Check(gf.verdict == Verdict::kNoVerdict,
              std::string(d.name) + " " + CounterName(k) + ": a raised floor that failed emits no verdict (" +
                  V(gf.verdict) + ")");
        Check(gt.verdict == Verdict::kNoVerdict,
              std::string(d.name) + " " + CounterName(k) + ": a trimmed ballast page emits no verdict (" +
                  V(gt.verdict) + ")");
      }
    }
  }
  // An excursion is never graded on a steady-only leg.
  const LegReading steady_only = ConstructedLeg(false, 0, 1000);
  Check(GradeExcursion(steady_only, kWorkingSet, kLongExcursionBoundMiB).verdict == Verdict::kNoVerdict,
        "a steady-only leg's excursion emits no verdict");
}

// ---------------------------------------------------------------------------
// --legs reading: the plan's calibration processes (Windows).
// ---------------------------------------------------------------------------
bool Near(double reading, double expected) { return std::fabs(reading - expected) <= kResolution; }

// Places this process's `c` counter at `aim_mib` by committing and touching
// blocks of its own memory: a first block sized to undershoot, then top-ups
// read back after each commit, until the counter reads within 0.5 MiB of the
// aim. Holding memory costs more than the block itself -- on Windows the
// block's own page tables (8 B per 4 KiB page, 1/512 of the block: 1.2 MiB
// for a 630 MiB footprint) are charged to the process -- so a footprint
// "16 MiB under the bound" is placed by the counter C62 reads, not by the
// block's size. Returns the reading; `blocks` holds what to release.
Counters PlaceCounter(Counter c, double aim_mib, void** blocks, int max_blocks, int* n_blocks,
                      double* committed_mib) {
  Counters r = Read();
  *n_blocks = 0;
  *committed_mib = 0;
  for (int step = 0; step < max_blocks && r.ok; ++step) {
    const double gap = aim_mib - MiB(r.current[c]);
    if (gap <= 0.5) break;
    // Undershoot by the block's page-table share and half a MiB, so the
    // placement approaches the aim from below and never overshoots it.
    const double want = step == 0 ? gap * 512.0 / 513.0 - 0.5 : gap - 0.25;
    if (want <= 0) break;
    uint64_t held = 0;
    void* p = CommitAndTouch(Bytes(want), &held);
    if (!p) break;
    blocks[(*n_blocks)++] = p;
    *committed_mib += MiB(held);
    r = Read();
  }
  return r;
}

void OpenCalibration() {
  // One (mc, counter) at a time; everything is released before the next.
  const Counter counters[] = {kWorkingSet, kPrivateBytes};
  for (uint32_t mc : {1u, 4u}) {
    for (Counter c : counters) {
      const double bound = OpenBoundMiB(mc, c);
      const std::string cell = "C62 (a) calibration mc=" + std::to_string(mc) + " " + CounterName(c);
      const Counters start = Read();
      if (!start.ok) {
        Check(false, cell + ": Read() failed");
        continue;
      }
      const double under = bound - kMargin;
      if (MiB(start.current[c]) >= under) {
        Check(false, cell + ": the calibration process already reads " + F(MiB(start.current[c])) +
                         " MiB, above the under-bound target " + F(under));
        continue;
      }
      void* blocks[16] = {};
      int n = 0;
      double committed = 0;
      const Counters r1 = PlaceCounter(c, under, blocks, 8, &n, &committed);
      const Grade g1 = GradeOpen(r1, mc, c);
      std::printf("  %s: placed at %s MiB with %s MiB committed in %d block(s) from %s MiB (holding overhead "
                  "%s MiB)\n", cell.c_str(), F(MiB(r1.current[c])).c_str(), F(committed).c_str(), n,
                  F(MiB(start.current[c])).c_str(),
                  F(MiB(r1.current[c]) - MiB(start.current[c]) - committed).c_str());
      Check(r1.ok && Near(MiB(r1.current[c]), under),
            cell + ": the footprint reads " + F(MiB(r1.current[c])) + " MiB, placed at " + F(under) +
                " (bound - 16) within " + F(kResolution));
      Check(g1.verdict == Verdict::kPass, cell + ": 16 MiB under the bound (" + F(g1.reading_mib) + " vs " +
                                               F(g1.bound_mib) + ") is " + V(g1.verdict) + " (expected accepted)");
      int n2 = 0;
      double committed2 = 0;
      const Counters r2 = PlaceCounter(c, bound + kMargin, blocks + n, 8, &n2, &committed2);
      const Grade g2 = GradeOpen(r2, mc, c);
      Check(r2.ok && Near(MiB(r2.current[c]), bound + kMargin),
            cell + ": the footprint reads " + F(MiB(r2.current[c])) + " MiB, placed at " + F(bound + kMargin) +
                " (bound + 16) within " + F(kResolution));
      Check(g2.verdict == Verdict::kFail, cell + ": 16 MiB over the bound (" + F(g2.reading_mib) + " vs " +
                                              F(g2.bound_mib) + ") is " + V(g2.verdict) + " (expected refused)");
      for (int k = n + n2 - 1; k >= 0; --k) Release(blocks[k]);
    }
  }
}

// Excursion: touch and free a block inside C62's own ballast step.
LegReading ExcursionOf(double block_mib) {
  const Counters base = Read();
  return MeasureExcursionLeg(base, [block_mib] {
    uint64_t held = 0;
    void* p = CommitAndTouch(Bytes(block_mib), &held);
    Release(p);
    return p != nullptr;
  });
}

// Steady: commit, touch and KEEP a block; released after the leg's reading.
LegReading SteadyOf(double block_mib, bool ballasted) {
  const Counters base = Read();
  void* kept = nullptr;
  auto action = [&kept, block_mib] {
    uint64_t held = 0;
    kept = CommitAndTouch(Bytes(block_mib), &held);
    return kept != nullptr;
  };
  LegReading leg = ballasted ? MeasureExcursionLeg(base, action) : MeasureSteadyLeg(base, action);
  Release(kept);
  return leg;
}

void PerDocumentCalibration() {
  // The reading's resolution: a known block reads within 1 MiB (P:2809-2811).
  {
    const LegReading e = ExcursionOf(kKnownBlockMiB);
    PrintLeg(stdout, "C62 (b)/(c) calibration, a 64 MiB block touched and freed", e);
    for (int c = 0; c < kCounters; ++c)
      Check(e.preconditions_hold() && e.action_ok && Near(e.excursion_mib[c], kKnownBlockMiB),
            std::string("C62 (b)/(c) calibration ") + CounterName(static_cast<Counter>(c)) +
                ": excursion reads the 64 MiB block as " + F(e.excursion_mib[c]) + " MiB (within 1 MiB)");
    const LegReading s = SteadyOf(kKnownBlockMiB, true);
    PrintLeg(stdout, "C62 (b)/(c) calibration, a 64 MiB block kept", s);
    for (int c = 0; c < kCounters; ++c)
      Check(s.preconditions_hold() && s.action_ok && Near(s.steady_mib[c], kKnownBlockMiB),
            std::string("C62 (b)/(c) calibration ") + CounterName(static_cast<Counter>(c)) +
                ": steady reads the kept 64 MiB block as " + F(s.steady_mib[c]) + " MiB (within 1 MiB)");
  }
  // What C62's steady value keeps of its own ballast. Steady subtracts the
  // ballast's bytes, not what holding them costs (its page tables on
  // Windows), so after a large earlier peak -- as in C62's own run, where the
  // open's two model copies set the peak -- the ballast is large and steady
  // reads above the block by about ballast / 512. Measured, not graded: the
  // resolution legs above run first, while this process's peak gap is small.
  {
    uint64_t held = 0;
    void* inflate = CommitAndTouch(Bytes(652.0), &held);  // ~ C62's mc 1 ballast (P:2732)
    Release(inflate);
    const LegReading s = SteadyOf(kKnownBlockMiB, true);
    PrintLeg(stdout, "C62 (b)/(c) diagnostic, a 64 MiB block kept under a ~653 MiB ballast", s);
    for (int c = 0; c < kCounters; ++c)
      std::printf("[NOTE] C62 (b)/(c) %s: steady reads the kept 64 MiB block as %s MiB under a %s MiB ballast "
                  "(%+.2f MiB; ballast / 512 = %.2f MiB)\n",
                  CounterName(static_cast<Counter>(c)), F(s.steady_mib[c]).c_str(), F(MiB(s.ballast_bytes)).c_str(),
                  s.steady_mib[c] - kKnownBlockMiB, MiB(s.ballast_bytes) / 512.0);
  }
  // Accept and refuse, 16 MiB either side of each bound, on both counters.
  struct Case { const char* name; double bound; bool steady; bool ballasted; double under; };
  const Case cases[] = {
      {"(b) 1,111-token excursion", kLongExcursionBoundMiB, false, true, kLongExcursionBoundMiB - kMargin},
      {"(c) batch excursion", kBatchExcursionBoundMiB, false, true, kBatchExcursionBoundMiB - kMargin},
      {"(b) 1,111-token steady", kLongSteadyBoundMiB, true, true, kLongSteadyBoundMiB - kMargin},
      {"(c) batch steady", kBatchSteadyBoundMiB, true, true, kBatchSteadyBoundMiB - kMargin},
      // 16 MiB under 11.5 is negative: the accept side holds the design's 3.5 MiB.
      {"(b) 5-token steady", kShortSteadyBoundMiB, true, false, 3.5},
  };
  for (const Case& k : cases) {
    const double sizes[2] = {k.under, k.bound + kMargin};
    for (int side = 0; side < 2; ++side) {
      const LegReading leg = k.steady ? SteadyOf(sizes[side], k.ballasted) : ExcursionOf(sizes[side]);
      const std::string cell = std::string("C62 ") + k.name + " calibration, a " + F(sizes[side]) + " MiB block";
      PrintLeg(stdout, cell.c_str(), leg);
      for (int c = 0; c < kCounters; ++c) {
        const Counter ctr = static_cast<Counter>(c);
        const Grade g = k.steady ? GradeSteady(leg, ctr, k.bound) : GradeExcursion(leg, ctr, k.bound);
        const Verdict want = side == 0 ? Verdict::kPass : Verdict::kFail;
        Check(leg.action_ok && g.verdict == want, cell + " " + CounterName(ctr) + ": reads " + F(g.reading_mib) +
                                                      " MiB against " + F(k.bound) + ": " + V(g.verdict) +
                                                      " (expected " + V(want) + ")");
      }
    }
  }
}

}  // namespace

int main(int argc, char** argv) {
  std::string legs;
  for (int i = 1; i + 1 < argc; i += 2)
    if (!std::strcmp(argv[i], "--legs")) legs = argv[i + 1];
  if (legs != "comparison" && legs != "reading") {
    std::fprintf(stderr, "usage: u2_9_c62_calibration_test --legs comparison|reading\n");
    return 64;
  }
  std::printf("C62 must-accept constructions (the adversary's; te267 U2-9, P:2806-2811), legs: %s\n",
              legs.c_str());
  if (legs == "comparison") {
    ComparisonLegs();
  } else {
    if (!PlatformSupported()) {
      std::printf("SKIPPED (platform): the calibration reads GetProcessMemoryInfo and QueryWorkingSetEx "
                  "through C62's reader; Windows only (te267 U2-9, P:2845)\n");
      return 77;
    }
    InitInstrument();
    // Per-document legs first: C62's ballast is sized from this process's
    // peak gap, and the (a) legs' footprints (up to ~673 MiB, touched and
    // freed) would otherwise size every later ballast at ~670 MiB, whose
    // unsubtracted page tables (~1.3 MiB) enter the steady readback.
    PerDocumentCalibration();
    OpenCalibration();
  }
  std::printf("C62 must-accept (%s): %d PASS, %d FAIL\n", legs.c_str(), g_pass, g_fail);
  return g_fail ? 1 : 0;
}
