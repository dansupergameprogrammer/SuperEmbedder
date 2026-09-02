// tests/fixtures/c39_singleton/two_references_b.cpp -- MUST-REJECT fixture
// (half B) for tests/c39_singleton_check.py: a second, independent
// implementation of the same seam -- the exact defect class C39 exists to
// refuse (two files agreeing about the encoder rather than one file
// specifying it).
#include "superslm/forward_sites.h"

void EncodeB() { superslm::EmbedEntry(1, 1, nullptr, 0, {}, nullptr, nullptr); }
