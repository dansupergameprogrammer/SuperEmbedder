// tests/u1_batch_contract_test.cpp -- TE-145 (U1 slice 2): the red suite for
// `semb_encode_batch`, the bake-side corpus entry point
// (`Claude/Plans/SuperEmbedder_Plan.md` sec 3.1; the ruled contract is
// `Claude/Fable/te96-u1-contract-closure-2026-09-05.md` sec 4, quoted by
// step number throughout this file). Cell group 1 of this slice's dispatch
// ("The batch contract driver"), plus C27's corpus form (sec 8 C27; TE-96
// sec 4.5's "matched by id" ruling), folded in here since neither needs the
// K-15 workspace seam (`tests/u1_batch_workspace_test.cpp` carries the
// seam-dependent cells: C4's no-forward-ran proof, C26's two races, C48,
// C49, C50 -- see that file's own header comment).
//
// RED-UNIMPLEMENTED at this branch's own base c0f52d4: `semb_encode_batch`
// is declared only in tests/semb_batch_abi_contract.h (this seat's own
// contract, TE-145) and nowhere in `superembedder`
// (`git grep -n semb_encode_batch src/ include/` returns nothing at
// c0f52d4) -- this executable fails to LINK until the builder's round adds
// it. tests/u1_batch_contract_check.py builds this target on demand and
// reports the unresolved symbol by name, the same red-first shape
// tests/u1_raw_text_cells_check.py already uses for the raw slice.
//
// STEP NUMBERS refer to TE-96 sec 4.2's table, reproduced here for the
// reader who has it open: 1 NULL_ARGUMENT (enc/out_required_bytes/docs-null-
// with-n>0); 2 INVALID_HANDLE; 3 n==0 -> CORPUS_EMPTY; 4 n > 2^28 ->
// CORPUS_TOO_LARGE, before the multiplication; 5 required = n*dims*4; 6
// MISALIGNED_BUFFER; 7 BUFFER_TOO_SMALL (the query form (NULL,0) lands
// here); 8 out_rows==NULL with sufficient capacity -> NULL_ARGUMENT; 9
// per-document, INDEX ORDER, first-failing-document's first-failing-check;
// 10 uniqueness over all n ids -> DOCUMENT_ID_DUPLICATE; 11 tokenize every
// document, context_cap -> CONTEXT_CAP_EXCEEDED (all rows tokenized before
// any forward); 12 one workspace for the whole call -> CONCURRENCY_EXCEEDED
// (covered by tests/u1_batch_workspace_test.cpp, which can actually hold the
// pool's only slot); 13 forward each row into STAGED storage, any runtime
// refusal discards the stage; 14 copy all rows, SEMB_OK.
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --dims <n> [--context-cap <n>]
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>
#include <utility>
#include <vector>

#include "semb_public_abi_contract.h"
#include "semb_batch_abi_contract.h"

// ---------------------------------------------------------------------------
// The allocation-failure hook, identical shape to
// tests/u1_raw_text_contract_test.cpp's own alloc_hook (Policy 1 only: the
// first allocation of at least g_fail_min_bytes bytes throws, then disarms).
// Reused rather than reinvented -- this project's own discipline (Slice 1's
// casebook, sec 6: "the identical canary PS-1's own cell uses (reused
// verbatim -- the canary is product-independent, and this project's
// discipline is one proven detector, not a second invented one)").
// ---------------------------------------------------------------------------
namespace alloc_hook {
std::atomic<std::size_t> g_fail_min_bytes{0};
std::atomic<std::uint64_t> g_fail_fired{0};
void ArmFail(std::size_t min_bytes) { g_fail_min_bytes.store(min_bytes, std::memory_order_release); }
void DisarmFail() { g_fail_min_bytes.store(0, std::memory_order_release); }
void* Allocate(std::size_t n) {
  std::size_t min = g_fail_min_bytes.load(std::memory_order_acquire);
  if (min != 0 && n >= min && g_fail_min_bytes.compare_exchange_strong(min, 0, std::memory_order_acq_rel)) {
    g_fail_fired.fetch_add(1, std::memory_order_acq_rel);
    throw std::bad_alloc();
  }
  void* p = std::malloc(n == 0 ? 1 : n);
  if (!p) throw std::bad_alloc();
  return p;
}
}  // namespace alloc_hook

