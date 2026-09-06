// tests/c41_environment_invariance_test.cpp -- TE-144 (U1 slice 1): C41
// parts 1-3 (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C41: "the emitted
// bytes do not depend on the floating-point ENVIRONMENT, and the
// reproducible path performs no floating-point operation").
//
// PART 1 -- ENVIRONMENT INVARIANCE OF THE BYTES. The row digest over a
// fixed document set and W-A's own digest (`semb_wa_digest`) are asserted
// IDENTICAL across all eight {rounding mode} x {denormal state}
// combinations, set through MXCSR immediately before each `semb_encode`
// call and restored after (sec 8's own text, applied literally). The oracle
// is a FEATURE oracle in the sense the catalog's dimension 10 requires: it
// executes the real raw path eight times, under eight genuinely different
// hardware FP environments, and compares the bytes the path actually
// emitted -- not a recomputation of what the epilogue's arithmetic is
// claimed to do.
//
// PART 2 -- THE CROSS-THREAD LEG. N threads encode the SAME document
// through ONE encoder handle, each thread carrying a DIFFERENT
// {rounding, denormal} state set on ITS OWN thread before its call (MXCSR
// is per-thread state, sec 1.3) -- the property no single-threaded
// construction can reach: a handle documented as callable from many
// threads whose output secretly depended on which thread called it.
// Every thread's vector must be byte-identical to the serial (default
// environment) reference.
//
// PART 3 -- THE CLEARED-MASK LEGS. Three sub-legs, each named because sec
// 8 requires it stated separately:
//   (a) LIVENESS CONTROL (required before either b or c is meaningful):
//       clear all six MXCSR exception masks and execute a deliberately
//       inexact division OUTSIDE any library call, wrapped in Windows SEH
//       (__try/__except) so a genuine hardware trap is OBSERVED rather
//       than crashing this process. If the host/toolchain does not trap
//       under cleared masks (observed on some environments, sec 1.3's own
//       toolset table), this leg reports UNDETERMINED rather than a false
//       PASS -- a control that cannot fire proves nothing about the legs
//       it is meant to gate (StandardsDocument.md sec 5.4's commissioning
//       discipline, applied to this cell's own internal control).
//   (b) THE LIBRARY CALL UNDER CLEARED MASKS: with the SAME cleared masks
//       (proven live by (a)), `semb_encoder_open` + `semb_encode` must
//       RETURN NORMALLY -- no trap -- because SuperSLM >= 1.3.0's open
//       path performs no floating-point operation (sec 1.3's own
//       TERM REMOVAL ruling, D-SLM4231). The call is itself wrapped in SEH
//       so a genuine regression traps THIS assertion rather than crashing
//       the test binary silently.
//   (c) THE ENGINE-PIN ASSERTION, BESIDE THE LEG (sec 8's own text: "the
//       cell asserts the linked engine's VERSION beside the leg", D-SLM4602,
//       because a green leg is compatible with an UNDER-PINNED engine on
//       some toolchains -- an outcome-inferred pin check is a refusal that
//       can be satisfied without the condition being absent). Reads
//       `SEMB_ENGINE_PIN_TAG` from `generated/semb_engine_pin.h` --
//       CMakeLists.txt's own EngineGuards.cmake already refuses to
//       configure this tree at all if the installed package's reported
//       version disagrees with `superslm.lock`, so by the time this binary
//       exists the compiled-in tag IS the linked engine's version, not
//       merely a string this file trusts on its own authority -- and
//       parses it numerically (never lexically: "v1.10.0" < "v1.9.0" as
//       strings) to assert >= 1.3.0.
//
// MASKS ARE ALWAYS RESTORED before this file's `main` returns, on every
// exit path (including a caught SEH trap), via a scope guard -- clearing
// MXCSR exception masks and leaving them cleared would make every
// subsequent floating-point operation in a shared test process a live
// trap, corrupting whichever cell ctest happens to run next.
//
// RED-FIRST: before this file existed, no test in tests/ set MXCSR's
// rounding/flush-to-zero/denormals-are-zero bits, called
// `semb_wa_digest`+`semb_encode` together, or asserted an engine-pin floor
// numerically from the generated pin header (confirmed by `git grep`,
// filed in the casebook). This is the cell's own red-to-green transition.
#include <array>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <pmmintrin.h>
#include <string>
#include <thread>
#include <vector>
#include <xmmintrin.h>

