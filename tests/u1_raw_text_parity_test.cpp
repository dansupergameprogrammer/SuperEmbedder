// tests/u1_raw_text_parity_test.cpp -- TE-92 (U1, the first frozen public
// raw-text vertical slice), re-entered at TE-94 (D-SLM6314 resolution, P-1:
// the frozen config carries no appended-token member -- open derives the
// end token from the tokenizer artifact; `--append-id` below feeds ONLY the
// independent interim oracle, never the frozen path): the
// TOKENIZATION-PARITY cells. The frozen raw
// entry `semb_encode(utf8, len)` must produce, bit for bit, the vector the
// EXISTING interim token-id path produces from the same document's content
// token ids (`semb_interim_encode_ps_n`, include/superembedder/encoder_abi.h,
// the path C12b graded 239/239 at v1.4.0 -- TE-91, D-SLM6310), where the
// content ids come from an oracle that takes NO input from the engine's C++
// tokenizer:
//
//   * the synthetic pair's ids are the pinned converter's own reference
//     encoder over tests/fixtures/tokenizer/u1-mechanism-corpus.jsonl
//     (tests/fixtures/regenerate_tokenizer_pair_fixture.py);
//   * the real candidate's ids are the upstream HF tokenizer's, committed in
//     tests/fixtures/c12b/corpus-239.jsonl (the C12b corpus, minted by
//     tools/c12b/mint_c12b_corpus.py) and in the converter's golden pack over
//     SuperSLM's own 44-record tokenizer corpus
//     (tests/fixtures/tokenizer/qwen3-embedding-0.6b-golden.json).
//
// Because the interim path appends EXACTLY ONE fixed end token
// (sec 3.2's corrected PS-N position rule: id 151643 for the candidate) and
// the three wrong compositions -- omitted, doubled, wrong id -- are each
// executed through that same interim path and shown to move the vector on
// every row compared (cells P-03/P-04), equality with the interim path pins
// the frozen path's composition as well as its tokenization: a frozen build
// that appended nothing, appended twice, or appended <|im_end|> could not
// read equal here.
//
// USAGE
//   --model <.sslm> --tokenizer <.sslm> --append-id <id> --wrong-append-id <id>
//   --expected-ids <tsv: label \t comma-ids \t utf8-hex> [--limit N]
//   [--mutant-rows N]   how many rows the three in-process mutants run over (default 8)
//   [--legacy-append-id <id>]  DIAGNOSTIC ONLY, honoured only when compiled with
//                              SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER (the driver's
//                              --diag-legacy-layout pass against a 496d036-layout product)
//
// RED-UNIMPLEMENTED at main@1a040a4: none of the frozen verbs exists, so
// this translation unit does not link; the driver reports the unresolved
// symbols by name.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "semb_public_abi_contract.h"
#include "superembedder/encoder_abi.h"

namespace {

int g_failures = 0;
int g_cells = 0;

void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}

const char* Name(semb_status s) {
  const char* n = semb_status_name(s);
  return n ? n : "<NULL>";
}

struct Record {
  std::string label;
  std::vector<int32_t> ids;  // empty for the empty record
  std::string text;          // raw UTF-8 bytes (may contain NUL)
};

int HexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

bool ReadRecords(const std::string& path, std::vector<Record>* out) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  std::string line;
  while (std::getline(in, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty() || line[0] == '#') continue;
    const size_t t1 = line.find('\t');
    const size_t t2 = t1 == std::string::npos ? std::string::npos : line.find('\t', t1 + 1);
    if (t1 == std::string::npos || t2 == std::string::npos) return false;
    Record r;
    r.label = line.substr(0, t1);
    const std::string csv = line.substr(t1 + 1, t2 - t1 - 1);
    size_t start = 0;
    while (start < csv.size()) {
      size_t comma = csv.find(',', start);
      if (comma == std::string::npos) comma = csv.size();
      if (comma > start) r.ids.push_back(std::atoi(csv.substr(start, comma - start).c_str()));
      start = comma + 1;
    }
    const std::string hex = line.substr(t2 + 1);
    if (hex.size() % 2 != 0) return false;
    for (size_t i = 0; i < hex.size(); i += 2) {
      const int hi = HexNibble(hex[i]), lo = HexNibble(hex[i + 1]);
      if (hi < 0 || lo < 0) return false;
      r.text.push_back(static_cast<char>((hi << 4) | lo));
    }
    out->push_back(std::move(r));
  }
  return !out->empty();
}

