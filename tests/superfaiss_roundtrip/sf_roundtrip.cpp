// The SuperFAISS side of the round-trip harness (plan U2-2).
//
// Compiled from SuperFAISS's own src/*.cpp at the tag superfaiss.lock pins,
// with the flags SuperFAISS's docs/INTEGRATION.md section 1 requires. It links
// no SuperEmbedder code: it reads the .wvbank payload and query vectors as
// plain float32 bytes and runs exactly the import and query path a SuperFAISS
// user runs (INTEGRATION.md section 4):
//
//   bake:  ValidateSourceRows -> NormalizeRows (cosine) -> QuantizeRowsInt8
//          and PadRowsFloat32 -> ValidateBank + ValidateBankData on both banks
//   query: each query vector zero-padded to the bank's paddedDims, passed
//          otherwise unchanged (no normalization), then Query() in PerDevice
//          mode on the float32 bank or CrossDevice mode on the int8 bank.
//
// The JSON header is parsed by the Python driver with SuperFAISS's reference
// reader (tools/wvbank.py read_bank); this program receives its fields as
// arguments, as an importer's own JSON library would hand them over.
//
// Usage:
//   sf_roundtrip bake  <payload.bin> <count> <dims> <metric> <out-dir>
//   sf_roundtrip query <bank-dir> <count> <dims> <metric> <perdevice|crossdevice>
//                      <k> <queries.bin> <query-count> <hits.bin>
//
// bake writes <out-dir>/f32.rows, int8.rows and int8.scales (the baked
// layouts, little-endian) and prints one KEY=VALUE line per step. query writes
// query-count x k records of {int32 index, float32 score}, little-endian,
// query-major, best first. Exit 0 only when every SuperFAISS call returned Ok.

#include <superfaiss/superfaiss.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <new>
#include <string>
#include <vector>

namespace {

using superfaiss::Status;

const char* StatusName(Status status) {
  switch (status) {
    case Status::Ok: return "Ok";
    case Status::InvalidArgument: return "InvalidArgument";
    case Status::DimsMismatch: return "DimsMismatch";
    case Status::NonFiniteQuery: return "NonFiniteQuery";
    case Status::ZeroNormQuery: return "ZeroNormQuery";
    case Status::NonZeroPadding: return "NonZeroPadding";
    case Status::BadAlignment: return "BadAlignment";
    case Status::BadFormat: return "BadFormat";
    case Status::ZeroNormRow: return "ZeroNormRow";
    case Status::OutOfMemory: return "OutOfMemory";
  }
  return "Unknown";
}

// A 16-byte-aligned byte buffer (FORMAT.md section 2: row blocks and query
// buffers must be kAlignment-aligned).
class Aligned {
 public:
  explicit Aligned(size_t bytes) : size_(bytes) {
    data_ = static_cast<unsigned char*>(
        ::operator new(bytes == 0 ? 1 : bytes, std::align_val_t(superfaiss::kAlignment)));
    std::memset(data_, 0, bytes == 0 ? 1 : bytes);
  }
  ~Aligned() { ::operator delete(data_, std::align_val_t(superfaiss::kAlignment)); }
  Aligned(const Aligned&) = delete;
  Aligned& operator=(const Aligned&) = delete;
  template <typename T> T* as() { return reinterpret_cast<T*>(data_); }
  size_t size() const { return size_; }

 private:
  unsigned char* data_;
  size_t size_;
};

bool ReadFile(const std::string& path, std::vector<unsigned char>* out) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  out->assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
  return true;
}

bool ReadInto(const std::string& path, Aligned* buffer) {
  std::vector<unsigned char> bytes;
  if (!ReadFile(path, &bytes) || bytes.size() != buffer->size()) return false;
  if (!bytes.empty()) std::memcpy(buffer->as<unsigned char>(), bytes.data(), bytes.size());
  return true;
}

bool WriteFile(const std::string& path, const void* data, size_t bytes) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out.write(static_cast<const char*>(data), static_cast<std::streamsize>(bytes));
  out.close();
  return static_cast<bool>(out);
}

bool ParseInt(const char* text, int32_t* out) {
  char* end = nullptr;
  const long long value = std::strtoll(text, &end, 10);
  if (end == text || *end != '\0' || value < INT32_MIN || value > INT32_MAX) return false;
  *out = static_cast<int32_t>(value);
  return true;
}

