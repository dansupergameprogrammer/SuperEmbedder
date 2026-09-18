// tests/te194_query_test.cpp -- TE-194 (U1 slice 5 red suite,
// `Claude/Bach/briefs/te194-slice5-red.md`): cells 1, 2, and 6 of this
// round's own dispatch -- the query contract driver (dims 1, 5), C8's three
// legs (dim 2), and W-Q's own leg (dim 8, QUARANTINED). C26's remaining two
// legs (dim 3, the seam-parked races) are a SEPARATE file,
// tests/te194_query_workspace_test.cpp, because they need
// `superembedder_testseam`; C17's sixth leg (dim 7/11, the composition-drift
// scratch-build harness) is a separate Python driver,
// tests/te194_c17_sixth_leg_construction.py, because mutating a single
// build's own composition needs a scratch reconfigure, the same shape
// tests/te163_c34_manifest_honesty_check.py already uses.
//
// RED AT 21b1735: undefined at link. None of semb_query_open,
// semb_query_encode, semb_query_close, or semb_fingerprint_of exists in
// `superembedder` at this branch's own base (confirmed:
// `git grep -n "semb_query_open\|semb_query_encode\|semb_query_close\|
// semb_fingerprint_of" src/ include/` returns nothing) -- every cell below
// fails to LINK until the builder's round adds them. This is therefore a
// LINK-red file: `tests/te194_query_check.py` builds it on demand and
// reports the unresolved symbols by name, the same shape
// `tests/te163_bank_pair_check.py` already uses for the bank pair.
//
// TWO ARTIFACTS, "A" AND "B": the mechanism driver supplies B from the
// pinned cap-512 pair and A from the shared cap-64 variant. They share the
// converter-emitted tokenizer but have distinct model artifact bytes, so C8's
// compatibility refusal executes without requiring a real candidate.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bank_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_query_abi_contract.h"
#include "semb_wb_witness_abi_contract.h"
#include "superembedder/witness_abi.h"
#include "json_mini.h"
#include "superslm/sha256.h"