void* operator new(std::size_t n) { return alloc_hook::Allocate(n); }
void* operator new[](std::size_t n) { return alloc_hook::Allocate(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }

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
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }

struct Statuses {
  int32_t ok, null_argument, struct_size_mismatch, invalid_handle, buffer_too_small, misaligned_buffer,
      input_empty, invalid_utf8, context_cap_exceeded, corpus_empty, document_id_invalid,
      document_id_duplicate, corpus_too_large, allocation_failed, engine_refused;
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
  s.invalid_utf8 = StatusByName("SEMB_INVALID_UTF8");
  s.context_cap_exceeded = StatusByName("SEMB_CONTEXT_CAP_EXCEEDED");
  s.corpus_empty = StatusByName("SEMB_CORPUS_EMPTY");
  s.document_id_invalid = StatusByName("SEMB_DOCUMENT_ID_INVALID");
  s.document_id_duplicate = StatusByName("SEMB_DOCUMENT_ID_DUPLICATE");
  s.corpus_too_large = StatusByName("SEMB_CORPUS_TOO_LARGE");
  s.allocation_failed = StatusByName("SEMB_ALLOCATION_FAILED");
  s.engine_refused = StatusByName("SEMB_ENGINE_REFUSED");
  return s;
}

struct Args {
  std::string model, tokenizer;
  unsigned dims = 0;
  size_t context_cap = 0;
};

Args ParseArgs(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&](std::string* v) { if (i + 1 < argc) *v = argv[++i]; };
    if (k == "--model") next(&a.model);
    else if (k == "--tokenizer") next(&a.tokenizer);
    else if (k == "--dims") { std::string v; next(&v); a.dims = static_cast<unsigned>(std::atoi(v.c_str())); }
    else if (k == "--context-cap") { std::string v; next(&v); a.context_cap = static_cast<size_t>(std::atoll(v.c_str())); }
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
  c.max_concurrency = 2;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&c, &enc);
  if (s != SEMB_OK || !enc) { Verdict(false, "(setup) open", Name(s)); return nullptr; }
  return enc;
}

// A 16-byte-aligned document row canary buffer: 0xA5-poisoned, with a 64-byte
// poisoned tail so an out-of-bounds write past `required` is caught by name
// (the same convention w_b_serialization_test.cpp uses for the serialiser,
// and TE-96 sec 4.7's own must-accept: "the row stride, order and tail
// preservation (`required + 64` bytes, the tail untouched)").
struct RowBuffer {
  std::vector<uint8_t> storage;
  size_t required = 0xBAD5EED;
  explicit RowBuffer(size_t capacity_bytes) : storage(capacity_bytes + 16 + 64) {
    std::memset(storage.data(), 0xA5, storage.size());
  }
  float* data() {
    auto p = reinterpret_cast<uintptr_t>(storage.data()) + 16;
    return reinterpret_cast<float*>((p + 15) & ~uintptr_t(15));
  }
  size_t capacity_bytes() const { return storage.size() - 16 - 64; }
  bool Untouched() const {
    for (auto b : storage) if (b != 0xA5) return false;
    return required == 0xBAD5EED;
  }
  // Everything outside [0, used_bytes) -- the alignment pad before, and the
  // capacity beyond used_bytes -- must still read 0xA5.
  bool GuardedTo(size_t used_bytes) const {
    auto begin = storage.data();
    auto first = reinterpret_cast<const uint8_t*>(const_cast<RowBuffer*>(this)->data());
    auto end = storage.data() + storage.size();
    for (auto p = begin; p < first; ++p) if (*p != 0xA5) return false;
    for (auto p = first + used_bytes; p < end; ++p) if (*p != 0xA5) return false;
    return true;
  }
  std::vector<uint8_t> Bytes(size_t used_bytes) {
    auto p = reinterpret_cast<uint8_t*>(data());
    return {p, p + used_bytes};
  }
};

