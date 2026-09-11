// src/main.cpp -- Slice 6's `semb` command-line drivers over the frozen C ABI.
#include <algorithm>
#include <atomic>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

#include "json_lite.h"
#include "semb_engine_pin.h"
#include "superembedder/bake_abi.h"
#include "superembedder/semb.h"
#include "superembedder/version.h"

namespace {

void PrintStatus(const char* where, semb_status status) {
  std::cerr << where << ": " << semb_status_name(status) << " ("
            << static_cast<int>(status) << ")\n";
}

int Refuse(const char* where, semb_status status) {
  PrintStatus(where, status);
  return 1;
}

const char* Option(const std::vector<std::string>& args, const char* name) {
  for (size_t i = 0; i + 1 < args.size(); ++i) {
    if (args[i] == name) return args[i + 1].c_str();
  }
  return nullptr;
}

bool HasOption(const std::vector<std::string>& args, const char* name) {
  return std::find(args.begin(), args.end(), name) != args.end();
}

struct QueryArguments {
  const char* model = nullptr;
  const char* tokenizer = nullptr;
  const char* top = nullptr;
  bool help = false;
  bool stdin_mode = false;
  bool hex = false;
  bool raw = false;
  std::vector<std::string> positional;
};

// Query deliberately parses left-to-right.  The `--` boundary ends option
// parsing, so option-shaped query text is data there; before it, each known
// option spelling remains control syntax even when options follow positionals.
bool ParseQueryArguments(const std::vector<std::string>& args, QueryArguments* out,
                         const char** bad_option) {
  bool options = true;
  for (size_t i = 0; i < args.size(); ++i) {
    const std::string& argument = args[i];
    if (!options) {
      out->positional.push_back(argument);
      continue;
    }
    if (argument == "--") {
      options = false;
      continue;
    }
    if (argument == "--help") {
      out->help = true;
      continue;
    }
    if (argument == "--stdin") {
      out->stdin_mode = true;
      continue;
    }
    if (argument == "--hex") {
      out->hex = true;
      continue;
    }
    if (argument == "--raw") {
      out->raw = true;
      continue;
    }
    const char** value = nullptr;
    if (argument == "--model") value = &out->model;
    if (argument == "--tokenizer") value = &out->tokenizer;
    if (argument == "--top") value = &out->top;
    if (value) {
      if (i + 1 == args.size() || args[i + 1] == "--") {
        *bad_option = argument.c_str();
        return false;
      }
      *value = args[++i].c_str();
      continue;
    }
    out->positional.push_back(argument);
  }
  return true;
}

bool ReadFile(const std::string& path, std::string* out) {
  std::ifstream stream(path, std::ios::binary | std::ios::ate);
  if (!stream) return false;
  const std::streamoff size = stream.tellg();
  if (size < 0) return false;
  out->resize(static_cast<size_t>(size));
  stream.seekg(0);
  return size == 0 || static_cast<bool>(stream.read(out->data(), size));
}

// Verify reuses the shipping bake primitive instead of duplicating either
// corpus- or row-digest construction in the CLI. Its private directory lives
// under the system temp root, never beside the bank being checked, and its
// destructor removes every temporary triple on success and every refusal.
class TemporaryBakeDirectory {
 public:
  bool Create() {
    std::error_code error;
    const std::filesystem::path root = std::filesystem::temp_directory_path(error);
    if (error) return false;
    static std::atomic<unsigned long long> counter{0};
    const auto ticks = static_cast<unsigned long long>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    for (unsigned int attempt = 0; attempt < 128; ++attempt) {
      path_ = root / ("semb-verify-" + std::to_string(ticks) + "-" +
                      std::to_string(counter.fetch_add(1, std::memory_order_relaxed)));
      if (std::filesystem::create_directory(path_, error)) return true;
      if (error && error != std::errc::file_exists) return false;
      error.clear();
    }
    return false;
  }

  const std::filesystem::path& path() const { return path_; }

  ~TemporaryBakeDirectory() {
    if (!path_.empty()) {
      std::error_code error;
      std::filesystem::remove_all(path_, error);
    }
  }

