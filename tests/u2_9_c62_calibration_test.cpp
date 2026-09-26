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
//          Read(), and grades it with GradeOpen: accepted. It then adds 32
//          MiB (16 MiB over): refused. Each held reading must also land
//          within 1 MiB of the value the process aimed at (the reading's
//          resolution, P:2743, P:2811). P:2807-2808.
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

void OpenCalibration() {
  // One (mc, counter) at a time. Each step commits more of this process's own
  // memory; everything is released before the next.
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
      const double hold_mib = under - MiB(start.current[c]);
      if (hold_mib <= 0) {
        Check(false, cell + ": the calibration process already reads " + F(MiB(start.current[c])) +
                         " MiB, above the under-bound target " + F(under));
        continue;
      }
      uint64_t held1 = 0, held2 = 0;
      void* first = CommitAndTouch(Bytes(hold_mib), &held1);
      const Counters r1 = Read();
      const double target1 = MiB(start.current[c]) + MiB(held1);
      const Grade g1 = GradeOpen(r1, mc, c);
      Check(first != nullptr && Near(MiB(r1.current[c]), target1),
            cell + ": footprint held " + F(MiB(held1)) + " MiB; reads " + F(MiB(r1.current[c])) + " MiB, aimed at " +
                F(target1) + " (within " + F(kResolution) + ")");
      Check(g1.verdict == Verdict::kPass, cell + ": 16 MiB under the bound (" + F(g1.reading_mib) + " vs " +
                                               F(g1.bound_mib) + ") is " + V(g1.verdict) + " (expected accepted)");
      void* second = CommitAndTouch(Bytes(2 * kMargin), &held2);
      const Counters r2 = Read();
      const double target2 = target1 + MiB(held2);
      const Grade g2 = GradeOpen(r2, mc, c);
      Check(second != nullptr && Near(MiB(r2.current[c]), target2),
            cell + ": 32 MiB more held; reads " + F(MiB(r2.current[c])) + " MiB, aimed at " + F(target2));
      Check(g2.verdict == Verdict::kFail, cell + ": 16 MiB over the bound (" + F(g2.reading_mib) + " vs " +
                                              F(g2.bound_mib) + ") is " + V(g2.verdict) + " (expected refused)");
      Release(second);
      Release(first);
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
    OpenCalibration();
    PerDocumentCalibration();
  }
  std::printf("C62 must-accept (%s): %d PASS, %d FAIL\n", legs.c_str(), g_pass, g_fail);
  return g_fail ? 1 : 0;
}
