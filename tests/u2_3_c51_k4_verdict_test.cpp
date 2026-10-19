// tests/u2_3_c51_k4_verdict_test.cpp -- (k-4), the verdict function (`Claude/Plans/te267-u2-release-plan.md`
// sec 5 U2-3 item 13, must-reject (k-4); item 1: "The engine-toolchain refusal is part of the same function, so
// C51 grades it without a mixed build"; plan of record sec 8 C51 (d); REL-2 step 1).
//
// The product's engine-toolchain comparison is semb::engine_link::CheckLinkedEngine (the product's own
// src/superembedder/engine_link_check.cpp, linked from the shipped static library): it reads the linked engine's
// sslm_build_identity() and compares its compiler and standard-library macro values with this library's own. This
// test is the linked engine: it defines sslm_build_identity() itself, ahead of the engine archive on the link line,
// returning an identity the test sets row by row, so the comparison is graded over chosen inputs with no mixed
// build. Every row carries the build record configure verified, an empty required_isa and no forced tier, so the
// only field that differs from the must-accept row is the one the row names.
//
//   must-accept     the identity of this product's own compiler and standard library     -> SEMB_OK
//   (k-4) compiler  another compiler's engine (on MSVC: clang-cl 18.1.8's, which reports __clang__ beside the same
//                   _MSC_FULL_VER; on clang-cl: MSVC's; on GCC: clang-18's against the same libstdc++; on Clang:
//                   GCC 13.3.0's)                                                       -> SEMB_ENGINE_TOOLCHAIN_MISMATCH
//   (k-4) version   the same compiler at another version (on MSVC: 19.44.35214 against 19.33)
//                                                                                       -> SEMB_ENGINE_TOOLCHAIN_MISMATCH
//   (k-4) stdlib    an equal toolchain with another standard library (on MSVC: _MSVC_STL_UPDATE 202503 against
//                   202205; on libstdc++: another __GLIBCXX__; on libc++: another _LIBCPP_VERSION)
//                                                                                       -> SEMB_ENGINE_TOOLCHAIN_MISMATCH
//                   (a configure-only implementation fails this row: configure compares the compiler, not the
//                   library)
//   control         this toolchain's identity with another build record                -> SEMB_ENGINE_LINK_MISMATCH
//                   (the function distinguishes the record from the toolchain, so the rows above are refused for
//                   their field)
//
// Runs on every host, with the tree's own compiler; exit 0 only when every row passes.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "semb_engine_pin.h"  // SEMB_ENGINE_BUILD_RECORD: the record configure verified
#include "superembedder/engine_identity/superslm_build_identity.h"
#include "superembedder/engine_link_check.h"
#include "superembedder/semb.h"
#if defined(__has_include)
#if __has_include(<version>)
#include <version>
#endif
#endif

namespace {
SslmBuildIdentity g_identity{};
std::string g_record;
}  // namespace

extern "C" const SslmBuildIdentity* sslm_build_identity(void) { return &g_identity; }

namespace {

int g_failures = 0;

SslmBuildIdentity OwnToolchain() {
  SslmBuildIdentity id{};
  id.struct_size = sizeof(SslmBuildIdentity);
  id.schema_version = 1;
#if defined(_MSC_FULL_VER)
  id.msc_full_ver = _MSC_FULL_VER;
#endif
#if defined(__clang__)
  id.clang_version = __clang_major__ * 10000 + __clang_minor__ * 100 + __clang_patchlevel__;
#endif
#if defined(__GNUC__) && !defined(__clang__)
  id.gnuc_version = __GNUC__ * 10000 + __GNUC_MINOR__ * 100 + __GNUC_PATCHLEVEL__;
#endif
#if defined(_MSVC_STL_UPDATE)
  id.msvc_stl_update = static_cast<uint32_t>(_MSVC_STL_UPDATE);
#endif
#if defined(__GLIBCXX__)
  id.glibcxx = static_cast<uint32_t>(__GLIBCXX__);
#endif
#if defined(_LIBCPP_VERSION)
  id.libcpp_version = static_cast<uint32_t>(_LIBCPP_VERSION);
#endif
  id.forced_tier = SSLM_FORCED_TIER_NONE;
  id.compiled_isa = 0;
  id.required_isa = 0;
  g_record = SEMB_ENGINE_BUILD_RECORD;
  id.build_record = g_record.c_str();
  return id;
}

std::string Describe(const SslmBuildIdentity& id) {
  char buf[256];
  std::snprintf(buf, sizeof buf, "msc_full_ver=%u clang=%u gnuc=%u msvc_stl=%u glibcxx=%u libcpp=%u record=%.24s...",
                id.msc_full_ver, id.clang_version, id.gnuc_version, id.msvc_stl_update, id.glibcxx,
                id.libcpp_version, id.build_record ? id.build_record : "(null)");
  return buf;
}

void Row(const char* name, const SslmBuildIdentity& id, semb_status want) {
  g_identity = id;
  const semb::engine_link::Verdict v = semb::engine_link::CheckLinkedEngine();
  const bool ok = v.status == want;
  if (!ok) ++g_failures;
  std::printf("[%s] %s -> %s (want %s); engine identity %s\n", ok ? "PASS" : "FAIL", name, semb_status_name(v.status),
              semb_status_name(want), Describe(id).c_str());
  std::fflush(stdout);
}

}  // namespace

