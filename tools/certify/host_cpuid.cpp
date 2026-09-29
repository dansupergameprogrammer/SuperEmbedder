// The certification package's own CPU reading (te267 U2-6; U2-3 item 7). It is a second producer of the host's
// best tier beside the product's own report (the bake manifest's machine_tier), so it links neither engine nor
// product code and shares no source with either: it is written from the vendor documentation of CPUID leaves 0,
// 1, 7 (sub-leaf 0) and 0x80000000..0x80000004, and XGETBV with ECX = 0 (Intel SDM Vol. 2A "CPUID", Vol. 1
// sec. 13.3 and 15.2; AMD APM Vol. 3 "CPUID").
//
// Built for Windows (MSVC, clang-cl) and for Linux (GCC, Clang); run_certify.ps1 runs the Windows build beside
// each Windows member and the Linux build under wsl.exe beside the WSL member, because a WSL guest can expose
// fewer CPU features than its host.
//
// Output, one KEY=VALUE per line, exit 0:
//   HOST_BRAND=<the brand string of leaves 0x80000002..4, leading and trailing spaces trimmed>
//   HOST_BEST_TIER=<scalar|sse2|avx2|avx512>
//   HOST_FEATURES=sse2=<0|1> osxsave=<0|1> avx=<0|1> fma=<0|1> avx2=<0|1> avx512f=<0|1> avx512bw=<0|1> xcr0=0x<hex>
//
// The tiers are the kernels' own requirements (te267 U2-3 item 14): avx2 needs AVX, AVX2 and FMA with the OS
// saving SSE and AVX state (XCR0 bits 1 and 2); avx512 additionally needs AVX-512F and AVX-512BW with the OS
// saving opmask, ZMM_Hi256 and Hi16_ZMM state (XCR0 bits 5, 6 and 7). On a target that is not x86-64 the tier is
// scalar and the brand is empty.
#include <cstdio>
#include <cstring>

#if defined(_M_X64) || defined(__x86_64__)
#define HOST_CPUID_X64 1
#if defined(_MSC_VER)
#include <intrin.h>
#else
#include <cpuid.h>
#endif
#else
#define HOST_CPUID_X64 0
#endif

namespace {

#if HOST_CPUID_X64
struct Regs {
  unsigned a, b, c, d;
};

Regs Leaf(unsigned leaf, unsigned subleaf) {
  Regs r{};
#if defined(_MSC_VER)
  int v[4];
  __cpuidex(v, static_cast<int>(leaf), static_cast<int>(subleaf));
  r.a = static_cast<unsigned>(v[0]);
  r.b = static_cast<unsigned>(v[1]);
  r.c = static_cast<unsigned>(v[2]);
  r.d = static_cast<unsigned>(v[3]);
#else
  __cpuid_count(leaf, subleaf, r.a, r.b, r.c, r.d);
#endif
  return r;
}

unsigned long long ReadXcr0() {
#if defined(_MSC_VER)
  return _xgetbv(0);
#else
  unsigned lo = 0, hi = 0;
  __asm__ volatile("xgetbv" : "=a"(lo), "=d"(hi) : "c"(0));
  return (static_cast<unsigned long long>(hi) << 32) | lo;
#endif
}

bool Bit(unsigned value, int bit) { return ((value >> bit) & 1u) != 0; }
#endif

}  // namespace

int main() {
  bool sse2 = false, osxsave = false, avx = false, fma = false, avx2 = false, avx512f = false, avx512bw = false;
  unsigned long long xcr0 = 0;
  char brand[49] = {0};
#if HOST_CPUID_X64
  const unsigned max_leaf = Leaf(0, 0).a;
  if (max_leaf >= 1) {
    const Regs l1 = Leaf(1, 0);
    sse2 = Bit(l1.d, 26);
    fma = Bit(l1.c, 12);
    osxsave = Bit(l1.c, 27);
    avx = Bit(l1.c, 28);
  }
  if (max_leaf >= 7) {
    const Regs l7 = Leaf(7, 0);
    avx2 = Bit(l7.b, 5);
    avx512f = Bit(l7.b, 16);
    avx512bw = Bit(l7.b, 30);
  }
  if (osxsave) xcr0 = ReadXcr0();  // XGETBV faults unless the OS set CR4.OSXSAVE, which leaf 1 ECX bit 27 reports
  if (Leaf(0x80000000u, 0).a >= 0x80000004u) {
    for (unsigned i = 0; i < 3; ++i) {
      const Regs r = Leaf(0x80000002u + i, 0);
      const unsigned words[4] = {r.a, r.b, r.c, r.d};
      std::memcpy(brand + 16 * i, words, 16);
    }
  }
#endif
  const bool ymm_state = (xcr0 & 0x6u) == 0x6u;
  const bool zmm_state = (xcr0 & 0xE6u) == 0xE6u;
  const char* tier = "scalar";
  if (sse2) tier = "sse2";
  if (sse2 && osxsave && avx && fma && avx2 && ymm_state) tier = "avx2";
  if (sse2 && osxsave && avx && fma && avx2 && avx512f && avx512bw && ymm_state && zmm_state) tier = "avx512";

  const char* begin = brand;
  while (*begin == ' ') ++begin;
  size_t length = std::strlen(begin);
  while (length > 0 && begin[length - 1] == ' ') --length;
  std::printf("HOST_BRAND=%.*s\n", static_cast<int>(length), begin);
  std::printf("HOST_BEST_TIER=%s\n", tier);
  std::printf("HOST_FEATURES=sse2=%d osxsave=%d avx=%d fma=%d avx2=%d avx512f=%d avx512bw=%d xcr0=0x%llx\n", sse2,
              osxsave, avx, fma, avx2, avx512f, avx512bw, xcr0);
  return 0;
}
