// tests/u3_guard_fixture_test.cpp -- U3 red suite, sec 4.6 row 5(a)'s fixture
// and its CPU half (te266 P:4215; TE-389 G1). The test author's.
//
// Links the SHIPPED static target, every build. Runs on the guard pair minted
// by tests/fixtures/regenerate_u3_guard_pair_fixture.py (the U1 pair with
// embedding rows 121 and 173 exchanged and layer0.attn_norm's mantissa set to
// -679,477,248).
//
// Cells:
//   5a-pre   SETUP PRECONDITION (P:4215): the cell's own CPU oracle reproduces
//            the one-id trip set. For every id in [0, vocab), the one-content-id
//            document [id] (the end token 262 appended) goes down the interim
//            composed path; exactly one id refuses with the forward status
//            CarriedScaleMantissaOutOfDomain, and it is 173.
//   5a-wit   all 22 witness sequences pass: a public CPU open over the pair
//            (which runs W-B and W-Q) returns SEMB_OK.
//   5a-cpu   the document "abcdefg\xC3\xAD" (content ids 97..103, 195, 173:
//            eight passing ids, then 173) refuses on a CPU handle with
//            SEMB_ENGINE_REFUSED; the CPU channel (the interim verb's
//            out_engine_status_name, over the same ids) carries
//            CarriedScaleMantissaOutOfDomain; the same handle then encodes a
//            passing document to the row a fresh handle gives it.
// These are PINS of today's CPU behaviour, green by construction once the
// fixture reproduces; they gate the GPU half (u3_gpu_cells_test --cell
// row5a_guard), which is [U] until the dev box runs it (P:4215, P:4261).
//
// USAGE: u3_guard_fixture_test --model <guard model> --tokenizer <pair tokenizer> [--log <file>]
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <set>
#include <string>
#include <vector>

#include "superembedder/encoder_interim_abi.h"
#include "support/u3_common.h"

namespace {
constexpr int32_t kPairAppended = 262;
constexpr int32_t kTripId = 173;
const char* const kGuardStatus = "CarriedScaleMantissaOutOfDomain";
}  // namespace