struct Args {
  std::string model, tokenizer, expected_ids;
  int32_t append_id = -1, wrong_append_id = -1;
  int32_t legacy_append_id = -1;  // diagnostic-only, see USAGE
  size_t limit = 0, mutant_rows = 8;
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
    else if (k == "--expected-ids") next(&a.expected_ids);
    else if (k == "--append-id") { next(&v); a.append_id = std::atoi(v.c_str()); }
    else if (k == "--wrong-append-id") { next(&v); a.wrong_append_id = std::atoi(v.c_str()); }
    else if (k == "--limit") { next(&v); a.limit = static_cast<size_t>(std::atoll(v.c_str())); }
    else if (k == "--mutant-rows") { next(&v); a.mutant_rows = static_cast<size_t>(std::atoll(v.c_str())); }
    else if (k == "--legacy-append-id") { next(&v); a.legacy_append_id = std::atoi(v.c_str()); }
    else { std::fprintf(stderr, "unknown argument %s\n", k.c_str()); std::exit(2); }
  }
  if (a.model.empty() || a.tokenizer.empty() || a.expected_ids.empty() || a.append_id < 0 || a.wrong_append_id < 0) {
    std::fprintf(stderr, "usage: --model <.sslm> --tokenizer <.sslm> --append-id <id> --wrong-append-id <id> "
                         "--expected-ids <tsv> [--limit N] [--mutant-rows N]\n");
    std::exit(2);
  }
  return a;
}

// The interim path over content ids, under an encoder opened with the given
// appended id. Returns false (with the status name) on any refusal.
struct Interim {
  SembInterimEncoder* enc = nullptr;
  size_t hidden = 0;
  std::string open_status;
  bool Open(const std::string& model, int32_t append_id) {
    const char* name = nullptr;
    const SembInterimStatus st = semb_interim_encoder_open(model.c_str(), append_id, &enc, &name);
    if (st != kSembInterimOk) {
      open_status = std::string("interim open refused: status ") + std::to_string(static_cast<int>(st)) +
                    " engine=" + (name ? name : "?");
      enc = nullptr;
      return false;
    }
    SembInterimGeometry g{};
    g.struct_size = sizeof(g);
    if (semb_interim_encoder_geometry(enc, &g) != kSembInterimOk) {
      open_status = "interim geometry refused";
      return false;
    }
    hidden = g.hidden_size;
    return true;
  }
  bool Encode(const std::vector<int32_t>& ids, std::vector<float>* out, std::string* why) {
    out->assign(hidden, 0.0f);
    size_t req = 0;
    SembWaPoolStatus dq = kSembOk;
    const char* name = nullptr;
    const SembInterimStatus st = semb_interim_encode_ps_n(enc, ids.data(), ids.size(), 0, out->data(),
                                                          out->size() * sizeof(float), &req, &dq, &name);
    if (st != kSembInterimOk) {
      *why = std::string("interim encode status ") + std::to_string(static_cast<int>(st)) +
             " dequantize=" + std::to_string(static_cast<int>(dq)) + " engine=" + (name ? name : "?");
      return false;
    }
    return true;
  }
  void Close() {
    if (enc) semb_interim_encoder_close(enc);
    enc = nullptr;
  }
};

bool FrozenEncode(semb_encoder enc, const Record& r, uint32_t dims, std::vector<float>* out, semb_status* st_out) {
  out->assign(dims, 0.0f);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  *st_out = semb_encode(enc, r.text.data(), r.text.size(), out->data(), out->size() * sizeof(float), &req, &fp);
  return *st_out == SEMB_OK;
}

bool SameBytes(const std::vector<float>& a, const std::vector<float>& b) {
  return a.size() == b.size() && std::memcmp(a.data(), b.data(), a.size() * sizeof(float)) == 0;
}

