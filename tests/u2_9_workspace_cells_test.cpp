// tests/u2_9_workspace_cells_test.cpp -- U2 cloud build, the U2-9/U2-10 red
// suite's seam-observable cells (te267 sec 5 U2-9 "Cells", U2-10 C66 (a)):
//
//   C60 (c)      output bytes unchanged by the workspace rule, every edge, both
//                legs, on the minimal-geometry cap-5,000 pair: documents of
//                n = 1, 63, 64, 65, 512, 4,096, 4,097, 5,000 positions encoded
//                in that order on ONE handle with the new-buffer fill armed at
//                0xA5 equal the same documents under the forced-reference arm.
//   C60 must-reject / must-accept (synthetic, and real with --real-model): a
//                200-position document in two chunk-batched calls equals the
//                one-call seam; the poison arm at position 0 between the two
//                calls makes the seam (and its SHA-256) differ; poisoning rows
//                at positions >= n leaves it equal. Per-token leg likewise,
//                poisoned between two positions.
//   C61 (a)-(f)  slot mechanics (nothing reserved at open; lifetime and reuse;
//                release; the long-document gate; failure; the bound).
//   C66 (a)      the worker-thread start: the spawn fail arm.
//
// Links `superembedder_testseam` (tests/support/semb_u2_memory_seam.h), never
// the shipped library. P is read from the handle's own geometry
// (layers x KV heads x head dim x 2), never from a constant.
//
// RED ON TODAY'S POOL, each for the plan's stated reason (te267 U2-9 "Red
// first", U2-10 "Red first"): C61 (a) reads max_concurrency records at full
// capacity and a model buffer holding the artifact; C61 (b)/(c) read
// full-cap capacities; C61 (d)'s bounded wait for the gate's park point times
// out; C61 (e)'s encodes return SEMB_OK because nothing grows and the growth
// fail arm never fires; C66 (a)'s armed legs return SEMB_ENGINE_REFUSED.
// GREEN BY CONSTRUCTION TODAY (pins, the plan says so): C60 (c) (both arms
// compare today's rule with itself), C60's must-reject/must-accept, C61 (f).
// NOT RUN RED: C61 (a)'s (uint32_t)-1 open, which runs only once the bounded
// leg of C61 (a) passes (its red state is read at source, te267 U2-9).
//
// USAGE: --model <pair model> --tokenizer <pair tokenizer> --scratch <dir>
//        [--real-model <.sslm>] [--cells c60,c61a,...]
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "superembedder/semb.h"
#include "superembedder/bake_abi.h"
#include "superembedder/encoder_interim_abi.h"
#include "superembedder/seam_abi.h"
#include "support/semb_u2_memory_seam.h"
#include "support/semb_workspace_seam.h"
#include "superslm/sha256.h"

namespace fs = std::filesystem;

