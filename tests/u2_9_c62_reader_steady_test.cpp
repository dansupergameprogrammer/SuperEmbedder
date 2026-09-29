// tests/u2_9_c62_reader_steady_test.cpp -- U2 cloud build, U2-9's C62: the
// steady reading (P:2737-2738, "each current value less the ballast's size,
// compared with the post-open reading"), at the comparison level, on every
// platform. The test author's own check of C62's reader; the adversary's
// constructions are separate.
//
// The ballast is the instrument (P:2731-2732), so steady subtracts what the
// ballast costs on each counter, as step 1's two readings measure it in the
// same run (raised.current - before.current), not its bytes alone: on
// Windows private bytes also carry the ballast's page tables, about 1/512 of
// it. ComputeStep3 is the one place step 3 is computed (EndExcursion calls
// it), so these constructed readings drive the code C62 runs.
//
// Mutation proof: steady = after - ballast bytes - base (the formula this
// replaced) reads the dev box's mc 4 shape 1.17 MiB high and refuses the
// accept-side case below; each is a FAIL line here. A constant charge
// (bytes / 512) fails the 1/464 case.
#include <cmath>
#include <cstdio>
#include <string>

#include "u2_9_c62_reader.h"

using namespace semb_c62;

namespace {
int g_fail = 0;
void Check(bool ok, const std::string& what) {
  if (!ok) ++g_fail;
  std::printf("[%s] steady %s\n", ok ? "PASS" : "FAIL", what.c_str());
}
std::string F(double x, int prec = 3) {
  char b[48];
  std::snprintf(b, sizeof(b), "%.*f", prec, x);
  return b;
}
// Readings are whole pages on Windows; build them on 4 KiB pages so the
// arithmetic below is exact to the byte.
constexpr uint64_t kPage = 4096;
uint64_t Pages(double mib) { return static_cast<uint64_t>(std::llround(mib * kMiB / kPage)) * kPage; }
const char* V(Verdict v) {
  return v == Verdict::kPass ? "accepted" : v == Verdict::kFail ? "refused" : "no verdict";
}
constexpr double kTol = 1e-9;  // MiB; the arithmetic is exact, this only absorbs double rounding

Counters Make(uint64_t ws, uint64_t pb) {
  Counters r;
  r.ok = true;
  r.current[kWorkingSet] = r.peak[kWorkingSet] = ws;
  r.current[kPrivateBytes] = r.peak[kPrivateBytes] = pb;
  return r;
}

// One ballasted leg, constructed: `base` is the post-open reading, `drift`
// what the product retained between it and the ballast step (both counters),
// `ballast` its bytes, `pt_div` its page-table ratio on private bytes (0 = no
// overhead), `growth` the product's growth across the action (both counters,
// its own page tables included on private bytes as `growth_pt`).
LegReading Leg(uint64_t base_ws, uint64_t base_pb, uint64_t drift, uint64_t ballast, double pt_div, uint64_t growth,
               uint64_t growth_pt) {
  LegReading r;
  r.base = Make(base_ws, base_pb);
  r.ballasted = r.ballast_committed = r.resident_ok = true;
  r.before = Make(base_ws + drift, base_pb + drift);
  // Earlier peaks well below the raised floor (the precondition holds).
  r.before.peak[kWorkingSet] = r.before.current[kWorkingSet] + ballast - Pages(1.0);
  r.before.peak[kPrivateBytes] = r.before.current[kPrivateBytes] + ballast - Pages(1.0);
  const uint64_t charge_pb = ballast + (pt_div > 0 ? Pages(MiB(ballast) / pt_div) : 0);
  r.ballast_bytes = ballast;
  r.raised = Make(r.before.current[kWorkingSet] + ballast, r.before.current[kPrivateBytes] + charge_pb);
  r.floor_ok = FloorAboveEarlierPeaks(r.before, r.raised);
  r.after = Make(r.raised.current[kWorkingSet] + growth, r.raised.current[kPrivateBytes] + growth + growth_pt);
  r.action_ok = true;
  ComputeStep3(&r);
  return r;
}
}  // namespace

