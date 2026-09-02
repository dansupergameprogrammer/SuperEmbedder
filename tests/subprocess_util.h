// tests/subprocess_util.h -- TE-62: run a child process and capture its
// stdout as a string, and locate the Python interpreter this suite's own
// oracle scripts are invoked with. `popen`/`_popen` (POSIX/MSVC) rather
// than a process library this project does not otherwise depend on --
// every caller here runs a short, already-trusted local script
// (`tests/oracle/*.py`), never caller-supplied or network input.
#ifndef SEMB_TESTS_SUBPROCESS_UTIL_H
#define SEMB_TESTS_SUBPROCESS_UTIL_H

#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#define SEMB_POPEN _popen
#define SEMB_PCLOSE _pclose
#include <process.h>  // _getpid
#else
#define SEMB_POPEN popen
#define SEMB_PCLOSE pclose
#include <unistd.h>  // getpid
#endif

namespace semb_test {

// TE-83 (TE-81 review N-9): a unique path under the platform's own temp
// directory, used to capture a child's stderr SEPARATELY from its stdout
// (see RunCaptureStdout below). PID + a per-process atomic counter makes
// this collision-free across concurrent calls within one process and
// across concurrently-running test binaries (each has its own PID).
inline std::string UniqueTempPath() {
  static std::atomic<int> counter{0};
#ifdef _WIN32
  const char* tmp = std::getenv("TEMP");
  if (!tmp || !*tmp) tmp = std::getenv("TMP");
  if (!tmp || !*tmp) tmp = ".";
  const int pid = _getpid();
#else
  const char* tmp = std::getenv("TMPDIR");
  if (!tmp || !*tmp) tmp = "/tmp";
  const int pid = static_cast<int>(getpid());
#endif
  return std::string(tmp) + "/semb_test_stderr_" + std::to_string(pid) + "_" +
         std::to_string(counter.fetch_add(1)) + ".txt";
}

// Runs `command` (a full shell command line) and returns its stdout.
//
// TE-83 (TE-81 review N-9, Observation): TE-80's own F-20 remedy merged
// the child's stderr into the SAME stream this function reads (`2>&1`),
// so an oracle's own Python traceback would reach a caller's exception
// message rather than being silently discarded on a non-zero exit -- the
// benefit F-20 wanted. The side effect: `c1_ps1_reference_test.cpp` and
// `w_a_pool_population_test.cpp` both feed this function's SUCCESS-PATH
// return value straight into `json_mini::Parse` over the whole string:
// today the oracle scripts only ever `print()` on their success paths, so
// nothing is broken, but a future interpreter warning landing on stderr
// (a DeprecationWarning, say) would corrupt what those two callers treat
// as pure JSON, and do so silently -- a parse error with no indication
// the cause was an unrelated stderr line.
//
// Fixed by capturing stderr SEPARATELY (a temp file, `UniqueTempPath()`,
// redirected via `2>"<path>"` on the command line -- understood
// identically by cmd.exe and a POSIX sh) rather than merging it into the
// stream callers parse. stdout, returned on success, is now exactly what
// the child wrote to stdout and nothing else -- F-20's coupling is
// removed. stderr is read back and attached to the exception message
// ONLY when the process exits non-zero, which is the one case F-20's own
// finding cared about; the temp file is removed in every case (success or
// failure) so nothing is left behind under the platform temp directory.
// Throws std::runtime_error if the process cannot be started or exits
// non-zero.
inline std::string RunCaptureStdout(const std::string& command) {
  const std::string stderr_path = UniqueTempPath();
  const std::string full_command = command + " 2>\"" + stderr_path + "\"";

  std::array<char, 8192> buf{};
  std::string result;
  FILE* pipe = SEMB_POPEN(full_command.c_str(), "r");
  if (!pipe) {
    std::remove(stderr_path.c_str());
    throw std::runtime_error("subprocess_util: failed to start: " + command);
  }
  size_t n;
  while ((n = std::fread(buf.data(), 1, buf.size(), pipe)) > 0) result.append(buf.data(), n);
  const int rc = SEMB_PCLOSE(pipe);

  std::string captured_stderr;
  {
    std::ifstream errf(stderr_path, std::ios::binary);
    if (errf) {
      std::ostringstream oss;
      oss << errf.rdbuf();
      captured_stderr = oss.str();
    }
  }
  std::remove(stderr_path.c_str());

  if (rc != 0) {
    throw std::runtime_error("subprocess_util: command exited " + std::to_string(rc) +
                              ": " + command + "\nstdout:\n" + result +
                              "\nstderr:\n" + captured_stderr);
  }
  return result;
}

// The Python interpreter this test build was configured with, or "python"
// as a PATH-resolved fallback. Overridable via SEMB_TEST_PYTHON so a
// caller (or a future CMake-driven test) can pin an exact interpreter,
// matching the rest of this project's configure-time Python discovery
// (`find_package(Python3 ...)`).
inline std::string PythonExecutable() {
  const char* env = std::getenv("SEMB_TEST_PYTHON");
  if (env && *env) return env;
#ifdef SEMB_TEST_PYTHON_EXECUTABLE
  return SEMB_TEST_PYTHON_EXECUTABLE;
#else
  return "python";
#endif
}

}  // namespace semb_test

#endif  // SEMB_TESTS_SUBPROCESS_UTIL_H