// clang-cl and cl.exe both support SEH __try/__except on a Windows target;
// this file is not built for any non-Windows toolchain in this session
// (the WSL GCC leg is filed UNREACHABLE by the sub-plan's own toolchain
// crossing, tests/c23_token_id_determinism_check.py's report).
#include <windows.h>

#include "semb_engine_pin.h"
#include "semb_public_abi_contract.h"
#include "semb_wa_pool_abi_contract.h"  // for kSembWaPoolMaxAbsEMin's sibling constants -- unused directly, kept for future parts

#include "superembedder/witness_abi.h"

#define SEMB_STRINGIZE_(x) #x
#define SEMB_STRINGIZE(x) SEMB_STRINGIZE_(x)

namespace {

int g_failures = 0;
int g_undetermined = 0;

void Fail(const char* fmt, ...) {
  char buf[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  std::fprintf(stderr, "C41 FAIL: %s\n", buf);
  ++g_failures;
}

void Undetermined(const char* fmt, ...) {
  char buf[1024];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  std::fprintf(stderr, "C41 UNDETERMINED: %s\n", buf);
  ++g_undetermined;
}

// One {rounding, denormal} coordinate. FTZ and DAZ are handled together as
// "denormals flushed" (sec 8's own "{denormals preserved, flushed}" pairs
// the two bits as one axis, matching the ambient-machine-state census's
// own item 2 "FTZ / DAZ" pairing, sec 2.2).
struct FpState {
  const char* label;
  unsigned rounding;  // _MM_ROUND_*
  bool flush_denormals;
};

const FpState kStates[8] = {
    {"RN,preserve", _MM_ROUND_NEAREST, false},
    {"RN,flush", _MM_ROUND_NEAREST, true},
    {"RP,preserve", _MM_ROUND_UP, false},
    {"RP,flush", _MM_ROUND_UP, true},
    {"RM,preserve", _MM_ROUND_DOWN, false},
    {"RM,flush", _MM_ROUND_DOWN, true},
    {"RZ,preserve", _MM_ROUND_TOWARD_ZERO, false},
    {"RZ,flush", _MM_ROUND_TOWARD_ZERO, true},
};

// RAII: captures MXCSR on construction, restores it on destruction --
// covers every exit path (normal return, an assertion `return`, or an SEH
// exception unwinding through this scope) so a leg that traps or fails
// never leaves the process's floating-point environment corrupted for
// whatever ctest runs next.
class MxcsrGuard {
 public:
  MxcsrGuard() : saved_(_mm_getcsr()) {}
  ~MxcsrGuard() { _mm_setcsr(saved_); }

 private:
  unsigned saved_;
};

void ApplyState(const FpState& st) {
  _MM_SET_ROUNDING_MODE(st.rounding);
  _MM_SET_FLUSH_ZERO_MODE(st.flush_denormals ? _MM_FLUSH_ZERO_ON : _MM_FLUSH_ZERO_OFF);
  _MM_SET_DENORMALS_ZERO_MODE(st.flush_denormals ? _MM_DENORMALS_ZERO_ON : _MM_DENORMALS_ZERO_OFF);
}

// A handful of documents from the fixed mechanism corpus (hand-selected,
// not the whole 24 -- this cell's own claim is invariance across the FP
// ENVIRONMENT, not corpus coverage, which C23 and the parity cells already
// carry over the full set): a plain-ASCII case, a multi-byte UTF-8 case,
// and an empty-adjacent short case.
const char* const kDocs[] = {"hello world", "café résumé", "Numbers 1234 and 42"};
constexpr size_t kDocCount = sizeof(kDocs) / sizeof(kDocs[0]);

bool OpenMechanismEncoder(semb_encoder* out, uint32_t max_concurrency) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  static const std::string model_path = "build/_scratch/u1_pair/u1_pair_model.sslm";
  static const std::string tok_path = "build/_scratch/u1_pair/u1_pair_tokenizer.sslm";
  cfg.model_path = model_path.c_str();
  cfg.model_path_len = model_path.size();
  cfg.tokenizer_path = tok_path.c_str();
  cfg.tokenizer_path_len = tok_path.size();
  cfg.max_concurrency = max_concurrency;
  const semb_status st = semb_encoder_open(&cfg, out);
  if (st != SEMB_OK) {
    Fail("semb_encoder_open failed: %s (status %d) -- run u1_raw_text_cells_check.py first to mint "
         "build/_scratch/u1_pair/*.sslm",
         semb_status_name(st), static_cast<int>(st));
    return false;
  }
  return true;
}

// Encodes every document in kDocs through `enc` and appends every emitted
// vector's raw bytes, in order, to `out` -- the "row digest" input this
// cell compares across environment states.
bool EncodeAllDocs(semb_encoder enc, std::vector<uint8_t>* out) {
  uint32_t dims = 0;
  if (semb_encoder_dims(enc, &dims) != SEMB_OK) {
    Fail("semb_encoder_dims failed");
    return false;
  }
  for (size_t i = 0; i < kDocCount; ++i) {
    std::vector<float> vec(dims);
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    size_t required = 0;
    const semb_status st = semb_encode(enc, kDocs[i], std::strlen(kDocs[i]), vec.data(),
                                        vec.size() * sizeof(float), &required, &fp);
    if (st != SEMB_OK) {
      Fail("semb_encode('%s') failed: %s", kDocs[i], semb_status_name(st));
      return false;
    }
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(vec.data());
    out->insert(out->end(), bytes, bytes + vec.size() * sizeof(float));
  }
  return true;
}

// SEH: __except's filter expression cannot see C++ objects with
// destructors in the same function scope in general, so the trapping call
// is isolated in its own small function with only POD locals.
int TrapIfInexact() {
  __try {
    volatile float a = 1.0f;
    volatile float b = 3.0f;
    volatile float c = a / b;  // 1/3 is not exactly representable: genuinely inexact
    (void)c;
    return 0;  // did not trap
  } __except (GetExceptionCode() == STATUS_FLOAT_INEXACT_RESULT ||
                       GetExceptionCode() == STATUS_FLOAT_MULTIPLE_TRAPS
                   ? EXCEPTION_EXECUTE_HANDLER
                   : EXCEPTION_CONTINUE_SEARCH) {
    return 1;  // trapped, for the expected reason
  }
}

// The real work, as an ordinary C++ function -- vectors, strings, RAII,
// all legal here because this function contains no __try/__except of its
// own. Called ONLY from inside OpenAndEncodeCatchingTraps's __try block,
// below, so a trap during any of this unwinds into that wrapper's
// __except, never through a frame that itself mixes SEH with objects
// requiring unwinding (MSVC C2712: a function using __try/__except cannot
// also contain a C++ object with a destructor in the SAME function scope).
void DoOpenAndEncode(bool* opened_ok, semb_status* out_status) {
  semb_encoder enc = nullptr;
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  const std::string model_path = "build/_scratch/u1_pair/u1_pair_model.sslm";
  const std::string tok_path = "build/_scratch/u1_pair/u1_pair_tokenizer.sslm";
  cfg.model_path = model_path.c_str();
  cfg.model_path_len = model_path.size();
  cfg.tokenizer_path = tok_path.c_str();
  cfg.tokenizer_path_len = tok_path.size();
  cfg.max_concurrency = 1;
  *out_status = semb_encoder_open(&cfg, &enc);
  if (*out_status != SEMB_OK) return;
  *opened_ok = true;
  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  std::vector<float> vec(dims);
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  size_t required = 0;
  *out_status = semb_encode(enc, "hello world", 11, vec.data(), vec.size() * sizeof(float), &required, &fp);
  semb_encoder_close(enc);
}

int OpenAndEncodeCatchingTraps(bool* opened_ok, semb_status* out_status) {
  *opened_ok = false;
  __try {
    DoOpenAndEncode(opened_ok, out_status);
    return 0;  // did not trap
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    return 1;  // trapped somewhere in open/encode/close
  }
}

}  // namespace

