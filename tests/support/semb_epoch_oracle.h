// tests/support/semb_epoch_oracle.h -- the certification_epoch field of the five-field fingerprint, as the
// C++ fingerprint-composition cells recompute it (te267-u2-release-plan.md sec 5 U2-3 item 1, P:1003-1006;
// item 9, P:1136-1137 and P:1156-1158).
//
// U2-3 moves the epoch from the whole list to the identity file, in the verdict's form:
//   a build that resolves to a certified cell   SHA-256(identity bytes)
//   any other build                             SHA-256("SEMB-UNCERTIFIED" || NUL || identity bytes)
// The identity bytes are read by the cell from docs/certification-identity.json and the prefix is typed here
// from the plan. The form is the one the SAME encoder's bake manifest reports as `certified_cell`: these cells
// grade the fingerprint's composition, and the verdict itself is graded independently of the product -- from
// the committed list and the manifest's descriptor, by the plan's matching rule -- by
// tests/te264_fingerprint_final_check.py's epoch cell.
#ifndef SEMB_TESTS_SUPPORT_EPOCH_ORACLE_H
#define SEMB_TESTS_SUPPORT_EPOCH_ORACLE_H

#include <cstdint>
#include <string>

#include "superslm/sha256.h"

namespace semb_epoch_oracle {

inline constexpr char kIdentityPath[] = "docs/certification-identity.json";
inline constexpr char kUncertifiedCell[] = "uncertified";

// The bake manifest's `certified_cell` string value, or "" when the manifest carries none.
inline std::string CertifiedCellOf(const std::string& manifest_text) {
  const std::string key = "\"certified_cell\"";
  size_t at = manifest_text.find(key);
  if (at == std::string::npos) return std::string();
  at = manifest_text.find(':', at + key.size());
  if (at == std::string::npos) return std::string();
  const size_t open = manifest_text.find('"', at + 1);
  if (open == std::string::npos) return std::string();
  const size_t close = manifest_text.find('"', open + 1);
  if (close == std::string::npos) return std::string();
  return manifest_text.substr(open + 1, close - open - 1);
}

// The epoch for `cell` (a builds[] id, or "uncertified") over the identity file's exact bytes.
inline void EpochFor(const std::string& cell, const std::string& identity_bytes, uint8_t out[32]) {
  std::string input;
  if (cell == kUncertifiedCell) {
    input.assign("SEMB-UNCERTIFIED");
    input.push_back('\0');
  }
  input.append(identity_bytes);
  superslm::Sha256 h;
  h.Update(reinterpret_cast<const uint8_t*>(input.data()), input.size());
  h.Final(out);
}

}  // namespace semb_epoch_oracle

#endif  // SEMB_TESTS_SUPPORT_EPOCH_ORACLE_H
