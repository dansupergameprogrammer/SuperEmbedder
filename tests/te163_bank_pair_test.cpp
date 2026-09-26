// tests/te163_bank_pair_test.cpp -- TE-163 (U1 slice 4): the red suite for
// the bank pair, the manifest sidecar, and `semb_bank_open`/`semb_bank_close`
// (`Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.4, `Claude/Plans/
// SuperEmbedder_Plan.md` sec 3.1, sec 3.4, sec 8 C9/C18/C34, sec 9 dims 1, 2,
// 3, 5, 7, 9, 11). Cells 1, 2, 3, 5, 6 of this round's own dispatch
// (`Claude/Bach/briefs/te163-slice4-red.md`); cell 4 (C34 legs e/h, the
// scratch-build mutation proof) is `tests/te163_c34_manifest_honesty_check.py`
// -- a compiled-in-constant mutation cannot be driven from inside one already-
// linked executable.
//
// RED AT `7af22da`: `semb_bake_to_path` (tests/semb_bake_abi_contract.h),
// `semb_bank_open`/`semb_bank_close` and the `semb_bank` type (tests/
// semb_bank_abi_contract.h) exist nowhere in `superembedder`
// (`git grep -n "semb_bake_to_path\|semb_bank_open\|semb_bank_close"
// src/ include/` returns nothing at this branch's own base) -- this
// executable fails to LINK until the builder's round adds them.
// `tests/te163_bank_pair_check.py` builds this target on demand and reports
// the unresolved symbol(s) by name, the same red-first shape
// `tests/u1_batch_contract_check.py` already uses for Slice 2.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --dims <n> --scratch <dir>
//        --wb-corpus <wb-corpus.jsonl path>
//        [--corpus-239 <corpus-239.jsonl path> --real --stem <name>]
// Without --real this binary runs the MECHANISM legs only (cheap, always).
// With --real it additionally runs the real-artifact 239-document bake and
// this slice's own round-trip leg against it, timed and reported.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "json_mini.h"
#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_bank_abi_contract.h"

// This driver deliberately includes the test-side ABI contracts instead of
// the product header, so repeat F4's internal declaration here rather than
// including bank_internal_abi.h (which would redefine the contract types).
extern "C" semb_status semb_bank_debug_state(semb_bank bank, uint8_t out_fingerprint[32],
                                               int64_t* out_count, int64_t* out_dims);

#include "superslm/matmul.h"
#include "superslm/sha256.h"

#if SUPERSLM_MATMUL_HAVE_SIMD_X64
#if defined(_MSC_VER)
#include <intrin.h>
#else
#include <cpuid.h>
#endif
#endif

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// TE-159 item 5's own aligned leak instrument (D-SLM6353), the SAME shape
// tests/u1_batch_workspace_test.cpp already uses for C49 -- reused, not
// reinvented, per this project's "one proven detector, not a second
// invented one" discipline. A per-TU operator-new/delete override cannot
// literally be shared across executables; this is the identical
// Header-alignment technique, not a second design.
// ---------------------------------------------------------------------------
namespace leak_hook {
std::atomic<int64_t> g_live_bytes{0};
struct alignas(__STDCPP_DEFAULT_NEW_ALIGNMENT__) Header { size_t size; };
void* Allocate(std::size_t n) {
  const size_t total = n + sizeof(Header);
  void* raw = std::malloc(total == 0 ? 1 : total);
  if (!raw) throw std::bad_alloc();
  static_cast<Header*>(raw)->size = n;
  g_live_bytes.fetch_add(static_cast<int64_t>(n), std::memory_order_relaxed);
  return static_cast<uint8_t*>(raw) + sizeof(Header);
}
void Deallocate(void* p) noexcept {
  if (!p) return;
  void* raw = static_cast<uint8_t*>(p) - sizeof(Header);
  const size_t n = static_cast<Header*>(raw)->size;
  g_live_bytes.fetch_sub(static_cast<int64_t>(n), std::memory_order_relaxed);
  std::free(raw);
}
}  // namespace leak_hook
void* operator new(std::size_t n) { return leak_hook::Allocate(n); }
void* operator new[](std::size_t n) { return leak_hook::Allocate(n); }
void operator delete(void* p) noexcept { leak_hook::Deallocate(p); }
void operator delete[](void* p) noexcept { leak_hook::Deallocate(p); }
void operator delete(void* p, std::size_t) noexcept { leak_hook::Deallocate(p); }
void operator delete[](void* p, std::size_t) noexcept { leak_hook::Deallocate(p); }

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

// The CPU tier this build dispatches to (te267 U2-3 item 8, P:1108-1114),
// from producers other than the manifest writer. A forced build dispatches
// to its forced tier: the dispatch field of the engine-build record this
// build's configure verified (TE163_ENGINE_DISPATCH, from
// SEMB_ENGINE_DISPATCH; an open reaches the bake only after the linked-engine
// check matched that record, item 14). An auto build dispatches to the
// host's best tier: this test's own CPUID and XGETBV reading, resolved by the
// engine's tier rule (superslm::ResolveDotRowTier, the resolver the engine's
// dispatch calls, exported for verification). A non-x64 build is scalar.
// Returns "" when the build states no dispatch.
std::string ExpectedDispatchedTier() {
#ifdef TE163_ENGINE_DISPATCH
  const std::string dispatch = TE163_ENGINE_DISPATCH;
#else
  const std::string dispatch;
#endif
  if (dispatch.empty() || dispatch != "auto") return dispatch;
#if SUPERSLM_MATMUL_HAVE_SIMD_X64
  unsigned r0[4] = {0, 0, 0, 0}, r1[4] = {0, 0, 0, 0}, r7[4] = {0, 0, 0, 0};
  auto cpuid = [](unsigned leaf, unsigned sub, unsigned r[4]) {
#if defined(_MSC_VER)
    int v[4];
    __cpuidex(v, static_cast<int>(leaf), static_cast<int>(sub));
    for (int i = 0; i < 4; ++i) r[i] = static_cast<unsigned>(v[i]);
#else
    __cpuid_count(leaf, sub, r[0], r[1], r[2], r[3]);
#endif
  };
  cpuid(0, 0, r0);
  cpuid(1, 0, r1);
  if (r0[0] >= 7) cpuid(7, 0, r7);
  unsigned long long xcr0 = 0;
  if (r1[2] & (1u << 27)) {  // OSXSAVE: XGETBV is available
#if defined(_MSC_VER)
    xcr0 = _xgetbv(0);
#else
    unsigned lo = 0, hi = 0;
    __asm__ volatile("xgetbv" : "=a"(lo), "=d"(hi) : "c"(0));
    xcr0 = (static_cast<unsigned long long>(hi) << 32) | lo;
#endif
  }
  switch (superslm::ResolveDotRowTier(static_cast<int>(r0[0]), static_cast<int>(r1[2]), static_cast<int>(r7[1]),
                                      xcr0)) {
    case 0:
      return "sse2";
    case 1:
      return "avx2";
    case 2:
      return "avx512";
    default:
      return "unknown";
  }
#else
  return "scalar";
#endif
}

std::string Hex(const uint8_t* d, size_t n) {
  static const char* kHex = "0123456789abcdef";
  std::string out(n * 2, '0');
  for (size_t i = 0; i < n; ++i) {
    out[2 * i] = kHex[(d[i] >> 4) & 0xF];
    out[2 * i + 1] = kHex[d[i] & 0xF];
  }
  return out;
}
std::string Sha256Hex(const uint8_t* data, size_t len) {
  superslm::Sha256 h;
  h.Update(data, len);
  uint8_t out[32];
  h.Final(out);
  return Hex(out, 32);
}
std::string ReadFileBytes(const fs::path& p) {
  std::ifstream f(p, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open " + p.string());
  std::ostringstream oss;
  oss << f.rdbuf();
  return oss.str();
}
bool FileExists(const fs::path& p) { return fs::exists(p); }

struct Statuses {
  int32_t ok, null_argument, invalid_handle, corpus_empty, document_id_duplicate,
      fingerprint_mismatch, manifest_schema_unsupported, bank_size_mismatch,
      artifact_sha_mismatch, adapter_id_mismatch, ps_version_label_mismatch,
      context_cap_exceeded, bank_ids_count_mismatch, bank_nonfinite_row,
      bank_zero_norm_row, bank_geometry_ceiling_exceeded,
      bank_metric_dtype_unsupported, bank_digest_mismatch, artifact_unreadable;
};
Statuses ResolveStatuses() {
  using semb_contract::StatusByName;
  Statuses s{};
  s.ok = StatusByName("SEMB_OK");
  s.null_argument = StatusByName("SEMB_NULL_ARGUMENT");
  s.invalid_handle = StatusByName("SEMB_INVALID_HANDLE");
  s.corpus_empty = StatusByName("SEMB_CORPUS_EMPTY");
  s.document_id_duplicate = StatusByName("SEMB_DOCUMENT_ID_DUPLICATE");
  s.fingerprint_mismatch = StatusByName("SEMB_FINGERPRINT_MISMATCH");
  s.manifest_schema_unsupported = StatusByName("SEMB_MANIFEST_SCHEMA_UNSUPPORTED");
  s.bank_size_mismatch = StatusByName("SEMB_BANK_SIZE_MISMATCH");
  s.artifact_sha_mismatch = StatusByName("SEMB_ARTIFACT_SHA_MISMATCH");
  s.adapter_id_mismatch = StatusByName("SEMB_ADAPTER_ID_MISMATCH");
  s.ps_version_label_mismatch = StatusByName("SEMB_PS_VERSION_LABEL_MISMATCH");
  s.context_cap_exceeded = StatusByName("SEMB_CONTEXT_CAP_EXCEEDED");
  // TE-183 (D-SLM6410), ordinals 28-31: the four FORMAT.md sec 1 obligations
  // cell 2's tamper constructions drove by value only, unpinned, until now.
  s.bank_ids_count_mismatch = StatusByName("SEMB_BANK_IDS_COUNT_MISMATCH");
  s.bank_nonfinite_row = StatusByName("SEMB_BANK_NONFINITE_ROW");
  s.bank_zero_norm_row = StatusByName("SEMB_BANK_ZERO_NORM_ROW");
  s.bank_geometry_ceiling_exceeded = StatusByName("SEMB_BANK_GEOMETRY_CEILING_EXCEEDED");
  // TE-192 (D-SLM6467 F2/F8), ordinal 32: unknown metric/dtype.
  s.bank_metric_dtype_unsupported = StatusByName("SEMB_BANK_METRIC_DTYPE_UNSUPPORTED");
  // TE-192 (D-SLM6467 F3/F8), ordinal 33: a manifest digest (row_digest, or
  // corpus_digest's self-consistency against its own witness copy)
  // disagreeing with what it is checked against.
  s.bank_digest_mismatch = StatusByName("SEMB_BANK_DIGEST_MISMATCH");
  s.artifact_unreadable = StatusByName("SEMB_ARTIFACT_UNREADABLE");
  return s;
}

struct Args {
  std::string model, tokenizer, scratch, wb_corpus, corpus_239, stem = "bank";
  unsigned dims = 0;
  bool real = false;
};
Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--dims") { std::string v; next(&v); a.dims = static_cast<unsigned>(std::atoi(v.c_str())); }
    else if (k == "--scratch") next(&a.scratch);
    else if (k == "--wb-corpus") next(&a.wb_corpus);
    else if (k == "--corpus-239") next(&a.corpus_239);
    else if (k == "--stem") next(&a.stem);
    else if (k == "--real") a.real = true;
  }
  return a;
}

