// tests/u1_interim_batch_optional_output_test.cpp -- TE-182 (U1 slice 2's
// fourth test-author round, D-SLM6434 item 1): the interim ABI's own bare
// cells over `semb_interim_encode_batch_ps_n`'s optional-output contract
// (`include/superembedder/encoder_interim_abi.h`), routed from TE-149's
// coverage audit (`Claude/Mendeleev/te149-slice12-coverage-audit-2026-09-07.md`
// sec 7) and TE-161's confirmation review
// (`Claude/Poirot/7af22da-te161-slice2-confirm.md` M-1, M-2):
//
//   * BARE CELL 3 (sec 7 item 3; TE-161 M-1) -- out_vectors == nullptr AND
//     out_seam_stream == nullptr together: unreachable from either current
//     caller (`encoder.cpp`'s public verb always passes exactly one), but
//     an undocumented, untested state on a shared internal ABI. Pinned
//     here as the documented no-op it is today: the forward still runs for
//     every document, the call returns kSembInterimOk having written
//     nothing, every status-shaped output stays at its "no failure" value.
//   * BARE CELL 4 (sec 7 item 4; TE-161 M-2) -- doc_count == 0 with a
//     non-null out_seam_stream and out_seam_stream_len: the header's own
//     contract (encoder_interim_abi.h:206-211) states "on success
//     *out_seam_stream_len holds the exact length written", but the
//     empty-corpus early return (engine_adapter_interim.cpp:719) returns
//     before the seam-capacity block that would write it, so a caller's
//     own preloaded sentinel survives. This cell asserts the documented
//     contract; if the product still leaves the sentinel, it is RED BY
//     NAME and stays red -- the fix is src/**, outside this seat's
//     writable scope, owed to the builder's next round (D-SLM6434).
//
// Opens the mechanism synthetic model directly through the INTERIM path
// (semb_interim_encoder_open), never the public semb_encoder_open -- the
// interim verb under test takes already-tokenized content ids, not UTF-8
// text, so no tokenizer artifact is needed here at all. Hardcoded to the
// mechanism pair's own model file, following
// tests/c41_environment_invariance_test.cpp's own convention (a plain,
// no-argument executable; ctest does not order tests by dependency, so a
// run of ONLY this test on a fresh build reports the open refusal by name
// rather than a silent skip -- running the full suite, or
// tests/u1_raw_text_cells_check.py once, mints the pair first).
//
// RED-FIRST: before this file existed, no test anywhere in tests/ called
// semb_interim_encode_batch_ps_n with both out_vectors and out_seam_stream
// null, or with doc_count == 0 and a non-null out_seam_stream_len
// (confirmed by `git grep -n semb_interim_encode_batch_ps_n tests/` at this
// branch's own base 3e93430: only src/superembedder/encoder.cpp's own
// ComposeBatch calls it, always with out_vectors non-null when out_seam_stream
// is null and vice versa or both non-null -- never null/null, and never
// with doc_count == 0 reachable from either caller, since the public
// verb's own step 3 refuses SEMB_CORPUS_EMPTY before ComposeBatch is ever
// entered).
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "superembedder/encoder_interim_abi.h"

namespace {

int g_failures = 0;
int g_cells = 0;

void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}

// The mechanism synthetic pair's own fixed geometry
// (tests/fixtures/regenerate_tokenizer_pair_fixture.py): hidden 32, vocab
// 384, context_cap 64, <|endoftext|> = 262 (PAIR_APPENDED_TOKEN_ID in that
// script). Only the model half is needed here -- the interim path takes
// content ids directly, never UTF-8 text.
constexpr int32_t kPairAppendedTokenId = 262;
const char* kPairModelPath = "build/_scratch/u1_pair/u1_pair_model.sslm";

}  // namespace