bool ParseMetric(const std::string& text, superfaiss::Metric* out) {
  if (text == "cosine") { *out = superfaiss::Metric::Cosine; return true; }
  if (text == "dot") { *out = superfaiss::Metric::Dot; return true; }
  if (text == "l2") { *out = superfaiss::Metric::L2; return true; }
  return false;
}

int Usage() {
  std::cerr << "usage: sf_roundtrip bake <payload.bin> <count> <dims> <metric> <out-dir>\n"
               "       sf_roundtrip query <bank-dir> <count> <dims> <metric> <perdevice|crossdevice>"
               " <k> <queries.bin> <query-count> <hits.bin>\n";
  return 64;
}

int Bake(int argc, char** argv) {
  if (argc != 7) return Usage();
  int32_t count = 0, dims = 0;
  superfaiss::Metric metric{};
  if (!ParseInt(argv[3], &count) || !ParseInt(argv[4], &dims) || !ParseMetric(argv[5], &metric) ||
      count < 0 || dims <= 0) {
    return Usage();
  }
  const std::string out_dir = argv[6];
  std::vector<unsigned char> payload;
  if (!ReadFile(argv[2], &payload)) {
    std::cout << "payload=unreadable\n";
    return 2;
  }
  const size_t source_floats = static_cast<size_t>(count) * static_cast<size_t>(dims);
  if (payload.size() != source_floats * sizeof(float)) {
    std::cout << "payload=size_mismatch bytes=" << payload.size() << "\n";
    return 2;
  }
  std::vector<float> rows(source_floats);
  if (!payload.empty()) std::memcpy(rows.data(), payload.data(), payload.size());

  bool ok = true;
  int32_t bad = -1;
  Status status = superfaiss::ValidateSourceRows(rows.data(), count, dims, &bad);
  std::cout << "validate_source_rows=" << StatusName(status) << " bad_row=" << bad << "\n";
  if (status != Status::Ok) return 2;  // an importer rejects with no partial output

  if (metric == superfaiss::Metric::Cosine) {
    bad = -1;
    status = superfaiss::NormalizeRows(rows.data(), count, dims, &bad);
    std::cout << "normalize_rows=" << StatusName(status) << " bad_row=" << bad << "\n";
    if (status != Status::Ok) return 2;
  }

  const int32_t pd_f32 = superfaiss::PaddedDims(dims, superfaiss::Quantization::Float32);
  const int32_t pd_i8 = superfaiss::PaddedDims(dims, superfaiss::Quantization::Int8);
  std::cout << "padded_dims_float32=" << pd_f32 << " padded_dims_int8=" << pd_i8 << "\n";

  Aligned f32(static_cast<size_t>(count) * pd_f32 * sizeof(float));
  superfaiss::PadRowsFloat32(rows.data(), count, dims, pd_f32, f32.as<float>());
  Aligned i8(static_cast<size_t>(count) * pd_i8);
  Aligned scales(static_cast<size_t>(count) * sizeof(float));
  superfaiss::QuantizeRowsInt8(rows.data(), count, dims, pd_i8, i8.as<int8_t>(), scales.as<float>());

  superfaiss::BankView f32_view;
  f32_view.rows = f32.as<void>();
  f32_view.count = count;
  f32_view.dims = dims;
  f32_view.paddedDims = pd_f32;
  f32_view.quant = superfaiss::Quantization::Float32;
  f32_view.metric = metric;
  superfaiss::BankView i8_view = f32_view;
  i8_view.rows = i8.as<void>();
  i8_view.scales = scales.as<float>();
  i8_view.paddedDims = pd_i8;
  i8_view.quant = superfaiss::Quantization::Int8;

  for (const auto& [name, view] : {std::pair<const char*, const superfaiss::BankView*>{"float32", &f32_view},
                                   std::pair<const char*, const superfaiss::BankView*>{"int8", &i8_view}}) {
    status = superfaiss::ValidateBank(*view);
    std::cout << "validate_bank_" << name << "=" << StatusName(status) << "\n";
    ok = ok && status == Status::Ok;
    bad = -1;
    status = superfaiss::ValidateBankData(*view, &bad);
    std::cout << "validate_bank_data_" << name << "=" << StatusName(status) << " bad_row=" << bad << "\n";
    ok = ok && status == Status::Ok;
  }
  if (!ok) return 2;
  if (!WriteFile(out_dir + "/f32.rows", f32.as<void>(), f32.size()) ||
      !WriteFile(out_dir + "/int8.rows", i8.as<void>(), i8.size()) ||
      !WriteFile(out_dir + "/int8.scales", scales.as<void>(), scales.size())) {
    std::cout << "write=failed\n";
    return 2;
  }
  std::cout << "write=Ok\n";
  return 0;
}

