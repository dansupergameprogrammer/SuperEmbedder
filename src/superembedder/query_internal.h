#pragma once

#include <array>

struct semb_encoder_s;

// W-Q is computed from the query entry point's committed composition corpus.
// It is private build machinery, called during encoder open before any
// ABI-facing fingerprint is derived.
bool semb_compute_wq_digest(semb_encoder_s* encoder, std::array<uint8_t, 32>* out_digest);
