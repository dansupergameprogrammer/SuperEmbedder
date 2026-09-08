// src/superembedder/json_lite.cpp -- see json_lite.h for scope.
#include "json_lite.h"

#include <cctype>
#include <cstdio>

namespace semb::json {

namespace {

void WriteEscapedString(const std::string& s, std::string* out) {
  out->push_back('"');
  for (unsigned char c : s) {
    switch (c) {
      case '"': *out += "\\\""; break;
      case '\\': *out += "\\\\"; break;
      case '\b': *out += "\\b"; break;
      case '\f': *out += "\\f"; break;
      case '\n': *out += "\\n"; break;
      case '\r': *out += "\\r"; break;
      case '\t': *out += "\\t"; break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof(buf), "\\u%04x", c);
          *out += buf;
        } else {
          out->push_back(static_cast<char>(c));
        }
    }
  }
  out->push_back('"');
}

void WriteValue(const Value& v, std::string* out) {
  switch (v.kind) {
    case Kind::kNull:
      *out += "null";
      break;
    case Kind::kBool:
      *out += v.as_bool ? "true" : "false";
      break;
    case Kind::kInt:
      *out += std::to_string(v.as_int);
      break;
    case Kind::kString:
      WriteEscapedString(v.as_string, out);
      break;
    case Kind::kArray: {
      out->push_back('[');
      for (size_t i = 0; i < v.as_array.size(); ++i) {
        if (i) *out += ", ";
        WriteValue(v.as_array[i], out);
      }
      out->push_back(']');
      break;
    }
    case Kind::kObject: {
      out->push_back('{');
      for (size_t i = 0; i < v.as_object.size(); ++i) {
        if (i) *out += ", ";
        WriteEscapedString(v.as_object[i].first, out);
        *out += ": ";
        WriteValue(v.as_object[i].second, out);
      }
      out->push_back('}');
      break;
    }
  }
}

class ParserImpl {
 public:
  explicit ParserImpl(const std::string& text) : s_(text) {}

  Value Parse() {
    SkipWs();
    Value v = ParseValue();
    SkipWs();
    if (i_ != s_.size()) throw std::runtime_error("json_lite: trailing content after top-level value");
    return v;
  }

 private:
  const std::string& s_;
  size_t i_ = 0;

  char Peek() const {
    if (i_ >= s_.size()) throw std::runtime_error("json_lite: unexpected end of input");
    return s_[i_];
  }
  char Next() {
    char c = Peek();
    ++i_;
    return c;
  }
  void SkipWs() {
    while (i_ < s_.size()) {
      const char c = s_[i_];
      if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
        ++i_;
      } else {
        break;
      }
    }
  }
  void Expect(char c) {
    if (Next() != c) throw std::runtime_error(std::string("json_lite: expected '") + c + "'");
  }
  bool TryLiteral(const char* lit) {
    const size_t n = std::string(lit).size();
    if (s_.compare(i_, n, lit) == 0) {
      i_ += n;
      return true;
    }
    return false;
  }

  Value ParseValue() {
    SkipWs();
    const char c = Peek();
    if (c == '{') return ParseObject();
    if (c == '[') return ParseArray();
    if (c == '"') return Value::MakeString(ParseString());
    if (c == 't' || c == 'f') return ParseBool();
    if (c == 'n') {
      if (!TryLiteral("null")) throw std::runtime_error("json_lite: malformed literal");
      return Value();
    }
    return ParseNumber();
  }

  Value ParseObject() {
    Expect('{');
    Value v = Value::MakeObject();
    SkipWs();
    if (Peek() == '}') {
      ++i_;
      return v;
    }
    while (true) {
      SkipWs();
      std::string key = ParseString();
      SkipWs();
      Expect(':');
      Value val = ParseValue();
      v.as_object.emplace_back(std::move(key), std::move(val));
      SkipWs();
      const char c = Next();
      if (c == ',') continue;
      if (c == '}') break;
      throw std::runtime_error("json_lite: malformed object");
    }
    return v;
  }

  Value ParseArray() {
    Expect('[');
    Value v = Value::MakeArray();
    SkipWs();
    if (Peek() == ']') {
      ++i_;
      return v;
    }
    while (true) {
      v.as_array.push_back(ParseValue());
      SkipWs();
      const char c = Next();
      if (c == ',') continue;
      if (c == ']') break;
      throw std::runtime_error("json_lite: malformed array");
    }
    return v;
  }

  std::string ParseString() {
    Expect('"');
    std::string out;
    while (true) {
      const char c = Next();
      if (c == '"') break;
      if (c == '\\') {
        const char e = Next();
        switch (e) {
          case '"': out.push_back('"'); break;
          case '\\': out.push_back('\\'); break;
          case '/': out.push_back('/'); break;
          case 'b': out.push_back('\b'); break;
          case 'f': out.push_back('\f'); break;
          case 'n': out.push_back('\n'); break;
          case 'r': out.push_back('\r'); break;
          case 't': out.push_back('\t'); break;
          case 'u': {
            unsigned int cp = 0;
            for (int k = 0; k < 4; ++k) {
              const char h = Next();
              cp <<= 4;
              if (h >= '0' && h <= '9') cp |= static_cast<unsigned int>(h - '0');
              else if (h >= 'a' && h <= 'f') cp |= static_cast<unsigned int>(h - 'a' + 10);
              else if (h >= 'A' && h <= 'F') cp |= static_cast<unsigned int>(h - 'A' + 10);
              else throw std::runtime_error("json_lite: malformed \\u escape");
            }
            // Minimal UTF-8 encode of a BMP code point (this library's own
            // producer never writes ids containing astral-plane escapes;
            // a caller reading a hand-tampered manifest with one is
            // refused here rather than mis-decoded).
            if (cp <= 0x7F) {
              out.push_back(static_cast<char>(cp));
            } else if (cp <= 0x7FF) {
              out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
              out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
            } else {
              out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
              out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
              out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
            }
            break;
          }
          default:
            throw std::runtime_error("json_lite: malformed escape");
        }
      } else {
        out.push_back(c);
      }
    }
    return out;
  }

  Value ParseBool() {
    if (TryLiteral("true")) {
      Value v;
      v.kind = Kind::kBool;
      v.as_bool = true;
      return v;
    }
    if (TryLiteral("false")) {
      Value v;
      v.kind = Kind::kBool;
      v.as_bool = false;
      return v;
    }
    throw std::runtime_error("json_lite: malformed literal");
  }

  Value ParseNumber() {
    const size_t start = i_;
    if (i_ < s_.size() && s_[i_] == '-') ++i_;
    bool any_digit = false;
    while (i_ < s_.size() && std::isdigit(static_cast<unsigned char>(s_[i_]))) {
      ++i_;
      any_digit = true;
    }
    if (!any_digit) throw std::runtime_error("json_lite: malformed number");
    // This library's own producer never writes a fractional/exponent
    // number (every numeric field in the two documents it serves is an
    // integer); a '.' or 'e'/'E' here means the input is not a shape this
    // reader supports.
    if (i_ < s_.size() && (s_[i_] == '.' || s_[i_] == 'e' || s_[i_] == 'E')) {
      throw std::runtime_error("json_lite: non-integer numbers are not supported");
    }
    return Value::MakeInt(std::stoll(s_.substr(start, i_ - start)));
  }
};

}  // namespace

std::string Write(const Value& v) {
  std::string out;
  WriteValue(v, &out);
  return out;
}

Value Parse(const std::string& text) {
  ParserImpl p(text);
  return p.Parse();
}

}  // namespace semb::json
