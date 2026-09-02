// tests/fixtures/c39_singleton/two_references_a.cpp -- MUST-REJECT fixture
// (half A) for tests/c39_singleton_check.py: this file and
// two_references_b.cpp both name EmbedEntry, which the check must flag as
// a second copy of the specified encoder.
#include "superslm/forward_sites.h"

void EncodeA() { superslm::EmbedEntry(0, 0, nullptr, 0, {}, nullptr, nullptr); }
