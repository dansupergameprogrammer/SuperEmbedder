// include/superembedder/version.h — public version surface for the
// `superembedder` library and the `semb` CLI. This slice (TE-61, U0's
// non-arithmetic half) ships no encoder; the version below identifies the
// scaffold only, not a product release.
#pragma once

#define SEMB_VERSION_MAJOR 0
#define SEMB_VERSION_MINOR 1
#define SEMB_VERSION_PATCH 0
#define SEMB_VERSION_STRING "0.1.0-u0-scaffold"

namespace superembedder {

// Returns SEMB_VERSION_STRING.
const char* Version();

}  // namespace superembedder