double Seconds(std::chrono::steady_clock::time_point t0) {
  return std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  std::vector<Record> records;
  if (!ReadRecords(a.expected_ids, &records)) {
    std::fprintf(stderr, "could not read --expected-ids %s\n", a.expected_ids.c_str());
    return 2;
  }
  if (a.limit > 0 && records.size() > a.limit) records.resize(a.limit);

  const int32_t s_ok = semb_contract::StatusByName("SEMB_OK");
  const int32_t s_empty = semb_contract::StatusByName("SEMB_INPUT_EMPTY");

  Interim interim;
  if (!interim.Open(a.model, a.append_id)) {
    Verdict(false, "P-00 the interim token-id path opens the model (the oracle side)", interim.open_status);
    return 1;
  }
  // P-1: the frozen config names the two artifacts and the pool size, and
  // nothing else -- the end token is the artifact pair's own property.
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = a.model.c_str();
  cfg.model_path_len = a.model.size();
  cfg.tokenizer_path = a.tokenizer.c_str();
  cfg.tokenizer_path_len = a.tokenizer.size();
#ifdef SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER
  cfg.appended_token_id = a.legacy_append_id >= 0 ? a.legacy_append_id : a.append_id;
#endif
  cfg.max_concurrency = 1;
  semb_encoder enc = nullptr;
  const semb_status so = semb_encoder_open(&cfg, &enc);
  if (so != s_ok || !enc) {
    Verdict(false, "P-00 the frozen semb_encoder_open opens the pair", std::string("refused: ") + Name(so));
    return 1;
  }
  uint32_t dims = 0;
  (void)semb_encoder_dims(enc, &dims);
  Verdict(dims == interim.hidden, "P-00 semb_encoder_dims equals the interim geometry's hidden_size",
          "dims=" + std::to_string(dims) + " hidden=" + std::to_string(interim.hidden));

  // ---- P-01 raw text through the frozen path == content ids through the interim path -------
  {
    const auto t0 = std::chrono::steady_clock::now();
    size_t compared = 0, empty_seen = 0, specials_in_content = 0;
    std::string first_diff, first_refusal;
    std::vector<float> v_ref, v_new;
    for (const Record& r : records) {
      if (r.ids.empty()) {
        ++empty_seen;
        continue;
      }
      for (int32_t id : r.ids)
        if (id == a.append_id) ++specials_in_content;
      std::string why;
      if (!interim.Encode(r.ids, &v_ref, &why)) {
        if (first_refusal.empty()) first_refusal = r.label + " (" + why + ")";
        continue;
      }
      semb_status st = 0;
      if (!FrozenEncode(enc, r, dims, &v_new, &st)) {
        if (first_refusal.empty()) first_refusal = r.label + " (frozen: " + Name(st) + ")";
        continue;
      }
      ++compared;
      if (!SameBytes(v_ref, v_new) && first_diff.empty()) first_diff = r.label;
    }
    const size_t expected = records.size() - empty_seen;
    Verdict(first_refusal.empty() && first_diff.empty() && compared == expected && compared > 0,
            "P-01 every non-empty record: frozen semb_encode(text) == interim PS-N over the oracle's content ids, bit for bit",
            "compared " + std::to_string(compared) + " of " + std::to_string(expected) + " records in " +
                std::to_string(Seconds(t0)) + "s; first difference: " + (first_diff.empty() ? "none" : first_diff) +
                "; first refusal: " + (first_refusal.empty() ? "none" : first_refusal));
    std::printf("[OBSERVED] P-01 records whose CONTENT ids already contain the appended id (literal special text): %zu occurrence(s)\n",
                specials_in_content);
  }

  // ---- P-02 the empty record: refused by both paths, same class -----------------------------
  {
    bool have_empty = false;
    for (const Record& r : records) if (r.ids.empty() && r.text.empty()) have_empty = true;
    if (have_empty) {
      std::vector<float> v;
      semb_status st = 0;
      Record e;
      const bool ok = FrozenEncode(enc, e, dims, &v, &st);
      std::string why;
      std::vector<int32_t> none;
      const bool interim_ok = interim.Encode(none, &v, &why);
      Verdict(!ok && st == s_empty && !interim_ok,
              "P-02 the empty record -> SEMB_INPUT_EMPTY on the frozen path; the interim path refuses zero ids too",
              std::string("frozen ") + Name(st) + "; interim " + why);
    } else {
      std::printf("[OBSERVED] P-02 no empty record in this population\n");
    }
  }

  // ---- P-03 exactly one appended token: the three wrong compositions each move the vector ---
  {
    const auto t0 = std::chrono::steady_clock::now();
    Interim wrong_id;
    const bool wrong_open = wrong_id.Open(a.model, a.wrong_append_id);
    size_t rows = 0, doubled_rows = 0, doubled_moved = 0, uniform_rows = 0, omitted_rows = 0, omitted_moved = 0,
           wrongid_moved = 0, frozen_ok = 0;
    std::string note;
    std::vector<float> v_new, v_doubled, v_omitted, v_wrong;
    for (const Record& r : records) {
      if (r.ids.empty()) continue;
      if (rows >= a.mutant_rows) break;
      ++rows;
      semb_status st = 0;
      if (!FrozenEncode(enc, r, dims, &v_new, &st)) { note += " frozen-refused:" + r.label; continue; }
      ++frozen_ok;
      std::string why;
      // A row whose content is nothing but the appended id becomes, doubled, a
      // UNIFORM sequence one token longer, and a uniform sequence's last
      // position can be length-invariant by construction (identical value
      // vectors at every position). Executed on the synthetic pair: uniform
      // 262/97/300 sequences of lengths 2..8 emit one vector each; the real
      // candidate's end-token lengths 2/3/4 emit three different vectors.
      // Such rows are reported, never counted (tests/u1_trailing_special_mutants_check.py
      // holds the same rule).
      bool uniform = true;
      for (int32_t id : r.ids) if (id != a.append_id) uniform = false;
      std::vector<int32_t> doubled = r.ids;
      doubled.push_back(a.append_id);  // content + [append] handed in, then the path appends once more
      if (uniform) {
        ++uniform_rows;
      } else {
        ++doubled_rows;
        if (interim.Encode(doubled, &v_doubled, &why) && !SameBytes(v_new, v_doubled)) ++doubled_moved;
      }
      if (r.ids.size() >= 2) {
        ++omitted_rows;
        // Open with the document's own last content id as the "end token" and hand
        // in content[:-1]: the sequence is exactly the content, with NO end token.
        Interim omit;
        if (omit.Open(a.model, r.ids.back())) {
          std::vector<int32_t> head(r.ids.begin(), r.ids.end() - 1);
          if (omit.Encode(head, &v_omitted, &why) && !SameBytes(v_new, v_omitted)) ++omitted_moved;
          omit.Close();
        }
      }
      if (wrong_open && wrong_id.Encode(r.ids, &v_wrong, &why) && !SameBytes(v_new, v_wrong)) ++wrongid_moved;
    }
    wrong_id.Close();
    Verdict(rows > 0 && frozen_ok == rows && doubled_rows > 0 && doubled_moved == doubled_rows,
            "P-03a DOUBLED end token (content + [id] then append) moves the vector on every row that carries content",
            std::to_string(doubled_moved) + " of " + std::to_string(doubled_rows) + " rows moved; uniform end-token-only rows reported, not counted: " +
                std::to_string(uniform_rows) + note);
    Verdict(omitted_rows > 0 && omitted_moved == omitted_rows,
            "P-03b OMITTED end token (content alone, no append) moves the vector on every row with >= 2 content tokens",
            std::to_string(omitted_moved) + " of " + std::to_string(omitted_rows) + " rows moved");
    Verdict(wrong_open && rows > 0 && wrongid_moved == rows,
            "P-03c WRONG end token id (" + std::to_string(a.wrong_append_id) + " instead of " + std::to_string(a.append_id) +
                ") moves the vector on every row",
            (wrong_open ? std::to_string(wrongid_moved) + " of " + std::to_string(rows) + " rows moved" : wrong_id.open_status) +
                " (" + std::to_string(Seconds(t0)) + "s)");
  }

  // ---- P-04 repeated encodes through one handle; reuse across a shape change (C27's shape) --
  {
    const Record* longest = nullptr;
    const Record* shortest = nullptr;
    for (const Record& r : records) {
      if (r.ids.empty()) continue;
      if (!longest || r.ids.size() > longest->ids.size()) longest = &r;
      if (!shortest || r.ids.size() < shortest->ids.size()) shortest = &r;
    }
    if (longest && shortest) {
      std::vector<float> base, again;
      semb_status st = 0;
      FrozenEncode(enc, *longest, dims, &base, &st);
      bool repeat_same = st == s_ok;
      for (int i = 0; i < 20 && repeat_same; ++i) {
        FrozenEncode(enc, *longest, dims, &again, &st);
        repeat_same = st == s_ok && SameBytes(base, again);
      }
      Verdict(repeat_same, "P-04a 20 repeated encodes of one document through one handle are byte-identical",
              longest->label + " (" + std::to_string(longest->ids.size()) + " content tokens)");
      // long, short, long, short on ONE handle, each compared to a FRESH handle's vector.
      semb_encoder fresh = nullptr;
      const semb_status sf = semb_encoder_open(&cfg, &fresh);
      if (sf == s_ok && fresh) {
        std::vector<float> fl, fs, l1, s1, l2, s2;
        FrozenEncode(fresh, *longest, dims, &fl, &st);
        FrozenEncode(fresh, *shortest, dims, &fs, &st);
        FrozenEncode(enc, *longest, dims, &l1, &st);
        FrozenEncode(enc, *shortest, dims, &s1, &st);
        FrozenEncode(enc, *longest, dims, &l2, &st);
        FrozenEncode(enc, *shortest, dims, &s2, &st);
        Verdict(SameBytes(fl, l1) && SameBytes(fs, s1) && SameBytes(fl, l2) && SameBytes(fs, s2),
                "P-04b long/short/long/short on one handle each equal a fresh handle's vector for the same document",
                longest->label + " (" + std::to_string(longest->ids.size()) + ") / " + shortest->label + " (" +
                    std::to_string(shortest->ids.size()) + ")");
        (void)semb_encoder_close(fresh);
      } else {
        Verdict(false, "P-04b (setup) a second handle opens", Name(sf));
      }
    }
  }

  // ---- P-05 the population contains the literal-special-text class ---------------------------
  {
    size_t n = 0;
    for (const Record& r : records)
      for (int32_t id : r.ids)
        if (id == a.append_id) { ++n; break; }
    Verdict(n > 0, "P-05 the population has at least one record whose text tokenizes to the end token itself (doubled by the append, by design)",
            std::to_string(n) + " record(s)");
  }

  (void)semb_encoder_close(enc);
  interim.Close();
  std::printf("\nu1_raw_text_parity_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
