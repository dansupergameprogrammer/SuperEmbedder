// tests/u2_6_fake_tool.cpp -- U2 cloud build, U2-6: the stand-in program the package-script check
// (tests/u2_6_package_check.py) stages in a constructed package wherever the package carries a binary
// (a member's semb, the CPU probe, c63, wsl.exe). It is one real executable on every platform, so
// run_certify.ps1 starts it exactly as it starts the real binaries (CreateProcess on Windows, execve
// elsewhere). It runs the Python script beside it with the same stem (<dir>/<stem>.py), under the
// interpreter SEMB_FAKE_PYTHON names, passing its arguments, standard input and standard output through,
// and exits with that script's exit code. The script decides the behaviour.
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <windows.h>
#else
#include <climits>
#include <unistd.h>
#endif

namespace {

std::string SelfPath(const char* argv0) {
#if defined(_WIN32)
  char buffer[MAX_PATH * 4];
  const DWORD n = GetModuleFileNameA(nullptr, buffer, sizeof(buffer));
  if (n > 0 && n < sizeof(buffer)) return std::string(buffer, n);
#else
  char buffer[PATH_MAX];
  const ssize_t n = readlink("/proc/self/exe", buffer, sizeof(buffer) - 1);
  if (n > 0) return std::string(buffer, static_cast<size_t>(n));
#endif
  return argv0;
}

std::string ScriptFor(const std::string& self) {
  const size_t slash = self.find_last_of("/\\");
  const std::string dir = slash == std::string::npos ? std::string() : self.substr(0, slash + 1);
  std::string name = slash == std::string::npos ? self : self.substr(slash + 1);
  const size_t dot = name.rfind('.');
  if (dot != std::string::npos && dot > 0) name = name.substr(0, dot);
  return dir + name + ".py";
}

#if defined(_WIN32)
// One argument quoted by the rules CommandLineToArgvW reads back.
std::string Quote(const std::string& arg) {
  if (!arg.empty() && arg.find_first_of(" \t\"") == std::string::npos) return arg;
  std::string out = "\"";
  size_t backslashes = 0;
  for (const char c : arg) {
    if (c == '\\') {
      ++backslashes;
      continue;
    }
    if (c == '"') {
      out.append(2 * backslashes + 1, '\\');
      out.push_back('"');
      backslashes = 0;
      continue;
    }
    out.append(backslashes, '\\');
    backslashes = 0;
    out.push_back(c);
  }
  out.append(2 * backslashes, '\\');
  out.push_back('"');
  return out;
}
#endif

}  // namespace

int main(int argc, char** argv) {
  const char* python = std::getenv("SEMB_FAKE_PYTHON");
  if (!python || !*python) {
    std::fprintf(stderr, "u2_6_fake_tool: SEMB_FAKE_PYTHON is not set\n");
    return 90;
  }
  const std::string script = ScriptFor(SelfPath(argv[0]));
#if defined(_WIN32)
  std::string command = Quote(python) + " " + Quote(script);
  for (int i = 1; i < argc; ++i) command += " " + Quote(argv[i]);
  STARTUPINFOA si{};
  si.cb = sizeof(si);
  si.dwFlags = STARTF_USESTDHANDLES;
  si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
  si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
  si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
  PROCESS_INFORMATION pi{};
  std::vector<char> line(command.begin(), command.end());
  line.push_back('\0');
  if (!CreateProcessA(nullptr, line.data(), nullptr, nullptr, TRUE, 0, nullptr, nullptr, &si, &pi)) {
    std::fprintf(stderr, "u2_6_fake_tool: cannot start %s\n", python);
    return 91;
  }
  WaitForSingleObject(pi.hProcess, INFINITE);
  DWORD code = 92;
  GetExitCodeProcess(pi.hProcess, &code);
  CloseHandle(pi.hThread);
  CloseHandle(pi.hProcess);
  return static_cast<int>(code);
#else
  std::vector<char*> args;
  args.push_back(const_cast<char*>(python));
  args.push_back(const_cast<char*>(script.c_str()));
  for (int i = 1; i < argc; ++i) args.push_back(argv[i]);
  args.push_back(nullptr);
  execv(python, args.data());
  std::fprintf(stderr, "u2_6_fake_tool: cannot exec %s\n", python);
  return 91;
#endif
}
