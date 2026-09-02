// src/superembedder/wa_digest.cpp -- TE-78: W-A's own digest, driven over
// sec 4.4's named edge sets crossed with the full legal parameter range
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 4.4b), calling the library's
// own semb_wa_pool_run (ps1_pool.cpp) over the population and folding
// every case's inputs, status, and (on SEMB_OK) emitted bits into one
// SHA-256 -- the engine's own portable routine (superslm/sha256.h), sec
// 4.4b's own "one hash function, not two."
//
// THE POPULATION IS SEC 4.4'S OWN PROSE, TRANSCRIBED DIRECTLY -- not
// derived from any test file or oracle: "hidden in {1,2,7,64}, n in
// {1,2,3,5,17,41}, exponent spread in {0,1,2,9,10,63,64,73,74} crossed
// with a base exponent in {-33,-160,+80}, canonical-m edges at 2^30,
// 2^30+1, 2^31-1 and mid-range, and the int8 code edge set {-128,-127,-1,
// 0,1,126,127} on the leading positions -- 2,592 cases; every refusal's
// STATUS digested." The crossing order and the per-case construction
// (edge codes on the leading positions, a seeded splitmix64 filling the
// rest; m rotating through the edge set per position; e alternating
// between the base exponent and the base-plus-spread so both e_min and
// e_max are actually attained) mirror the withdrawn fold-round-11 probe's
// own driver shape (`Claude/Vitruvius/t2217-fold4-probe/cost/
// t2217_fold11_pooling_wa_cell.cpp`, read as population/construction
// precedent per this seat's own brief, never as an oracle) -- that
// driver's own POOLING ARITHMETIC was withdrawn (D-SLM4079, no corner
// refusals); its POPULATION CONSTRUCTION is not, and this file drives the
// SAME population through THIS project's own corrected epilogue
// (semb_wa_pool_run, which does carry both corner refusals).
#include "superembedder/witness_abi.h"

#include <cstdint>
#include <cstring>
#include <vector>

#include "superembedder/pool_abi.h"
#include "superslm/sha256.h"

namespace semb {
namespace {

struct SplitMix64 {
  uint64_t state;
  uint64_t Next() {
    uint64_t z = (state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
  }
};

// sec 4.4's own named edge sets.
const int8_t kCodeEdges[] = {-128, -127, -1, 0, 1, 126, 127};
constexpr size_t kNumCodeEdges = sizeof(kCodeEdges) / sizeof(kCodeEdges[0]);
const int64_t kMEdges[] = {(int64_t{1} << 30), (int64_t{1} << 30) + 1, (int64_t{1} << 31) - 1,
                           (int64_t{1} << 30) + (int64_t{1} << 29)};
constexpr size_t kNumMEdges = sizeof(kMEdges) / sizeof(kMEdges[0]);
const int64_t kSpreads[] = {0, 1, 2, 9, 10, 63, 64, 73, 74};
const size_t kNs[] = {1, 2, 3, 5, 17, 41};
const size_t kHiddens[] = {1, 2, 7, 64};
const int64_t kEBases[] = {-33, -160, 80};

const char* StatusName(SembWaPoolStatus s) {
  switch (s) {
    case kSembOk: return "SEMB_OK";
    case kSembInputTooShort: return "SEMB_INPUT_TOO_SHORT";
    case kSembAccumulatorOverflow: return "SEMB_ACCUMULATOR_OVERFLOW";
    case kSembPooledSubnormal: return "SEMB_POOLED_SUBNORMAL";
    case kSembPooledOverflow: return "SEMB_POOLED_OVERFLOW";
  }
  return "SEMB_UNKNOWN";
}

// A small streaming-digest helper over superslm::Sha256, matching the
// withdrawn probe's own Digest struct shape (little-endian u64s,
// length-prefixed strings, raw float32 bits) so every digested value has
// an unambiguous, injective encoding.
struct Digest {
  superslm::Sha256 h;
  void Bytes(const void* p, size_t n) { h.Update(static_cast<const uint8_t*>(p), n); }
  void U64(uint64_t v) {
    uint8_t b[8];
    for (int i = 0; i < 8; ++i) b[i] = static_cast<uint8_t>((v >> (8 * i)) & 0xFF);
    Bytes(b, 8);
  }
  void Str(const char* s) {
    const size_t len = std::strlen(s);
    U64(len);
    Bytes(s, len);
  }
  void F32(float f) {
    uint32_t bits;
    std::memcpy(&bits, &f, 4);
    U64(bits);
  }
};

}  // namespace
}  // namespace semb

extern "C" void semb_wa_digest(uint8_t out_digest[32]) {
  using semb::Digest;
  using semb::kCodeEdges;
  using semb::kEBases;
  using semb::kHiddens;
  using semb::kMEdges;
  using semb::kNs;
  using semb::kNumCodeEdges;
  using semb::kNumMEdges;
  using semb::kSpreads;
  using semb::SplitMix64;
  using semb::StatusName;

  Digest d;
  d.Str("SEMB-W-A-1");  // a domain-separation tag, so this digest's own
                        // namespace never collides with W-B's or W-Q's.
  SplitMix64 rng{0x0F01D11ULL};  // sec 4.4's own named seed.

  for (size_t hidden : kHiddens) {
    for (size_t n : kNs) {
      for (int64_t spread : kSpreads) {
        for (int64_t ebase : kEBases) {
          for (size_t me = 0; me < kNumMEdges; ++me) {
            std::vector<int8_t> codes(n * hidden);
            std::vector<int64_t> m(n), e(n);
            for (size_t t = 0; t < n; ++t) {
              for (size_t i = 0; i < hidden; ++i) {
                const size_t k = t * hidden + i;
                codes[k] = (k < kNumCodeEdges) ? kCodeEdges[k]
                                                : static_cast<int8_t>(rng.Next() & 0xFF);
              }
              m[t] = kMEdges[(me + t) % kNumMEdges];
              // Alternate the extreme exponents so e_min and e_max are
              // both attained, exercising the full spread rather than an
              // average of it -- the same reason the withdrawn probe's
              // own construction alternates.
              e[t] = (t % 2 == 0) ? ebase : (ebase + spread);
            }

            std::vector<float> out(hidden, 0.0f);
            const SembWaPoolStatus status =
                semb_wa_pool_run(codes.data(), m.data(), e.data(), n, hidden, out.data());

            d.U64(hidden);
            d.U64(n);
            d.U64(static_cast<uint64_t>(spread));
            d.U64(static_cast<uint64_t>(ebase));
            d.U64(me);
            d.Str(StatusName(status));  // every refusal's STATUS digested
            if (status == kSembOk) {
              for (size_t i = 0; i < hidden; ++i) d.F32(out[i]);
            }
          }
        }
      }
    }
  }

  d.h.Final(out_digest);
}
