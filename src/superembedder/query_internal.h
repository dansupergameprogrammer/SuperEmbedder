#pragma once

#include <array>
#include <string_view>

struct semb_encoder_s;

namespace semb {

// The compiled query prefix has one definition, in query.cpp.  Both the
// query composition and encoder fingerprint digest consume these bytes.
extern const char kQueryPrefix[];

}  // namespace semb

// W-Q is computed from the query entry point's committed composition corpus.
// It is private build machinery, called during encoder open before any
// ABI-facing fingerprint is derived.
// Returns SEMB_OK, SEMB_ALLOCATION_FAILED when an encode could not allocate
// (U2-10 Builds item 3), or SEMB_ENGINE_REFUSED on any other refusal.
semb_status semb_compute_wq_digest(semb_encoder_s* encoder, std::array<uint8_t, 32>* out_digest);
