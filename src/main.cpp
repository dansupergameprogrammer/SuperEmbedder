// src/main.cpp — the `semb` CLI. This slice (TE-61) ships a stub: it prints
// its own version and the pinned engine's tag. The verbs (bake/query/verify)
// are U1's (Claude/Plans/SuperEmbedder_Plan.md §7, the U1 row).
#include <cstdio>

#include "semb_engine_pin.h"
#include "superembedder/version.h"

int main(int argc, char** argv) {
  (void)argc;
  (void)argv;
  std::printf("semb %s (engine pin %s @ %s)\n", superembedder::Version(), SEMB_ENGINE_PIN_TAG,
              SEMB_ENGINE_PIN_COMMIT);
  return 0;
}