 private:
  std::filesystem::path path_;
};

bool ManifestField(const std::string& manifest, const char* field, std::string* out) {
  try {
    const semb::json::Value parsed = semb::json::Parse(manifest);
    const semb::json::Value* value = parsed.Find(field);
    if (!value || !value->IsString()) return false;
    *out = value->as_string;
    return true;
  } catch (...) {
    return false;
  }
}

bool LoadCorpus(const std::string& path, std::vector<std::string>* ids,
                std::vector<std::string>* texts, std::vector<semb_document>* docs) {
  std::ifstream stream(path);
  if (!stream) return false;
  // Format is selected by the path, never by a line's contents: exactly a
  // `.jsonl` extension selects JSONL; every other extension is one UTF-8 text
  // document per physical line, with the zero-based line number as its id.
  const bool jsonl = std::filesystem::path(path).extension() == ".jsonl";
  std::string line;
  size_t line_number = 0;
  try {
    while (std::getline(stream, line)) {
      if (jsonl) {
        if (line.empty()) continue;
        const semb::json::Value row = semb::json::Parse(line);
        const semb::json::Value* id = row.Find("id");
        const semb::json::Value* text = row.Find("text");
        if (!row.IsObject() || !id || !text || !id->IsString() || !text->IsString()) return false;
        ids->push_back(id->as_string);
        texts->push_back(text->as_string);
      } else {
        ids->push_back(std::to_string(line_number));
        texts->push_back(line);
      }
      ++line_number;
    }
  } catch (...) {
    return false;
  }
  docs->clear();
  docs->reserve(ids->size());
  for (size_t i = 0; i < ids->size(); ++i) {
    docs->push_back(semb_document{sizeof(semb_document), ids->at(i).data(), ids->at(i).size(),
                                  texts->at(i).data(), texts->at(i).size()});
  }
  return true;
}

struct Handles {
  semb_encoder encoder = nullptr;
  semb_bank bank = nullptr;
  semb_query query = nullptr;
  ~Handles() {
    if (query) (void)semb_query_close(query);
    if (bank) (void)semb_bank_close(bank);
    if (encoder) (void)semb_encoder_close(encoder);
  }
};

semb_status OpenEncoder(const char* model, const char* tokenizer, Handles* handles) {
  if (!model || !tokenizer) return SEMB_NULL_ARGUMENT;
  const semb_config config{sizeof(config), model, std::strlen(model), tokenizer,
                           std::strlen(tokenizer), 1};
  return semb_encoder_open(&config, &handles->encoder);
}

semb_status OpenCheckedQuery(const std::string& stem, const char* model, const char* tokenizer,
                             Handles* handles) {
  semb_status status = OpenEncoder(model, tokenizer, handles);
  if (status != SEMB_OK) return status;
  status = semb_bank_open(stem.data(), stem.size(), &handles->bank);
  if (status != SEMB_OK) return status;
  return semb_query_open(handles->encoder, handles->bank, &handles->query);
}

semb_status QueryVector(semb_query query, std::string_view text, std::vector<float>* vector) {
  size_t required = 0;
  semb_status status = semb_query_encode(query, text.data(), text.size(), nullptr, 0, &required);
  if (status != SEMB_BUFFER_TOO_SMALL) return status;
  vector->assign(required / sizeof(float), 0.0f);
  return semb_query_encode(query, text.data(), text.size(), vector->data(), required, &required);
}

std::string Hex(const std::vector<float>& vector) {
  static constexpr char kHex[] = "0123456789abcdef";
  const auto* bytes = reinterpret_cast<const unsigned char*>(vector.data());
  std::string out;
  out.reserve(vector.size() * sizeof(float) * 2);
  for (size_t i = 0; i < vector.size() * sizeof(float); ++i) {
    out.push_back(kHex[bytes[i] >> 4]);
    out.push_back(kHex[bytes[i] & 0x0f]);
  }
  return out;
}

struct SearchBank {
  std::vector<std::string> ids;
  std::vector<float> rows;
  size_t dims = 0;
};

bool LoadSearchBank(const std::string& stem, SearchBank* bank) {
  std::string header, payload;
  if (!ReadFile(stem + ".wvbank.json", &header) || !ReadFile(stem + ".wvbank.bin", &payload)) return false;
  try {
    const semb::json::Value parsed = semb::json::Parse(header);
    const semb::json::Value* ids = parsed.Find("ids");
    const semb::json::Value* dims = parsed.Find("dims");
    if (!ids || !dims || !ids->IsArray() || dims->kind != semb::json::Kind::kInt || dims->as_int <= 0) return false;
    bank->dims = static_cast<size_t>(dims->as_int);
    bank->ids.clear();
    for (const auto& id : ids->as_array) {
      if (!id.IsString()) return false;
      bank->ids.push_back(id.as_string);
    }
    if (payload.size() != bank->ids.size() * bank->dims * sizeof(float)) return false;
    bank->rows.resize(payload.size() / sizeof(float));
    std::memcpy(bank->rows.data(), payload.data(), payload.size());
    return true;
  } catch (...) {
    return false;
  }
}

std::string TopHitsJson(const SearchBank& bank, const std::vector<float>& query, size_t top) {
  if (query.size() != bank.dims) return {};
  struct Hit { size_t index; double score; };
  std::vector<Hit> hits;
  hits.reserve(bank.ids.size());
  for (size_t row = 0; row < bank.ids.size(); ++row) {
    double dot = 0.0, query_norm = 0.0, row_norm = 0.0;
    for (size_t dim = 0; dim < bank.dims; ++dim) {
      const double q = query[dim];
      const double r = bank.rows[row * bank.dims + dim];
      dot += q * r;
      query_norm += q * q;
      row_norm += r * r;
    }
    const double denominator = std::sqrt(query_norm * row_norm);
    hits.push_back(Hit{row, denominator == 0.0 ? -1.0 : dot / denominator});
  }
  std::sort(hits.begin(), hits.end(), [](const Hit& left, const Hit& right) {
    return left.score != right.score ? left.score > right.score : left.index < right.index;
  });
  semb::json::Value output = semb::json::Value::MakeObject();
  semb::json::Value array = semb::json::Value::MakeArray();
  for (size_t i = 0; i < std::min(top, hits.size()); ++i) {
    semb::json::Value hit = semb::json::Value::MakeObject();
    hit.Set("id", semb::json::Value::MakeString(bank.ids[hits[i].index]));
    array.as_array.push_back(std::move(hit));
  }
  output.Set("hits", std::move(array));
  return semb::json::Write(output);
}

int Bake(const std::vector<std::string>& args) {
  if (args.empty()) return Refuse("semb bake", SEMB_NULL_ARGUMENT);
  const char* out = Option(args, "--out");
  const char* model = Option(args, "--model");
  const char* tokenizer = Option(args, "--tokenizer");
  if (!out || !model || !tokenizer) return Refuse("semb bake", SEMB_NULL_ARGUMENT);
  const std::string corpus = args.front();
  std::vector<std::string> ids, texts;
  std::vector<semb_document> docs;
  if (!LoadCorpus(corpus, &ids, &texts, &docs)) return Refuse("semb bake corpus", SEMB_ARTIFACT_UNREADABLE);
  Handles handles;
  semb_status status = OpenEncoder(model, tokenizer, &handles);
  if (status != SEMB_OK) return Refuse("semb_encoder_open", status);
  status = semb_bake_to_path(handles.encoder, docs.data(), docs.size(), out, std::strlen(out));
  if (status != SEMB_OK) return Refuse("semb_bake_to_path", status);
  return 0;
}

int Query(const std::vector<std::string>& args) {
  if (args.size() == 1 && args[0] == "--help") {
    std::cout << "usage: semb query [--stdin] <name> [<text>] [--hex | --top k] --model <sslm> --tokenizer <sslm>\n"
                 "One-shot query is a documented diagnostic; --stdin reuses one checked query handle.\n";
    return 0;
  }
  QueryArguments parsed;
  const char* bad_option = nullptr;
  if (!ParseQueryArguments(args, &parsed, &bad_option)) return Refuse(bad_option, SEMB_NULL_ARGUMENT);
  if (parsed.help) return Refuse("semb query --help", SEMB_NULL_ARGUMENT);
  if (!parsed.model || !parsed.tokenizer) return Refuse("semb query", SEMB_NULL_ARGUMENT);
  if ((parsed.stdin_mode && parsed.positional.size() != 1) ||
      (!parsed.stdin_mode && parsed.positional.size() != 2)) {
    return Refuse("semb query", SEMB_NULL_ARGUMENT);
  }
  size_t top = 0;
  if (parsed.top) {
    const auto top_parsed = std::from_chars(parsed.top, parsed.top + std::strlen(parsed.top), top);
    if (top_parsed.ec != std::errc{} || *top_parsed.ptr != '\0' || top == 0) {
      return Refuse("semb query --top", SEMB_NULL_ARGUMENT);
    }
  }
  if (parsed.raw && (parsed.stdin_mode || top != 0)) return Refuse("semb query --raw", SEMB_NULL_ARGUMENT);
#if defined(_WIN32)
  if (parsed.raw && _setmode(_fileno(stdout), _O_BINARY) == -1) {
    return Refuse("semb query --raw", SEMB_ARTIFACT_UNREADABLE);
  }
#endif
  Handles handles;
  const std::string stem = parsed.positional[0];
  semb_status status = OpenCheckedQuery(stem, parsed.model, parsed.tokenizer, &handles);
  if (status != SEMB_OK) return Refuse("semb query", status);
  SearchBank search_bank;
  if (top && !LoadSearchBank(stem, &search_bank)) return Refuse("semb query bank", SEMB_ARTIFACT_UNREADABLE);
  auto emit = [&](const std::string& text) -> bool {
    std::vector<float> vector;
    status = QueryVector(handles.query, text, &vector);
    if (status != SEMB_OK) {
      (void)Refuse("semb_query_encode", status);
      return false;
    }
    if (parsed.raw) {
      std::cout.write(reinterpret_cast<const char*>(vector.data()),
                      static_cast<std::streamsize>(vector.size() * sizeof(float)));
      std::cout.flush();
    } else if (top) {
      const std::string output = TopHitsJson(search_bank, vector, top);
      if (output.empty()) {
        (void)Refuse("semb query bank", SEMB_ARTIFACT_UNREADABLE);
        return false;
      }
      std::cout << output << '\n' << std::flush;
    } else {
      std::cout << "VECTOR_HEX=" << Hex(vector) << '\n' << std::flush;
    }
    return true;
  };
  if (parsed.stdin_mode) {
    std::string line;
    while (std::getline(std::cin, line)) {
      if (!emit(line)) return 1;
    }
  } else if (!emit(parsed.positional[1])) {
    return 1;
  }
  if (parsed.stdin_mode) std::cerr << "query_handle_opens=1\n";
  return 0;
}

int Verify(const std::vector<std::string>& args) {
  const char* model = Option(args, "--model");
  const char* tokenizer = Option(args, "--tokenizer");
  const char* corpus = Option(args, "--corpus");
  std::vector<std::string> positional;
  for (size_t i = 0; i < args.size(); ++i) {
    if ((args[i] == "--model" || args[i] == "--tokenizer" || args[i] == "--corpus") && i + 1 < args.size()) {
      ++i;
      continue;
    }
    positional.push_back(args[i]);
  }
  if (!model || !tokenizer || !corpus || positional.size() != 1) return Refuse("semb verify", SEMB_NULL_ARGUMENT);
  Handles handles;
  semb_status status = OpenCheckedQuery(positional[0], model, tokenizer, &handles);
  if (status != SEMB_OK) return Refuse("semb verify", status);

  std::vector<std::string> ids, texts;
  std::vector<semb_document> docs;
  if (!LoadCorpus(corpus, &ids, &texts, &docs)) return Refuse("semb verify corpus", SEMB_ARTIFACT_UNREADABLE);
  TemporaryBakeDirectory scratch;
  if (!scratch.Create()) return Refuse("semb verify scratch", SEMB_ARTIFACT_UNREADABLE);
  const std::string rebaked_stem = (scratch.path() / "rebaked").string();
  status = semb_bake_to_path(handles.encoder, docs.data(), docs.size(), rebaked_stem.data(), rebaked_stem.size());
  if (status != SEMB_OK) return Refuse("semb verify re-encode", status);

  std::string bank_manifest, rebaked_manifest;
  if (!ReadFile(positional[0] + ".semb.json", &bank_manifest) ||
      !ReadFile(rebaked_stem + ".semb.json", &rebaked_manifest)) {
    return Refuse("semb verify manifest", SEMB_ARTIFACT_UNREADABLE);
  }
  std::string bank_corpus_digest, rebaked_corpus_digest, bank_row_digest, rebaked_row_digest;
  if (!ManifestField(bank_manifest, "corpus_digest", &bank_corpus_digest) ||
      !ManifestField(rebaked_manifest, "corpus_digest", &rebaked_corpus_digest) ||
      !ManifestField(bank_manifest, "row_digest", &bank_row_digest) ||
      !ManifestField(rebaked_manifest, "row_digest", &rebaked_row_digest)) {
    return Refuse("semb verify manifest", SEMB_ARTIFACT_UNREADABLE);
  }
  if (bank_corpus_digest != rebaked_corpus_digest) {
    std::cerr << "semb verify: SEMB_CORPUS_DIGEST_MISMATCH\n";
    return 1;
  }
  if (bank_row_digest != rebaked_row_digest) return Refuse("semb verify", SEMB_BANK_DIGEST_MISMATCH);
  return 0;
}

int Inspect(const std::vector<std::string>& args) {
  if (args.size() != 1) return Refuse("semb inspect", SEMB_NULL_ARGUMENT);
  std::string manifest;
  if (!ReadFile(args[0], &manifest)) return Refuse("semb inspect", SEMB_ARTIFACT_UNREADABLE);
  try {
    semb::json::Parse(manifest);
  } catch (...) {
    return Refuse("semb inspect", SEMB_ARTIFACT_UNREADABLE);
  }
  std::cout << manifest;
  if (manifest.empty() || manifest.back() != '\n') std::cout << '\n';
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cout << "semb " << superembedder::Version() << " (engine pin " << SEMB_ENGINE_PIN_TAG
              << " @ " << SEMB_ENGINE_PIN_COMMIT << ", engine_path_sha=" << SEMB_ENGINE_PATH_SHA << ")\n";
    return 0;
  }
  const std::string command = argv[1];
  std::vector<std::string> args;
  for (int i = 2; i < argc; ++i) args.emplace_back(argv[i]);
  if (command == "bake") return Bake(args);
  if (command == "query") return Query(args);
  if (command == "verify") return Verify(args);
  if (command == "inspect") return Inspect(args);
  return Refuse("semb", SEMB_NULL_ARGUMENT);
}
