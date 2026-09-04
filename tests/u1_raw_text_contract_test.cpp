// tests/u1_raw_text_contract_test.cpp -- TE-92 (U1, the first frozen public
// raw-text vertical slice): the CONTRACT cells of sec 3.1's five frozen verbs
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1, "The C ABI, frozen"; the
// frozen properties 1-7; sec 8 C4's mechanism edges), executed against a
// model + tokenizer pair handed on the command line:
//
//   --model <.sslm> --tokenizer <.sslm> --append-id <id> --dims <expected>
//   [--context-cap <n>]              enables the at-cap / over-cap cells (K-12)
//   [--other-model <.sslm>]          a model whose vocab_size is SMALLER than the
//                                    tokenizer's id range (mismatch cell K-06a)
//   [--other-tokenizer <.sslm>]      a tokenizer whose id range EXCEEDS --model's
//                                    vocab_size (mismatch cell K-06d)
//   [--truncated-tokenizer <path>]   a scratch path this test writes a truncated
//                                    copy of --tokenizer to (K-05d)
//
// The driver (tests/u1_raw_text_cells_check.py) runs this once on the
// synthetic pair (tests/fixtures/regenerate_tokenizer_pair_fixture.py: hidden
// 32, vocab 384, context_cap 64, appended id 262) -- the MECHANISM run -- and,
// when the real Qwen3-Embedding-0.6B artifact and its converter-emitted
// tokenizer are configured, once more on the real pair (dims 1024, appended
// id 151643) -- the PRODUCT run. Every cell below is stated with the sec 3.1
// item it realizes. Statuses are resolved BY NAME through semb_status_name
// (tests/semb_public_abi_contract.h: the names are frozen, the values are the
// builder's).
//
// RED-UNIMPLEMENTED at main@1a040a4: none of the five verbs exists, so this
// translation unit does not link; the driver reports the unresolved symbols
// by name.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"

namespace {

int g_failures = 0;
int g_cells = 0;
constexpr size_t kRequiredSentinel = static_cast<size_t>(0xC5C5C5C5u);

void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}

void Missing(const std::string& cell, const std::string& why) {
  ++g_cells;
  std::printf("[MISSING PREREQUISITE] %s: %s\n", cell.c_str(), why.c_str());
  std::fflush(stdout);
}

const char* Name(semb_status s) {
  const char* n = semb_status_name(s);
  return n ? n : "<NULL>";
}

// A status resolved by name, or -1 (reported by the coverage cell K-07,
// and compared against by every other cell -- a -1 never equals a real
// status, so a missing name fails every cell that expects it).
struct Statuses {
  int32_t ok, null_argument, struct_size_mismatch, invalid_handle, buffer_too_small,
      misaligned_buffer, input_empty, engine_refused;
};

Statuses ResolveStatuses() {
  using semb_contract::StatusByName;
  Statuses s{};
  s.ok = StatusByName("SEMB_OK");
  s.null_argument = StatusByName("SEMB_NULL_ARGUMENT");
  s.struct_size_mismatch = StatusByName("SEMB_STRUCT_SIZE_MISMATCH");
  s.invalid_handle = StatusByName("SEMB_INVALID_HANDLE");
  s.buffer_too_small = StatusByName("SEMB_BUFFER_TOO_SMALL");
  s.misaligned_buffer = StatusByName("SEMB_MISALIGNED_BUFFER");
  s.input_empty = StatusByName("SEMB_INPUT_EMPTY");
  s.engine_refused = StatusByName("SEMB_ENGINE_REFUSED");
  return s;
}

semb_config MakeConfig(const std::string& model, const std::string& tokenizer, int32_t append_id) {
  semb_config cfg{};
  cfg.struct_size = sizeof(semb_config);
  cfg.model_path = model.c_str();
  cfg.model_path_len = model.size();
  cfg.tokenizer_path = tokenizer.c_str();
  cfg.tokenizer_path_len = tokenizer.size();
  cfg.appended_token_id = append_id;
  cfg.max_concurrency = 1;
  return cfg;
}

