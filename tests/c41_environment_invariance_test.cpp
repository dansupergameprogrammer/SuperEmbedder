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
// 8 requires it stated separately. (a) and (b) below are each run in their
// OWN CHILD PROCESS of this same binary (TE-192 item 7, TE-187 bare cell
// 6, D-SLM6441 item 4; the outside review's sec 5) rather than wrapped in
// Windows SEH (__try/__except) in-process: MSVC and clang-cl 18.1.8 lower
// __try/__except at this exact call site DIFFERENTLY (D-SLM6438 --
// clang-cl's own SEH did not intercept the trap, crashing the whole test
// binary instead of reporting a clean result), while both compilers
// terminate an unhandled hardware exception's PROCESS with the trapping
// NTSTATUS as its exit code IDENTICALLY -- so observing the trap at the
// OS process boundary (`GetExitCodeProcess`) needs no compiler-specific
// SEH lowering at all. Verified by execution to hold on both compilers
// (this file's own build record); replaces both, one code path for both,
// rather than forking on `#if defined(__clang__)`.
//   (a) LIVENESS CONTROL (required before either b or c is meaningful):
//       a child process clears all six MXCSR exception masks and executes
//       a deliberately inexact division OUTSIDE any library call; the
//       parent requires the child to be terminated by the OS with the
//       expected floating-point exception NTSTATUS as its exit code. A
//       SECOND child performs the SAME division WITHOUT clearing the
//       masks and must exit cleanly (0) -- the outside review's own
//       must-accept, proving the first child's trap is the cleared masks,
//       not the division itself. If the host/toolchain does not trap
//       under cleared masks (observed on some environments, sec 1.3's own
//       toolset table), this leg reports UNDETERMINED rather than a false
//       PASS -- a control that cannot fire proves nothing about the legs
//       it is meant to gate (StandardsDocument.md sec 5.4's commissioning
//       discipline, applied to this cell's own internal control).
//   (b) THE LIBRARY CALL UNDER CLEARED MASKS: a THIRD child, with the
//       SAME cleared masks (proven live by (a)), calls
//       `semb_encoder_open` + `semb_encode` and must RETURN NORMALLY --
//       no trap, exit 0 -- because SuperSLM >= 1.3.0's open path performs
//       no floating-point operation (sec 1.3's own TERM REMOVAL ruling,
//       D-SLM4231). A genuine regression traps the CHILD process, which
//       the parent observes as a non-zero exit code, rather than crashing
//       the test binary itself.
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
// parent-process exit path, via a scope guard -- clearing MXCSR exception
// masks and leaving them cleared would make every subsequent floating-
// point operation in a shared test process a live trap, corrupting
// whichever cell ctest happens to run next. Part 3's own mask-clearing
// (TE-192 item 7) happens entirely inside a CHILD process's own MXCSR
// register state, which the OS discards when that child exits -- the
// PARENT's own MXCSR is never touched by Part 3 at all, so nothing there
// needs restoring on that path.
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

// Part 3's child processes are spawned through Win32 on Windows and through
// fork/execv of /proc/self/exe elsewhere; a child's trap is observed at the
// process boundary on both (the trapping NTSTATUS as the exit code on
// Windows; termination by SIGFPE on POSIX). Parts 1 and 2 are SSE
// intrinsics and std::thread only. Before the POSIX branch this file
// included <windows.h> unconditionally and was not built off Windows.
#if defined(_WIN32)
#include <windows.h>
#else
#include <cerrno>
#include <csignal>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

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

// The real work, as an ordinary C++ function -- vectors, strings, RAII, all
// legal here since no caller wraps this in SEH any more (see below). Called
// ONLY from RunChildLibrary, in its own child process: a trap anywhere in
// here terminates that child, observed by the parent as a non-zero exit
// code, never caught in-process.
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

