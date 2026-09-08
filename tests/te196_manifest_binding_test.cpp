// tests/te196_manifest_binding_test.cpp -- TE-196 (U1 slice 4 fix round):
// the driver for the TE-193 review's fix cells, each naming the exact
// status the fixed build must refuse with (Claude/Bach/briefs/
// te196-slice4-fix.md; the findings are Claude/Poirot/21b1735-te193-
// slice4-review.md sec 3). Built and run by
// tests/te196_manifest_binding_check.py against the synthetic mechanism
// pair, the same driver shape te163_bank_pair_check.py established; the
// mechanism-bake scaffolding below is COPIED from
// tests/te163_bank_pair_test.cpp per this round's own brief (TE-192 owns
// that file in a concurrent round -- nothing is factored out of it).
//
// USAGE: --model <.sslm> --tokenizer <.sslm> --dims <n> --scratch <dir>
// [--stem <name>]
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "json_mini.h"
#include "json_lite.h"
#include "superembedder/manifest_labels_abi.h"
#include "semb_public_abi_contract.h"
#include "semb_bake_abi_contract.h"
#include "semb_bank_abi_contract.h"

namespace fs = std::filesystem;

namespace {

int g_failures = 0;
int g_cells = 0;
void Verdict(bool ok, const std::string& cell, const std::string& observed) {
  ++g_cells;
  if (!ok) ++g_failures;
  std::printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", cell.c_str(), observed.c_str());
  std::fflush(stdout);
}
void Observed(const std::string& what) {
  std::printf("[OBSERVED] %s\n", what.c_str());
  std::fflush(stdout);
}
const char* Name(semb_status s) { const char* n = semb_status_name(s); return n ? n : "<NULL>"; }

std::string ReadFileBytes(const fs::path& p) {
  std::ifstream f(p, std::ios::binary);
  if (!f) throw std::runtime_error("cannot open " + p.string());
  std::ostringstream oss;
  oss << f.rdbuf();
  return oss.str();
}

// Statuses 0-31 resolve through the contract header's own StatusByName
// (tests/semb_public_abi_contract.h). Ordinals 32-33 are provisional and
// the contract does not carry them (H-5c is the open gap, TE-192's), so
// this driver resolves ANY status by scanning the product's own
// semb_status_name over the enum's range and matching the name -- resolved
// against the running library, never hardcoded as an ordinal here.
semb_status ResolveStatus(const char* name) {
  for (int i = 0; i < 64; ++i) {
    const char* n = semb_status_name(static_cast<semb_status>(i));
    if (n && std::strcmp(n, name) == 0) return static_cast<semb_status>(i);
  }
  throw std::runtime_error(std::string("status not found: ") + name);
}

struct Args {
  std::string model, tokenizer, scratch, stem = "te196";
  unsigned dims = 0;
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
    else if (k == "--stem") next(&a.stem);
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

// The DocSet arena pattern, copied from tests/te163_bank_pair_test.cpp (a
// temporary std::string bound to a semb_document's raw pointer dangles the
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

// Copies the three-file triple at `src_stem` to `dst_stem`, applying `edit`
// to the manifest/header/bin bytes before writing each copy -- the same
// "editing a copy of a good triple" construction the TE-163 suite uses.
// An exception thrown out of `edit` is caught and reported as a NAMED FAIL
// for `cell_name`, never left to propagate (D-SLM6411 item (a)).
bool CopyTriple(const fs::path& src_stem, const fs::path& dst_stem, const std::string& cell_name,
                const std::function<std::string(std::string)>& edit_manifest = nullptr,
                const std::function<std::string(std::string)>& edit_header = nullptr,
                const std::function<std::string(std::string)>& edit_bin = nullptr) {
  bool ok = true;
  auto copy_one = [&](const char* suffix, const std::function<std::string(std::string)>& edit) {
    if (!ok) return;
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

// Opens the triple at `stem`, expecting exactly `expect`, and asserts the
// refusal shape the bank contract pins (every refused open: *out == NULL).
void TryOpenExpect(const std::string& cell, const fs::path& stem, semb_status expect,
                   const std::string& expect_name) {
  const std::string stem_str = stem.string();
  semb_bank bank = nullptr;
  const semb_status s = semb_bank_open(stem_str.c_str(), stem_str.size(), &bank);
  Verdict(s == expect, cell, std::string(Name(s)) + " (expected " + expect_name + ")");
  Verdict(bank == nullptr, cell + " leaves *out == NULL", bank == nullptr ? "confirmed" : "NOT NULL");
  if (bank) semb_bank_close(bank);  // never reached on a correct refusal; drains defensively
}

}  // namespace

int main(int argc, char** argv) {
  const Args a = ParseArgs(argc, argv);
  if (a.model.empty() || a.tokenizer.empty() || a.dims == 0 || a.scratch.empty()) {
    std::fprintf(stderr, "usage: %s --model <.sslm> --tokenizer <.sslm> --dims <n> --scratch <dir> [--stem <name>]\n", argv[0]);
    return 2;
  }
  fs::create_directories(a.scratch);
  const fs::path scratch(a.scratch);
  const std::string label = "mechanism";

  // The good triple every tamper cell edits a copy of (the same two-document
  // fixture te163_bank_pair_test.cpp's cell 2 uses, baked fresh here).
  const fs::path good_stem = scratch / (a.stem + "_good");
  {
    semb_encoder enc = Open(a);
    if (!enc) return 1;
    DocSet arena;
    std::vector<semb_document> docs = {arena.Add("g0", "the first small good document"),
                                       arena.Add("g1", "the second small good document")};
    const std::string stem_str = good_stem.string();
    fs::remove(fs::path(stem_str + ".wvbank.json"));
    fs::remove(fs::path(stem_str + ".wvbank.bin"));
    fs::remove(fs::path(stem_str + ".semb.json"));
    const semb_status bs = semb_bake_to_path(enc, docs.data(), docs.size(), stem_str.c_str(), stem_str.size());
    semb_encoder_close(enc);
    if (bs != SEMB_OK) { Verdict(false, label + "/(setup) bake the good triple", Name(bs)); return 1; }
  }
  {
    semb_bank bank = nullptr;
    const std::string good_str = good_stem.string();
    const semb_status s = semb_bank_open(good_str.c_str(), good_str.size(), &bank);
    Verdict(s == SEMB_OK, label + "/control the freshly baked good triple opens -> SEMB_OK", Name(s));
    if (s == SEMB_OK) semb_bank_close(bank);
  }

  // =========================================================================
  // TE-193 P-3 -- FORMAT.md sec 1's field table makes "channels" a
  // schemaVersion-2-only table (and required by it); the reference
  // importer refuses it by name (wvbank.py: "channels table requires
  // schemaVersion 2"). A v1 header carrying it must refuse
  // SEMB_MANIFEST_SCHEMA_UNSUPPORTED, not open SEMB_OK.
  // =========================================================================
  {
    const fs::path stem = scratch / (a.stem + "_t_channels_v1");
    if (CopyTriple(good_stem, stem, label + "/P3 channels under schemaVersion 1", nullptr,
                   [](std::string header) {
                     // json_lite::Write emits no nested object, so the
                     // first '}' is the header's own terminator; a member
                     // appended before it keeps the JSON well formed.
                     return ReplaceOnce(header, "}",
                                        ", \"channels\": [{\"name\": \"x\", \"offset\": 0, \"dims\": 4}]}");
                   })) {
      TryOpenExpect(label + "/P3 a v1 header carrying a channels table -> SEMB_MANIFEST_SCHEMA_UNSUPPORTED",
                    stem, ResolveStatus("SEMB_MANIFEST_SCHEMA_UNSUPPORTED"), "SEMB_MANIFEST_SCHEMA_UNSUPPORTED");
    }
  }

  // =========================================================================
  // TE-193 P-4 -- the manifest binds metric and dtype: the bake writes both
  // into the manifest, and open compares header against manifest so a
  // header edited after the bake refuses. The metric flip is header-side
  // (cosine -> l2 is inside FORMAT.md's admitted set, so only the manifest
  // binding can catch it); the dtype flip is manifest-side (float32 is the
  // header's only admitted dtype, so a header-side flip would refuse at the
  // admitted-set check instead of at the binding).
  // =========================================================================
  {
    // Bake half: the freshly baked manifest carries both fields, agreeing
    // with the header the same bake wrote.
    {
      const std::string manifest_text = ReadFileBytes(fs::path(good_stem.string() + ".semb.json"));
      json_mini::Parser mp(manifest_text);
      json_mini::Value manifest = mp.Parse();
      const bool has_both = manifest.as_object.count("metric") && manifest.as_object.count("dtype") &&
                            manifest["metric"].s() == "cosine" && manifest["dtype"].s() == "float32";
      Verdict(has_both,
              label + "/P4 the baked manifest binds metric and dtype (cosine/float32, agreeing with its own header)",
              has_both ? "metric=cosine dtype=float32" : "missing or disagreeing");
    }
    const semb_status st_metric_dtype = ResolveStatus("SEMB_BANK_METRIC_DTYPE_UNSUPPORTED");
    {
      const fs::path stem = scratch / (a.stem + "_t_metric_header");
      if (CopyTriple(good_stem, stem, label + "/P4 header metric cosine -> l2", nullptr,
                     [](std::string header) { return ReplaceOnce(header, "\"metric\": \"cosine\"", "\"metric\": \"l2\""); })) {
        TryOpenExpect(label + "/P4 header metric edited cosine -> l2 against an untampered manifest "
                             "-> SEMB_BANK_METRIC_DTYPE_UNSUPPORTED",
                      stem, st_metric_dtype, "SEMB_BANK_METRIC_DTYPE_UNSUPPORTED");
      }
    }
    {
      const fs::path stem = scratch / (a.stem + "_t_dtype_manifest");
      if (CopyTriple(good_stem, stem, label + "/P4 manifest dtype float32 -> int8",
                     [](std::string manifest) { return ReplaceOnce(manifest, "\"dtype\": \"float32\"", "\"dtype\": \"int8\""); })) {
        TryOpenExpect(label + "/P4 manifest dtype edited float32 -> int8 against an untampered header "
                             "-> SEMB_BANK_METRIC_DTYPE_UNSUPPORTED",
                      stem, st_metric_dtype, "SEMB_BANK_METRIC_DTYPE_UNSUPPORTED");
      }
    }
  }

  // =========================================================================
  // TE-193 P-5 -- label:ps_version accepts exactly what the bake writes
  // (semb_ps_n_version_label(); the bake path compares against it alone), the
  // shape of the sibling label:engine_path_id check. PS-1 is a label no bake
  // of this build can emit, so it must refuse; PS-Z must still refuse.
  // =========================================================================
  {
    const semb_status st_ps_mismatch = ResolveStatus("SEMB_PS_VERSION_LABEL_MISMATCH");
    const std::string ps_n = semb_ps_n_version_label();
    {
      const fs::path stem = scratch / (a.stem + "_t_ps1");
      if (CopyTriple(good_stem, stem, label + "/P5 manifest label:ps_version PS-N -> PS-1",
                     [ps_n](std::string manifest) {
                       return ReplaceOnce(manifest, "\"label:ps_version\": \"" + ps_n + "\"",
                                                           "\"label:ps_version\": \"PS-1\"");
                     })) {
        TryOpenExpect(label + "/P5 manifest label:ps_version PS-N -> PS-1 (a label this build's bake never writes) "
                             "-> SEMB_PS_VERSION_LABEL_MISMATCH",
                      stem, st_ps_mismatch, "SEMB_PS_VERSION_LABEL_MISMATCH");
      }
    }
    {
      const fs::path stem = scratch / (a.stem + "_t_psz");
      if (CopyTriple(good_stem, stem, label + "/P5 manifest label:ps_version PS-N -> PS-Z",
                     [ps_n](std::string manifest) {
                       return ReplaceOnce(manifest, "\"label:ps_version\": \"" + ps_n + "\"",
                                                           "\"label:ps_version\": \"PS-Z\"");
                     })) {
        TryOpenExpect(label + "/P5 manifest label:ps_version PS-N -> PS-Z still refuses -> SEMB_PS_VERSION_LABEL_MISMATCH",
                      stem, st_ps_mismatch, "SEMB_PS_VERSION_LABEL_MISMATCH");
      }
    }
    // Control: the untouched good triple above already proves the PS-N the
    // bake writes opens; no additional control is needed here.
  }

  // =========================================================================
  // TE-193 P-12 -- dims:0 and count:-1 are malformed header values, not
  // values over a format ceiling: they refuse SEMB_ARTIFACT_UNREADABLE, and
  // the ceiling status is reserved for dims > 131,072 / count > 2^28 (the
  // only values the plan's own ordinal-31 row names).
  // =========================================================================
  {
    const semb_status st_unreadable = ResolveStatus("SEMB_ARTIFACT_UNREADABLE");
    const semb_status st_ceiling = ResolveStatus("SEMB_BANK_GEOMETRY_CEILING_EXCEEDED");
    const std::string dims_field = "\"dims\": " + std::to_string(a.dims);
    const std::string count_field = "\"count\": 2";
    {
      const fs::path stem = scratch / (a.stem + "_t_dims_zero");
      if (CopyTriple(good_stem, stem, label + "/P12 dims: 0", nullptr,
                     [dims_field](std::string header) { return ReplaceOnce(header, dims_field, "\"dims\": 0"); })) {
        TryOpenExpect(label + "/P12 dims 0 (malformed, not over a ceiling) -> SEMB_ARTIFACT_UNREADABLE",
                      stem, st_unreadable, "SEMB_ARTIFACT_UNREADABLE");
      }
    }
    {
      const fs::path stem = scratch / (a.stem + "_t_count_neg");
      if (CopyTriple(good_stem, stem, label + "/P12 count: -1", nullptr,
                     [count_field](std::string header) { return ReplaceOnce(header, count_field, "\"count\": -1"); })) {
        TryOpenExpect(label + "/P12 count -1 (malformed, not over a ceiling) -> SEMB_ARTIFACT_UNREADABLE",
                      stem, st_unreadable, "SEMB_ARTIFACT_UNREADABLE");
      }
    }
    {
      const fs::path stem = scratch / (a.stem + "_t_dims_ceiling_control");
      if (CopyTriple(good_stem, stem, label + "/P12 dims over the ceiling (control)", nullptr,
                     [dims_field](std::string header) { return ReplaceOnce(header, dims_field, "\"dims\": 999999999"); })) {
        TryOpenExpect(label + "/P12 dims over 131,072 still -> SEMB_BANK_GEOMETRY_CEILING_EXCEEDED (control)",
                      stem, st_ceiling, "SEMB_BANK_GEOMETRY_CEILING_EXCEEDED");
      }
    }
  }

  std::printf("\nte196_manifest_binding_test: %d cell(s), %d failure(s)\n", g_cells, g_failures);
  return g_failures ? 1 : 0;
}