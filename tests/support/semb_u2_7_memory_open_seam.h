#ifndef SEMB_U2_7_MEMORY_OPEN_SEAM_H
#define SEMB_U2_7_MEMORY_OPEN_SEAM_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* U2 cloud build: the test seam C52 (d) needs (te267 sec 5 U2-7, "C52 (d),
 * the in-call rewrite"). Test-only declarations, defined by the builder with
 * U2-7 item 1 under SEMB_ENABLE_WORKSPACE_TEST_SEAM, so they exist only in the
 * `superembedder_testseam` mirror, never in the shipped library.
 *
 * The park point sits in `semb_encoder_open_memory`, after the owned copies
 * of both spans are digested and before the interim open loads them. Armed,
 * the next memory open parks there until released; while it is parked, the
 * test overwrites both caller spans with 0xFF.
 *
 * Builder obligation: define these three and call the park point there. */
/* Park the next memory open at the park point. 0 if one is already parked. */
int32_t semb_test_seam_memory_open_arm_park(void);
/* 1 once a memory open is parked there, 0 on timeout. */
int32_t semb_test_seam_memory_open_wait_parked(uint32_t timeout_ms);
/* Release the parked open (and disarm). */
void semb_test_seam_memory_open_release(void);
#ifdef __cplusplus
}
#endif
#endif