// -----------------------------------------------------------------------
// TE-192 item 7 (TE-187 bare cell 6, D-SLM6441 item 4; the outside review's
// sec 5, "clang-cl C41 liveness without fragile in-process SEH"): PART
// 3(a)'s liveness control and PART 3(b)'s library-under-cleared-masks leg
// are both replaced by a parent/child PROCESS boundary, on BOTH compilers
// (not clang-cl only) -- verified by execution below to hold identically
// on MSVC 19.33.31631.0 and clang-cl 18.1.8, so one code path serves both
// rather than forking on `#if defined(__clang__)`. The property under
// test ("does a genuinely inexact operation trap under cleared MXCSR
// exception masks on this host/toolchain") is observed at OS
// process-termination level (GetExitCodeProcess), which needs no
// compiler-specific SEH lowering at all: Windows terminates an unhandled
// hardware exception's process with the trapping NTSTATUS as its exit
// code on both toolchains identically. This removes the exact dependency
// D-SLM6438's own clang-cl 18.1.8 crash traced to -- clang-cl's
// __try/__except did not intercept the trap at this call site the way
// MSVC's does, crashing the whole test binary rather than reporting a
// clean FAIL or UNDETERMINED.
//
// This binary re-execs its OWN on-disk path (`argv[0]`'s resolved module
// path, not the caller-supplied argv[0] text) as a child process carrying
// one mode flag; the child does the minimal, SEH-free, POD-only work its
// mode names and either exits 0 (did not trap) or is terminated by the OS
// with the trapping NTSTATUS as its exit code (did trap) -- no code path
// in a child catches anything, so a genuine trap is never masked by an
// in-process handler either compiler might lower differently.
// -----------------------------------------------------------------------
constexpr char kChildInexactCleared[] = "--c41-child-inexact-cleared";
constexpr char kChildInexactUncleared[] = "--c41-child-inexact-uncleared";
constexpr char kChildLibraryCleared[] = "--c41-child-library-cleared";

enum class ChildMode { kNone, kInexactCleared, kInexactUncleared, kLibraryCleared };

ChildMode ParseChildMode(int argc, char** argv) {
  if (argc >= 2) {
    if (std::strcmp(argv[1], kChildInexactCleared) == 0) return ChildMode::kInexactCleared;
    if (std::strcmp(argv[1], kChildInexactUncleared) == 0) return ChildMode::kInexactUncleared;
    if (std::strcmp(argv[1], kChildLibraryCleared) == 0) return ChildMode::kLibraryCleared;
  }
  return ChildMode::kNone;
}

// A child's own inexact-division leg: with (`clear_masks`) or without all
// six MXCSR exception masks cleared, perform a genuinely inexact division.
// If the hardware traps, the OS terminates THIS process with the trapping
// NTSTATUS as its exit code -- nothing here catches it. If it does not
// trap, the process exits 0. No SEH anywhere in this function.
int RunChildInexact(bool clear_masks) {
#if defined(_WIN32)
  SetErrorMode(SEM_NOGPFAULTERRORBOX | SEM_FAILCRITICALERRORS);  // no modal crash dialog under automation
#endif
  if (clear_masks) _MM_SET_EXCEPTION_MASK(0);
  volatile float a = 1.0f;
  volatile float b = 3.0f;
  volatile float c = a / b;  // 1/3 is not exactly representable: genuinely inexact
  (void)c;
  return 0;  // did not trap
}

// A child's own library leg: with all six MXCSR exception masks cleared,
// open the mechanism encoder and encode one document (SuperSLM >= 1.3.0's
// open path performs no floating-point operation, D-SLM4231, so this must
// return normally). On success, serializes the resulting status name to
// stdout for the parent to read; a trap here terminates the child before
// any of that runs, observed by the parent through the exit code alone.
int RunChildLibrary() {
#if defined(_WIN32)
  SetErrorMode(SEM_NOGPFAULTERRORBOX | SEM_FAILCRITICALERRORS);
#endif
  _MM_SET_EXCEPTION_MASK(0);
  bool opened_ok = false;
  semb_status out_status = SEMB_OK;
  DoOpenAndEncode(&opened_ok, &out_status);
  std::printf("opened_ok=%d status=%s\n", opened_ok ? 1 : 0, semb_status_name(out_status));
  std::fflush(stdout);
  return 0;  // did not trap
}

// How a child ended, normalized across platforms. `code` is what the
// messages print: the Win32 exit code (an NTSTATUS for a trap), or on POSIX
// the exit status, or 0x80000000 | signal number for a signal termination.
struct ChildOutcome {
  bool exited_cleanly = false;  // exit code 0
  bool fp_trapped = false;      // ended by the floating-point exception itself
  unsigned long code = 0xFFFFFFFFul;
};