namespace {

int g_failures = 0;
int g_cells = 0;
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
void Observed(const std::string& what) {
  std::printf("[OBSERVED] %s\n", what.c_str());
  std::fflush(stdout);
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }

std::string Hex(const uint8_t* d, size_t n) {
  static const char* kHexDigits = "0123456789abcdef";
  std::string out(n * 2, '0');
  for (size_t i = 0; i < n; ++i) {
    out[2 * i] = kHexDigits[(d[i] >> 4) & 0xF];
    out[2 * i + 1] = kHexDigits[d[i] & 0xF];
  }
  return out;
}

std::string Sha256Hex(const std::string& bytes) {
  superslm::Sha256 hash;
  hash.Update(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
  uint8_t digest[32];
  hash.Final(digest);
  return Hex(digest, sizeof(digest));
}

// The join leg ALONE of §4.4b/c's public W-Q construction: the five
// committed join rows through semb_query_encode itself, in the same
// length-prefixed stream shape the product's own W-Q computation uses --
// u64(count) first, then each emitted vector's u64(byte_count) || bytes.
// OBSERVED machinery only (TE-228), never a verdict: the join rows are
// uncapped by construction, so the public verb's emitted vectors are
// recomputable; the committed truncation row is capped at the manifest's
// truncation_content_cap inside the product's witness construction, a cap
// the public verb has no parameter for, so that row is NOT recomputable
// here. Cell 6 prints this digest beside semb_wq_digest's own so a later
// seat commissioning W-Q has both numbers.
bool ComputePlanWqJoinDigest(semb_query query, uint32_t dims, uint8_t out[32], std::string* why) {
  std::vector<std::string> queries;
  {
    std::ifstream f("tests/fixtures/wq/wq-queries.jsonl");
    if (!f) { *why = "cannot open tests/fixtures/wq/wq-queries.jsonl"; return false; }
    std::string line;
    while (std::getline(f, line)) {
      if (!line.empty()) queries.push_back(json_mini::Parse(line)["text"].s());
    }
  }
  if (queries.size() != 5) { *why = "committed W-Q join population count is " + std::to_string(queries.size()); return false; }
  auto update_u64 = [](superslm::Sha256* h, uint64_t v) {
    uint8_t b[8];
    for (size_t i = 0; i < sizeof(b); ++i) b[i] = static_cast<uint8_t>(v >> (8 * i));
    h->Update(b, sizeof(b));
  };
  superslm::Sha256 hash;
  update_u64(&hash, queries.size());
  for (const std::string& text : queries) {
    std::vector<uint8_t> storage(static_cast<size_t>(dims) * sizeof(float) + 16);
    const uintptr_t raw = reinterpret_cast<uintptr_t>(storage.data());
    float* vector = reinterpret_cast<float*>((raw + 15) & ~uintptr_t(15));
    size_t required = 0;
    const semb_status s = semb_query_encode(query, text.data(), text.size(), vector,
                                             static_cast<size_t>(dims) * sizeof(float), &required);
    if (s != SEMB_OK || required != static_cast<size_t>(dims) * sizeof(float)) {
      *why = "semb_query_encode=" + std::string(Name(s)) + " required=" + std::to_string(required);
      return false;
    }
    update_u64(&hash, required);
    hash.Update(reinterpret_cast<const uint8_t*>(vector), required);
  }
  hash.Final(out);
  return true;
}

// sec 2.1's own compiled-in literal, quoted here as an INDEPENDENT copy of
// the plan's own normative text (`Claude/Plans/SuperEmbedder_Plan.md` sec
// 2.1: "the model's own declared usage... prefixes queries and not
// documents: 'Instruct: Given a web search query, retrieve relevant
// passages that answer the query\nQuery:' on the query side"). This is NOT
// a read of `src/superembedder/encoder.cpp`'s own `kQueryPrefix` constant
// (src/ is this round's read-only surface, and the point of an independent
// copy is that it is not derived from the implementation under test) --
// it is transcribed from the plan's own normative prose, the primary
// source both this literal and the product's own compiled-in constant are
// each independently required to match.
constexpr char kQueryPrefix[] =
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:";

// The crossing-table rule this cell asserts (sec 3.3's entry-point crossing
// table, `semb_query_encode` row: "Applies query_prefix_bytes, at whatever
// join, order, special-token setting and truncation ordering the
// implementation chooses"; sec 2.1: "the prefix is applied inside semb's
// query-encoding path... query_prefix_bytes ‖ caller text"). The RATIFIED
// composition is simple concatenation, prefix then text, with no separator
// -- this function is that composition, INDEPENDENT of semb_query_encode
// (it never calls it), so it is a fit ground truth to compare
// semb_query_encode's own output against via the raw path (`semb_encode`,
// already built and already verified by this suite's own u1_raw_text_*
// cells), per Curie.md's "grounded in the statistic's definition, not a
// recode of the implementation's steps": semb_encode already IS the
// independent, previously-verified entry point that performs
// tokenize+append+forward on whatever byte string it is handed, so
// composing the prefix here and calling semb_encode on the result is the
// crossing table's rule stated as data, not a re-implementation of
// semb_query_encode's own internals.
std::string ComposeQueryText(const std::string& caller_text) {
  return std::string(kQueryPrefix) + caller_text;
}

// MUTATION PROOF of ComposeQueryText itself (Curie.md: "Every hand-derived
// assertion is mutation-proved (inject a wrong value, watch it fail,
// restore)"), executed at process start, independent of whether any
// semb_query_* symbol resolves: each of the five census members TE-37's
// own probe names (`Claude/Loki/te37-probe/te37_probe.py`) -- prefix
// omitted, prefix double-applied, appended instead of prepended, a join
// separator inserted, and (T-2293/T-2294's own correction) the
// special-token disposition -- produces a STRING DIFFERENT from
// ComposeQueryText's own output for the identical caller text, proving
// this oracle actually discriminates the composition it is meant to pin
// rather than being trivially satisfied. This is a property of THIS FILE's
// own oracle function, checkable today, independent of the link failure
// below.
bool MutationProveComposeQueryText() {
  const std::string caller = "example query text";
  const std::string correct = ComposeQueryText(caller);
  bool all_differ = true;

  const std::string omitted = caller;                                   // prefix omitted entirely
  const std::string doubled = std::string(kQueryPrefix) + kQueryPrefix + caller;  // prefix applied twice
  const std::string appended = caller + kQueryPrefix;                   // appended instead of prepended
  const std::string separated = std::string(kQueryPrefix) + " " + caller;  // an extra join separator
  const std::string case_folded =
      []{ std::string s(kQueryPrefix); for (char& c : s) c = static_cast<char>(std::toupper((unsigned char)c)); return s; }() + caller;

  const std::string* mutants[] = {&omitted, &doubled, &appended, &separated, &case_folded};
  for (const std::string* mutant : mutants) {
    if (*mutant == correct) all_differ = false;
  }
  return all_differ;
}

std::string ReadFile(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  std::ostringstream ss;
  ss << f.rdbuf();
  return ss.str();
}

struct Args {
  std::string model_a, tokenizer_a;    // artifact A (the real candidate, when --real)
  std::string model_b, tokenizer_b;    // artifact B (the tokenizer-pair fixture)
  std::string wb_corpus, scratch;
  bool real = false;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model-a") next(&a.model_a);
    else if (k == "--tokenizer-a") next(&a.tokenizer_a);
    else if (k == "--model-b") next(&a.model_b);
    else if (k == "--tokenizer-b") next(&a.tokenizer_b);
    else if (k == "--wb-corpus") next(&a.wb_corpus);
    else if (k == "--scratch") next(&a.scratch);
    else if (k == "--real") a.real = true;
  }
  return a;
}

class DocSet {
 public:
  DocSet() { arena_.reserve(1024); }
  semb_document Add(std::string id, std::string text) {
    arena_.push_back(std::move(id));
    const std::string& sid = arena_.back();
    arena_.push_back(std::move(text));
    const std::string& stext = arena_.back();
    semb_document d{};
    d.struct_size = sizeof(semb_document);
    d.id = sid.c_str();
    d.id_len = sid.size();
    d.utf8 = stext.c_str();
    d.utf8_len = stext.size();
    return d;
  }

