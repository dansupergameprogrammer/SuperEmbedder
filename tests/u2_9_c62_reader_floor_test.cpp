// tests/u2_9_c62_reader_floor_test.cpp -- U2 cloud build, U2-9's C62: the
// floor precondition (P:2733-2734, "so the floor is above every earlier
// peak"), at the comparison level, on every platform. The test author's own
// check of C62's reader; the adversary's constructions are separate.
//
// FloorAboveEarlierPeaks(before, raised) must accept a raised current value
// at or above the pre-ballast peak on both counters, including the case the
// dev box reads on Windows (the raised peak a few pages above the raised
// current value), and must refuse a raised current value below the earlier
// peak on either counter by as little as one byte, or an absent reading.
// Mutation proof: the previous rule (raised.peak == raised.current) refuses
// the Windows case, and a rule with no earlier-peak comparison accepts the
// one-byte-below cases; each is a FAIL line here.
#include <cstdio>
#include <string>

#include "u2_9_c62_reader.h"

using namespace semb_c62;

namespace {
int g_fail = 0;
void Expect(bool got, bool want, const std::string& what) {
  const bool ok = got == want;
  if (!ok) ++g_fail;
  std::printf("[%s] floor precondition %s: %s (want %s)\n", ok ? "PASS" : "FAIL", what.c_str(),
              got ? "accepted" : "refused", want ? "accepted" : "refused");
}
constexpr uint64_t kMiBBytes = 1048576;
Counters Make(uint64_t ws, uint64_t ws_peak, uint64_t pb, uint64_t pb_peak) {
  Counters r;
  r.ok = true;
  r.current[kWorkingSet] = ws;
  r.peak[kWorkingSet] = ws_peak;
  r.current[kPrivateBytes] = pb;
  r.peak[kPrivateBytes] = pb_peak;
  return r;
}
}  // namespace

int main() {
  // Before the ballast: TE-398-like mc 1 shape, peaks ~600 MiB above current.
  const uint64_t ws0 = 642 * kMiBBytes, ws_peak0 = 1233 * kMiBBytes;
  const uint64_t pb0 = 647 * kMiBBytes, pb_peak0 = 1240 * kMiBBytes;
  const Counters before = Make(ws0, ws_peak0, pb0, pb_peak0);
  const uint64_t ballast = (pb_peak0 - pb0) + kMiBBytes;  // the larger gap + 1 MiB

  // Accept: the healthy step, peak == current (the plan's literal case).
  {
    const Counters r = Make(ws0 + ballast, ws0 + ballast, pb0 + ballast, pb0 + ballast);
    Expect(FloorAboveEarlierPeaks(before, r), true, "raised peak equals raised current");
  }
  // Accept: the dev box's Windows case, the raised peak 0.09 MiB above the
  // raised current value on both counters, the current well above every
  // earlier peak.
  {
    const uint64_t d = 92160;  // 22.5 pages of 4 KiB
    const Counters r = Make(ws0 + ballast - d, ws0 + ballast, pb0 + ballast - d, pb0 + ballast);
    Expect(FloorAboveEarlierPeaks(before, r), true, "raised peak 0.09 MiB above raised current (Windows)");
  }
  // Accept: the boundary, raised current exactly at the earlier peak.
  {
    const Counters r = Make(ws_peak0, ws_peak0 + 4096, pb_peak0, pb_peak0 + 4096);
    Expect(FloorAboveEarlierPeaks(before, r), true, "raised current exactly at the earlier peak, both counters");
  }
  // Refuse: one byte below the earlier peak, working set only.
  {
    const Counters r = Make(ws_peak0 - 1, ws_peak0 + 4096, pb_peak0 + kMiBBytes, pb_peak0 + kMiBBytes);
    Expect(FloorAboveEarlierPeaks(before, r), false, "working set 1 B below its earlier peak");
  }
  // Refuse: one byte below the earlier peak, private bytes only.
  {
    const Counters r = Make(ws_peak0 + kMiBBytes, ws_peak0 + kMiBBytes, pb_peak0 - 1, pb_peak0 + 4096);
    Expect(FloorAboveEarlierPeaks(before, r), false, "private bytes 1 B below its earlier peak");
  }
  // Refuse: a trimmed working set after the ballast, raised peak == raised
  // current but both below the earlier peak (the old rule accepted this).
  {
    const Counters r = Make(ws_peak0 - 64 * kMiBBytes, ws_peak0 - 64 * kMiBBytes, pb0 + ballast, pb0 + ballast);
    Expect(FloorAboveEarlierPeaks(before, r), false, "peak == current but 64 MiB below the earlier peak");
  }
  // Refuse: a ballast too small to clear the earlier peak.
  {
    const Counters r = Make(ws0 + 100 * kMiBBytes, ws_peak0, pb0 + 100 * kMiBBytes, pb_peak0);
    Expect(FloorAboveEarlierPeaks(before, r), false, "a ballast that does not reach the earlier peak");
  }
  // Refuse: an absent reading on either side.
  {
    Counters r = Make(ws0 + ballast, ws0 + ballast, pb0 + ballast, pb0 + ballast);
    Counters b = before;
    b.ok = false;
    Expect(FloorAboveEarlierPeaks(b, r), false, "no pre-ballast reading");
    r.ok = false;
    Expect(FloorAboveEarlierPeaks(before, r), false, "no raised reading");
  }
  // The gate: a leg whose floor failed emits no verdict (GradeExcursion).
  {
    LegReading leg;
    leg.base = before;
    leg.after = before;
    leg.raised = before;
    leg.ballasted = leg.ballast_committed = leg.resident_ok = true;
    leg.floor_ok = false;
    leg.excursion_mib[kWorkingSet] = 1.0;
    const bool none = GradeExcursion(leg, kWorkingSet, 189.5).verdict == Verdict::kNoVerdict;
    Expect(!none, false, "leg with floor_ok = false grades (must be NO VERDICT)");
    leg.floor_ok = true;
    const bool pass = GradeExcursion(leg, kWorkingSet, 189.5).verdict == Verdict::kPass;
    Expect(pass, true, "leg with floor_ok = true grades PASS under the bound");
  }
  std::printf("u2_9_c62_reader_floor: %s\n", g_fail ? "FAIL" : "PASS");
  return g_fail ? 1 : 0;
}