int main() {
  const SslmBuildIdentity own = OwnToolchain();
  std::printf("this product: %s\n", Describe(own).c_str());

  Row("must-accept: the engine identity of this product's own compiler and standard library", own, SEMB_OK);

  // (k-4) compiler: the other compiler of this platform's pair.
  SslmBuildIdentity other = own;
  const char* what = "";
  if (own.msc_full_ver != 0 && own.clang_version == 0) {
    other.clang_version = 180108;  // clang-cl 18.1.8 under the same MSVC frontend version
    what = "(k-4) compiler: an engine clang-cl 18.1.8 built under this MSVC product";
  } else if (own.msc_full_ver != 0) {
    other.clang_version = 0;  // MSVC proper under this clang-cl product
    what = "(k-4) compiler: an engine MSVC built under this clang-cl product";
  } else if (own.gnuc_version != 0) {
    other.gnuc_version = 0;
    other.clang_version = 180103;  // clang-18 against the same libstdc++ (REL-2 step 1's GCC column)
    what = "(k-4) compiler: an engine clang-18 built against this GCC product's libstdc++";
  } else {
    other.clang_version = 0;
    other.gnuc_version = 130300;
    what = "(k-4) compiler: an engine GCC 13.3.0 built under this Clang product";
  }
  Row(what, other, SEMB_ENGINE_TOOLCHAIN_MISMATCH);

  // (k-4) version: the same compiler, another version.
  SslmBuildIdentity version = own;
  if (own.msc_full_ver != 0 && own.clang_version == 0) {
    version.msc_full_ver = own.msc_full_ver == 194435214u ? 193331631u : 194435214u;  // MSVC 19.44 against 19.33
  } else if (own.clang_version != 0) {
    version.clang_version = own.clang_version + 1;
  } else {
    version.gnuc_version = own.gnuc_version + 1;
  }
  Row("(k-4) version: an engine the same compiler built at another version", version, SEMB_ENGINE_TOOLCHAIN_MISMATCH);

  // (k-4) stdlib: an equal toolchain, another standard library.
  SslmBuildIdentity stdlib = own;
  if (own.msvc_stl_update != 0) {
    stdlib.msvc_stl_update = own.msvc_stl_update == 202503u ? 202205u : 202503u;
  } else if (own.glibcxx != 0) {
    stdlib.glibcxx = own.glibcxx + 1;
  } else if (own.libcpp_version != 0) {
    stdlib.libcpp_version = own.libcpp_version + 1;
  } else {
    stdlib.glibcxx = 20240904u;  // a library this product does not use at all
  }
  Row("(k-4) stdlib: equal toolchains, another standard library", stdlib, SEMB_ENGINE_TOOLCHAIN_MISMATCH);

  // Control: the record alone differs.
  SslmBuildIdentity record = own;
  static const std::string kOther = "sslm-build-record-v1:" + std::string(64, '0');
  record.build_record = kOther.c_str();
  Row("control: this toolchain's identity with a build record configure did not verify", record,
      SEMB_ENGINE_LINK_MISMATCH);

  std::printf("TOTAL C51 (k-4): failures=%d\n", g_failures);
  return g_failures == 0 ? 0 : 1;
}