int main() {
  // 1. The dev box's mc 4 shape (C62 (c), MSVC, tip 1ed6b7f): post-open
  //    working set 634.8 and private 633.2 MiB, a 600.3 MiB ballast, and a
  //    product that grew by 448 MiB of buffers plus their own page tables
  //    (448 / 512 = 0.875 MiB of private bytes) plus 6.0 MiB of other growth.
  //    Steady must read exactly the product's growth on each counter: the
  //    ballast's page tables (600.3 / 512 = 1.17 MiB) are not in it, the
  //    product's own are.
  {
    const uint64_t growth = Pages(454.0), growth_pt = Pages(448.0 / 512.0);
    const LegReading r = Leg(Pages(634.8), Pages(633.2), 0, Pages(600.3), 512.0, growth, growth_pt);
    const double want_ws = MiB(growth), want_pb = MiB(growth + growth_pt);
    Check(r.floor_ok && r.preconditions_hold(), "mc 4 shape: the constructed leg meets every precondition");
    Check(std::fabs(r.steady_mib[kWorkingSet] - want_ws) < kTol,
          "mc 4 shape, working set: reads the product's growth " + F(want_ws) + " MiB (" +
              F(r.steady_mib[kWorkingSet]) + ")");
    Check(std::fabs(r.steady_mib[kPrivateBytes] - want_pb) < kTol,
          "mc 4 shape, private bytes: reads the product's growth " + F(want_pb) +
              " MiB, its own page tables included and the ballast's excluded (" +
              F(r.steady_mib[kPrivateBytes]) + "; the bytes-only formula reads " +
              F(MiB(r.after.current[kPrivateBytes]) - MiB(r.ballast_bytes) - MiB(r.base.current[kPrivateBytes])) + ")");
    Check(std::fabs(r.ballast_charge_mib[kPrivateBytes] - MiB(r.raised.current[kPrivateBytes] -
                                                                r.before.current[kPrivateBytes])) < kTol &&
              r.ballast_charge_mib[kPrivateBytes] > MiB(r.ballast_bytes),
          "mc 4 shape: the private-bytes charge is step 1's measured rise, " + F(r.ballast_charge_mib[kPrivateBytes]) +
              " MiB, above the ballast's " + F(MiB(r.ballast_bytes)) + " MiB of bytes");
    Check(std::fabs(r.ballast_charge_mib[kWorkingSet] - MiB(r.ballast_bytes)) < kTol,
          "mc 4 shape: the working-set charge is the ballast's bytes, as the dev box reads it (+0.00)");
  }

  // 2. Accept and refuse at the (c) private-bytes bound, 479.3 MiB (moved on
  //    an independent reading, P:2817-2819; see the reader). A product at
  //    479.2 MiB under a 600.3 MiB ballast is accepted (the bytes-only
  //    formula reads it about 1.17 MiB high and refuses it); a product at
  //    479.4 is refused (the correction takes none of the product's own
  //    footprint).
  {
    const LegReading under = Leg(Pages(634.8), Pages(633.2), 0, Pages(600.3), 512.0, Pages(479.2), 0);
    const Grade gu = GradeSteady(under, kPrivateBytes, kBatchSteadyBoundMiB);
    Check(gu.verdict == Verdict::kPass, "(c) private bytes: a 479.2 MiB product under the ballast reads " +
                                            F(gu.reading_mib, 2) + " and is " + V(gu.verdict) + " against 479.3 (expected accepted)");
    const LegReading over = Leg(Pages(634.8), Pages(633.2), 0, Pages(600.3), 512.0, Pages(479.4), 0);
    const Grade go = GradeSteady(over, kPrivateBytes, kBatchSteadyBoundMiB);
    Check(go.verdict == Verdict::kFail, "(c) private bytes: a 479.4 MiB product under the ballast reads " +
                                            F(go.reading_mib, 2) + " and is " + V(go.verdict) + " against 479.3 (expected refused)");
    // (b) at mc 1: 653 MiB ballast, bound 120.
    const LegReading b_under = Leg(Pages(640.0), Pages(645.0), 0, Pages(653.0), 512.0, Pages(119.9), 0);
    const Grade gbu = GradeSteady(b_under, kPrivateBytes, kLongSteadyBoundMiB);
    Check(gbu.verdict == Verdict::kPass, "(b) private bytes: a 119.9 MiB product under a 653 MiB ballast reads " +
                                             F(gbu.reading_mib, 2) + " and is " + V(gbu.verdict) +
                                             " against 120.0 (expected accepted)");
    const LegReading b_over = Leg(Pages(640.0), Pages(645.0), 0, Pages(653.0), 512.0, Pages(120.1), 0);
    const Grade gbo = GradeSteady(b_over, kPrivateBytes, kLongSteadyBoundMiB);
    Check(gbo.verdict == Verdict::kFail, "(b) private bytes: a 120.1 MiB product under a 653 MiB ballast reads " +
                                             F(gbo.reading_mib, 2) + " and is " + V(gbo.verdict) +
                                             " against 120.0 (expected refused)");
  }

  // 3. The charge is measured per run, not assumed: a counter charging 1/464
  //    (the dev box's calibration ratio if all +1.41 MiB were the ballast's)
  //    and one charging nothing both read the product's growth exactly.
  for (double div : {464.0, 0.0}) {
    const LegReading r = Leg(Pages(634.8), Pages(633.2), 0, Pages(654.3), div, Pages(64.0), 0);
    Check(std::fabs(r.steady_mib[kPrivateBytes] - 64.0) < kTol,
          std::string("a 64 MiB kept block under a 654.3 MiB ballast charging ") +
              (div > 0 ? "1/" + F(div, 0) : std::string("no overhead")) + " reads " +
              F(r.steady_mib[kPrivateBytes]) + " MiB of private bytes");
  }

  // 4. What the product retained between the base reading and the ballast
  //    step stays in steady (mc 1: a 5-token encode's 3.5 MiB buffer, if kept).
  {
    const uint64_t drift = Pages(3.5);
    const LegReading r = Leg(Pages(640.0), Pages(645.0), drift, Pages(653.0), 512.0, Pages(100.0), 0);
    Check(std::fabs(r.steady_mib[kPrivateBytes] - 103.5) < kTol && std::fabs(r.steady_mib[kWorkingSet] - 103.5) < kTol,
          "a 3.5 MiB retained before the ballast step reads in steady on both counters (" +
              F(r.steady_mib[kWorkingSet]) + ", " + F(r.steady_mib[kPrivateBytes]) + "; want 103.500)");
  }

  // 5. The excursion is unchanged by the charge: peak after - raised current.
  {
    LegReading r = Leg(Pages(634.8), Pages(633.2), 0, Pages(600.3), 512.0, Pages(448.0), 0);
    r.after.peak[kPrivateBytes] = r.raised.current[kPrivateBytes] + Pages(717.6);
    ComputeStep3(&r);
    Check(std::fabs(r.excursion_mib[kPrivateBytes] - MiB(Pages(717.6))) < kTol,
          "the excursion reads the peak above the raised floor, " + F(r.excursion_mib[kPrivateBytes]) +
              " MiB, with no charge applied");
  }

  std::printf("u2_9_c62_reader_steady: %s\n", g_fail ? "FAIL" : "PASS");
  return g_fail ? 1 : 0;
}