#if defined(_WIN32)
// Spawns THIS binary's own resolved on-disk path as a child process with
// `mode_flag` as argv[1], waits for it to exit, and returns its exit code.
// When `capture_stdout` is non-null, the child's stdout/stderr are piped
// and collected into it -- used only for the library leg, whose result the
// parent must read; the two inexact legs need nothing but the exit code.
DWORD SpawnChildAndWaitWin32(const char* mode_flag, std::string* capture_stdout) {
  char self_path[MAX_PATH] = {0};
  if (GetModuleFileNameA(nullptr, self_path, MAX_PATH) == 0) {
    Fail("SpawnChildAndWait: GetModuleFileNameA failed (error %lu)", GetLastError());
    return static_cast<DWORD>(-1);
  }

  HANDLE stdout_read = nullptr, stdout_write = nullptr;
  if (capture_stdout) {
    SECURITY_ATTRIBUTES sa{};
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;
    if (!CreatePipe(&stdout_read, &stdout_write, &sa, 0)) {
      Fail("SpawnChildAndWait: CreatePipe failed (error %lu)", GetLastError());
      return static_cast<DWORD>(-1);
    }
    SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0);  // the parent's own read end is not inherited further
  }

  std::string cmdline = "\"" + std::string(self_path) + "\" " + mode_flag;
  std::vector<char> cmdline_buf(cmdline.begin(), cmdline.end());
  cmdline_buf.push_back('\0');

  STARTUPINFOA si{};
  si.cb = sizeof(si);
  PROCESS_INFORMATION pi{};
  if (capture_stdout) {
    si.dwFlags |= STARTF_USESTDHANDLES;
    si.hStdOutput = stdout_write;
    si.hStdError = stdout_write;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
  }

  const BOOL created = CreateProcessA(self_path, cmdline_buf.data(), nullptr, nullptr,
                                       /*bInheritHandles=*/capture_stdout ? TRUE : FALSE, 0, nullptr, nullptr, &si,
                                       &pi);
  if (capture_stdout) CloseHandle(stdout_write);
  if (!created) {
    Fail("SpawnChildAndWait: CreateProcessA('%s') failed (error %lu)", mode_flag, GetLastError());
    if (stdout_read) CloseHandle(stdout_read);
    return static_cast<DWORD>(-1);
  }

  if (capture_stdout) {
    char buf[4096];
    DWORD n = 0;
    while (ReadFile(stdout_read, buf, sizeof(buf), &n, nullptr) && n > 0) {
      capture_stdout->append(buf, n);
    }
    CloseHandle(stdout_read);
  }

  WaitForSingleObject(pi.hProcess, INFINITE);
  DWORD exit_code = static_cast<DWORD>(-1);
  GetExitCodeProcess(pi.hProcess, &exit_code);
  CloseHandle(pi.hProcess);
  CloseHandle(pi.hThread);
  return exit_code;
}

ChildOutcome SpawnChildAndWait(const char* mode_flag, std::string* capture_stdout) {
  const DWORD exit_code = SpawnChildAndWaitWin32(mode_flag, capture_stdout);
  ChildOutcome out;
  out.code = exit_code;
  out.exited_cleanly = exit_code == 0;
  out.fp_trapped = exit_code == static_cast<DWORD>(STATUS_FLOAT_INEXACT_RESULT) ||
                   exit_code == static_cast<DWORD>(STATUS_FLOAT_MULTIPLE_TRAPS);
  return out;
}
#else
// POSIX: re-exec /proc/self/exe (this binary's own on-disk image, not the
// caller-supplied argv[0] text) with `mode_flag` as argv[1]. An unmasked SSE
// exception raises SIGFPE, whose default action terminates the child; the
// parent observes it through waitpid, never through an in-process handler.
ChildOutcome SpawnChildAndWait(const char* mode_flag, std::string* capture_stdout) {
  ChildOutcome out;
  int pipe_fds[2] = {-1, -1};
  if (capture_stdout && pipe(pipe_fds) != 0) {
    Fail("SpawnChildAndWait: pipe failed (errno %d)", errno);
    return out;
  }
  std::fflush(stdout);
  std::fflush(stderr);
  const pid_t pid = fork();
  if (pid < 0) {
    Fail("SpawnChildAndWait: fork('%s') failed (errno %d)", mode_flag, errno);
    if (capture_stdout) {
      close(pipe_fds[0]);
      close(pipe_fds[1]);
    }
    return out;
  }
  if (pid == 0) {
    signal(SIGFPE, SIG_DFL);
    if (capture_stdout) {
      dup2(pipe_fds[1], STDOUT_FILENO);
      dup2(pipe_fds[1], STDERR_FILENO);
      close(pipe_fds[0]);
      close(pipe_fds[1]);
    }
    char self_path[] = "/proc/self/exe";
    char* child_argv[] = {self_path, const_cast<char*>(mode_flag), nullptr};
    execv(self_path, child_argv);
    _exit(127);  // exec failed
  }
  if (capture_stdout) {
    close(pipe_fds[1]);
    char buf[4096];
    for (;;) {
      const ssize_t n = read(pipe_fds[0], buf, sizeof(buf));
      if (n > 0) {
        capture_stdout->append(buf, static_cast<size_t>(n));
      } else if (n < 0 && errno == EINTR) {
        continue;
      } else {
        break;
      }
    }
    close(pipe_fds[0]);
  }
  int status = 0;
  pid_t waited = -1;
  do {
    waited = waitpid(pid, &status, 0);
  } while (waited < 0 && errno == EINTR);
  if (waited != pid) {
    Fail("SpawnChildAndWait: waitpid('%s') failed (errno %d)", mode_flag, errno);
    return out;
  }
  if (WIFEXITED(status)) {
    out.code = static_cast<unsigned long>(WEXITSTATUS(status));
    out.exited_cleanly = WEXITSTATUS(status) == 0;
  } else if (WIFSIGNALED(status)) {
    out.code = 0x80000000ul | static_cast<unsigned long>(WTERMSIG(status));
    out.fp_trapped = WTERMSIG(status) == SIGFPE;
  }
  return out;
}
#endif

}  // namespace

