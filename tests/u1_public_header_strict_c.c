/* tests/u1_public_header_strict_c.c -- TE-94 (D-SLM6314 resolution, sec 7.1;
 * K-16): the public header compiles as STRICT C on every platform that
 * builds the library. This translation unit is compiled as an object on the
 * default build (tests/CMakeLists.txt: /TC /W4 /WX under MSVC and clang-cl;
 * -std=c99 -Wall -Wextra -Werror -pedantic under GCC/Clang/AppleClang), so a
 * C++-only construct entering include/superembedder/semb.h breaks
 * `cmake --build` on every CI job -- and tests/u1_public_header_strict_c_check.py
 * is the ctest cell that compiles this file by name against the real header
 * (must-accept) and against mutated copies carrying C++ syntax (must-reject,
 * each of which must FAIL to compile as C and compile as C++).
 *
 * Every public declaration is exercised so a declaration a C compiler
 * cannot parse, or a type it cannot size, fails HERE rather than only in a
 * consumer. Nothing is linked: this object references the five verbs through
 * function pointers, which the object file records as undefined symbols the
 * checker never resolves.
 */
#include "superembedder/semb.h"

#include <stddef.h>
#include <stdint.h>

typedef semb_status (*semb_open_fn)(const semb_config*, semb_encoder*);
typedef semb_status (*semb_close_fn)(semb_encoder);
typedef semb_status (*semb_dims_fn)(semb_encoder, uint32_t*);
typedef semb_status (*semb_encode_fn)(semb_encoder, const char*, size_t, float*, size_t, size_t*,
                                      semb_fingerprint*);
typedef const char* (*semb_name_fn)(semb_status);

/* Exported so the object carries a definition a linker would keep; the
 * checker compiles only. */
int semb_u1_public_header_strict_c_probe(void);

int semb_u1_public_header_strict_c_probe(void) {
  semb_open_fn open_fn = semb_encoder_open;
  semb_close_fn close_fn = semb_encoder_close;
  semb_dims_fn dims_fn = semb_encoder_dims;
  semb_encode_fn encode_fn = semb_encode;
  semb_name_fn name_fn = semb_status_name;
  semb_config cfg;
  semb_fingerprint fp;
  semb_encoder enc = NULL;
  semb_status ok = SEMB_OK;
  int sum = 0;

  cfg.struct_size = (uint32_t)sizeof(semb_config);
  cfg.model_path = NULL;
  cfg.model_path_len = 0;
  cfg.tokenizer_path = NULL;
  cfg.tokenizer_path_len = 0;
  cfg.max_concurrency = 0;
  fp.struct_size = (uint32_t)sizeof(semb_fingerprint);
  fp.digest[0] = 0;

  /* The five verbs are addressable; the sentinel is the enum's last value. */
  sum += open_fn != NULL;
  sum += close_fn != NULL;
  sum += dims_fn != NULL;
  sum += encode_fn != NULL;
  sum += name_fn != NULL;
  sum += (int)ok;
  sum += (int)SEMB_STATUS_NEXT_FREE;
  sum += (int)sizeof(fp.digest);
  sum += (int)SEMB_FINGERPRINT_PROVISIONAL_TAG_SIZE;
  sum += (int)(sizeof(SEMB_FINGERPRINT_PROVISIONAL_TAG) - 1u);
  sum += enc == NULL;
  return sum;
}
