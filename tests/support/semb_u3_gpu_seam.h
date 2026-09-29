#ifndef SEMB_U3_GPU_SEAM_H
#define SEMB_U3_GPU_SEAM_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* U3 red suite (te266 sec 4.2, "The adapter-boundary test seam", P:4067-4076):
 * the test-only C surface of the GPU adapter's engine function table. Test-only
 * declarations; the test author's names. Every definition sits under
 * SEMB_ENABLE_WORKSPACE_TEST_SEAM, so it exists only in the
 * `superembedder_testseam` mirror, never in the shipped `superembedder`
 * (C14's absent-symbol check, P:4076; tests/u3_gpu_seam_absent_check.py).
 *
 * Every symbol is prefixed `semb_test_seam_`, so K-18
 * (tests/u1_workspace_seam_absent_check.py) also reads its absence from the
 * shipped archive.
 *
 * Where each lives (builder's items, te266 sec 4.7 step 3, P:4263-4275):
 *   - semb_test_seam_gpu_*          engine_adapter_gpu.cpp (SEMB_BUILD_GPU=ON only);
 *   - semb_test_seam_ps_n_select_count  engine_adapter_interim.cpp (every build).
 *
 * `enc` below is a public `semb_encoder` passed as `const void*`, so this
 * header composes with the product's semb.h or the suite's contract header. */

/* ---- capability 1: the call log (P:4068) ----------------------------------
 * One record per call U3 makes into the GPU engine, in call order, from every
 * handle in the process. `verb` is the engine function's own name
 * ("sslm_gpu_context_create", "sslm_gpu_model_map", "sslm_gpu_seq_create",
 * "sslm_gpu_seq_release", "sslm_gpu_seq_reset",
 * "SslmGpuSeqPrefillPromptForG5Bridge",
 * "sslm_gpu_seq_read_prefill_final_hidden", "sslm_gpu_model_hidden_size",
 * "sslm_gpu_model_unmap", "sslm_gpu_context_destroy"); `status` is the name of
 * the SslmGpuStatus it returned ("SSLM_OK", "SSLM_DEVICE_LOST", ...), or of
 * the injected status. `index` is the running call count at this call
 * (1-based; semb_test_seam_gpu_call_count() after it). `arg` is the call's
 * size argument: the token count for the prompt prefill, the context cap for
 * a sequence create, 0 otherwise (C10 (g) and C11 read positions from it,
 * P:4169, P:4195). `handle` is the public handle whose call made it, as the
 * `semb_encoder` value (0 for none). `injected` is 1 when capability 2
 * returned the status without calling the engine. */
typedef struct semb_test_seam_gpu_call {
  char verb[48];
  char status[48];
  uint64_t index;
  uint64_t arg;
  uint64_t handle;
  int32_t injected;
} semb_test_seam_gpu_call;
/* The running count of engine calls made (injected calls included). */
uint64_t semb_test_seam_gpu_call_count(void);
/* Copies up to `cap` records starting at 0-based record `first`; returns the
 * total number of records held. */
uint64_t semb_test_seam_gpu_call_log(semb_test_seam_gpu_call* out, uint64_t first, uint64_t cap);
/* Clears the records and zeroes the running count. Returns 0 (and clears
 * nothing) while any thread is inside an engine call. */
int32_t semb_test_seam_gpu_call_log_reset(void);

/* ---- capability 2: status injection (P:4069) ------------------------------
 * The `nth` (1-based) call of `verb` made after this call returns the status
 * named `status_name` without calling the engine, and is logged with
 * injected = 1. Returns 1 when armed; 0 when the verb or status name is
 * unknown. Several arms may be pending at once; each fires once. */
int32_t semb_test_seam_gpu_inject(const char* verb, uint64_t nth, const char* status_name);
/* Drops every pending arm; returns how many had not fired. */
uint64_t semb_test_seam_gpu_inject_clear(void);

/* ---- capability 3: the lock-held assertion (P:4070) -----------------------
 * Every entry to the function table checks that the calling thread holds the
 * process-wide submission lock; each entry that does not is counted here.
 * A cell fails when it reads a nonzero count. Reset with the call log. */
uint64_t semb_test_seam_gpu_lock_violations(void);

/* ---- capability 4: the occupancy maximum (P:4071) -------------------------
 * The most threads ever inside an engine call at once, across every handle in
 * the process, since the last reset. */
uint32_t semb_test_seam_gpu_occupancy_max(void);
void semb_test_seam_gpu_occupancy_reset(void);
/* The same counter's current value: threads inside an engine call right now.
 * The test author's addition to capability 4, read by the allocation hooks
 * of tests/u3_gpu_alloc_test.cpp and tests/u3_c64_gpu_leg_test.cpp at the
 * moment they fail an allocation, to place k inside an engine call or in
 * U3's own frames (te267 P:3757). It and semb_test_seam_gpu_call_count are
 * called from inside a replaced operator new, so both must be a single
 * atomic load: no allocation, no lock. */
uint32_t semb_test_seam_gpu_occupancy_now(void);

/* ---- capability 5: the engine-context count (P:4072, P:4083) --------------
 * Engine contexts the adapter boundary holds: +1 when sslm_gpu_context_create
 * returns SSLM_OK, -1 only when sslm_gpu_context_destroy returns SSLM_OK. */
int64_t semb_test_seam_gpu_context_count(void);

/* ---- capability 6: the GPU slot-record count (P:4073, P:4085) -------------
 * GPU slot records the handle has created (records are created on
 * acquisition, never sized at open). The bound is max(1, max_concurrency) as
 * the handle stores it. Both read 0 for a handle that is not a GPU handle. */
uint64_t semb_test_seam_gpu_slot_record_count(const void* enc);
uint64_t semb_test_seam_gpu_slot_bound(const void* enc);

/* ---- capability 7: the submission-lock try-lock (P:4074) ------------------
 * Tries the process-wide lock from the calling thread without waiting,
 * releases it at once if taken, and returns 1 if it was free, 0 if held. */
int32_t semb_test_seam_gpu_try_lock(void);

/* ---- C10 (e)'s perturbation seam (P:4160-4167) ----------------------------
 * Not one of sec 4.2's seven; C10 (e) 1 and 4 name "a test seam between the
 * read verb and the agreement check" and (e) 2 the same perturbation "after
 * the agreement check".
 *   where    0: applied to the read's triple before the agreement check
 *               compares it (open only);
 *            1: applied to every encode's triple after the check (after
 *               open), before dequantize.
 *   target   0: codes[code_index] += 1 (two's-complement wrap on int8);
 *            1: the scale mantissa m += 1, codes untouched.
 *   sequence where 0: the agreement check's sequence index, 0-15 the W-B
 *            documents in corpus order, 16-21 the W-Q queries in order (21 is
 *            the truncation query); where 1: ignored.
 * One arm at a time; semb_test_seam_gpu_perturb_disarm returns 1 if it fired. */
void semb_test_seam_gpu_arm_perturb(int32_t where, int32_t target, int32_t sequence, uint32_t code_index);
int32_t semb_test_seam_gpu_perturb_disarm(void);
/* The internal channel of the last refused agreement check (P:4108): the
 * sequence index (0-21) whose GPU triple differed first, or -1 when the last
 * check found none. Process-wide: a refused open leaves no handle. */
int32_t semb_test_seam_gpu_last_diverged_sequence(void);
/* The triple of the most recent read that returned SSLM_OK, after any
 * where=1 perturbation (what dequantize received). Copies min(width,
 * capacity) codes; returns 1, or 0 when no read has succeeded. */
int32_t semb_test_seam_gpu_last_read(int8_t* out_codes, size_t capacity, size_t* out_width,
                                     int64_t* out_m, int64_t* out_e);

/* ---- sec 4.6 row 11's witness-triple counter (P:4221, T388-11) ------------
 * Process-wide count of calls to semb_interim_ps_n_select (the C verb, every
 * caller). Lives in engine_adapter_interim.cpp, so it exists in the
 * SEMB_BUILD_GPU=OFF testseam too. */
uint64_t semb_test_seam_ps_n_select_count(void);

#ifdef __cplusplus
}
#endif
#endif
