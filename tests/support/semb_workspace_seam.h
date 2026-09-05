#ifndef SEMB_WORKSPACE_SEAM_H
#define SEMB_WORKSPACE_SEAM_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Test-only declarations. Builder definitions belong in the guarded adapter at
 * the acquired-and-held workspace point. Arm parks the next count successful
 * process-wide acquisitions, holding workspace and encoder leases. Returns 0
 * without changing state if any caller is parked. */
int32_t semb_test_seam_arm_park(uint32_t count);
uint32_t semb_test_seam_parked(void);
/* Condition-variable wait: 1 for at least n parked, 0 on timeout. */
int32_t semb_test_seam_wait_parked(uint32_t n, uint32_t timeout_ms);
/* Release every park, clear remaining budget, advance release generation. */
void semb_test_seam_release(void);
/* Monotonic count in epoch; startup is zero; arm/release preserve the count. */
uint64_t semb_test_seam_acquisitions(void);
/* Precondition: workers/helpers joined. Refuses unchanged while parked;
 * otherwise clears budget/count and advances release generation. */
int32_t semb_test_seam_reset(void);
#ifdef __cplusplus
}
#endif
#endif
