// tests/fixtures/c39_singleton/single_reference.cpp -- MUST-ACCEPT fixture
// for tests/c39_singleton_check.py: exactly one file naming a closed-set
// symbol must not be flagged.
#include "superslm/forward_sites.h"

void Encode() { superslm::EmbedEntry(0, 0, nullptr, 0, {}, nullptr, nullptr); }
