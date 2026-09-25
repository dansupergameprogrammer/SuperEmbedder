#ifndef SEMB_U2_MEMORY_SEAM_H
#define SEMB_U2_MEMORY_SEAM_H
#include <stdint.h>
#include "superembedder/encoder_interim_abi.h"
#ifdef __cplusplus
extern "C" {
#endif
/* U2 cloud build, the seam commit (te267 sec 6.1 step 1; U2-9 Builds item 9,
 * U2-10 Builds item 2c). Test-only declarations. Every definition sits under
 * SEMB_ENABLE_WORKSPACE_TEST_SEAM in src/superembedder/engine_adapter_interim.cpp
 * (and one accessor in encoder.cpp), so it exists only in the
 * `superembedder_testseam` mirror, never in the shipped library.
 *
 * On today's pool (before U2-9's build) each reader reads today's state: the
 * record count is the pool's size, each capacity is P * context_cap, and the
 * model buffer holds the artifact. The fill, forced-reference and growth-fail
 * arms have nothing to act on, because nothing grows; the gate hooks never
 * fire, because no gate exists. The poison arm and the spawn fail arm act on
 * today's code.
 *
 * Builder obligations at U2-9's build (the C++ hooks named in the adapter's
 * `semb::test_seam` namespace): call BeforeSlotGrowth(C, current_capacity)
 * inside the new buffer's allocation step (it may throw std::bad_alloc: the
 * growth fail arm) and AfterSlotGrowth(data, bytes) after it; read
 * ForcedReferenceArmed() where C is chosen; call OnGateWaitBegin/End around a
 * wait for the long-document gate, OnGateTaken(capacity) as the gate is taken
 * (before the growth), OnGateHolding() after the holder's buffer has grown
 * and before its forward runs (the park point), OnGateGiveBack(capacity) as
 * the gate is given back; keep PoisonAt()'s context_cap argument equal to
 * the cap the forward receives; and move OnWorkerStart() into StartWorker
 * (U2-10 Builds item 2c). */

/* ---- readers (U2-9 item 9) ---- */
/* The public handle's interim encoder, so the readers below apply to it.
 * `enc` is a `semb_encoder` (void* here, so this header composes with either
 * the product's semb.h or the suite's own contract header). */
SembInterimEncoder* semb_test_seam_interim_of(const void* enc);
/* Slot records the handle holds. */
uint64_t semb_test_seam_slot_record_count(const SembInterimEncoder* enc);
/* 1 and the capacity of record `index`'s buffer, or 0 if no such record. */
int32_t semb_test_seam_slot_capacity(const SembInterimEncoder* enc, uint64_t index,
                                     uint64_t* out_capacity_bytes);
/* The capacity of the product's own copy of the model bytes. */
uint64_t semb_test_seam_model_buffer_capacity(const SembInterimEncoder* enc);
/* Process-wide count of slot growths (readable without a handle). */
uint64_t semb_test_seam_slot_growths(void);

/* ---- arms (U2-9 item 9) ---- */
/* Fill every newly grown buffer with `byte` (0..255); -1 disarms. */
void semb_test_seam_arm_fill(int32_t byte);
/* Nonzero forces today's rule: C = context_cap with a zeroed buffer. */
void semb_test_seam_arm_forced_reference(int32_t on);
/* The next slot growth to a C >= min_c throws std::bad_alloc in place of the
 * new buffer's allocation; 0 disarms. One shot. */
void semb_test_seam_arm_growth_fail(uint64_t min_c);
/* 1 if the growth fail arm fired since it was armed, with the slot's buffer
 * capacity at the moment it fired. */
int32_t semb_test_seam_growth_fail_fired(uint64_t* out_capacity_at_fire);
/* Poison: when the forward of one document reaches position `split` (the
 * start of the chunk-batched call at offset `split`, or the per-token
 * position `split`), overwrite the K rows of positions [pos_begin, pos_end)
 * (clamped to the forward's context cap), in every layer and KV head, with
 * `byte`. One shot. */
void semb_test_seam_arm_poison(uint64_t split, uint64_t pos_begin, uint64_t pos_end, uint8_t byte);
/* Disarm the poison arm; returns 1 if it fired since it was armed. */
int32_t semb_test_seam_poison_disarm(void);

/* ---- the long-document gate (U2-9 items 6 and 9) ---- */
/* Park the next `count` holders at the gate's park point. 0 if any parked. */
int32_t semb_test_seam_gate_arm_park(uint32_t count);
int32_t semb_test_seam_gate_wait_parked(uint32_t n, uint32_t timeout_ms);
uint32_t semb_test_seam_gate_parked(void);
void semb_test_seam_gate_release(void);
uint32_t semb_test_seam_gate_holders(void);
uint32_t semb_test_seam_gate_high_water(void);
uint32_t semb_test_seam_gate_waiters(void);
/* Ordered records: each slot's capacity as it took the gate (before it grew)
 * and as it gave the gate back. Returns the record count; copies up to cap. */
uint64_t semb_test_seam_gate_take_records(uint64_t* out, uint64_t cap);
uint64_t semb_test_seam_gate_give_records(uint64_t* out, uint64_t cap);
/* Clear every gate record, counter and budget. 0 while any holder is parked. */
int32_t semb_test_seam_gate_reset(void);

/* ---- C66's spawn fail arm (U2-10 Builds item 2c) ---- */
/* Armed with k, the k-th worker start of the next batch in the process throws
 * std::system_error(resource_unavailable_try_again) in place of starting the
 * thread; 0 disarms. */
void semb_test_seam_arm_spawn_fail(uint32_t k);
/* 1 if the arm fired since armed; *out_starts_after is the count of worker
 * starts attempted after it in the same call. */
int32_t semb_test_seam_spawn_fail_fired(uint32_t* out_starts_after);
#ifdef __cplusplus
}
#endif
#endif