// A sentinel-filled, 16-byte-aligned float buffer with slack on both ends so
// "nothing written" and "nothing written past the required size" are both
// checkable byte for byte.
struct SentinelBuffer {
  static constexpr uint8_t kSentinel = 0xA5;
  std::vector<float> storage;  // over-allocated; Data() is 16-byte aligned
  size_t capacity_bytes = 0;
  explicit SentinelBuffer(size_t bytes) : capacity_bytes(bytes) {
    storage.assign((bytes + 64) / sizeof(float) + 16, 0.0f);
    std::memset(storage.data(), kSentinel, storage.size() * sizeof(float));
  }
  float* Data() {
    auto p = reinterpret_cast<uintptr_t>(storage.data());
    p = (p + 15) & ~static_cast<uintptr_t>(15);
    return reinterpret_cast<float*>(p);
  }
  bool Untouched(size_t bytes_from_start) {
    const auto* b = reinterpret_cast<const uint8_t*>(Data());
    for (size_t i = 0; i < bytes_from_start; ++i)
      if (b[i] != kSentinel) return false;
    return true;
  }
  bool UntouchedFrom(size_t offset, size_t count) {
    const auto* b = reinterpret_cast<const uint8_t*>(Data());
    for (size_t i = offset; i < offset + count; ++i)
      if (b[i] != kSentinel) return false;
    return true;
  }
};

semb_fingerprint MakeFingerprint() {
  semb_fingerprint fp{};
  fp.struct_size = sizeof(semb_fingerprint);
  std::memset(fp.digest, 0xC3, sizeof(fp.digest));
  return fp;
}

bool FingerprintUntouched(const semb_fingerprint& fp) {
  for (uint8_t b : fp.digest)
    if (b != 0xC3) return false;
  return fp.struct_size == sizeof(semb_fingerprint);
}

std::string Hex(const uint8_t* p, size_t n) {
  static const char* d = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; ++i) {
    s += d[p[i] >> 4];
    s += d[p[i] & 15];
  }
  return s;
}

struct Args {
  std::string model, tokenizer, other_model, other_tokenizer, truncated_tokenizer;
  int32_t append_id = -1;
  uint32_t dims = 0;
  size_t context_cap = 0;
};

Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&](std::string* dst) {
      if (i + 1 >= argc) { std::fprintf(stderr, "missing value for %s\n", k.c_str()); std::exit(2); }
      *dst = argv[++i];
    };
    std::string v;
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--other-model") next(&a.other_model);
    else if (k == "--other-tokenizer") next(&a.other_tokenizer);
    else if (k == "--truncated-tokenizer") next(&a.truncated_tokenizer);
    else if (k == "--append-id") { next(&v); a.append_id = std::atoi(v.c_str()); }
    else if (k == "--dims") { next(&v); a.dims = static_cast<uint32_t>(std::atoi(v.c_str())); }
    else if (k == "--context-cap") { next(&v); a.context_cap = static_cast<size_t>(std::atoll(v.c_str())); }
    else { std::fprintf(stderr, "unknown argument %s\n", k.c_str()); std::exit(2); }
  }
  if (a.model.empty() || a.tokenizer.empty() || a.append_id < 0 || a.dims == 0) {
    std::fprintf(stderr, "usage: --model <.sslm> --tokenizer <.sslm> --append-id <id> --dims <n> ...\n");
    std::exit(2);
  }
  return a;
}

// Opens the pair or fails the named cell; returns nullptr on failure.
semb_encoder OpenPair(const Args& a, const Statuses& st, const char* cell) {
  const semb_config cfg = MakeConfig(a.model, a.tokenizer, a.append_id);
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&cfg, &enc);
  if (s != st.ok || !enc) {
    Verdict(false, cell, std::string("open refused: ") + Name(s));
    return nullptr;
  }
  return enc;
}