// Owns a copy of every id/text string used to build a semb_document, in a
// non-reallocating arena (reserved ONCE, generously, before any entry is
// added) so a semb_document's raw pointers never dangle.
//
// THE BUG THIS REPLACES, FOUND BY EXECUTING THIS FILE (StandardsDocument.md
// sec 5.4: "exactness is verified at source or by execution, never by
// construction"): a first-draft `MakeDoc(const std::string& id, const
// std::string& text)` convenience overload, called as
// `MakeDoc("literal-id", "literal-text")`, binds each `const std::string&`
// parameter to a TEMPORARY std::string materialised from the string
// literal at the CALL SITE. That temporary is destroyed at the end of the
// FULL EXPRESSION that created it -- but the semb_document the overload
// returned carried a raw `.c_str()` POINTER into that temporary, and the
// caller then stored the struct in a `std::vector<semb_document>` for use
// SEVERAL STATEMENTS LATER, well after the temporary was gone. A scratch
// stand-in implementation (never committed; this seat's writable scope is
// tests/** and could not touch a product header to STUB `semb_encode_batch`
// for a self-test) exposed it immediately: cells running AFTER the first
// dangling MakeDoc call reported `SEMB_UNKNOWN` for a status that should
// have resolved cleanly, the classic later-manifesting symptom of a
// use-after-free. DocSet::Add is the fix -- it copies both strings into an
// arena reserved up front, so every returned semb_document's pointers stay
// valid for the arena's own lifetime, not the calling expression's.
class DocSet {
 public:
  DocSet() { arena_.reserve(kCapacity); }
  semb_document Add(std::string id, std::string text) {
    arena_.push_back(std::move(id));
    const std::string& stable_id = arena_.back();
    arena_.push_back(std::move(text));
    const std::string& stable_text = arena_.back();
    semb_document d{};
    d.struct_size = sizeof(semb_document);
    d.id = stable_id.c_str();
    d.id_len = stable_id.size();
    d.utf8 = stable_text.c_str();
    d.utf8_len = stable_text.size();
    return d;
  }
  // Raw variant for a NULL id/utf8 pointer, or a length deliberately
  // mismatched from a string's own size -- cases Add()'s owned-std::string
  // shape cannot represent. The caller's `id`/`text` pointers must
  // themselves outlive the returned struct's own use (a string literal,
  // whose storage is the whole program's lifetime, is always safe here).
  static semb_document Raw(const char* id, size_t id_len, const char* text, size_t text_len) {
    semb_document d{};
    d.struct_size = sizeof(semb_document);
    d.id = id;
    d.id_len = id_len;
    d.utf8 = text;
    d.utf8_len = text_len;
    return d;
  }

 private:
  static constexpr size_t kCapacity = 256;
  std::vector<std::string> arena_;
};

