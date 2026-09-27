// tests/u2_9_c62_reader.h -- U2 cloud build, U2-9's C62 (te267 sec 5 U2-9,
// C62, P:2720-2826): C62's reading and comparison code. Windows only: it reads
// GetProcessMemoryInfo's WorkingSetSize and PrivateUsage (and their peaks,
// PeakWorkingSetSize and PeakPagefileUsage) and QueryWorkingSetEx. On any
// other platform PlatformSupported() is false and every reading reports
// ok = false; the file still compiles, so GCC checks everything but the
// Win32 bodies.
//
// This is the whole of C62's instrument: the C62 process
// (u2_9_c62_process.h, u2_9_c62_resident_memory_test.cpp) reads and grades
// through these functions and nothing else, and a process C62 did not create
// -- the adversary's calibration processes (P:2806-2810) -- links the same
// library (CMake target u2_9_c62_reader; no product library needed) and runs
// the same steps on its own footprint.
//
// ENTRY POINTS FOR A CALIBRATION PROCESS (P:2806-2810)
//   (a)  hold a footprint, then
//          Counters r = Read();
//          Grade g = GradeOpen(r, mc, kWorkingSet);   // and kPrivateBytes
//        or GradeAtMost(MiB(r.current[c]), bound, r.ok) for any stated bound.
//        OpenBoundMiB(mc, c) is P:2757-2760's table.
//   (b), (c)  the excursion above a raised floor:
//          Counters base = Read();                    // the "post-open" reading
//          LegReading leg = MeasureExcursionLeg(base, [&] { touch and free a block; return true; });
//          GradeExcursion(leg, kWorkingSet, bound)    // and kPrivateBytes
//          GradeSteady(leg, kWorkingSet, bound)       // steady, graded separately
//        leg.excursion_mib[c] reads the block; leg.steady_mib[c] reads what the
//        action left committed (or resident) after it returned. The two are
//        separate fields with separate grades, so a construction can drive
//        either one alone. For finer control the three steps are exported:
//        BeginExcursion (step 1: size, commit and touch the ballast, re-read,
//        check the floor), the action, EndExcursion (steps 2-4: read, check
//        every ballast page resident, compute, release the ballast).
//
// WHAT THE STEPS ARE (P:2731-2741)
//   1. Read both current values and both peaks. Commit and touch a ballast
//      block 1 MiB larger than the larger of the two gaps (peak - current),
//      rounded up to a page, every page written with distinct bytes (so page
//      combining cannot merge them), and read again. PRECONDITION (P:2733-
//      2734, "each peak now equals its current value, so the floor is above
//      every earlier peak"): each counter's raised current value is at or
//      above that counter's peak before the ballast, i.e. the floor is above
//      every earlier peak; otherwise the leg emits no verdict. See
//      FloorAboveEarlierPeaks for why this, and not byte equality of the
//      raised peak and current value, is the tested property.
//   2. Run the action, then read both peaks and both current values.
//   3. Excursion = each peak (after) - its pre-action value (the raised
//      floor). Steady = each current value (after) - the ballast's size -
//      the base ("post-open") reading's current value, where the ballast's
//      size is taken ON EACH COUNTER, as step 1's two readings measure it in
//      this run: raised.current - before.current. The ballast is the
//      instrument, the raised floor (P:2731-2732, P:2736-2738), not the
//      product, so what holding it costs is
//      subtracted whole. On Windows that is more than its bytes: private
//      bytes also carry the ballast's own page tables, about 1/512 of it
//      (the dev box read a kept 64 MiB block as 65.4 MiB of private bytes
//      under a 654.3 MiB ballast when steady subtracted only the bytes, and
//      64.0 of working set). A constant would be a fudge; the charge is read
//      per run, per counter, from the readings step 1 already takes.
//      Algebraically steady = (after - raised) + (before - base): the growth
//      across the action plus anything the product retained between the
//      base reading and the ballast step (mc 1's 5-token encode). The
//      product's own page tables are not subtracted: they are footprint.
//      Between `before` and `raised` this code commits nothing but the
//      ballast and the action has not started, so the subtraction takes
//      none of the product's growth unless a product thread commits memory
//      while no call is in progress (none is expected; not measured). The
//      charge and its excess over the ballast's bytes are printed with each
//      leg, so an excess far from 1/512 is visible in the log.
//   4. PRECONDITION: every ballast page is still resident after the action
//      (QueryWorkingSetEx, every page Valid); otherwise no verdict.
//
// THE INSTRUMENT'S OWN FOOTPRINT. Between the base reading and the last
// reading of a leg, this code commits nothing but the ballast. The
// QueryWorkingSetEx buffer is a fixed static array touched by
// InitInstrument(), which a process calls once before its base reading
// (MeasureExcursionLeg and BeginExcursion call it too; it is idempotent).
// No heap allocation happens inside a leg.
#ifndef SEMB_U2_9_C62_READER_H
#define SEMB_U2_9_C62_READER_H