int main(int argc, char** argv) {
  // Child dispatch (TE-192 item 7): a child invocation does the minimal,
  // SEH-free work its mode names and returns immediately, before the
  // parent-only MxcsrGuard/Part-1/Part-2 machinery below ever runs.
  const ChildMode child_mode = ParseChildMode(argc, argv);
  if (child_mode == ChildMode::kInexactCleared) return RunChildInexact(/*clear_masks=*/true);
  if (child_mode == ChildMode::kInexactUncleared) return RunChildInexact(/*clear_masks=*/false);
  if (child_mode == ChildMode::kLibraryCleared) return RunChildLibrary();

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
  // on THIS host/toolchain, at the OS process boundary, before either
  // sub-leg below is treated as meaningful. Two children: one with masks
  // cleared (expected to trap -- terminated by the OS with the trapping
  // NTSTATUS as its exit code), one WITHOUT (the outside review's own
  // must-accept: "a child that does not clear the masks must be seen not
  // to trap" -- proving the trap below is the CLEARED MASKS, not the
  // division itself). ---
  const ChildOutcome cleared = SpawnChildAndWait(kChildInexactCleared, nullptr);
  const unsigned long cleared_exit = cleared.code;
  const bool trapped = cleared.fp_trapped;
  const ChildOutcome uncleared = SpawnChildAndWait(kChildInexactUncleared, nullptr);
  const unsigned long uncleared_exit = uncleared.code;
  if (!uncleared.exited_cleanly) {
    Fail("part 3(a) must-accept: the child WITHOUT cleared masks did not exit cleanly (exit code 0x%08lX) "
         "-- the same division traps regardless of the mask state on this host/toolchain, so a trap below "
         "under cleared masks would prove nothing about the masks specifically",
         uncleared_exit);
  }
  if (!trapped) {
    Undetermined("part 3(a): the liveness-control child did not trap under cleared MXCSR exception masks "
                 "on this host/toolchain (child exit code 0x%08lX) -- STATUS_FLOAT_INEXACT_RESULT (SIGFPE "
                 "on POSIX) was not observed for a genuinely inexact division in its own child process. Parts 3(b)/3(c) "
                 "below still ran and are reported, but a PASS on 3(b) is not evidence of anything when "
                 "this control cannot fire; what would settle it: re-running on a host/toolchain "
                 "combination matching sec 1.3's own toolset table (MSVC 19.3x is documented as trapping; "
                 "19.44 is documented as not trapping on the cited construction -- this build's own "
                 "compiler is "
#if defined(__clang__)
                 "clang " __clang_version__
#elif defined(_MSC_VER)
                 "MSVC " SEMB_STRINGIZE(_MSC_FULL_VER)
#elif defined(__GNUC__)
                 "GCC " __VERSION__
#else
                 "unknown"
#endif
                 ").",
                 cleared_exit);
  } else {
    std::printf("C41 part 3(a): liveness control trapped as expected in its own child process (exit code "
                "0x%08lX; masks-cleared is live on this host/toolchain); the must-accept uncleared-masks "
                "child exited cleanly.\n",
                cleared_exit);
  }

  // --- PART 3(b): the library call under cleared masks must return
  // normally, in its own child process (SuperSLM >= 1.3.0's open path
  // performs no floating-point operation). ---
  std::string lib_stdout;
  const ChildOutcome lib = SpawnChildAndWait(kChildLibraryCleared, &lib_stdout);
  const unsigned long lib_exit = lib.code;
  if (!lib.exited_cleanly) {
    Fail("part 3(b): semb_encoder_open/semb_encode TRAPPED under cleared MXCSR exception masks in its own "
         "child process (exit code 0x%08lX) -- the raw path performed a floating-point operation that "
         "raised",
         lib_exit);
  } else if (lib_stdout.find("status=SEMB_OK") == std::string::npos) {
    Fail("part 3(b): the library call's own child did not trap (exit 0) but its serialized result was "
         "not SEMB_OK: '%s'",
         lib_stdout.c_str());
  } else {
    std::printf("C41 part 3(b): semb_encoder_open + semb_encode returned normally under cleared masks in "
                "its own child process ('%s').\n",
                lib_stdout.c_str());
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
