#pragma once

#include "superembedder/encoder_interim_abi.h"

namespace semb {

// Private raw-text open: validate the tokenizer/model vocabulary join after
// engine load and marshal, before sizing or allocating the workspace pool.
// A zero tokenizer vocabulary preserves the interim token-id open behavior.
// On a join refusal, returns kSembInterimEngineRefused with vocab_mismatch set;
// the public wrapper maps that distinct refusal to its public status.
SembInterimStatus OpenEncoderOwnedWithVocabJoin(
    std::vector<uint8_t>&& model_bytes, int32_t appended_token_id,
    uint32_t max_concurrency, uint32_t tokenizer_vocab_size,
    SembInterimEncoder** out_encoder, const char** out_engine_status_name,
    bool& vocab_mismatch);

}  // namespace semb