#include <cstdint>
#include <cstdio>

namespace semb_c62 {

enum Counter : int { kWorkingSet = 0, kPrivateBytes = 1 };
constexpr int kCounters = 2;
const char* CounterName(Counter c);  // "working set" / "private bytes"

constexpr double kMiB = 1048576.0;
inline double MiB(uint64_t bytes) { return static_cast<double>(bytes) / kMiB; }

// ---- the bounds (P:2753-2785), in MiB, each stated for both counters ----
// (a): P:2757-2760's table. 0 for an mc the table does not state.
double OpenBoundMiB(uint32_t max_concurrency, Counter c);
// (b), mc 1: the 5-token encode (n = 6, C = 64): steady <= post-open + 3.5 + 8.
constexpr double kShortSteadyBoundMiB = 3.5 + 8.0;
// (b), mc 1: the 1,111-token encode (n = 1,112, C = 2,048).
constexpr double kLongSteadyBoundMiB = 112.0 + 8.0;
constexpr double kLongExcursionBoundMiB = 112.0 + 69.5 + 8.0;  // 189.5
// (c), mc 4: semb_encode_batch over four copies of the 1,111-token text.
constexpr double kBatchSteadyBoundMiB = 448.0 + 8.0;
constexpr double kBatchExcursionBoundMiB = 448.0 + 4.0 * 69.5 + 8.0;  // 734.0

// ---- readings ----
struct Counters {
  bool ok = false;               // false: the platform call failed or is absent
  uint64_t current[kCounters]{};  // WorkingSetSize, PrivateUsage
  uint64_t peak[kCounters]{};     // PeakWorkingSetSize, PeakPagefileUsage
};

bool PlatformSupported();
// Touches the static QueryWorkingSetEx buffer and caches the page size. Call
// once before the base reading. Idempotent.
void InitInstrument();
Counters Read();
// Commits and touches `bytes` (rounded up to a page) of private memory,
// every page distinct. Returns nullptr on failure. For callers that hold a
// footprint (a calibration process); C62 itself uses it only for the ballast.
void* CommitAndTouch(uint64_t bytes, uint64_t* out_committed_bytes);
void Release(void* base);
uint64_t PageSize();

// ---- one leg ----
struct Ballast {
  void* base = nullptr;
  uint64_t bytes = 0;      // committed and touched (steady subtracts what it costs, step 3)
  Counters before;         // step 1's first reading
  Counters raised;         // step 1's second reading: the pre-action values
  bool floor_ok = false;   // precondition 1: FloorAboveEarlierPeaks(before, raised)
};

// Precondition 1 (P:2733-2734). True iff both readings are ok and, for each
// counter, raised.current >= before.peak: the pre-encode value (the floor)
// is at or above every peak the process reached before the ballast, so no
// earlier peak (the open's, a prior encode's) can enter the excursion.
//
// Why not raised.peak == raised.current, the plan's literal wording: the
// wording is the means, "so the floor is above every earlier peak" is the
// end. On Windows the raised peak exceeds the raised current value by a few
// pages (< 0.1 MiB, dev box, MSVC): the working set dips between the last
// ballast touch and the reading. Any such gap was reached during the ballast
// step itself, above every earlier peak, so it is not the open's history. It
// can only raise the excursion (peak after - raised current), never lower
// it, so it errs toward refusal; its size is printed with each leg
// (floor_gap_bytes). The comparison is exact, in bytes, with no slack: the
// ballast is 1 MiB larger than the larger gap, so a healthy step clears the
// earlier peak by about 1 MiB, and a raised current even one byte below an
// earlier peak is refused.
bool FloorAboveEarlierPeaks(const Counters& before, const Counters& raised);

struct LegReading {
  // Inputs and raw readings.
  Counters base;           // the post-open reading the steady value is taken against
  bool ballasted = false;  // false: a steady-only leg (no floor, no excursion)
  uint64_t ballast_bytes = 0;
  Counters before;         // step 1's first reading (ballasted legs)
  Counters raised;         // step 1's second reading (ballasted legs)
  Counters after;          // step 2's reading
  bool action_ok = false;  // what the action returned
  // Preconditions (ballasted legs). A leg with either false emits no verdict.
  bool ballast_committed = false;
  bool floor_ok = false;
  bool resident_ok = false;
  // raised.peak - raised.current per counter (0 if the peak is not above it):
  // reported, not gated; see FloorAboveEarlierPeaks.
  uint64_t floor_gap_bytes[kCounters]{};
  uint64_t nonresident_pages = 0;
  // Step 3, in MiB, per counter. Excursion is defined only on ballasted legs.
  // ballast_charge_mib: what the ballast step raised each counter by,
  // raised.current - before.current, measured in this run; steady subtracts
  // it (see step 3 in the header comment).
  double ballast_charge_mib[kCounters]{};
  double steady_mib[kCounters]{};
  double excursion_mib[kCounters]{};
  bool preconditions_hold() const {
    return base.ok && after.ok && (!ballasted || (ballast_committed && floor_ok && resident_ok && raised.ok));
  }
};

// Step 1. False if the ballast could not be committed (no verdict follows).
bool BeginExcursion(Ballast* b);
// Steps 2-4 (step 2's reading is taken first, before anything else), and
// releases the ballast. `b` may be one whose BeginExcursion failed: the leg
// then reads ballast_committed = false and emits no verdict.
void EndExcursion(Ballast* b, const Counters& base, bool action_ok, LegReading* out);

// Step 3 alone, on a ballasted leg's raw readings: fills ballast_charge_mib,
// excursion_mib and steady_mib from base, before, raised and after. No
// platform call, so the comparison-level tests drive it on every platform;
// EndExcursion calls it and nothing else computes step 3.
void ComputeStep3(LegReading* r);

// Steps 1-4 around `action` (any callable returning bool; no heap use).
template <class Action>
LegReading MeasureExcursionLeg(const Counters& base, Action&& action) {
  InitInstrument();
  Ballast b;
  const bool committed = BeginExcursion(&b);
  const bool ok = committed ? static_cast<bool>(action()) : false;
  LegReading r;
  EndExcursion(&b, base, ok, &r);
  return r;
}

// A steady-only leg (P:2766-2768: the 5-token encode has a steady bound and
// no excursion bound): run the action, read, steady = current - base.
template <class Action>
LegReading MeasureSteadyLeg(const Counters& base, Action&& action) {
  InitInstrument();
  LegReading r;
  r.base = base;
  r.action_ok = static_cast<bool>(action());
  r.after = Read();
  for (int c = 0; c < kCounters; ++c)
    r.steady_mib[c] = MiB(r.after.current[c]) - MiB(base.current[c]);
  return r;
}

// ---- comparison ----
enum class Verdict { kPass, kFail, kNoVerdict };
struct Grade {
  Verdict verdict = Verdict::kNoVerdict;
  double reading_mib = 0;
  double bound_mib = 0;
};
// reading <= bound -> kPass; > bound -> kFail; preconditions false -> kNoVerdict.
Grade GradeAtMost(double reading_mib, double bound_mib, bool preconditions_hold);
// (a): the post-open current value against OpenBoundMiB(mc, c).
Grade GradeOpen(const Counters& post_open, uint32_t max_concurrency, Counter c);
Grade GradeSteady(const LegReading& leg, Counter c, double bound_mib);
// No verdict on a steady-only leg.
Grade GradeExcursion(const LegReading& leg, Counter c, double bound_mib);

// One verdict line: "[PASS] <cell> <counter>: <what> <reading> MiB <= <bound> MiB".
// Returns the verdict so a caller can tally it.
Verdict Report(std::FILE* out, const char* cell, Counter c, const char* what, const Grade& g);
// The raw readings of a leg, one line per counter.
void PrintLeg(std::FILE* out, const char* cell, const LegReading& leg);
void PrintCounters(std::FILE* out, const char* label, const Counters& r);

}  // namespace semb_c62

#endif  // SEMB_U2_9_C62_READER_H