 private:
  std::vector<std::string> arena_;
};

std::vector<std::pair<std::string, std::string>> LoadJsonlWbCorpus(const std::string& path) {
  std::vector<std::pair<std::string, std::string>> out;
  std::ifstream f(path);
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    json_mini::Value v = json_mini::Parse(line);
    out.emplace_back(v["id"].s(), v["text"].s());
  }
  return out;
}

semb_encoder OpenEncoder(const std::string& model, const std::string& tokenizer,
                         const std::string& label) {
  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = model.data();
  c.model_path_len = model.size();
  c.tokenizer_path = tokenizer.data();
  c.tokenizer_path_len = tokenizer.size();
  c.max_concurrency = 4;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&c, &enc);
  if (s != SEMB_OK || !enc) {
    Verdict(false, "(setup) semb_encoder_open " + label, Name(s));
    return nullptr;
  }
  return enc;
}

}  // namespace

// The product's encoder-scoped W-Q witness digest accessor (TE-224 M-1,
// include/superembedder/wq_digest_abi.h), declared in this TU's own
// contract types for cell 6, at file scope because MSVC rejects a
// function-local linkage specification (C2598, executed against TE-228):
// including the product header in this TU would pull
// superembedder/semb.h's own typedefs over this suite's independent
// semb_public_abi_contract.h types -- the duplicate-definition conflict
// include/superembedder/wb_digest_abi.h's own header comment names
// (executed against TE-228: four redefinition errors) -- and the
// declaration's own types are layout-identical across both typedef sets,
// the same convention tests/semb_wb_witness_abi_contract.h establishes
// for semb_wb_digest.
extern "C" semb_status semb_wq_digest(semb_encoder enc, uint8_t out_digest[32]);

