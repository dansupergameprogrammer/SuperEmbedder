// tests/subprocess_util.h -- TE-62: run a child process and capture its
// stdout as a string, and locate the Python interpreter this suite's own
// oracle scripts are invoked with. `popen`/`_popen` (POSIX/MSVC) rather
// than a process library this project does not otherwise depend on --
// every caller here runs a short, already-trusted local script
// (`tests/oracle/*.py`), never caller-supplied or network input.
#ifndef SEMB_TESTS_SUBPROCESS_UTIL_H
#define SEMB_TESTS_SUBPROCESS_UTIL_H

#include <array>
#include <cstdio>
#include <stdexcept>
#include <string>

#ifdef _WIN32
#define SEMB_POPEN _popen
#define SEMB_PCLOSE _pclose
#else
#define SEMB_POPEN popen
#define SEMB_PCLOSE pclose
#endif

namespace semb_test {

// Runs `command` (a full shell command line) and returns its COMBINED
// stdout+stderr (TE-80, TE-76 review F-20: the prior version discarded
// the child's stderr -- both _popen and popen only ever captured stdout
// -- so an oracle's own Python traceback reached a caller's exception
// message as an exit code and nothing else, the least useful moment to
// lose it. `2>&1`, appended to the command line, is understood
// identically by cmd.exe (Windows _popen's shell) and a POSIX sh, and
// merges the child's stderr into the SAME stream this function already
// reads -- no caller needs to change, and a caller with clean stdout
// under normal operation sees no difference.
// Throws std::runtime_error if the process cannot be started or exits
// non-zero.
inline std::string RunCaptureStdout(const std::string& command) {
  std::array<char, 8192> buf{};
  std::string result;
  FILE* pipe = SEMB_POPEN((command + " 2>&1").c_str(), "r");
  if (!pipe) throw std::runtime_error("subprocess_util: failed to start: " + command);
  size_t n;
  while ((n = std::fread(buf.data(), 1, buf.size(), pipe)) > 0) result.append(buf.data(), n);
  int rc = SEMB_PCLOSE(pipe);
  if (rc != 0)
    throw std::runtime_error("subprocess_util: command exited " + std::to_string(rc) +
                              ": " + command + "\noutput:\n" + result);
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