int QueryBank(int argc, char** argv) {
  if (argc != 11) return Usage();
  int32_t count = 0, dims = 0, k = 0, query_count = 0;
  superfaiss::Metric metric{};
  const std::string mode = argv[6];
  if (!ParseInt(argv[3], &count) || !ParseInt(argv[4], &dims) || !ParseMetric(argv[5], &metric) ||
      !ParseInt(argv[7], &k) || !ParseInt(argv[9], &query_count) || count <= 0 || dims <= 0 || k <= 0 ||
      query_count < 0 || (mode != "perdevice" && mode != "crossdevice")) {
    return Usage();
  }
  const bool cross = mode == "crossdevice";
  const std::string bank_dir = argv[2];
  const auto quant = cross ? superfaiss::Quantization::Int8 : superfaiss::Quantization::Float32;
  const int32_t padded = superfaiss::PaddedDims(dims, quant);

  Aligned rows(static_cast<size_t>(count) * padded * superfaiss::ElementSize(quant));
  Aligned scales(cross ? static_cast<size_t>(count) * sizeof(float) : 0);
  if (!ReadInto(bank_dir + (cross ? "/int8.rows" : "/f32.rows"), &rows) ||
      (cross && !ReadInto(bank_dir + "/int8.scales", &scales))) {
    std::cout << "bank=unreadable\n";
    return 2;
  }
  superfaiss::BankView view;
  view.rows = rows.as<void>();
  view.scales = cross ? scales.as<float>() : nullptr;
  view.count = count;
  view.dims = dims;
  view.paddedDims = padded;
  view.quant = quant;
  view.metric = metric;
  int32_t bad = -1;
  Status status = superfaiss::ValidateBank(view);
  if (status == Status::Ok) status = superfaiss::ValidateBankData(view, &bad);
  std::cout << "load_" << mode << "=" << StatusName(status) << " bad_row=" << bad << "\n";
  if (status != Status::Ok) return 2;

  std::vector<unsigned char> query_bytes;
  if (!ReadFile(argv[8], &query_bytes) ||
      query_bytes.size() != static_cast<size_t>(query_count) * dims * sizeof(float)) {
    std::cout << "queries=size_mismatch\n";
    return 2;
  }
  superfaiss::QueryParams params;
  params.k = k;
  params.exactness = cross ? superfaiss::Exactness::CrossDevice : superfaiss::Exactness::PerDevice;
  superfaiss::Workspace workspace;
  // The query buffer is float32 in both modes (CrossDevice quantizes it
  // internally); it is padded to the BANK's paddedDims with zero lanes.
  Aligned query(static_cast<size_t>(padded) * sizeof(float));
  std::vector<superfaiss::Hit> hits(static_cast<size_t>(k));
  std::vector<unsigned char> out;
  out.reserve(static_cast<size_t>(query_count) * k * 8);
  for (int32_t q = 0; q < query_count; ++q) {
    std::memset(query.as<void>(), 0, query.size());
    std::memcpy(query.as<float>(), query_bytes.data() + static_cast<size_t>(q) * dims * sizeof(float),
                static_cast<size_t>(dims) * sizeof(float));
    int32_t got = 0;
    status = superfaiss::Query(view, query.as<float>(), params, workspace, hits.data(), &got);
    if (status != Status::Ok || got != k) {
      std::cout << "query=" << StatusName(status) << " index=" << q << " hits=" << got << "\n";
      return 2;
    }
    for (int32_t i = 0; i < k; ++i) {
      unsigned char record[8];
      std::memcpy(record, &hits[static_cast<size_t>(i)].index, 4);
      std::memcpy(record + 4, &hits[static_cast<size_t>(i)].score, 4);
      out.insert(out.end(), record, record + 8);
    }
  }
  if (!WriteFile(argv[10], out.data(), out.size())) {
    std::cout << "write=failed\n";
    return 2;
  }
  std::cout << "query_" << mode << "=Ok queries=" << query_count << " k=" << k << "\n";
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  static_assert(sizeof(float) == 4 && sizeof(int32_t) == 4, "record layout");
  if (argc < 2) return Usage();
  const std::string verb = argv[1];
  if (verb == "bake") return Bake(argc, argv);
  if (verb == "query") return QueryBank(argc, argv);
  return Usage();
}