// The row/raw achievement oracle (TE-96 sec 4.7 must-accept, PS-N ships so
// no framing applies): row i of a batch equals semb_encode() of docs[i]'s
// own text, called through a FRESH handle so the comparison is not merely
// "the same handle agrees with itself."
std::vector<uint8_t> RawEncode(const Args& a, const std::string& text, semb_status* out_status) {
  semb_encoder enc = Open(a);
  if (!enc) { *out_status = -1; return {}; }
  RowBuffer buf(static_cast<size_t>(a.dims) * sizeof(float));
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  *out_status = semb_encode(enc, text.data(), text.size(), buf.data(), buf.capacity_bytes(), &buf.required, &fp);
  std::vector<uint8_t> out = (*out_status == SEMB_OK) ? buf.Bytes(buf.required) : std::vector<uint8_t>{};
  semb_encoder_close(enc);
  return out;
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0) {
    std::fprintf(stderr, "usage: %s --model <.sslm> --tokenizer <.sslm> --dims <n> [--context-cap <n>]\n", argv[0]);
    return 2;
  }
  const Statuses st = ResolveStatuses();
  const unsigned dims = a.dims;
  const size_t required1 = static_cast<size_t>(dims) * sizeof(float);
  DocSet docs_arena;  // see DocSet's own header comment: one non-reallocating arena for the whole run.

  // ---- Step 1/2: NULL_ARGUMENT / INVALID_HANDLE preconditions -------------
  {
    size_t req = 0xBAD5EED;
    const semb_status s1 = semb_encode_batch(nullptr, nullptr, 0, nullptr, 0, &req);
    Verdict(s1 == st.null_argument, "step1a enc==NULL -> SEMB_NULL_ARGUMENT", Name(s1));

    semb_encoder enc = Open(a);
    if (enc) {
      semb_document doc = docs_arena.Add("d0", "hello");
      const semb_status s2 = semb_encode_batch(enc, &doc, 1, nullptr, 0, nullptr);
      Verdict(s2 == st.null_argument, "step1b out_required_bytes==NULL -> SEMB_NULL_ARGUMENT", Name(s2));

      req = 0xBAD5EED;
      const semb_status s3 = semb_encode_batch(enc, nullptr, 1, nullptr, 0, &req);
      Verdict(s3 == st.null_argument, "step1c docs==NULL with n>0 -> SEMB_NULL_ARGUMENT (P-8's span rule)", Name(s3));
      semb_encoder_close(enc);
    }
  }

  // ---- Step 2, real cell (kept separate: a closed handle) ------------------
  {
    semb_encoder enc = Open(a);
    if (enc) {
      semb_encoder_close(enc);
      semb_document doc = docs_arena.Add("d0", "hello");
      size_t req = 0xBAD5EED;
      const semb_status s = semb_encode_batch(enc, &doc, 1, nullptr, 0, &req);
      Verdict(s == st.invalid_handle, "step2 a closed (non-live) cookie -> SEMB_INVALID_HANDLE", Name(s));
    }
  }

  semb_encoder enc = Open(a);
  if (!enc) { std::printf("\nu1_batch_contract_test: setup failed, cannot proceed\n"); return 1; }

  // ---- Step 3: n == 0, whatever docs is ------------------------------------
  {
    size_t req = 0xBAD5EED;
    semb_status s = semb_encode_batch(enc, nullptr, 0, nullptr, 0, &req);
    Verdict(s == st.corpus_empty, "step3a n==0, docs==NULL -> SEMB_CORPUS_EMPTY", Name(s));
    semb_document doc = docs_arena.Add("d0", "hello");
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, &doc, 0, nullptr, 0, &req);
    Verdict(s == st.corpus_empty, "step3b n==0, docs!=NULL -> SEMB_CORPUS_EMPTY (whatever docs is)", Name(s));
  }

  // ---- Step 4: n > 2^28, BEFORE the multiplication -------------------------
  // docs is a deliberately non-dereferenceable pointer: if the product
  // computed `n * dims * 4` or touched docs[0] before checking n against
  // the ceiling, this crashes instead of returning a clean status -- the
  // able-to-fail shape TE-96 sec 4.2 step 4 itself calls out ("checked
  // BEFORE the multiplication").
  {
    const semb_document* poison_docs = reinterpret_cast<const semb_document*>(uintptr_t{1});
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, poison_docs, kSembMaxCorpusRows + 1, nullptr, 0, &req);
    Verdict(s == st.corpus_too_large,
            "step4 n = 2^28+1 with an undereferenceable docs pointer -> SEMB_CORPUS_TOO_LARGE, no crash, "
            "checked before docs is ever touched",
            Name(s));
  }

  // ---- Step 6: misaligned out_rows, checked BEFORE step 7's capacity ------
  {
    std::vector<semb_document> docs = {docs_arena.Add("d0", "hello"), docs_arena.Add("d1", "world")};
    std::vector<uint8_t> raw(2 * required1 + 64, 0xA5);
    // Deliberately misaligned: offset 1 from any 16-byte boundary, with
    // capacity generously sufficient so a capacity-first implementation
    // would report BUFFER_TOO_SMALL instead of MISALIGNED_BUFFER (they must
    // not, per the precedence order: misalignment precedes capacity).
    uint8_t* base = raw.data();
    uintptr_t aligned = (reinterpret_cast<uintptr_t>(base) + 15) & ~uintptr_t(15);
    float* misaligned = reinterpret_cast<float*>(aligned + 1);
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), misaligned, raw.size(), &req);
    Verdict(s == st.misaligned_buffer,
            "step6 a misaligned out_rows -> SEMB_MISALIGNED_BUFFER, before capacity is even examined", Name(s));
  }

  // ---- Step 7: capacity too small; the query form (NULL, 0) lands here ----
  {
    std::vector<semb_document> docs = {docs_arena.Add("d0", "hello"), docs_arena.Add("d1", "greetings")};
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), nullptr, 0, &req);
    Verdict(s == st.buffer_too_small && req == docs.size() * required1,
            "step7a the query form (out_rows=NULL, out_capacity_bytes=0) -> SEMB_BUFFER_TOO_SMALL, "
            "*out_required_bytes = n*dims*4, no row written (TE-96 sec 4.7 must-accept)",
            "status=" + std::string(Name(s)) + " required=" + std::to_string(req) +
                " expected=" + std::to_string(docs.size() * required1));

    RowBuffer too_small(docs.size() * required1 - 4);  // one float short
    req = 0xBAD5EED;
    const semb_status s2 = semb_encode_batch(enc, docs.data(), docs.size(), too_small.data(),
                                              too_small.capacity_bytes(), &req);
    Verdict(s2 == st.buffer_too_small && req == docs.size() * required1 && too_small.Untouched(),
            "step7b capacity one float short of required -> SEMB_BUFFER_TOO_SMALL, required stated, buffer untouched",
            "status=" + std::string(Name(s2)) + " required=" + std::to_string(req));
  }

  // ---- Step 8: out_rows == NULL with sufficient capacity -------------------
  {
    std::vector<semb_document> docs = {docs_arena.Add("d0", "hello")};
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), nullptr, required1, &req);
    Verdict(s == st.null_argument,
            "step8 out_rows==NULL with out_capacity_bytes==required (sufficient) -> SEMB_NULL_ARGUMENT "
            "(distinct from the query form, which has capacity 0)",
            Name(s));
  }

  // ---- Step 9: per-document, INDEX ORDER, first-failing CHECK -------------
  {
    // 9a: struct_size mismatch on document k>0, out_rows untouched.
    std::vector<semb_document> docs = {docs_arena.Add("d0", "hello"), docs_arena.Add("d1", "world")};
    docs[1].struct_size = sizeof(semb_document) - 1;
    RowBuffer buf(2 * required1);
    size_t req = 0xBAD5EED;
    semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.struct_size_mismatch && buf.Untouched(),
            "step9a wrong struct_size on document index 1 -> SEMB_STRUCT_SIZE_MISMATCH, out_rows untouched",
            Name(s));

    // 9b: id==NULL && id_len>0 on document 0 -> NULL_ARGUMENT.
    docs = {DocSet::Raw(nullptr, 3, "hello", 5), docs_arena.Add("d1", "world")};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.null_argument, "step9b id==NULL, id_len>0 -> SEMB_NULL_ARGUMENT", Name(s));

    // 9c: utf8==NULL && utf8_len>0 -> NULL_ARGUMENT.
    docs = {DocSet::Raw("d0", 2, nullptr, 5)};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.null_argument, "step9c utf8==NULL, utf8_len>0 -> SEMB_NULL_ARGUMENT", Name(s));

    // 9d: id_len == 0 -> DOCUMENT_ID_INVALID.
    docs = {DocSet::Raw("", 0, "hello", 5)};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.document_id_invalid, "step9d empty id (id_len==0) -> SEMB_DOCUMENT_ID_INVALID", Name(s));

    // 9e: id with a NUL byte -> DOCUMENT_ID_INVALID.
    {
      docs = {docs_arena.Add(std::string("a\0b", 3), "hello")};
      req = 0xBAD5EED;
      s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
      Verdict(s == st.document_id_invalid, "step9e id containing a NUL byte -> SEMB_DOCUMENT_ID_INVALID", Name(s));
    }

    // 9f: id not well-formed UTF-8 (lone continuation byte) -> DOCUMENT_ID_INVALID.
    {
      std::string bad_id;
      bad_id.push_back(static_cast<char>(0x80));
      docs = {docs_arena.Add(bad_id, "hello")};
      req = 0xBAD5EED;
      s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
      Verdict(s == st.document_id_invalid, "step9f id not well-formed UTF-8 -> SEMB_DOCUMENT_ID_INVALID", Name(s));
    }

    // 9g: utf8_len == 0 -> INPUT_EMPTY.
    docs = {docs_arena.Add("d0", "")};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.input_empty, "step9g empty document text (utf8_len==0) -> SEMB_INPUT_EMPTY", Name(s));

    // 9h: utf8 not well-formed UTF-8 -> INVALID_UTF8.
    {
      std::string bad_text;
      bad_text.push_back(static_cast<char>(0xC0));  // overlong lead, never valid
      docs = {docs_arena.Add("d0", bad_text)};
      req = 0xBAD5EED;
      s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
      Verdict(s == st.invalid_utf8, "step9h document text not well-formed UTF-8 -> SEMB_INVALID_UTF8", Name(s));
    }

    // 9-order: a document failing BOTH struct_size and id-invalid resolves
    // to struct_size (listed first in step 9's own precedence).
    docs = {DocSet::Raw("", 0, "hello", 5)};
    docs[0].struct_size = sizeof(semb_document) - 1;
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.struct_size_mismatch,
            "step9-order struct_size wrong AND id empty on the same document -> struct_size wins (listed first)",
            Name(s));
    // A document failing both id-invalid and utf8-empty resolves to id
    // (listed before utf8_len==0 in step 9's own order).
    docs = {DocSet::Raw("", 0, "", 0)};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.document_id_invalid,
            "step9-order empty id AND empty text on the same document -> id wins (listed before utf8_len==0)",
            Name(s));

    // 9-index-order: document 0 is well-formed; the FIRST failing document
    // is index 2 (not the earliest-failing CHECK across the whole array).
    docs = {docs_arena.Add("ok0", "fine"), docs_arena.Add("ok1", "also fine"), DocSet::Raw("", 0, "bad id", 6)};
    RowBuffer buf3(3 * required1);
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf3.data(), buf3.capacity_bytes(), &req);
    Verdict(s == st.document_id_invalid && buf3.Untouched(),
            "step9-index-order two good documents then a bad one at index 2 -> refuses on index 2's own "
            "failure, nothing written for any row",
            Name(s));
  }

  // ---- Step 10: uniqueness over ALL n ids, byte identity (sec 4.3) --------
  {
    RowBuffer buf(2 * required1);
    std::vector<semb_document> docs = {docs_arena.Add("dup", "first"), docs_arena.Add("dup", "second")};
    size_t req = 0xBAD5EED;
    semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.document_id_duplicate && buf.Untouched(),
            "step10a byte-identical ids from DISTINCT storage (two separate std::string backings) -> "
            "SEMB_DOCUMENT_ID_DUPLICATE, nothing written",
            Name(s));

    // Must-accept: case-distinct and NFC/NFD-distinct ids are NOT duplicates
    // (sec 4.3: byte identity only, no normalization, no case folding).
    docs = {docs_arena.Add("A", "one"), docs_arena.Add("a", "two")};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.ok,
            "step10b must-accept: ids differing only in ASCII case are DISTINCT (no case folding, sec 4.3)",
            Name(s));

    // NFC "e with acute" (U+00E9, 2 bytes) vs NFD "e" + combining acute
    // (U+0065 U+0301, 3 bytes) -- distinct byte spans, distinct code points.
    const std::string nfc = "caf\xC3\xA9";  // "café" (NFC)
    std::string nfd = "cafe";
    nfd += static_cast<char>(0xCC);
    nfd += static_cast<char>(0x81);  // combining acute accent, U+0301 -- "cafe" + U+0301 (NFD)
    docs = {docs_arena.Add(nfc, "one"), docs_arena.Add(nfd, "two")};
    req = 0xBAD5EED;
    s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.ok,
            "step10c must-accept: NFC and NFD forms of one visual string are DISTINCT byte spans "
            "(no Unicode normalization, sec 4.3)",
            Name(s));
  }

  // ---- Step 11: tokenize EVERY document before any forward -----------------
  if (a.context_cap > 0) {
    std::string over_cap;
    for (size_t i = 0; i < a.context_cap; ++i) over_cap += (i % 2 == 0 ? 'a' : 'b');  // context_cap positions of content -> content+1 > cap
    std::vector<semb_document> docs = {docs_arena.Add("ok", "fine"), docs_arena.Add("bad", over_cap)};
    RowBuffer buf(2 * required1);
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    Verdict(s == st.context_cap_exceeded && buf.Untouched(),
            "step11 a later document over context_cap -> SEMB_CONTEXT_CAP_EXCEEDED, NO row written for the "
            "earlier good document either (all rows tokenized before any forward -- TE-96 sec 4.2's own "
            "'a late bad row never exposes a partial matrix')",
            Name(s));
  } else {
    Missing("step11 context_cap refusal", "no --context-cap given");
  }

  // ---- Step 13/14: successful bake, batch 1 and batch N --------------------
  {
    std::vector<std::string> texts = {"one small step", "two if by sea", "three blind mice"};
    std::vector<semb_document> docs;
    for (size_t i = 0; i < texts.size(); ++i) docs.push_back(docs_arena.Add("doc" + std::to_string(i), texts[i]));
    RowBuffer buf(texts.size() * required1);
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    const bool basic_ok = s == st.ok && req == texts.size() * required1 &&
                           buf.GuardedTo(texts.size() * required1);
    Verdict(basic_ok, "step14 batch N succeeds, SEMB_OK, required stated, tail/lead poison intact (stride check)",
            Name(s));

    // Row/raw bit identity, PS-N direct oracle (TE-96 sec 4.7 must-accept):
    // row i equals semb_encode() of docs[i].utf8, through a FRESH handle.
    if (basic_ok) {
      bool all_match = true;
      std::string mismatches;
      for (size_t i = 0; i < texts.size(); ++i) {
        semb_status rs = -1;
        const std::vector<uint8_t> raw = RawEncode(a, texts[i], &rs);
        const std::vector<uint8_t> row = buf.Bytes((i + 1) * required1);
        const std::vector<uint8_t> row_i(row.end() - required1, row.end());
        if (rs != SEMB_OK || row_i != raw) { all_match = false; mismatches += " " + std::to_string(i); }
      }
      Verdict(all_match, "step14-parity row i == semb_encode(docs[i].utf8) bit for bit, for every row (PS-N, no framing)",
              all_match ? std::to_string(texts.size()) + " of " + std::to_string(texts.size()) + " rows matched"
                        : "mismatched rows:" + mismatches);
    }

    // Row order: rows are in INPUT document order, not any other order
    // (already implied by the equality check above being indexed by i, but
    // stated as its own cell so a builder who silently sorted or reversed
    // rows is caught by a differently-worded failure).
    if (basic_ok) {
      const std::vector<uint8_t> row0 = buf.Bytes(required1);
      semb_status rs0 = -1;
      const std::vector<uint8_t> raw0 = RawEncode(a, texts[0], &rs0);
      Verdict(rs0 == SEMB_OK && row0 == raw0, "step14-order row 0 equals docs[0]'s own text, not a permuted row",
              rs0 == SEMB_OK ? "match=" + std::to_string(row0 == raw0) : Name(rs0));
    }

    // Batch of exactly 1.
    std::vector<semb_document> one = {docs_arena.Add("solo", "a single document")};
    RowBuffer buf1(required1);
    req = 0xBAD5EED;
    const semb_status s1 = semb_encode_batch(enc, one.data(), one.size(), buf1.data(), buf1.capacity_bytes(), &req);
    Verdict(s1 == st.ok && req == required1, "step14-batch1 n==1 succeeds, SEMB_OK, required == dims*4", Name(s1));
  }

  // ---- Runtime failure (step 13): allocation failure on a later row -------
  // Armed at the exact byte width of ONE row's own staged output
  // (dims * sizeof(float)) so the failure targets the staging allocation
  // rather than an earlier, small bookkeeping allocation.
  {
    std::vector<std::string> texts = {"first document", "second document survives to be re-baked"};
    std::vector<semb_document> docs;
    for (size_t i = 0; i < texts.size(); ++i) docs.push_back(docs_arena.Add("r" + std::to_string(i), texts[i]));
    RowBuffer buf(texts.size() * required1);
    alloc_hook::ArmFail(required1);
    size_t req = 0xBAD5EED;
    const semb_status s = semb_encode_batch(enc, docs.data(), docs.size(), buf.data(), buf.capacity_bytes(), &req);
    alloc_hook::DisarmFail();
    const bool fired = alloc_hook::g_fail_fired.load() > 0;
    Verdict(fired && (s == st.allocation_failed || s == st.engine_refused) && buf.Untouched(),
            "runtime an injected allocation failure during staging -> a named runtime status "
            "(SEMB_ALLOCATION_FAILED or SEMB_ENGINE_REFUSED), out_rows fully untouched, no partial matrix",
            "fired=" + std::to_string(fired) + " status=" + Name(s));

    // Retry with the SAME handle succeeds, serial-identical to the earlier
    // successful bake -- the failed call released whatever it held.
    RowBuffer retry(texts.size() * required1);
    req = 0xBAD5EED;
    const semb_status s2 = semb_encode_batch(enc, docs.data(), docs.size(), retry.data(), retry.capacity_bytes(), &req);
    Verdict(s2 == st.ok, "runtime-retry the same handle bakes successfully afterward (nothing left held)", Name(s2));
  }

  // ---- C27's corpus form: long-then-short vs short-then-long ---------------
  // (`Claude/Plans/SuperEmbedder_Plan.md` sec 8 C27; TE-96 sec 4.5's own
  // ruling -- "rows are matched BY ID across the two bakes, since row order
  // differs by construction".)
  {
    // Text length is kept modest (well under any host's context_cap, the
    // mechanism pair's own 64-token cap included) so this cell exercises
    // ORDER, not a second, unrelated context-cap refusal.
    std::vector<std::pair<std::string, std::string>> named = {
        {"short-a", "hi"},
        {"long-b", "a somewhat longer line"},
        {"short-c", "yo"},
        {"long-d", "another longer line here"},
    };
    std::vector<semb_document> long_then_short, short_then_long;
    // long_then_short: sorted by text length, DESCENDING.
    std::vector<size_t> order_desc = {1, 3, 0, 2};
    std::vector<size_t> order_asc = {0, 2, 1, 3};
    for (size_t i : order_desc) long_then_short.push_back(docs_arena.Add(named[i].first, named[i].second));
    for (size_t i : order_asc) short_then_long.push_back(docs_arena.Add(named[i].first, named[i].second));

    RowBuffer buf_a(named.size() * required1), buf_b(named.size() * required1);
    size_t req_a = 0xBAD5EED, req_b = 0xBAD5EED;
    const semb_status sa = semb_encode_batch(enc, long_then_short.data(), long_then_short.size(), buf_a.data(),
                                              buf_a.capacity_bytes(), &req_a);
    const semb_status sb = semb_encode_batch(enc, short_then_long.data(), short_then_long.size(), buf_b.data(),
                                              buf_b.capacity_bytes(), &req_b);
    bool ok = sa == st.ok && sb == st.ok;
    if (ok) {
      // Match rows BY ID, not by position (positions differ by construction).
      for (size_t pos_a = 0; pos_a < order_desc.size() && ok; ++pos_a) {
        const std::string& id = named[order_desc[pos_a]].first;
        size_t pos_b = 0;
        for (; pos_b < order_asc.size(); ++pos_b) if (named[order_asc[pos_b]].first == id) break;
        const std::vector<uint8_t> row_a = buf_a.Bytes((pos_a + 1) * required1);
        const std::vector<uint8_t> ra(row_a.end() - required1, row_a.end());
        const std::vector<uint8_t> row_b = buf_b.Bytes((pos_b + 1) * required1);
        const std::vector<uint8_t> rb(row_b.end() - required1, row_b.end());
        if (ra != rb) ok = false;
      }
    }
    Verdict(ok, "C27-corpus-form long-then-short vs short-then-long: row digests equal when matched BY ID "
                "(TE-96 sec 4.5's own ruling, since row order differs by construction)",
            "sa=" + std::string(Name(sa)) + " sb=" + std::string(Name(sb)) + " all_ids_matched=" + std::to_string(ok));
  }

  semb_encoder_close(enc);
  std::printf("\nu1_batch_contract_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}
