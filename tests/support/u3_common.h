// tests/support/u3_common.h -- the U3 red suite's shared helpers (te266 sec 4,
// P:3874-4322). Header-only; C++17.
//
// The U3 ABI is written against the plan, not against today's semb.h:
//   * semb_config gains a last member `uint32_t device;` (P:4022), with
//     SEMB_DEVICE_CPU = 0, the zero-initialized default, and SEMB_DEVICE_GPU = 1.
//     u3::Config below is today's semb_config plus that member. On LP64 and
//     LLP64 the member lands in the tail padding, so sizeof is 48 either way
//     and today's product ACCEPTS a u3::Config, ignoring `device` (the plan's
//     "struct_size grows", P:4022, does not hold: a PENDING planner item). No
//     cell may read an accepted open as the device working: a cell that needs
//     the member checks kProductHasDevice and is RED without it. Once semb.h
//     carries the member, the static_asserts below hold the two layouts equal.
//   * the three statuses are resolved BY NAME through semb_status_name (P:4023:
//     "named, never numbered, in U3's cells"). An unresolved name is a
//     RED-UNIMPLEMENTED verdict, never a compile error, so each cell is red for
//     its own reason.
#ifndef SEMB_U3_COMMON_H
#define SEMB_U3_COMMON_H

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <type_traits>
#include <vector>

#include "superembedder/semb.h"

namespace u3 {

constexpr uint32_t kDeviceCpu = 0;  // SEMB_DEVICE_CPU (P:4022)
constexpr uint32_t kDeviceGpu = 1;  // SEMB_DEVICE_GPU (P:4022)

// Today's semb_config members, in order, then U3's `device` (P:4022).
struct Config {
  uint32_t struct_size;
  const char* model_path;
  size_t model_path_len;
  const char* tokenizer_path;
  size_t tokenizer_path_len;
  uint32_t max_concurrency;
  uint32_t device;
};

template <class T, class = void>
struct HasDevice : std::false_type {};
template <class T>
struct HasDevice<T, std::void_t<decltype(std::declval<T&>().device)>> : std::true_type {};

// True once the product header carries U3's member.
constexpr bool kProductHasDevice = HasDevice<semb_config>::value;

template <class C, bool = HasDevice<C>::value>
struct LayoutCheck {
  static constexpr bool ok = true;  // today's header: nothing to compare yet
};
template <class C>
struct LayoutCheck<C, true> {  // instantiated only once semb_config::device exists
  static constexpr bool ok = sizeof(C) == sizeof(Config) && offsetof(C, device) == offsetof(Config, device) &&
                             offsetof(C, max_concurrency) == offsetof(Config, max_concurrency);
};
static_assert(LayoutCheck<semb_config>::ok,
              "U3 ABI (P:4022): semb_config's `device` is its last member, after max_concurrency, "
              "and the layout equals today's members plus one uint32_t");

inline Config MakeConfig(const std::string& model, const std::string& tokenizer, uint32_t mc,
                         uint32_t device) {
  Config c{};
  c.struct_size = static_cast<uint32_t>(sizeof(Config));
  c.model_path = model.data();
  c.model_path_len = model.size();
  c.tokenizer_path = tokenizer.data();
  c.tokenizer_path_len = tokenizer.size();
  c.max_concurrency = mc;
  c.device = device;
  return c;
}

inline semb_status Open(const Config& c, semb_encoder* out) {
  return semb_encoder_open(reinterpret_cast<const semb_config*>(&c), out);
}

// Resolves the value whose semb_status_name is exactly `name` in [0, 4096);
// -1 when no value carries it.
inline int32_t StatusByName(const char* name) {
  for (int32_t v = 0; v < 4096; ++v) {
    const char* n = semb_status_name(static_cast<semb_status>(v));
    if (n && std::strcmp(n, name) == 0) return v;
  }
  return -1;
}
inline const char* Name(int32_t s) {
  const char* n = semb_status_name(static_cast<semb_status>(s));
  return n ? n : "(null)";
}

// ---- verdicts ---------------------------------------------------------------
// [PASS] / [FAIL] / [RED-UNIMPLEMENTED] / [MISSING PREREQUISITE] / [NOTE]
// lines, one per leg, flushed as they are written (the dev box's logs are read
// after a crash, so every line must already be on disk).
struct Tally {
  int pass = 0, fail = 0, red = 0, missing = 0;
};
inline Tally& T() {
  static Tally t;
  return t;
}
inline std::FILE*& LogFile() {
  static std::FILE* f = nullptr;
  return f;
}
inline void Emit(const char* tag, const std::string& cell, const std::string& observed) {
  std::printf("[%s] %s: %s\n", tag, cell.c_str(), observed.c_str());
  std::fflush(stdout);
  if (LogFile()) {
    std::fprintf(LogFile(), "[%s] %s: %s\n", tag, cell.c_str(), observed.c_str());
    std::fflush(LogFile());
  }
}
inline void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  (ok ? T().pass : T().fail)++;
  Emit(ok ? "PASS" : "FAIL", cell, observed);
}
inline void Red(const std::string& cell, const std::string& why) {
  T().red++;
  Emit("RED-UNIMPLEMENTED", cell, why);
}
inline void Missing(const std::string& cell, const std::string& why) {
  T().missing++;
  Emit("MISSING PREREQUISITE", cell, why);
}
inline void Note(const std::string& cell, const std::string& what) { Emit("NOTE", cell, what); }
// Exit code: 1 on any FAIL or RED; 77 (ctest SKIP_RETURN_CODE) when every leg
// was a missing prerequisite; 0 only when at least one leg passed and none
// failed.
inline int ExitCode() {
  const Tally& t = T();
  if (t.fail || t.red) return 1;
  if (t.pass == 0) return 77;
  return 0;
}

// Resolves each U3 status by name; a missing one is a RED-UNIMPLEMENTED line
// for `cell` and returns false.
inline bool Resolve(const std::string& cell, const char* name, int32_t* out) {
  *out = StatusByName(name);
  if (*out < 0) {
    Red(cell, std::string(name) + " names no semb_status (P:4023-4026; J9)");
    return false;
  }
  return true;
}

inline std::vector<uint8_t> ReadAll(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}
inline bool FileExists(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  return static_cast<bool>(f);
}
inline std::string S(uint64_t v) { return std::to_string(v); }

// Encodes `text` on `enc`; returns the status and the row's bytes.
inline semb_status EncodeRow(semb_encoder enc, const std::string& text, std::vector<float>* row) {
  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  row->assign(dims ? dims : 1, 0.0f);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  const semb_status s = semb_encode(enc, text.data(), text.size(), row->data(), row->size() * sizeof(float),
                                    &req, &fp);
  if (s != SEMB_OK) row->clear();
  return s;
}
inline bool SameBytes(const std::vector<float>& a, const std::vector<float>& b) {
  return a.size() == b.size() && !a.empty() && std::memcmp(a.data(), b.data(), a.size() * sizeof(float)) == 0;
}

}  // namespace u3

#endif  // SEMB_U3_COMMON_H