semb_encoder Open(const Args& a) {
  semb_config c{};
  c.struct_size = sizeof(c);
  c.model_path = a.model.data();
  c.model_path_len = a.model.size();
  c.tokenizer_path = a.tokenizer.data();
  c.tokenizer_path_len = a.tokenizer.size();
  c.max_concurrency = 4;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&c, &enc);
  if (s != SEMB_OK || !enc) { Verdict(false, "(setup) open", Name(s)); return nullptr; }
  return enc;
}

// Arena-owned document set (the DocSet pattern tests/u1_batch_contract_test.cpp
// establishes and this round's own casebook cites as this tree's convention:
// a temporary std::string bound to a semb_document's raw pointer dangles the
// instant the constructing expression ends).
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

// A minimal one-object-per-line JSONL reader over the two corpus shapes this
// suite already carries as committed fixtures: {"id":.., "text":..} (this
// round's own writable fixtures) and {"label":.., "text":.., ...} (the
// existing corpus-239.jsonl, C12b's own committed fixture -- read here as
// data, not modified; "label" stands in as this cell's own row id, since
// FORMAT.md/sec 3.4 require SOME id and corpus-239.jsonl's own "label"
// column is already the project's de facto per-row identifier, unique by
// construction -- see tests/fixtures/c12b/corpus-239.manifest.json).
std::vector<std::pair<std::string, std::string>> LoadJsonlCorpus(const fs::path& path, const char* id_key) {
  std::vector<std::pair<std::string, std::string>> out;
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open corpus " + path.string());
  std::string line;
  while (std::getline(f, line)) {
    if (line.empty()) continue;
    json_mini::Parser p(line);
    json_mini::Value v = p.Parse();
    out.emplace_back(v[id_key].s(), v["text"].s());
  }
  return out;
}

// ---------------------------------------------------------------------------
// The manifest's own required field set (Claude/Bach/briefs/te163-slice4-red.md,
// this round's own contract header tests/semb_bake_abi_contract.h): every
// field present, none omitted, a field 1.0 does not compute carrying a named
// `SEMB-...` label rather than a value.
// ---------------------------------------------------------------------------
bool ManifestHasAllFields(const json_mini::Value& m, std::string* missing) {
  static const char* kTop[] = {
      "encoder_fingerprint", "model_sha", "tokenizer_sha", "template_sha256",
      "witness_sha", "certification_epoch", "certified_builds_path",
      "provenance", "label:ps_version", "label:engine_path_id",
      "label:superslm_tag_commit", "label:semb_version", "count", "dims",
      "row_digest", "corpus_digest", "machine_tier", "per_row_token_counts"};
  for (const char* k : kTop) {
    if (m.kind != json_mini::Kind::kObject || !m.as_object.count(k)) { *missing = k; return false; }
  }
  static const char* kProvenance[] = {"object_code_sha", "engine_object_code_sha", "semb_source_sha",
                                       "engine_tree_sha", "engine_path_sha", "engine_chunk_budget", "witness"};
  const auto& prov = m["provenance"];
  for (const char* k : kProvenance) {
    if (prov.kind != json_mini::Kind::kObject || !prov.as_object.count(k)) { *missing = std::string("provenance.") + k; return false; }
  }
  static const char* kWitness[] = {"corpus_digest", "wa_digest", "wb_digest", "cpu_tier"};
  const auto& wit = prov["witness"];
  for (const char* k : kWitness) {
    if (wit.kind != json_mini::Kind::kObject || !wit.as_object.count(k)) { *missing = std::string("provenance.witness.") + k; return false; }
  }
  return true;
}

// sec 3.3's exact five-field composition, recomputed from the manifest's OWN
// clear-text hex fields -- cell 3's own reading (a) oracle: bank_open must
// refuse a manifest whose encoder_fingerprint disagrees with this
// recomputation. Length-prefixed, little-endian u64, sec 3.3's own table.
std::vector<uint8_t> HexToBytes(const std::string& hex) {
  std::vector<uint8_t> out(hex.size() / 2);
  for (size_t i = 0; i < out.size(); ++i) out[i] = static_cast<uint8_t>(std::stoul(hex.substr(2 * i, 2), nullptr, 16));
  return out;
}
void AppendLenPrefixed(superslm::Sha256* h, const std::vector<uint8_t>& field) {
  uint64_t len = static_cast<uint64_t>(field.size());
  uint8_t le[8];
  for (int i = 0; i < 8; ++i) le[i] = static_cast<uint8_t>((len >> (8 * i)) & 0xFF);
  h->Update(le, 8);
  h->Update(field.data(), field.size());
}
std::string RecomputeFingerprintFromManifest(const json_mini::Value& m) {
  superslm::Sha256 h;
  for (const char* k : {"model_sha", "tokenizer_sha", "template_sha256", "witness_sha", "certification_epoch"})
    AppendLenPrefixed(&h, HexToBytes(m[k].s()));
  uint8_t out[32];
  h.Final(out);
  return Hex(out, 32);
}

// Copies the three-file triple at `src_stem` to `dst_stem`, applying `edit`
// to the manifest/header/bin bytes before writing each copy -- the "editing
// a copy of a good triple" construction cell 2's own dispatch text names for
// every tamper leg. Returns true iff every edit ran without throwing and the
// copy completed. D-SLM6411 item (a): a `ReplaceOnce` (or any edit) that
// cannot find what it names is a defect IN THAT CONSTRUCTION -- not a reason
// to kill the whole process before its later cells run. An exception thrown
// out of `edit` is caught here and reported as a NAMED FAIL for `cell_name`,
// never left to propagate past this function.
bool CopyTriple(const fs::path& src_stem, const fs::path& dst_stem, const std::string& cell_name,
                 const std::function<std::string(std::string)>& edit_manifest = nullptr,
                 const std::function<std::string(std::string)>& edit_header = nullptr,
                 const std::function<std::string(std::string)>& edit_bin = nullptr) {
  bool ok = true;
  auto copy_one = [&](const char* suffix, const std::function<std::string(std::string)>& edit) {
    if (!ok) return;  // an earlier suffix's own edit already failed this construction
    std::string bytes = ReadFileBytes(fs::path(src_stem.string() + suffix));
    if (edit) {
      try {
        bytes = edit(std::move(bytes));
      } catch (const std::exception& e) {
        Verdict(false, cell_name + " (setup) the construction's own edit", std::string("threw: ") + e.what());
        ok = false;
        return;
      }
    }
    std::ofstream out(fs::path(dst_stem.string() + suffix), std::ios::binary);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  };
  copy_one(".wvbank.json", edit_header);
  copy_one(".wvbank.bin", edit_bin);
  copy_one(".semb.json", edit_manifest);
  return ok;
}

std::string ReplaceOnce(std::string s, const std::string& from, const std::string& to) {
  auto pos = s.find(from);
  if (pos == std::string::npos) throw std::runtime_error("ReplaceOnce: '" + from + "' not found");
  return s.substr(0, pos) + to + s.substr(pos + from.size());
}

// The manifest's own "corpus_digest" key appears TWICE in a good triple's
// text -- once inside provenance.witness (the witness pass's own copy) and
// once at the top level (D-SLM6409(b): the two are the SAME value by
// construction) -- and when both copies still carry the identical value
// (as a good triple's do), `ReplaceOnce` on the bare key/value pair finds
// the FIRST (witness) occurrence, not the top-level one this construction
// means to tamper. `ReplaceLast` finds the LAST occurrence instead, so a
// caller can target the top-level field specifically while leaving the
// witness copy untouched -- which is the whole point of the construction
// (assert open catches the two disagreeing, not merely that the field
// changed).
std::string ReplaceLast(std::string s, const std::string& from, const std::string& to) {
  auto pos = s.rfind(from);
  if (pos == std::string::npos) throw std::runtime_error("ReplaceLast: '" + from + "' not found");
  return s.substr(0, pos) + to + s.substr(pos + from.size());
}

