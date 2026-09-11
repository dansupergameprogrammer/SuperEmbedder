#ifndef SEMB_BANK_OPEN_SEAM_H
#define SEMB_BANK_OPEN_SEAM_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* TE-237 (S-3, D-SLM6642): test-only declarations for parking a materializing
 * `semb_bank_open` at its snapshot-materialization point.  The builder-side
 * definitions belong in src/superembedder/bank.cpp under
 * `#ifdef SEMB_ENABLE_WORKSPACE_TEST_SEAM` (so they exist only in the
 * `superembedder_testseam` mirror, never in the shipped library), exactly as
 * the workspace seam's own definitions live under the same guard in the
 * guarded adapter.  The exact hook contract -- park-point placement, call
 * count, and lock-held semantics -- is stated in full in
 * tests/te237_bank_cross_handle_test.cpp's header comment; this header carries
 * only the surface, mirroring support/semb_workspace_seam.h's shape.
 *
 * Arm parks the next `count` semb_bank_open calls that reach snapshot
 * materialization.  Returns 0 without changing state if any thread is
 * currently parked at the park point. */
int32_t semb_bank_test_seam_arm_snapshot_park(uint32_t count);
/* Threads currently parked at the materialization park point. */
uint32_t semb_bank_test_seam_snapshot_parked(void);
/* Condition-variable wait: 1 for at least n parked, 0 on timeout. */
int32_t semb_bank_test_seam_snapshot_wait_parked(uint32_t n, uint32_t timeout_ms);
/* Release every parked materialization, clear remaining budget, advance the
 * release generation. */
void semb_bank_test_seam_snapshot_release(void);
/* Precondition: workers joined.  Refuses (returns 0) while any thread is
 * parked; otherwise clears budget/count and advances the release generation. */
int32_t semb_bank_test_seam_snapshot_reset(void);
#ifdef __cplusplus
}
#endif
#endif