namespace {

int g_fail = 0, g_pass = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  (ok ? g_pass : g_fail)++;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
void Note(const char* tag, const std::string& cell, const std::string& observed) {
  std::printf("[%s] %s: %s\n", tag, cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
std::string S(uint64_t v) { return std::to_string(v); }
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "?"; }

struct Args {
  std::string model, tokenizer, scratch, real_model;
  std::set<std::string> cells;
  bool Want(const std::string& c) const { return cells.empty() || cells.count(c) != 0; }
};

constexpr int32_t kPairAppended = 262;  // <|endoftext|> in the synthetic checkpoint
constexpr int32_t kRealAppended = 151643;

std::vector<uint8_t> ReadAll(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}

// Content ids for an n-position document (n - 1 content ids; the seam appends
// the end token). Byte ids 3..252 only, never a special.
std::vector<int32_t> Ids(size_t n_positions, uint32_t salt) {
  std::vector<int32_t> ids(n_positions - 1);
  for (size_t i = 0; i < ids.size(); ++i) ids[i] = 3 + static_cast<int32_t>((i * 7 + salt) % 250);
  return ids;
}
std::vector<int32_t> RealIds(size_t n_positions) {
  std::vector<int32_t> ids(n_positions - 1);
  for (size_t i = 0; i < ids.size(); ++i) ids[i] = 1000 + static_cast<int32_t>((i * 37) % 90000);
  return ids;
}

uint64_t PBytes(const SembInterimEncoder* enc) {
  SembInterimGeometry g{};
  g.struct_size = sizeof(g);
  if (semb_interim_encoder_geometry(enc, &g) != kSembInterimOk) return 0;
  return uint64_t{g.num_hidden_layers} * g.num_key_value_heads * g.head_dim * 2;
}
uint32_t Cap(const SembInterimEncoder* enc) {
  SembInterimGeometry g{};
  g.struct_size = sizeof(g);
  semb_interim_encoder_geometry(enc, &g);
  return g.context_cap;
}
size_t Hidden(const SembInterimEncoder* enc) {
  SembInterimGeometry g{};
  g.struct_size = sizeof(g);
  semb_interim_encoder_geometry(enc, &g);
  return g.hidden_size;
}

SembInterimEncoder* OpenInterimPath(const std::string& model, int32_t appended) {
  SembInterimEncoder* enc = nullptr;
  const char* name = nullptr;
  if (semb_interim_encoder_open(model.c_str(), appended, &enc, &name) != kSembInterimOk) return nullptr;
  return enc;
}
SembInterimEncoder* OpenInterimMemory(const std::vector<uint8_t>& bytes, uint32_t mc) {
  SembInterimEncoder* enc = nullptr;
  const char* name = nullptr;
  if (semb_interim_encoder_open_from_memory(bytes.data(), bytes.size(), kPairAppended, mc, &enc, &name) !=
      kSembInterimOk) {
    return nullptr;
  }
  return enc;
}
semb_encoder OpenPublic(const Args& a, uint32_t mc, semb_status* out_status = nullptr) {
  semb_config cfg{};
  cfg.struct_size = sizeof(cfg);
  cfg.model_path = a.model.data();
  cfg.model_path_len = a.model.size();
  cfg.tokenizer_path = a.tokenizer.data();
  cfg.tokenizer_path_len = a.tokenizer.size();
  cfg.max_concurrency = mc;
  semb_encoder enc = nullptr;
  const semb_status s = semb_encoder_open(&cfg, &enc);
  if (out_status) *out_status = s;
  return s == SEMB_OK ? enc : nullptr;
}

struct SeamOut {
  SembInterimStatus status = kSembInterimOk;
  std::vector<int8_t> codes;
  std::vector<int64_t> m, e;
  bool operator==(const SeamOut& o) const {
    return status == o.status && codes == o.codes && m == o.m && e == o.e;
  }
};

SeamOut RunSeam(SembInterimEncoder* enc, const std::vector<int32_t>& ids, size_t chunk_budget,
                SembForwardLeg leg) {
  SeamOut out;
  const size_t n = ids.size() + 1;
  const size_t hidden = Hidden(enc);
  out.codes.assign(n * hidden, 0);
  out.m.assign(n, 0);
  out.e.assign(n, 0);
  size_t positions = 0;
  const char* name = nullptr;
  out.status = semb_interim_encode_seam(enc, ids.data(), ids.size(), chunk_budget, leg, out.codes.data(),
                                        out.codes.size(), out.m.data(), out.e.data(), n, &positions, &name);
  return out;
}

std::string SeamSha(const SeamOut& s, size_t hidden) {
  const size_t n = s.m.size();
  std::vector<uint8_t> buf(16 + n * (hidden + 16));
  size_t len = 0;
  if (semb_seam_serialize_document(s.codes.data(), s.m.data(), s.e.data(), n, hidden, buf.data(), buf.size(),
                                   &len) != kSembSerializeOk) {
    return "serialize-failed";
  }
  uint8_t d[32];
  superslm::Sha256Hash(buf.data(), len, d);
  return superslm::ToHex(d);
}

uint64_t SlotCap(const SembInterimEncoder* enc, uint64_t i) {
  uint64_t c = UINT64_MAX;
  if (!semb_test_seam_slot_capacity(enc, i, &c)) return UINT64_MAX;
  return c;
}
std::string CapList(const SembInterimEncoder* enc) {
  std::string s;
  const uint64_t n = semb_test_seam_slot_record_count(enc);
  for (uint64_t i = 0; i < n && i < 8; ++i) s += (i ? "," : "") + S(SlotCap(enc, i));
  if (n > 8) s += ",...";
  return "[" + s + "]";
}

void DisarmAll() {
  semb_test_seam_arm_fill(-1);
  semb_test_seam_arm_forced_reference(0);
  semb_test_seam_arm_growth_fail(0);
  semb_test_seam_poison_disarm();
  semb_test_seam_arm_spawn_fail(0);
  semb_test_seam_gate_release();
  semb_test_seam_gate_reset();
}

// ---------------------------------------------------------------------------
// C60 (c): every edge, both legs, fill-armed vs forced-reference.
// ---------------------------------------------------------------------------
void CellC60c(const Args& a) {
  const size_t kN[] = {63, 64, 65, 512, 4096, 4097, 5000};  // n = 1 runs through the witness verb below
  for (const SembForwardLeg leg : {kSembForwardLegChunkBatched, kSembForwardLegPerToken}) {
    const char* leg_name = leg == kSembForwardLegChunkBatched ? "chunk-batched" : "per-token";
    std::vector<SeamOut> ref;
    DisarmAll();
    semb_test_seam_arm_forced_reference(1);
    SembInterimEncoder* r = OpenInterimPath(a.model, kPairAppended);
    if (!r) { Verdict(false, "C60 (c) setup", "reference open failed"); return; }
    for (size_t n : kN) ref.push_back(RunSeam(r, Ids(n, 11), 0, leg));
    semb_interim_encoder_close(r);
    semb_test_seam_arm_forced_reference(0);
    semb_test_seam_arm_fill(0xA5);
    SembInterimEncoder* enc = OpenInterimPath(a.model, kPairAppended);
    if (!enc) { Verdict(false, "C60 (c) setup", "open failed"); DisarmAll(); return; }
    std::string detail;
    bool all = true;
    for (size_t i = 0; i < sizeof(kN) / sizeof(kN[0]); ++i) {
      const SeamOut got = RunSeam(enc, Ids(kN[i], 11), 0, leg);
      const bool eq = got.status == kSembInterimOk && got == ref[i];
      all = all && eq;
      detail += "n=" + S(kN[i]) + (eq ? ":eq " : ":DIFF ");
    }
    semb_interim_encoder_close(enc);
    semb_test_seam_arm_fill(-1);
    Verdict(all, std::string("C60 (c) ") + leg_name + " fill-0xA5 one handle == forced-reference", detail);
  }
  // n = 1: the interim seam refuses zero content ids (kSembInterimInputEmpty), so
  // the one-position document runs through the witness verb (chunk-batched only).
  std::vector<int8_t> c_ref(1024), c_got(1024);
  int64_t m_ref = 0, e_ref = 0, m_got = 0, e_got = 0;
  size_t hidden = 0;
  const int32_t one[1] = {kPairAppended};
  semb_test_seam_arm_forced_reference(1);
  const SembEncodeStatus s1 = semb_encode_document_for_witness(a.model.c_str(), one, 1, 0, c_ref.data(), &m_ref,
                                                               &e_ref, &hidden);
  semb_test_seam_arm_forced_reference(0);
  semb_test_seam_arm_fill(0xA5);
  const SembEncodeStatus s2 = semb_encode_document_for_witness(a.model.c_str(), one, 1, 0, c_got.data(), &m_got,
                                                               &e_got, &hidden);
  semb_test_seam_arm_fill(-1);
  Verdict(s1 == kSembEncodeOk && s2 == kSembEncodeOk && m_ref == m_got && e_ref == e_got &&
              std::memcmp(c_ref.data(), c_got.data(), hidden) == 0,
          "C60 (c) n=1 (witness verb, chunk-batched) fill-0xA5 == forced-reference",
          "status " + S(s1) + "/" + S(s2));
}

// ---------------------------------------------------------------------------
// C60's must-reject / must-accept: the comparison can differ.
// ---------------------------------------------------------------------------
void PoisonLeg(SembInterimEncoder* enc, const std::vector<int32_t>& ids, SembForwardLeg leg, const char* tag) {
  const size_t n = ids.size() + 1;
  const size_t hidden = Hidden(enc);
  const size_t split = 100;
  const size_t budget = (leg == kSembForwardLegChunkBatched) ? split : 0;
  const SeamOut one = RunSeam(enc, ids, 0, leg);
  const SeamOut two = RunSeam(enc, ids, budget, leg);
  if (leg == kSembForwardLegChunkBatched) {
    Verdict(one.status == kSembInterimOk && one == two, std::string(tag) + " two chunk-batched calls == one call",
            "positions " + S(n));
  }
  semb_test_seam_arm_poison(split, 0, 1, 0x7F);
  const SeamOut poisoned = RunSeam(enc, ids, budget, leg);
  const int32_t fired = semb_test_seam_poison_disarm();
  Verdict(fired == 1 && poisoned.status == kSembInterimOk && !(poisoned == two) &&
              SeamSha(poisoned, hidden) != SeamSha(two, hidden),
          std::string(tag) + " must-reject: position 0's K rows poisoned at split 100 -> seam and its SHA-256 differ",
          "fired=" + S(fired) + " sha " + SeamSha(poisoned, hidden).substr(0, 16) + " vs " +
              SeamSha(two, hidden).substr(0, 16));
  semb_test_seam_arm_poison(split, n, UINT64_MAX, 0x7F);
  const SeamOut beyond = RunSeam(enc, ids, budget, leg);
  const int32_t fired2 = semb_test_seam_poison_disarm();
  Verdict(fired2 == 1 && beyond == two,
          std::string(tag) + " must-accept: rows at positions >= n poisoned -> seam equal", "fired=" + S(fired2));
}

void CellC60Poison(const Args& a) {
  DisarmAll();
  SembInterimEncoder* enc = OpenInterimPath(a.model, kPairAppended);
  if (!enc) { Verdict(false, "C60 poison setup", "open failed"); return; }
  PoisonLeg(enc, Ids(200, 5), kSembForwardLegChunkBatched, "C60 synthetic chunk-batched");
  PoisonLeg(enc, Ids(200, 5), kSembForwardLegPerToken, "C60 synthetic per-token");
  semb_interim_encoder_close(enc);
  if (a.real_model.empty()) {
    Note("MISSING PREREQUISITE", "C60 real-artifact chunk-batched poison leg",
         "no --real-model (the converted Qwen3-Embedding-0.6B artifact); owed to the dev box");
    return;
  }
  SembInterimEncoder* real = OpenInterimPath(a.real_model, kRealAppended);
  if (!real) { Verdict(false, "C60 real setup", "open failed"); return; }
  PoisonLeg(real, RealIds(200), kSembForwardLegChunkBatched, "C60 real chunk-batched");
  semb_interim_encoder_close(real);
}

// ---------------------------------------------------------------------------
// C61 (a): nothing reserved at open.
// ---------------------------------------------------------------------------
void CellC61a(const Args& a) {
  DisarmAll();
  const uint64_t hw = std::max(1u, std::thread::hardware_concurrency());
  const uint64_t witness_workers = std::min<uint64_t>(16, hw);
  semb_encoder pub = OpenPublic(a, 64);
  bool bounded_ok = false;
  if (!pub) {
    Verdict(false, "C61 (a) public open at max_concurrency 64", "open failed");
  } else {
    const SembInterimEncoder* ie = semb_test_seam_interim_of(pub);
    const uint64_t records = semb_test_seam_slot_record_count(ie);
    bool all_zero = true;
    for (uint64_t i = 0; i < records; ++i) all_zero = all_zero && SlotCap(ie, i) == 0;
    const uint64_t model_cap = semb_test_seam_model_buffer_capacity(ie);
    const bool rec_ok = records <= witness_workers;
    Verdict(rec_ok, "C61 (a) records after open at mc 64 <= min(16, hardware threads) = " + S(witness_workers),
            "records=" + S(records));
    Verdict(all_zero, "C61 (a) every record's capacity reads 0 after open (end-of-open release)",
            "capacities=" + CapList(ie) + " P=" + S(PBytes(ie)));
    Verdict(model_cap == 0, "C61 (a) product model-buffer capacity 0 after the public open", "capacity=" + S(model_cap));
    bounded_ok = rec_ok && all_zero;
    semb_encoder_close(pub);
  }
  SembInterimEncoder* ip = OpenInterimPath(a.model, kPairAppended);
  Verdict(ip && semb_test_seam_model_buffer_capacity(ip) == 0,
          "C61 (a) product model-buffer capacity 0 after the interim path open",
          "capacity=" + S(ip ? semb_test_seam_model_buffer_capacity(ip) : UINT64_MAX));
  if (ip) semb_interim_encoder_close(ip);
  const std::vector<uint8_t> bytes = ReadAll(a.model);
  SembInterimEncoder* im = OpenInterimMemory(bytes, 1);
  Verdict(im && semb_test_seam_model_buffer_capacity(im) == 0,
          "C61 (a) product model-buffer capacity 0 after the interim memory open",
          "capacity=" + S(im ? semb_test_seam_model_buffer_capacity(im) : UINT64_MAX));
  if (im) semb_interim_encoder_close(im);
  Note("NOTE", "C61 (a) memory open (U2-7 item 1)",
       "semb_encoder_open_memory does not exist yet; its model-buffer leg is graded by the U2-7 driver's C52 (d)");
  if (!bounded_ok) {
    Note("NOT RUN", "C61 (a) open at (uint32_t)-1",
         "runs only once the bounded leg passes: on today's pool it would open as many full-cap slots as free "
         "memory affords (its red state is read at source, te267 U2-9 red-first)");
    return;
  }
  semb_status st = SEMB_OK;
  semb_encoder unbounded = OpenPublic(a, UINT32_MAX, &st);
  bool enc_ok = false;
  if (unbounded) {
    std::vector<float> v(64);
    size_t req = 0;
    uint32_t dims = 0;
    semb_encoder_dims(unbounded, &dims);
    v.resize(dims);
    semb_fingerprint fp{};
    fp.struct_size = sizeof(fp);
    enc_ok = semb_encode(unbounded, "aaaa", 4, v.data(), v.size() * 4, &req, &fp) == SEMB_OK;
    semb_encoder_close(unbounded);
  }
  Verdict(st == SEMB_OK && enc_ok, "C61 (a) open at (uint32_t)-1 returns SEMB_OK and a document encodes",
          std::string("open=") + Name(st));
}

// ---------------------------------------------------------------------------
// C61 (b) lifetime and reuse; (c) release.
// ---------------------------------------------------------------------------
void CellC61bc(const Args& a) {
  DisarmAll();
  SembInterimEncoder* enc = OpenInterimPath(a.model, kPairAppended);
  if (!enc) { Verdict(false, "C61 (b) setup", "open failed"); return; }
  const uint64_t P = PBytes(enc);
  Verdict(SlotCap(enc, 0) == 0, "C61 (b) the one slot starts empty after open", "capacity=" + S(SlotCap(enc, 0)));
  const size_t ns[] = {6, 512, 6};
  const uint64_t want[] = {P * 64, P * 512, P * 512};
  for (int i = 0; i < 3; ++i) {
    const SeamOut got = RunSeam(enc, Ids(ns[i], 3), 0, kSembForwardLegChunkBatched);
    const uint64_t cap = SlotCap(enc, 0);
    SembInterimEncoder* fresh = OpenInterimPath(a.model, kPairAppended);
    const SeamOut ref = RunSeam(fresh, Ids(ns[i], 3), 0, kSembForwardLegChunkBatched);
    semb_interim_encoder_close(fresh);
    Verdict(got.status == kSembInterimOk && got == ref, "C61 (b) n=" + S(ns[i]) + " seam equals a fresh handle's", "");
    Verdict(cap == want[i], "C61 (b) after n=" + S(ns[i]) + " capacity reads " + S(want[i]),
            "capacity=" + S(cap) + " (P=" + S(P) + ")");
  }
  semb_interim_encoder_close(enc);

  SembInterimEncoder* rel = OpenInterimPath(a.model, kPairAppended);
  if (!rel) { Verdict(false, "C61 (c) setup", "open failed"); return; }
  const SeamOut s4096 = RunSeam(rel, Ids(4096, 9), 0, kSembForwardLegChunkBatched);
  const uint64_t c4096 = SlotCap(rel, 0);
  const SeamOut s4097 = RunSeam(rel, Ids(4097, 9), 0, kSembForwardLegChunkBatched);
  const uint64_t c4097 = SlotCap(rel, 0);
  Verdict(s4096.status == kSembInterimOk && c4096 == P * 4096, "C61 (c) capacity P*4096 after n=4,096",
          "capacity=" + S(c4096) + " want " + S(P * 4096));
  Verdict(s4097.status == kSembInterimOk && c4097 == 0, "C61 (c) capacity 0 after n=4,097 (released)",
          "capacity=" + S(c4097));
  semb_interim_encoder_close(rel);
}

// ---------------------------------------------------------------------------
// C61 (d): the gate.
// ---------------------------------------------------------------------------
struct BatchResult {
  SembInterimStatus status = kSembInterimOk;
  std::vector<float> rows;
};
BatchResult RunInterimBatch(SembInterimEncoder* enc, const std::vector<std::vector<int32_t>>& docs) {
  BatchResult r;
  const size_t hidden = Hidden(enc);
  std::vector<const int32_t*> ptrs;
  std::vector<size_t> lens;
  for (const auto& d : docs) { ptrs.push_back(d.data()); lens.push_back(d.size()); }
  r.rows.assign(docs.size() * hidden, 0.0f);
  size_t required = 0, failed = 0;
  SembWaPoolStatus dq = kSembOk;
  const char* name = nullptr;
  r.status = semb_interim_encode_batch_ps_n(enc, ptrs.data(), lens.data(), docs.size(), 0, r.rows.data(),
                                            r.rows.size() * sizeof(float), &required, &failed, &dq, &name,
                                            nullptr, 0, nullptr);
  return r;
}

void CellC61d(const Args& a) {
  DisarmAll();
  if (std::thread::hardware_concurrency() < 2) {
    Note("NOT RUN", "C61 (d)", "needs hardware_concurrency() >= 2");
    return;
  }
  const std::vector<uint8_t> bytes = ReadAll(a.model);
  const std::vector<std::vector<int32_t>> docs = {Ids(4097, 21), Ids(4097, 22)};
  // Reference rows: each document alone on a fresh handle.
  BatchResult ref0, ref1;
  {
    SembInterimEncoder* r = OpenInterimMemory(bytes, 1);
    ref0 = RunInterimBatch(r, {docs[0]});
    ref1 = RunInterimBatch(r, {docs[1]});
    semb_interim_encoder_close(r);
  }
  SembInterimEncoder* enc = OpenInterimMemory(bytes, 2);
  if (!enc) { Verdict(false, "C61 (d) setup", "open failed"); return; }
  const uint64_t P = PBytes(enc);
  const uint64_t cap = Cap(enc);
  const uint64_t clamp = P * std::min<uint64_t>(8192, cap);
  semb_test_seam_gate_arm_park(2);
  BatchResult got;
  std::thread batch([&] { got = RunInterimBatch(enc, docs); });
  const bool first = semb_test_seam_gate_wait_parked(1, 20000) == 1;
  if (!first) {
    batch.join();
    uint64_t rec[4];
    Verdict(false, "C61 (d) the gate's park point reached by the first holder",
            "bounded wait (20 s) timed out: the park point was never reached; take records=" +
                S(semb_test_seam_gate_take_records(rec, 4)) + " give records=" + S(semb_test_seam_gate_give_records(rec, 4)));
    DisarmAll();
    semb_interim_encoder_close(enc);
    return;
  }
  // Let the other worker reach the gate's wait.
  for (int i = 0; i < 200 && semb_test_seam_gate_waiters() < 1; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(50));
  {
    const uint64_t c0 = SlotCap(enc, 0), c1 = SlotCap(enc, 1);
    const uint64_t holder = std::max(c0, c1), waiter = std::min(c0, c1);
    const int over = (c0 > P * 4096) + (c1 > P * 4096);
    Verdict(semb_test_seam_gate_waiters() == 1 && semb_test_seam_gate_high_water() == 1,
            "C61 (d) first holder parked: waiter count 1, high-water 1",
            "waiters=" + S(semb_test_seam_gate_waiters()) + " hwm=" + S(semb_test_seam_gate_high_water()));
    Verdict(holder == clamp && waiter == 0 && over == 1,
            "C61 (d) first holder parked: holder capacity P*min(8192,cap), waiter capacity 0, exactly one > P*4096",
            "capacities=" + S(c0) + "," + S(c1) + " want holder " + S(clamp));
  }
  semb_test_seam_gate_release();
  const bool second = semb_test_seam_gate_wait_parked(1, 20000) == 1;
  if (second) {
    const uint64_t c0 = SlotCap(enc, 0), c1 = SlotCap(enc, 1);
    const int over = (c0 > P * 4096) + (c1 > P * 4096);
    Verdict(std::min(c0, c1) == 0 && over == 1,
            "C61 (d) second holder parked: the first slot reads 0, exactly one > P*4096",
            "capacities=" + S(c0) + "," + S(c1));
  } else {
    Verdict(false, "C61 (d) second holder parked", "timed out");
  }
  semb_test_seam_gate_release();
  batch.join();
  const size_t hidden = Hidden(enc);
  const bool rows_ok = got.status == kSembInterimOk &&
                       std::memcmp(got.rows.data(), ref0.rows.data(), hidden * 4) == 0 &&
                       std::memcmp(got.rows.data() + hidden, ref1.rows.data(), hidden * 4) == 0;
  Verdict(rows_ok && semb_test_seam_gate_high_water() == 1,
          "C61 (d) after release: both documents succeed, equal to the reference, high-water stays 1",
          "status=" + S(got.status) + " hwm=" + S(semb_test_seam_gate_high_water()));
  uint64_t take[8] = {}, give[8] = {};
  const uint64_t nt = semb_test_seam_gate_take_records(take, 8), ng = semb_test_seam_gate_give_records(give, 8);
  bool zeros = nt == 2 && ng == 2;
  for (uint64_t i = 0; i < std::min<uint64_t>(nt, 8); ++i) zeros = zeros && take[i] == 0;
  for (uint64_t i = 0; i < std::min<uint64_t>(ng, 8); ++i) zeros = zeros && give[i] == 0;
  Verdict(zeros, "C61 (d) every take-time and give-back capacity record reads 0",
          "take=" + S(nt) + " give=" + S(ng) + " first take=" + S(take[0]) + " first give=" + S(give[0]));
  semb_interim_encoder_close(enc);
  DisarmAll();
  SembInterimEncoder* one = OpenInterimMemory(bytes, 1);
  const BatchResult solo = one ? RunInterimBatch(one, docs) : BatchResult{kSembInterimNullArgument, {}};
  Verdict(solo.status == kSembInterimOk, "C61 (d) at max_concurrency 1 the same batch completes (no self-wait)",
          "status=" + S(solo.status));
  if (one) semb_interim_encoder_close(one);
  DisarmAll();
}

// ---------------------------------------------------------------------------
// C61 (e): failure at the growth site.
// ---------------------------------------------------------------------------
std::string Text(size_t positions) { return std::string(positions - 1, 'a'); }  // byte-level: one id per 'a'

struct Vec {
  semb_status status = SEMB_OK;
  std::vector<float> v;
};
Vec Encode(semb_encoder enc, const std::string& text) {
  Vec r;
  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  r.v.assign(dims ? dims : 1, 0.0f);
  size_t req = 0;
  semb_fingerprint fp{};
  fp.struct_size = sizeof(fp);
  r.status = semb_encode(enc, text.data(), text.size(), r.v.data(), r.v.size() * 4, &req, &fp);
  return r;
}
Vec Reference(const Args& a, const std::string& text) {
  semb_encoder f = OpenPublic(a, 1);
  if (!f) return Vec{SEMB_ENGINE_REFUSED, {}};
  Vec r = Encode(f, text);
  semb_encoder_close(f);
  return r;
}
semb_status Batch(semb_encoder enc, const std::vector<std::string>& texts, std::vector<float>* rows) {
  std::vector<semb_document> docs(texts.size());
  std::vector<std::string> ids(texts.size());
  for (size_t i = 0; i < texts.size(); ++i) {
    ids[i] = "d" + S(i);
    docs[i].struct_size = sizeof(semb_document);
    docs[i].id = ids[i].data();
    docs[i].id_len = ids[i].size();
    docs[i].utf8 = texts[i].data();
    docs[i].utf8_len = texts[i].size();
  }
  uint32_t dims = 0;
  semb_encoder_dims(enc, &dims);
  rows->assign(texts.size() * dims, 0.0f);
  size_t req = 0;
  return semb_encode_batch(enc, docs.data(), docs.size(), rows->data(), rows->size() * 4, &req);
}

void CellC61e(const Args& a) {
  DisarmAll();
  const std::string t512 = Text(512);
  const Vec ref512 = Reference(a, t512);
  const Vec ref6 = Reference(a, Text(6));
  {
    semb_encoder enc = OpenPublic(a, 1);
    const SembInterimEncoder* ie = semb_test_seam_interim_of(enc);
    semb_test_seam_arm_growth_fail(512);
    const Vec failed = Encode(enc, t512);
    const uint64_t cap_after = SlotCap(ie, 0);
    semb_test_seam_arm_growth_fail(0);
    const Vec next = Encode(enc, t512);
    Verdict(failed.status == SEMB_ALLOCATION_FAILED && cap_after == 0 && next.status == SEMB_OK && next.v == ref512.v,
            "C61 (e) semb_encode, growth to C>=512 failed: SEMB_ALLOCATION_FAILED, slot 0, next encode = reference",
            std::string("status=") + Name(failed.status) + " capacity=" + S(cap_after) + " next=" + Name(next.status));
    semb_encoder_close(enc);
  }
  {
    semb_encoder enc = OpenPublic(a, 1);
    const SembInterimEncoder* ie = semb_test_seam_interim_of(enc);
    semb_document d{};
    d.struct_size = sizeof(d);
    d.id = "d0"; d.id_len = 2;
    d.utf8 = t512.data(); d.utf8_len = t512.size();
    const std::string stem = (fs::path(a.scratch) / "c61e_bake").string();
    semb_test_seam_arm_growth_fail(512);
    const semb_status bs = semb_bake_to_path(enc, &d, 1, stem.data(), stem.size());
    const uint64_t cap_after = SlotCap(ie, 0);
    semb_test_seam_arm_growth_fail(0);
    const Vec next = Encode(enc, t512);
    Verdict(bs == SEMB_ALLOCATION_FAILED && cap_after == 0 && next.status == SEMB_OK && next.v == ref512.v,
            "C61 (e) semb_bake_to_path, growth failed: SEMB_ALLOCATION_FAILED, slot 0, next encode = reference",
            std::string("status=") + Name(bs) + " capacity=" + S(cap_after));
    semb_encoder_close(enc);
  }
  if (std::thread::hardware_concurrency() >= 2) {
    semb_encoder enc = OpenPublic(a, 2);
    std::vector<float> rows;
    semb_test_seam_arm_growth_fail(512);
    const semb_status bs = Batch(enc, {t512, t512}, &rows);
    semb_test_seam_arm_growth_fail(0);
    // Follow-up takes every slot: two encodes held at the acquisition park point.
    semb_test_seam_reset();
    semb_test_seam_arm_park(2);
    Vec v1, v2;
    std::thread th1([&] { v1 = Encode(enc, t512); });
    std::thread th2([&] { v2 = Encode(enc, t512); });
    const bool parked = semb_test_seam_wait_parked(2, 20000) == 1;
    const uint64_t records = semb_test_seam_slot_record_count(semb_test_seam_interim_of(enc));
    semb_test_seam_release();
    th1.join();
    th2.join();
    Verdict(bs == SEMB_ALLOCATION_FAILED && parked && records == 2 && v1.status == SEMB_OK && v2.status == SEMB_OK &&
                v1.v == ref512.v && v2.v == ref512.v,
            "C61 (e) semb_encode_batch T=2, growth failed: SEMB_ALLOCATION_FAILED; follow-up holds both slots, "
            "each = reference",
            std::string("status=") + Name(bs) + " parked=" + S(parked) + " records=" + S(records));
    semb_test_seam_reset();
    semb_encoder_close(enc);
  } else {
    Note("NOT RUN", "C61 (e) batch leg", "needs hardware_concurrency() >= 2");
  }
  {
    semb_encoder enc = OpenPublic(a, 1);
    semb_test_seam_gate_reset();
    semb_test_seam_arm_growth_fail(5000);
    const Vec failed = Encode(enc, Text(4097));
    semb_test_seam_arm_growth_fail(0);
    uint64_t give[8] = {};
    const uint64_t ng = semb_test_seam_gate_give_records(give, 8);
    Verdict(failed.status == SEMB_ALLOCATION_FAILED && semb_test_seam_gate_holders() == 0 && ng >= 1 &&
                give[std::min<uint64_t>(ng, 8) - 1] == 0,
            "C61 (e) long document, growth to C=5,000 failed: SEMB_ALLOCATION_FAILED, gate holders 0, give-back 0",
            std::string("status=") + Name(failed.status) + " holders=" + S(semb_test_seam_gate_holders()) +
                " give records=" + S(ng));
    semb_encoder_close(enc);
  }
  {
    // The warm-slot leg (TE-417): the one cell that fails on "a growth never holds two buffers".
    semb_encoder enc = OpenPublic(a, 1);
    const SembInterimEncoder* ie = semb_test_seam_interim_of(enc);
    const uint64_t P = PBytes(ie);
    const Vec warm = Encode(enc, t512);
    const uint64_t warm_cap = SlotCap(ie, 0);
    semb_test_seam_arm_growth_fail(1024);
    const Vec failed = Encode(enc, Text(1000));
    uint64_t at_fire = UINT64_MAX;
    const int32_t fired = semb_test_seam_growth_fail_fired(&at_fire);
    semb_test_seam_arm_growth_fail(0);
    const uint64_t cap_after = SlotCap(ie, 0);
    const Vec next = Encode(enc, t512);
    Verdict(warm.status == SEMB_OK && warm_cap == P * 512 && failed.status == SEMB_ALLOCATION_FAILED && fired == 1 &&
                at_fire == 0 && cap_after == 0 && next.status == SEMB_OK && next.v == ref512.v,
            "C61 (e) warm slot (P*512 held), growth to C=1,024 failed: capacity-at-fire 0, capacity 0 after, "
            "next = reference",
            "warm_cap=" + S(warm_cap) + " status=" + Name(failed.status) + " fired=" + S(fired) +
                " at_fire=" + S(at_fire) + " after=" + S(cap_after));
    semb_encoder_close(enc);
  }
  (void)ref6;
  DisarmAll();
}

// ---------------------------------------------------------------------------
// C61 (f): max_concurrency is a bound (a pin, green before and after).
// ---------------------------------------------------------------------------
void CellC61f(const Args& a) {
  DisarmAll();
  const std::string t = Text(40);
  const Vec ref = Reference(a, t);
  semb_encoder enc = OpenPublic(a, 2);
  if (!enc) { Verdict(false, "C61 (f) setup", "open failed"); return; }
  semb_test_seam_reset();
  semb_test_seam_arm_park(2);
  Vec v1, v2;
  std::thread th1([&] { v1 = Encode(enc, t); });
  std::thread th2([&] { v2 = Encode(enc, t); });
  const bool parked = semb_test_seam_wait_parked(2, 20000) == 1;
  const uint64_t records = semb_test_seam_slot_record_count(semb_test_seam_interim_of(enc));
  const Vec third = parked ? Encode(enc, t) : Vec{SEMB_OK, {}};
  semb_test_seam_release();
  th1.join();
  th2.join();
  Verdict(parked && records == 2 && third.status == SEMB_CONCURRENCY_EXCEEDED && v1.status == SEMB_OK &&
              v2.status == SEMB_OK && v1.v == ref.v && v2.v == ref.v,
          "C61 (f) two held encodes each hold a record (count 2); a third returns SEMB_CONCURRENCY_EXCEEDED; "
          "both return the reference",
          "parked=" + S(parked) + " records=" + S(records) + " third=" + Name(third.status));
  semb_test_seam_reset();
  semb_encoder_close(enc);
}

// ---------------------------------------------------------------------------
// C66 (a): the spawn fail arm.
// ---------------------------------------------------------------------------
std::string ReadText(const std::string& p) {
  std::ifstream f(p, std::ios::binary);
  std::ostringstream o;
  o << f.rdbuf();
  return o.str();
}
std::string JsonField(const std::string& json, const std::string& key) {
  const auto k = json.find("\"" + key + "\"");
  if (k == std::string::npos) return "";
  const auto q1 = json.find('"', json.find(':', k) + 1);
  const auto q2 = json.find('"', q1 + 1);
  return json.substr(q1 + 1, q2 - q1 - 1);
}

void CellC66a(const Args& a) {
  DisarmAll();
  if (std::thread::hardware_concurrency() < 4) {
    Note("NOT RUN", "C66 (a)", "needs hardware_concurrency() >= 4");
    return;
  }
  std::vector<std::string> texts;
  for (int i = 0; i < 8; ++i) texts.push_back(std::string(20 + i, static_cast<char>('b' + i)));
  std::vector<semb_document> docs(8);
  std::vector<std::string> ids(8);
  for (int i = 0; i < 8; ++i) {
    ids[i] = "d" + S(i);
    docs[i] = semb_document{sizeof(semb_document), ids[i].data(), ids[i].size(), texts[i].data(), texts[i].size()};
  }
  for (const uint32_t mc : {2u, 4u}) {
    const uint32_t T = std::min<uint32_t>(8, std::min<uint32_t>(mc, std::thread::hardware_concurrency()));
    std::vector<uint32_t> ks = {1};
    if (T - 1 != 1) ks.push_back(T - 1);
    for (const uint32_t k : ks) {
      const std::string tag = "C66 (a) mc " + S(mc) + " k " + S(k);
      // Batch.
      semb_encoder enc = OpenPublic(a, mc);
      if (!enc) { Verdict(false, tag + " setup", "open failed"); continue; }
      std::vector<float> base, armed, after;
      const semb_status sb = Batch(enc, texts, &base);
      semb_test_seam_arm_spawn_fail(k);
      const semb_status sa = Batch(enc, texts, &armed);
      uint32_t starts_after = 99;
      const int32_t fired = semb_test_seam_spawn_fail_fired(&starts_after);
      semb_test_seam_arm_spawn_fail(0);
      const semb_status sf = Batch(enc, texts, &after);
      const semb_status sc = semb_encoder_close(enc);
      Verdict(sb == SEMB_OK && sa == SEMB_OK && armed == base && fired == 1 && starts_after == 0 && sf == SEMB_OK &&
                  after == base && sc == SEMB_OK,
              tag + " semb_encode_batch of 8: SEMB_OK, rows = baseline, fired once, no start after; follow-up and "
                    "close OK",
              std::string("armed=") + Name(sa) + " fired=" + S(fired) + " starts_after=" + S(starts_after) +
                  " close=" + Name(sc));
      // Bake.
      enc = OpenPublic(a, mc);
      const std::string stem_base = (fs::path(a.scratch) / ("c66_base_" + S(mc) + "_" + S(k))).string();
      const std::string stem_armed = (fs::path(a.scratch) / ("c66_armed_" + S(mc) + "_" + S(k))).string();
      const semb_status b0 = semb_bake_to_path(enc, docs.data(), 8, stem_base.data(), stem_base.size());
      semb_test_seam_arm_spawn_fail(k);
      const semb_status b1 = semb_bake_to_path(enc, docs.data(), 8, stem_armed.data(), stem_armed.size());
      starts_after = 99;
      const int32_t bfired = semb_test_seam_spawn_fail_fired(&starts_after);
      semb_test_seam_arm_spawn_fail(0);
      const bool bytes_eq = b1 == SEMB_OK && ReadText(stem_base + ".wvbank.bin") == ReadText(stem_armed + ".wvbank.bin");
      const std::string rd0 = JsonField(ReadText(stem_base + ".semb.json"), "row_digest");
      const std::string rd1 = JsonField(ReadText(stem_armed + ".semb.json"), "row_digest");
      std::vector<float> after2;
      const semb_status sf2 = Batch(enc, texts, &after2);
      const semb_status sc2 = semb_encoder_close(enc);
      Verdict(b0 == SEMB_OK && b1 == SEMB_OK && bytes_eq && !rd0.empty() && rd0 == rd1 && bfired == 1 &&
                  starts_after == 0 && sf2 == SEMB_OK && after2 == base && sc2 == SEMB_OK,
              tag + " semb_bake_to_path of 8: SEMB_OK, .wvbank.bin and row digest = unarmed bake; fired once",
              std::string("armed=") + Name(b1) + " fired=" + S(bfired) + " row_digest " + rd0.substr(0, 12) + "/" +
                  rd1.substr(0, 12));
      // Open (the witness batch).
      semb_encoder plain = OpenPublic(a, mc);
      semb_fingerprint f0{}, f1{};
      f0.struct_size = f1.struct_size = sizeof(semb_fingerprint);
      if (plain) semb_fingerprint_of(plain, &f0);
      if (plain) semb_encoder_close(plain);
      semb_test_seam_arm_spawn_fail(k);
      semb_status so = SEMB_OK;
      semb_encoder opened = OpenPublic(a, mc, &so);
      starts_after = 99;
      const int32_t ofired = semb_test_seam_spawn_fail_fired(&starts_after);
      semb_test_seam_arm_spawn_fail(0);
      bool fp_eq = false, follow = false;
      semb_status oc = SEMB_INVALID_HANDLE;
      if (opened) {
        semb_fingerprint_of(opened, &f1);
        fp_eq = std::memcmp(f0.digest, f1.digest, 32) == 0;
        std::vector<float> after3;
        follow = Batch(opened, texts, &after3) == SEMB_OK && after3 == base;
        oc = semb_encoder_close(opened);
      }
      Verdict(so == SEMB_OK && fp_eq && ofired == 1 && starts_after == 0 && follow && oc == SEMB_OK,
              tag + " semb_encoder_open armed for its witness batch: SEMB_OK, fingerprint = unarmed open's",
              std::string("open=") + Name(so) + " fired=" + S(ofired) + " starts_after=" + S(starts_after));
    }
  }
  DisarmAll();
}

}  // namespace

int main(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    const std::string k = argv[i];
    auto next = [&]() -> std::string { return i + 1 < argc ? argv[++i] : ""; };
    if (k == "--model") a.model = next();
    else if (k == "--tokenizer") a.tokenizer = next();
    else if (k == "--scratch") a.scratch = next();
    else if (k == "--real-model") a.real_model = next();
    else if (k == "--cells") {
      std::stringstream ss(next());
      std::string c;
      while (std::getline(ss, c, ',')) a.cells.insert(c);
    }
  }
  if (a.model.empty() || a.tokenizer.empty() || a.scratch.empty()) {
    std::fprintf(stderr, "usage: %s --model <m> --tokenizer <t> --scratch <dir> [--real-model <m>] [--cells ...]\n",
                 argv[0]);
    return 2;
  }
  fs::create_directories(a.scratch);
  if (a.Want("c60c")) CellC60c(a);
  if (a.Want("c60poison")) CellC60Poison(a);
  if (a.Want("c61a")) CellC61a(a);
  if (a.Want("c61bc")) CellC61bc(a);
  if (a.Want("c61d")) CellC61d(a);
  if (a.Want("c61e")) CellC61e(a);
  if (a.Want("c61f")) CellC61f(a);
  if (a.Want("c66a")) CellC66a(a);
  std::printf("TOTAL pass=%d fail=%d\n", g_pass, g_fail);
  return g_fail == 0 ? 0 : 1;
}