int main() {
  MxcsrGuard top_level_guard;  // restores the process's MXCSR on every exit path below

  semb_encoder enc = nullptr;
  if (!OpenMechanismEncoder(&enc, /*max_concurrency=*/4)) {
    std::fprintf(stderr, "C41: cannot proceed without the mechanism encoder handle.\n");
    return 1;
  }

  // --- PART 1: environment invariance of the row digest and W-A's own digest ---
  std::vector<uint8_t> reference_row;
  std::array<uint8_t, 32> reference_wa{};
  for (size_t s = 0; s < 8; ++s) {
    ApplyState(kStates[s]);
    std::vector<uint8_t> row;
    if (!EncodeAllDocs(enc, &row)) {
      _MM_SET_ROUNDING_MODE(_MM_ROUND_NEAREST);
      _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_OFF);
      _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_OFF);
      continue;
    }
    std::array<uint8_t, 32> wa{};
    semb_wa_digest(wa.data());
    _MM_SET_ROUNDING_MODE(_MM_ROUND_NEAREST);
    _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_OFF);
    _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_OFF);

    if (s == 0) {
      reference_row = row;
      reference_wa = wa;
      std::printf("C41 part 1: reference state %s captured (%zu row bytes)\n", kStates[s].label, row.size());
      continue;
    }
    if (row != reference_row) {
      Fail("part 1: row digest bytes moved under state %s (row differs from the %s reference)",
           kStates[s].label, kStates[0].label);
    }
    if (wa != reference_wa) {
      Fail("part 1: W-A's own digest moved under state %s", kStates[s].label);
    }
  }
  std::printf("C41 part 1: %zu of 8 environment states compared against the %s reference.\n", size_t{8},
              kStates[0].label);

  // --- PART 2: the cross-thread leg ---
  {
    constexpr size_t kThreads = 4;
    uint32_t dims = 0;
    semb_encoder_dims(enc, &dims);
    std::vector<std::vector<uint8_t>> per_thread(kThreads);
    std::vector<std::thread> threads;
    for (size_t t = 0; t < kThreads; ++t) {
      threads.emplace_back([&, t]() {
        ApplyState(kStates[t % 8]);
        semb_fingerprint fp{};
        fp.struct_size = sizeof(fp);
        std::vector<float> vec(dims);
        size_t required = 0;
        const semb_status st =
            semb_encode(enc, "hello world", 11, vec.data(), vec.size() * sizeof(float), &required, &fp);
        if (st == SEMB_OK) {
          const uint8_t* bytes = reinterpret_cast<const uint8_t*>(vec.data());
          per_thread[t].assign(bytes, bytes + vec.size() * sizeof(float));
        }
        _MM_SET_ROUNDING_MODE(_MM_ROUND_NEAREST);
        _MM_SET_FLUSH_ZERO_MODE(_MM_FLUSH_ZERO_OFF);
        _MM_SET_DENORMALS_ZERO_MODE(_MM_DENORMALS_ZERO_OFF);
      });
    }
    for (auto& th : threads) th.join();

    // Serial reference for the identical document, default environment.
    std::vector<float> serial_vec(dims);
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    size_t required = 0;
    const semb_status serial_st =
        semb_encode(enc, "hello world", 11, serial_vec.data(), serial_vec.size() * sizeof(float), &required, &fp);
    if (serial_st != SEMB_OK) {
      Fail("part 2: the serial reference call itself failed: %s", semb_status_name(serial_st));
    } else {
      const uint8_t* bytes = reinterpret_cast<const uint8_t*>(serial_vec.data());
      const std::vector<uint8_t> serial_bytes(bytes, bytes + serial_vec.size() * sizeof(float));
      for (size_t t = 0; t < kThreads; ++t) {
        if (per_thread[t].empty()) {
          Fail("part 2: thread %zu (state %s) did not produce a vector", t, kStates[t % 8].label);
        } else if (per_thread[t] != serial_bytes) {
          Fail("part 2: thread %zu (state %s) diverged from the serial reference", t, kStates[t % 8].label);
        }
      }
    }
    std::printf("C41 part 2: %zu threads through one handle, each a different environment, compared.\n",
                kThreads);
  }

  semb_encoder_close(enc);

  // --- PART 3(a): liveness control -- prove masks-cleared genuinely traps
  // on THIS host/toolchain, outside the library, before either sub-leg
  // below is treated as meaningful. ---
  const unsigned saved_csr_before_part3 = _mm_getcsr();
  _MM_SET_EXCEPTION_MASK(0);  // unmask all six exceptions
  const int trapped = TrapIfInexact();
  _mm_setcsr(saved_csr_before_part3);  // restore before doing anything else
  if (!trapped) {
    Undetermined("part 3(a): the liveness control did not trap under cleared MXCSR exception masks on "
                 "this host/toolchain -- STATUS_FLOAT_INEXACT_RESULT was not observed for a genuinely "
                 "inexact division outside the library. Parts 3(b)/3(c) below still ran and are reported, "
                 "but a PASS on 3(b) is not evidence of anything when this control cannot fire; what would "
                 "settle it: re-running on a host/toolchain combination matching sec 1.3's own toolset "
                 "table (MSVC 19.3x is documented as trapping; 19.44 is documented as not trapping on the "
                 "cited construction -- this build's own compiler is "
#if defined(__clang__)
                 "clang " __clang_version__
#elif defined(_MSC_VER)
                 "MSVC " SEMB_STRINGIZE(_MSC_FULL_VER)
#else
                 "unknown"
#endif
                 ".");
  } else {
    std::printf("C41 part 3(a): liveness control trapped as expected (masks-cleared is live on this "
                "host/toolchain).\n");
  }

  // --- PART 3(b): the library call under cleared masks must return
  // normally (SuperSLM >= 1.3.0's open path performs no FP operation). ---
  _MM_SET_EXCEPTION_MASK(0);
  bool opened_ok = false;
  semb_status lib_status = SEMB_OK;
  const int lib_trapped = OpenAndEncodeCatchingTraps(&opened_ok, &lib_status);
  _mm_setcsr(saved_csr_before_part3);
  if (lib_trapped) {
    Fail("part 3(b): semb_encoder_open/semb_encode TRAPPED under cleared MXCSR exception masks -- the "
         "raw path performed a floating-point operation that raised (opened_ok=%d)",
         opened_ok ? 1 : 0);
  } else if (lib_status != SEMB_OK) {
    Fail("part 3(b): the library call did not trap but returned %s instead of SEMB_OK",
         semb_status_name(lib_status));
  } else {
    std::printf("C41 part 3(b): semb_encoder_open + semb_encode returned normally under cleared masks.\n");
  }

  // --- PART 3(c): the engine-pin assertion, beside the leg. ---
  {
    int major = -1, minor = -1, patch = -1;
    if (std::sscanf(SEMB_ENGINE_PIN_TAG, "v%d.%d.%d", &major, &minor, &patch) != 3) {
      Fail("part 3(c): could not parse SEMB_ENGINE_PIN_TAG ('%s') as vMAJOR.MINOR.PATCH", SEMB_ENGINE_PIN_TAG);
    } else if (major < 1 || (major == 1 && minor < 3)) {
      Fail("part 3(c): the linked engine pin is %s, below the required floor 1.3.0 -- part 3(b)'s green "
           "leg is compatible with an under-pinned engine unless this assertion also holds (sec 8's own "
           "'a green leg is compatible with an under-pinned engine' warning, D-SLM4602)",
           SEMB_ENGINE_PIN_TAG);
    } else {
      std::printf("C41 part 3(c): linked engine pin %s is >= 1.3.0.\n", SEMB_ENGINE_PIN_TAG);
    }
  }

  if (g_failures) {
    std::fprintf(stderr, "C41: %d failure(s), %d undetermined leg(s).\n", g_failures, g_undetermined);
    return 1;
  }
  std::printf("C41: parts 1-3 passed (%d leg(s) undetermined, filed above).\n", g_undetermined);
  return 0;
}