int main() {
  const char* engine_status = nullptr;
  SembInterimEncoder* enc = nullptr;
  const SembInterimStatus open_st =
      semb_interim_encoder_open(kPairModelPath, kPairAppendedTokenId, &enc, &engine_status);
  if (open_st != kSembInterimOk || !enc) {
    Verdict(false, "(setup) semb_interim_encoder_open on the mechanism pair",
            "status=" + std::to_string(static_cast<int>(open_st)) +
                " engine=" + (engine_status ? engine_status : "?") +
                " -- run the full suite, or tests/u1_raw_text_cells_check.py once, to mint " +
                std::string(kPairModelPath) + " first");
    return 1;
  }

  SembInterimGeometry geometry{};
  geometry.struct_size = sizeof(geometry);
  if (semb_interim_encoder_geometry(enc, &geometry) != kSembInterimOk) {
    Verdict(false, "(setup) semb_interim_encoder_geometry", "refused");
    semb_interim_encoder_close(enc);
    return 1;
  }
  const size_t hidden = geometry.hidden_size;

  // ---- Bare cell 3 (M-1): out_vectors == nullptr AND out_seam_stream == nullptr ----
  {
    const std::vector<int32_t> doc0 = {1, 2, 3};
    const std::vector<int32_t> doc1 = {4, 5, 6, 7};
    const int32_t* docs_content_ids[2] = {doc0.data(), doc1.data()};
    const size_t docs_n_content[2] = {doc0.size(), doc1.size()};

    size_t required_bytes = 0xBAD5EED;
    size_t failed_index = 0xBAD5EED;
    SembWaPoolStatus dequantize_status = static_cast<SembWaPoolStatus>(0xBAD5EED);
    const char* out_engine_status = nullptr;

    const SembInterimStatus s = semb_interim_encode_batch_ps_n(
        enc, docs_content_ids, docs_n_content, /*doc_count=*/2, /*chunk_budget=*/0,
        /*out_vectors=*/nullptr, /*out_capacity_bytes=*/0, &required_bytes, &failed_index,
        &dequantize_status, &out_engine_status, /*out_seam_stream=*/nullptr,
        /*out_seam_stream_capacity=*/0, /*out_seam_stream_len=*/nullptr);

    const size_t expected_required = 2 * hidden * sizeof(float);
    const bool ok = s == kSembInterimOk && required_bytes == expected_required && failed_index == 0 &&
                     dequantize_status == kSembOk && out_engine_status != nullptr &&
                     std::strcmp(out_engine_status, "Ok") == 0;
    Verdict(ok,
            "bare-cell-3 out_vectors==nullptr and out_seam_stream==nullptr together -> kSembInterimOk, "
            "the forward still runs for every document (no crash reaching this line proves no write was "
            "attempted through either null pointer), *out_required_bytes states what a row buffer WOULD "
            "need, *out_failed_index and *out_dequantize_status stay at their no-failure defaults "
            "(the documented no-op TE-161 M-1 and D-SLM6434 item 1 name)",
            "status=" + std::to_string(static_cast<int>(s)) + " required_bytes=" + std::to_string(required_bytes) +
                " (expected " + std::to_string(expected_required) + ") failed_index=" + std::to_string(failed_index) +
                " dequantize_status=" + std::to_string(static_cast<int>(dequantize_status)) +
                " engine_status=" + (out_engine_status ? out_engine_status : "<NULL>"));
  }

  // ---- Bare cell 4 (M-2): doc_count == 0 with a non-null out_seam_stream ----------
  {
    std::vector<uint8_t> seam_buf(64, 0xA5);
    size_t seam_len = 0xBAD5EED;      // the caller-supplied sentinel the header says success overwrites
    size_t required_bytes = 0xBAD5EED;
    size_t failed_index = 0xBAD5EED;
    SembWaPoolStatus dequantize_status = static_cast<SembWaPoolStatus>(0xBAD5EED);
    const char* out_engine_status = nullptr;

    const SembInterimStatus s = semb_interim_encode_batch_ps_n(
        enc, /*docs_content_ids=*/nullptr, /*docs_n_content=*/nullptr, /*doc_count=*/0,
        /*chunk_budget=*/0, /*out_vectors=*/nullptr, /*out_capacity_bytes=*/0, &required_bytes,
        &failed_index, &dequantize_status, &out_engine_status, seam_buf.data(), seam_buf.size(), &seam_len);

    // *out_required_bytes IS documented and IS written on every return
    // (encoder_interim_abi.h:187-189), including this one -- checked
    // alongside the seam length so a reader sees the contrast directly:
    // one output the empty-corpus return already honours, one it does not.
    const bool required_bytes_ok = s == kSembInterimOk && required_bytes == 0;
    const bool seam_len_written = s == kSembInterimOk && seam_len == 0;
    Verdict(required_bytes_ok && seam_len_written,
            "bare-cell-4 doc_count==0 with a non-null out_seam_stream/out_seam_stream_len -> kSembInterimOk, "
            "*out_required_bytes == 0 (already honoured) AND *out_seam_stream_len == 0 (encoder_interim_abi.h:210-211's "
            "own documented contract; RED BY NAME if the sentinel survives -- TE-161 M-2, D-SLM6434 item 1, "
            "the fix is src/** and owed to the builder's next round, never weakened or touched here)",
            "status=" + std::to_string(static_cast<int>(s)) + " required_bytes=" + std::to_string(required_bytes) +
                " seam_len=" + std::to_string(seam_len) + " (0xBAD5EED sentinel = " +
                std::to_string(static_cast<size_t>(0xBAD5EED)) + ")");
  }

  semb_interim_encoder_close(enc);
  std::printf("\nu1_interim_batch_optional_output_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