int main(int argc, char** argv) {
  std::string model, tokenizer, log;
  for (int i = 1; i + 1 < argc; i += 2) {
    const std::string a = argv[i];
    if (a == "--model") model = argv[i + 1];
    else if (a == "--tokenizer") tokenizer = argv[i + 1];
    else if (a == "--log") log = argv[i + 1];
  }
  if (!log.empty()) u3::LogFile() = std::fopen(log.c_str(), "ab");
  if (model.empty() || !u3::FileExists(model) || tokenizer.empty() || !u3::FileExists(tokenizer)) {
    u3::Missing("u3_guard_fixture", "the guard pair (--model, --tokenizer) is absent");
    return u3::ExitCode();
  }

  // ---- 5a-pre: the trip set over the whole vocabulary ----------------------
  SembInterimEncoder* ienc = nullptr;
  const char* eng = nullptr;
  if (semb_interim_encoder_open(model.c_str(), kPairAppended, &ienc, &eng) != kSembInterimOk) {
    u3::Verdict(false, "5a-pre the guard model opens on the interim path", eng ? eng : "?");
    return u3::ExitCode();
  }
  SembInterimGeometry g{};
  g.struct_size = sizeof(g);
  semb_interim_encoder_geometry(ienc, &g);
  std::set<int32_t> trips;
  std::vector<std::string> other_refusals;
  std::vector<float> vec(g.hidden_size);
  for (int32_t id = 0; id < static_cast<int32_t>(g.vocab_size); ++id) {
    size_t req = 0;
    SembWaPoolStatus dq{};
    const char* name = nullptr;
    const SembInterimStatus s = semb_interim_encode_ps_n(ienc, &id, 1, 0, vec.data(), vec.size() * sizeof(float),
                                                         &req, &dq, &name);
    if (s == kSembInterimOk) continue;
    if (name && std::strcmp(name, kGuardStatus) == 0) {
      trips.insert(id);
    } else if (other_refusals.size() < 8) {
      other_refusals.push_back(std::to_string(id) + ":" + (name ? name : "?"));
    }
  }
  std::string trip_list;
  for (const int32_t t : trips) trip_list += (trip_list.empty() ? "" : ",") + std::to_string(t);
  const bool pre_ok = trips.size() == 1 && *trips.begin() == kTripId && other_refusals.empty();
  u3::Verdict(pre_ok, "5a-pre SETUP: the CPU oracle's trip set over the vocabulary is exactly {173} (P:4215)",
              "vocab=" + u3::S(g.vocab_size) + " trips={" + trip_list + "}" +
                  (other_refusals.empty() ? "" : " other refusals: " + other_refusals.front()));

  // ---- 5a-wit: every witness sequence passes (a public CPU open) -----------
  semb_encoder enc = nullptr;
  {
    semb_config c{};
    c.struct_size = sizeof(c);
    c.model_path = model.data();
    c.model_path_len = model.size();
    c.tokenizer_path = tokenizer.data();
    c.tokenizer_path_len = tokenizer.size();
    c.max_concurrency = 1;
    const semb_status s = semb_encoder_open(&c, &enc);
    u3::Verdict(s == SEMB_OK, "5a-wit all 22 witness sequences pass: the CPU open over the guard pair succeeds",
                u3::Name(s));
  }

  // ---- 5a-cpu: the guard document on a CPU handle --------------------------
  if (enc) {
    const std::string doc = "abcdefg\xC3\xAD";  // ids 97..103, 195, then 173 (U+00ED's second byte)
    std::vector<float> row;
    const semb_status s = u3::EncodeRow(enc, doc, &row);
    const int32_t ids[9] = {97, 98, 99, 100, 101, 102, 103, 195, kTripId};
    size_t req = 0;
    SembWaPoolStatus dq{};
    const char* name = nullptr;
    const SembInterimStatus is = semb_interim_encode_ps_n(ienc, ids, 9, 0, vec.data(), vec.size() * sizeof(float),
                                                          &req, &dq, &name);
    u3::Verdict(s == SEMB_ENGINE_REFUSED && is != kSembInterimOk && name && std::strcmp(name, kGuardStatus) == 0,
                "5a-cpu the guard document refuses SEMB_ENGINE_REFUSED; the CPU channel carries "
                "CarriedScaleMantissaOutOfDomain",
                std::string("public ") + u3::Name(s) + ", channel " + (name ? name : "(none)"));
    std::vector<float> after, fresh;
    const semb_status s2 = u3::EncodeRow(enc, "abcdefg", &after);
    semb_encoder_close(enc);
    semb_config c{};
    c.struct_size = sizeof(c);
    c.model_path = model.data();
    c.model_path_len = model.size();
    c.tokenizer_path = tokenizer.data();
    c.tokenizer_path_len = tokenizer.size();
    c.max_concurrency = 1;
    semb_encoder e2 = nullptr;
    if (semb_encoder_open(&c, &e2) == SEMB_OK) {
      u3::EncodeRow(e2, "abcdefg", &fresh);
      semb_encoder_close(e2);
    }
    u3::Verdict(s2 == SEMB_OK && u3::SameBytes(after, fresh),
                "5a-cpu' the refusing handle then encodes a passing document to a fresh handle's row",
                std::string(u3::Name(s2)) + (u3::SameBytes(after, fresh) ? ", byte-equal" : ", DIFFERS"));
  }
  semb_interim_encoder_close(ienc);
  std::printf("SUMMARY u3_guard_fixture pass=%d fail=%d red=%d missing=%d\n", u3::T().pass, u3::T().fail,
              u3::T().red, u3::T().missing);
  return u3::ExitCode();
}