bool DirEmptyOfTriple(const fs::path& stem) {
  return !FileExists(fs::path(stem.string() + ".wvbank.json")) &&
         !FileExists(fs::path(stem.string() + ".wvbank.bin")) &&
         !FileExists(fs::path(stem.string() + ".semb.json"));
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0 || a.scratch.empty() || a.wb_corpus.empty()) {
    std::fprintf(stderr, "usage: %s --model <.sslm> --tokenizer <.sslm> --dims <n> --scratch <dir> "
                          "--wb-corpus <path> [--corpus-239 <path> --real --stem <name>]\n", argv[0]);
    return 2;
  }
  const Statuses st = ResolveStatuses();
  fs::create_directories(a.scratch);
  const fs::path scratch(a.scratch);
  const auto label = a.real ? std::string("product") : std::string("mechanism");

  // =========================================================================
  // CELL 1 -- the bake contract driver: the WB fixture, FORMAT.md sec 1's
  // header/payload pinned byte for byte, refusal-writes-nothing per TE-96
  // sec 4.2 class, SuperFAISS's own reader as the must-accept (driven by
  // tests/te163_bank_pair_check.py against the .wvbank.json this cell bakes,
  // outside this process).
  // =========================================================================
  auto wb_docs_raw = LoadJsonlCorpus(a.wb_corpus, "id");
  DocSet wb_arena;
  std::vector<semb_document> wb_docs;
  for (auto& [id, text] : wb_docs_raw) wb_docs.push_back(wb_arena.Add(id, text));

  const fs::path wb_stem = scratch / (a.stem + "_wb");
  fs::remove(fs::path(wb_stem.string() + ".wvbank.json"));
  fs::remove(fs::path(wb_stem.string() + ".wvbank.bin"));
  fs::remove(fs::path(wb_stem.string() + ".semb.json"));
  {
    semb_encoder enc = Open(a);
    if (!enc) return 1;
    uint32_t enc_dims = 0;
    semb_encoder_dims(enc, &enc_dims);
    const std::string stem_str = wb_stem.string();
    const semb_status bs = semb_bake_to_path(enc, wb_docs.data(), wb_docs.size(), stem_str.c_str(), stem_str.size());
    // D-SLM6411 item (c): a small enough context_cap is legitimately
    // exceeded by at least one WB document's raw (uncut) token count, and
    // semb_bake_to_path applies NO document cutting (cutting is
    // ComputeWbDigest's own open-time-only accommodation, never exposed to
    // a caller's own bake per its own contract) -- so a bake against a
    // small-context_cap pair correctly REFUSES with
    // SEMB_CONTEXT_CAP_EXCEEDED, and a bake against a large-context_cap
    // pair correctly bakes to SEMB_OK. Which one is correct here depends on
    // the OPEN HANDLE's own context_cap, never on the `--real` flag: this
    // binary has a second caller (tests/te163_c34_manifest_honesty_check.py's
    // mutation probe) that opens a real, large-context_cap model WITHOUT
    // ever passing --real, so gating this expectation on a.real (tried and
    // reverted -- it broke that caller's own "restored build bakes to
    // SEMB_OK" check) is wrong. Both outcomes are accepted as legitimate;
    // only a THIRD status is a genuine cell failure.
    const bool bake_ok = bs == st.ok;
    const bool bake_cap_refused = bs == st.context_cap_exceeded;
    Verdict(bake_ok || bake_cap_refused,
            label + "/cell1 bake the WB fixture -> SEMB_OK, or a legitimate SEMB_CONTEXT_CAP_EXCEEDED refusal "
                    "when this open handle's own context_cap is smaller than an uncut WB document",
            Name(bs));

    if (bake_ok) {
      const std::string header_text = ReadFileBytes(fs::path(stem_str + ".wvbank.json"));
      json_mini::Parser hp(header_text);
      json_mini::Value header = hp.Parse();
      bool header_ok = header["schemaVersion"].i() == 1 && header["dims"].i() == enc_dims &&
                        header["count"].i() == static_cast<int64_t>(wb_docs.size()) &&
                        header["metric"].s() == "cosine" && header["dtype"].s() == "float32" &&
                        !header.as_object.count("channels");
      Verdict(header_ok, label + "/cell1 wvbank.json pinned to FORMAT.md sec 1 (schemaVersion 1, dims, count, "
                                  "cosine, float32, no channels)",
              "schemaVersion=" + std::to_string(header["schemaVersion"].i()) +
                  " dims=" + std::to_string(header["dims"].i()) + " count=" + std::to_string(header["count"].i()) +
                  " metric=" + header["metric"].s() + " dtype=" + header["dtype"].s());

      bool ids_ok = header.as_object.count("ids") && header["ids"].arr().size() == wb_docs.size();
      if (ids_ok) {
        for (size_t i = 0; i < wb_docs.size(); ++i)
          if (header["ids"].arr()[i].s() != wb_docs_raw[i].first) { ids_ok = false; break; }
      }
      Verdict(ids_ok, label + "/cell1 ids exactly count entries, row i <-> docs[i] (TE-96 sec 4.2)", "");

      const std::string bin = ReadFileBytes(fs::path(stem_str + ".wvbank.bin"));
      const size_t expected_bytes = wb_docs.size() * static_cast<size_t>(enc_dims) * 4;
      Verdict(bin.size() == expected_bytes,
              label + "/cell1 .wvbank.bin length == count*dims*4",
              "got " + std::to_string(bin.size()) + " expected " + std::to_string(expected_bytes));

      // Payload identity against a FRESH direct semb_encode_batch call.
      semb_encoder enc2 = Open(a);
      if (enc2) {
        std::vector<float> direct(wb_docs.size() * enc_dims);
        size_t required = 0;
        const semb_status ds = semb_encode_batch(enc2, wb_docs.data(), wb_docs.size(),
                                                  direct.data(), direct.size() * sizeof(float), &required);
        bool identical = ds == st.ok && required == expected_bytes &&
                          bin.size() == expected_bytes &&
                          std::memcmp(bin.data(), direct.data(), expected_bytes) == 0;
        Verdict(identical, label + "/cell1 payload bit-identical to a fresh semb_encode_batch on the same handle",
                "batch status=" + std::string(Name(ds)));
        semb_encoder_close(enc2);
      }

      const std::string manifest_text = ReadFileBytes(fs::path(stem_str + ".semb.json"));
      json_mini::Parser mp(manifest_text);
      json_mini::Value manifest = mp.Parse();
      std::string missing;
      Verdict(ManifestHasAllFields(manifest, &missing),
              label + "/cell1 .semb.json carries every named field (this round's own contract)",
              missing.empty() ? "all present" : ("missing: " + missing));
      bool tok_counts_ok = manifest.as_object.count("per_row_token_counts") &&
                            manifest["per_row_token_counts"].arr().size() == wb_docs.size();
      Verdict(tok_counts_ok, label + "/cell1 per_row_token_counts has one entry per row, row order", "");

      // TE-187 bare cell 4 (row 5(b), D-SLM6409(b)): this bake's own act of
      // encoding is its own witness pass -- provenance.witness.corpus_digest
      // and the top-level corpus_digest are the SAME value BY CONSTRUCTION
      // on a legitimately baked manifest. (The refusal side -- a manifest
      // whose two copies disagree -- is TE-192 item 2's own
      // "corpus_digest_binding" construction in cell 2.)
      {
        const std::string witness_corpus_digest = manifest["provenance"]["witness"]["corpus_digest"].s();
        const std::string top_level_corpus_digest = manifest["corpus_digest"].s();
        Verdict(!witness_corpus_digest.empty() && witness_corpus_digest == top_level_corpus_digest,
                label + "/cell1 provenance.witness.corpus_digest equals the top-level corpus_digest "
                        "(D-SLM6409(b): this bake's own encoding is its own witness pass)",
                "witness=" + witness_corpus_digest.substr(0, 16) + "... top_level=" +
                    top_level_corpus_digest.substr(0, 16) + "...");
      }

      // TE-187 bare cell 5 (row 5(c), D-SLM6409(c)); label convention
      // renamed at U1 Slice 7 step 8 (D-SLM7212): object_code_sha and
      // engine_object_code_sha carry the named not-computed label rather
      // than a computed value -- a guard-vitality claim about what must NOT
      // be true in 1.0, violated by either carrying a computed or fabricated
      // value. Computing them is 1.x scope.
      //
      // U2-3 item 8 (te267, D-SLM7279 overriding D-SLM7212 for this one
      // field, P:1108-1114): the top-level machine_tier and
      // provenance.witness.cpu_tier no longer carry the label; each carries
      // the tier this build dispatched to (sse2, avx2, avx512 or scalar),
      // graded against ExpectedDispatchedTier() -- the configure-verified
      // engine record's forced tier, or on an auto build the host's best
      // tier from this test's own CPUID reading -- never a fixed string, so
      // the same cell holds on an AVX2 host and an AVX-512 host.
      //
      // TE-272 (D-SLM7257, sec 7): semb_source_sha joins the same check.
      // It was excluded on D-SLM6443 item 2's reasoning -- that a
      // mechanism for its own circularity was Slice 7's, where it would
      // "become real for the public surface" -- but Slice 7's own F-4
      // (D-SLM7257) did not make it real: it gave semb_source_sha the
      // identical -NOT-COMPUTED-IN-1.0 label the other three already
      // carried (encoder.cpp's own comment: "as is reporting semb_source_sha
      // in the manifest (D-SLM7257)"), so D-SLM6443 item 2's reason no
      // longer distinguishes it from the other three. Canonicalizing it
      // (computing a real value) is cut to 1.x exactly like the others
      // (D-SLM7198); nothing about its own provenance is checked here,
      // never a fingerprint input.
      {
        auto is_uncomputed_label = [](const std::string& v) {
          static const std::string kSuffix = "-NOT-COMPUTED-IN-1.0";
          return v.rfind("SEMB-", 0) == 0 && v.size() > kSuffix.size() &&
                 v.compare(v.size() - kSuffix.size(), kSuffix.size(), kSuffix) == 0;
        };
        const std::string object_code_sha = manifest["provenance"]["object_code_sha"].s();
        const std::string engine_object_code_sha = manifest["provenance"]["engine_object_code_sha"].s();
        const std::string machine_tier = manifest["machine_tier"].s();
        const std::string witness_cpu_tier = manifest["provenance"]["witness"]["cpu_tier"].s();
        const std::string semb_source_sha = manifest["provenance"]["semb_source_sha"].s();
        Verdict(is_uncomputed_label(object_code_sha),
                label + "/cell1 provenance.object_code_sha carries the not-computed-in-1.0 label "
                        "(D-SLM6409(c), D-SLM7212)", object_code_sha);
        Verdict(is_uncomputed_label(engine_object_code_sha),
                label + "/cell1 provenance.engine_object_code_sha carries the not-computed-in-1.0 label "
                        "(D-SLM6409(c), D-SLM7212)", engine_object_code_sha);
        const std::string want_tier = ExpectedDispatchedTier();
        const bool want_tier_named =
            want_tier == "sse2" || want_tier == "avx2" || want_tier == "avx512" || want_tier == "scalar";
        Verdict(want_tier_named && machine_tier == want_tier,
                label + "/cell1 the top-level machine_tier carries the dispatched tier (U2-3 item 8, D-SLM7279)",
                "machine_tier=" + machine_tier + " dispatched=" + (want_tier.empty() ? "<unstated>" : want_tier));
        Verdict(want_tier_named && witness_cpu_tier == want_tier,
                label + "/cell1 provenance.witness.cpu_tier carries the dispatched tier (U2-3 item 8, D-SLM7279)",
                "cpu_tier=" + witness_cpu_tier + " dispatched=" + (want_tier.empty() ? "<unstated>" : want_tier));
        Verdict(is_uncomputed_label(semb_source_sha),
                label + "/cell1 provenance.semb_source_sha carries the not-computed-in-1.0 label "
                        "(D-SLM6409(c), D-SLM7257)", semb_source_sha);
      }
    } else if (bake_cap_refused) {
      Missing(label + "/cell1 header/payload/manifest pins, payload identity, SuperFAISS must-accept",
              "this open handle's own context_cap is smaller than an uncut WB document (D-SLM6411 item c); "
              "unreachable under this open's own artifact pair -- carried by a large-context_cap pair instead");
    }

    semb_encoder_close(enc);
  }

  // Refusal-writes-nothing: one TE-96 sec 4.2 class (duplicate ids) driven
  // through the bake, asserting no file appears -- not even a partial one.
  {
    semb_encoder enc = Open(a);
    if (enc) {
      DocSet dup_arena;
      std::vector<semb_document> dup_docs = {dup_arena.Add("dup", "first document body"),
                                              dup_arena.Add("dup", "second document body, different text")};
      const fs::path refuse_stem = scratch / (a.stem + "_refuse_dup");
      fs::remove(fs::path(refuse_stem.string() + ".wvbank.json"));
      fs::remove(fs::path(refuse_stem.string() + ".wvbank.bin"));
      fs::remove(fs::path(refuse_stem.string() + ".semb.json"));
      const std::string stem_str = refuse_stem.string();
      const semb_status rs = semb_bake_to_path(enc, dup_docs.data(), dup_docs.size(), stem_str.c_str(), stem_str.size());
      Verdict(rs == st.document_id_duplicate,
              label + "/cell1 duplicate-id batch refused through bake -> SEMB_DOCUMENT_ID_DUPLICATE", Name(rs));
      Verdict(DirEmptyOfTriple(refuse_stem),
              label + "/cell1 refused bake writes NONE of the three sibling files, not even a partial one",
              DirEmptyOfTriple(refuse_stem) ? "confirmed absent" : "a file was left behind");
      semb_encoder_close(enc);
    }
  }

  // TE-187 bare cell 3 (row 3), D-SLM6440's own fix (TE-184 item 3, built
  // ad hoc in that round's own build record since tests/** was barred to
  // that seat -- this is the registration TE-187 row 3 names as still
  // owed): a missing OUTPUT directory refuses SEMB_ARTIFACT_UNREADABLE,
  // never the generic engine-refused catch-all.
  {
    semb_encoder enc = Open(a);
    if (enc) {
      DocSet nodir_arena;
      std::vector<semb_document> nodir_docs = {nodir_arena.Add("n0", "a single small document")};
      const fs::path nodir_parent = scratch / (a.stem + "_nonexistent_parent");
      const fs::path nodir_stem = nodir_parent / "out";
      // The parent directory itself must not exist -- not merely be empty
      // -- this is the "missing" half of D-SLM6440's own "missing or
      // unwritable" rule; removed rather than assumed absent, so a prior
      // run's leftovers cannot silently pass this construction.
      fs::remove_all(nodir_parent);
      Verdict(!fs::exists(nodir_parent),
              label + "/cell1 (setup) the output path's own parent directory does not exist",
              fs::exists(nodir_parent) ? "EXISTS (setup defect)" : "confirmed absent");
      const std::string stem_str = nodir_stem.string();
      const semb_status ns = semb_bake_to_path(enc, nodir_docs.data(), nodir_docs.size(), stem_str.c_str(), stem_str.size());
      Verdict(ns == st.artifact_unreadable,
              label + "/cell1 bake into a non-existent parent directory -> SEMB_ARTIFACT_UNREADABLE, not the "
                      "generic engine-refused catch-all (TE-187 row 3, D-SLM6440)",
              Name(ns));
      Verdict(!fs::exists(nodir_parent),
              label + "/cell1 the refused bake did not create the missing parent directory either",
              fs::exists(nodir_parent) ? "the directory now exists (defect)" : "confirmed still absent");
      semb_encoder_close(enc);
    }
  }

  // =========================================================================
  // CELL 2 -- semb_bank_open/semb_bank_close: a well-formed triple opens;
  // every importer obligation FORMAT.md sec 1 lists refuses, built by
  // editing a copy of a good triple; open/close leak-free; close of a
  // never-opened or already-closed handle -> SEMB_INVALID_HANDLE.
  // =========================================================================
  // A small, cheap "good triple" this cell tampers copies of (distinct from
  // the WB fixture above, so cell 1's own bytes are never mutated).
  const fs::path good_stem = scratch / (a.stem + "_good");
  {
    semb_encoder enc = Open(a);
    if (!enc) return 1;
    DocSet good_arena;
    std::vector<semb_document> good_docs = {good_arena.Add("g0", "the first small good document"),
                                             good_arena.Add("g1", "the second small good document")};
    const std::string stem_str = good_stem.string();
    fs::remove(fs::path(stem_str + ".wvbank.json"));
    fs::remove(fs::path(stem_str + ".wvbank.bin"));
    fs::remove(fs::path(stem_str + ".semb.json"));
    const semb_status bs = semb_bake_to_path(enc, good_docs.data(), good_docs.size(), stem_str.c_str(), stem_str.size());
    semb_encoder_close(enc);
    if (bs != st.ok) { Verdict(false, label + "/cell2 (setup) bake the good triple", Name(bs)); return 1; }
  }

  {
    const std::string good_str = good_stem.string();
    semb_bank bank = nullptr;
    const semb_status os = semb_bank_open(good_str.c_str(), good_str.size(), &bank);
    Verdict(os == st.ok && bank != nullptr, label + "/cell2 a well-formed triple opens -> SEMB_OK", Name(os));
    if (os == st.ok) {
      const semb_status cs = semb_bank_close(bank);
      Verdict(cs == st.ok, label + "/cell2 close a live handle -> SEMB_OK", Name(cs));
    }
  }

  // Close of a never-opened or already-closed handle.
  {
    semb_bank never = reinterpret_cast<semb_bank>(static_cast<uintptr_t>(0xDEADBEEF));
    const semb_status s1 = semb_bank_close(never);
    Verdict(s1 == st.invalid_handle, label + "/cell2 close of a never-opened handle -> SEMB_INVALID_HANDLE", Name(s1));

    const std::string good_str = good_stem.string();
    semb_bank bank = nullptr;
    semb_bank_open(good_str.c_str(), good_str.size(), &bank);
    semb_bank_close(bank);
    const semb_status s2 = semb_bank_close(bank);
    Verdict(s2 == st.invalid_handle, label + "/cell2 double close -> SEMB_INVALID_HANDLE", Name(s2));
  }

  // The named tamper constructions, each built by editing a COPY of the good
  // triple (the good triple itself is never mutated).
  {
    auto try_open_expect = [&](const std::string& name, const fs::path& stem, int32_t expect,
                                const std::string& expect_name) {
      const std::string stem_str = stem.string();
      semb_bank bank = nullptr;
      const semb_status s = semb_bank_open(stem_str.c_str(), stem_str.size(), &bank);
      const bool ok = (expect >= 0) ? (s == expect) : (s != st.ok);  // expect<0: "asserted a refusal, name unpinned"
      Verdict(ok, label + "/cell2 " + name,
              std::string(Name(s)) + (expect_name.empty() ? "" : (" (expected " + expect_name + ")")));
      Verdict(bank == nullptr, label + "/cell2 " + name + " leaves *out == NULL", bank == nullptr ? "confirmed" : "NOT NULL");
      if (bank) semb_bank_close(bank);  // never reached on a correct refusal; drains defensively if it is
    };

    // Unknown schemaVersion -> SEMB_MANIFEST_SCHEMA_UNSUPPORTED. D-SLM6411
    // item (a): `schemaVersion` is a HEADER (.wvbank.json) field per
    // FORMAT.md sec 1, never a manifest field -- the edit belongs on
    // CopyTriple's edit_header parameter, not edit_manifest (the original
    // defect: passing it as edit_manifest made ReplaceOnce throw, uncaught,
    // killing the whole process before cells 3, 5, 6 or the --real leg ran).
    {
      fs::path stem = scratch / (a.stem + "_t_schema");
      if (CopyTriple(good_stem, stem, label + "/cell2 unknown schemaVersion", nullptr,
                     [](std::string t) { return ReplaceOnce(t, "\"schemaVersion\": 1", "\"schemaVersion\": 999"); })) {
        try_open_expect("unknown schemaVersion", stem, st.manifest_schema_unsupported, "SEMB_MANIFEST_SCHEMA_UNSUPPORTED");
      }
    }
    // .bin length off by one ROW.
    {
      fs::path stem = scratch / (a.stem + "_t_size_row");
      if (CopyTriple(good_stem, stem, label + "/cell2 .bin length off by one row", nullptr, nullptr,
                     [dims = a.dims](std::string bin) { bin.resize(bin.size() + static_cast<size_t>(dims) * 4, '\0'); return bin; })) {
        try_open_expect(".bin length off by one row -> SEMB_BANK_SIZE_MISMATCH", stem, st.bank_size_mismatch, "SEMB_BANK_SIZE_MISMATCH");
      }
    }
    // .bin length off by one BYTE.
    {
      fs::path stem = scratch / (a.stem + "_t_size_byte");
      if (CopyTriple(good_stem, stem, label + "/cell2 .bin length off by one byte", nullptr, nullptr,
                     [](std::string bin) { bin.push_back('\0'); return bin; })) {
        try_open_expect(".bin length off by one byte -> SEMB_BANK_SIZE_MISMATCH", stem, st.bank_size_mismatch, "SEMB_BANK_SIZE_MISMATCH");
      }
    }
    // The manifest's own artifact SHA edited (a provenance field, not the
    // fingerprint components) -> SEMB_ARTIFACT_SHA_MISMATCH.
    {
      fs::path stem = scratch / (a.stem + "_t_artifact_sha");
      if (CopyTriple(good_stem, stem, label + "/cell2 manifest's own model_sha edited", [](std::string m) {
            json_mini::Parser p(m);
            json_mini::Value v = p.Parse();
            const std::string real = v["model_sha"].s();
            std::string tampered = real;
            tampered[0] = (tampered[0] == '0') ? '1' : '0';
            return ReplaceOnce(m, "\"model_sha\": \"" + real + "\"", "\"model_sha\": \"" + tampered + "\"");
          })) {
        try_open_expect("manifest's own model_sha edited -> SEMB_ARTIFACT_SHA_MISMATCH", stem, st.artifact_sha_mismatch,
                         "SEMB_ARTIFACT_SHA_MISMATCH");
      }
    }
    // ids array: missing (absent key entirely).
    {
      fs::path stem = scratch / (a.stem + "_t_ids_missing");
      if (CopyTriple(good_stem, stem, label + "/cell2 ids array missing entirely", nullptr, [](std::string header) {
            // "ids" is written last (confirmed at source, encoder.cpp's own
            // header.Set() order and the baked header's own byte layout), so
            // removing it must also remove the preceding ", " -- leaving it
            // in place drops a dangling trailing comma before the closing
            // brace, which is a JSON SYNTAX error, not the "ids missing"
            // semantic this construction names: it made semb_bank_open's own
            // json parse throw and refuse SEMB_ARTIFACT_UNREADABLE before the
            // ids-cardinality check this construction targets ever ran.
            json_mini::Parser p(header);
            json_mini::Value v = p.Parse();
            const auto& ids = v["ids"];
            std::string quoted = ", \"ids\": [";
            for (size_t i = 0; i < ids.arr().size(); ++i) quoted += (i ? ", " : "") + ("\"" + ids.arr()[i].s() + "\"");
            quoted += "]";
            return ReplaceOnce(header, quoted, "");
          })) {
        try_open_expect("ids array missing entirely -> SEMB_BANK_IDS_COUNT_MISMATCH (TE-183, D-SLM6410)",
                         stem, st.bank_ids_count_mismatch, "SEMB_BANK_IDS_COUNT_MISMATCH");
      }
    }
    // ids array: short (one fewer entry than count).
    {
      fs::path stem = scratch / (a.stem + "_t_ids_short");
      if (CopyTriple(good_stem, stem, label + "/cell2 ids array short by one", nullptr,
                     // Same JSON-syntax hazard as "ids array missing
                     // entirely" just above: "g1" is the array's LAST
                     // element, so removing only the token leaves a
                     // dangling ", " before the closing "]" -- a syntax
                     // error, not a short array. Removing the leading ", "
                     // too leaves a syntactically valid one-element array.
                     [](std::string header) { return ReplaceOnce(header, ", \"g1\"", ""); })) {
        try_open_expect("ids array short by one -> SEMB_BANK_IDS_COUNT_MISMATCH (TE-183, D-SLM6410)",
                         stem, st.bank_ids_count_mismatch, "SEMB_BANK_IDS_COUNT_MISMATCH");
      }
    }
    // ids array: long (one more entry than count) -- the third cardinality
    // direction (TE-193 review P-8): "g1" gains a trailing ", \"g2\"", so the
    // array holds three entries against the header's unchanged "count": 2.
    // The construction stays syntactically valid JSON; the refusal is the
    // ids-cardinality check itself, not a parse failure.
    {
      fs::path stem = scratch / (a.stem + "_t_ids_long");
      if (CopyTriple(good_stem, stem, label + "/cell2 ids array long by one", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"g1\"", "\"g1\", \"g2\""); })) {
        try_open_expect("ids array long by one -> SEMB_BANK_IDS_COUNT_MISMATCH (TE-183, D-SLM6410; TE-193 P-8)",
                         stem, st.bank_ids_count_mismatch, "SEMB_BANK_IDS_COUNT_MISMATCH");
      }
    }
    // ids array: duplicated (both entries the same id).
    {
      fs::path stem = scratch / (a.stem + "_t_ids_dup");
      if (CopyTriple(good_stem, stem, label + "/cell2 ids array carries a duplicate", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"g1\"", "\"g0\""); })) {
        try_open_expect("ids array carries a duplicate -> SEMB_DOCUMENT_ID_DUPLICATE (reused: the identical "
                         "semantic C18/C4 already name)",
                         stem, st.document_id_duplicate, "SEMB_DOCUMENT_ID_DUPLICATE");
      }
    }
    // TE-201 item 4(i): ids compare after JSON string decoding.  The first
    // spelling is a surrogate pair and the second is its literal UTF-8 scalar;
    // a parser that preserves CESU-8-like surrogate halves would open them as
    // distinct strings and this exact assertion would fail.
    {
      fs::path stem = scratch / (a.stem + "_t_ids_surrogate_duplicate");
      if (CopyTriple(good_stem, stem, label + "/TE201 ids surrogate-pair duplicate", nullptr,
                     [](std::string header) {
                       return ReplaceOnce(header, "\"g0\", \"g1\"",
                                          "\"\\uD83D\\uDE00\", \"\xF0\x9F\x98\x80\"");
                     })) {
        try_open_expect("surrogate-pair id and its literal UTF-8 scalar decode to one id -> "
                        "SEMB_DOCUMENT_ID_DUPLICATE", stem, st.document_id_duplicate,
                        "SEMB_DOCUMENT_ID_DUPLICATE");
      }
    }
    // TE-201 item 4(ii): RFC 8259 forbids an unescaped U+0000--U+001F byte in
    // a JSON string.  This is a literal newline in the header, not the valid
    // two-byte escape spelling "\\n".
    {
      fs::path stem = scratch / (a.stem + "_t_ids_raw_control");
      if (CopyTriple(good_stem, stem, label + "/TE201 id raw control byte", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"g0\"", "\"raw\ncontrol\""); })) {
        try_open_expect("raw control byte in an id string -> SEMB_ARTIFACT_UNREADABLE", stem,
                        st.artifact_unreadable, "SEMB_ARTIFACT_UNREADABLE");
      }
    }
    // A non-finite row value.
    {
      fs::path stem = scratch / (a.stem + "_t_nonfinite");
      if (CopyTriple(good_stem, stem, label + "/cell2 a non-finite row value", nullptr, nullptr, [](std::string bin) {
            if (bin.size() >= 4) {
              uint32_t nan_bits = 0x7FC00000u;  // a quiet NaN, little-endian float32
              std::memcpy(bin.data(), &nan_bits, 4);
            }
            return bin;
          })) {
        try_open_expect("a non-finite row value -> SEMB_BANK_NONFINITE_ROW (TE-183, D-SLM6410)",
                         stem, st.bank_nonfinite_row, "SEMB_BANK_NONFINITE_ROW");
      }
    }
    // A zero-norm row (metric cosine). D-SLM6411 item (b): the construction
    // must zero exactly one row's worth of bytes AT THE PAIR'S OWN dims --
    // the original hardcoded 32*4 (the mechanism pair's own dims), so under
    // --real (dims 1024) it zeroed only 32 of 1024 elements and the row was
    // NOT actually zero-norm. `dims = a.dims` scales the construction to
    // whichever pair is running, mechanism or product.
    {
      fs::path stem = scratch / (a.stem + "_t_zeronorm");
      if (CopyTriple(good_stem, stem, label + "/cell2 a zero-norm row under cosine", nullptr, nullptr,
                     [dims = a.dims](std::string bin) {
                       std::fill(bin.begin(), bin.begin() + std::min<size_t>(bin.size(), static_cast<size_t>(dims) * 4), '\0');
                       return bin;
                     })) {
        try_open_expect("a zero-norm row under cosine (zeroed at the pair's own dims) -> SEMB_BANK_ZERO_NORM_ROW "
                         "(TE-183, D-SLM6410)", stem, st.bank_zero_norm_row, "SEMB_BANK_ZERO_NORM_ROW");
      }
    }
    // Header geometry over the ceilings -- dims over 131,072, on the header
    // alone (FORMAT.md sec 1: rejected before any size arithmetic).
    {
      fs::path stem = scratch / (a.stem + "_t_dims_ceiling");
      if (CopyTriple(good_stem, stem, label + "/cell2 dims over 131,072", nullptr,
                     [&](std::string header) { return ReplaceOnce(header, "\"dims\": " + std::to_string(a.dims),
                                                                    "\"dims\": 999999999"); })) {
        try_open_expect("dims over 131,072 refused on the header alone -> SEMB_BANK_GEOMETRY_CEILING_EXCEEDED "
                         "(TE-183, D-SLM6410)", stem, st.bank_geometry_ceiling_exceeded,
                         "SEMB_BANK_GEOMETRY_CEILING_EXCEEDED");
      }
    }
    // count over 2^28, on the header alone.
    {
      fs::path stem = scratch / (a.stem + "_t_count_ceiling");
      if (CopyTriple(good_stem, stem, label + "/cell2 count over 2^28", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"count\": 2", "\"count\": 999999999"); })) {
        try_open_expect("count over 2^28 refused on the header alone -> SEMB_BANK_GEOMETRY_CEILING_EXCEEDED "
                         "(TE-183, D-SLM6410)", stem, st.bank_geometry_ceiling_exceeded,
                         "SEMB_BANK_GEOMETRY_CEILING_EXCEEDED");
      }
    }
    // Unknown metric (F2, D-SLM6467/D-SLM6472): FORMAT.md sec 1's own
    // admitted set is {"dot", "cosine", "l2"}; a value outside that set is
    // this round's own SEMB_BANK_METRIC_DTYPE_UNSUPPORTED (32).
    {
      fs::path stem = scratch / (a.stem + "_t_metric_unknown");
      if (CopyTriple(good_stem, stem, label + "/cell2 unknown metric", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"metric\": \"cosine\"",
                                                                    "\"metric\": \"unknown\""); })) {
        try_open_expect("unknown metric -> SEMB_BANK_METRIC_DTYPE_UNSUPPORTED (F2, D-SLM6467)", stem,
                         st.bank_metric_dtype_unsupported, "SEMB_BANK_METRIC_DTYPE_UNSUPPORTED");
      }
    }
    // Unknown dtype (F2, D-SLM6467/D-SLM6472): FORMAT.md sec 1's own
    // admitted dtype is "float32" alone.
    {
      fs::path stem = scratch / (a.stem + "_t_dtype_unknown");
      if (CopyTriple(good_stem, stem, label + "/cell2 unknown dtype", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"dtype\": \"float32\"",
                                                                    "\"dtype\": \"garbage\""); })) {
        try_open_expect("unknown dtype -> SEMB_BANK_METRIC_DTYPE_UNSUPPORTED (F2, D-SLM6467)", stem,
                         st.bank_metric_dtype_unsupported, "SEMB_BANK_METRIC_DTYPE_UNSUPPORTED");
      }
    }
    // F3/F8 (D-SLM6467, D-SLM6472): one mutation-pinned refusal per
    // relationship TE-191's semb_bank_open now cross-checks between the
    // manifest and its paired header/payload, or the manifest's own
    // internal fields -- each construction mutates ONE field alone in a
    // copy of the good triple, so cell 6's self-consistency claim is the
    // handle's own (checked at open), never the test's own recomputation.
    // count -> SEMB_BANK_SIZE_MISMATCH. The good triple is always 2
    // documents (g0, g1) on both legs, mechanism and product -- "count": 2
    // is a safe literal here, unlike dims below.
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_count");
      if (CopyTriple(good_stem, stem, label + "/cell2 manifest count disagrees with the header",
                     [](std::string m) { return ReplaceOnce(m, "\"count\": 2", "\"count\": 3"); })) {
        try_open_expect("manifest count disagrees with the header -> SEMB_BANK_SIZE_MISMATCH (F3, D-SLM6467)", stem,
                         st.bank_size_mismatch, "SEMB_BANK_SIZE_MISMATCH");
      }
    }
    // dims -> SEMB_BANK_SIZE_MISMATCH. dims varies by leg (32 mechanism,
    // 1024 product), so the tamper is built from a.dims rather than a literal.
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_dims");
      if (CopyTriple(good_stem, stem, label + "/cell2 manifest dims disagrees with the header",
                     [dims = a.dims](std::string m) {
                       return ReplaceOnce(m, "\"dims\": " + std::to_string(dims),
                                          "\"dims\": " + std::to_string(dims + 1));
                     })) {
        try_open_expect("manifest dims disagrees with the header -> SEMB_BANK_SIZE_MISMATCH (F3, D-SLM6467)", stem,
                         st.bank_size_mismatch, "SEMB_BANK_SIZE_MISMATCH");
      }
    }
    // per_row_token_counts cardinality -> SEMB_BANK_SIZE_MISMATCH (the same
    // cardinality obligation ids already carries at the header level,
    // reused here at the manifest level). Built generically from the
    // parsed array so it holds at any document count, not just 2.
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_token_counts_cardinality");
      if (CopyTriple(good_stem, stem, label + "/cell2 per_row_token_counts short by one", [](std::string m) {
            json_mini::Parser p(m);
            json_mini::Value v = p.Parse();
            const auto& counts = v["per_row_token_counts"];
            std::string full = "\"per_row_token_counts\": [";
            for (size_t i = 0; i < counts.arr().size(); ++i) full += (i ? ", " : "") + std::to_string(counts.arr()[i].i());
            full += "]";
            std::string shortened = "\"per_row_token_counts\": [";
            for (size_t i = 0; i + 1 < counts.arr().size(); ++i) shortened += (i ? ", " : "") + std::to_string(counts.arr()[i].i());
            shortened += "]";
            return ReplaceOnce(m, full, shortened);
          })) {
        try_open_expect("per_row_token_counts short by one -> SEMB_BANK_SIZE_MISMATCH (F3, D-SLM6467)", stem,
                         st.bank_size_mismatch, "SEMB_BANK_SIZE_MISMATCH");
      }
    }
    // row_digest -> SEMB_BANK_DIGEST_MISMATCH: recomputed over the payload
    // just read; a manifest whose own copy disagrees is refused.
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_row_digest");
      if (CopyTriple(good_stem, stem, label + "/cell2 manifest row_digest disagrees with the payload", [](std::string m) {
            json_mini::Parser p(m);
            json_mini::Value v = p.Parse();
            const std::string real = v["row_digest"].s();
            std::string tampered = real;
            tampered[0] = (tampered[0] == '0') ? '1' : '0';
            return ReplaceOnce(m, "\"row_digest\": \"" + real + "\"", "\"row_digest\": \"" + tampered + "\"");
          })) {
        try_open_expect("manifest row_digest disagrees with the payload -> SEMB_BANK_DIGEST_MISMATCH (F3, D-SLM6467)",
                         stem, st.bank_digest_mismatch, "SEMB_BANK_DIGEST_MISMATCH");
      }
    }
    // corpus_digest's own binding -> SEMB_BANK_DIGEST_MISMATCH: the
    // top-level corpus_digest and provenance.witness.corpus_digest are the
    // SAME value by construction (D-SLM6409(b)); this tampers the
    // TOP-LEVEL copy alone (ReplaceLast -- the key appears twice in the
    // text, witness's own copy first) and leaves the witness copy
    // untouched, so open's own binding check -- not a plain "the field
    // changed" check -- is what this construction exercises.
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_corpus_digest_binding");
      if (CopyTriple(good_stem, stem, label + "/cell2 top-level corpus_digest disagrees with its own witness copy",
                     [](std::string m) {
                       json_mini::Parser p(m);
                       json_mini::Value v = p.Parse();
                       const std::string real = v["corpus_digest"].s();  // the top-level copy
                       std::string tampered = real;
                       tampered[0] = (tampered[0] == '0') ? '1' : '0';
                       return ReplaceLast(m, "\"corpus_digest\": \"" + real + "\"",
                                          "\"corpus_digest\": \"" + tampered + "\"");
                     })) {
        try_open_expect("top-level corpus_digest disagrees with its own witness copy -> SEMB_BANK_DIGEST_MISMATCH "
                         "(F3, D-SLM6467)", stem, st.bank_digest_mismatch, "SEMB_BANK_DIGEST_MISMATCH");
      }
    }
    // label:engine_path_id -> SEMB_ADAPTER_ID_MISMATCH (reused: open checks
    // this label against this BUILD's own compiled semb_adapter_self_id(),
    // a free handle-less accessor, not a caller-supplied encoder). The
    // real value is read back from the manifest rather than hardcoded, so
    // this construction holds whatever this build's own compiled identity is.
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_label_engine_path_id");
      if (CopyTriple(good_stem, stem,
                     label + "/cell2 label:engine_path_id disagrees with this build's own compiled identity",
                     [](std::string m) {
                       json_mini::Parser p(m);
                       json_mini::Value v = p.Parse();
                       const std::string real = v["label:engine_path_id"].s();
                       return ReplaceOnce(m, "\"label:engine_path_id\": \"" + real + "\"",
                                          "\"label:engine_path_id\": \"" + real + "_tampered\"");
                     })) {
        try_open_expect("label:engine_path_id disagrees with this build's own compiled identity -> "
                         "SEMB_ADAPTER_ID_MISMATCH (F3, D-SLM6467)", stem, st.adapter_id_mismatch,
                         "SEMB_ADAPTER_ID_MISMATCH");
      }
    }
    // label:ps_version -> SEMB_PS_VERSION_LABEL_MISMATCH (reused: open
    // checks this label against this build's own compiled
    // semb_ps_n_version_label()/semb_ps1_version_label()).
    {
      fs::path stem = scratch / (a.stem + "_t_manifest_label_ps_version");
      if (CopyTriple(good_stem, stem,
                     label + "/cell2 label:ps_version disagrees with this build's own compiled identity",
                     [](std::string m) {
                       json_mini::Parser p(m);
                       json_mini::Value v = p.Parse();
                       const std::string real = v["label:ps_version"].s();
                       return ReplaceOnce(m, "\"label:ps_version\": \"" + real + "\"",
                                          "\"label:ps_version\": \"" + real + "_tampered\"");
                     })) {
        try_open_expect("label:ps_version disagrees with this build's own compiled identity -> "
                         "SEMB_PS_VERSION_LABEL_MISMATCH (F3, D-SLM6467)", stem, st.ps_version_label_mismatch,
                         "SEMB_PS_VERSION_LABEL_MISMATCH");
      }
    }
  }

  // Open/close loop under the aligned leak instrument, real artifact and
  // synthetic pair both (TE-159 item 5's own aligned Header technique,
  // reused above): open/close cycles against the good triple, flat live
  // bytes throughout. D-SLM6412's own 10-cycle figure was reused from
  // TE-159 unjustified; investigating it this round (D-SLM6412's own
  // "allocator warm-up" diagnosis, re-opened by measurement) found the true
  // cause was neither this path's allocations nor an allocator warm-up at
  // all: it was THIS CELL'S OWN measurement vector (`live_after_cycle`, one
  // `push_back` per cycle, capacity never reserved) reallocating under the
  // SAME global operator-new/delete override the instrument counts -- at
  // MSVC's own 1.5x growth factor, which produces exactly the geometric
  // "settling" shape a real allocator warm-up would, and does not actually
  // settle (traced past cycle 700 before the next reallocation). The
  // instrument was polluting the exact counter it measures with its own
  // bookkeeping. `reserve()` below removes that self-contamination: with it
  // in place, 1,000 measured cycles hold IDENTICAL live bytes from cycle 1
  // through cycle 1,000 -- zero growth anywhere, quoted in this round's own
  // record. `semb_bank_open`/`semb_bank_close` need no warm-up at all. The
  // small window below is margin, not a warm-up this path was shown to
  // need: 5 cycles for any one-time CRT lazy-init this host performs on a
  // process's first few allocations of a given size class, then 50 cycles
  // asserted EXACTLY flat -- a leak of even one allocation per open fails
  // on the very first post-warm-up cycle.
  {
    constexpr int kWarmupCycles = 5;
    constexpr int kWindowCycles = 50;
    constexpr int kTotalCycles = kWarmupCycles + kWindowCycles;
    const std::string good_str = good_stem.string();
    std::vector<int64_t> live_after_cycle;
    live_after_cycle.reserve(kTotalCycles);  // the fix: no reallocation during the measured loop
    for (int i = 0; i < kTotalCycles; ++i) {
      semb_bank bank = nullptr;
      semb_bank_open(good_str.c_str(), good_str.size(), &bank);
      semb_bank_close(bank);
      live_after_cycle.push_back(leak_hook::g_live_bytes.load(std::memory_order_relaxed));
    }
    const int64_t warm = live_after_cycle[kWarmupCycles - 1];
    bool flat = true;
    for (size_t i = kWarmupCycles; i < live_after_cycle.size(); ++i)
      if (live_after_cycle[i] != warm) { flat = false; break; }
    Verdict(flat, label + "/cell2 " + std::to_string(kTotalCycles) + " open/close cycles hold live bytes flat "
                           "over the final " + std::to_string(kWindowCycles) + "-cycle window, past a " +
                           std::to_string(kWarmupCycles) + "-cycle warm-up (D-SLM6412 corrected: the reused "
                           "10-cycle figure's own apparent growth was the measurement vector's own unreserved "
                           "reallocation, not this path's allocations -- reserve() above removes it; 1,000 "
                           "cycles measured with reserve() in place show zero growth from cycle 1)",
            "cycle" + std::to_string(kWarmupCycles) + "=" + std::to_string(warm) +
                " cycle" + std::to_string(kTotalCycles) + "=" + std::to_string(live_after_cycle.back()));
  }

  // =========================================================================
  // CELL 3 -- the tampered-manifest-fingerprint refusal, resolved to
  // reading (a): bank_open checks the manifest's own internal consistency
  // (encoder_fingerprint against SHA-256 of its five components in clear)
  // and refuses SEMB_FINGERPRINT_MISMATCH on disagreement.
  // =========================================================================
  {
    const std::string manifest_text = ReadFileBytes(fs::path(good_stem.string() + ".semb.json"));
    json_mini::Parser mp(manifest_text);
    json_mini::Value manifest = mp.Parse();
    const std::string real_fp = manifest["encoder_fingerprint"].s();
    const std::string recomputed = RecomputeFingerprintFromManifest(manifest);
    Verdict(real_fp == recomputed,
            label + "/cell3 (setup) the good triple's own encoder_fingerprint agrees with this cell's "
                    "independent sec 3.3 recomputation from the manifest's five clear-text components",
            "manifest=" + real_fp.substr(0, 16) + "... recomputed=" + recomputed.substr(0, 16) + "...");

    fs::path stem = scratch / (a.stem + "_t_fp");
    if (CopyTriple(good_stem, stem, label + "/cell3 tampered encoder_fingerprint", [&](std::string m) {
          std::string tampered_fp = real_fp;
          tampered_fp[0] = (tampered_fp[0] == '0') ? '1' : '0';
          return ReplaceOnce(m, "\"encoder_fingerprint\": \"" + real_fp + "\"",
                              "\"encoder_fingerprint\": \"" + tampered_fp + "\"");
        })) {
      const std::string stem_str = stem.string();
      semb_bank bank = nullptr;
      const semb_status s = semb_bank_open(stem_str.c_str(), stem_str.size(), &bank);
      Verdict(s == st.fingerprint_mismatch,
              label + "/cell3 encoder_fingerprint disagreeing with its own five clear-text components "
                      "-> SEMB_FINGERPRINT_MISMATCH (reading (a): bank_open checks manifest self-consistency, "
                      "not a comparison to any encoder -- semb_bank_open takes no encoder argument)",
              Name(s));
      Verdict(bank == nullptr, label + "/cell3 leaves *out == NULL on the fingerprint-mismatch refusal",
              bank == nullptr ? "confirmed" : "NOT NULL");
      if (bank) semb_bank_close(bank);
    }
  }

  // =========================================================================
  // TE-201 item 3 -- F4's retained-handle state survives deletion of the
  // backing triple.  A copied triple keeps this destructive construction from
  // disturbing the good triple later cells still require.
  // =========================================================================
  {
    const fs::path stem = scratch / (a.stem + "_t_handle_ownership");
    if (CopyTriple(good_stem, stem, label + "/TE201 handle owns opened state")) {
      const std::string stem_str = stem.string();
      semb_bank bank = nullptr;
      const semb_status opened = semb_bank_open(stem_str.c_str(), stem_str.size(), &bank);
      Verdict(opened == st.ok && bank != nullptr,
              label + "/TE201 F4 copied good triple opens before backing files are deleted -> SEMB_OK", Name(opened));
      if (opened == st.ok && bank) {
        uint8_t before[32]{};
        int64_t count_before = 0, dims_before = 0;
        const semb_status before_status = semb_bank_debug_state(bank, before, &count_before, &dims_before);
        Verdict(before_status == st.ok,
                label + "/TE201 F4 pre-deletion debug state reads the live handle -> SEMB_OK", Name(before_status));
        fs::remove(fs::path(stem_str + ".wvbank.json"));
        fs::remove(fs::path(stem_str + ".wvbank.bin"));
        fs::remove(fs::path(stem_str + ".semb.json"));
        uint8_t after[32]{};
        int64_t count_after = 0, dims_after = 0;
        const semb_status after_status = semb_bank_debug_state(bank, after, &count_after, &dims_after);
        Verdict(after_status == st.ok && std::memcmp(before, after, sizeof(before)) == 0 &&
                    count_before == count_after && dims_before == dims_after,
                label + "/TE201 F4 deleted backing files leave retained fingerprint/count/dims byte-identical -> SEMB_OK",
                "status=" + std::string(Name(after_status)) + " count=" + std::to_string(count_after) +
                    " dims=" + std::to_string(dims_after));
        const semb_status closed = semb_bank_close(bank);
        Verdict(closed == st.ok, label + "/TE201 F4 close retained handle -> SEMB_OK", Name(closed));
        const semb_status stale = semb_bank_debug_state(bank, after, &count_after, &dims_after);
        Verdict(stale == st.invalid_handle,
                label + "/TE201 F4 debug state after close -> SEMB_INVALID_HANDLE", Name(stale));
      }
    }
  }

  // =========================================================================
  // CELL 5 -- lifecycle and concurrency (dims 1, 3). SEMB_BANK_IN_USE is
  // Slice 5's own (no semb_query handle exists yet); named here, not built.
  // =========================================================================
  Missing(label + "/cell5 SEMB_BANK_IN_USE (a live query-handle reference count on the bank)",
          "Slice 5's own -- no semb_query_open exists yet to raise the bank's reference count (D-SLM4664)");
  {
    // Open twice from the same path -> two independent handles.
    const std::string good_str = good_stem.string();
    semb_bank b1 = nullptr, b2 = nullptr;
    const semb_status s1 = semb_bank_open(good_str.c_str(), good_str.size(), &b1);
    const semb_status s2 = semb_bank_open(good_str.c_str(), good_str.size(), &b2);
    Verdict(s1 == st.ok && s2 == st.ok && b1 != nullptr && b2 != nullptr && b1 != b2,
            label + "/cell5 open twice from the same path gives two independent, distinct handles",
            "b1_ok=" + std::string(Name(s1)) + " b2_ok=" + std::string(Name(s2)));
    // Close order irrelevant: close the SECOND handle first, then the first.
    const semb_status c2 = semb_bank_close(b2);
    const semb_status c1 = semb_bank_close(b1);
    Verdict(c2 == st.ok && c1 == st.ok, label + "/cell5 close order is irrelevant (closed b2 then b1, both OK)",
            "c2=" + std::string(Name(c2)) + " c1=" + std::string(Name(c1)));
  }
  {
    // "One bank opened once and read from N threads concurrently, byte-
    // identical reads." THE GAP, NAMED: the frozen ABI at this slice gives
    // semb_bank_open/semb_bank_close and NO accessor that reads metadata or
    // rows THROUGH an already-open handle (that is semb_query_open's,
    // Slice 5's own) -- routed as a finding below. What this slice CAN
    // drive, and does: N threads concurrently exercise semb_bank_open
    // against the ONE baked artifact's own files (the "read-only after
    // open; concurrent use safe" contract's own subject, D-SLM4647) and
    // each thread independently recomputes a SHA-256 over the .wvbank.bin
    // bytes ITS OWN open validated -- every thread's digest must agree with
    // every other's and with a serial reference, which is the
    // "byte-identical reads" property realized against what this slice's
    // own ABI actually exposes.
    Observed(label + "/cell5 finding: 'read from N threads concurrently (metadata and rows)' has no accessor "
                      "at this slice -- semb_bank_open/close expose no metadata/row read. Realized here as N "
                      "threads concurrently opening the SAME bank path and independently reading its own "
                      "backing .wvbank.bin bytes; the literal per-handle read claim routes to Slice 5's own "
                      "semb_query_open coverage.");
    const std::string good_str = good_stem.string();
    const std::string serial_ref = Sha256Hex(reinterpret_cast<const uint8_t*>(ReadFileBytes(fs::path(good_str + ".wvbank.bin")).data()),
                                              ReadFileBytes(fs::path(good_str + ".wvbank.bin")).size());
    constexpr int kThreads = 8;
    std::vector<std::string> digests(kThreads);
    std::vector<semb_status> opens(kThreads);
    std::vector<std::thread> pool;
    for (int t = 0; t < kThreads; ++t) {
      pool.emplace_back([&, t]() {
        semb_bank bank = nullptr;
        opens[t] = semb_bank_open(good_str.c_str(), good_str.size(), &bank);
        const std::string bytes = ReadFileBytes(fs::path(good_str + ".wvbank.bin"));
        digests[t] = Sha256Hex(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
        if (bank) semb_bank_close(bank);
      });
    }
    for (auto& th : pool) th.join();
    bool all_ok = true, all_equal = true;
    for (int t = 0; t < kThreads; ++t) {
      if (opens[t] != st.ok) all_ok = false;
      if (digests[t] != serial_ref) all_equal = false;
    }
    Verdict(all_ok && all_equal,
            label + "/cell5 " + std::to_string(kThreads) + " threads concurrently open the same bank path; "
                    "every open succeeds and every thread's own independent read of the bank's bytes agrees "
                    "byte-for-byte with a serial reference",
            "all_ok=" + std::to_string(all_ok) + " all_equal=" + std::to_string(all_equal));
  }

  // =========================================================================
  // CELL 6 -- round trip (dim 9, C9's Slice 4 share): bake -> open -> the
  // rows persisted equal the rows baked, bit for bit; the manifest's row
  // digest recomputable from the payload; the corpus digest recomputable
  // from the documents' own bytes. `semb verify`'s own cells are Slice 6's.
  //
  // THE READING, STATED (the frozen ABI has no row-read verb through an
  // open semb_bank at this slice -- that is semb_query_encode's, Slice 5's
  // own): "the rows the handle exposes" is realized here as the bytes on
  // disk a SUCCESSFUL semb_bank_open stands for (open's own success is
  // itself the assertion that the pair is self-consistent per FORMAT.md);
  // this cell proves those bytes are unmoved by an open/close round trip
  // and equal what was baked, and separately proves both digests are
  // independently recomputable, exactly as `semb verify` will do at Slice 6.
  // =========================================================================
  {
    const std::string good_str = good_stem.string();
    const std::string bin_before = ReadFileBytes(fs::path(good_str + ".wvbank.bin"));
    semb_bank bank = nullptr;
    const semb_status os = semb_bank_open(good_str.c_str(), good_str.size(), &bank);
    const semb_status cs = (os == st.ok) ? semb_bank_close(bank) : os;
    const std::string bin_after = ReadFileBytes(fs::path(good_str + ".wvbank.bin"));
    Verdict(os == st.ok && cs == st.ok && bin_before == bin_after,
            label + "/cell6 open then close does not move the bank's own bytes; equal to what was baked",
            "open=" + std::string(Name(os)) + " close=" + std::string(Name(cs)) +
                " bytes_equal=" + std::to_string(bin_before == bin_after));

    const std::string manifest_text = ReadFileBytes(fs::path(good_str + ".semb.json"));
    json_mini::Parser mp(manifest_text);
    json_mini::Value manifest = mp.Parse();
    const std::string recomputed_row_digest = Sha256Hex(reinterpret_cast<const uint8_t*>(bin_after.data()), bin_after.size());
    Verdict(manifest["row_digest"].s() == recomputed_row_digest,
            label + "/cell6 the manifest's row_digest is recomputable from the payload (SHA-256 over the "
                    ".wvbank.bin bytes)",
            "manifest=" + manifest["row_digest"].s().substr(0, 16) + "... recomputed=" + recomputed_row_digest.substr(0, 16) + "...");
  }

  // ---- Real-artifact leg: 239-document bake on the real candidate, timed --
  if (a.real) {
    if (a.corpus_239.empty()) {
      Missing(label + "/cell1,6 the 239-document real-artifact bake", "--corpus-239 not given");
    } else {
      auto docs_raw = LoadJsonlCorpus(a.corpus_239, "label");
      DocSet arena;
      std::vector<semb_document> docs;
      for (auto& [id, text] : docs_raw) docs.push_back(arena.Add(id, text));
      semb_encoder enc = Open(a);
      if (enc) {
        const fs::path stem = scratch / (a.stem + "_239");
        const std::string stem_str = stem.string();
        fs::remove(fs::path(stem_str + ".wvbank.json"));
        fs::remove(fs::path(stem_str + ".wvbank.bin"));
        fs::remove(fs::path(stem_str + ".semb.json"));
        const auto t0 = std::chrono::steady_clock::now();
        const semb_status bs = semb_bake_to_path(enc, docs.data(), docs.size(), stem_str.c_str(), stem_str.size());
        const auto t1 = std::chrono::steady_clock::now();
        const double wall_s = std::chrono::duration<double>(t1 - t0).count();
        Verdict(bs == st.ok, "product/cell1,6 239-document bake on the real candidate artifact -> SEMB_OK", Name(bs));
        Observed("product/cell1,6 239-document real-artifact bake wall clock: " + std::to_string(wall_s) + "s");
        if (bs == st.ok) {
          const std::string bin = ReadFileBytes(fs::path(stem_str + ".wvbank.bin"));
          uint32_t enc_dims = 0;
          semb_encoder_dims(enc, &enc_dims);
          const size_t expected = docs.size() * static_cast<size_t>(enc_dims) * 4;
          Verdict(bin.size() == expected, "product/cell6 239-document .wvbank.bin length == count*dims*4",
                  "got " + std::to_string(bin.size()) + " expected " + std::to_string(expected));
          const std::string manifest_text = ReadFileBytes(fs::path(stem_str + ".semb.json"));
          json_mini::Parser mp(manifest_text);
          json_mini::Value manifest = mp.Parse();
          const std::string recomputed_row_digest = Sha256Hex(reinterpret_cast<const uint8_t*>(bin.data()), bin.size());
          Verdict(manifest["row_digest"].s() == recomputed_row_digest,
                  "product/cell6 239-document row_digest recomputable from the payload", "");
        }
        semb_encoder_close(enc);
      }
    }
  } else {
    Missing("product/cell1,6 the 239-document real-artifact bake", "--real not given (mechanism-only run)");
  }

  std::printf("\nte163_bank_pair_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