const char kDoc[] = "hello world";

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  const Statuses st = ResolveStatuses();

  // ---- K-07 status names: every status this slice reaches has a name; static storage --------
  {
    std::string missing, found;
    for (size_t i = 0; i < semb_contract::kSliceStatusNameCount; ++i) {
      const int32_t v = semb_contract::StatusByName(semb_contract::kSliceStatusNames[i]);
      if (v < 0) missing += std::string(" ") + semb_contract::kSliceStatusNames[i];
      else found += std::string(" ") + semb_contract::kSliceStatusNames[i] + "=" + std::to_string(v);
    }
    Verdict(missing.empty(), "K-07a every status name this slice reaches is returned by semb_status_name",
            missing.empty() ? found : "missing:" + missing + "; found:" + found);
    Verdict(st.ok == SEMB_OK, "K-07b SEMB_OK is value 0 (the project's kSemb*Ok convention)",
            "SEMB_OK resolved to " + std::to_string(st.ok));
    std::string absent;
    int present = 0;
    for (size_t i = 0; i < semb_contract::kPlanStatusNameCount; ++i) {
      if (semb_contract::StatusByName(semb_contract::kPlanStatusNames[i]) < 0)
        absent += std::string(" ") + semb_contract::kPlanStatusNames[i];
      else ++present;
    }
    std::printf("[OBSERVED] K-07c sec 3.1/sec 8 vocabulary outside this slice: %d present, absent:%s\n",
                present, absent.empty() ? " none" : absent.c_str());
    // Distinct names across distinct recognized values.
    bool distinct = true;
    std::vector<int32_t> values;
    for (size_t i = 0; i < semb_contract::kSliceStatusNameCount; ++i)
      values.push_back(semb_contract::StatusByName(semb_contract::kSliceStatusNames[i]));
    std::sort(values.begin(), values.end());
    for (size_t i = 1; i < values.size(); ++i)
      if (values[i] == values[i - 1] && values[i] >= 0) distinct = false;
    Verdict(distinct, "K-07d recognized status values are distinct", "values sorted, no duplicate >= 0");
    // Never NULL, including for values that are not members of the enum.
    const char* n_neg = semb_status_name(-1);
    const char* n_big = semb_status_name(INT32_MAX);
    const char* n_scan = semb_status_name(semb_contract::kStatusScanLimit);
    Verdict(n_neg && n_big && n_scan,
            "K-07e semb_status_name is never NULL, including for non-member values",
            std::string("name(-1)=") + (n_neg ? n_neg : "<NULL>") + " name(INT32_MAX)=" +
                (n_big ? n_big : "<NULL>"));
    bool nonmember_distinct = true;
    if (n_neg) {
      for (size_t i = 0; i < semb_contract::kSliceStatusNameCount; ++i)
        if (std::strcmp(n_neg, semb_contract::kSliceStatusNames[i]) == 0) nonmember_distinct = false;
    }
    Verdict(nonmember_distinct, "K-07f a non-member value's name is not a member's name", n_neg ? n_neg : "<NULL>");
    // Static storage: the same pointer on every call, still valid across handle lifetimes.
    const char* p1 = semb_status_name(st.ok);
    const char* p2 = semb_status_name(st.ok);
    const char* q1 = semb_status_name(st.null_argument);
    Verdict(p1 && p1 == p2 && q1 && q1 != p1,
            "K-07g the returned pointer is stable across calls (static storage) and per-status",
            std::string("name(SEMB_OK) ") + (p1 == p2 ? "same pointer" : "DIFFERENT pointers"));
    std::string copy_before = p1 ? p1 : "";
    {
      semb_encoder enc = OpenPair(a, st, "K-07h (setup)");
      if (enc) {
        SentinelBuffer buf(a.dims * sizeof(float));
        size_t req = 0;
        semb_fingerprint fp = MakeFingerprint();
        (void)semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), buf.capacity_bytes, &req, &fp);
        (void)semb_encoder_close(enc);
      }
    }
    const char* p3 = semb_status_name(st.ok);
    Verdict(p3 == p1 && p3 && copy_before == p3,
            "K-07h the pointer outlives an encoder handle's whole life (open, encode, close)",
            std::string("before=") + copy_before + " after=" + (p3 ? p3 : "<NULL>"));
  }

  // ---- K-01 open / close round trip; K-02 dims -------------------------------------------------
  {
    const semb_config cfg = MakeConfig(a.model, a.tokenizer, a.append_id);
    semb_encoder enc = nullptr;
    const semb_status s = semb_encoder_open(&cfg, &enc);
    Verdict(s == st.ok && enc != nullptr, "K-01a semb_encoder_open on the pair returns SEMB_OK and a non-NULL handle",
            std::string(Name(s)) + (enc ? ", handle non-NULL" : ", handle NULL"));
    if (enc) {
      uint32_t dims = 0;
      const semb_status sd = semb_encoder_dims(enc, &dims);
      Verdict(sd == st.ok && dims == a.dims, "K-02a semb_encoder_dims reports the artifact's hidden_size",
              std::string(Name(sd)) + " dims=" + std::to_string(dims) + " expected=" + std::to_string(a.dims));
      uint32_t sentinel = 0xDEADBEEF;
      const semb_status sn = semb_encoder_dims(nullptr, &sentinel);
      Verdict(sn == st.null_argument && sentinel == 0xDEADBEEF,
              "K-02b semb_encoder_dims(NULL handle) -> SEMB_NULL_ARGUMENT, out untouched", Name(sn));
      const semb_status so = semb_encoder_dims(enc, nullptr);
      Verdict(so == st.null_argument, "K-02c semb_encoder_dims(enc, NULL) -> SEMB_NULL_ARGUMENT", Name(so));
      const semb_status sc = semb_encoder_close(enc);
      Verdict(sc == st.ok, "K-01b semb_encoder_close returns SEMB_OK", Name(sc));
    }
  }

  // ---- K-03 / K-04 open: NULL pointers and struct_size ------------------------------------------
  {
    semb_config cfg = MakeConfig(a.model, a.tokenizer, a.append_id);
    semb_encoder enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    semb_status s = semb_encoder_open(nullptr, &enc);
    Verdict(s == st.null_argument, "K-03a open(NULL cfg) -> SEMB_NULL_ARGUMENT", Name(s));
    s = semb_encoder_open(&cfg, nullptr);
    Verdict(s == st.null_argument, "K-03b open(cfg, NULL out) -> SEMB_NULL_ARGUMENT", Name(s));
    semb_config c2 = cfg; c2.model_path = nullptr; enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    s = semb_encoder_open(&c2, &enc);
    Verdict(s == st.null_argument && enc == nullptr, "K-03c open with model_path NULL -> SEMB_NULL_ARGUMENT, *out = NULL",
            std::string(Name(s)) + (enc ? " *out NOT cleared" : " *out NULL"));
    semb_config c3 = cfg; c3.tokenizer_path = nullptr; enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    s = semb_encoder_open(&c3, &enc);
    Verdict(s == st.null_argument && enc == nullptr, "K-03d open with tokenizer_path NULL -> SEMB_NULL_ARGUMENT, *out = NULL",
            std::string(Name(s)) + (enc ? " *out NOT cleared" : " *out NULL"));
    const uint32_t sizes[] = {0u, static_cast<uint32_t>(sizeof(semb_config) - 4), static_cast<uint32_t>(sizeof(semb_config) + 4)};
    for (uint32_t sz : sizes) {
      semb_config c4 = cfg; c4.struct_size = sz; enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
      s = semb_encoder_open(&c4, &enc);
      Verdict(s == st.struct_size_mismatch && enc == nullptr,
              "K-04 open with struct_size=" + std::to_string(sz) + " -> SEMB_STRUCT_SIZE_MISMATCH, *out = NULL",
              std::string(Name(s)) + (enc ? " *out NOT cleared" : " *out NULL"));
    }
  }

  // ---- K-05 the artifacts are a trust boundary: refusals at open, *out = NULL ----------------
  {
    semb_encoder enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    const std::string nowhere = a.model + ".does-not-exist";
    semb_config c1 = MakeConfig(nowhere, a.tokenizer, a.append_id);
    semb_status s = semb_encoder_open(&c1, &enc);
    Verdict(s == st.engine_refused && enc == nullptr, "K-05a a model path that does not exist -> SEMB_ENGINE_REFUSED, *out = NULL",
            std::string(Name(s)) + (enc ? " *out NOT cleared" : " *out NULL"));
    enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    const std::string nowhere_t = a.tokenizer + ".does-not-exist";
    semb_config c2 = MakeConfig(a.model, nowhere_t, a.append_id);
    s = semb_encoder_open(&c2, &enc);
    Verdict(s == st.engine_refused && enc == nullptr, "K-05b a tokenizer path that does not exist -> SEMB_ENGINE_REFUSED, *out = NULL",
            std::string(Name(s)) + (enc ? " *out NOT cleared" : " *out NULL"));
    enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    semb_config c3 = MakeConfig(a.model, a.model, a.append_id);  // the model handed as the tokenizer
    s = semb_encoder_open(&c3, &enc);
    Verdict(s != st.ok && enc == nullptr,
            "K-05c the model artifact handed as the tokenizer (no Tokenizer section) is refused, *out = NULL",
            std::string("observed ") + Name(s) + (enc ? " *out NOT cleared" : " *out NULL"));
    if (!a.truncated_tokenizer.empty()) {
      std::ifstream in(a.tokenizer, std::ios::binary);
      std::vector<char> bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
      const size_t keep = bytes.size() > 4096 ? bytes.size() - 4096 : bytes.size() / 2;
      std::ofstream out(a.truncated_tokenizer, std::ios::binary);
      out.write(bytes.data(), static_cast<std::streamsize>(keep));
      out.close();
      enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
      semb_config c4 = MakeConfig(a.model, a.truncated_tokenizer, a.append_id);
      s = semb_encoder_open(&c4, &enc);
      Verdict(s == st.engine_refused && enc == nullptr,
              "K-05d a truncated tokenizer artifact (the engine's own loader refuses it) -> SEMB_ENGINE_REFUSED, *out = NULL",
              std::string(Name(s)) + " (" + std::to_string(keep) + " of " + std::to_string(bytes.size()) + " bytes kept)" +
                  (enc ? " *out NOT cleared" : " *out NULL"));
    } else {
      Missing("K-05d truncated tokenizer artifact refused", "no --truncated-tokenizer scratch path given");
    }
  }

  // ---- K-06 artifact/tokenizer MISMATCH refusal ----------------------------------------------
  {
    semb_encoder enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    if (!a.other_model.empty()) {
      semb_config c1 = MakeConfig(a.other_model, a.tokenizer, a.append_id);
      const semb_status s = semb_encoder_open(&c1, &enc);
      Verdict(s != st.ok && s != st.null_argument && s != st.struct_size_mismatch && enc == nullptr,
              "K-06a a tokenizer whose ids exceed the model's vocab_size is refused at open, *out = NULL",
              std::string("observed ") + Name(s) + (enc ? " *out NOT cleared" : " *out NULL"));
    } else {
      Missing("K-06a tokenizer ids exceed the model's vocab_size", "no --other-model given");
    }
    enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    semb_config c2 = MakeConfig(a.model, a.tokenizer, 1 << 30);  // far past any vocab
    semb_status s = semb_encoder_open(&c2, &enc);
    Verdict(s != st.ok && s != st.null_argument && s != st.struct_size_mismatch && enc == nullptr,
            "K-06b an appended_token_id outside the model's vocabulary (1<<30) is refused at open, *out = NULL",
            std::string("observed ") + Name(s) + (enc ? " *out NOT cleared" : " *out NULL"));
    enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
    semb_config c3 = MakeConfig(a.model, a.tokenizer, -1);
    s = semb_encoder_open(&c3, &enc);
    Verdict(s != st.ok && s != st.null_argument && s != st.struct_size_mismatch && enc == nullptr,
            "K-06c a negative appended_token_id is refused at open, *out = NULL",
            std::string("observed ") + Name(s) + (enc ? " *out NOT cleared" : " *out NULL"));
    if (!a.other_tokenizer.empty()) {
      enc = reinterpret_cast<semb_encoder>(static_cast<uintptr_t>(0x1));
      semb_config c4 = MakeConfig(a.model, a.other_tokenizer, a.append_id);
      s = semb_encoder_open(&c4, &enc);
      Verdict(s != st.ok && s != st.null_argument && s != st.struct_size_mismatch && enc == nullptr,
              "K-06d a foreign tokenizer artifact (id range past this model's vocab_size) is refused at open, *out = NULL",
              std::string("observed ") + Name(s) + (enc ? " *out NOT cleared" : " *out NULL"));
    } else {
      Missing("K-06d foreign tokenizer artifact against this model", "no --other-tokenizer given");
    }
  }

  // ---- K-08 output capacity, required size, no partial writes, alignment (sec 3.1 items 3-4) --
  {
    semb_encoder enc = OpenPair(a, st, "K-08 (setup)");
    if (enc) {
      const size_t need = a.dims * sizeof(float);
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      semb_status s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, nullptr, 0, &req, &fp);
      Verdict(s == st.buffer_too_small && req == need,
              "K-08a the query form (NULL, capacity 0) -> SEMB_BUFFER_TOO_SMALL with required = dims*4",
              std::string(Name(s)) + " required=" + std::to_string(req) + " expected=" + std::to_string(need));
      Verdict(FingerprintUntouched(fp), "K-08b the query form writes no fingerprint", Hex(fp.digest, 4) + "...");
      {
        SentinelBuffer buf(need);
        req = 0;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need - 4, &req, &fp);
        Verdict(s == st.buffer_too_small && req == need && buf.Untouched(need),
                "K-08c capacity dims*4-4 -> SEMB_BUFFER_TOO_SMALL, required written, buffer byte-for-byte untouched",
                std::string(Name(s)) + " required=" + std::to_string(req) + (buf.Untouched(need) ? " untouched" : " WRITTEN"));
      }
      {
        SentinelBuffer buf(need);
        req = 0;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
        Verdict(s == st.ok && req == need && !buf.Untouched(need),
                "K-08d capacity dims*4 exactly -> SEMB_OK, required written on success too, vector written",
                std::string(Name(s)) + " required=" + std::to_string(req));
      }
      {
        SentinelBuffer buf(need + 64);
        req = 0;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need + 64, &req, &fp);
        Verdict(s == st.ok && req == need && buf.UntouchedFrom(need, 64),
                "K-08e capacity dims*4+64 -> SEMB_OK; the 64 bytes past the required size are untouched",
                std::string(Name(s)) + " required=" + std::to_string(req) + (buf.UntouchedFrom(need, 64) ? " tail untouched" : " TAIL WRITTEN"));
      }
      {
        SentinelBuffer buf(need + 16);
        float* mis = reinterpret_cast<float*>(reinterpret_cast<uint8_t*>(buf.Data()) + 4);
        req = kRequiredSentinel;
        s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, mis, need, &req, &fp);
        Verdict(s == st.misaligned_buffer && req == kRequiredSentinel && buf.Untouched(need + 16),
                "K-08f a buffer 4 bytes off 16-byte alignment -> SEMB_MISALIGNED_BUFFER before any output write",
                std::string(Name(s)) + (buf.Untouched(need + 16) ? " untouched" : " WRITTEN"));
      }
      (void)semb_encoder_close(enc);
    }
  }

  // ---- K-09 / K-10 / K-11 encode: NULL and malformed arguments, the empty input, invalid UTF-8 --
  {
    semb_encoder enc = OpenPair(a, st, "K-09 (setup)");
    if (enc) {
      const size_t need = a.dims * sizeof(float);
      SentinelBuffer buf(need);
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      semb_status s = semb_encode(nullptr, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.null_argument && buf.Untouched(need), "K-09a encode(NULL handle) -> SEMB_NULL_ARGUMENT, nothing written", Name(s));
      s = semb_encode(enc, nullptr, 5, buf.Data(), need, &req, &fp);
      Verdict(s == st.null_argument && buf.Untouched(need), "K-09b encode(utf8 NULL, len 5) -> SEMB_NULL_ARGUMENT, nothing written", Name(s));
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, nullptr, &fp);
      Verdict(s == st.null_argument && buf.Untouched(need), "K-09c encode(out_required_bytes NULL) -> SEMB_NULL_ARGUMENT, nothing written", Name(s));
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, nullptr);
      Verdict(s == st.null_argument && buf.Untouched(need), "K-09d encode(out_fingerprint NULL) -> SEMB_NULL_ARGUMENT, nothing written", Name(s));
      semb_fingerprint bad = MakeFingerprint(); bad.struct_size = sizeof(semb_fingerprint) + 8;
      s = semb_encode(enc, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &bad);
      Verdict(s == st.struct_size_mismatch && buf.Untouched(need) && FingerprintUntouched(MakeFingerprint()),
              "K-09e a fingerprint struct_size that is not this build's -> SEMB_STRUCT_SIZE_MISMATCH, nothing written", Name(s));
      s = semb_encode(enc, nullptr, 0, buf.Data(), need, &req, &fp);
      Verdict((s == st.input_empty || s == st.null_argument) && buf.Untouched(need),
              "K-09f encode(utf8 NULL, len 0) is refused (SEMB_INPUT_EMPTY or SEMB_NULL_ARGUMENT), nothing written",
              std::string("observed ") + Name(s));
      req = kRequiredSentinel;
      s = semb_encode(enc, "", 0, buf.Data(), need, &req, &fp);
      Verdict(s == st.input_empty && req == kRequiredSentinel && buf.Untouched(need),
              "K-10a the empty string -> SEMB_INPUT_EMPTY (sec 8 C4), nothing written", Name(s));
      s = semb_encode(enc, " ", 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.ok, "K-10b a whitespace-only input is one token and is ACCEPTED under PS-N (D-SLM4729)", Name(s));
      const char bad1[] = {static_cast<char>(0xFF)};
      const char bad2[] = {'a', static_cast<char>(0x80), 'b'};
      const char bad3[] = {static_cast<char>(0xE4), static_cast<char>(0xBD)};
      const char bad4[] = {static_cast<char>(0xED), static_cast<char>(0xA0), static_cast<char>(0x80)};  // UTF-16 surrogate
      struct { const char* p; size_t n; const char* what; } bads[] = {
          {bad1, sizeof(bad1), "0xFF"}, {bad2, sizeof(bad2), "lone continuation 0x80"},
          {bad3, sizeof(bad3), "truncated 3-byte sequence"}, {bad4, sizeof(bad4), "encoded surrogate U+D800"}};
      for (const auto& b : bads) {
        SentinelBuffer buf2(need);
        req = kRequiredSentinel;
        s = semb_encode(enc, b.p, b.n, buf2.Data(), need, &req, &fp);
        Verdict(s != st.ok && req == kRequiredSentinel && buf2.Untouched(need),
                std::string("K-11 invalid UTF-8 (") + b.what + ") is rejected (sec 8 C4), nothing written",
                std::string("observed ") + Name(s) + (buf2.Untouched(need) ? " untouched" : " WRITTEN"));
      }
      (void)semb_encoder_close(enc);
    }
  }

  // ---- K-12 the context cap: at cap accepted, cap+1 refused, nothing written ----------------
  if (a.context_cap > 0) {
    semb_encoder enc = OpenPair(a, st, "K-12 (setup)");
    if (enc) {
      const size_t need = a.dims * sizeof(float);
      // "ab" tokenizes to two single-byte tokens in the synthetic pair (m-017);
      // n content tokens + the appended token = n + 1 positions.
      std::string at_cap, over_cap;
      for (size_t i = 0; i + 1 < a.context_cap; ++i) at_cap += (i % 2 == 0 ? 'a' : 'b');   // cap-1 content -> cap positions
      for (size_t i = 0; i < a.context_cap; ++i) over_cap += (i % 2 == 0 ? 'a' : 'b');     // cap content -> cap+1 positions
      SentinelBuffer b1(need);
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      semb_status s = semb_encode(enc, at_cap.data(), at_cap.size(), b1.Data(), need, &req, &fp);
      Verdict(s == st.ok, "K-12a a document of exactly context_cap positions (content + appended token) is accepted",
              std::string(Name(s)) + " content=" + std::to_string(at_cap.size()));
      SentinelBuffer b2(need);
      req = kRequiredSentinel;
      s = semb_encode(enc, over_cap.data(), over_cap.size(), b2.Data(), need, &req, &fp);
      Verdict(s != st.ok && req == kRequiredSentinel && b2.Untouched(need),
              "K-12b context_cap+1 positions is refused (sec 8 C4: 'context_cap+1 -> rejected'), nothing written",
              std::string("observed ") + Name(s) + (b2.Untouched(need) ? " untouched" : " WRITTEN"));
      (void)semb_encoder_close(enc);
    }
  } else {
    Missing("K-12 context cap edges", "no --context-cap given (the real artifact's 32,768 is not driven here)");
  }

  // ---- K-13 opaque-handle ownership (sec 3.1 item 5) --------------------------------------------
  {
    semb_encoder enc = OpenPair(a, st, "K-13 (setup)");
    if (enc) {
      semb_encoder copy = enc;  // a copy of the VALUE grants no second lifetime
      semb_status s = semb_encoder_close(enc);
      Verdict(s == st.ok, "K-13a first close -> SEMB_OK", Name(s));
      s = semb_encoder_close(enc);
      Verdict(s == st.invalid_handle, "K-13b double close -> SEMB_INVALID_HANDLE, never undefined", Name(s));
      s = semb_encoder_close(copy);
      Verdict(s == st.invalid_handle, "K-13c closing a copied handle value after the close -> SEMB_INVALID_HANDLE", Name(s));
      uint32_t dims = 0;
      s = semb_encoder_dims(copy, &dims);
      Verdict(s == st.invalid_handle, "K-13d dims on a closed handle -> SEMB_INVALID_HANDLE", Name(s));
      const size_t need = a.dims * sizeof(float);
      SentinelBuffer buf(need);
      size_t req = kRequiredSentinel;
      semb_fingerprint fp = MakeFingerprint();
      s = semb_encode(copy, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &fp);
      Verdict(s == st.invalid_handle && req == kRequiredSentinel && buf.Untouched(need),
              "K-13e encode on a closed handle -> SEMB_INVALID_HANDLE, nothing written", Name(s));
    }
    semb_status s = semb_encoder_close(nullptr);
    Verdict(s == st.null_argument, "K-13f close(NULL) -> SEMB_NULL_ARGUMENT (sec 3.1 item 7: any required pointer NULL)", Name(s));
    semb_encoder e1 = OpenPair(a, st, "K-13g (setup 1)");
    semb_encoder e2 = OpenPair(a, st, "K-13g (setup 2)");
    if (e1 && e2) {
      const size_t need = a.dims * sizeof(float);
      SentinelBuffer b1(need), b2(need);
      size_t req = 0;
      semb_fingerprint fp = MakeFingerprint();
      (void)semb_encoder_close(e1);
      s = semb_encode(e2, kDoc, sizeof(kDoc) - 1, b2.Data(), need, &req, &fp);
      Verdict(e1 != e2 && s == st.ok, "K-13g two handles are distinct; closing one leaves the other encoding",
              std::string(Name(s)));
      (void)semb_encoder_close(e2);
    }
    semb_encoder stale = OpenPair(a, st, "K-13h (setup stale)");
    if (stale) {
      (void)semb_encoder_close(stale);
      semb_encoder replacement = OpenPair(a, st, "K-13h (setup replacement)");
      if (replacement) {
        uint32_t stale_dims = 0xC5C5C5C5u;
        const semb_status dims_status = semb_encoder_dims(stale, &stale_dims);
        const semb_status close_status = semb_encoder_close(stale);
        Verdict(replacement != stale && dims_status == st.invalid_handle &&
                    close_status == st.invalid_handle && stale_dims == 0xC5C5C5C5u,
                "K-13h reopening cannot recycle a published address or make the stale handle valid again",
                std::string("replacement ") + (replacement == stale ? "ALIASED" : "distinct") +
                    "; dims=" + Name(dims_status) + "; close=" + Name(close_status));
        (void)semb_encoder_close(replacement);
      }
    }
  }

  // ---- K-14 the fingerprint IN/OUT struct: preserved size, stable across encodes and handles --
  {
    semb_encoder e1 = OpenPair(a, st, "K-14 (setup 1)");
    if (e1) {
      const size_t need = a.dims * sizeof(float);
      SentinelBuffer buf(need);
      size_t req = 0;
      semb_fingerprint f1 = MakeFingerprint(), f2 = MakeFingerprint(), f3 = MakeFingerprint();
      const char other[] = "a completely different document, with more words in it";
      semb_status s1 = semb_encode(e1, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &f1);
      semb_status s2 = semb_encode(e1, other, sizeof(other) - 1, buf.Data(), need, &req, &f2);
      semb_status s3 = semb_encode(e1, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &f3);
      const bool same = std::memcmp(f1.digest, f2.digest, 32) == 0 && std::memcmp(f1.digest, f3.digest, 32) == 0;
      const bool written = !FingerprintUntouched(f1);
      Verdict(s1 == st.ok && s2 == st.ok && s3 == st.ok && same && written &&
                  f1.struct_size == sizeof(semb_fingerprint),
              "K-14a the fingerprint is written on SEMB_OK, is the HANDLE's (identical across documents), struct_size preserved",
              std::string(Name(s1)) + " digest=" + Hex(f1.digest, 8) + "... " + (same ? "identical" : "DIFFERS across documents"));
      semb_encoder e2 = OpenPair(a, st, "K-14b (setup 2)");
      if (e2) {
        semb_fingerprint f4 = MakeFingerprint();
        semb_status s4 = semb_encode(e2, kDoc, sizeof(kDoc) - 1, buf.Data(), need, &req, &f4);
        Verdict(s4 == st.ok && std::memcmp(f1.digest, f4.digest, 32) == 0,
                "K-14b a second handle on the same pair reports the identical fingerprint",
                Hex(f4.digest, 8) + "...");
        (void)semb_encoder_close(e2);
      }
      (void)semb_encoder_close(e1);
    }
  }

  std::printf("\nu1_raw_text_contract_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