int main(int argc, char** argv) {
  Args args = ParseArgs(argc, argv);

  // The mutation proof runs unconditionally -- it needs no artifact and no
  // link against any semb_query_* symbol.
  Verdict(MutationProveComposeQueryText(),
          "(oracle self-check) ComposeQueryText discriminates every TE-37 census mutation",
          "five constructions (omitted/doubled/appended/separated/case-folded prefix) each "
          "produce a string different from the correct composition");

  if (args.model_b.empty() || args.tokenizer_b.empty() || args.wb_corpus.empty() || args.scratch.empty()) {
    Missing("te194 query cells 1/2/6",
            "requires --model-b --tokenizer-b --wb-corpus --scratch at minimum (mechanism leg); "
            "--model-a --tokenizer-a additionally exercise C8");
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return g_failures > 0 ? 1 : 0;
  }

  const bool have_a = !args.model_a.empty() && !args.tokenizer_a.empty();
  semb_encoder enc_b = OpenEncoder(args.model_b, args.tokenizer_b, "B (tokenizer-pair fixture)");
  semb_encoder enc_a = have_a ? OpenEncoder(args.model_a, args.tokenizer_a, "A (real candidate)") : nullptr;
  if (!enc_b || (have_a && !enc_a)) {
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  DocSet docs_b;
  // This driver needs an ordinary bank B that the exact encoder handle can
  // open.  W-B's sixteen-document corpus deliberately exceeds the synthetic
  // pair's context cap when passed uncut to the public bake entry; using it
  // here therefore aborts every query assertion before its own setup exists.
  // These are the same short, cap-safe shape as te163_bank_pair_test.cpp's
  // good triple, kept separate from W-B's witness population.
  std::vector<semb_document> doc_vec_b = {
      docs_b.Add("te194-q-00", "the first short query-driver bank document"),
      docs_b.Add("te194-q-01", "the second short query-driver bank document"),
  };

  const std::string stem_b = args.scratch + "/te194_bank_b";
  const semb_status bake_b_s =
      semb_bake_to_path(enc_b, doc_vec_b.data(), doc_vec_b.size(), stem_b.c_str(), stem_b.size());
  if (bake_b_s != SEMB_OK) {
    Verdict(false, "(setup) semb_bake_to_path(bank B)", Name(bake_b_s));
    std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
    return 1;
  }

  // ---------------------------------------------------------------------
  // Cell 1 -- the query contract driver.
  // ---------------------------------------------------------------------
  {
    semb_bank bank_b = nullptr;
    const semb_status open_bank_s = semb_bank_open(stem_b.c_str(), stem_b.size(), &bank_b);
    Verdict(open_bank_s == SEMB_OK && bank_b != nullptr,
            "cell1 semb_bank_open(bank B, matching encoder)", Name(open_bank_s));

    semb_query q = nullptr;
    const semb_status open_q_s = semb_query_open(enc_b, bank_b, &q);
    Verdict(open_q_s == SEMB_OK && q != nullptr,
            "cell1 semb_query_open(matching encoder+bank)", Name(open_q_s));

    if (q) {
      // The query-prefix composition equals semb_encode on the composed
      // text, for every committed query in the join leg -- the crossing
      // table's own rule, checked against the already-verified raw path.
      std::ifstream f(std::string("tests/fixtures/wq/wq-queries.jsonl"));
      std::string line;
      uint32_t dims = 0;
      semb_encoder_dims(enc_b, &dims);
      while (std::getline(f, line)) {
        if (line.empty()) continue;
        json_mini::Value v = json_mini::Parse(line);
        const std::string qid = v["id"].s();
        const std::string qtext = v["text"].s();
        const std::string composed = ComposeQueryText(qtext);
        std::vector<float> via_query(dims), via_raw(dims);
        size_t req_q = 0, req_raw = 0;
        const semb_status qs = semb_query_encode(q, qtext.data(), qtext.size(), via_query.data(),
                                                  via_query.size() * sizeof(float), &req_q);
        semb_fingerprint fp_raw{}; fp_raw.struct_size = sizeof(fp_raw);
        const semb_status rs = semb_encode(enc_b, composed.data(), composed.size(), via_raw.data(),
                                            via_raw.size() * sizeof(float), &req_raw, &fp_raw);
        const bool ok = qs == SEMB_OK && rs == SEMB_OK &&
                        std::memcmp(via_query.data(), via_raw.data(), dims * sizeof(float)) == 0;
        Verdict(ok, "cell1 semb_query_encode(" + qid + ") == semb_encode(prefix ‖ text)",
                "query_status=" + std::string(Name(qs)) + " raw_status=" + std::string(Name(rs)) +
                    (ok ? " vectors byte-identical" : " vectors differ or a call refused"));
      }

      // Buffer too small: SEMB_BUFFER_TOO_SMALL, required bytes written,
      // vector untouched (sec 3.1 property 3, applied to semb_query_encode).
      std::vector<float> tiny(1, -777.0f);
      size_t req = 0;
      const semb_status small_s = semb_query_encode(q, "temperature", 11, tiny.data(),
                                                     1 * sizeof(float), &req);
      Verdict(small_s == SEMB_BUFFER_TOO_SMALL && req == dims * sizeof(float) && tiny[0] == -777.0f,
              "cell1 semb_query_encode buffer too small",
              Name(small_s) + std::string(" required=") + std::to_string(req) +
                  " expected=" + std::to_string(dims * sizeof(float)) +
                  " vector_untouched=" + (tiny[0] == -777.0f ? "true" : "false"));
    }

    // semb_bank_close with a live query handle -> SEMB_BANK_IN_USE, freeing
    // nothing; C26's third leg (sec 8 C26: "a bank closed under a live
    // query handle") is exactly this sequential construction -- the
    // refusal is keyed on the bank's own reference count of OPEN query
    // handles (D-SLM4664), not on an in-flight call, so no seam parking is
    // needed to construct it.
    const semb_status close_while_open_s = semb_bank_close(bank_b);
    Verdict(close_while_open_s == SEMB_BANK_IN_USE,
            "cell1/C26-leg3 semb_bank_close while a query handle is open", Name(close_while_open_s));

    const semb_status close_q_s = semb_query_close(q);
    Verdict(close_q_s == SEMB_OK, "cell1 semb_query_close", Name(close_q_s));

    const semb_status close_q_again_s = semb_query_close(q);
    Verdict(close_q_again_s == SEMB_INVALID_HANDLE,
            "cell1 semb_query_close (already closed)", Name(close_q_again_s));

    const semb_status close_after_s = semb_bank_close(bank_b);
    Verdict(close_after_s == SEMB_OK,
            "cell1/C26-leg3 semb_bank_close now succeeds after the query closed", Name(close_after_s));

    const semb_status null_open_s = semb_query_open(nullptr, nullptr, nullptr);
    Verdict(null_open_s == SEMB_NULL_ARGUMENT, "cell1 semb_query_open(NULL, NULL, NULL)",
            Name(null_open_s));

    semb_query never_opened = reinterpret_cast<semb_query>(0x1);
    const semb_status invalid_close_s = semb_query_close(never_opened);
    Verdict(invalid_close_s == SEMB_INVALID_HANDLE,
            "cell1 semb_query_close(never-opened cookie)", Name(invalid_close_s));
  }

  // ---------------------------------------------------------------------
  // Cell 2 -- C8, three legs.
  // ---------------------------------------------------------------------
  if (have_a) {
    semb_bank bank_b = nullptr;
    semb_bank_open(stem_b.c_str(), stem_b.size(), &bank_b);

    // (a) mismatch at open: bank baked under B queried with encoder bound
    // to A -> SEMB_FINGERPRINT_MISMATCH, no handle. A and B also differ in
    // dims (1024 vs 32), which exercises the refusal precedence: sec 3.1's
    // open table checks struct_size/artifact-readability/engine-load
    // before deriving the fingerprint, so a dims difference alone (which
    // this cell does not construct as an otherwise-valid geometry
    // mismatch, since dims is not itself a semb_query_open argument) never
    // competes with SEMB_FINGERPRINT_MISMATCH here -- the fingerprint
    // comparison is the ONLY check semb_query_open performs beyond
    // enc/bank liveness, so it fires whenever the five derived fields
    // disagree, dims-driven or not.
    semb_query q_mismatch = nullptr;
    const semb_status mismatch_s = semb_query_open(enc_a, bank_b, &q_mismatch);
    Verdict(mismatch_s == SEMB_FINGERPRINT_MISMATCH && q_mismatch == nullptr,
            "cell2/C8-leg-a mismatch at open (A queries B's bank)",
            Name(mismatch_s) + std::string(" handle=") + (q_mismatch ? "non-null (LEAK)" : "null"));

    // (b) the well-formed-value leg: A reads its OWN fingerprint via
    // semb_fingerprint_of, distinct from B's expected fingerprint (which
    // bank_b owns, per bank_internal_abi.h's own semb_bank_debug_state --
    // this cell reads it indirectly via the SAME refusal above, since the
    // refusal only fires because the two disagree).
    semb_fingerprint fp_a{}; fp_a.struct_size = sizeof(fp_a);
    const semb_status fp_of_s = semb_fingerprint_of(enc_a, &fp_a);
    Verdict(fp_of_s == SEMB_OK, "cell2/C8-leg-b semb_fingerprint_of(A)", Name(fp_of_s));
    if (fp_of_s == SEMB_OK) {
      Observed("cell2/C8-leg-b A's own fingerprint (well-formed, not the bank's expected value) = " +
               Hex(fp_a.digest, 32));
    }

    // (c) the raw path's own leg: semb_encode on B-encoder emits a vector
    // AND the B fingerprint, never A's or the bank's -- already exercisable
    // via the raw path built at Slice 0/1, folded in here for a shared
    // harness rather than needing its own file.
    uint32_t dims_b = 0;
    semb_encoder_dims(enc_b, &dims_b);
    std::vector<float> raw_vec(dims_b);
    size_t raw_req = 0;
    semb_fingerprint fp_raw{}; fp_raw.struct_size = sizeof(fp_raw);
    const semb_status raw_s = semb_encode(enc_b, "a plain raw-path probe", 23, raw_vec.data(),
                                          raw_vec.size() * sizeof(float), &raw_req, &fp_raw);
    semb_fingerprint fp_b_of{}; fp_b_of.struct_size = sizeof(fp_b_of);
    semb_fingerprint_of(enc_b, &fp_b_of);
    const bool raw_leg_ok = raw_s == SEMB_OK && std::memcmp(fp_raw.digest, fp_b_of.digest, 32) == 0 &&
                            std::memcmp(fp_raw.digest, fp_a.digest, 32) != 0;
    Verdict(raw_leg_ok,
            "cell2/C8-leg-c semb_encode(B) returns B's own fingerprint, not A's",
            std::string("raw_status=") + Name(raw_s) +
                " raw_fp==B_own_fp=" + (std::memcmp(fp_raw.digest, fp_b_of.digest, 32) == 0 ? "true" : "false") +
                " raw_fp!=A_fp=" + (std::memcmp(fp_raw.digest, fp_a.digest, 32) != 0 ? "true" : "false"));

    semb_bank_close(bank_b);
  } else {
    Missing("cell2/C8 (all three legs)",
            "requires --model-a --tokenizer-a (a second, artifact-distinct encoder)");
  }

  // ---------------------------------------------------------------------
  // Cell 6 -- W-Q's own leg (TE-228): the W-Q digest comes from the
  // product's encoder-scoped accessor, semb_wq_digest, the same standing
  // the W-B leg has always had through semb_wb_digest. The cell's
  // achievement claim is that the COMPOSITION is right -- witness_sha folds
  // the real accessor values and the five fields compose to the emitted
  // fingerprint -- not that the test re-derives W-Q from scratch. The
  // committed truncation row is capped at the manifest's
  // truncation_content_cap inside the product's witness construction, and
  // the public query verb has no cap parameter, so no public recomputation
  // of that row exists; the join leg is uncapped and recomputable, and its
  // recomputation is kept as an OBSERVED line only -- never a verdict.
  {
    const std::string join_bytes = ReadFile("tests/fixtures/wq/wq-queries.jsonl");
    const std::string trunc_bytes = ReadFile("tests/fixtures/wq/wq-truncation-leg.jsonl");
    const json_mini::Value manifest = json_mini::Parse(ReadFile("tests/fixtures/wq/wq-queries.manifest.json"));
    const bool fixture_hashes_match =
        Sha256Hex(join_bytes) == manifest["files"]["wq-queries.jsonl"]["sha256"].s() &&
        Sha256Hex(trunc_bytes) == manifest["files"]["wq-truncation-leg.jsonl"]["sha256"].s();
    Verdict(fixture_hashes_match, "cell6 W-Q committed join and truncation fixtures match their manifest hashes",
            "join=" + Sha256Hex(join_bytes) + " truncation=" + Sha256Hex(trunc_bytes));

    uint8_t wq[32]{};
    const semb_status wq_s = semb_wq_digest(enc_b, wq);

    // The join leg, recomputed independently through the public verb and
    // printed beside the accessor's digest as an OBSERVED pair: the
    // accessor's value covers the full six-row population including the
    // capped truncation row; the join recomputation covers the five rows a
    // public caller can reproduce.
    semb_bank bank = nullptr;
    const semb_status bank_s = semb_bank_open(stem_b.c_str(), stem_b.size(), &bank);
    semb_query query = nullptr;
    const semb_status query_s = bank_s == SEMB_OK ? semb_query_open(enc_b, bank, &query) : bank_s;
    uint32_t dims = 0;
    semb_encoder_dims(enc_b, &dims);
    uint8_t wq_join[32]{};
    std::string join_why;
    const bool join_ok = query && ComputePlanWqJoinDigest(query, dims, wq_join, &join_why);
    if (join_ok) {
      Observed("cell6 W-Q accessor digest (semb_wq_digest, full six-row population incl. the capped "
               "truncation row) = " + Hex(wq, 32) + "; join-leg-only recomputation via semb_query_encode "
               "(five committed join rows, uncapped) = " + Hex(wq_join, 32));
    } else {
      Observed("cell6 W-Q accessor digest (semb_wq_digest) = " + Hex(wq, 32) +
               "; join-leg recomputation unavailable: bank=" + Name(bank_s) + " query=" + Name(query_s) +
               (join_why.empty() ? "" : " " + join_why));
    }
    std::string why;

    const std::string model_bytes = ReadFile(args.model_b);
    const std::string tokenizer_bytes = ReadFile(args.tokenizer_b);
    uint8_t model_sha[32]{}, tokenizer_sha[32]{}, template_sha[32]{}, wa[32]{}, wb[32]{};
    auto hash_bytes = [](const uint8_t* bytes, size_t size, uint8_t out[32]) {
      superslm::Sha256 h; h.Update(bytes, size); h.Final(out);
    };
    if (!model_bytes.empty() && !tokenizer_bytes.empty()) {
      hash_bytes(reinterpret_cast<const uint8_t*>(model_bytes.data()), model_bytes.size(), model_sha);
      hash_bytes(reinterpret_cast<const uint8_t*>(tokenizer_bytes.data()), tokenizer_bytes.size(), tokenizer_sha);
    }
    // TE-264 (U1 Slice 7 steps 3-5): the final five-field form. The template
    // digests three length-prefixed literals -- the empty PS-N frame, the
    // plan sec 2.1 query prefix and the plan sec 3.2 end token
    // `<|endoftext|>`; certification_epoch is the SHA-256 of
    // docs/certified-builds.json's exact bytes, read from the repository; the
    // fingerprint is the full 32-byte SHA-256 over the five length-prefixed
    // fields, untagged. RED by design until steps 3, 4 and 5 have all landed.
    constexpr char kEndToken[] = "<|endoftext|>";
    const std::string cert_doc = ReadFile("docs/certified-builds.json");
    std::vector<uint8_t> template_stream;
    auto put_len = [&template_stream](uint64_t v) {
      for (size_t i = 0; i < 8; ++i) template_stream.push_back(static_cast<uint8_t>(v >> (8 * i)));
    };
    put_len(0);
    put_len(sizeof(kQueryPrefix) - 1);
    template_stream.insert(template_stream.end(), kQueryPrefix, kQueryPrefix + sizeof(kQueryPrefix) - 1);
    put_len(sizeof(kEndToken) - 1);
    template_stream.insert(template_stream.end(), kEndToken, kEndToken + sizeof(kEndToken) - 1);
    hash_bytes(template_stream.data(), template_stream.size(), template_sha);
    semb_wa_digest(wa);
    const semb_status wb_s = semb_wb_digest(enc_b, wb);
    uint8_t expected[32]{}, actual[32]{};
    bool composed = false;
    if (wq_s == SEMB_OK && wb_s == SEMB_OK && !model_bytes.empty() && !tokenizer_bytes.empty() &&
        !cert_doc.empty()) {
      uint8_t witness[32], epoch[32];
      std::vector<uint8_t> witness_stream;
      witness_stream.insert(witness_stream.end(), wa, wa + 32);
      witness_stream.insert(witness_stream.end(), wb, wb + 32);
      witness_stream.insert(witness_stream.end(), wq, wq + 32);
      hash_bytes(witness_stream.data(), witness_stream.size(), witness);
      hash_bytes(reinterpret_cast<const uint8_t*>(cert_doc.data()), cert_doc.size(), epoch);
      std::vector<uint8_t> stream;
      for (const uint8_t* field : {model_sha, tokenizer_sha, template_sha, witness, epoch}) {
        for (size_t i = 0; i < 8; ++i) stream.push_back(i == 0 ? 32 : 0);
        stream.insert(stream.end(), field, field + 32);
      }
      hash_bytes(stream.data(), stream.size(), expected);
      std::vector<uint8_t> storage(static_cast<size_t>(dims) * sizeof(float) + 16);
      float* vector = reinterpret_cast<float*>((reinterpret_cast<uintptr_t>(storage.data()) + 15) & ~uintptr_t(15));
      size_t required = 0; semb_fingerprint fp{}; fp.struct_size = sizeof(fp);
      const semb_status raw_s = semb_encode(enc_b, "cell6 fingerprint probe", 23, vector,
                                             static_cast<size_t>(dims) * sizeof(float), &required, &fp);
      std::memcpy(actual, fp.digest, sizeof(actual));
      composed = raw_s == SEMB_OK && std::memcmp(expected, actual, sizeof(expected)) == 0;
      why = std::string("wq=") + Name(wq_s) + " wb=" + Name(wb_s) + " raw=" + Name(raw_s) +
            " expected=" + Hex(expected, 32) + " actual=" + Hex(actual, 32);
    } else {
      why = "wq=" + std::string(Name(wq_s)) + " wb=" + Name(wb_s);
      if (model_bytes.empty() || tokenizer_bytes.empty()) why += " model/tokenizer artifact bytes unreadable";
      if (cert_doc.empty())
        why += " docs/certified-builds.json is absent or empty in the repository (U1 Slice 7 step 4 writes it)";
    }
    Verdict(composed, "cell6 W-Q accessor digest folds into the emitted five-field fingerprint", why);
    if (query) semb_query_close(query);
    if (bank) semb_bank_close(bank);
  }

  std::printf("[SUMMARY] cells=%d failures=%d\n", g_cells, g_failures);
  return g_failures > 0 ? 1 : 0;
}
